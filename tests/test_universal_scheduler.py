#!/usr/bin/env python3
"""Tests for the Universal Scheduler (scripts/parallel/) + validation pilot.

Covers:
- config loading (yaml, env override, hardware profile)
- resource calculation (cpu/ram/disk, safe_worker_limit)
- worker limits (never exceed safety margin)
- task lifecycle (pending/running/completed/failed/retry)
- crash recovery (stale running re-claim, resume skips completed)
- deterministic ordering (results sorted by task_id)
- retry behaviour (failed tasks retried up to max_retries)
- validation comparison: old manual ProcessPoolExecutor vs scheduler
  produce identical record counts / failures / report output
"""

from __future__ import annotations

import json
import multiprocessing
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Ensure scripts/ is importable (repo layout: scripts/parallel, scripts/validate_dataset.py)
SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
REPO = Path(__file__).resolve().parent.parent

# ProcessPoolExecutor on macOS needs fork; on Linux the default is fork anyway.
if sys.platform == "darwin":
    try:
        multiprocessing.set_start_method("fork", force=True)
    except RuntimeError:
        pass


# ----------------------------------------------------------------------
# fixtures
# ----------------------------------------------------------------------

def _valid_record(i: int = 1) -> dict:
    """Curated-stage record shape (validates cleanly against validate_one_file)."""
    return {
        "id": f"test_{i:07d}",
        "category": "01_foundation",
        "subcategory": "general-reasoning",
        "type": "qa",
        "source": {"name": "test", "license": "CC-BY-4.0", "date": "2024-01-01"},
        "messages": [
            {"role": "system", "content": "You are Atlas, a precise and helpful AI assistant."},
            {"role": "user", "content": f"What is 2+2? (record {i})"},
            {"role": "assistant", "content": f"4 (record {i})"},
        ],
        "language": "en",
        "difficulty": 2,
        "tags": [],
        "quality_score": 8,
        "verified": True,
        "notes": "",
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


@pytest.fixture
def fixture_dir(tmp_path: Path) -> Path:
    """Three valid files + one file with a bad record."""
    d = tmp_path / "fixture"
    d.mkdir()
    _write_jsonl(d / "file_001.jsonl", [_valid_record(i) for i in range(1, 11)])
    _write_jsonl(d / "file_002.jsonl", [_valid_record(i) for i in range(11, 21)])
    _write_jsonl(d / "file_003.jsonl", [_valid_record(i) for i in range(21, 31)])
    # one malformed record
    with open(d / "file_004_bad.jsonl", "w", encoding="utf-8") as f:
        for i in range(1, 6):
            f.write(json.dumps(_valid_record(100 + i)) + "\n")
        f.write("{this is not json}\n")
    return d


def _worker_ok(task) -> dict:
    """Module-level scheduler worker: echo a deterministic result."""
    return {"task_id": task.task_id, "n": task.offset_end or 1}


def _worker_fail_once(task) -> dict:
    """Fail the first attempt, succeed on retry (module-level for pickling)."""
    n = getattr(_worker_fail_once, "_calls", 0) + 1
    _worker_fail_once._calls = n
    if n % 2 == 1:
        raise RuntimeError(f"transient {task.task_id}")
    return {"task_id": task.task_id, "ok": True}


def _worker_always_fail(task) -> dict:
    raise RuntimeError(f"always {task.task_id}")


# ----------------------------------------------------------------------
# 1. config loading
# ----------------------------------------------------------------------

class TestConfig:
    def test_load_defaults_when_missing(self, tmp_path: Path):
        from parallel.config import load_parallelism_config

        cfg = load_parallelism_config(tmp_path / "none.yaml")
        assert "parallelism" in cfg
        assert "validation" in cfg["parallelism"]

    def test_load_real_config(self):
        from parallel.config import load_parallelism_config

        cfg = load_parallelism_config()
        assert "validation" in cfg["parallelism"]

    def test_get_stage_config(self):
        from parallel.config import get_stage_config

        v = get_stage_config("validation")
        assert "file_workers" in v or "chunk_size" in v

    def test_env_override(self, monkeypatch):
        from parallel.config import env_override

        monkeypatch.setenv("ATLAS_WORKERS_VALIDATION", "3")
        assert env_override("validation") == 3
        monkeypatch.delenv("ATLAS_WORKERS_VALIDATION")
        assert env_override("validation") is None

    def test_resolve_worker_count_explicit(self):
        from parallel.config import resolve_worker_count

        assert resolve_worker_count("validation", explicit=5) == 5

    def test_resolve_worker_count_env(self, monkeypatch):
        from parallel.config import resolve_worker_count

        monkeypatch.setenv("ATLAS_WORKERS_VALIDATION", "7")
        assert resolve_worker_count("validation") == 7

    def test_hardware_profile_env(self, monkeypatch):
        from parallel.config import get_hardware_profile, load_parallelism_config

        cfg = load_parallelism_config()
        monkeypatch.setenv("ATLAS_PROFILE", "dev-pc")
        prof = get_hardware_profile(cfg)
        assert prof is not None and prof.get("profile") == "worker"


# ----------------------------------------------------------------------
# 2. resource calculation
# ----------------------------------------------------------------------

class TestResource:
    def test_detect_cpu(self):
        from parallel.resource import detect_cpu

        assert detect_cpu() >= 1

    def test_detect_ram_shape(self):
        from parallel.resource import detect_ram

        ram = detect_ram()
        assert ram["total_mb"] > 0
        assert ram["available_mb"] > 0
        assert ram["available_mb"] <= ram["total_mb"]

    def test_disk_free(self):
        from parallel.resource import disk_free

        assert disk_free(".") > 0

    def test_detect_gpu_placeholder(self):
        from parallel.resource import detect_gpu

        gpu = detect_gpu()
        assert "present" in gpu and "count" in gpu  # never crashes


# ----------------------------------------------------------------------
# 3. worker limits
# ----------------------------------------------------------------------

class TestWorkerLimits:
    def test_safe_worker_limit_min_1(self):
        from parallel.resource import safe_worker_limit

        assert safe_worker_limit(per_task_ram_mb=10**9) >= 1  # absurd RAM -> 1

    def test_safe_worker_limit_capped_by_cores(self):
        from parallel.resource import detect_cpu, safe_worker_limit

        cores = detect_cpu()
        limit = safe_worker_limit(per_task_ram_mb=1, safety_margin=1.0, cpu_cap=cores)
        assert 1 <= limit <= cores

    def test_safe_worker_limit_never_exceeds_max(self):
        from parallel.resource import safe_worker_limit

        limit = safe_worker_limit(per_task_ram_mb=512, safety_margin=0.8, max_workers=1)
        assert limit == 1

    def test_safe_worker_limit_respects_margin(self):
        from parallel.resource import detect_ram, safe_worker_limit

        ram = detect_ram()
        per_task = max(1, int(ram["available_mb"] // 2))  # only 2 workers fit
        limit = safe_worker_limit(per_task_ram_mb=per_task, safety_margin=0.8)
        # available * 0.8 / per_task <= 2 by construction
        assert limit <= 2


# ----------------------------------------------------------------------
# 4. task lifecycle
# ----------------------------------------------------------------------

class TestRegistry:
    def test_initial_pending(self, tmp_path: Path):
        from parallel.registry import TaskRegistry

        r = TaskRegistry(tmp_path, "stage")
        assert r.status("t1") == "pending"
        assert not r.is_completed("t1")

    def test_lifecycle_flow(self, tmp_path: Path):
        from parallel.registry import TaskRegistry

        r = TaskRegistry(tmp_path, "stage")
        assert r.claim("t1")
        assert r.status("t1") == "running"
        r.complete("t1", record_count=5)
        assert r.status("t1") == "completed"
        assert r.is_completed("t1")

    def test_terminal_blocks_transition(self, tmp_path: Path):
        from parallel.registry import RegistryError, TaskRegistry

        r = TaskRegistry(tmp_path, "stage")
        r.complete("t1")
        with pytest.raises(RegistryError):
            r.record("t1", "running")

    def test_claim_denied_when_completed(self, tmp_path: Path):
        from parallel.registry import TaskRegistry

        r = TaskRegistry(tmp_path, "stage")
        r.complete("t1")
        assert not r.claim("t1")

    def test_attempts_count(self, tmp_path: Path):
        from parallel.registry import TaskRegistry

        r = TaskRegistry(tmp_path, "stage")
        r.record("t1", "retry", error="a")
        r.record("t1", "retry", error="b")
        assert r.attempts("t1") == 2
        r.fail("t1", error="c")
        assert r.status("t1") == "failed"
        assert r.attempts("t1") == 3

    def test_summary(self, tmp_path: Path):
        from parallel.registry import TaskRegistry

        r = TaskRegistry(tmp_path, "stage")
        r.complete("a")
        r.complete("b")
        s = r.summary()
        assert s["completed"] == 2


# ----------------------------------------------------------------------
# 5. crash recovery
# ----------------------------------------------------------------------

class TestCrashRecovery:
    def test_resume_skips_completed(self, tmp_path: Path):
        from parallel.planner import file_tasks
        from parallel.scheduler import Scheduler

        d = tmp_path / "f"
        d.mkdir()
        (d / "a.jsonl").write_text("x\n")
        (d / "b.jsonl").write_text("y\n")
        tasks = file_tasks([d / "a.jsonl", d / "b.jsonl"], "s", "op")

        s1 = Scheduler("crash", registry_root=tmp_path / "reg", workers=2, pool="thread", max_retries=0)
        r1 = s1.run(tasks, _worker_ok)
        assert len(r1) == 2
        assert all(r.status == "completed" for r in r1)

        # Second run: same registry -> all skipped, results deterministic.
        s2 = Scheduler("crash", registry_root=tmp_path / "reg", workers=2, pool="thread", max_retries=0)
        r2 = s2.run(tasks, _worker_ok)
        assert len(r2) == 2
        assert all(r.status == "skipped" for r in r2)

    def test_reclaim_stale_running(self, tmp_path: Path):
        from parallel.registry import TaskRegistry

        r = TaskRegistry(tmp_path, "stage")
        r.claim("t1")
        assert r.status("t1") == "running"
        reclaimed = r.reclaim_stale_running(lease_seconds=0)  # immediate stale
        assert "t1" in reclaimed
        assert r.status("t1") == "pending"


# ----------------------------------------------------------------------
# 6. deterministic ordering
# ----------------------------------------------------------------------

class TestDeterministicOrdering:
    def test_results_sorted_by_task_id(self, tmp_path: Path):
        from parallel.planner import file_tasks
        from parallel.scheduler import Scheduler

        d = tmp_path / "f"
        d.mkdir()
        names = ["zzz.jsonl", "aaa.jsonl", "mmm.jsonl"]
        for n in names:
            (d / n).write_text("x\n")
        tasks = file_tasks([d / n for n in names], "s", "op")

        s = Scheduler("order", registry_root=tmp_path / "reg", workers=2, pool="thread", max_retries=0)
        results = s.run(tasks, _worker_ok)
        ids = [r.task_id for r in results]
        assert ids == sorted(ids)

    def test_task_ids_deterministic(self):
        from parallel.planner import file_tasks

        t1 = file_tasks(["a.jsonl"], "s", "op")
        t2 = file_tasks(["a.jsonl"], "s", "op")
        assert t1[0].task_id == t2[0].task_id


# ----------------------------------------------------------------------
# 7. retry behaviour
# ----------------------------------------------------------------------

class TestRetry:
    def test_failure_retried_and_succeeds(self, tmp_path: Path):
        from parallel.planner import file_tasks
        from parallel.scheduler import Scheduler

        _worker_fail_once._calls = 0  # reset
        d = tmp_path / "f"
        d.mkdir()
        (d / "a.jsonl").write_text("x\n")
        tasks = file_tasks([d / "a.jsonl"], "s", "op")

        s = Scheduler("retry", registry_root=tmp_path / "reg", workers=1, pool="thread", max_retries=2)
        results = s.run(tasks, _worker_fail_once)
        assert results[0].status == "completed"
        assert results[0].attempts >= 1

    def test_terminal_failure_after_max_retries(self, tmp_path: Path):
        from parallel.planner import file_tasks
        from parallel.scheduler import Scheduler

        d = tmp_path / "f"
        d.mkdir()
        (d / "a.jsonl").write_text("x\n")
        tasks = file_tasks([d / "a.jsonl"], "s", "op")

        s = Scheduler("retry", registry_root=tmp_path / "reg", workers=1, pool="thread", max_retries=2)
        results = s.run(tasks, _worker_always_fail)
        assert results[0].status == "failed"
        assert results[0].attempts == 3  # 1 initial + 2 retries
        reg = s.registry
        assert reg.status("s:op:a.jsonl") == "failed"


# ----------------------------------------------------------------------
# 8. validation comparison: old manual pool vs scheduler
# ----------------------------------------------------------------------

class TestValidationComparison:
    def test_scheduler_matches_manual_pool(self, fixture_dir: Path):
        """Same fixtures, same worker function -> identical stats."""
        from validate_dataset import validate_one_file, validate_task
        from parallel.planner import file_tasks
        from parallel.scheduler import Scheduler

        files = sorted(fixture_dir.glob("*.jsonl"))

        # OLD path: manual ProcessPoolExecutor (behavior reference).
        from concurrent.futures import ProcessPoolExecutor, as_completed
        old_results = []
        with ProcessPoolExecutor(max_workers=2) as ex:
            futures = {ex.submit(validate_one_file, p, False, True): p for p in files}
            for fut in as_completed(futures):
                old_results.append(fut.result())

        # NEW path: universal scheduler.
        tasks = file_tasks(files, source="validation", operation="validate_one_file",
                           extra={"strict": False, "quiet": True})
        sched = Scheduler(
            "validation", registry_root=str(tmp_path_reg := files[0].parent.parent / "reg"),
            workers=2, pool="process", max_retries=0,
        )
        trs = sched.run(tasks, validate_task)
        new_results = [r.result for r in trs if r.status == "completed"]

        # Same record counts / failures.
        old_totals = sorted(r["total"] for r in old_results)
        new_totals = sorted(r["total"] for r in new_results)
        assert old_totals == new_totals
        old_err = sorted(r["record_errors"] for r in old_results)
        new_err = sorted(r["record_errors"] for r in new_results)
        assert old_err == new_err
        old_bad = sorted(r["bad_json"] for r in old_results)
        new_bad = sorted(r["bad_json"] for r in new_results)
        assert old_bad == new_bad

    def test_cli_uses_scheduler_on_glob(self, tmp_path: Path):
        """CLI end-to-end: scheduler path produces the same PASS summary."""
        d = tmp_path / "fx"
        d.mkdir()
        for i in range(1, 4):
            _write_jsonl(d / f"f{i}.jsonl", [_valid_record(i) for i in range(1, 6)])
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "validate_dataset.py"),
             "--input", str(d / "*.jsonl"), "--file-workers", "2", "--quiet"],
            capture_output=True, text=True, cwd=str(REPO), timeout=120,
        )
        out = r.stdout + r.stderr
        assert r.returncode == 0, out
        assert "RESULT: PASS" in out
        assert "scheduler" in out  # scheduler path was exercised


# ----------------------------------------------------------------------
# 9. planner
# ----------------------------------------------------------------------

class TestPlanner:
    def test_file_tasks(self, tmp_path: Path):
        from parallel.planner import file_tasks

        p = tmp_path / "a.jsonl"
        p.write_text("x\n")
        tasks = file_tasks([p], "s", "op")
        assert len(tasks) == 1
        assert tasks[0].operation == "op"
        assert tasks[0].offset_start is None  # whole-file task

    def test_byte_range_splits_large_file(self, tmp_path: Path):
        from parallel.planner import byte_range_tasks

        p = tmp_path / "big.jsonl"
        with open(p, "w") as f:
            for i in range(1000):
                f.write(json.dumps({"id": i}) + "\n")
        # Force split with tiny targets (file is ~0.011 MB).
        tasks = byte_range_tasks(p, "s", "op", target_size_mb=0.001, min_split_mb=0.001)
        assert len(tasks) >= 2
        offsets = sorted((t.offset_start, t.offset_end) for t in tasks)
        assert offsets[0][0] == 0
        assert offsets[-1][1] == 1000
        # contiguous
        assert all(a[1] == b[0] for a, b in zip(offsets, offsets[1:]))

    def test_byte_range_small_file_no_split(self, tmp_path: Path):
        from parallel.planner import byte_range_tasks

        p = tmp_path / "small.jsonl"
        p.write_text("x\n")
        tasks = byte_range_tasks(p, "s", "op", target_size_mb=64, min_split_mb=128)
        assert len(tasks) == 1
