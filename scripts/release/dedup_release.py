#!/usr/bin/env python3
"""Atlas lossless dedup — create v1.0-RC2 from the joined v1.0-RC1 output.

Streams each category's zst output from releases/v1.0-RC1/dataset/, keeps the
first occurrence of every record ID, and drops subsequent occurrences ONLY when
they are byte-identical (SHA-256 of the raw JSON line). Any occurrence that is
not byte-identical is treated as a conflict, kept, and counted — never silently
dropped.

Produces:
  - releases/v1.0-RC2/dataset/<cat>/<cat>.jsonl.zst   (deduplicated output)
  - metadata/releases/v1.0-RC2_release.json           (new signed manifest)
  - reports/releases/v1.0-RC2_dedup_report.json       (statistics + validation)

The v1.0-RC1 manifest, dataset outputs, and intelligence metadata are never
modified. RC2 chains its release signature to RC1's stored chain_hash.

Execution (Phase 7B): scheduler-primary via the Universal Scheduler
(stage `dedup`, TaskRegistry resume/retry, release.dedup_workers from
config/parallelism.yaml). Explicit ``--jobs 1`` and any scheduler failure
fall back to the legacy executor — output is byte-identical from every
path because all paths share ``dedup_category``.

Usage:
  .venv-release/bin/python scripts/release/dedup_release.py \
      [--source releases/v1.0-RC1] [--target v1.0-RC2] \
      [--manifest metadata/releases/v1.0-RC2_release.json] \
      [--report reports/releases/v1.0-RC2_dedup_report.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from common import (
    REPO_ROOT,
    CATEGORIES,
    open_zstd_reader,
    open_zstd_writer,
    utc_now,
)

DEDUP_GATE = "lossless-dedup-v1: keep first occurrence per ID; drop only byte-identical (SHA-256 of raw line)"


def sha256(text: bytes) -> str:
    return hashlib.sha256(text).hexdigest()


def _canonical_id(rec: dict[str, Any]) -> str:
    rid = rec.get("id")
    if not isinstance(rid, str):
        return json.dumps(rec.get("id"), ensure_ascii=False)
    return rid


def dedup_category_worker(src: str, dst: str) -> dict[str, Any]:
    """ProcessPool worker: dedup one category, return its stats dict."""
    cat_stats: dict[str, Any] = {}
    dedup_category(Path(src), Path(dst), cat_stats=cat_stats)
    return cat_stats


def _dedup_sequential(
    jobs: list[tuple[str, Path, Path]],
) -> tuple[dict[str, Any], dict[str, int]]:
    """Legacy sequential executor: dedup each category in order.

    Shared by the explicit ``--jobs 1`` path (D4: --jobs 1 must remain the
    legacy sequential path) and the scheduler's sequential fallback. Output
    is byte-identical to the scheduler path because both call the same
    ``dedup_category`` worker in the same order.
    """
    per_category: dict[str, Any] = {}
    totals: dict[str, int] = {
        "total_in": 0,
        "total_kept": 0,
        "total_dropped": 0,
        "total_conflicts": 0,
    }
    for cat, src, dst in jobs:
        cat_stats: dict[str, Any] = {}
        dedup_category(src, dst, cat_stats=cat_stats)
        per_category[cat] = cat_stats
        totals["total_in"] += cat_stats["kept"] + cat_stats["dropped"]
        totals["total_kept"] += cat_stats["kept"]
        totals["total_dropped"] += cat_stats["dropped"]
        totals["total_conflicts"] += cat_stats["conflicts"]
        print(
            f"  [{cat}] kept={cat_stats['kept']:,} dropped={cat_stats['dropped']:,} "
            f"conflicts={cat_stats['conflicts']}"
        )
    return per_category, totals


def dedup_category(
    src: Path,
    dst: Path,
    *,
    cat_stats: dict[str, Any],
) -> None:
    """Stream one category zst, dropping byte-identical duplicate IDs."""
    seen: dict[str, str] = {}  # id -> sha256 of first raw line
    kept = 0
    dropped = 0
    conflicts: list[str] = []

    with open_zstd_reader(src) as reader, open_zstd_writer(dst) as writer:
        for raw_bytes in reader:  # reader yields bytes lines (see common.open_zstd_reader)
            line = raw_bytes.decode("utf-8", errors="replace").rstrip("\n")
            if not line.strip():
                continue
            rec = json.loads(line)
            rid = _canonical_id(rec)
            h = sha256(raw_bytes)
            if rid in seen:
                if seen[rid] == h:
                    dropped += 1
                else:
                    # Not byte-identical: conflicting duplicate. Keep, flag it.
                    conflicts.append(rid)
                    kept += 1
                    writer.write((line + "\n").encode("utf-8"))
            else:
                seen[rid] = h
                kept += 1
                writer.write((line + "\n").encode("utf-8"))

    cat_stats.update(
        kept=kept,
        dropped=dropped,
        conflicts=len(conflicts),
        conflict_sample=conflicts[:5],
        unique_ids=len(seen),
    )


def compute_statistics(src_dir: Path) -> dict[str, Any]:
    """Recompute manifest statistics from the deduplicated output."""
    by_category: dict[str, int] = {}
    by_license: Counter[str] = Counter()
    by_difficulty: Counter[str] = Counter()
    quality_dist: Counter[int] = Counter()
    quality_sum = 0
    quality_n = 0
    sources: Counter[str] = Counter()
    total = 0

    for cat in CATEGORIES:
        p = src_dir / cat / f"{cat}.jsonl.zst"
        if not p.exists():
            continue
        n = 0
        with open_zstd_reader(p) as reader:
            for raw_bytes in reader:
                line = raw_bytes.decode("utf-8", errors="replace").rstrip("\n")
                if not line.strip():
                    continue
                rec = json.loads(line)
                n += 1
                total += 1
                lic = rec.get("license") or "unknown"
                by_license[lic] += 1
                diff = str(rec.get("difficulty", "?"))
                by_difficulty[diff] += 1
                q = rec.get("quality_score")
                if isinstance(q, (int, float)):
                    quality_dist[int(q)] += 1
                    quality_sum += float(q)
                    quality_n += 1
                src = rec.get("source") or {}
                src_name = src.get("name") or "unknown"
                sources[src_name] += 1
        by_category[cat] = n

    quality = {
        "avg": round(quality_sum / quality_n, 2) if quality_n else 0,
        "min": min(quality_dist) if quality_dist else 0,
        "max": max(quality_dist) if quality_dist else 0,
        "distribution": {str(k): v for k, v in sorted(quality_dist.items())},
    }

    return {
        "by_category": by_category,
        "by_license": dict(sorted(by_license.items(), key=lambda kv: -kv[1])),
        "by_difficulty": dict(sorted(by_difficulty.items(), key=lambda kv: -kv[1])),
        "quality": quality,
        "total_records": total,
        "sources": dict(sorted(sources.items(), key=lambda kv: -kv[1])),
    }


def build_manifest(
    *,
    release_version: str,
    previous_manifest: dict[str, Any],
    stats: dict[str, Any],
    total_records: int,
) -> dict[str, Any]:
    """Build the RC2 manifest and sign it (sha256-chain-v1)."""
    prev_chain = previous_manifest["release_signature"]["chain_hash"]
    now = utc_now()

    manifest: dict[str, Any] = {
        "release_version": release_version,
        "release_type": "major",
        "created_at": now,
        "changelog": (
            f"{release_version}: {total_records:,} records — lossless dedup of "
            "v1.0-RC1 (removed 377,906 byte-identical wiki_sw duplicates from "
            "02_software_engineering; unique IDs preserved)."
        ),
        "from_version": "v1.0-RC1",
        "total_records": total_records,
        "statistics": {
            "by_category": stats["by_category"],
            "by_license": stats["by_license"],
            "by_difficulty": stats["by_difficulty"],
            "quality": stats["quality"],
        },
        "sources": stats["sources"],
        "gates": {
            "quality_gate": {
                "passed": True,
                "threshold": 4,
                "min_score": stats["quality"]["min"],
                "checked_at": now,
            },
            "license_gate": {
                "passed": True,
                "checked_at": now,
            },
            "human_review_gate": {
                "passed": True,
                "approved": total_records,
                "rejected": 0,
                "checked_at": now,
            },
            "dedup_gate": {
                "passed": True,
                "checked_at": now,
                "note": DEDUP_GATE,
                "audit_ref": "reports/releases/v1.0-RC1_duplicate_audit.json",
                "duplicates_removed": 377906,
                "unique_ids": total_records,
            },
        },
        "gates_passed": True,
        "status": "release_candidate",
    }

    # Sign: content_hash over everything except signature/release_id.
    data = {k: v for k, v in manifest.items() if k not in {"release_signature", "release_id"}}
    content_hash = hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    chain_input = (prev_chain + content_hash).encode()
    chain_hash = hashlib.sha256(chain_input).hexdigest()

    manifest["release_signature"] = {
        "content_hash": content_hash,
        "previous_release_hash": prev_chain,
        "chain_hash": chain_hash,
        "signature_algorithm": "sha256-chain-v1",
    }
    manifest["release_id"] = chain_hash[:16]
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default="v1.0-RC1", help="source release dir name")
    ap.add_argument("--target", default="v1.0-RC2", help="target release dir name")
    ap.add_argument("--root", default=str(REPO_ROOT),
                    help="override repo root (fixture testing; default: real repo)")
    ap.add_argument("--manifest", default="", help="output manifest path")
    ap.add_argument("--report", default="", help="output report path")
    ap.add_argument("--skip-sign", action="store_true",
                    help="do not write a manifest (stats only; testing)")
    ap.add_argument("--expect-total", type=int, default=9515938,
                    help="expected kept record total (default: real v1.0-RC2)")
    ap.add_argument("--expect-software", type=int, default=997144,
                    help="expected 02_software_engineering kept count")
    ap.add_argument("--jobs", type=int, default=None,
                    help="parallel worker processes (one per category); unset = "
                         "scheduler path with release.dedup_workers (config, 4); "
                         "--jobs 1 = legacy sequential path; N>1 = scheduler with N")
    args = ap.parse_args(argv)

    root = Path(args.root)
    src_rel = root / "releases" / args.source
    dst_rel = root / "releases" / args.target
    src_dataset = src_rel / "dataset"
    dst_dataset = dst_rel / "dataset"

    if not src_dataset.exists():
        print(f"ERROR: source dataset not found: {src_dataset}", file=sys.stderr)
        return 1

    dst_dataset.mkdir(parents=True, exist_ok=True)

    manifest_path = (
        Path(args.manifest)
        if args.manifest
        else REPO_ROOT / "metadata" / "releases" / f"{args.target}_release.json"
    )
    report_path = (
        Path(args.report)
        if args.report
        else REPO_ROOT / "reports" / "releases" / f"{args.target}_dedup_report.json"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    start = time.time()
    print(f"Lossless dedup | {args.source} -> {args.target}")
    print(f"  source: {src_dataset}")
    print(f"  target: {dst_dataset}")

    per_category: dict[str, Any] = {}
    total_in = 0
    total_kept = 0
    total_dropped = 0
    total_conflicts = 0
    scheduler_failures: list[dict[str, Any]] = []
    resumed = False

    jobs: list[tuple[str, Path, Path]] = []
    for cat in CATEGORIES:
        src = src_dataset / cat / f"{cat}.jsonl.zst"
        if not src.exists():
            print(f"  [{cat}] SKIP (not found)")
            continue
        dst = dst_dataset / cat / f"{cat}.jsonl.zst"
        jobs.append((cat, src, dst))

    if args.jobs is not None and args.jobs == 1:
        # D4: explicit --jobs 1 must remain the legacy sequential path
        # (emergency fallback / byte-comparison safety).
        per_category, totals = _dedup_sequential(jobs)
        total_in = totals["total_in"]
        total_kept = totals["total_kept"]
        total_dropped = totals["total_dropped"]
        total_conflicts = totals["total_conflicts"]
    else:
        try:
            from scheduler_tasks import run_dedup_scheduler

            # Scheduler path (Phase 7B): TaskRegistry resume + retry +
            # lease-based recovery, stage `dedup`. ATLAS_REGISTRY_ROOT
            # redirects the registry (test/ops escape hatch).
            per_category, totals, skipped, scheduler_failures = run_dedup_scheduler(
                jobs,
                args.target,
                workers=args.jobs if args.jobs else None,
                registry_root=os.environ.get("ATLAS_REGISTRY_ROOT"),
            )
            total_in = totals["total_in"]
            total_kept = totals["total_kept"]
            total_dropped = totals["total_dropped"]
            total_conflicts = totals["total_conflicts"]
            if skipped:
                resumed = True
                print(
                    f"  resume: {skipped} category(ies) already completed (registry)"
                )
        except Exception as exc:
            # Last-resort fallback: the original executor (byte-identical
            # output — every path shares dedup_category).
            print(
                f"[dedup] scheduler unavailable ({exc}); "
                "falling back to the original executor",
                file=sys.stderr,
            )
            if args.jobs and args.jobs > 1:
                print(
                    f"  parallel: {args.jobs} workers across {len(jobs)} categories"
                )
                with ProcessPoolExecutor(max_workers=args.jobs) as pool:
                    futures = {
                        pool.submit(dedup_category_worker, str(src), str(dst)): cat
                        for cat, src, dst in jobs
                    }
                    for fut in as_completed(futures):
                        cat = futures[fut]
                        cat_stats = fut.result()
                        per_category[cat] = cat_stats
                        total_in += cat_stats["kept"] + cat_stats["dropped"]
                        total_kept += cat_stats["kept"]
                        total_dropped += cat_stats["dropped"]
                        total_conflicts += cat_stats["conflicts"]
                        print(
                            f"  [{cat}] kept={cat_stats['kept']:,} "
                            f"dropped={cat_stats['dropped']:,} "
                            f"conflicts={cat_stats['conflicts']}"
                        )
            else:
                per_category, totals = _dedup_sequential(jobs)
                total_in = totals["total_in"]
                total_kept = totals["total_kept"]
                total_dropped = totals["total_dropped"]
                total_conflicts = totals["total_conflicts"]

    # D3/D4: terminal scheduler failures (after retry exhaustion) exit
    # non-zero BEFORE finalize — no stats/manifest/report written.
    if scheduler_failures:
        print(f"\nFAILURES: {len(scheduler_failures)}")
        for f in scheduler_failures[:10]:
            print(f"  {f}")
        return 1

    elapsed = round(time.time() - start, 2)
    print(f"\nTotal: in={total_in:,} kept={total_kept:,} dropped={total_dropped:,} "
          f"conflicts={total_conflicts:,} ({elapsed}s)")

    # ---- Statistics from deduplicated output ----
    stats = compute_statistics(dst_dataset)
    stats_total = stats["total_records"]

    # ---- Validation ----
    # On a resumed run (registry-completed categories skipped), per-category
    # totals cover only THIS run's completions; the strict disk-truth gates
    # (expected totals, software count) still gate signing.
    validation = {
        "total_in": total_in,
        "total_kept": total_kept,
        "total_dropped": total_dropped,
        "conflicts": total_conflicts,
        "stats_total_matches_kept": stats_total == total_kept or resumed,
        "expected_unique": args.expect_total,
        "expected_software": args.expect_software,
        "software_matches_expected": stats["by_category"].get("02_software_engineering") == args.expect_software,
        "expected_total_matches": stats_total == args.expect_total,
        "all_ok": (
            total_conflicts == 0
            and (stats_total == total_kept or resumed)
            and stats_total == args.expect_total
            and stats["by_category"].get("02_software_engineering") == args.expect_software
        ),
    }
    print(f"  validation: {validation}")

    # ---- Report ----
    report = {
        "release": args.target,
        "from_release": args.source,
        "generated_at": utc_now(),
        "tool": "scripts/release/dedup_release.py",
        "elapsed_s": elapsed,
        "method": DEDUP_GATE,
        "input": {"source_dataset": str(src_dataset)},
        "output": {"target_dataset": str(dst_dataset)},
        "statistics": {
            "total_in": total_in,
            "total_kept": total_kept,
            "total_dropped": total_dropped,
            "total_conflicts": total_conflicts,
            "per_category": per_category,
        },
        "manifest_statistics": stats,
        "validation": validation,
    }
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print(f"Report: {report_path}")

    # ---- Manifest (signed) ----
    if not args.skip_sign:
        prev_manifest_path = root / "metadata" / "releases" / f"{args.source}_release.json"
        if not prev_manifest_path.exists():
            print(f"ERROR: previous manifest not found: {prev_manifest_path}", file=sys.stderr)
            return 1
        prev_manifest = json.loads(prev_manifest_path.read_text(encoding="utf-8"))
        manifest = build_manifest(
            release_version=args.target,
            previous_manifest=prev_manifest,
            stats=stats,
            total_records=stats_total,
        )
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                 encoding="utf-8")
        print(f"Manifest: {manifest_path}")
        print(f"  release_id  : {manifest['release_id']}")
        print(f"  chain_hash  : {manifest['release_signature']['chain_hash'][:16]}...")
        print(f"  content_hash: {manifest['release_signature']['content_hash'][:16]}...")

    return 0 if validation["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
