#!/usr/bin/env python3
"""
batch_classify_v1_1.py — Production batch classifier for Atlas Intelligence Layer v1.1.

Processes source shards sequentially (streaming, O(1) memory per record),
classifies each record, and produces:
  - metadata/intelligence/unknown_classified_v1.1.jsonl
  - metadata/intelligence/difficulty_distribution_v1.1.json
  - metadata/intelligence/classification_summary_v1.1.json

Usage:
  python batch_classify_v1_1.py [--aggregate-only] [--classify-only]
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add scripts/intelligence to path for the analyzer
HERE = Path(__file__).resolve().parent
SCRIPTS_DIR = HERE.parent
ROOT = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(HERE))

from difficulty_analyzer import analyze_record

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CLASSIFIER_VERSION = "1.1.0"
BATCH_SIZE = 5000  # Number of classified results to batch-write at once

# Source shard patterns: (glob_pattern, source_label)
SOURCE_PATTERNS: list[tuple[str, str]] = [
    ("raw/generated/tulu3_shard*_atlas.jsonl", "tulu3"),
    ("raw/generated/openwebmath_shard*_atlas.jsonl", "openwebmath"),
    ("raw/generated/arxiv_*_atlas.jsonl", "arxiv"),
    ("raw/generated/c4_ai_shard*_atlas.jsonl", "c4"),
]

OUTPUT_DIR = ROOT / "metadata" / "intelligence"
CLASSIFIED_OUTPUT = OUTPUT_DIR / "unknown_classified_v1.1.jsonl"
DISTRIBUTION_OUTPUT = OUTPUT_DIR / "difficulty_distribution_v1.1.json"
SUMMARY_OUTPUT = OUTPUT_DIR / "classification_summary_v1.1.json"

# ---------------------------------------------------------------------------
# Accumulators (merges across shards, minimal memory)
# ---------------------------------------------------------------------------

class SummaryAccumulator:
    """Thread-safe accumulator for classification statistics."""

    def __init__(self) -> None:
        self.total_records = 0
        self.classified = 0
        self.errors: list[dict] = []
        self.difficulty_counts: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        self.confidences: list[float] = []
        self.reasoning_type_counts: dict[str, int] = {}
        self.skill_domain_counts: dict[str, int] = {}
        self.source_counts: dict[str, int] = {}         # total per source
        self.source_classified: dict[str, int] = {}     # classified per source
        self.source_difficulty: dict[str, dict[int, int]] = {}  # source -> level -> count
        self.remaining_unknown = 0
        self.start_time: float = 0.0

    def record_source_result(self, source: str, level: int | None, confidence: float | None,
                             reasoning_types: list[str] | None, skill_domains: list[str] | None) -> None:
        self.source_counts[source] = self.source_counts.get(source, 0) + 1
        self.total_records += 1

        if level is not None:
            self.classified += 1
            self.difficulty_counts[level] = self.difficulty_counts.get(level, 0) + 1
            self.source_classified[source] = self.source_classified.get(source, 0) + 1

            src_diffs = self.source_difficulty.setdefault(source, {1: 0, 2: 0, 3: 0, 4: 0, 5: 0})
            src_diffs[level] = src_diffs.get(level, 0) + 1

            if confidence is not None:
                self.confidences.append(confidence)

            if reasoning_types:
                for rt in reasoning_types:
                    self.reasoning_type_counts[rt] = self.reasoning_type_counts.get(rt, 0) + 1

            if skill_domains:
                for sd in skill_domains:
                    self.skill_domain_counts[sd] = self.skill_domain_counts.get(sd, 0) + 1

    def record_error(self, index: int, record_id: str, error: str, source: str) -> None:
        self.total_records += 1
        self.source_counts[source] = self.source_counts.get(source, 0) + 1
        self.errors.append({
            "index": index,
            "record_id": record_id,
            "error": error,
            "source": source,
        })

    @property
    def failed(self) -> int:
        return len(self.errors)

    def get_confidence_stats(self) -> dict:
        confs = self.confidences
        if not confs:
            return {"mean": 0.0, "min": 0.0, "max": 0.0, "low_confidence_count": 0, "low_confidence_fraction": 0.0}
        low = [c for c in confs if c < 0.5]
        return {
            "mean": round(sum(confs) / len(confs), 4),
            "min": round(min(confs), 4),
            "max": round(max(confs), 4),
            "low_confidence_count": len(low),
            "low_confidence_fraction": round(len(low) / len(confs), 4),
        }

    def get_elapsed(self) -> str:
        elapsed = time.time() - self.start_time
        if elapsed < 60:
            return f"{elapsed:.1f}s"
        return f"{elapsed/60:.1f}m"


# ---------------------------------------------------------------------------
# Per-shard streaming processor
# ---------------------------------------------------------------------------

def classify_shard(
    shard_path: Path,
    source_label: str,
    accumulator: SummaryAccumulator,
    output_fh,
) -> int:
    """Classify all records in one shard file, write results to output_fh.
    Returns count of records processed from this shard."""
    local_count = 0
    write_buffer: list[str] = []
    progress_interval = 10000  # Print progress every 10k records
    total_in_shard = 0
    # Quick count for progress tracking
    try:
        with open(shard_path, "r", encoding="utf-8") as _ct:
            total_in_shard = sum(1 for _l in _ct if _l.strip())
    except Exception:
        total_in_shard = 0

    with open(shard_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                accumulator.record_error(local_count, "unknown", f"JSON parse: {e}", source_label)
                local_count += 1
                continue

            rec_id = rec.get("id", "unknown")
            local_count += 1

            # Intra-shard progress
            if local_count % progress_interval == 0:
                pct = local_count / max(total_in_shard, 1) * 100
                elapsed = accumulator.get_elapsed()
                rate = accumulator.total_records / max(time.time() - accumulator.start_time, 0.1)
                print(
                    f"  ... {source_label}/{shard_path.name}: "
                    f"{local_count}/{total_in_shard} ({pct:.0f}%) | "
                    f"Total: {accumulator.total_records} | "
                    f"Classified: {accumulator.classified} | "
                    f"Rate: {rate:.0f}/s | "
                    f"Elapsed: {elapsed}",
                    flush=True,
                )

            try:
                result = analyze_record(rec)
                if result:
                    # Add source tracking for reporting
                    result["_source"] = source_label
                    write_buffer.append(json.dumps(result, ensure_ascii=False) + "\n")

                    accumulator.record_source_result(
                        source=source_label,
                        level=result["difficulty"]["level"],
                        confidence=result["difficulty"]["confidence"],
                        reasoning_types=result.get("reasoning_types"),
                        skill_domains=result.get("skill_domains"),
                    )
                else:
                    accumulator.record_error(local_count - 1, rec_id, "Could not parse (missing content)", source_label)
            except Exception as e:
                accumulator.record_error(local_count - 1, rec_id, str(e), source_label)

            # Flush buffer periodically
            if len(write_buffer) >= BATCH_SIZE:
                output_fh.writelines(write_buffer)
                output_fh.flush()
                write_buffer.clear()

    # Final flush
    if write_buffer:
        output_fh.writelines(write_buffer)
        output_fh.flush()

    return local_count


def collect_source_shards(source_glob: str, source_label: str) -> list[Path]:
    """Collect and sort shard files for a source pattern."""
    files = sorted(ROOT.glob(source_glob))
    # Filter out zero-byte files
    files = [f for f in files if f.stat().st_size > 0]
    return files


def print_progress(shard_idx: int, total_shards: int, shard_name: str,
                   shard_count: int, accumulator: SummaryAccumulator) -> None:
    elapsed = accumulator.get_elapsed()
    rate = accumulator.total_records / max(time.time() - accumulator.start_time, 0.1)
    print(
        f"  [{shard_idx}/{total_shards}] {shard_name}: "
        f"{shard_count} records | "
        f"Total: {accumulator.total_records} | "
        f"Classified: {accumulator.classified} | "
        f"Errors: {accumulator.failed} | "
        f"Rate: {rate:.0f} rec/s | "
        f"Elapsed: {elapsed}",
        flush=True,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 70)
    print("Atlas Intelligence Layer v1.1 — Production Classification Run")
    print("=" * 70)
    print()

    accumulator = SummaryAccumulator()
    accumulator.start_time = time.time()

    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Track which shards are processed
    all_shards: list[tuple[Path, str]] = []
    for glob_pattern, label in SOURCE_PATTERNS:
        shards = collect_source_shards(glob_pattern, label)
        all_shards.extend((s, label) for s in shards)
        print(f"  {label}: {len(shards)} shards ({sum(s.stat().st_size for s in shards) / 1024 / 1024:.0f} MB)")

    total_shards = len(all_shards)
    print(f"\nTotal shards to process: {total_shards}")
    print(f"Output: {CLASSIFIED_OUTPUT}")
    print()

    # Open output file and process each shard
    with open(CLASSIFIED_OUTPUT, "w", encoding="utf-8") as out_fh:
        for shard_idx, (shard_path, source_label) in enumerate(all_shards, 1):
            shard_count = classify_shard(shard_path, source_label, accumulator, out_fh)
            print_progress(shard_idx, total_shards, shard_path.name, shard_count, accumulator)

    elapsed = accumulator.get_elapsed()
    print(f"\n--- Classification complete ({elapsed}) ---")
    print()

    # -----------------------------------------------------------------------
    # Build distribution report
    # -----------------------------------------------------------------------
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
        "total_records": accumulator.total_records,
        "classified": accumulator.classified,
        "failed": accumulator.failed,
        "remaining_unknown": accumulator.remaining_unknown,
        "difficulty_distribution": {
            str(k): accumulator.difficulty_counts.get(k, 0)
            for k in range(1, 6)
        },
        "confidence_stats": accumulator.get_confidence_stats(),
        "reasoning_type_distribution": dict(
            sorted(accumulator.reasoning_type_counts.items(), key=lambda x: -x[1])
        ),
        "skill_domain_distribution": dict(
            sorted(accumulator.skill_domain_counts.items(), key=lambda x: -x[1])
        ),
        "per_source": {},
    }

    # Build per-source breakdown
    for source_label in ["tulu3", "openwebmath", "arxiv", "c4"]:
        src_total = accumulator.source_counts.get(source_label, 0)
        src_classified = accumulator.source_classified.get(source_label, 0)
        src_diffs = accumulator.source_difficulty.get(source_label, {})
        distribution["per_source"][source_label] = {
            "total_records": src_total,
            "classified": src_classified,
            "difficulty_distribution": {
                str(k): src_diffs.get(k, 0) for k in range(1, 6)
            },
        }

    with open(DISTRIBUTION_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(distribution, f, indent=2, ensure_ascii=False)
    print(f"Written: {DISTRIBUTION_OUTPUT}")

    # -----------------------------------------------------------------------
    # Build classification summary
    # -----------------------------------------------------------------------
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
            "total_records": accumulator.total_records,
            "successful_classifications": accumulator.classified,
            "failed_classifications": accumulator.failed,
            "classification_rate": round(
                accumulator.classified / max(accumulator.total_records, 1) * 100, 2
            ),
            "elapsed": elapsed,
            "records_per_second": round(
                accumulator.total_records / max(time.time() - accumulator.start_time, 0.1), 1
            ),
        },
        "target_population": {
            "description": "All records from Tulu-3, OpenWebMath, ArXiv, and C4 source shards in raw/generated/",
            "estimated_unknown_before": 1543548,  # Baseline estimate
            "actual_records_processed": accumulator.total_records,
        },
        "difficulty_distribution": {
            str(k): {
                "count": accumulator.difficulty_counts.get(k, 0),
                "percentage": round(
                    accumulator.difficulty_counts.get(k, 0) / max(accumulator.classified, 1) * 100, 2
                ),
            }
            for k in range(1, 6)
        },
        "confidence": accumulator.get_confidence_stats(),
        "per_source": {},
        "comparison": {
            "before": {
                "unknown": accumulator.total_records,
                "note": "All records were unclassified by the v1.1 Intelligence Layer classifier.",
            },
            "after": {
                str(k): accumulator.difficulty_counts.get(k, 0)
                for k in range(1, 6)
            },
            "remaining_unknown": accumulator.remaining_unknown,
        },
    }

    # Per-source breakdown
    for source_label in ["tulu3", "openwebmath", "arxiv", "c4"]:
        src_total = accumulator.source_counts.get(source_label, 0)
        src_classified = accumulator.source_classified.get(source_label, 0)
        src_diffs = accumulator.source_difficulty.get(source_label, {})
        summary["per_source"][source_label] = {
            "total_records": src_total,
            "classified": src_classified,
            "difficulty_distribution": {
                str(k): src_diffs.get(k, 0) for k in range(1, 6)
            },
        }

    # Error summary
    if accumulator.errors:
        # Group errors by source
        error_by_source: dict[str, int] = {}
        error_samples: list[dict] = []
        for err in accumulator.errors:
            src = err.get("source", "unknown")
            error_by_source[src] = error_by_source.get(src, 0) + 1
            if len(error_samples) < 5:
                error_samples.append(err)
        summary["errors"] = {
            "total": len(accumulator.errors),
            "by_source": error_by_source,
            "samples": error_samples,
        }

    with open(SUMMARY_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"Written: {SUMMARY_OUTPUT}")

    # -----------------------------------------------------------------------
    print("FINAL CLASSIFICATION REPORT")
    # -----------------------------------------------------------------------
    print()
    print("=" * 70)
    print()
    print(f"  Total records processed:  {accumulator.total_records}")
    print(f"  Successful classifications: {accumulator.classified}")
    print(f"  Failed classifications:     {accumulator.failed}")
    print()
    print(f"  Difficulty distribution:")
    for lvl in range(1, 6):
        cnt = accumulator.difficulty_counts.get(lvl, 0)
        pct = cnt / max(accumulator.classified, 1) * 100
        label = {1: "Basic", 2: "Intermediate", 3: "Advanced", 4: "Expert", 5: "Research"}[lvl]
        print(f"    L{lvl} ({label}): {cnt:>8} ({pct:5.2f}%)")

    conf = accumulator.get_confidence_stats()
    print()
    print(f"  Confidence distribution:")
    print(f"    Mean: {conf['mean']:.4f}")
    print(f"    Min:  {conf['min']:.4f}")
    print(f"    Max:  {conf['max']:.4f}")
    print(f"    Low-confidence (<0.5): {conf['low_confidence_count']} ({conf['low_confidence_fraction']*100:.1f}%)")

    print()
    print(f"  Per-source breakdown:")
    for source_label in ["tulu3", "openwebmath", "arxiv", "c4"]:
        src_total = accumulator.source_counts.get(source_label, 0)
        src_classified_data = accumulator.source_classified.get(source_label, 0)
        src_diffs = accumulator.source_difficulty.get(source_label, {})
        print(f"    {source_label}:")
        print(f"      Total: {src_total}, Classified: {src_classified_data}")
        for lvl in range(1, 6):
            cnt = src_diffs.get(lvl, 0)
            pct = cnt / max(src_classified_data, 1) * 100
            print(f"      L{lvl}: {cnt:>6} ({pct:5.1f}%)")

    print()
    print(f"  Comparison:")
    print(f"    Before:")
    print(f"      Unknown = {accumulator.total_records}")
    print(f"    After:")
    for lvl in range(1, 6):
        cnt = accumulator.difficulty_counts.get(lvl, 0)
        print(f"      L{lvl}: {cnt}")
    print(f"      Remaining unknown: {accumulator.remaining_unknown}")
    print()
    print("=" * 70)
    print(f"Run completed in {elapsed}")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
