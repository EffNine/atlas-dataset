#!/usr/bin/env python3
"""Tests for the extraction pipeline migration (Universal Scheduler Phase 2).

Covers:
- shard task planning (one shard = one task, deterministic ids)
- resume after failed shard (failed -> retry -> completed / terminal failed)
- deterministic merge (results sorted by task_id; registry skip on re-run)
- duplicate task prevention (completed tasks never re-run)
- partial output recovery (registry + lease re-claim)
- resource awareness (safe_worker_limit never exceeds RAM margin / caps)
- performance comparison: manual pool vs scheduler produce identical files
  and content hashes
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import subprocess
import sys
import tempfile
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

# Fake extraction script: writes a deterministic per-shard JSONL output.
# Output dir comes from ATLAS_FAKE_OUT env (tests must set it).
FAKE_EXTRACT = r'''#!/usr/bin/env python3
"""Fake extract script for scheduler tests (deterministic, no network)."""
import json, os, sys
shard = int(sys.argv[1])
out_dir = os.environ.get("ATLAS_FAKE_OUT", "raw/generated")
os.makedirs(out_dir, exist_ok=True)
recs = []
for i in range(5):
    recs.append({
        "id": f"fake_{shard:05d}_{i:07d}",
        "category": "test",
        "source": {"name": "fake", "license": "CC-BY-4.0"},
        "messages": [
            {"role": "user", "content": f"q {shard}-{i}"},
            {"role": "assistant", "content": f"a {shard}-{i}"},
        ],
        "difficulty": 2,
    })
with open(os.path.join(out_dir, f"fake_shard{shard}_atlas.jsonl"), "w") as f:
    for rec in recs:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
print(f"Fake articles: {len(recs)}")
'''


@pytest.fixture
def fake_env(tmp_path: Path, monkeypatch):
    """Create a fake extract script + raw/generated dir, chdir-safe."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "extract_fake.py").write_text(FAKE_EXTRACT)
    raw = tmp_path / "raw" / "generated"
    raw.mkdir(parents=True)
    monkeypatch.setenv("ATLAS_FAKE_OUT", str(raw))  # subprocess workers inherit
    return {"script": scripts / "extract_fake.py", "scripts": scripts, "raw": raw}


def _import_runner():
    """Import run_extract_all as a real module (picklable for process pools)."""
    import importlib
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    return importlib.import_module("run_extract_all")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ----------------------------------------------------------------------
# 1. shard task planning
# ----------------------------------------------------------------------

class TestShardPlanning:
    def test_one_shard_one_task(self, fake_env):
        mod = _import_runner()
        tasks = mod.plan_extraction_tasks("fake", 41, fake_env["scripts"])
        assert len(tasks) == 41
        assert all(t.operation == "extract_wiki_shard" for t in tasks)
        assert all(t.extra["shard"] == i for i, t in enumerate(tasks))
        assert all(t.input == str(fake_env["scripts"] / "extract_fake.py") for t in tasks)

    def test_task_ids_deterministic(self, fake_env):
        mod = _import_runner()
        a = mod.plan_extraction_tasks("fake", 5, fake_env["scripts"])
        b = mod.plan_extraction_tasks("fake", 5, fake_env["scripts"])
        assert [t.task_id for t in a] == [t.task_id for t in b]
        assert a[0].task_id == "extract:fake:000"


# ----------------------------------------------------------------------
# 2. resume after failed shard + retry
# ----------------------------------------------------------------------

class TestResumeAndRetry:
    def test_failed_shard_retried_then_completed(self, fake_env, monkeypatch, tmp_path: Path):
        """First attempt fails (missing output dir), retry succeeds."""
        mod = _import_runner()
        # Make the first invocation fail: remove raw/generated, then restore
        # before retry via a wrapper that fails once.
        calls = {"n": 0}
        original = mod.extract_task

        def flaky(task):
            if calls["n"] == 0:
                calls["n"] += 1
                raise RuntimeError("simulated shard failure")
            calls["n"] += 1
            return original(task)

        tasks = mod.plan_extraction_tasks("fake", 2, fake_env["scripts"])
        from parallel.scheduler import Scheduler

        sched = Scheduler("extraction", registry_root=tmp_path / "reg", workers=1,
                          pool="thread", max_retries=2)
        results = sched.run(tasks, flaky)
        completed = [r for r in results if r.status == "completed"]
        assert len(completed) == 2  # both eventually completed via retry

    def test_persistent_failure_terminal(self, fake_env, tmp_path: Path):
        mod = _import_runner()

        def always_fail(task):
            raise RuntimeError("always fails")

        tasks = mod.plan_extraction_tasks("fake", 1, fake_env["scripts"])
        from parallel.scheduler import Scheduler

        sched = Scheduler("extraction", registry_root=tmp_path / "reg", workers=1,
                          pool="thread", max_retries=2)
        results = sched.run(tasks, always_fail)
        assert results[0].status == "failed"
        assert results[0].attempts == 3  # 1 initial + 2 retries
        assert sched.registry.status("extract:fake:000") == "failed"


# ----------------------------------------------------------------------
# 3. deterministic merge + duplicate prevention
# ----------------------------------------------------------------------

class TestDeterministic:
    def test_results_sorted(self, fake_env, tmp_path: Path):
        mod = _import_runner()
        tasks = mod.plan_extraction_tasks("fake", 6, fake_env["scripts"])
        from parallel.scheduler import Scheduler

        sched = Scheduler("extraction", registry_root=tmp_path / "reg", workers=2,
                          pool="thread", max_retries=0)
        results = sched.run(tasks, mod.extract_task)
        ids = [r.task_id for r in results]
        assert ids == sorted(ids)
        assert len(results) == 6

    def test_rerun_skips_completed_no_duplicate(self, fake_env, tmp_path: Path):
        """Second run must skip all completed tasks (status='skipped')."""
        mod = _import_runner()
        tasks = mod.plan_extraction_tasks("fake", 3, fake_env["scripts"])
        from parallel.scheduler import Scheduler

        reg_root = tmp_path / "reg"
        s1 = Scheduler("extraction", registry_root=reg_root, workers=2, pool="thread", max_retries=0)
        r1 = s1.run(tasks, mod.extract_task)
        assert all(r.status == "completed" for r in r1)

        s2 = Scheduler("extraction", registry_root=reg_root, workers=2, pool="thread", max_retries=0)
        r2 = s2.run(tasks, mod.extract_task)
        assert all(r.status == "skipped" for r in r2)  # duplicate prevention


# ----------------------------------------------------------------------
# 4. partial output recovery
# ----------------------------------------------------------------------

class TestPartialRecovery:
    def test_stale_running_reclaimed(self, tmp_path: Path):
        from parallel.registry import TaskRegistry

        reg = TaskRegistry(tmp_path / "reg", "extraction")
        reg.claim("extract:fake:001")
        assert reg.status("extract:fake:001") == "running"
        reclaimed = reg.reclaim_stale_running(lease_seconds=0)
        assert "extract:fake:001" in reclaimed
        assert reg.status("extract:fake:001") == "pending"

    def test_scheduler_reruns_stale(self, fake_env, tmp_path: Path):
        """A task stuck 'running' (simulated crash) is re-claimed and re-runs."""
        mod = _import_runner()
        tasks = mod.plan_extraction_tasks("fake", 2, fake_env["scripts"])
        from parallel.registry import TaskRegistry
        from parallel.scheduler import Scheduler

        reg_root = tmp_path / "reg"
        # Simulate a crashed run: claim both tasks, leave them running.
        reg = TaskRegistry(reg_root, "extraction")
        reg.claim(tasks[0].task_id)
        reg.claim(tasks[1].task_id)

        # Scheduler with lease_seconds=0: stale running tasks are reclaimed
        # immediately, then re-run to completion.
        sched = Scheduler("extraction", registry_root=reg_root, workers=2,
                          pool="thread", max_retries=0, lease_seconds=0)
        results = sched.run(tasks, mod.extract_task)
        assert all(r.status == "completed" for r in results)


# ----------------------------------------------------------------------
# 5. resource awareness
# ----------------------------------------------------------------------

class TestResourceAwareness:
    def test_small_machine_low_ram_reduces_workers(self, monkeypatch):
        from parallel import resource

        monkeypatch.setattr(resource, "detect_ram", lambda: {"total_mb": 2048, "available_mb": 512, "used_mb": 1536})
        monkeypatch.setattr(resource, "detect_cpu", lambda: 16)
        limit = resource.safe_worker_limit(per_task_ram_mb=512, safety_margin=0.8)
        # 512 * 0.8 / 512 = 0.8 -> max(1, int(0.8)) = 1
        assert limit == 1

    def test_normal_devpc_profile(self):
        from parallel.config import get_hardware_profile, load_parallelism_config
        from parallel import resource

        cfg = load_parallelism_config()
        prof = get_hardware_profile(cfg, name="dev-pc")
        assert prof is not None
        limit = resource.safe_worker_limit(
            per_task_ram_mb=prof.get("per_task_ram_mb", 512),
            safety_margin=0.8,
            cpu_cap=prof.get("cpu_cores", 16),
        )
        assert 1 <= limit <= prof["cpu_cores"]

    def test_large_worker_profile_never_exceeds_cap(self, monkeypatch):
        from parallel import resource

        monkeypatch.setattr(resource, "detect_ram", lambda: {"total_mb": 262144, "available_mb": 200000, "used_mb": 62144})
        monkeypatch.setattr(resource, "detect_cpu", lambda: 64)
        # Even with huge RAM, explicit cap wins.
        limit = resource.safe_worker_limit(per_task_ram_mb=512, safety_margin=0.8, max_workers=10)
        assert limit == 10
        # CPU cap also respected.
        limit2 = resource.safe_worker_limit(per_task_ram_mb=512, safety_margin=0.8, cpu_cap=8)
        assert limit2 <= 8


# ----------------------------------------------------------------------
# 6. performance comparison: manual pool vs scheduler (identical output)
# ----------------------------------------------------------------------

class TestPerformanceComparison:
    def test_identical_outputs(self, fake_env, tmp_path: Path):
        """Manual ProcessPoolExecutor vs Universal Scheduler -> same files,
        same content hashes."""
        mod = _import_runner()
        mod.SCRIPT_DIR = fake_env["scripts"]  # manual path resolves scripts here
        tasks = mod.plan_extraction_tasks("fake", 4, fake_env["scripts"])

        # --- Before: manual ProcessPoolExecutor (reference) ---
        from concurrent.futures import ProcessPoolExecutor, as_completed
        old_fail = 0
        with ProcessPoolExecutor(max_workers=2) as ex:
            futures = {ex.submit(mod.extract_one, ("fake", t.extra["shard"])): t for t in tasks}
            for fut in as_completed(futures):
                _, shard, out = fut.result()
                if out.startswith("ERROR"):
                    old_fail += 1
        assert old_fail == 0

        old_files = {}
        for p in sorted((fake_env["raw"]).glob("fake_shard*_atlas.jsonl")):
            old_files[p.name] = _sha(p)
        assert len(old_files) == 4

        # --- After: Universal Scheduler (fresh output dir via env) ---
        new_raw = tmp_path / "raw2" / "generated"
        new_raw.mkdir(parents=True)
        import os
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setenv("ATLAS_FAKE_OUT", str(new_raw))
        try:
            from parallel.scheduler import Scheduler
            sched = Scheduler("extraction", registry_root=tmp_path / "reg", workers=2,
                              pool="process", max_retries=0)
            results = sched.run(tasks, mod.extract_task)
        finally:
            monkeypatch.undo()
        assert all(r.status == "completed" for r in results)

        new_files = {}
        for p in sorted(new_raw.glob("fake_shard*_atlas.jsonl")):
            new_files[p.name] = _sha(p)
        assert len(new_files) == 4
        assert new_files == old_files  # identical content

    def test_record_counts_match(self, fake_env, tmp_path: Path):
        mod = _import_runner()
        tasks = mod.plan_extraction_tasks("fake", 3, fake_env["scripts"])
        from parallel.scheduler import Scheduler

        sched = Scheduler("extraction", registry_root=tmp_path / "reg", workers=2,
                          pool="thread", max_retries=0)
        results = sched.run(tasks, mod.extract_task)
        assert len(results) == 3
        # Each fake shard emits 5 records; count lines in generated files.
        total = 0
        for p in fake_env["raw"].glob("fake_shard*_atlas.jsonl"):
            total += sum(1 for _ in open(p, encoding="utf-8"))
        assert total == 15
