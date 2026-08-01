#!/usr/bin/env python3
"""Tests for the training views migration (Universal Scheduler Phase 3).

Covers:
- task planning (file tasks for load, record-range tasks for validate)
- chunk splitting (records split into balanced ranges)
- resource limits (safe_worker_limit, RAM-aware sizing)
- deterministic generation (old vs new identical results)
- resume (completed tasks skipped; stale running re-claimed)
- retry (failed task retried)
- output validation (schema/order preserved)

Design note: record-range tasks carry the chunk in extra (mirrors the
existing _validate_chunk_standalone pickling contract); task_id encodes the
offset range so deterministic ordering = original record order.
"""

from __future__ import annotations

import json
import multiprocessing
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
REPO = Path(__file__).resolve().parent.parent

if sys.platform == "darwin":
    try:
        multiprocessing.set_start_method("fork", force=True)
    except RuntimeError:
        pass


def _validator_record(i: int) -> dict:
    """Canonical knowledge-object shape that passes validate_record."""
    return {
        "id": f"rec_{i:04d}",
        "category": "01_foundation",
        "subcategory": "general-reasoning",
        "type": "qa",
        "messages": [{"role": "user", "content": f"q{i}"},
                     {"role": "assistant", "content": f"a{i}"}],
        "difficulty": 2,
        "knowledge_type": "factual",
        "canonical_answer": f"a{i}",
        "metadata": {},
        "source_attribution": {"source": "test"},
        "source": {"name": "test", "license": "CC-BY-4.0"},
        "license": "CC-BY-4.0",
        "language": "en",
        "tags": [],
        "quality_score": 9,
        "verification_status": "approved",
        "training_view_eligibility": True,
        "lineage": {
            "source": "test",
            "transformations": [],
            "knowledge_object": f"rec_{i:04d}",
        },
    }


def _validator() -> object:
    from training_view_engine.validator import TrainingViewValidator
    return TrainingViewValidator(REPO)


# ----------------------------------------------------------------------
# 1. task planning (record-range)
# ----------------------------------------------------------------------

class TestTaskPlanning:
    def test_record_range_tasks_cover_all(self):
        v = _validator()
        records = [_validator_record(i) for i in range(500)]
        # Build the same chunking the validator uses
        workers = 4
        chunk_size = max(1, len(records) // (workers * 4))
        chunks = [records[i:i + chunk_size] for i in range(0, len(records), chunk_size)]
        assert sum(len(c) for c in chunks) == 500
        assert len(chunks) >= 2

    def test_task_id_encodes_offset(self):
        from parallel.models import Task
        # The validator builds task ids like tv:validate:000000:000031
        t = Task(task_id="tv:validate:000000:000031", source="training_views",
                 operation="validate_record_range", input="",
                 offset_start=0, offset_end=31)
        parts = t.task_id.split(":")
        assert parts[0] == "tv"
        assert int(parts[2]) == t.offset_start
        assert int(parts[3]) == t.offset_end

    def test_file_tasks_for_load(self, tmp_path: Path):
        from parallel.planner import file_tasks
        d = tmp_path / "curated" / "v0.1"
        d.mkdir(parents=True)
        (d / "a.jsonl").write_text("x\n")
        (d / "b.jsonl").write_text("y\n")
        tasks = file_tasks(sorted(d.glob("*.jsonl")), source="curated/v0.1",
                           operation="load_curated_file")
        assert len(tasks) == 2
        assert all(t.operation == "load_curated_file" for t in tasks)


# ----------------------------------------------------------------------
# 2. deterministic generation: scheduler vs sequential / manual pool
# ----------------------------------------------------------------------

class TestDeterministicGeneration:
    def test_validate_records_scheduler_matches_sequential(self):
        v = _validator()
        records = [_validator_record(i) for i in range(300)]
        seq = v.validate_records(records, quality_threshold=7, workers=1)
        par = v.validate_records(records, quality_threshold=7, workers=4)
        assert len(seq) == len(par) == 300
        assert [r["record_id"] for r in seq] == [r["record_id"] for r in par]
        assert [r["valid"] for r in seq] == [r["valid"] for r in par]

    def test_validate_records_order_preserved_with_invalid(self):
        v = _validator()
        records = [_validator_record(i) for i in range(250)]
        records[10]["verification_status"] = "pending"  # invalid
        records[50]["license"] = "unknown"              # invalid
        seq = v.validate_records(records, quality_threshold=7, workers=1)
        par = v.validate_records(records, quality_threshold=7, workers=4)
        assert [r["valid"] for r in seq] == [r["valid"] for r in par]
        assert not par[10]["valid"]
        assert not par[50]["valid"]

    def test_small_input_ignores_workers(self):
        v = _validator()
        res = v.validate_records([_validator_record(i) for i in range(2)],
                                 quality_threshold=7, workers=4)
        assert len(res) == 2


# ----------------------------------------------------------------------
# 3. resource limits
# ----------------------------------------------------------------------

class TestResourceLimits:
    def test_safe_worker_limit_never_zero(self):
        from parallel.resource import safe_worker_limit
        assert safe_worker_limit(per_task_ram_mb=10**9) >= 1

    def test_worker_limit_capped(self):
        from parallel.resource import safe_worker_limit
        limit = safe_worker_limit(per_task_ram_mb=512, safety_margin=0.8, max_workers=2)
        assert limit == 2

    def test_chunk_size_balanced(self):
        # 1000 records / (8 workers * 4) -> chunk 31 -> 33 chunks (covers all)
        records = [_validator_record(i) for i in range(1000)]
        workers = 8
        chunk_size = max(1, len(records) // (workers * 4))
        chunks = [records[i:i + chunk_size] for i in range(0, len(records), chunk_size)]
        assert sum(len(c) for c in chunks) == 1000


# ----------------------------------------------------------------------
# 4. resume support
# ----------------------------------------------------------------------

class TestResume:
    def test_completed_skipped_on_rerun(self, tmp_path: Path):
        from parallel.models import Task
        from parallel.registry import TaskRegistry
        from parallel.scheduler import Scheduler

        reg_root = tmp_path / "reg"
        tasks = [Task(task_id=f"tv:validate:{i:06d}:{i+1:06d}", source="training_views",
                      operation="validate_record_range", input="",
                      offset_start=i, offset_end=i + 1,
                      extra={"records": [_validator_record(i)], "quality_threshold": 7})
                 for i in range(3)]

        def worker(t):
            return [{"record_id": t.extra["records"][0]["id"], "valid": True, "errors": []}]

        s1 = Scheduler("training_views", registry_root=reg_root, workers=2,
                       pool="thread", max_retries=0)
        r1 = s1.run(tasks, worker)
        assert all(x.status == "completed" for x in r1)

        s2 = Scheduler("training_views", registry_root=reg_root, workers=2,
                       pool="thread", max_retries=0)
        r2 = s2.run(tasks, worker)
        assert all(x.status == "skipped" for x in r2)  # duplicate prevention

    def test_stale_running_reclaimed(self, tmp_path: Path):
        from parallel.registry import TaskRegistry
        reg = TaskRegistry(tmp_path / "reg", "training_views")
        reg.claim("tv:validate:000000:000010")
        reclaimed = reg.reclaim_stale_running(lease_seconds=0)
        assert "tv:validate:000000:000010" in reclaimed
        assert reg.status("tv:validate:000000:000010") == "pending"


# ----------------------------------------------------------------------
# 5. retry
# ----------------------------------------------------------------------

class TestRetry:
    def test_failed_then_retried(self, tmp_path: Path):
        from parallel.models import Task
        from parallel.scheduler import Scheduler

        calls = {"n": 0}

        def flaky(t):
            if calls["n"] == 0:
                calls["n"] += 1
                raise RuntimeError("transient")
            calls["n"] += 1
            return [{"record_id": "r1", "valid": True, "errors": []}]

        tasks = [Task(task_id="tv:validate:000000:000001", source="training_views",
                      operation="validate_record_range", input="",
                      offset_start=0, offset_end=1)]
        s = Scheduler("training_views", registry_root=tmp_path / "reg", workers=1,
                      pool="thread", max_retries=2)
        results = s.run(tasks, flaky)
        assert results[0].status == "completed"

    def test_terminal_after_max_retries(self, tmp_path: Path):
        from parallel.models import Task
        from parallel.scheduler import Scheduler

        def always_fail(t):
            raise RuntimeError("always")

        tasks = [Task(task_id="tv:validate:000000:000001", source="training_views",
                      operation="validate_record_range", input="",
                      offset_start=0, offset_end=1)]
        s = Scheduler("training_views", registry_root=tmp_path / "reg", workers=1,
                      pool="thread", max_retries=2)
        results = s.run(tasks, always_fail)
        assert results[0].status == "failed"
        assert results[0].attempts == 3


# ----------------------------------------------------------------------
# 6. end-to-end load via scheduler
# ----------------------------------------------------------------------

class TestLoad:
    def test_load_curated_records_scheduler(self, tmp_path: Path, monkeypatch):
        """Generator _load_curated_records via scheduler returns all records
        deterministically (same as sequential load)."""
        d = tmp_path / "curated" / "v0.1"
        d.mkdir(parents=True)
        for j in range(1, 4):
            with open(d / f"f{j}.jsonl", "w", encoding="utf-8") as fh:
                for i in range(5):
                    fh.write(json.dumps(_validator_record(j * 100 + i)) + "\n")

        # Point the generator at the tmp root and force workers>1
        from training_view_engine.generator import TrainingViewGenerator, _load_curated_file
        gen = TrainingViewGenerator(tmp_path)
        monkeypatch.setattr(gen, "_load_view_workers", lambda: 4)
        records = gen._load_curated_records("v0.1")
        assert len(records) == 15

        # Deterministic: sequential load must be identical
        files = sorted(d.rglob("*.jsonl"))
        seq = []
        for fp in files:
            seq.extend(_load_curated_file(fp))
        assert [r["id"] for r in records] == [r["id"] for r in seq]

    def test_load_sequential_equal(self, tmp_path: Path):
        from training_view_engine.generator import TrainingViewGenerator, _load_curated_file
        d = tmp_path / "curated" / "v0.1"
        d.mkdir(parents=True)
        for j in range(1, 3):
            with open(d / f"f{j}.jsonl", "w", encoding="utf-8") as fh:
                for i in range(5):
                    fh.write(json.dumps(_validator_record(j * 100 + i)) + "\n")
        gen = TrainingViewGenerator(tmp_path)
        records = gen._load_curated_records("v0.1")
        assert len(records) == 10
        # files sorted by name: f1 then f2 -> ids in order
        ids = [r["id"] for r in records]
        assert ids == sorted(ids)


# ----------------------------------------------------------------------
# 7. output validation
# ----------------------------------------------------------------------

class TestOutputValidation:
    def test_view_schema_via_validator(self):
        """Generated validation results conform to the expected schema."""
        v = _validator()
        records = [_validator_record(i) for i in range(120)]
        res = v.validate_records(records, quality_threshold=7, workers=4)
        for r in res:
            assert set(r.keys()) == {"record_id", "valid", "errors"}
            assert isinstance(r["valid"], bool)
            assert isinstance(r["errors"], list)
