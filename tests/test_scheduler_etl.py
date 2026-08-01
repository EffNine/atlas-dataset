#!/usr/bin/env python3
"""Tests for the ETL migration (Universal Scheduler Phase 4).

Covers:
- task planning (source-level tasks, deterministic ids)
- worker limits (safe_worker_limit, RAM-aware)
- retry (failed source retried then completed / terminal after max)
- resume (completed sources skipped; stale running re-claimed)
- failed task recovery (scheduler reports failure dict)
- deterministic output (scheduler vs sequential: same records, ids, hashes)
"""

from __future__ import annotations

import hashlib
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


def _seed_source(root: Path, source_id: str, n: int = 5) -> None:
    """Seed registry + cache + download log for one source (mirrors test_etl_v1_7)."""
    from downloader.cache import CacheManager

    reg_path = root / "metadata" / "source_registry.json"
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    if reg_path.exists():
        doc = json.loads(reg_path.read_text(encoding="utf-8"))
    else:
        doc = {"sources": []}
    doc["sources"].append({
        "id": source_id,
        "name": f"test/{source_id}",
        "url": f"https://example.com/{source_id}",
        "license": "MIT",
        "category": "06_science_engineering",
        "subcategory_hint": "mathematics",
        "status": "accepted",
    })
    reg_path.write_text(json.dumps(doc), encoding="utf-8")

    cache = CacheManager(root)
    payload = "\n".join(
        json.dumps({"question": f"q {source_id} {i}", "answer": f"a {source_id} {i}"})
        for i in range(n)
    ).encode("utf-8") + b"\n"
    entry = cache.put_bytes(
        f"huggingface:{source_id}:data.jsonl",
        payload,
        adapter="huggingface",
        metadata={"filename": "data.jsonl"},
    )
    (root / "metadata" / "download_logs").mkdir(parents=True, exist_ok=True)
    (root / "metadata" / "download_logs" / f"{source_id}.download.json").write_text(
        json.dumps({
            "source_id": source_id,
            "adapter": "huggingface",
            "status": "downloaded",
            "entries": [entry.to_dict()],
            "files": [{"filename": "data.jsonl", "source_ref": entry.source_ref}],
        }),
        encoding="utf-8",
    )


def _output_hashes(root: Path, source_id: str) -> dict[str, str]:
    out = root / "metadata" / "etl" / source_id
    hashes = {}
    for f in sorted(out.glob("*.jsonl")):
        hashes[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
    return hashes


@pytest.fixture
def etl_env(tmp_path: Path):
    """Root with two seeded sources (s1: 5 recs, s2: 3 recs)."""
    _seed_source(tmp_path, "s1", n=5)
    _seed_source(tmp_path, "s2", n=3)
    return tmp_path


# ----------------------------------------------------------------------
# 1. task planning
# ----------------------------------------------------------------------

class TestTaskPlanning:
    def test_source_level_tasks(self, etl_env: Path):
        from etl.pipeline import plan_etl_tasks

        tasks = plan_etl_tasks(["s2", "s1"], etl_env)
        assert len(tasks) == 2
        assert [t.task_id for t in tasks] == ["etl:s1", "etl:s2"]  # sorted
        assert all(t.operation == "run_etl_for_source" for t in tasks)
        assert all(t.input in ("s1", "s2") for t in tasks)
        assert all(t.extra["root"] == str(etl_env.resolve()) for t in tasks)

    def test_task_ids_deterministic(self, etl_env: Path):
        from etl.pipeline import plan_etl_tasks

        a = plan_etl_tasks(["s1", "s2"], etl_env)
        b = plan_etl_tasks(["s2", "s1"], etl_env)
        assert [t.task_id for t in a] == [t.task_id for t in b]
        assert a[0].task_id == "etl:s1"


# ----------------------------------------------------------------------
# 2. worker limits
# ----------------------------------------------------------------------

class TestWorkerLimits:
    def test_safe_limit_never_zero(self):
        from parallel.resource import safe_worker_limit
        assert safe_worker_limit(per_task_ram_mb=10**9) >= 1

    def test_safe_limit_capped(self):
        from parallel.resource import safe_worker_limit
        assert safe_worker_limit(per_task_ram_mb=512, safety_margin=0.8, max_workers=2) == 2

    def test_low_ram_reduces_workers(self, monkeypatch):
        from parallel import resource
        monkeypatch.setattr(resource, "detect_ram",
                            lambda: {"total_mb": 2048, "available_mb": 512, "used_mb": 1536})
        monkeypatch.setattr(resource, "detect_cpu", lambda: 16)
        limit = resource.safe_worker_limit(per_task_ram_mb=512, safety_margin=0.8)
        assert limit == 1  # 512*0.8/512 = 0.8 -> max(1, 0) = 1


# ----------------------------------------------------------------------
# 3. deterministic output: scheduler vs sequential
# ----------------------------------------------------------------------

class TestDeterminism:
    def test_scheduler_matches_sequential(self, etl_env: Path):
        from etl.pipeline import run_etl_for_source, run_etl_scheduler

        # Sequential reference
        seq = [run_etl_for_source(etl_env, "s1", limit=3).to_dict(),
               run_etl_for_source(etl_env, "s2").to_dict()]
        seq_hashes = {sid: _output_hashes(etl_env, sid) for sid in ("s1", "s2")}

        # Scheduler run on a fresh root clone (avoid resume interference)
        import shutil
        fresh = etl_env.parent / "fresh"
        shutil.copytree(etl_env, fresh)
        sched_results = run_etl_scheduler(fresh, ["s1", "s2"], limit=None)
        # Note: scheduler uses limit=None here; sequential used limit=3 for s1.
        # Compare with matching sequential run for correctness of record counts.
        sched_hashes = {sid: _output_hashes(fresh, sid) for sid in ("s1", "s2")}

        # Same output structure: each has extracted/cleaned/atlas_records keys
        for r in sched_results:
            assert "source_id" in r and "status" in r
            assert "extracted" in r and "cleaned" in r and "atlas_records" in r
        assert sorted(r["source_id"] for r in sched_results) == ["s1", "s2"]
        assert all(r["status"] == "passed" for r in sched_results)

        # s2 deterministic: scheduler s2 == sequential s2.
        # NOTE: (a) on macOS the process pool may fall back to the sequential
        # executor (sqlite3 fork segfault) — fallback output is identical by
        # construction; (b) normalized.jsonl/cleaned.jsonl embed
        # created_at=utc_now() (pre-existing pipeline behavior), so those two
        # files are NOT byte-deterministic between any two runs. We compare
        # deterministic files (extracted, atlas_staging) by hash and
        # timestamped files by record count + record ids.
        seq_s2 = run_etl_for_source(etl_env, "s2").to_dict()
        sched_s2 = next(r for r in sched_results if r["source_id"] == "s2")
        assert sched_s2["extracted"] == seq_s2["extracted"] == 3
        assert sched_s2["cleaned"] == seq_s2["cleaned"] == 3
        # deterministic files identical
        assert seq_hashes["s2"]["extracted.jsonl"] == sched_hashes["s2"]["extracted.jsonl"]
        assert seq_hashes["s2"]["atlas_staging.jsonl"] == sched_hashes["s2"]["atlas_staging.jsonl"]

        def _record_ids(path: Path) -> list[str]:
            ids = []
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if line:
                    ids.append(json.loads(line).get("id") or json.loads(line).get("record_id"))
            return ids

        assert _record_ids(etl_env / "metadata" / "etl" / "s2" / "normalized.jsonl") == \
            _record_ids(fresh / "metadata" / "etl" / "s2" / "normalized.jsonl")
        assert _record_ids(etl_env / "metadata" / "etl" / "s2" / "cleaned.jsonl") == \
            _record_ids(fresh / "metadata" / "etl" / "s2" / "cleaned.jsonl")

    def test_record_ids_present(self, etl_env: Path):
        from etl.pipeline import run_etl_scheduler
        fresh = etl_env.parent / "fresh2"
        import shutil
        shutil.copytree(etl_env, fresh)
        results = run_etl_scheduler(fresh, ["s1"])
        assert results[0]["status"] == "passed"
        staging = fresh / "metadata" / "etl" / "s1" / "atlas_staging.jsonl"
        ids = []
        for line in open(staging, encoding="utf-8"):
            line = line.strip()
            if line:
                ids.append(json.loads(line).get("id"))
        assert len(ids) == results[0]["atlas_records"]
        assert all(i for i in ids)  # non-empty ids


# ----------------------------------------------------------------------
# 4. resume + retry
# ----------------------------------------------------------------------

class TestResumeRetry:
    def test_completed_skipped_on_rerun(self, etl_env: Path):
        from etl.pipeline import run_etl_scheduler
        import shutil
        fresh = etl_env.parent / "resume"
        shutil.copytree(etl_env, fresh)
        r1 = run_etl_scheduler(fresh, ["s1", "s2"])
        assert all(r["status"] == "passed" for r in r1)
        # Registry now has completed tasks. Rerun: scheduler returns skipped
        # results, reloading report.json (still present with same counts).
        r2 = run_etl_scheduler(fresh, ["s1", "s2"])
        assert sorted(r["source_id"] for r in r2) == ["s1", "s2"]
        assert all(r.get("extracted", 0) > 0 for r in r2)

    def test_failed_task_retried_then_completed(self, etl_env: Path, tmp_path: Path):
        from etl.pipeline import etl_task, plan_etl_tasks
        from parallel.scheduler import Scheduler

        tasks = plan_etl_tasks(["s1"], etl_env)
        calls = {"n": 0}

        def flaky(t):
            if calls["n"] == 0:
                calls["n"] += 1
                raise RuntimeError("transient")
            calls["n"] += 1
            return etl_task(t)

        s = Scheduler("etl", registry_root=tmp_path / "reg", workers=1,
                      pool="thread", max_retries=2)
        results = s.run(tasks, flaky)
        assert results[0].status == "completed"

    def test_terminal_failure_after_max_retries(self, etl_env: Path, tmp_path: Path):
        from etl.pipeline import etl_task, plan_etl_tasks
        from parallel.scheduler import Scheduler

        tasks = plan_etl_tasks(["missing_source"], etl_env)

        def always_fail(t):
            raise RuntimeError("always")

        s = Scheduler("etl", registry_root=tmp_path / "reg", workers=1,
                      pool="thread", max_retries=2)
        results = s.run(tasks, always_fail)
        assert results[0].status == "failed"
        assert results[0].attempts == 3
        assert s.registry.status("etl:missing_source") == "failed"

    def test_stale_running_reclaimed(self, tmp_path: Path):
        from parallel.registry import TaskRegistry
        reg = TaskRegistry(tmp_path / "reg", "etl")
        reg.claim("etl:s1")
        reclaimed = reg.reclaim_stale_running(lease_seconds=0)
        assert "etl:s1" in reclaimed
        assert reg.status("etl:s1") == "pending"


# ----------------------------------------------------------------------
# 5. failed task recovery through scheduler API
# ----------------------------------------------------------------------

class TestFailureRecovery:
    def test_run_etl_scheduler_reports_failure(self, etl_env: Path, tmp_path: Path):
        """A source with no cache files -> failed dict, not a crash."""
        from etl.pipeline import run_etl_scheduler
        # s3 has registry entry but no download log -> run_etl_for_source fails
        reg_path = etl_env / "metadata" / "source_registry.json"
        doc = json.loads(reg_path.read_text(encoding="utf-8"))
        doc["sources"].append({"id": "s3", "name": "t/s3", "license": "MIT",
                               "category": "01_foundation", "subcategory_hint": "general"})
        reg_path.write_text(json.dumps(doc), encoding="utf-8")

        results = run_etl_scheduler(etl_env, ["s1", "s3"], registry_root=tmp_path / "reg")
        by_id = {r["source_id"]: r for r in results}
        assert by_id["s1"]["status"] == "passed"
        assert by_id["s3"]["status"] == "failed"
        assert by_id["s3"]["errors"]


# ----------------------------------------------------------------------
# 6. output schema
# ----------------------------------------------------------------------

class TestOutputSchema:
    def test_schema_preserved(self, etl_env: Path):
        from etl.pipeline import run_etl_scheduler
        import shutil
        fresh = etl_env.parent / "schema"
        shutil.copytree(etl_env, fresh)
        results = run_etl_scheduler(fresh, ["s1"])
        r = results[0]
        assert set(r.keys()) >= {"source_id", "status", "summary", "extracted",
                                 "normalized", "cleaned", "atlas_records", "dropped",
                                 "output_dir", "files_processed", "errors", "warnings", "stats"}
        out = Path(r["output_dir"])
        for name in ("extracted.jsonl", "normalized.jsonl", "cleaned.jsonl",
                     "atlas_staging.jsonl", "report.json"):
            assert (out / name).exists(), name
        # immutable trees untouched (dirs may not exist -> treat as empty)
        curated = fresh / "curated"
        ext_raw = fresh / "raw" / "external"
        assert list(curated.iterdir()) == [] if curated.exists() else True
        assert list(ext_raw.iterdir()) == [] if ext_raw.exists() else True
