#!/usr/bin/env python3
"""Universal Scheduler integration for release compression (Phase 6B).

Execution orchestration ONLY — the routing/compression/verification logic
stays in ``compress_release._route_shard`` (untouched). This module adds:

- deterministic task identity: ``compress:<release>:<shard_stem>`` (release
  tag avoids cross-release registry collisions — the registry is repo-global)
- TaskRegistry checkpoint/resume/retry via the Universal Scheduler
  (stage key ``compression`` ->
  ``metadata/pipeline_state/task_registry_compression.jsonl``)
- fixed worker limit (D3): ``release.compress_workers = 4``, never auto
- ``--skip-existing`` plan-time disk scan layered on registry resume (D2:
  registry is the primary resume mechanism, disk check the secondary guard)
- sequential fallback (byte-identical behavior) on any scheduler error
- ``_SCHEDULER_ENABLED`` kill-switch for tests + operational override

The old executor in ``compress_release.main`` remains the last-resort
fallback (scheduler_tasks import failure); output is identical from every
path because all paths share the same ``_route_shard`` worker.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

# D3: fixed compression worker limit — do NOT auto-resolve yet.
_DEFAULT_COMPRESS_WORKERS = 4

# Operational kill-switch: set False to force the sequential fallback even
# when the scheduler imports cleanly (also used by tests).
_SCHEDULER_ENABLED = True


def resolve_compress_workers(explicit: int | None = None) -> int:
    """Fixed compression worker limit (D3).

    Precedence: explicit (CLI) > env ``ATLAS_WORKERS_RELEASE`` > config
    ``release.compress_workers`` (pinned to 4). Never returns 'auto' — the
    scheduler path is not allowed to auto-resolve compression workers yet.
    """
    if explicit is not None and explicit > 0:
        return explicit
    try:
        from parallel.config import resolve_worker_count

        resolved = resolve_worker_count("release", explicit=explicit)
        if isinstance(resolved, int) and resolved > 0:
            return resolved
    except Exception:
        pass
    return _DEFAULT_COMPRESS_WORKERS


def compress_task_id(release: str, shard_stem: str) -> str:
    """Deterministic task identity: ``compress:<release>:<shard_stem>``.

    The release prefix keeps each release's tasks distinct (a bare
    ``compress:<stem>`` would collide across releases in the repo-global
    registry). Within one release the id sorts by shard name, which matches
    the report's ``sorted(results, key=input)`` order.
    """
    return f"compress:{release}:{shard_stem}"


def _outputs_exist_ok(out_root: Path, stem: str) -> tuple[bool, bool]:
    """(found_any, all_ok) — mirrors compress_release's --skip-existing check.

    A shard counts as already-compressed when at least one category output
    exists and every existing output decompresses OK. Corrupt/empty frames
    mark the shard as NOT done (all_ok False) so it is re-run.
    """
    from common import CATEGORIES, count_jsonl_zst

    found_any = False
    ok = True
    for cat in CATEGORIES:
        out_file = out_root / cat / f"{stem}.jsonl.zst"
        if out_file.exists():
            found_any = True
            try:
                if count_jsonl_zst(out_file) < 0:
                    ok = False
                    break
            except Exception:
                ok = False
                break
    return found_any, ok


def plan_compress_tasks(
    shards,
    release: str,
    out_root,
    level: int,
    *,
    skip_existing: bool = False,
) -> tuple[list, int]:
    """One Task per shard with deterministic id ``compress:<release>:<stem>``.

    ``--skip-existing`` runs here (plan time): shards whose outputs exist and
    verify OK are dropped before the scheduler sees them (secondary guard —
    the TaskRegistry completed state remains the primary resume mechanism).

    Returns ``(tasks, skipped_disk)`` where ``skipped_disk`` counts shards
    already compressed on disk.
    """
    from parallel.models import Task

    out_root_p = Path(out_root)
    tasks: list = []
    skipped_disk = 0
    for shard in sorted(Path(p) for p in shards):
        stem = shard.stem
        if skip_existing:
            found_any, ok = _outputs_exist_ok(out_root_p, stem)
            if found_any and ok:
                skipped_disk += 1
                continue
        tasks.append(
            Task(
                task_id=compress_task_id(release, stem),
                source="compression",
                operation="compress",
                input=str(shard),
                estimated_size_mb=(
                    shard.stat().st_size / (1024 * 1024) if shard.exists() else 0.0
                ),
                extra={
                    "out_root": str(out_root_p),
                    "level": int(level),
                    "release": release,
                },
            )
        )
    return tasks, skipped_disk


def compress_task(task) -> dict[str, Any]:
    """Universal Scheduler worker: compress one shard.

    Module-level (picklable for process pools). Delegates to
    ``compress_release._route_shard`` verbatim — the SAME worker the original
    ProcessPoolExecutor dispatched — so output bytes are identical by
    construction.

    Raises on any error or verification mismatch so the scheduler records a
    retry; a terminal failure after ``max_retries`` is surfaced to the caller
    as a failure entry (exit 1, today's semantics). Each task owns its
    output files (disjoint per shard), so a retry rewrites only that shard's
    outputs — no duplicate records possible.
    """
    from common import DEFAULT_ZSTD_LEVEL
    from compress_release import _route_shard

    extra = getattr(task, "extra", {}) or {}
    args = {
        "input_path": task.input,
        "out_root": extra.get("out_root", ""),
        "level": extra.get("level", DEFAULT_ZSTD_LEVEL),
    }
    result = _route_shard(args)
    if result.get("errors"):
        raise RuntimeError(
            f"compress errors for {Path(task.input).name}: {result['errors']}"
        )
    for cat, v in (result.get("verified") or {}).items():
        if not v.get("ok"):
            raise RuntimeError(
                f"verification failed for {Path(task.input).name} category {cat}: "
                f"expected {v.get('expected')} got {v.get('actual')}"
            )
    # Registry telemetry alias (design R7): the monitor reads `total`.
    result["total"] = result.get("input_records", 0)
    return result


def run_compression_scheduler(
    shards,
    release: str,
    out_root,
    level: int,
    *,
    workers: int | None = None,
    skip_existing: bool = False,
    registry_root=None,
    lease_seconds: int = 900,
):
    """Run compression through the Universal Scheduler.

    Returns ``(results, skipped, failures)``:
      results  — ``_route_shard``-style result dicts for COMPLETED tasks
                 (deterministic task_id order; the caller re-sorts by input
                 name for the report, as the legacy path does)
      skipped  — plan-time disk skips + registry-completed skips
      failures — ``[{"shard": <input name>, "errors": [msg]}]`` for terminal
                 failures (after retry exhaustion)

    Falls back to a sequential loop on any scheduler error. Output from
    either path is byte-identical; the registry is only written by the
    scheduler path.
    """
    out_root_p = Path(out_root)
    tasks, disk_skipped = plan_compress_tasks(
        shards, release, out_root_p, level, skip_existing=skip_existing
    )
    if not tasks:
        return [], disk_skipped, []

    if workers is None:
        workers = resolve_compress_workers()
    input_by_id = {t.task_id: Path(t.input).name for t in tasks}

    try:
        from parallel.scheduler import Scheduler

        if not _SCHEDULER_ENABLED:
            raise RuntimeError("scheduler disabled (kill-switch)")

        reg_root = (
            Path(registry_root)
            if registry_root
            else REPO_ROOT / "metadata" / "pipeline_state"
        )
        sched = Scheduler(
            "compression",
            registry_root=str(reg_root),
            workers=workers,
            pool="process",
            max_retries=2,
            lease_seconds=lease_seconds,
        )
        print(
            f"[compression] scheduler: {len(tasks)} shard tasks, "
            f"{sched.workers} workers"
        )
        results: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        skipped = disk_skipped
        for tr in sched.run(tasks, compress_task):
            if tr.status == "completed" and isinstance(tr.result, dict):
                results.append(tr.result)
            elif tr.status == "failed":
                stem = tr.task_id.rsplit(":", 1)[-1]
                failures.append(
                    {
                        "shard": input_by_id.get(tr.task_id, stem),
                        "errors": [tr.error or "compression failed"],
                    }
                )
            elif tr.status == "skipped":
                skipped += 1
        return results, skipped, failures
    except Exception as exc:
        print(
            f"[compression] scheduler unavailable ({exc}); falling back to sequential",
            file=sys.stderr,
        )
        from compress_release import _route_shard

        results = []
        for t in tasks:
            results.append(
                _route_shard(
                    {
                        "input_path": t.input,
                        "out_root": str(out_root_p),
                        "level": level,
                    }
                )
            )
        return results, disk_skipped, []
