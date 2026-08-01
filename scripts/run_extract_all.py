#!/usr/bin/env python3
"""Parallel Wikipedia extraction runner for Atlas.

Fans out per-shard invocations of scripts/extract_wiki_<source>.py across
shard workers, so all 41 shards of a source extract concurrently instead of
one at a time.

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
    """Run extract_wiki_<source>.py <shard>. Returns (source_idx, shard, output)."""
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


def run_source(source: str, shard_workers: int, shards_per_source: int) -> int:
    print(f"\n=== {source}: extracting {shards_per_source} shards with {shard_workers} workers ===")
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
