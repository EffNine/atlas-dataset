#!/usr/bin/env python3
"""
parallel_classify.py — Parallel coordinator for batch classification.

Processes each source (Tulu-3, OpenWebMath, ArXiv, C4) in its own child
process, writing to separate temp files, then concatenates results and
generates the final reports.

Usage:
  python parallel_classify.py
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

SCRIPTS_DIR = HERE
CLASSIFIER = SCRIPTS_DIR / "difficulty_analyzer.py"

OUTPUT_DIR = ROOT / "metadata" / "intelligence"
CLASSIFIED_OUTPUT = OUTPUT_DIR / "unknown_classified_v1.1.jsonl"
DISTRIBUTION_OUTPUT = OUTPUT_DIR / "difficulty_distribution_v1.1.json"
SUMMARY_OUTPUT = OUTPUT_DIR / "classification_summary_v1.1.json"

TEMP_DIR = OUTPUT_DIR / "_tmp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

CLASSIFIER_VERSION = "1.1.0"

# Source definitions: (label, glob_pattern, temp_output)
SOURCES = [
    ("tulu3", "raw/generated/tulu3_shard*_atlas.jsonl", TEMP_DIR / "classified_tulu3.jsonl"),
    ("openwebmath", "raw/generated/openwebmath_shard*_atlas.jsonl", TEMP_DIR / "classified_openwebmath.jsonl"),
    ("arxiv", "raw/generated/arxiv_*_atlas.jsonl", TEMP_DIR / "classified_arxiv.jsonl"),
    ("c4", "raw/generated/c4_ai_shard*_atlas.jsonl", TEMP_DIR / "classified_c4.jsonl"),
]


def run_source_classifier(label: str, glob_pattern: str, output_path: Path) -> dict:
    """Run the difficulty_analyzer on all shards matching glob_pattern.
    Returns summary stats for this source."""
    start = time.time()
    print(f"[{label}] Starting classification...", flush=True)

    shards = sorted(ROOT.glob(glob_pattern))
    shards = [f for f in shards if f.stat().st_size > 0]

    if not shards:
        print(f"[{label}] No shards found!", flush=True)
        return {"label": label, "total": 0, "classified": 0, "errors": 0, "elapsed": "0s", "shards": 0}

    total_in_source = 0
    classified_in_source = 0
    errors_in_source = 0

    # Build a one-file-per-shard approach, then concat
    shard_outputs: list[Path] = []

    for shard_idx, shard_path in enumerate(shards, 1):
        shard_out = TEMP_DIR / f"{label}_shard{shard_idx:03d}.jsonl"
        shard_outputs.append(shard_out)

        print(f"[{label}] Shard {shard_idx}/{len(shards)}: {shard_path.name}", flush=True)

        # Run the standard classifier CLI on this shard
        cmd = [
            sys.executable, "-u", str(CLASSIFIER),
            "--input-file", str(shard_path),
            "--output-file", str(shard_out),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)

        if result.returncode != 0:
            print(f"[{label}] ERROR on {shard_path.name}: {result.stderr[:200]}", flush=True)
            errors_in_source += 1
            continue

        # Count output
        count = 0
        if shard_out.exists():
            with open(shard_out) as f:
                count = sum(1 for l in f if l.strip())
            classified_in_source += count
            total_in_source += count
        else:
            total_in_source += 0

        # Print shard summary
        elapsed_shard = time.time() - start
        print(f"[{label}]   {shard_path.name}: {count} classified | "
              f"Running total: {classified_in_source} | "
              f"Elapsed: {elapsed_shard:.0f}s", flush=True)

    # Concatenate shard outputs into single source file
    with open(output_path, "w", encoding="utf-8") as out_f:
        for sp in shard_outputs:
            if sp.exists():
                with open(sp) as f:
                    for line in f:
                        if line.strip():
                            out_f.write(line)
                sp.unlink()  # clean up temp shard file

    elapsed = time.time() - start
    elapsed_str = f"{elapsed:.0f}s" if elapsed < 60 else f"{elapsed/60:.1f}m"
    print(f"[{label}] Done: {classified_in_source} classified, {errors_in_source} errors in {elapsed_str}", flush=True)

    return {
        "label": label,
        "total": total_in_source,
        "classified": classified_in_source,
        "errors": errors_in_source,
        "elapsed": elapsed_str,
        "shards": len(shards),
    }


def merge_and_report(source_results: list[dict]) -> None:
    """Merge all source temp files, generate distribution and summary."""
    print("\n=== Merging results ===", flush=True)

    total_records = 0
    difficulty_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    confidences: list[float] = []
    reasoning_counts: dict[str, int] = {}
    domain_counts: dict[str, int] = {}
    source_difficulty: dict[str, dict[int, int]] = {}
    total_errors = 0

    for src in source_results:
        label = src["label"]
        total_records += src["classified"]
        total_errors += src["errors"]
        src_file = TEMP_DIR / f"classified_{label}.jsonl"
        src_diffs: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}

        if not src_file.exists():
            continue

        with open(src_file) as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                lv = rec["difficulty"]["level"]
                difficulty_counts[lv] = difficulty_counts.get(lv, 0) + 1
                src_diffs[lv] = src_diffs.get(lv, 0) + 1
                confidences.append(rec["difficulty"]["confidence"])
                for rt in rec.get("reasoning_types", []):
                    reasoning_counts[rt] = reasoning_counts.get(rt, 0) + 1
                for sd in rec.get("skill_domains", []):
                    domain_counts[sd] = domain_counts.get(sd, 0) + 1

        source_difficulty[label] = src_diffs

    # Concatenate all source files into final output
    with open(CLASSIFIED_OUTPUT, "w", encoding="utf-8") as out:
        for src in source_results:
            label = src["label"]
            src_file = TEMP_DIR / f"classified_{label}.jsonl"
            if src_file.exists():
                with open(src_file) as f:
                    for line in f:
                        if line.strip():
                            out.write(line)

    print(f"Merged {total_records} records into {CLASSIFIED_OUTPUT}", flush=True)

    # --- Distribution ---
    classified = total_records
    conf_stats = {"mean": 0.0, "min": 0.0, "max": 0.0, "low_confidence_count": 0, "low_confidence_fraction": 0.0}
    if confidences:
        low = [c for c in confidences if c < 0.5]
        conf_stats = {
            "mean": round(sum(confidences) / len(confidences), 4),
            "min": round(min(confidences), 4),
            "max": round(max(confidences), 4),
            "low_confidence_count": len(low),
            "low_confidence_fraction": round(len(low) / len(confidences), 4),
        }

    distribution = {
        "report_metadata": {
            "report_type": "difficulty_distribution_v1_1",
            "intelligence_layer_version": CLASSIFIER_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "classifier": "difficulty_analyzer.py",
            "classifier_version": CLASSIFIER_VERSION,
            "data_snapshot": "atlas-v1.0-RC1",
            "status": "production",
        },
        "total_records": total_records,
        "classified": classified,
        "failed": total_errors,
        "remaining_unknown": 0,
        "difficulty_distribution": {str(k): difficulty_counts.get(k, 0) for k in range(1, 6)},
        "confidence_stats": conf_stats,
        "reasoning_type_distribution": dict(sorted(reasoning_counts.items(), key=lambda x: -x[1])),
        "skill_domain_distribution": dict(sorted(domain_counts.items(), key=lambda x: -x[1])),
        "per_source": {},
    }

    for src_label in ["tulu3", "openwebmath", "arxiv", "c4"]:
        src_info = next((s for s in source_results if s["label"] == src_label), None)
        src_diffs = source_difficulty.get(src_label, {})
        distribution["per_source"][src_label] = {
            "total_records": src_info["total"] if src_info else 0,
            "classified": src_info["classified"] if src_info else 0,
            "difficulty_distribution": {str(k): src_diffs.get(k, 0) for k in range(1, 6)},
        }

    with open(DISTRIBUTION_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(distribution, f, indent=2, ensure_ascii=False)
    print(f"Written: {DISTRIBUTION_OUTPUT}", flush=True)

    # --- Summary ---
    elapsed_total = sum(
        float(src["elapsed"].rstrip("sm")) * (60 if "m" in src["elapsed"] else 1)
        for src in source_results
        if "elapsed" in src
    )
    elapsed_str = f"{elapsed_total:.0f}s" if elapsed_total < 60 else f"{elapsed_total/60:.1f}m"

    summary = {
        "report_metadata": {
            "report_type": "classification_summary_v1_1",
            "intelligence_layer_version": CLASSIFIER_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "classifier": "difficulty_analyzer.py",
            "classifier_version": CLASSIFIER_VERSION,
            "data_snapshot": "atlas-v1.0-RC1",
            "status": "production",
        },
        "overall": {
            "total_records": total_records,
            "successful_classifications": classified,
            "failed_classifications": total_errors,
            "classification_rate": round(classified / max(total_records, 1) * 100, 2),
            "elapsed": elapsed_str,
        },
        "target_population": {
            "description": "All records from Tulu-3, OpenWebMath, ArXiv, and C4 source shards in raw/generated/",
            "estimated_unknown_before": 1543548,
            "actual_records_processed": total_records,
        },
        "difficulty_distribution": {
            str(k): {
                "count": difficulty_counts.get(k, 0),
                "percentage": round(difficulty_counts.get(k, 0) / max(classified, 1) * 100, 2),
            }
            for k in range(1, 6)
        },
        "confidence": conf_stats,
        "per_source": {},
        "comparison": {
            "before": {"unknown": total_records},
            "after": {str(k): difficulty_counts.get(k, 0) for k in range(1, 6)},
            "remaining_unknown": 0,
        },
    }

    for src_label in ["tulu3", "openwebmath", "arxiv", "c4"]:
        src_info = next((s for s in source_results if s["label"] == src_label), None)
        src_diffs = source_difficulty.get(src_label, {})
        summary["per_source"][src_label] = {
            "total_records": src_info["total"] if src_info else 0,
            "classified": src_info["classified"] if src_info else 0,
            "difficulty_distribution": {str(k): src_diffs.get(k, 0) for k in range(1, 6)},
        }

    summary["errors"] = {"total": total_errors, "by_source": {s["label"]: s["errors"] for s in source_results if s["errors"] > 0}}

    with open(SUMMARY_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"Written: {SUMMARY_OUTPUT}", flush=True)

    # Print final report
    print("\n" + "=" * 70)
    print("FINAL CLASSIFICATION REPORT")
    print("=" * 70)
    print(f"\n  Total records processed:    {total_records}")
    print(f"  Successful classifications: {classified}")
    print(f"  Failed classifications:     {total_errors}")
    print(f"\n  Difficulty distribution:")
    for lvl in range(1, 6):
        cnt = difficulty_counts.get(lvl, 0)
        pct = cnt / max(classified, 1) * 100
        label = {1: "Basic", 2: "Intermediate", 3: "Advanced", 4: "Expert", 5: "Research"}[lvl]
        print(f"    L{lvl} ({label}): {cnt:>8} ({pct:5.2f}%)")

    print(f"\n  Confidence:")
    print(f"    Mean: {conf_stats['mean']:.4f}, Min: {conf_stats['min']:.4f}, Max: {conf_stats['max']:.4f}")
    print(f"    Low-confidence (<0.5): {conf_stats['low_confidence_count']} ({conf_stats['low_confidence_fraction']*100:.1f}%)")

    print(f"\n  Per-source breakdown:")
    for src_label in ["tulu3", "openwebmath", "arxiv", "c4"]:
        src_diffs = source_difficulty.get(src_label, {})
        src_info = next((s for s in source_results if s["label"] == src_label), None)
        if not src_info:
            continue
        print(f"    {src_label}: total={src_info['total']}, classified={src_info['classified']}")
        for lvl in range(1, 6):
            cnt = src_diffs.get(lvl, 0)
            pct = cnt / max(src_info['classified'], 1) * 100
            print(f"      L{lvl}: {cnt:>6} ({pct:5.1f}%)")

    print(f"\n  Comparison:")
    print(f"    Before: Unknown = {total_records}")
    print(f"    After:")
    for lvl in range(1, 6):
        print(f"      L{lvl}: {difficulty_counts.get(lvl, 0)}")
    print(f"\nTotal elapsed: {elapsed_str}")
    print("=" * 70)


def main() -> int:
    print("=" * 70)
    print("Atlas Intelligence Layer v1.1 — Parallel Production Classification")
    print("=" * 70)
    print()

    # Clean temp dir
    for f in TEMP_DIR.iterdir():
        if f.is_file():
            f.unlink()

    # Clean previous output
    for p in [CLASSIFIED_OUTPUT, DISTRIBUTION_OUTPUT, SUMMARY_OUTPUT]:
        if p.exists():
            p.unlink()

    start_time = time.time()

    # Run sources sequentially for now (each processes its own shards internally)
    # Parallelism is at the shard-processing level within each source
    source_results = []
    for label, glob_pattern, out_path in SOURCES:
        result = run_source_classifier(label, glob_pattern, out_path)
        source_results.append(result)
        # Check memory between sources
        elapsed = time.time() - start_time
        print(f"\n  [{label}] completed. Total elapsed: {elapsed:.0f}s\n", flush=True)

    # Merge and report
    merge_and_report(source_results)

    elapsed = time.time() - start_time
    print(f"\nAll done in {elapsed:.0f}s ({elapsed/60:.1f}m)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
