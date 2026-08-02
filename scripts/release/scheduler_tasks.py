#!/usr/bin/env python3
"""Universal Scheduler integration for release steps.

Execution orchestration ONLY — the routing/compression/verification logic
stays in ``compress_release._route_shard`` and the dedup logic stays in
``dedup_release.dedup_category`` (both untouched). This module adds:

Compression (Phase 6B)
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

Dedup (Phase 7B)
- deterministic task identity: ``dedup:<release>:<category>`` (release tag
  avoids cross-release registry collisions)
- TaskRegistry checkpoint/resume/retry via the Universal Scheduler
  (stage key ``dedup`` ->
  ``metadata/pipeline_state/task_registry_dedup.jsonl``)
- fixed worker limit (D2): ``release.dedup_workers = 4``, never auto
- pure worker + serialized finalize (5C pattern): ``dedup_task`` only calls
  the existing ``dedup_category`` and returns per-category stats — no
  manifest/stats/checksum/lifecycle/registry writes in the worker. The
  driver serializes ``compute_statistics`` + ``build_manifest`` + report
  after all categories complete.
- sequential fallback (byte-identical behavior) on any scheduler error
- ``_SCHEDULER_ENABLED`` kill-switch forces the sequential fallback

The old executors in ``compress_release.main`` / ``dedup_release.main``
remain the last-resort fallback (scheduler_tasks import failure); output is
identical from every path because all paths share the same workers.
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


# ==========================================================================
# Dedup (Phase 7B)
# ==========================================================================

# D2: fixed dedup worker limit — never auto-resolve yet.
_DEFAULT_DEDUP_WORKERS = 4


def resolve_dedup_workers(explicit: int | None = None) -> int:
    """Fixed dedup worker limit (D2).

    Precedence: explicit (CLI ``--jobs``) > env ``ATLAS_WORKERS_RELEASE`` >
    config ``release.dedup_workers`` (pinned to 4) > fixed default 4.
    Never returns 'auto' — the scheduler path is not allowed to auto-resolve
    dedup workers yet. Reads the dedicated ``dedup_workers`` key (not the
    generic release candidates) so a future divergence from
    ``compress_workers`` cannot leak across steps.
    """
    if explicit is not None and explicit > 0:
        return explicit
    try:
        from parallel.config import env_override, get_stage_config

        env_val = env_override("release")
        if env_val is not None and env_val > 0:
            return env_val
        stage_cfg = get_stage_config("release")
        val = stage_cfg.get("dedup_workers", "auto")
        if isinstance(val, int) and val > 0:
            return val
        if isinstance(val, str) and val.strip().isdigit():
            return int(val.strip())
    except Exception:
        pass
    return _DEFAULT_DEDUP_WORKERS


def dedup_task_id(release: str, category: str) -> str:
    """Deterministic task identity: ``dedup:<release>:<category>``.

    The release prefix keeps each release's tasks distinct (a bare
    ``dedup:<category>`` would collide across releases in the repo-global
    registry). Within one release the id sorts by category name, which
    matches ``CATEGORIES`` order and the report's aggregation order.
    """
    return f"dedup:{release}:{category}"


def plan_dedup_tasks(jobs, release: str) -> list:
    """One Task per category with deterministic id ``dedup:<release>:<cat>``.

    ``jobs`` is the driver's ``[(category, src_path, dst_path), ...]`` list
    (already filtered to categories whose source exists — mirrors the
    legacy loop's SKIP-not-found behavior). Planning is stateless and
    sorts by category: same inputs -> same task list (same order) -> same
    task_ids -> registry resume works across restarts.
    """
    from parallel.models import Task

    tasks: list = []
    for cat, src, dst in sorted(jobs, key=lambda j: j[0]):
        src_p = Path(src)
        tasks.append(
            Task(
                task_id=dedup_task_id(release, cat),
                source="release",
                operation="dedup",
                input=str(src_p),
                estimated_size_mb=(
                    src_p.stat().st_size / (1024 * 1024) if src_p.exists() else 0.0
                ),
                extra={
                    "source": str(src_p),
                    "target": str(dst),
                    "category": cat,
                    "release": release,
                },
            )
        )
    return tasks


def dedup_task(task) -> dict[str, Any]:
    """Universal Scheduler worker: dedup one category.

    Module-level (picklable for process pools). Delegates to
    ``dedup_release.dedup_category`` verbatim — the SAME worker the original
    ProcessPoolExecutor / sequential loop dispatched — so output bytes are
    identical by construction.

    Pure worker (5C pattern): returns the per-category stats dict only; no
    manifest / stats / checksums / lifecycle / registry-finalize writes.
    Raises on any error (missing/corrupt source, write failure) so the
    scheduler records a retry; a terminal failure after ``max_retries`` is
    surfaced to the caller as a failure entry (exit 1, today's semantics).
    Each task owns its output file (disjoint per category), so a retry
    rewrites only that category's output — no duplicate records possible.
    """
    from dedup_release import dedup_category

    extra = getattr(task, "extra", {}) or {}
    cat_stats: dict[str, Any] = {}
    dedup_category(Path(extra["source"]), Path(extra["target"]), cat_stats=cat_stats)
    result: dict[str, Any] = {"category": extra["category"], **cat_stats}
    # Registry telemetry alias (design R7): the monitor reads `total`.
    result["total"] = result.get("kept", 0)
    return result


def run_dedup_scheduler(
    jobs,
    release: str,
    *,
    workers: int | None = None,
    registry_root=None,
    lease_seconds: int = 900,
):
    """Run dedup through the Universal Scheduler.

    Returns ``(per_category, totals, skipped, failures)``:
      per_category — ``{category: stats}`` for tasks completed in THIS run
                    (deterministic task_id order == CATEGORIES order)
      totals       — ``{"total_in", "total_kept", "total_dropped",
                    "total_conflicts"}`` summed over THIS run's completions
      skipped      — count of registry-completed tasks skipped (resume)
      failures     — ``[{"category": <cat>, "errors": [msg]}]`` for terminal
                    failures (after retry exhaustion)

    Falls back to the legacy sequential loop on any scheduler error. Output
    from either path is byte-identical; the registry is only written by the
    scheduler path.
    """
    tasks = plan_dedup_tasks(jobs, release)
    if not tasks:
        empty_totals = {
            "total_in": 0,
            "total_kept": 0,
            "total_dropped": 0,
            "total_conflicts": 0,
        }
        return {}, empty_totals, 0, []

    if workers is None:
        workers = resolve_dedup_workers()
    category_by_id = {t.task_id: t.extra["category"] for t in tasks}

    def _empty_totals() -> dict[str, int]:
        return {
            "total_in": 0,
            "total_kept": 0,
            "total_dropped": 0,
            "total_conflicts": 0,
        }

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
            "dedup",
            registry_root=str(reg_root),
            workers=workers,
            pool="process",
            max_retries=2,
            lease_seconds=lease_seconds,
        )
        print(
            f"[dedup] scheduler: {len(tasks)} category tasks, "
            f"{sched.workers} workers"
        )
        per_category: dict[str, Any] = {}
        totals = _empty_totals()
        failures: list[dict[str, Any]] = []
        skipped = 0
        for tr in sched.run(tasks, dedup_task):
            if tr.status == "completed" and isinstance(tr.result, dict):
                cat = tr.result.get("category", tr.task_id.rsplit(":", 1)[-1])
                # Drop the scheduler-only telemetry alias AND the redundant
                # `category` field (the dict key carries it) so per-category
                # stats are byte-identical to the legacy executor's stats.
                per_category[cat] = {
                    k: v for k, v in tr.result.items()
                    if k not in ("total", "category")
                }
                totals["total_in"] += tr.result.get("kept", 0) + tr.result.get(
                    "dropped", 0
                )
                totals["total_kept"] += tr.result.get("kept", 0)
                totals["total_dropped"] += tr.result.get("dropped", 0)
                totals["total_conflicts"] += tr.result.get("conflicts", 0)
                print(
                    f"  [{cat}] kept={tr.result.get('kept', 0):,} "
                    f"dropped={tr.result.get('dropped', 0):,} "
                    f"conflicts={tr.result.get('conflicts', 0)}"
                )
            elif tr.status == "failed":
                cat = category_by_id.get(tr.task_id, tr.task_id.rsplit(":", 1)[-1])
                failures.append(
                    {"category": cat, "errors": [tr.error or "dedup failed"]}
                )
            elif tr.status == "skipped":
                skipped += 1
        return per_category, totals, skipped, failures
    except Exception as exc:
        print(
            f"[dedup] scheduler unavailable ({exc}); falling back to sequential",
            file=sys.stderr,
        )
        from dedup_release import _dedup_sequential

        per_category, totals = _dedup_sequential(jobs)
        return per_category, totals, 0, []
