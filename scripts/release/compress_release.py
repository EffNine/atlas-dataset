#!/usr/bin/env python3
"""Atlas release compression pipeline.

Streams Atlas JSONL shards (raw/generated/*.jsonl) and writes per-category
compressed JSONL.ZST files under releases/<release>/dataset/<category>/.

Records are routed by their ``category`` field (NOT by filename), because
several shards contain mixed categories (e.g. ultrafeedback_atlas.jsonl
spans 01_foundation and 08_creative_knowledge).

Features:
  - parallel compression (ProcessPoolExecutor, configurable workers)
  - streaming, O(1) memory per worker
  - preserves original filenames inside each category folder
  - verifies every output file (decompress + line count)
  - writes a compression report + statistics.json

Usage:
  .venv-release/bin/python scripts/release/compress_release.py \
      --release v1.0-RC1 \
      --input raw/generated \
      --pattern '*_atlas.jsonl' \
      --workers 2 \
      --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from common import (
    CATEGORIES,
    DEFAULT_ZSTD_LEVEL,
    human_bytes,
    iter_jsonl,
    open_zstd_writer,
    count_jsonl_zst,
    sha256_file,
    utc_now,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _route_shard(args: dict[str, Any]) -> dict[str, Any]:
    """Compress one shard, routing each record by category.

    Runs inside a worker process, so it only takes/returns JSON-safe values.
    """
    input_path = Path(args["input_path"])
    out_root = Path(args["out_root"])
    level = args["level"]

    start = time.time()
    writers: dict[str, Any] = {}
    counts: dict[str, int] = {}
    total = 0
    errors: list[str] = []

    try:
        for rec in iter_jsonl(input_path):
            cat = rec.get("category")
            if cat not in CATEGORIES:
                errors.append(
                    f"record {rec.get('id', '?')}: unknown category {cat!r}"
                )
                continue
            if cat not in writers:
                out_file = out_root / cat / f"{input_path.stem}.jsonl.zst"
                writers[cat] = open_zstd_writer(out_file, level=level)
                counts[cat] = 0
            line = json.dumps(rec, ensure_ascii=False)
            writers[cat].write((line + "\n").encode("utf-8"))
            counts[cat] += 1
            total += 1
    except Exception as exc:  # pragma: no cover - defensive
        errors.append(f"read error: {exc}")
    finally:
        for w in writers.values():
            try:
                w.close()
            except Exception:
                pass

    # Verify each output file (decompress + count) in the same worker.
    verified: dict[str, dict[str, Any]] = {}
    for cat, n in counts.items():
        out_file = out_root / cat / f"{input_path.stem}.jsonl.zst"
        try:
            actual = count_jsonl_zst(out_file)
            verified[cat] = {
                "expected": n,
                "actual": actual,
                "ok": actual == n,
                "bytes": out_file.stat().st_size,
                "sha256": sha256_file(out_file),
            }
        except Exception as exc:  # pragma: no cover - defensive
            verified[cat] = {
                "expected": n,
                "actual": -1,
                "ok": False,
                "bytes": -1,
                "sha256": "",
                "error": str(exc),
            }

    return {
        "input": input_path.name,
        "input_bytes": input_path.stat().st_size,
        "input_records": total,
        "by_category": counts,
        "verified": verified,
        "errors": errors,
        "elapsed_s": round(time.time() - start, 2),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Compress Atlas JSONL shards into per-category JSONL.ZST.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--release", default="v1.0-RC1", help="Release version tag.")
    ap.add_argument(
        "--input",
        default=str(REPO_ROOT / "raw" / "generated"),
        help="Directory containing JSONL shards.",
    )
    ap.add_argument(
        "--pattern",
        default="*_atlas.jsonl",
        help="Glob pattern for shard files inside --input.",
    )
    ap.add_argument(
        "--output",
        default=None,
        help="Release root (default: <repo>/releases/<release>).",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=2,
        help="Parallel worker processes (keep low on 8GB RAM machines).",
    )
    ap.add_argument(
        "--level", type=int, default=DEFAULT_ZSTD_LEVEL, help="zstd level (1-22)."
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Only list shards and plan; write nothing.",
    )
    ap.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip shards whose output files already exist and verify OK.",
    )
    args = ap.parse_args(argv)

    release = args.release
    release_root = (
        Path(args.output) if args.output else REPO_ROOT / "releases" / release
    )
    out_root = release_root / "dataset"
    in_dir = Path(args.input)
    shards = sorted(in_dir.glob(args.pattern))

    if not shards:
        print(f"ERROR: no shards matched {in_dir / args.pattern}")
        return 2
    print(
        f"Atlas release compression | release={release} | shards={len(shards)} "
        f"| workers={args.workers} | level={args.level} | dry_run={args.dry_run}"
    )

    if args.dry_run:
        print("\nDry run — no files written. Planned routing:")
        for shard in shards:
            # Peek at the first record for a quick category preview (best effort).
            preview = "?"
            try:
                with shard.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            preview = json.loads(line).get("category", "?")
                            break
            except Exception:
                pass
            print(f"  {shard.name}  (preview category: {preview})")
        print(f"\nTotal planned inputs: {len(shards)} shards")
        print(f"Output root: {out_root}")
        return 0

    tasks: list[dict[str, Any]] = []
    skipped = 0
    for shard in shards:
        # Skip existing outputs if the shard's files already verified.
        if args.skip_existing:
            existing_ok = True
            found_any = False
            # Look for any category outputs for this shard under out_root.
            for cat in CATEGORIES:
                out_file = out_root / cat / f"{shard.stem}.jsonl.zst"
                if out_file.exists():
                    found_any = True
                    try:
                        if count_jsonl_zst(out_file) < 0:
                            existing_ok = False
                            break
                    except Exception:
                        existing_ok = False
                        break
            if found_any and existing_ok:
                skipped += 1
                continue
        tasks.append(
            {
                "input_path": str(shard),
                "out_root": str(out_root),
                "level": args.level,
            }
        )

    if skipped:
        print(f"Skipping {skipped} already-compressed shards (--skip-existing).")
    if not tasks:
        print("Nothing to do — all shards already compressed.")
        return 0

    out_root.mkdir(parents=True, exist_ok=True)
    started = time.time()
    results: list[dict[str, Any]] = []
    if args.workers <= 1:
        for t in tasks:
            results.append(_route_shard(t))
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(_route_shard, t): t for t in tasks}
            for fut in as_completed(futures):
                results.append(fut.result())

    # Aggregate.
    total_records = 0
    total_in_bytes = 0
    total_out_bytes = 0
    cat_totals: dict[str, int] = {c: 0 for c in CATEGORIES}
    cat_bytes: dict[str, int] = {c: 0 for c in CATEGORIES}
    failures: list[dict[str, Any]] = []
    per_file: list[dict[str, Any]] = []

    for r in sorted(results, key=lambda x: x["input"]):
        total_records += r["input_records"]
        total_in_bytes += r["input_bytes"]
        for cat, n in r["by_category"].items():
            cat_totals[cat] += n
        for cat, v in r["verified"].items():
            cat_bytes[cat] += v["bytes"]
            total_out_bytes += v["bytes"]
            per_file.append(
                {
                    "file": f"dataset/{cat}/{Path(r['input']).stem}.jsonl.zst",
                    "category": cat,
                    "records": v["actual"],
                    "bytes": v["bytes"],
                    "sha256": v["sha256"],
                    "ok": v["ok"],
                }
            )
            if not v["ok"]:
                failures.append(
                    {
                        "shard": r["input"],
                        "category": cat,
                        "expected": v["expected"],
                        "actual": v["actual"],
                        "error": v.get("error"),
                    }
                )
        if r["errors"]:
            failures.append({"shard": r["input"], "errors": r["errors"]})

    elapsed = time.time() - started
    report = {
        "release": release,
        "generated_at": utc_now(),
        "tool": "scripts/release/compress_release.py",
        "zstd_level": args.level,
        "workers": args.workers,
        "shards_processed": len(results),
        "shards_skipped": skipped,
        "total_records": total_records,
        "total_input_bytes": total_in_bytes,
        "total_output_bytes": total_out_bytes,
        "compression_ratio": (
            round(total_in_bytes / total_out_bytes, 3) if total_out_bytes else 0
        ),
        "elapsed_s": round(elapsed, 2),
        "by_category": {
            c: {"records": cat_totals[c], "bytes": cat_bytes[c]}
            for c in CATEGORIES
        },
        "files": per_file,
        "failures": failures,
    }

    metadata_dir = release_root / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    (metadata_dir / "compression_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # statistics.json for the release (record counts per category).
    stats = {
        "release": release,
        "generated_at": utc_now(),
        "total_records": total_records,
        "by_category": cat_totals,
        "by_category_bytes": cat_bytes,
    }
    (metadata_dir / "statistics.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"\nCompressed {len(results)} shards in {elapsed:.1f}s")
    print(
        f"  input : {human_bytes(total_in_bytes)} ({total_records:,} records)"
    )
    print(f"  output: {human_bytes(total_out_bytes)}")
    print(
        f"  ratio : {report['compression_ratio']}x  "
        f"({human_bytes(total_in_bytes - total_out_bytes)} saved)"
    )
    print("\nPer-category:")
    print(f"  {'category':<28}{'records':>12}{'bytes':>14}")
    for c in CATEGORIES:
        if cat_totals[c] or cat_bytes[c]:
            print(
                f"  {c:<28}{cat_totals[c]:>12,}{human_bytes(cat_bytes[c]):>14}"
            )
    if failures:
        print(f"\nFAILURES: {len(failures)}")
        for f in failures[:10]:
            print(f"  {f}")
        return 1
    print(f"\nAll outputs verified OK. Report: {metadata_dir / 'compression_report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
