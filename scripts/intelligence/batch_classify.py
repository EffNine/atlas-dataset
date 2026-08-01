#!/usr/bin/env python3
"""
batch_classify.py — Reusable batch classification module for Atlas Intelligence Layer.

Processes source shards through the difficulty_analyzer, writes per-source
temp files, merges results, and generates distribution + summary reports.

Intended for reuse across releases (v1.x, v2.x, …). Each release pins the
version and optionally overrides defaults via keyword arguments.

Usage:
  # Command line — classify all known sources for a release
  python -m scripts.intelligence.batch_classify \\
      --root /path/to/atlas-dataset --release v2.0

  # As an importable module
  from scripts.intelligence.batch_classify import classify_source_shards, merge_and_report

  temp_files = classify_source_shards(...)
  merge_and_report(temp_files, root_path, release="v2.0")
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow running as `python -m scripts.intelligence.batch_classify`
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from difficulty_analyzer import process_file

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class SourceConfig:
    """Configuration for one data source to classify.

    Attributes:
        label: Short identifier (e.g. "tulu3", "openwebmath").
        glob_pattern: Glob relative to root_path (e.g. "raw/generated/tulu3_shard*_atlas.jsonl").
        description: Human-readable name (optional, used in logs).
    """
    label: str
    glob_pattern: str
    description: str = ""


DEFAULT_SOURCES: list[SourceConfig] = [
    SourceConfig("tulu3",      "raw/generated/tulu3_shard*_atlas.jsonl",          "Tulu-3 (6 shards)"),
    SourceConfig("openwebmath","raw/generated/openwebmath_shard*_atlas.jsonl",     "OpenWebMath (114 shards)"),
    SourceConfig("arxiv",      "raw/generated/arxiv_*_atlas.jsonl",                "ArXiv (3 shards)"),
    SourceConfig("c4",         "raw/generated/c4_ai_shard*_atlas.jsonl",           "C4 AI/ML (12 shards)"),
]

DEFAULT_CLASSIFIER_VERSION = "1.1.0"
DEFAULT_DATA_SNAPSHOT = "atlas-v1.0-RC1"

# ---------------------------------------------------------------------------
# Source shard classifier
# ---------------------------------------------------------------------------

def split_single_shard(
    shard: Path,
    tmp_dir: Path,
    n_chunks: int,
    label: str,
) -> list[Path]:
    """Split a single JSONL shard into n_chunks line-chunk files.

    Returns a list of chunk file paths in _tmp_shards, so the parallel
    shard path can process them with multiple workers. Chunks are named
    {label}_chunk{idx:04d}_{shard.name}.jsonl so the merge glob
    ({label}_*.jsonl) picks them up and cleanup removes them.

    Args:
        shard: The single input JSONL file.
        tmp_dir: Directory for chunk files (created if missing).
        n_chunks: Number of chunks to create.
        label: Source label for chunk filenames.

    Returns:
        List of chunk paths (may be [shard] if the file is tiny).
    """
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Count lines cheaply (one pass) to size chunks evenly
    line_count = 0
    with open(shard, "r", encoding="utf-8") as f:
        for _ in f:
            line_count += 1

    if line_count <= n_chunks:
        # File smaller than worker count — no point splitting
        return [shard]

    chunk_size = max(1, (line_count + n_chunks - 1) // n_chunks)  # ceil, exact chunk count
    chunks: list[Path] = []
    current: Path | None = None
    fh = None
    written = 0
    idx = 0

    # Strip the shard's .jsonl extension to avoid double-extension chunk names
    base = shard.name[:-len(".jsonl")] if shard.name.endswith(".jsonl") else shard.name

    try:
        with open(shard, "r", encoding="utf-8") as src:
            for line in src:
                if current is None or written >= chunk_size:
                    if fh is not None:
                        fh.close()
                    idx += 1
                    current = tmp_dir / f"{label}_chunk{idx:04d}_{base}.jsonl"
                    fh = open(current, "w", encoding="utf-8")
                    chunks.append(current)
                    written = 0
                fh.write(line)
                written += 1
    finally:
        if fh is not None:
            fh.close()

    return chunks


def classify_source_shards(
    root_path: str | Path,
    config: SourceConfig,
    output_path: str | Path,
    *,
    print_progress_interval: int = 20,
    shard_workers: int = 1,
) -> dict[str, Any]:
    """Classify all shards for one source by streaming through *process_file*.

    Args:
        root_path: Root of the atlas-dataset repository.
        config: Source configuration (label, glob pattern).
        output_path: Write classified JSONL records here.
        print_progress_interval: Print a progress line every N shards (0 = off).
        shard_workers: Parallel workers for shards within this source (1 = sequential).

    Returns:
        Stats dict with keys: label, total, classified, errors, elapsed, shards.
    """
    root = Path(root_path)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    shards = sorted(root.glob(config.glob_pattern))
    shards = [f for f in shards if f.stat().st_size > 0]

    if not shards:
        print(f"[{config.label}] No shards found for {config.glob_pattern}", flush=True)
        return {
            "label": config.label,
            "total": 0,
            "classified": 0,
            "errors": 0,
            "elapsed": "0s",
            "shards": 0,
        }

    label_str = config.description or config.label
    print(f"[{config.label}] {label_str}: {len(shards)} shards, {shard_workers} workers", flush=True)

    # Single-shard sources (e.g. swebench, mmlu) cannot use shard-level
    # parallelism — one worker does all the work. Split the single file into
    # line chunks and process them as virtual shards so multi-core speedup
    # applies to every source type. Per-source subdir keeps concurrent
    # sources (parallel_sources>1) from colliding.
    if shard_workers > 1 and len(shards) == 1:
        shards = split_single_shard(
            shards[0],
            out.parent / "_tmp_shards" / config.label,
            n_chunks=min(shard_workers, 64),
            label=config.label,
        )
        if len(shards) > 1:
            print(
                f"[{config.label}] split single file into {len(shards)} chunks "
                f"for {shard_workers} workers",
                flush=True,
            )

    total = 0
    total_errors = 0
    start = time.time()

    if shard_workers <= 1:
        # Sequential path: original behavior
        with open(out, "w", encoding="utf-8") as fh:
            for idx, shard in enumerate(shards, 1):
                t0 = time.time()
                _, _, results, errors = process_file(shard, None)

                for r in results:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                fh.flush()

                total += len(results)
                total_errors += len(errors)

                if print_progress_interval > 0 and (idx % print_progress_interval == 0 or idx == len(shards)):
                    elapsed = time.time() - t0
                    rate = len(results) / max(elapsed, 0.1)
                    total_elapsed = time.time() - start
                    print(
                        f"  [{idx}/{len(shards)}] {config.label}/{shard.name}: "
                        f"{len(results)} classified, {len(errors)} errors "
                        f"({elapsed:.0f}s, {rate:.0f}/s) "
                        f"[total: {total} in {total_elapsed:.0f}s]",
                        flush=True,
                    )
    else:
        # Parallel path: each worker gets a shard, writes to temp file, merge at end
        from concurrent.futures import ProcessPoolExecutor, as_completed

        # Per-source subdirectory so concurrent sources (parallel_sources>1)
        # never share/delete each other's in-flight chunk files.
        tmp_dir = out.parent / "_tmp_shards" / config.label
        tmp_dir.mkdir(parents=True, exist_ok=True)

        with ProcessPoolExecutor(max_workers=shard_workers) as pool:
            futures = {}
            for idx, shard in enumerate(shards, 1):
                tmp_path = tmp_dir / f"{config.label}_{idx:04d}_{shard.name}.jsonl"
                fut = pool.submit(_process_shard_worker, shard, tmp_path)
                futures[fut] = (idx, shard)

            for fut in as_completed(futures):
                idx, shard = futures[fut]
                try:
                    _, classified_count, error_count = fut.result()
                    total += classified_count
                    total_errors += error_count

                    if print_progress_interval > 0 and (idx % print_progress_interval == 0 or idx == len(shards)):
                        total_elapsed = time.time() - start
                        print(
                            f"  [{idx}/{len(shards)}] {config.label}/{shard.name}: "
                            f"{classified_count} classified, {error_count} errors "
                            f"[total: {total} in {total_elapsed:.0f}s]",
                            flush=True,
                        )
                except Exception as exc:
                    print(f"  [ERROR] {config.label}/{shard.name}: {exc}", file=sys.stderr, flush=True)
                    total_errors += 1

        # Merge temp files into final output
        with open(out, "w", encoding="utf-8") as fh:
            for tmp_file in sorted(tmp_dir.glob(f"{config.label}_*.jsonl")):
                with open(tmp_file, "r", encoding="utf-8") as tf:
                    for line in tf:
                        line = line.strip()
                        if line:
                            fh.write(line + "\n")

        # Remove ALL temp files (including stale files left by interrupted
        # runs of other sources) so rmdir() never hits Errno 39.
        for stale in tmp_dir.iterdir():
            try:
                stale.unlink()
            except OSError:
                pass
        try:
            tmp_dir.rmdir()
        except OSError:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

    elapsed = time.time() - start
    elapsed_str = f"{elapsed:.0f}s" if elapsed < 60 else f"{elapsed/60:.1f}m"
    print(
        f"[{config.label}] Done: {total} classified, {total_errors} errors "
        f"in {elapsed_str}",
        flush=True,
    )

    return {
        "label": config.label,
        "total": total,
        "classified": total,
        "errors": total_errors,
        "elapsed": elapsed_str,
        "shards": len(shards),
    }


def classify_source_shards_adaptive(
    root_path: str | Path,
    config: SourceConfig,
    output_path: str | Path,
    *,
    shard_workers: int = 1,
    scheduler_cfg: dict | None = None,
    print_progress_interval: int = 20,
    worker_id: str = "",
) -> dict[str, Any]:
    """Classify one source using the adaptive workload scheduler.

    Plans balanced tasks (whole shard or line-range chunk), runs them
    through ProcessPoolExecutor, tracks state in the task registry, and
    merges per-task outputs in deterministic order.

    Args:
        root_path: Repo root.
        config: Source configuration.
        output_path: Per-source classified output (merged).
        shard_workers: Max parallel workers.
        scheduler_cfg: Scheduler config (from load_scheduler_config).
        print_progress_interval: Progress print cadence.
        worker_id: Worker id for the registry.

    Returns:
        Stats dict (label, total, classified, errors, elapsed, shards).
    """
    from concurrent.futures import ProcessPoolExecutor, as_completed

    from adaptive_scheduler import (
        TaskRegistry,
        load_scheduler_config,
        plan_tasks,
        write_scheduler_report,
    )

    if scheduler_cfg is None:
        scheduler_cfg = load_scheduler_config()

    root = Path(root_path)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    shards = sorted(
        f for f in root.glob(config.glob_pattern) if f.stat().st_size > 0
    )
    if not shards:
        print(f"[{config.label}] No shards found for {config.glob_pattern}", flush=True)
        return {
            "label": config.label, "total": 0, "classified": 0,
            "errors": 0, "elapsed": "0s", "shards": 0,
        }

    worker_group = "stage2" if shard_workers >= 8 else "stage1"
    tasks = plan_tasks(config.label, shards, scheduler_cfg, worker_group)
    registry = TaskRegistry(root, worker_group)
    # Per-source subdirectory so concurrent sources (parallel_sources>1)
    # never share/delete each other's in-flight task outputs.
    tmp_dir = out.parent / "_tmp_shards" / config.label
    tmp_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"[{config.label}] adaptive: {len(shards)} shards -> {len(tasks)} tasks "
        f"({shard_workers} workers)",
        flush=True,
    )

    total = 0
    total_errors = 0
    start = time.time()
    split_ops = sum(1 for t in tasks if "chunk" in t.task_id)

    with ProcessPoolExecutor(max_workers=shard_workers) as pool:
        futures = {}
        for task in tasks:
            # Resume: skip completed, re-queue failed up to max_retries
            if registry.is_completed(task.task_id):
                continue
            if registry.is_failed(task.task_id) and registry.attempts(task.task_id) >= scheduler_cfg["max_retries"]:
                print(f"  [SKIP] {task.task_id} failed {scheduler_cfg['max_retries']}x", flush=True)
                continue
            tmp_path = tmp_dir / f"{task.task_id}.jsonl"
            registry.record(task, "running", worker_id=worker_id, output_file=str(tmp_path))
            futures[pool.submit(_process_task_worker, task.to_dict(), tmp_path)] = task

        for fut in as_completed(futures):
            task = futures[fut]
            try:
                total_records, classified_count, error_count = fut.result()
                total += classified_count
                total_errors += error_count
                registry.record(
                    task, "completed",
                    worker_id=worker_id,
                    output_file=str(tmp_dir / f"{task.task_id}.jsonl"),
                    record_count=classified_count,
                )
            except Exception as exc:
                total_errors += 1
                registry.record(task, "failed", worker_id=worker_id)
                print(f"  [ERROR] {task.task_id}: {exc}", file=sys.stderr, flush=True)

    # Merge per-task outputs in deterministic (sorted task_id) order
    with open(out, "w", encoding="utf-8") as fh:
        for task in sorted(tasks, key=lambda t: t.task_id):
            tmp_path = tmp_dir / f"{task.task_id}.jsonl"
            if not tmp_path.exists():
                continue
            with open(tmp_path, "r", encoding="utf-8") as tf:
                for line in tf:
                    line = line.strip()
                    if line:
                        fh.write(line + "\n")
            tmp_path.unlink()

    # Cleanup empty tmp dir
    try:
        tmp_dir.rmdir()
    except OSError:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    elapsed = time.time() - start
    elapsed_str = f"{elapsed:.0f}s" if elapsed < 60 else f"{elapsed/60:.1f}m"

    write_scheduler_report(
        root, worker_group, shards, tasks, registry,
        split_operations=split_ops,
    )

    print(
        f"[{config.label}] Done: {total} classified, {total_errors} errors "
        f"in {elapsed_str}",
        flush=True,
    )
    return {
        "label": config.label,
        "total": total,
        "classified": total,
        "errors": total_errors,
        "elapsed": elapsed_str,
        "shards": len(shards),
    }


def _process_shard_worker(shard: Path, output_path: Path) -> tuple[int, int, int]:
    """Worker function for parallel shard processing.

    Returns (total_records, classified_count, error_count).
    """
    _, _, results, errors = process_file(shard, None)

    with open(output_path, "w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    return len(results) + len(errors), len(results), len(errors)


def _process_task_worker(task: dict, output_path: Path) -> tuple[int, int, int]:
    """Worker function for adaptive scheduler tasks.

    A task covers a whole file (offset_end < 0) or a line range
    [offset_start, offset_end). Streaming — never modifies the input.

    Returns (total_records, classified_count, error_count).
    """
    from difficulty_analyzer import process_file_range

    input_file = Path(task["input_file"])
    offset_start = int(task.get("offset_start", 0))
    offset_end = int(task.get("offset_end", -1))

    if offset_end < 0:
        _, _, results, errors = process_file(input_file, None)
    else:
        _, _, results, errors = process_file_range(
            input_file, offset_start, offset_end, None
        )

    with open(output_path, "w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    return len(results) + len(errors), len(results), len(errors)


# ---------------------------------------------------------------------------
# Accumulator (collects stats across sources)
# ---------------------------------------------------------------------------

class SummaryAccumulator:
    """Accumulator that reads classified temp files to produce aggregated stats."""

    def __init__(self) -> None:
        self.total_records = 0
        self.classified = 0
        self.difficulty_counts: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        self.confidences: list[float] = []
        self.reasoning_type_counts: dict[str, int] = {}
        self.skill_domain_counts: dict[str, int] = {}
        self.source_classified: dict[str, int] = {}
        self.source_difficulty: dict[str, dict[int, int]] = {}
        self.source_results: dict[str, dict[str, Any]] = {}

    def ingest(self, source_results: list[dict], temp_dir: Path) -> None:
        """Read all classified temp files and accumulate stats."""
        for src in source_results:
            label = src["label"]
            self.total_records += src["classified"]
            self.classified += src["classified"]
            self.source_results[label] = src

            src_file = temp_dir / f"classified_{label}.jsonl"
            src_diffs: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}

            if not src_file.exists():
                print(f"  [WARN] Missing temp file for {label}: {src_file}", flush=True)
                continue

            with open(src_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    level = rec["difficulty"]["level"]
                    self.difficulty_counts[level] = self.difficulty_counts.get(level, 0) + 1
                    src_diffs[level] = src_diffs.get(level, 0) + 1
                    self.confidences.append(rec["difficulty"]["confidence"])
                    for rt in rec.get("reasoning_types", []):
                        self.reasoning_type_counts[rt] = self.reasoning_type_counts.get(rt, 0) + 1
                    for sd in rec.get("skill_domains", []):
                        self.skill_domain_counts[sd] = self.skill_domain_counts.get(sd, 0) + 1

            self.source_difficulty[label] = src_diffs
            self.source_classified[label] = sum(src_diffs.values())

    def get_confidence_stats(self) -> dict[str, Any]:
        confs = self.confidences
        if not confs:
            return {
                "mean": 0.0, "min": 0.0, "max": 0.0,
                "low_confidence_count": 0, "low_confidence_fraction": 0.0,
            }
        low = [c for c in confs if c < 0.5]
        return {
            "mean": round(sum(confs) / len(confs), 4),
            "min": round(min(confs), 4),
            "max": round(max(confs), 4),
            "low_confidence_count": len(low),
            "low_confidence_fraction": round(len(low) / len(confs), 4),
        }


# ---------------------------------------------------------------------------
# Merge and reporting
# ---------------------------------------------------------------------------

def merge_classified_files(
    source_results: list[dict],
    temp_dir: str | Path,
    merged_path: str | Path,
) -> int:
    """Concatenate per-source temp files into the final classified JSONL.

    Args:
        source_results: List of stats dicts (must have "label" key).
        temp_dir: Directory with per-source temp files.
        merged_path: Write the merged output here.

    Returns:
        Total records written.
    """
    temp = Path(temp_dir)
    merged = Path(merged_path)
    merged.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    with open(merged, "w", encoding="utf-8") as out:
        for src in source_results:
            label = src["label"]
            src_file = temp / f"classified_{label}.jsonl"
            if not src_file.exists():
                print(f"  [SKIP] {label} — temp file missing: {src_file}", flush=True)
                continue
            with open(src_file, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        out.write(line)
                        total += 1

    print(f"Merged {total} records into {merged}", flush=True)
    return total


def generate_distribution_report(
    accumulator: SummaryAccumulator,
    output_path: str | Path,
    *,
    classifier_version: str = DEFAULT_CLASSIFIER_VERSION,
    data_snapshot: str = DEFAULT_DATA_SNAPSHOT,
) -> None:
    """Generate the difficulty_distribution_v<release>.json report."""
    total_errors = sum(
        src.get("errors", 0) for src in accumulator.source_results.values()
    )

    report = {
        "report_metadata": {
            "report_type": "difficulty_distribution",
            "intelligence_layer_version": classifier_version,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "classifier": "difficulty_analyzer.py",
            "classifier_version": classifier_version,
            "data_snapshot": data_snapshot,
            "status": "production",
        },
        "total_records": accumulator.total_records,
        "classified": accumulator.classified,
        "failed": total_errors,
        "remaining_unknown": 0,
        "difficulty_distribution": {
            str(k): accumulator.difficulty_counts.get(k, 0) for k in range(1, 6)
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

    for label in accumulator.source_results:
        diffs = accumulator.source_difficulty.get(label, {})
        report["per_source"][label] = {
            "total_records": accumulator.source_results[label].get("total", 0),
            "classified": accumulator.source_classified.get(label, 0),
            "difficulty_distribution": {str(k): diffs.get(k, 0) for k in range(1, 6)},
        }

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"Written: {out}", flush=True)


def generate_summary_report(
    accumulator: SummaryAccumulator,
    output_path: str | Path,
    *,
    classifier_version: str = DEFAULT_CLASSIFIER_VERSION,
    data_snapshot: str = DEFAULT_DATA_SNAPSHOT,
) -> None:
    """Generate the classification_summary_v<release>.json report."""
    total_errors = sum(
        src.get("errors", 0) for src in accumulator.source_results.values()
    )
    classified = accumulator.classified
    difficulty_counts = accumulator.difficulty_counts

    report = {
        "report_metadata": {
            "report_type": "classification_summary",
            "intelligence_layer_version": classifier_version,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "classifier": "difficulty_analyzer.py",
            "classifier_version": classifier_version,
            "data_snapshot": data_snapshot,
            "status": "production",
        },
        "overall": {
            "total_records": accumulator.total_records,
            "successful_classifications": classified,
            "failed_classifications": total_errors,
            "classification_rate": round(
                classified / max(accumulator.total_records, 1) * 100, 2
            ),
        },
        "difficulty_distribution": {
            str(k): {
                "count": difficulty_counts.get(k, 0),
                "percentage": round(
                    difficulty_counts.get(k, 0) / max(classified, 1) * 100, 2
                ),
            }
            for k in range(1, 6)
        },
        "confidence": accumulator.get_confidence_stats(),
        "per_source": {},
        "comparison": {
            "before": {"unknown": accumulator.total_records},
            "after": {str(k): difficulty_counts.get(k, 0) for k in range(1, 6)},
            "remaining_unknown": 0,
        },
    }

    for label in accumulator.source_results:
        diffs = accumulator.source_difficulty.get(label, {})
        report["per_source"][label] = {
            "total_records": accumulator.source_results[label].get("total", 0),
            "classified": accumulator.source_classified.get(label, 0),
            "difficulty_distribution": {str(k): diffs.get(k, 0) for k in range(1, 6)},
        }

    # Error summary
    error_by_source: dict[str, int] = {}
    for src in accumulator.source_results.values():
        if src.get("errors", 0) > 0:
            error_by_source[src["label"]] = src["errors"]
    if error_by_source:
        report["errors"] = {"total": total_errors, "by_source": error_by_source}

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"Written: {out}", flush=True)


def merge_and_report(
    source_results: list[dict],
    output_dir: str | Path,
    temp_dir: str | Path,
    *,
    release: str = "v1.1",
    classifier_version: str = DEFAULT_CLASSIFIER_VERSION,
    data_snapshot: str = DEFAULT_DATA_SNAPSHOT,
) -> None:
    """Full merge-and-report pipeline: merge → distribution → summary.

    Args:
        source_results: List of stats dicts from classify_source_shards().
        output_dir: Directory for final outputs (merged JSONL + reports).
        temp_dir: Directory with per-source temp files.
        release: Release tag (e.g. "v1.1" → *v1.1.jsonl).
        classifier_version: Version string in report metadata.
        data_snapshot: Data snapshot string in report metadata.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Merge per-source temp files into final classified JSONL
    classified_path = out / f"unknown_classified_{release}.jsonl"
    total = merge_classified_files(source_results, temp_dir, classified_path)

    # Accumulate stats from temp files
    acc = SummaryAccumulator()
    acc.ingest(source_results, Path(temp_dir))

    # Generate reports
    dist_path = out / f"difficulty_distribution_{release}.json"
    generate_distribution_report(
        acc, dist_path,
        classifier_version=classifier_version,
        data_snapshot=data_snapshot,
    )

    summary_path = out / f"classification_summary_{release}.json"
    generate_summary_report(
        acc, summary_path,
        classifier_version=classifier_version,
        data_snapshot=data_snapshot,
    )

    # Print final report to stdout
    _print_final_report(acc)


def _print_final_report(acc: SummaryAccumulator) -> None:
    classified = acc.classified
    conf = acc.get_confidence_stats()

    print()
    print("=" * 70)
    print("FINAL CLASSIFICATION REPORT")
    print("=" * 70)
    print()
    print(f"  Total records processed:     {acc.total_records}")
    print(f"  Successful classifications:  {classified}")
    print(f"  Failed classifications:      {sum(src.get('errors', 0) for src in acc.source_results.values())}")
    print()
    print(f"  Difficulty distribution:")
    for lvl in range(1, 6):
        cnt = acc.difficulty_counts.get(lvl, 0)
        pct = cnt / max(classified, 1) * 100
        label = {1: "Basic", 2: "Intermediate", 3: "Advanced", 4: "Expert", 5: "Research"}[lvl]
        print(f"    L{lvl} ({label}): {cnt:>8} ({pct:5.2f}%)")
    print()
    print(f"  Confidence:")
    print(f"    Mean: {conf['mean']:.4f}, Min: {conf['min']:.4f}, Max: {conf['max']:.4f}")
    if conf["low_confidence_count"]:
        print(f"    Low-confidence (<0.5): {conf['low_confidence_count']} ({conf['low_confidence_fraction']*100:.1f}%)")
    print()
    print(f"  Per-source breakdown:")
    for label in sorted(acc.source_results.keys()):
        total_src = acc.source_results[label].get("total", 0)
        classified_src = acc.source_classified.get(label, 0)
        diffs = acc.source_difficulty.get(label, {})
        print(f"    {label}: total={total_src}, classified={classified_src}")
        for lvl in range(1, 6):
            cnt = diffs.get(lvl, 0)
            pct = cnt / max(classified_src, 1) * 100
            print(f"      L{lvl}: {cnt:>6} ({pct:5.1f}%)")
    print()
    print("=" * 70)


# ---------------------------------------------------------------------------
# Orchestrator: ProductionClassifier
# ---------------------------------------------------------------------------

class ProductionClassifier:
    """Orchestrates a production classification run across multiple sources.

    Typical usage::

        classifier = ProductionClassifier(
            root_path="/path/to/atlas-dataset",
            release="v1.1",
        )
        stats = classifier.run()
    """

    def __init__(
        self,
        root_path: str | Path,
        *,
        release: str = "v1.1",
        classifier_version: str = DEFAULT_CLASSIFIER_VERSION,
        data_snapshot: str = DEFAULT_DATA_SNAPSHOT,
        sources: list[SourceConfig] | None = None,
        temp_dir: str | Path | None = None,
        output_dir: str | Path | None = None,
        print_progress_interval: int = 20,
    ):
        self.root = Path(root_path)
        self.release = release
        self.classifier_version = classifier_version
        self.data_snapshot = data_snapshot
        self.sources = sources if sources is not None else DEFAULT_SOURCES
        self.temp_dir = Path(temp_dir) if temp_dir else (
            self.root / "metadata" / "intelligence" / "_tmp"
        )
        self.output_dir = Path(output_dir) if output_dir else (
            self.root / "metadata" / "intelligence"
        )
        self.print_progress_interval = print_progress_interval

    def run(self) -> list[dict[str, Any]]:
        """Execute classification for all configured sources.

        Returns:
            List of per-source stats dicts.
        """
        print("=" * 70)
        print(f"Atlas Intelligence Layer {self.release} — Production Classification")
        print("=" * 70)
        print()

        # Clean temp dir
        if self.temp_dir.exists():
            for f in self.temp_dir.iterdir():
                if f.is_file():
                    f.unlink()
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Clean previous output for this release
        for ext in [".jsonl", ".json"]:
            for p in self.output_dir.glob(f"*_{self.release}{ext}"):
                p.unlink()

        start_time = time.time()
        results: list[dict[str, Any]] = []

        for config in self.sources:
            out_path = self.temp_dir / f"classified_{config.label}.jsonl"
            stats = classify_source_shards(
                self.root,
                config,
                out_path,
                print_progress_interval=self.print_progress_interval,
            )
            results.append(stats)

            elapsed = time.time() - start_time
            print(f"\n  [{config.label}] Completed. Total elapsed: {elapsed:.0f}s\n", flush=True)

        # Merge and report
        merge_and_report(
            results,
            self.output_dir,
            self.temp_dir,
            release=self.release,
            classifier_version=self.classifier_version,
            data_snapshot=self.data_snapshot,
        )

        elapsed = time.time() - start_time
        print(f"\nAll done in {elapsed:.0f}s ({elapsed/60:.1f}m)")
        print(f"Output: {self.output_dir / f'unknown_classified_{self.release}.jsonl'}")

        return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Atlas Intelligence Layer — Production Batch Classification",
    )
    p.add_argument(
        "--root", "-r",
        default=str(Path.cwd()),
        help="Root of atlas-dataset repository (default: cwd)",
    )
    p.add_argument(
        "--release", "-v",
        default="v1.1",
        help="Release tag (e.g. v1.1, v2.0). Controls output filenames.",
    )
    p.add_argument(
        "--version",
        default=DEFAULT_CLASSIFIER_VERSION,
        help="Classifier version string for report metadata",
    )
    p.add_argument(
        "--snapshot",
        default=DEFAULT_DATA_SNAPSHOT,
        help="Data snapshot tag for report metadata",
    )
    p.add_argument(
        "--sources", nargs="*",
        choices=["tulu3", "openwebmath", "arxiv", "c4"],
        default=None,
        help="Specific sources to classify (default: all)",
    )
    p.add_argument(
        "--temp-dir",
        default=None,
        help="Temp directory for per-source output (default: <root>/metadata/intelligence/_tmp)",
    )
    p.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for final files (default: <root>/metadata/intelligence/)",
    )
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Filter sources if specified
    sources = DEFAULT_SOURCES
    if args.sources:
        sources = [s for s in DEFAULT_SOURCES if s.label in args.sources]

    classifier = ProductionClassifier(
        root_path=args.root,
        release=args.release,
        classifier_version=args.version,
        data_snapshot=args.snapshot,
        sources=sources,
        temp_dir=args.temp_dir,
        output_dir=args.output_dir,
    )
    classifier.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
