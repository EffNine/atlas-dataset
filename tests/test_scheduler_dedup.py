#!/usr/bin/env python3
"""Tests for the release-dedup migration (Universal Scheduler Phase 7B).

Covers:
- deterministic task identity (dedup:<release>:<category>)
- release isolation (dedup:RC1:cat != dedup:RC2:cat)
- task planning (one category = one task; missing source skipped)
- fixed worker limit (D2: release.dedup_workers = 4, never auto)
- scheduler vs legacy output identity (SHA-256 per deduplicated file)
- registry stage `dedup` write (task_registry_dedup.jsonl)
- resume (registry-completed tasks skipped; new category still runs)
- retry (worker failure retried then completed / terminal after max)
- fallback (kill-switch + original executor path, identical output)
- CLI --jobs 1 legacy sequential compatibility (byte-identical)

Run (from repo root):
  python3 -m pytest tests/test_scheduler_dedup.py -v
"""

from __future__ import annotations

import json
import multiprocessing
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
SCRIPTS_RELEASE = SCRIPTS / "release"
# scripts/release first so `common` / `dedup_release` / `scheduler_tasks`
# resolve there (bare module names, matching the pipeline's own imports);
# scripts second so `parallel.*` is importable for the scheduler path.
for _p in (SCRIPTS_RELEASE, SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

if sys.platform == "darwin":
    try:
        multiprocessing.set_start_method("fork", force=True)
    except RuntimeError:
        pass

import dedup_release  # noqa: E402
from common import CATEGORIES, count_jsonl_zst, open_zstd_writer, sha256_file  # noqa: E402
import scheduler_tasks as st  # noqa: E402
from scheduler_tasks import (  # noqa: E402
    dedup_task_id,
    plan_dedup_tasks,
    resolve_dedup_workers,
    run_dedup_scheduler,
)

RELEASE = "v1.0-RC2"

# Fixture totals (see _make_source):
#   01_foundation             : 7 lines  -> kept 5, dropped 2
#   02_software_engineering   : 5 lines  -> kept 4, dropped 1
#   06_science_engineering    : 3 lines  -> kept 3, dropped 0
EXPECT_TOTAL = 12
EXPECT_SOFTWARE = 4
TOTAL_IN = 15
TOTAL_DROPPED = 3


# --------------------------------------------------------------------------
# Fixtures / helpers
# --------------------------------------------------------------------------

def _rec(cat: str, sub: str, i: int) -> dict:
    return {
        "id": f"ph7b_{cat.split('_')[0]}_{i:05d}",
        "category": cat,
        "subcategory": sub,
        "type": "instruction",
        "source": {
            "name": f"source-{cat}",
            "url": "https://example.invalid/source",
            "license": "MIT",
            "date": "2026-01-01",
        },
        "messages": [
            {"role": "user", "content": f"Question {i} about {sub}?"},
            {"role": "assistant", "content": f"Answer {i} with detail."},
        ],
        "language": "en",
        "difficulty": 2,
        "tags": ["test", cat],
        "quality_score": 8,
        "verified": True,
        "notes": "",
    }


def _write_category(dataset: Path, cat: str, n: int, dup_ids: list[int]) -> None:
    """Write <cat>/<cat>.jsonl.zst with n unique records + byte-identical dups."""
    out = dataset / cat / f"{cat}.jsonl.zst"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open_zstd_writer(out, level=19) as w:
        for i in range(n):
            w.write(json.dumps(_rec(cat, f"sub-{cat}-{i}", i)).encode("utf-8") + b"\n")
        for i in dup_ids:
            # Byte-identical duplicate of an earlier line.
            w.write(json.dumps(_rec(cat, f"sub-{cat}-{i}", i)).encode("utf-8") + b"\n")


def _make_source(tmp_path: Path, rel: str = "v1.0-RC1") -> Path:
    """Build a 3-category source release; returns <root>/releases/<rel>/dataset."""
    dataset = tmp_path / "releases" / rel / "dataset"
    _write_category(dataset, "01_foundation", 5, [0, 1])
    _write_category(dataset, "02_software_engineering", 4, [2])
    _write_category(dataset, "06_science_engineering", 3, [])
    return dataset


def _make_jobs(src_dataset: Path, dst_dataset: Path, cats=("01_foundation", "02_software_engineering", "06_science_engineering")):
    jobs = []
    for cat in cats:
        src = src_dataset / cat / f"{cat}.jsonl.zst"
        if not src.exists():
            continue
        jobs.append((cat, src, dst_dataset / cat / f"{cat}.jsonl.zst"))
    return jobs


def _out_hashes(out_root: Path) -> dict[str, str]:
    """SHA-256 of every deduplicated output file, keyed by relative path."""
    hashes = {}
    for f in sorted(Path(out_root).rglob("*.jsonl.zst")):
        hashes[str(f.relative_to(out_root))] = sha256_file(f)
    return hashes


def _legacy_run(src_dataset: Path, dst_dataset: Path) -> tuple[dict, dict]:
    """The legacy sequential executor (shared worker), byte-identical output."""
    jobs = _make_jobs(src_dataset, dst_dataset)
    per_category, totals = dedup_release._dedup_sequential(jobs)
    assert totals["total_kept"] == EXPECT_TOTAL
    return per_category, totals


# --------------------------------------------------------------------------
# 1. task planning
# --------------------------------------------------------------------------

class TestTaskPlanning:
    def test_task_ids_deterministic(self, tmp_path: Path):
        src = _make_source(tmp_path)
        dst = tmp_path / "releases" / RELEASE / "dataset"
        jobs = _make_jobs(src, dst)
        a = plan_dedup_tasks(jobs, RELEASE)
        b = plan_dedup_tasks(list(reversed(jobs)), RELEASE)
        assert [t.task_id for t in a] == [t.task_id for t in b]
        # Sorted by category: 01_foundation < 02_software_engineering < ...
        assert a[0].task_id == f"dedup:{RELEASE}:01_foundation"
        assert a[1].task_id == f"dedup:{RELEASE}:02_software_engineering"
        assert a[2].task_id == f"dedup:{RELEASE}:06_science_engineering"

    def test_release_scoped_ids(self, tmp_path: Path):
        """Same category under two releases -> distinct task ids (release isolation)."""
        src = _make_source(tmp_path)
        dst = tmp_path / "releases" / RELEASE / "dataset"
        jobs = _make_jobs(src, dst)
        tasks_rc1 = plan_dedup_tasks(jobs, "v1.0-RC1")
        tasks_rc2 = plan_dedup_tasks(jobs, "v1.0-RC2")
        assert tasks_rc1[0].task_id == "dedup:v1.0-RC1:01_foundation"
        assert tasks_rc2[0].task_id == "dedup:v1.0-RC2:01_foundation"
        assert {t.task_id for t in tasks_rc1}.isdisjoint({t.task_id for t in tasks_rc2})

    def test_dedup_vs_compress_no_collision(self, tmp_path: Path):
        """dedup ids never collide with the compression stage ids (same registry family)."""
        src = _make_source(tmp_path)
        jobs = _make_jobs(src, tmp_path / "releases" / RELEASE / "dataset")
        tasks = plan_dedup_tasks(jobs, RELEASE)
        assert all(t.task_id.startswith(f"dedup:{RELEASE}:") for t in tasks)
        assert not any(t.task_id.startswith("compress:") for t in tasks)

    def test_task_payload(self, tmp_path: Path):
        src = _make_source(tmp_path)
        dst = tmp_path / "releases" / RELEASE / "dataset"
        jobs = _make_jobs(src, dst)
        tasks = plan_dedup_tasks(jobs, RELEASE)
        t = tasks[0]
        assert t.source == "release"
        assert t.operation == "dedup"
        assert t.input == str(src / "01_foundation" / "01_foundation.jsonl.zst")
        assert t.extra["category"] == "01_foundation"
        assert t.extra["release"] == RELEASE
        assert t.extra["source"] == t.input
        assert t.extra["target"] == str(dst / "01_foundation" / "01_foundation.jsonl.zst")
        assert t.estimated_size_mb > 0

    def test_missing_source_skipped_at_plan_time(self, tmp_path: Path):
        src = _make_source(tmp_path)
        dst = tmp_path / "releases" / RELEASE / "dataset"
        # Only 01_foundation exists in the source -> 1 task.
        jobs = _make_jobs(src, dst, cats=("01_foundation",))
        tasks = plan_dedup_tasks(jobs, RELEASE)
        assert [t.task_id for t in tasks] == [f"dedup:{RELEASE}:01_foundation"]


# --------------------------------------------------------------------------
# 2. worker limit (D2)
# --------------------------------------------------------------------------

class TestWorkerLimit:
    def test_fixed_default_four(self):
        """D2: fixed limit 4 from config release.dedup_workers — no auto."""
        assert resolve_dedup_workers() == 4

    def test_explicit_cli_override_wins(self):
        assert resolve_dedup_workers(2) == 2
        assert resolve_dedup_workers(8) == 8

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("ATLAS_WORKERS_RELEASE", "6")
        assert resolve_dedup_workers() == 6
        # Explicit still beats env.
        assert resolve_dedup_workers(3) == 3

    def test_never_auto(self, monkeypatch):
        """Even if config says 'auto', dedup falls back to the fixed 4."""
        import parallel.config as pcfg
        monkeypatch.setattr(
            pcfg, "get_stage_config",
            lambda stage, cfg=None: {"dedup_workers": "auto"} if stage == "release" else {},
        )
        assert resolve_dedup_workers() == 4


# --------------------------------------------------------------------------
# 3. determinism: scheduler vs legacy (SHA-256 identical)
# --------------------------------------------------------------------------

class TestDeterminism:
    def test_output_identical_scheduler_vs_legacy(self, tmp_path: Path):
        src = _make_source(tmp_path)
        dst_legacy = tmp_path / "releases" / "legacy" / "dataset"
        dst_sched = tmp_path / "releases" / RELEASE / "dataset"

        per_category_legacy, _ = _legacy_run(src, dst_legacy)
        jobs_sched = _make_jobs(src, dst_sched)
        per_category_sched, totals, skipped, failures = run_dedup_scheduler(
            jobs_sched, RELEASE, workers=2, registry_root=tmp_path / "reg",
        )
        assert not failures
        assert skipped == 0
        assert totals["total_kept"] == EXPECT_TOTAL
        assert totals["total_in"] == TOTAL_IN
        assert totals["total_dropped"] == TOTAL_DROPPED
        assert totals["total_conflicts"] == 0
        assert set(per_category_sched) == set(per_category_legacy)

        # Every deduplicated output file byte-identical.
        assert _out_hashes(dst_legacy) == _out_hashes(dst_sched)

        # Per-category stats identical (the worker returns the same dict the
        # legacy loop builds; no scheduler-only alias leaks into the report).
        for cat, stats in per_category_sched.items():
            assert stats == per_category_legacy[cat]
            assert "total" not in stats

    def test_conflict_detection_unchanged(self, tmp_path: Path):
        """A non-byte-identical duplicate is kept + flagged (never dropped)."""
        from common import open_zstd_reader

        cat = "01_foundation"
        src = tmp_path / "releases" / "v1.0-RC1" / "dataset"
        out = src / cat / f"{cat}.jsonl.zst"
        out.parent.mkdir(parents=True, exist_ok=True)
        rec = _rec(cat, "conflict", 0)
        with open_zstd_writer(out, level=19) as w:
            w.write(json.dumps(rec).encode("utf-8") + b"\n")
            rec2 = dict(rec)
            rec2["quality_score"] = 7  # same id, different bytes
            w.write(json.dumps(rec2).encode("utf-8") + b"\n")

        dst = tmp_path / "releases" / RELEASE / "dataset"
        jobs = [(cat, out, dst / cat / f"{cat}.jsonl.zst")]
        per_category, totals, skipped, failures = run_dedup_scheduler(
            jobs, RELEASE, workers=2, registry_root=tmp_path / "reg",
        )
        assert not failures
        stats = per_category[cat]
        assert stats["kept"] == 2
        assert stats["dropped"] == 0
        assert stats["conflicts"] == 1
        assert stats["conflict_sample"] == [rec["id"]]
        # Both conflicting lines written to output (2 records, 1 unique id).
        assert count_jsonl_zst(dst / cat / f"{cat}.jsonl.zst") == 2

    def test_cli_jobs1_vs_scheduler_identity(self, tmp_path: Path):
        """End-to-end: --jobs 1 (legacy sequential) vs scheduler -> identical.

        Two identical root trees so both paths produce the SAME target
        release name; only the per-category outputs and report semantics
        are compared (input/output paths necessarily differ).
        """
        reg = tmp_path / "reg"
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setenv("ATLAS_REGISTRY_ROOT", str(reg))

        root_a = tmp_path / "a"
        root_b = tmp_path / "b"
        _make_source(root_a)
        _make_source(root_b)

        rc1 = dedup_release.main([
            "--root", str(root_a),
            "--source", "v1.0-RC1",
            "--target", "v1.0-RC2",
            "--jobs", "1",
            "--skip-sign",
            "--expect-total", str(EXPECT_TOTAL),
            "--expect-software", str(EXPECT_SOFTWARE),
            "--report", str(tmp_path / "rep_legacy.json"),
        ])
        assert rc1 == 0
        rc2 = dedup_release.main([
            "--root", str(root_b),
            "--source", "v1.0-RC1",
            "--target", "v1.0-RC2",
            "--jobs", "2",
            "--skip-sign",
            "--expect-total", str(EXPECT_TOTAL),
            "--expect-software", str(EXPECT_SOFTWARE),
            "--report", str(tmp_path / "rep_sched.json"),
        ])
        assert rc2 == 0

        out_legacy = root_a / "releases" / "v1.0-RC2" / "dataset"
        out_sched = root_b / "releases" / "v1.0-RC2" / "dataset"
        assert _out_hashes(out_legacy) == _out_hashes(out_sched)

        def _report(p: Path) -> dict:
            rep = json.loads(p.read_text(encoding="utf-8"))
            for k in ("generated_at", "elapsed_s", "input", "output"):
                rep.pop(k, None)
            return rep

        assert _report(tmp_path / "rep_legacy.json") == _report(tmp_path / "rep_sched.json")
        monkeypatch.undo()


# --------------------------------------------------------------------------
# 4. registry + resume
# --------------------------------------------------------------------------

class TestResume:
    def test_registry_stage_key(self, tmp_path: Path):
        """D1: stage key `dedup` -> task_registry_dedup.jsonl."""
        src = _make_source(tmp_path)
        dst = tmp_path / "releases" / RELEASE / "dataset"
        jobs = _make_jobs(src, dst)
        reg = tmp_path / "reg"
        run_dedup_scheduler(jobs, RELEASE, workers=2, registry_root=reg)
        assert (reg / "task_registry_dedup.jsonl").exists()

    def test_resume_skips_completed(self, tmp_path: Path):
        src = _make_source(tmp_path)
        dst = tmp_path / "releases" / RELEASE / "dataset"
        jobs = _make_jobs(src, dst)
        reg = tmp_path / "reg"

        per_category1, _, s1, f1 = run_dedup_scheduler(
            jobs, RELEASE, workers=2, registry_root=reg)
        assert len(per_category1) == 3 and s1 == 0 and not f1
        hashes_before = _out_hashes(dst)

        # Second run: registry says completed -> nothing re-runs, outputs untouched.
        per_category2, _, s2, f2 = run_dedup_scheduler(
            jobs, RELEASE, workers=2, registry_root=reg)
        assert per_category2 == {}
        assert s2 == 3
        assert not f2
        assert _out_hashes(dst) == hashes_before

    def test_new_category_runs_after_resume(self, tmp_path: Path):
        src = _make_source(tmp_path)
        dst = tmp_path / "releases" / RELEASE / "dataset"
        jobs = _make_jobs(src, dst)
        reg = tmp_path / "reg"
        run_dedup_scheduler(jobs, RELEASE, workers=2, registry_root=reg)

        # A new category appears in the source -> only it runs.
        _write_category(src, "08_creative_knowledge", 2, [])
        jobs2 = _make_jobs(src, dst, cats=(
            "01_foundation", "02_software_engineering", "06_science_engineering",
            "08_creative_knowledge",
        ))
        per_category3, totals3, s3, f3 = run_dedup_scheduler(
            jobs2, RELEASE, workers=2, registry_root=reg)
        assert set(per_category3) == {"08_creative_knowledge"}
        assert s3 == 3
        assert not f3
        assert totals3["total_kept"] == 2
        assert count_jsonl_zst(dst / "08_creative_knowledge" / "08_creative_knowledge.jsonl.zst") == 2

    def test_cross_release_no_collision(self, tmp_path: Path):
        """Release B after release A completes -> B's tasks are distinct (R2)."""
        src = _make_source(tmp_path)
        dst = tmp_path / "releases" / RELEASE / "dataset"
        jobs = _make_jobs(src, dst)
        reg = tmp_path / "reg"
        per_category1, _, s1, _ = run_dedup_scheduler(
            jobs, "v1.0-RC1", workers=2, registry_root=reg)
        assert len(per_category1) == 3 and s1 == 0
        per_category2, _, s2, _ = run_dedup_scheduler(
            jobs, "v1.0-RC2", workers=2, registry_root=reg)
        assert len(per_category2) == 3 and s2 == 0


# --------------------------------------------------------------------------
# 5. retry
# --------------------------------------------------------------------------

class TestRetry:
    def test_retry_then_completed(self, tmp_path: Path):
        from parallel.scheduler import Scheduler

        src = _make_source(tmp_path)
        dst = tmp_path / "releases" / RELEASE / "dataset"
        # Single category so the counter is unambiguous: 1 failure + 1 success.
        jobs = _make_jobs(src, dst, cats=("01_foundation",))
        tasks = plan_dedup_tasks(jobs, RELEASE)
        calls = {"n": 0}

        def flaky(t):
            if calls["n"] == 0:
                calls["n"] += 1
                raise RuntimeError("transient worker failure")
            calls["n"] += 1
            return st.dedup_task(t)

        s = Scheduler("dedup", registry_root=tmp_path / "reg", workers=1,
                      pool="thread", max_retries=2)
        results = s.run(tasks, flaky)
        assert results[0].status == "completed"
        assert calls["n"] == 2

    def test_terminal_failure_after_max_retries(self, tmp_path: Path):
        from parallel.scheduler import Scheduler

        src = _make_source(tmp_path)
        dst = tmp_path / "releases" / RELEASE / "dataset"
        jobs = _make_jobs(src, dst)
        tasks = plan_dedup_tasks(jobs, RELEASE)

        def always_fail(t):
            raise RuntimeError("always fails")

        s = Scheduler("dedup", registry_root=tmp_path / "reg", workers=1,
                      pool="thread", max_retries=2)
        results = s.run(tasks, always_fail)
        assert results[0].status == "failed"
        assert results[0].attempts == 3
        assert s.registry.status(f"dedup:{RELEASE}:01_foundation") == "failed"

    def test_run_surfaces_terminal_failure(self, tmp_path: Path):
        """A corrupt category raises in the worker -> retried -> terminal failure entry."""
        src = _make_source(tmp_path)
        dst = tmp_path / "releases" / RELEASE / "dataset"
        # Corrupt 04_ai_machine_learning source (exists, but not zstd).
        bad = src / "04_ai_machine_learning" / "04_ai_machine_learning.jsonl.zst"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_bytes(b"not-zstd-garbage")
        jobs = _make_jobs(src, dst, cats=(
            "01_foundation", "02_software_engineering", "04_ai_machine_learning",
            "06_science_engineering",
        ))

        per_category, totals, skipped, failures = run_dedup_scheduler(
            jobs, RELEASE, workers=2, registry_root=tmp_path / "reg")
        assert len(per_category) == 3  # good categories completed
        assert totals["total_kept"] == EXPECT_TOTAL
        assert len(failures) == 1
        assert failures[0]["category"] == "04_ai_machine_learning"
        assert failures[0]["errors"]


# --------------------------------------------------------------------------
# 6. fallback
# --------------------------------------------------------------------------

class TestFallback:
    def test_kill_switch_forces_sequential(self, tmp_path: Path, monkeypatch):
        src = _make_source(tmp_path)
        dst = tmp_path / "releases" / RELEASE / "dataset"
        jobs = _make_jobs(src, dst)
        monkeypatch.setattr(st, "_SCHEDULER_ENABLED", False)

        per_category, totals, skipped, failures = run_dedup_scheduler(
            jobs, RELEASE, workers=2, registry_root=tmp_path / "reg")
        assert not failures
        assert skipped == 0
        assert totals["total_kept"] == EXPECT_TOTAL
        # No registry written by the fallback path.
        assert not (tmp_path / "reg" / "task_registry_dedup.jsonl").exists()
        # Fallback output is byte-identical to the shared legacy worker.
        legacy = tmp_path / "legacy"
        _legacy_run(src, legacy)
        assert _out_hashes(dst) == _out_hashes(legacy)

    def test_outer_fallback_original_loop(self, tmp_path: Path, monkeypatch):
        """Blocking scheduler_tasks import -> dedup_release's ORIGINAL loop."""
        src = _make_source(tmp_path)
        monkeypatch.setitem(sys.modules, "scheduler_tasks", None)

        rc = dedup_release.main([
            "--root", str(tmp_path),
            "--source", "v1.0-RC1",
            "--target", "v1.0-RC2",
            "--jobs", "2",
            "--skip-sign",
            "--expect-total", str(EXPECT_TOTAL),
            "--expect-software", str(EXPECT_SOFTWARE),
            "--report", str(tmp_path / "rep.json"),
        ])
        assert rc == 0
        rep = json.loads((tmp_path / "rep.json").read_text(encoding="utf-8"))
        assert rep["statistics"]["total_kept"] == EXPECT_TOTAL
        assert rep["statistics"]["total_dropped"] == TOTAL_DROPPED
        assert rep["validation"]["all_ok"] is True


# --------------------------------------------------------------------------
# 7. worker purity (no shared writes)
# --------------------------------------------------------------------------

class TestWorkerPurity:
    def test_dedup_task_returns_data_only(self, tmp_path: Path):
        """The worker never writes manifest/stats/checksum/registry files."""
        src = _make_source(tmp_path)
        dst = tmp_path / "releases" / RELEASE / "dataset"
        jobs = _make_jobs(src, dst)
        tasks = plan_dedup_tasks(jobs, RELEASE)
        res = st.dedup_task(tasks[0])
        assert res["category"] == "01_foundation"
        assert res["kept"] == 5
        assert res["dropped"] == 2
        assert res["conflicts"] == 0
        # Result = category + dedup stats + registry telemetry alias only.
        assert set(res) == {
            "category", "kept", "dropped", "conflicts",
            "conflict_sample", "unique_ids", "total",
        }
        # Nothing outside the category output was written (no manifest,
        # stats, checksums, lifecycle, or registry-finalize files).
        assert not (tmp_path / "releases" / RELEASE / "metadata").exists()
        assert not (tmp_path / "task_registry_dedup.jsonl").exists()
