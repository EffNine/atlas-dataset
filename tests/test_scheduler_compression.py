#!/usr/bin/env python3
"""Tests for the release-compression migration (Universal Scheduler Phase 6B).

Covers:
- deterministic task identity (compress:<release>:<shard_stem>)
- task planning (one shard = one task; --skip-existing plan-time disk scan)
- fixed worker limit (D3: release.compress_workers = 4, never auto)
- scheduler vs legacy output identity (SHA-256 per compressed file)
- resume (registry-completed tasks skipped; new shards still run)
- retry (worker failure retried then completed / terminal after max)
- partial output recovery (stale running task re-claimed and re-run)
- fallback (kill-switch + original executor path, identical output)
- CLI end-to-end determinism (scheduler subprocess vs fallback subprocess)

Run (from repo root):
  python3 -m pytest tests/test_scheduler_compression.py -v
"""

from __future__ import annotations

import json
import multiprocessing
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
SCRIPTS_RELEASE = SCRIPTS / "release"
# scripts/release first so `common` / `compress_release` / `scheduler_tasks`
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

import compress_release  # noqa: E402
from common import CATEGORIES, count_jsonl_zst, open_zstd_writer, sha256_file  # noqa: E402
import scheduler_tasks as st  # noqa: E402
from scheduler_tasks import (  # noqa: E402
    compress_task_id,
    plan_compress_tasks,
    resolve_compress_workers,
    run_compression_scheduler,
)

RELEASE = "v1.0-RC1"


# --------------------------------------------------------------------------
# Fixtures / helpers
# --------------------------------------------------------------------------

def _rec(cat: str, sub: str, i: int) -> dict:
    return {
        "id": f"ph6b_{cat.split('_')[0]}_{i:05d}",
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


def _make_shards(d: Path) -> list[Path]:
    """Two shards: one single-category, one mixed (mirrors test_release_pipeline)."""
    d.mkdir(parents=True, exist_ok=True)
    with (d / "wiki_sci_shard0_atlas.jsonl").open("w", encoding="utf-8") as fh:
        for i in range(5):
            fh.write(json.dumps(_rec("06_science_engineering", "science", i)) + "\n")
    with (d / "ultrafeedback_atlas.jsonl").open("w", encoding="utf-8") as fh:
        for i in range(3):
            fh.write(json.dumps(_rec("01_foundation", "general", i)) + "\n")
        for i in range(4):
            fh.write(json.dumps(_rec("08_creative_knowledge", "arts", i)) + "\n")
    return sorted(d.glob("*.jsonl"))


def _out_hashes(out_root: Path) -> dict[str, str]:
    """SHA-256 of every compressed output file, keyed by relative path."""
    hashes = {}
    for f in sorted(Path(out_root).rglob("*.jsonl.zst")):
        hashes[str(f.relative_to(out_root))] = sha256_file(f)
    return hashes


def _legacy_run(shards: list[Path], out_root: Path, level: int = 19) -> list[dict]:
    """The original executor's unit of work, run sequentially (shared worker)."""
    out_root.mkdir(parents=True, exist_ok=True)
    results = []
    for s in shards:
        results.append(
            compress_release._route_shard(
                {"input_path": str(s), "out_root": str(out_root), "level": level}
            )
        )
    return results


# --------------------------------------------------------------------------
# 1. task planning
# --------------------------------------------------------------------------

class TestTaskPlanning:
    def test_task_ids_deterministic(self, tmp_path: Path):
        shards = _make_shards(tmp_path / "in")
        a, _ = plan_compress_tasks(shards, RELEASE, tmp_path / "out", 19)
        b, _ = plan_compress_tasks(list(reversed(shards)), RELEASE, tmp_path / "out", 19)
        assert [t.task_id for t in a] == [t.task_id for t in b]
        # Sorted by shard stem: ultrafeedback_atlas < wiki_sci_shard0_atlas.
        assert a[0].task_id == f"compress:{RELEASE}:ultrafeedback_atlas"
        assert a[1].task_id == f"compress:{RELEASE}:wiki_sci_shard0_atlas"

    def test_release_scoped_ids(self, tmp_path: Path):
        """Same shard stem under two releases -> distinct task ids (R2)."""
        shards = _make_shards(tmp_path / "in")
        tasks_a, _ = plan_compress_tasks(shards, "v1.0-RC1", tmp_path / "out", 19)
        tasks_b, _ = plan_compress_tasks(shards, "v1.0-RC2", tmp_path / "out", 19)
        assert tasks_a[0].task_id == "compress:v1.0-RC1:ultrafeedback_atlas"
        assert tasks_b[0].task_id == "compress:v1.0-RC2:ultrafeedback_atlas"
        assert {t.task_id for t in tasks_a}.isdisjoint({t.task_id for t in tasks_b})

    def test_task_payload(self, tmp_path: Path):
        shards = _make_shards(tmp_path / "in")
        tasks, _ = plan_compress_tasks(shards, RELEASE, tmp_path / "out", 19)
        t = tasks[0]
        assert t.source == "compression"
        assert t.operation == "compress"
        assert t.input == str(shards[0])
        assert t.extra["out_root"] == str((tmp_path / "out").resolve())
        assert t.extra["level"] == 19
        assert t.extra["release"] == RELEASE
        assert t.estimated_size_mb > 0

    def test_planner_skip_existing(self, tmp_path: Path):
        shards = _make_shards(tmp_path / "in")
        out = tmp_path / "out"
        tasks, skipped = plan_compress_tasks(shards, RELEASE, out, 19)
        assert len(tasks) == 2 and skipped == 0

        # First shard's output (01_foundation, its real category) exists and
        # decompresses OK -> disk-skipped.
        stem = shards[0].stem  # ultrafeedback_atlas (mixed: 01_foundation)
        out_file = out / "01_foundation" / f"{stem}.jsonl.zst"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open_zstd_writer(out_file, level=19) as w:
            w.write(json.dumps(_rec("01_foundation", "general", 0)).encode("utf-8") + b"\n")

        tasks, skipped = plan_compress_tasks(shards, RELEASE, out, 19, skip_existing=True)
        assert skipped == 1
        assert [t.task_id for t in tasks] == [f"compress:{RELEASE}:wiki_sci_shard0_atlas"]

        # Corrupt output -> NOT skipped (integrity guard wins).
        corrupt = out / "06_science_engineering" / "wiki_sci_shard0_atlas.jsonl.zst"
        corrupt.parent.mkdir(parents=True, exist_ok=True)
        corrupt.write_bytes(b"not-zstd")
        tasks2, skipped2 = plan_compress_tasks(shards, RELEASE, out, 19, skip_existing=True)
        assert skipped2 == 1  # only the valid one
        assert [t.task_id for t in tasks2] == [f"compress:{RELEASE}:wiki_sci_shard0_atlas"]

    def test_registry_stage_key(self, tmp_path: Path):
        """D1: stage key `compression` -> task_registry_compression.jsonl."""
        shards = _make_shards(tmp_path / "in")
        reg = tmp_path / "reg"
        run_compression_scheduler(shards, RELEASE, tmp_path / "out", 19,
                                  workers=2, registry_root=reg)
        assert (reg / "task_registry_compression.jsonl").exists()


# --------------------------------------------------------------------------
# 2. worker limit (D3)
# --------------------------------------------------------------------------

class TestWorkerLimit:
    def test_fixed_default_four(self):
        """D3: fixed limit 4 from config release.compress_workers — no auto."""
        assert resolve_compress_workers() == 4

    def test_explicit_cli_override_wins(self):
        assert resolve_compress_workers(2) == 2
        assert resolve_compress_workers(8) == 8

    def test_never_auto(self, monkeypatch):
        """Even if config says 'auto', compression falls back to the fixed 4."""
        import parallel.config as pcfg
        monkeypatch.setattr(
            pcfg, "get_stage_config",
            lambda stage, cfg=None: {"compress_workers": "auto"} if stage == "release" else {},
        )
        assert resolve_compress_workers() == 4


# --------------------------------------------------------------------------
# 3. determinism: scheduler vs legacy (SHA-256 identical)
# --------------------------------------------------------------------------

class TestDeterminism:
    def test_output_identical_scheduler_vs_legacy(self, tmp_path: Path):
        shards = _make_shards(tmp_path / "in")
        out_legacy = tmp_path / "out_legacy"
        out_sched = tmp_path / "out_sched"

        legacy_results = _legacy_run(shards, out_legacy)
        sched_results, skipped, failures = run_compression_scheduler(
            shards, RELEASE, out_sched, 19, workers=2,
            registry_root=tmp_path / "reg",
        )
        assert not failures
        assert skipped == 0
        assert len(sched_results) == len(shards)

        # Every compressed output file byte-identical.
        assert _out_hashes(out_legacy) == _out_hashes(out_sched)

        # Result dicts identical except elapsed_s (report-only field) and
        # `total` (scheduler-only registry-telemetry alias).
        def _norm(results):
            return [
                {k: v for k, v in r.items() if k not in ("elapsed_s", "total")}
                for r in sorted(results, key=lambda r: r["input"])
            ]
        assert _norm(legacy_results) == _norm(sched_results)

    def test_cli_subprocess_identity(self, tmp_path: Path):
        """End-to-end: CLI without scripts on PYTHONPATH (fallback) vs with
        PYTHONPATH + redirected registry (scheduler) -> identical output."""
        shards_dir = tmp_path / "in"
        _make_shards(shards_dir)
        out_legacy = tmp_path / "rel_legacy"
        out_sched = tmp_path / "rel_sched"
        reg = tmp_path / "reg"

        base = [
            sys.executable,
            str(SCRIPTS_RELEASE / "compress_release.py"),
            "--input", str(shards_dir),
            "--pattern", "*_atlas.jsonl",
            "--workers", "2",
        ]
        env_plain = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        r1 = subprocess.run(base + ["--output", str(out_legacy)],
                            capture_output=True, text=True, cwd=ROOT, env=env_plain)
        assert r1.returncode == 0, r1.stderr

        env_sched = dict(env_plain)
        env_sched["PYTHONPATH"] = str(SCRIPTS)
        env_sched["ATLAS_REGISTRY_ROOT"] = str(reg)
        r2 = subprocess.run(base + ["--output", str(out_sched)],
                            capture_output=True, text=True, cwd=ROOT, env=env_sched)
        assert r2.returncode == 0, r2.stderr
        assert "scheduler" in r2.stdout  # scheduler path actually ran

        assert _out_hashes(out_legacy) == _out_hashes(out_sched)

        def _report(root: Path) -> dict:
            rep = json.loads(
                (Path(root) / "metadata" / "compression_report.json").read_text(encoding="utf-8")
            )
            rep.pop("generated_at")
            rep.pop("elapsed_s")
            return rep

        assert _report(out_legacy) == _report(out_sched)


# --------------------------------------------------------------------------
# 4. resume
# --------------------------------------------------------------------------

class TestResume:
    def test_resume_skips_completed(self, tmp_path: Path):
        shards = _make_shards(tmp_path / "in")
        out = tmp_path / "out"
        reg = tmp_path / "reg"

        r1, s1, f1 = run_compression_scheduler(shards, RELEASE, out, 19,
                                               workers=2, registry_root=reg)
        assert len(r1) == 2 and s1 == 0 and not f1
        hashes_before = _out_hashes(out)

        # Second run: registry says completed -> nothing re-runs, outputs untouched.
        r2, s2, f2 = run_compression_scheduler(shards, RELEASE, out, 19,
                                               workers=2, registry_root=reg)
        assert r2 == []
        assert s2 == 2
        assert not f2
        assert _out_hashes(out) == hashes_before

    def test_new_shard_runs_after_resume(self, tmp_path: Path):
        shards = _make_shards(tmp_path / "in")
        out = tmp_path / "out"
        reg = tmp_path / "reg"
        run_compression_scheduler(shards, RELEASE, out, 19, workers=2, registry_root=reg)

        # A new shard appears -> only it runs; the completed two stay skipped.
        with (tmp_path / "in" / "new_shard_atlas.jsonl").open("w", encoding="utf-8") as fh:
            for i in range(2):
                fh.write(json.dumps(_rec("02_software_engineering", "code", i)) + "\n")
        shards2 = sorted((tmp_path / "in").glob("*.jsonl"))
        r3, s3, f3 = run_compression_scheduler(shards2, RELEASE, out, 19,
                                               workers=2, registry_root=reg)
        assert len(r3) == 1
        assert s3 == 2
        assert not f3
        assert count_jsonl_zst(out / "02_software_engineering" / "new_shard_atlas.jsonl.zst") == 2

    def test_cross_release_no_collision(self, tmp_path: Path):
        """Release B after release A completes -> B's tasks are distinct (R2)."""
        shards = _make_shards(tmp_path / "in")
        out = tmp_path / "out"
        reg = tmp_path / "reg"
        r1, _, _ = run_compression_scheduler(shards, "v1.0-RC1", out, 19,
                                             workers=2, registry_root=reg)
        assert len(r1) == 2
        r2, s2, _ = run_compression_scheduler(shards, "v1.0-RC2", out, 19,
                                              workers=2, registry_root=reg)
        assert len(r2) == 2
        assert s2 == 0


# --------------------------------------------------------------------------
# 5. retry
# --------------------------------------------------------------------------

class TestRetry:
    def test_retry_then_completed(self, tmp_path: Path):
        from parallel.scheduler import Scheduler

        # Single shard so the counter is unambiguous: 1 failure + 1 success.
        shards = _make_shards(tmp_path / "in")[:1]
        tasks, _ = plan_compress_tasks(shards, RELEASE, tmp_path / "out", 19)
        calls = {"n": 0}

        def flaky(t):
            if calls["n"] == 0:
                calls["n"] += 1
                raise RuntimeError("transient worker failure")
            calls["n"] += 1
            return st.compress_task(t)

        s = Scheduler("compression", registry_root=tmp_path / "reg", workers=1,
                      pool="thread", max_retries=2)
        results = s.run(tasks, flaky)
        assert results[0].status == "completed"
        assert calls["n"] == 2

    def test_terminal_failure_after_max_retries(self, tmp_path: Path):
        from parallel.scheduler import Scheduler

        shards = _make_shards(tmp_path / "in")
        tasks, _ = plan_compress_tasks(shards, RELEASE, tmp_path / "out", 19)

        def always_fail(t):
            raise RuntimeError("always fails")

        s = Scheduler("compression", registry_root=tmp_path / "reg", workers=1,
                      pool="thread", max_retries=2)
        results = s.run(tasks, always_fail)
        assert results[0].status == "failed"
        assert results[0].attempts == 3
        assert s.registry.status(f"compress:{RELEASE}:wiki_sci_shard0_atlas") == "failed"

    def test_run_surfaces_terminal_failure(self, tmp_path: Path):
        """A bad shard raises in the worker -> retried -> terminal failure entry."""
        shards = _make_shards(tmp_path / "in")
        bad = tmp_path / "in" / "bad_atlas.jsonl"
        bad.write_text(
            json.dumps({"id": "bad1", "category": "zz_invalid", "messages": []}) + "\n",
            encoding="utf-8",
        )
        shards = sorted(shards + [bad])

        results, skipped, failures = run_compression_scheduler(
            shards, RELEASE, tmp_path / "out", 19, workers=2,
            registry_root=tmp_path / "reg",
        )
        assert len(results) == 2  # good shards completed
        assert len(failures) == 1
        assert "bad_atlas.jsonl" in failures[0]["shard"]
        assert failures[0]["errors"]


# --------------------------------------------------------------------------
# 6. partial output recovery (crash mid-shard)
# --------------------------------------------------------------------------

class TestRecovery:
    def test_stale_running_reclaimed_and_rerun(self, tmp_path: Path):
        from parallel.registry import TaskRegistry

        shards = _make_shards(tmp_path / "in")
        out = tmp_path / "out"
        reg = tmp_path / "reg"
        stems = [s.stem for s in shards]

        # Simulate a crash: the 2nd shard's task was claimed (running) and a
        # partial/corrupt output was left on disk. stems[1] = wiki_sci_shard0_atlas
        # (single category 06_science_engineering).
        tasks, _ = plan_compress_tasks(shards, RELEASE, out, 19)
        reg_obj = TaskRegistry(reg, "compression")
        reg_obj.claim(tasks[1].task_id)
        partial = out / "06_science_engineering" / f"{stems[1]}.jsonl.zst"
        partial.parent.mkdir(parents=True, exist_ok=True)
        partial.write_bytes(b"partial-garbage-not-zstd")

        # lease_seconds=0 -> the stale running task is re-claimed immediately.
        results, skipped, failures = run_compression_scheduler(
            shards, RELEASE, out, 19, workers=2, registry_root=reg,
            lease_seconds=0,
        )
        assert not failures
        assert skipped == 0
        assert len(results) == 2  # both shards ran; the stale one was re-run

        # Partial output replaced by a valid compressed frame (full rewrite).
        assert count_jsonl_zst(partial) == 5  # 5 science records
        # Ultrafeedback (mixed shard) wrote its own category outputs.
        assert count_jsonl_zst(out / "01_foundation" / f"{stems[0]}.jsonl.zst") == 3
        assert count_jsonl_zst(out / "08_creative_knowledge" / f"{stems[0]}.jsonl.zst") == 4


# --------------------------------------------------------------------------
# 7. fallback
# --------------------------------------------------------------------------

class TestFallback:
    def test_kill_switch_forces_sequential(self, tmp_path: Path, monkeypatch):
        shards = _make_shards(tmp_path / "in")
        out = tmp_path / "out"
        monkeypatch.setattr(st, "_SCHEDULER_ENABLED", False)

        results, skipped, failures = run_compression_scheduler(
            shards, RELEASE, out, 19, workers=2, registry_root=tmp_path / "reg",
        )
        assert not failures
        assert len(results) == 2
        # No registry written by the fallback path.
        assert not (tmp_path / "reg" / "task_registry_compression.jsonl").exists()
        # Fallback output is byte-identical to the shared legacy worker.
        legacy = tmp_path / "legacy"
        _legacy_run(shards, legacy)
        assert _out_hashes(out) == _out_hashes(legacy)

    def test_outer_fallback_original_loop(self, tmp_path: Path, monkeypatch):
        """Blocking scheduler_tasks import -> compress_release's ORIGINAL loop."""
        shards = _make_shards(tmp_path / "in")
        out = tmp_path / "out"
        monkeypatch.setitem(sys.modules, "scheduler_tasks", None)

        rc = compress_release.main([
            "--input", str(shards[0].parent),
            "--pattern", "*_atlas.jsonl",
            "--output", str(out),
            "--workers", "1",
        ])
        assert rc == 0
        report = json.loads(
            (out / "metadata" / "compression_report.json").read_text(encoding="utf-8")
        )
        assert report["total_records"] == 12
        assert report["failures"] == []
        assert len(report["files"]) == 3
