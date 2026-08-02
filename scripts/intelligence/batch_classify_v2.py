#!/usr/bin/env python3
"""
batch_classify_v2.py — full-source parallel classification for Atlas v1.x+.

Canonical implementation for source-shard classification. Supersedes
``batch_classify.py`` (kept as a backward-compatibility shim).

Extends the legacy classifier to cover ALL raw/generated shards, not just the 4
v1.1 sources. Sources are grouped into affinity groups and processed in
parallel via ProcessPoolExecutor (one worker per group).

Execution model:
- Static path (``classify_source_shards``): one worker per shard
  (ProcessPool), per-source temp files, deterministic merge.
- Adaptive path (``classify_source_shards_adaptive``): balanced byte-range
  tasks via ``parallel.planner``, task state in ``parallel.registry``,
  legacy-format scheduler report via ``parallel.monitor``.

This module is the SINGLE source of truth for classification logic. The legacy
``batch_classify`` module re-exports these functions with deprecation warnings;
it contains no business logic.

Usage:
  # Default: classify all sources, 8 workers
  python scripts/intelligence/batch_classify_v2.py --workers 8

  # Specific groups only
  python scripts/intelligence/batch_classify_v2.py --groups wikipedia mmlu tulu3

  # Dry run: show what would be classified
  python scripts/intelligence/batch_classify_v2.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Allow running as `python -m scripts.intelligence.batch_classify_v2`
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from difficulty_analyzer import process_file  # noqa: E402

# Unified worker resolution — single source of truth
from parallel.config import load_parallelism_config, resolve_worker_count  # noqa: E402

# ---------------------------------------------------------------------------
# Legacy constants (kept for report metadata compatibility)
# ---------------------------------------------------------------------------

DEFAULT_CLASSIFIER_VERSION = "1.1.0"
DEFAULT_DATA_SNAPSHOT = "atlas-v1.0-RC1"

# ---------------------------------------------------------------------------
# Source groups
# ---------------------------------------------------------------------------

@dataclass
class SourceConfig:
    label: str
    glob_pattern: str
    description: str = ""

ALL_SOURCES: list[SourceConfig] = [
    # Wikipedia family (6.2M records)
    SourceConfig("wiki_ai",     "raw/generated/wiki_ai_shard*_atlas.jsonl",     "Wikipedia AI (40 shards)"),
    SourceConfig("wiki_sw",     "raw/generated/wiki_sw_shard*_atlas.jsonl",     "Wikipedia SW (10 shards)"),
    SourceConfig("wiki_sys",    "raw/generated/wiki_sys_shard*_atlas.jsonl",    "Wikipedia Systems (8 shards)"),
    SourceConfig("wiki_sci",    "raw/generated/wiki_sci_shard*_atlas.jsonl",    "Wikipedia Science (16 shards)"),
    SourceConfig("wiki_biz",    "raw/generated/wiki_biz_shard*_atlas.jsonl",    "Wikipedia Business (13 shards)"),
    SourceConfig("wiki_cre",    "raw/generated/wiki_cre_shard*_atlas.jsonl",    "Wikipedia Creative (8 shards)"),
    SourceConfig("wiki_hw",     "raw/generated/wiki_hw_shard*_atlas.jsonl",     "Wikipedia Hardware (9 shards)"),
    # Synthetic
    SourceConfig("synthetic_pa", "raw/generated/synthetic_test_v1.jsonl",        "Synthetic personal-assistant"),
    # Tulu-3 family (939k + 100k + 93k + 50k + 50k + 50k + 50k + 50k)
    SourceConfig("tulu3",       "raw/generated/tulu3_shard*_atlas.jsonl",       "Tulu-3 (6 shards)"),
    SourceConfig("tulu3_wildchat", "raw/generated/tulu_v3.9_wildchat_*_atlas.jsonl", "Tulu-3 WildChat"),
    SourceConfig("tulu3_aya",   "raw/generated/tulu_v3.9_aya_*_atlas.jsonl",    "Tulu-3 Aya"),
    SourceConfig("tulu3_wildjailbreak", "raw/generated/tulu_v3.9_wildjailbreak_*_atlas.jsonl", "Tulu-3 WildJailbreak"),
    SourceConfig("tulu3_openmath2", "raw/generated/tulu_v3.9_open_math_2_gsm8k_*_atlas.jsonl", "Tulu-3 OpenMath2"),
    SourceConfig("tulu3_synthetic_finalresp", "raw/generated/tulu_v3.9_synthetic_finalresp_*_atlas.jsonl", "Tulu-3 Synthetic FinalResp"),
    SourceConfig("tulu3_sciriff", "raw/generated/tulu_v3.9_sciriff_*_atlas.jsonl", "Tulu-3 SciRRF"),
    SourceConfig("tulu3_tablegpt", "raw/generated/tulu_v3.9_table_gpt_*_atlas.jsonl", "Tulu-3 TableGPT"),
    SourceConfig("tulu3_hardcoded", "raw/generated/tulu_v3.9_hard_coded_repeated_*_atlas.jsonl", "Tulu-3 Hard-coded"),
    # Math
    SourceConfig("openwebmath", "raw/generated/openwebmath_shard*_atlas.jsonl", "OpenWebMath (114 shards)"),
    SourceConfig("personahub_math", "raw/generated/personahub_math_*_atlas.jsonl", "PersonaHub Math"),
    SourceConfig("numinamath",  "raw/generated/numinamath_tir_math_*_atlas.jsonl", "NuminaMath TIR"),
    # Code
    SourceConfig("codealpaca_heval", "raw/generated/evol_codealpaca_heval_*_atlas.jsonl", "Evol CodeAlpaca + HEval"),
    SourceConfig("personahub_code", "raw/generated/personahub_code_*_atlas.jsonl", "PersonaHub Code"),
    SourceConfig("personahub_ifdata", "raw/generated/personahub_ifdata_*_atlas.jsonl", "PersonaHub IFData"),
    SourceConfig("swebench",    "raw/generated/swebench_atlas.jsonl",            "SWE-bench"),
    SourceConfig("codealpaca",  "raw/generated/codealpaca_atlas.jsonl",          "CodeAlpaca-20k"),
    # Instruction/chat
    SourceConfig("ultrafeedback", "raw/generated/ultrafeedback_atlas.jsonl",     "UltraFeedback"),
    SourceConfig("oasst1",      "raw/generated/oasst1_atlas.jsonl",              "OpenAssistant OASST1"),
    SourceConfig("oasst1_val",  "raw/generated/oasst1_val_atlas.jsonl",          "OASST1 validation"),
    SourceConfig("no_robots",   "raw/generated/no_robots_converted_atlas.jsonl", "NoRobots"),
    SourceConfig("coconot",     "raw/generated/coconot_converted_atlas.jsonl",   "CoCoNot"),
    SourceConfig("flan_v2",     "raw/generated/flan_v2_converted_atlas.jsonl",   "Flan V2"),
    # General QA/science
    SourceConfig("sciq",        "raw/generated/sciq_atlas.jsonl",                "SciQ"),
    SourceConfig("gsm8k",       "raw/generated/gsm8k_atlas.jsonl",               "GSM8K"),
    SourceConfig("mmlu",        "raw/generated/mmlu_*_atlas.jsonl",              "MMLU subsets (56 shards)"),
    SourceConfig("capybara",    "raw/generated/capybara_atlas.jsonl",            "Capybara"),
    SourceConfig("capybara_extra", "raw/generated/capybara_extra_atlas.jsonl",  "Capybara extra"),
    SourceConfig("fin_alpaca",  "raw/generated/fin-alpaca_atlas.jsonl",          "Finance Alpaca"),
    # C4
    SourceConfig("c4",          "raw/generated/c4_ai_shard*_atlas.jsonl",        "C4 AI/ML (12 shards)"),
    # ArXiv
    SourceConfig("arxiv_cs",    "raw/generated/arxiv_cs_atlas.jsonl",            "ArXiv CS"),
    SourceConfig("arxiv_hw",    "raw/generated/arxiv_hardware_atlas.jsonl",      "ArXiv Hardware"),
    SourceConfig("arxiv_ml",    "raw/generated/arxiv_ml_batch*_atlas.jsonl",     "ArXiv ML"),
    # Miscellaneous
    SourceConfig("gutenberg",   "raw/generated/gutenberg_*_atlas.jsonl",         "Project Gutenberg"),
    SourceConfig("github_readmes", "raw/generated/github_readmes_atlas.jsonl",   "GitHub READMEs"),
    SourceConfig("stackoverflow", "raw/generated/stackoverflow_atlas.jsonl",     "Stack Overflow"),
    SourceConfig("batch_new",   "raw/generated/batch_new_sources.jsonl",         "Batch new sources"),
]

# ---------------------------------------------------------------------------
# Scheduler config view (legacy flat shape for backward compatibility)
# ---------------------------------------------------------------------------


def _load_scheduler_cfg(config: dict | None = None) -> dict:
    """Return the classification scheduler config as a legacy flat dict.

    If ``config`` is given it is treated as the unified config (may contain a
    ``parallelism.classification`` section); otherwise the on-disk unified
    config is loaded. The returned shape matches the legacy
    ``adaptive_scheduler.load_scheduler_config`` contract so callers that
    pass/expect that shape keep working.
    """
    if config is None:
        config = load_parallelism_config()
    clf = (config or {}).get("parallelism", {}).get("classification", {})
    return {
        "scheduler": clf.get("scheduler", "adaptive"),
        "target_task_size_mb": int(clf.get("target_task_size_mb", 512)),
        "max_task_size_mb": int(clf.get("max_task_size_mb", 1024)),
        "split_large_shards": bool(clf.get("split_large_shards", True)),
        "min_split_size_mb": int(clf.get("min_split_size_mb", 2048)),
        "task_timeout_seconds": int(clf.get("task_timeout_seconds", 3600)),
        "max_retries": int(clf.get("max_retries", 2)),
        "max_parallel_workers": int(clf.get("stage2_shard_workers", 10)),
    }


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
                assert fh is not None  # assigned in the branch above on first iteration
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

    Plans balanced byte-range tasks through ``parallel.planner``, runs them
    through ProcessPoolExecutor, tracks state in ``parallel.registry``, and
    merges per-task outputs in deterministic order. Writes the legacy-format
    scheduler report via ``parallel.monitor``.

    Args:
        root_path: Repo root.
        config: Source configuration.
        output_path: Per-source classified output (merged).
        shard_workers: Max parallel workers.
        scheduler_cfg: Legacy flat scheduler config (from _load_scheduler_cfg).
        print_progress_interval: Progress print cadence.
        worker_id: Worker id for the registry.

    Returns:
        Stats dict (label, total, classified, errors, elapsed, shards).
    """
    from parallel.monitor import write_legacy_scheduler_report
    from parallel.planner import byte_range_tasks
    from parallel.registry import TaskRegistry

    if scheduler_cfg is None:
        scheduler_cfg = _load_scheduler_cfg()

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

    # Plan balanced byte-range tasks via the canonical planner. The canonical
    # planner decides whole-file vs chunk split from the same thresholds the
    # legacy adaptive scheduler used (target/max/min_split size).
    tasks = []
    for shard in shards:
        tasks.extend(
            byte_range_tasks(
                shard,
                source=config.label,
                operation=worker_group,
                target_size_mb=int(scheduler_cfg["target_task_size_mb"]),
                max_size_mb=int(scheduler_cfg["max_task_size_mb"]),
                min_split_mb=int(scheduler_cfg["min_split_size_mb"]),
            )
        )
    tasks.sort(key=lambda t: t.task_id)

    registry = TaskRegistry(root / "metadata" / "pipeline_state", worker_group,
                            max_retries=int(scheduler_cfg.get("max_retries", 2)))
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
    split_ops = sum(1 for t in tasks if "~" in t.task_id)

    with ProcessPoolExecutor(max_workers=shard_workers) as pool:
        futures = {}
        for task in tasks:
            # Resume: skip completed, re-queue failed up to max_retries
            if registry.is_completed(task.task_id):
                continue
            if registry.status(task.task_id) == "failed" and registry.attempts(task.task_id) >= int(scheduler_cfg["max_retries"]):
                print(f"  [SKIP] {task.task_id} failed {scheduler_cfg['max_retries']}x", flush=True)
                continue
            tmp_path = tmp_dir / f"{task.task_id}.jsonl"
            registry.record(task.task_id, "running", worker_id=worker_id, output_file=str(tmp_path))
            futures[pool.submit(_process_task_worker, task.to_dict(), tmp_path)] = task

        for fut in as_completed(futures):
            task = futures[fut]
            try:
                total_records, classified_count, error_count = fut.result()
                total += classified_count
                total_errors += error_count
                registry.complete(
                    task.task_id,
                    worker_id=worker_id,
                    output_file=str(tmp_dir / f"{task.task_id}.jsonl"),
                    record_count=classified_count,
                )
            except Exception as exc:
                total_errors += 1
                registry.fail(task.task_id, error=str(exc))
                print(f"  [ERROR] {task.task_id}: {exc}", file=sys.stderr, flush=True)

    # Merge per-task outputs in deterministic (sorted task_id) order
    with open(out, "w", encoding="utf-8") as fh:
        for task in tasks:
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

    write_legacy_scheduler_report(
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

    Accepts a canonical ``parallel.models.Task.to_dict()`` (keys: input,
    offset_start, offset_end) or a legacy task dict (key: input_file).
    A task covers a whole file (offset_end None/-1) or a line range
    [offset_start, offset_end). Streaming — never modifies the input.

    Returns (total_records, classified_count, error_count).
    """
    from difficulty_analyzer import process_file_range

    input_file = Path(task.get("input") or task["input_file"])
    offset_start = int(task.get("offset_start") or 0)
    offset_end = task.get("offset_end")
    if offset_end is None:
        offset_end = -1
    else:
        offset_end = int(offset_end)

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
    """Concatenate per-source temp files into the final classified JSONL."""
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
# Worker
# ---------------------------------------------------------------------------


def _classify_one(config: SourceConfig, root: str, out_dir: str,
                  print_interval: int, shard_workers: int) -> dict[str, Any]:
    """Run classify_source_shards for one source (worker function).

    Uses the adaptive scheduler by default; falls back to the static
    per-shard path when scheduler=static. All functions are module-local
    (canonical) — no imports from the legacy shim.
    """
    out_path = Path(out_dir) / f"classified_{config.label}.jsonl"
    scheduler_cfg = _load_scheduler_cfg()

    if scheduler_cfg.get("scheduler", "adaptive") == "adaptive":
        stats = classify_source_shards_adaptive(
            root_path=root,
            config=config,
            output_path=out_path,
            shard_workers=shard_workers,
            scheduler_cfg=scheduler_cfg,
        )
    else:
        stats = classify_source_shards(
            root_path=root,
            config=config,
            output_path=out_path,
            print_progress_interval=print_interval,
            shard_workers=shard_workers,
        )
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", help="Repo root")
    ap.add_argument("--release", default="v1.2", help="Release tag for output filenames")
    ap.add_argument("--output-dir", default=None, help="Output dir (default: metadata/intelligence)")
    ap.add_argument("--temp-dir", default=None, help="Temp dir (default: metadata/intelligence/_tmp)")
    ap.add_argument("--workers", type=int, default=8, help="Parallel workers")
    ap.add_argument("--print-interval", type=int, default=20, help="Progress print every N shards")
    ap.add_argument("--shard-workers", type=int, default=1, help="Parallel workers within each source")
    ap.add_argument("--groups", nargs="*", default=None, help="Only run these source labels")
    ap.add_argument("--no-merge", action="store_true",
                    help="Skip merge_and_report (caller merges per-source files, e.g. run_classify_all_v2.py)")
    ap.add_argument("--dry-run", action="store_true", help="List sources, no work")
    args = ap.parse_args(argv)

    root = Path(args.root)
    out_dir = Path(args.output_dir) if args.output_dir else root / "metadata" / "intelligence"
    temp_dir = Path(args.temp_dir) if args.temp_dir else out_dir / "_tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    sources = ALL_SOURCES
    if args.groups:
        sources = [s for s in sources if s.label in args.groups]

    # Dry run: show what each group would process
    if args.dry_run:
        print(f"Dry run | root={root} | workers={args.workers} | sources={len(sources)}")
        for s in sources:
            shards = sorted(root.glob(s.glob_pattern))
            shards = [f for f in shards if f.stat().st_size > 0]
            total_bytes = sum(f.stat().st_size for f in shards)
            print(f"  {s.label:25s} {len(shards):4d} shards  {total_bytes/1e9:.2f} GB  {s.description}")
        return 0

    print(f"Classify all sources | release={args.release} | workers={args.workers} | sources={len(sources)}")
    start = time.time()

    results: list[dict[str, Any]] = []
    cfg = load_parallelism_config()
    # CLI override (--workers) > config resolution > safe default
    resolved_workers = args.workers or resolve_worker_count("classification", cfg)
    if resolved_workers == "auto":
        resolved_workers = 8  # safe default for classification
    with ProcessPoolExecutor(max_workers=resolved_workers) as pool:
        futures = {
            pool.submit(_classify_one, s, str(root), str(temp_dir), args.print_interval, args.shard_workers): s
            for s in sources
        }
        for fut in as_completed(futures):
            s = futures[fut]
            try:
                stats = fut.result()
                results.append(stats)
                print(f"[DONE] {s.label}: {stats['classified']:,} records, {stats.get('elapsed','?')}", flush=True)
            except Exception as exc:
                print(f"[FAIL] {s.label}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
                results.append({"label": s.label, "classified": 0, "errors": 1})

    elapsed = time.time() - start
    total_classified = sum(r.get("classified", 0) for r in results)
    print(f"\nAll sources done: {total_classified:,} records in {elapsed:.0f}s")

    if args.no_merge:
        print(f"Output: {temp_dir} (per-source files; --no-merge, caller merges)")
        # A source only "failed" if its classification worker crashed
        # (classified=0, errors=1). Record-level errors (bad JSON lines) are
        # expected in noisy sources and are not fatal — valid records are kept
        # in the per-source output file and the caller still appends them.
        fatal = [r for r in results if r.get("classified", 0) == 0 and r.get("errors", 0) > 0]
        if fatal:
            for r in fatal:
                print(f"  [FATAL] {r.get('label', '?')}: worker crashed, no output")
        return 1 if fatal else 0

    # Merge and generate reports
    print("Merging reports...")
    merge_and_report(
        results,
        output_dir=out_dir,
        temp_dir=temp_dir,
        release=args.release,
    )
    print(f"Output: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
