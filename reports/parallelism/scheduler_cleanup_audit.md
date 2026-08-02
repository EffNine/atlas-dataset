# Scheduler Cleanup Audit Report

**Date:** 2026-08-02  
**Scope:** Phase 5D — Universal Scheduler Cleanup & Consolidation  
**Repository:** /Users/afnanrudy/Github-Projects/atlas-dataset  
**Current scheduler:** `scripts/parallel/` (scheduler.py, registry.py, planner.py, config.py, resource.py, models.py, monitor.py, runner.py)

---

## PART 1 — Audit: All Parallel Implementations

### Classification Key
- **A. Must migrate** — Currently using standalone parallel executors; should use the universal scheduler
- **B. Must remain standalone** — Domain-specific logic that cannot be generalized; correct as-is
- **C. Legacy compatibility** — Superseded by the universal scheduler but retained for backward compatibility
- **D. Test-only** — Used only in test code

---

### A. Must Migrate

| File | Lines | Executor | Current Pattern | Notes |
|------|-------|----------|-----------------|-------|
| `scripts/intelligence/batch_classify.py` | 229-236, 330-375 | ProcessPoolExecutor | Direct executor with local TaskRegistry | Superseded by `batch_classify_v2.py` which uses the universal scheduler. The old path should be removed. |
| `scripts/intelligence/batch_classify_v2.py` | 27, 191 | ProcessPoolExecutor | Direct executor (no registry) | Uses hardcoded `args.workers`; should use `resolve_worker_count("classification", ...)` |
| `scripts/acquisition_engine/engine.py` | 806-819 | ProcessPoolExecutor | Direct executor for loading curated files | This is a one-off file loading, not a pipeline stage. Can be refactored to use the scheduler or simplified to sequential. |

### B. Must Remain Standalone

| File | Lines | Executor | Pattern | Rationale |
|------|-------|----------|---------|-----------|
| `scripts/parallel/runner.py` | 18, 111 | ThreadPoolExecutor | Thin wrapper for e2e_pipeline | Used by `scripts/e2e_pipeline.py` only. Low overhead, kept for simple test paths. **Classification: D (test-only utility)** |
| `scripts/release/compress_release.py` | 33, 245 | ProcessPoolExecutor | Configured via CLI args | Release pipeline, not a dataset processing pipeline. Different constraints (compression, not data transformation). |
| `scripts/release/upload_huggingface.py` | 31, 332 | ThreadPoolExecutor | HTTP uploads with backoff | External API calls; domain-specific retry/backoff logic. Not a dataset task. |
| `scripts/release/dedup_release.py` | 32, 305 | ProcessPoolExecutor | Release deduplication | Release pipeline specific. |
| `scripts/downloader/http_util.py` | 108-171 | None (sync) | HTTP Range resume + retry | Domain-specific HTTP transfer logic. Not a worker pool — this is protocol-level resume. |
| `scripts/downloader/cache.py` | 212-255 | None (sync) | Cache with resume + retry | Domain-specific caching layer. |
| `scripts/acquisition_engine/checkpoint.py` | 75-170 | None | JSON checkpoint for engine state | Different from TaskRegistry: manages batch/source lifecycle, not task-level state. |
| `scripts/automation/failure_recovery.py` | 184-525 | None | Pipeline-level retry/resume | Automation layer concept — different abstraction than task-level retry. |
| `scripts/intelligence/adaptive_scheduler.py` | 218-357 | ProcessPoolExecutor (own registry) | Custom adaptive scheduler | See "C. Legacy Compatibility" below. |

### C. Legacy Compatibility

| File | Lines | Executor | Pattern | Status |
|------|-------|----------|---------|--------|
| `scripts/intelligence/adaptive_scheduler.py` | 218+ | ProcessPoolExecutor + local TaskRegistry | Custom scheduler with its own YAML loader | **Superseded by** `scripts/parallel/`. The `batch_classify_v2.py` imports from this file for config loading but should use `parallel.config`. |
| `scripts/intelligence/batch_classify.py` | 229+ | ProcessPoolExecutor + its own registry | Old classification path | **Superseded by** `batch_classify_v2.py`. Can be removed after migration. |

### D. Test-Only / Already Migrated

| File | Lines | Executor | Status |
|------|-------|----------|--------|
| `scripts/e2e_pipeline.py` | 80, 97 | ParallelRunner (from parallel) | ✅ Already uses universal scheduler |
| `scripts/validate_dataset.py` | 374-376 | ProcessPoolExecutor fallback | ✅ **Primary path uses scheduler** (lines 337-339). Fallback retained for crash safety. |
| `scripts/run_extract_all.py` | 148-153 | ProcessPoolExecutor fallback | ✅ **Primary path uses scheduler** (lines 109-145). Fallback retained for crash safety. |
| `scripts/training_view_engine/validator.py` | 309-315 | ProcessPoolExecutor fallback | ✅ **Primary path uses scheduler** (lines 249-250). Fallback retained for crash safety. |
| `scripts/training_view_engine/generator.py` | 363-364 | ProcessPoolExecutor fallback | ✅ **Primary path uses scheduler** (lines 337-338). Fallback retained for crash safety. |
| `scripts/downloader/scheduler_tasks.py` | 165-166 | Scheduler (from parallel) | ✅ Already migrated |
| `scripts/acquisition_engine/scheduler_tasks.py` | 140-141 | Scheduler (from parallel) | ✅ Already migrated |
| `scripts/etl/pipeline.py` | 340, 374 | Scheduler (from parallel) | ✅ Already migrated |

---

## PART 2 — Duplicate Logic Inventory

### 2.1 Duplicate YAML Config Loaders

All of these read `config/parallelism.yaml` independently instead of using `parallel.config.load_parallelism_config()`:

| File | Function | Lines | Can Be Removed |
|------|----------|-------|----------------|
| `scripts/validate_dataset.py` | `load_parallelism_config()` | 211-219 | **Yes** — replace with `from parallel.config import load_parallelism_config` |
| `scripts/intelligence/adaptive_scheduler.py` | `_load_yaml()` | 107-118 | **Yes** — replace with `parallel.config.load_parallelism_config()` |
| `scripts/acquisition_engine/engine.py` | `_load_file_workers()` | 775-784 | **Yes** — use `resolve_worker_count("acquisition", ...)` |
| `scripts/training_view_engine/generator.py` | (inline yaml load) | 298-300 | **Yes** — use `parallel.config` |
| `scripts/release/download_release.py` | (inline yaml load) | 73-78 | **Yes** — use `parallel.config` |
| `scripts/run_extract_all.py` | (inline yaml load) | 38-40 | **Yes** — use `parallel.config` |

### 2.2 Duplicate TaskRegistry / Resume Logic

| File | Implementation | Can Be Merged |
|------|---------------|---------------|
| `scripts/parallel/registry.py` | Universal TaskRegistry | **Source of truth** |
| `scripts/intelligence/adaptive_scheduler.py` | Local `TaskRegistry` class | **Yes** — replace with `parallel.registry.TaskRegistry` |
| `scripts/intelligence/batch_classify.py` | Uses adaptive_scheduler's TaskRegistry | **Yes** — migrate to parallel.registry |
| `scripts/acquisition_engine/checkpoint.py` | `CheckpointManager` (different abstraction) | **No** — manages batch/source lifecycle, not task state |

### 2.3 Duplicate Worker Count Resolution

| File | Mechanism | Can Be Unified |
|------|-----------|----------------|
| `scripts/parallel/config.py` | `resolve_worker_count(stage, cfg)` | **Source of truth** |
| `scripts/intelligence/adaptive_scheduler.py` | Reads `stage2_shard_workers` / `stage1_shard_workers` directly | **Yes** — use `resolve_worker_count("classification", ...)` |
| `scripts/acquisition_engine/engine.py` | `_load_file_workers()` reads YAML directly | **Yes** — use `resolve_worker_count("acquisition", ...)` |
| `scripts/training_view_engine/generator.py` | Reads `parallelism.training_views.workers` from YAML | **Yes** — use `resolve_worker_count("training_views", ...)` |
| `scripts/release/*.py` | CLI args (`--workers`, `--jobs`) | **No** — release pipeline has its own config contract |

### 2.4 Manual ProcessPoolExecutor Fallback Paths

These are **intentional crash-safety fallbacks** in migrated pipelines. They should be kept but can be simplified:

| File | Fallback Lines | Reason for Keeping |
|------|---------------|-------------------|
| `scripts/validate_dataset.py` | 374-376 | Scheduler crash recovery gap |
| `scripts/run_extract_all.py` | 148-153 | Scheduler crash recovery gap |
| `scripts/training_view_engine/validator.py` | 309-315 | Scheduler crash recovery gap |
| `scripts/training_view_engine/generator.py` | 363-364 | Scheduler crash recovery gap |

---

## PART 3 — Summary of Findings

### Items to Remove (Cleanup)

1. **`scripts/intelligence/batch_classify.py`** — Entire file is legacy. `batch_classify_v2.py` supersedes it.
2. **`scripts/intelligence/adaptive_scheduler.py`** — Entire file is legacy. Its `_load_yaml()` and `TaskRegistry` should be replaced with `parallel.config` and `parallel.registry`.
3. **Standalone YAML loaders** in:
   - `scripts/validate_dataset.py:211-219` → replace with `from parallel.config import load_parallelism_config`
   - `scripts/acquisition_engine/engine.py:775-784` → replace with `resolve_worker_count("acquisition", ...)`
   - `scripts/training_view_engine/generator.py:298-300` → replace with `parallel.config`
   - `scripts/release/download_release.py:73-78` → replace with `parallel.config`
   - `scripts/run_extract_all.py:38-40` → replace with `parallel.config`

### Items to Keep (Correct as-Is)

1. **Fallback ProcessPoolExecutor paths** in migrated pipelines — crash safety nets.
2. **`scripts/parallel/runner.py`** — Simple test utility, no cleanup needed.
3. **Release pipeline executors** (`compress_release.py`, `upload_huggingface.py`, `dedup_release.py`) — different domain.
4. **Downloader HTTP resume/retry** — protocol-level, not a worker pool.
5. **Acquisition engine checkpoint** — different abstraction (batch/source vs task-level).
6. **Automation failure recovery** — different abstraction (pipeline-level).

### Items to Migrate

1. **`scripts/intelligence/batch_classify_v2.py`** — Replace hardcoded `args.workers` with `resolve_worker_count("classification", ...)`.

---

## PART 4 — Impact Assessment

| Category | Files Affected | Risk |
|----------|---------------|------|
| Remove legacy files | 2 (`batch_classify.py`, `adaptive_scheduler.py`) | Low — both have v2/scheduler replacements |
| Replace YAML loaders | 6 files | Low — same YAML, same structure |
| Replace worker count resolution | 3 files | Low — same config source |
| Migrate batch_classify_v2.py | 1 file | Medium — changes execution path |
| Fallback paths | 4 files | None — kept as-is |

---

## Appendices

### A. Universal Scheduler Component Map

```
scripts/parallel/
├── config.py       — load_parallelism_config(), resolve_worker_count(), get_stage_config()
├── resource.py     — detect_cpu(), detect_ram(), safe_worker_limit(), has_ram_headroom()
├── models.py       — Task, TaskResult, WorkerCapacity
├── planner.py      — file_tasks(), shard_tasks(), byte_range_tasks(), plan_workload()
├── registry.py     — TaskRegistry (append-only JSONL checkpoint + resume + retry)
├── scheduler.py    — Scheduler (adaptive workers, backpressure, retry, deterministic ordering)
├── monitor.py      — Monitor (runtime metrics)
└── runner.py       — ParallelRunner (test utility, ThreadPoolExecutor wrapper)
```

### B. Already-Migrated Pipelines (using parallel.scheduler)

| Pipeline | Entry Point | Scheduler Usage |
|----------|-------------|-----------------|
| Validation | `scripts/validate_dataset.py` | ✅ Scheduler primary, ProcessPoolExecutor fallback |
| Extraction | `scripts/run_extract_all.py` | ✅ Scheduler primary, ProcessPoolExecutor fallback |
| Training Views | `scripts/training_view_engine/*.py` | ✅ Scheduler primary, ProcessPoolExecutor fallback |
| ETL | `scripts/etl/pipeline.py` | ✅ Scheduler primary |
| Downloader | `scripts/downloader/scheduler_tasks.py` | ✅ Scheduler primary |
| Acquisition | `scripts/acquisition_engine/scheduler_tasks.py` | ✅ Scheduler primary (PURE WORKER) |

### C. Pipeline State

```
Total parallel implementations found: 28
- Already using universal scheduler: 8 files
- Legacy/superseded (can remove): 2 files
- Must migrate to scheduler: 1 file (batch_classify_v2.py)
- Standalone, correct as-is: 12 files (release, downloader, automation)
- Fallback paths to keep: 4 files