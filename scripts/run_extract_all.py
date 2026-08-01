#!/usr/bin/env python3
"""Parallel Wikipedia extraction runner for Atlas.

Fans out per-shard invocations of scripts/extract_wiki_<source>.py across
shard workers, so all 41 shards of a source extract concurrently instead of
one at a time.

Phase 2: execution layer uses the Universal Scheduler
(scripts/parallel/) — adaptive workers, TaskRegistry checkpoint/resume,
retry. The manual ProcessPoolExecutor path is preserved as a fallback and
its behavior is identical (same subprocess invocations, same outputs).

Usage:
  python scripts/run_extract_all.py --source wiki_sys
  python scripts/run_extract_all.py --source wiki_ai --shard-workers 4
  python scripts/run_extract_all.py --all --shard-workers 8
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
CONFIG_PATH = ROOT / "config" / "parallelism.yaml"

SOURCES = [
    "wiki_ai", "wiki_sw", "wiki_sys", "wiki_sci",
    "wiki_biz", "wiki_cre", "wiki_hw",
]


def load_config() -> dict:
    try:
        import yaml
        with open(CONFIG_PATH, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def extract_one(args: tuple[str, int]) -> tuple[int, int, str]:
    """Run extract_wiki_<source>.py <shard>. Returns (source_idx, shard, output).

    Legacy worker contract (kept for backward compatibility with tests and
    the manual-pool fallback path). Returns an ERROR string, never raises,
    when the script is missing.
    """
    source, shard = args
    script = SCRIPT_DIR / f"extract_{source}.py"
    if not script.exists():
        return (0, shard, f"ERROR: {script} not found")
    cmd = [sys.executable, str(script), str(shard)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    last = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
    if r.returncode != 0:
        return (0, shard, f"ERROR shard {shard}: {r.stderr.strip()[-200:]}")
    return (0, shard, last)


def extract_task(task) -> dict:
    """Universal Scheduler worker: dispatch a Task to extract_wiki_<source>.py.

    Module-level so it can be pickled into process workers. Raises on
    failure so the scheduler can retry and mark the registry entry failed.
    Uses task.input as the script path (set by the planner at plan time).
    """
    source = task.source
    shard = int(task.extra.get("shard", 0))
    script = Path(task.input) if task.input else SCRIPT_DIR / f"extract_{source}.py"
    if not script.exists():
        raise RuntimeError(f"script not found: {script}")
    cmd = [sys.executable, str(script), str(shard)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"shard {shard}: {r.stderr.strip()[-200:]}")
    last = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
    return {"shard": shard, "output": last}


def plan_extraction_tasks(source: str, shards_per_source: int, script_dir: str | Path | None = None) -> list:
    """Build extraction Tasks (one per shard) for the Universal Scheduler.

    One shard = one task (initial). Byte-range splitting of individual
    shards is supported by the planner for future phases.
    """
    from parallel.models import Task

    sd = Path(script_dir) if script_dir else SCRIPT_DIR
    return [
        Task(
            task_id=f"extract:{source}:{s:03d}",
            source=source,
            operation="extract_wiki_shard",
            input=str(sd / f"extract_{source}.py"),
            extra={"shard": s},
        )
        for s in range(shards_per_source)
    ]


def run_source_scheduler(source: str, shard_workers: int, shards_per_source: int,
                         registry_root: str | Path | None = None,
                         script_dir: str | Path | None = None) -> int:
    """Run one source through the Universal Scheduler."""
    from parallel.scheduler import Scheduler

    print(f"\n=== {source}: extracting {shards_per_source} shards with adaptive scheduler ===")
    tasks = plan_extraction_tasks(source, shards_per_source, script_dir)

    reg_root = registry_root or (ROOT / "metadata" / "pipeline_state")
    sched = Scheduler(
        "extraction",
        registry_root=str(reg_root),
        workers=shard_workers,
        pool="process",
        max_retries=2,
    )
    print(f"  [{source}] scheduler: {sched.workers} adaptive workers")
    results = sched.run(tasks, extract_task)

    ok = 0
    failed = 0
    for tr in results:
        if tr.status == "completed":
            ok += 1
            if ok % 5 == 0 or ok == shards_per_source:
                out = tr.result.get("output", "") if isinstance(tr.result, dict) else ""
                print(f"  [{source}] {ok}/{shards_per_source} shards done | {out}")
        elif tr.status == "failed":
            failed += 1
            print(f"  [{source}] ERROR shard {tr.task_id}: {tr.error}")
        else:  # skipped (completed in a prior run)
            ok += 1
    print(f"[{source}] Done: {ok} ok, {failed} failed")
    return failed


def run_source(source: str, shard_workers: int, shards_per_source: int) -> int:
    """Run one source: scheduler path with manual ProcessPool fallback."""
    try:
        return run_source_scheduler(source, shard_workers, shards_per_source)
    except Exception as sched_exc:
        # Fallback: manual ProcessPoolExecutor (identical behavior).
        print(f"  [{source}] scheduler unavailable ({sched_exc}); falling back to ProcessPoolExecutor", file=sys.stderr)
        print(f"\n=== {source}: extracting {shards_per_source} shards with {shard_workers} workers (fallback) ===")
        tasks = [(source, s) for s in range(shards_per_source)]
        ok = 0
        failed = 0
        with ProcessPoolExecutor(max_workers=shard_workers) as ex:
            futures = {ex.submit(extract_one, t): t for t in tasks}
            for fut in as_completed(futures):
                _, shard, out = fut.result()
                if out.startswith("ERROR"):
                    failed += 1
                    print(f"  [{source}] {out}")
                else:
                    ok += 1
                    if ok % 5 == 0 or ok == shards_per_source:
                        print(f"  [{source}] {ok}/{shards_per_source} shards done | {out}")
        print(f"[{source}] Done: {ok} ok, {failed} failed")
        return failed


def main() -> int:
    ap = argparse.ArgumentParser(description="Parallel Wikipedia extraction runner.")
    ap.add_argument("--source", default=None, help="Single source (e.g. wiki_sys)")
    ap.add_argument("--all", action="store_true", help="Extract all wiki sources")
    ap.add_argument("--shard-workers", type=int, default=None,
                    help="Parallel shard workers (default: config extraction.shard_workers or 4)")
    ap.add_argument("--shards", type=int, default=None,
                    help="Shards per source (default: config extraction.shards_per_source or 41)")
    ap.add_argument("--registry-root", default=None,
                    help="TaskRegistry root dir (default: metadata/pipeline_state)")
    args = ap.parse_args()

    config = load_config()
    ext = config.get("parallelism", {}).get("extraction", {})
    shard_workers = args.shard_workers or int(ext.get("shard_workers", 4))
    shards_per_source = args.shards or int(ext.get("shards_per_source", 41))

    sources = SOURCES if args.all else ([args.source] if args.source else [])
    if not sources:
        ap.print_help()
        return 2

    total_failed = 0
    for source in sources:
        total_failed += run_source(source, shard_workers, shards_per_source)

    print(f"\n=== EXTRACTION {'PASS' if total_failed == 0 else 'FAIL'} ({total_failed} failed shards) ===")
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
