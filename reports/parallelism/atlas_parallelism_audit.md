# Atlas Pipeline Parallelism Audit

**Date:** 2026-08-01
**Scope:** Read-only audit of all major Atlas pipelines. No code, dataset, release,
or configuration was modified.
**Audit artifacts:**
- This report: `reports/parallelism/atlas_parallelism_audit.md`
- Machine-readable inventory: `reports/parallelism/atlas_parallelism_inventory.json`

**Purpose:** Establish the current parallel execution architecture before
designing a Universal Scheduler.

---

## 0. Execution Model Legend

| Model | Meaning |
|-------|---------|
| `sequential` | One item at a time, single process/thread |
| `ThreadPoolExecutor` | Threads (I/O-bound or wrapper) |
| `ProcessPoolExecutor` | Processes (CPU-bound) |
| `asyncio` | Event loop |
| `custom workers` | Hand-rolled worker pool / subprocess fan-out |
| `adaptive scheduler` | Task-queue planner + registry (v1.2 classification only) |

Config source legend: `CONFIG` = `config/parallelism.yaml` (via loader),
`CLI` = argparse flag, `HARD` = hardcoded default, `ENV` = environment variable.

Resource awareness legend: `NONE` = no monitoring, `DISK` = disk checks,
`MEM` = memory checks.

---

## 1. Intelligence

### 1.1 Classification (difficulty classifier)

- **Files:** `scripts/intelligence/difficulty_analyzer.py`,
  `scripts/intelligence/batch_classify.py`, `scripts/intelligence/batch_classify_v2.py`
- **A. Execution model:** Dual-path.
  - CLI single-file mode (`difficulty_analyzer.py --input-file`): **sequential**
    per record (`process_file`).
  - Shard mode (`batch_classify.py classify_source_shards`): **ProcessPoolExecutor**
    over shard files; single-shard sources split into line chunks.
  - Adaptive mode (`classify_source_shards_adaptive`): **adaptive scheduler**
    (task queue + TaskRegistry + per-task ProcessPool execution).
- **B. Worker config:** `CONFIG` `classification.*` (stage1=8, stage2=10,
  parallel_sources=2, target_task_size_mb=64, max 128, min_split 128);
  `CLI` `--shard-workers`, `--workers`.
- **C. Resource awareness:** NONE (no RAM/CPU/disk/GPU monitoring).
- **D. Resume capability:** **Yes (adaptive mode)**: TaskRegistry
  (`metadata/pipeline_state/task_registry_{stage}.jsonl`), completed-skip,
  failed-retry (`max_retries=2`). Static mode: per-source `_tmp` files +
  runner `--skip` list (process-level resume, not record-level).
- **E. Workload unit:** shard → **task** (adaptive; line-range chunk of a shard).
- **F. Bottleneck:** **MEDIUM** — CPU-bound, long runtime (hours), but now
  balanced by adaptive tasks. Confidence scoring is heuristic (fast).

### 1.2 v1.2 Runner

- **Files:** `run_classify_all_v2.py`
- **A. Execution model:** **custom worker orchestration**: ThreadPoolExecutor
  for source-level parallelism (bounded: `parallel_sources=2` in flight),
  each source spawned as a subprocess (`batch_classify_v2.py`), which runs
  ProcessPoolExecutor internally.
- **B. Worker config:** `CONFIG` (all classification keys); `CLI` `--skip`.
- **C. Resource awareness:** NONE.
- **D. Resume capability:** Partial — `--skip` list + `_tmp` per-source
  outputs; append-per-source merge; crash-safe (no double-append).
- **E. Workload unit:** source.
- **F. Bottleneck:** **MEDIUM** — was HIGH (sequential sources, single-shard
  bottleneck); reduced by parallel_sources=2 + adaptive splitting. Still no
  auto-recovery: a crashed source aborts the stage.

### 1.3 Batch workers (archived v1.1)

- **Files:** `scripts/intelligence/archive/production_v1_1/*`
- **A. Execution model:** **custom workers** (parallel_classify.py subprocess
  fan-out; v1.1-era ProcessPool).
- **B. Worker config:** HARD.
- **C/D/E/F:** NONE / no registry / shard / **HIGH** — superseded, archived.

---

## 2. Acquisition

### 2.1 Downloader

- **Files:** `scripts/downloader/*` (`download_agent.py`, `cache.py`,
  `http_util.py`), `scripts/downloader/__init__.py`
- **A. Execution model:** **sequential** per source; cache + retry helpers.
- **B. Worker config:** HARD (no executor found in download_agent).
- **C. Resource awareness:** NONE (HTTP retries only).
- **D. Resume capability:** Partial — cache-based skip of already-downloaded
  files (downloader/cache.py); no task registry.
- **E. Workload unit:** file.
- **F. Bottleneck:** **MEDIUM** — network I/O-bound; parallel download would
  help but sequential is safe/simple.

### 2.2 Acquisition Engine (ingestion)

- **Files:** `scripts/acquisition_engine/engine.py`,
  `scripts/acquisition_engine/checkpoint.py`, `scripts/acquisition_engine/lifecycle.py`
- **A. Execution model:** **sequential** record generation
  (`generate_knowledge_pack` → per-source records); **ProcessPoolExecutor**
  only for parallel curated-file *loading* (`_load_file_workers`, file_workers=4).
- **B. Worker config:** `CONFIG` `acquisition.file_workers` (4), chunk_size 500.
- **C. Resource awareness:** NONE.
- **D. Resume capability:** **Yes** — checkpoint.py + `resume(max_records)`,
  integrity verify, version freeze/diff.
- **E. Workload unit:** source → pack; loading unit = file.
- **F. Bottleneck:** **MEDIUM** — generation sequential, but checkpointed;
  loading parallel.

### 2.3 Source processing (ETL ingestion)

- **Files:** `scripts/etl/pipeline.py`, `scripts/etl/normalizer.py`,
  `scripts/etl/types.py`
- **A. Execution model:** **sequential** (`run_etl_for_source` per source).
- **B. Worker config:** HARD (none).
- **C/D/E/F:** NONE / log-based skip (registry via `_load_registry`) / file /
  **LOW** — small volumes, per-source, idempotent.

---

## 3. ETL / Transform

### 3.1 Cleaners / converters / deduplication

- **Files:** `scripts/etl/normalizer.py` (clean/normalize), scripts using
  ParallelRunner: `scripts/e2e_pipeline.py`, `scripts/automation_runner.py`
  (`ParallelRunner` in `scripts/parallel/__init__.py`)
- **A. Execution model:** `ParallelRunner` = **ThreadPoolExecutor wrapper**
  (per-source jobs; deterministic output; serial fallback).
- **B. Worker config:** `CLI` `--max-workers` (default 4); `ParallelRunner`
  hardcoded default 4.
- **C. Resource awareness:** NONE.
- **D. Resume capability:** Partial — `IncrementalState` (`use_registry=True`)
  skips done sources.
- **E. Workload unit:** source.
- **F. Bottleneck:** **LOW** — transform per-source, thread-bound (GIL for
  CPU work), small volumes.

---

## 4. Extraction

### 4.1 Shard extraction orchestrator

- **Files:** `scripts/run_extract_all.py`
- **A. Execution model:** **ProcessPoolExecutor** over per-shard
  `extract_wiki_*.py` invocations (shard_workers=8, 41 shards/source).
- **B. Worker config:** `CONFIG` `extraction.shard_workers` (8),
  `shards_per_source` (41); `CLI` `--shard-workers`.
- **C. Resource awareness:** NONE.
- **D. Resume capability:** Partial — per-shard output files; failed shards
  reported (`total_failed`); no task registry; rerun re-extracts all.
- **E. Workload unit:** shard.
- **F. Bottleneck:** **MEDIUM** — disk I/O + CPU heavy (parquet → JSONL),
  balanced by fixed 41-shard layout but no adaptive sizing.

### 4.2 Wiki / document processing

- **Files:** `scripts/extract_wiki_*.py` (sys/sw/sci/hw/cre/biz/ai),
  `scripts/extract_tulu3_shard.py`, `scripts/extract_openwebmath.py`,
  `scripts/extract_oasst1.py`, `scripts/extract_mmlu_subject.py`
- **A. Execution model:** **sequential** single-shard scripts (invoked in
  parallel by run_extract_all).
- **B. Worker config:** N/A (single-shard scope).
- **C/D/E/F:** NONE / none / shard / **LOW** individually (parallelized upstream).

---

## 5. Validation

### 5.1 Dataset validation

- **Files:** `scripts/validate_dataset.py`
- **A. Execution model:** **ProcessPoolExecutor** file-level
  (`validate_one_file` per file; file_workers=8).
- **B. Worker config:** `CONFIG` `validation.file_workers` (8),
  `chunk_size` (1000), per-file timeout; `CLI` `--file-workers`.
- **C. Resource awareness:** per-file timeout only.
- **D. Resume capability:** None in-process; per-file results allow
  re-running only failed files manually.
- **E. Workload unit:** file.
- **F. Bottleneck:** **MEDIUM** — CPU-heavy JSON parsing, balanced by
  file-level parallelism; no adaptive sizing for uneven files.

### 5.2 Schema validation / architecture

- **Files:** `scripts/validate_architecture.py` (ast-based, Check 7 enforces
  config-only worker counts), `scripts/validate_knowledge_object.py`,
  `scripts/validate_quality_engine.py`
- **A. Execution model:** **sequential** (validate_architecture.py uses
  asyncio only for internal subprocess capture; not data parallelism).
- **B/C/D/E/F:** HARD/CLI / NONE / none / file / **LOW**.

---

## 6. Training Views

- **Files:** `scripts/training_view_engine/generator.py`,
  `scripts/training_view_engine/validator.py`, `filter.py`, `manifest.py`
- **A. Execution model:** **ProcessPoolExecutor** for both curated-file
  loading and record validation (`validate_records(workers=N)`); generation
  sequential per eligible record after parallel load.
- **B. Worker config:** `CONFIG` `training_views.workers` (8); loader
  `_load_view_workers()`.
- **C. Resource awareness:** NONE.
- **D. Resume capability:** Partial — manifest/registry-based (eligibility
  filter + manifest.py); no task-level checkpoint.
- **E. Workload unit:** file (load) / record (validate) / view (generate).
- **F. Bottleneck:** **MEDIUM** — per-model view generation (qwen/llama/
  deepseek) is sequential after parallel load; generator/validator separate
  pools (no shared scheduler).

---

## 7. Evaluation

- **Files:** `scripts/evaluation_engine/*` (engine.py, runner.py, registry.py,
  metrics.py, report.py), `scripts/eval_dataset.py`
- **A. Execution model:** **sequential** (`EvaluationRunner.run` → dry-run or
  full; no executors).
- **B. Worker config:** HARD.
- **C. Resource awareness:** Network block switch only.
- **D. Resume capability:** None (eval_id per run; no checkpoint).
- **E. Workload unit:** benchmark.
- **F. Bottleneck:** **LOW** — validation/registry-heavy, small data; full
  eval mode not yet parallelized.

---

## 8. Release

### 8.1 Join

- **Files:** `scripts/release/join_release.py`
- **A. Execution model:** **sequential** (sorted glob loop).
- **B. Worker config:** HARD (no executor).
- **C/D/E/F:** NONE / manifest-based skip (partial) / file / **MEDIUM**
  (single-pass join over ~9.5M records; resumable via manifest).

### 8.2 Compression

- **Files:** `scripts/release/compress_release.py`
- **A. Execution model:** **ProcessPoolExecutor** (workers, default 1; parallel
  zstd per shard).
- **B. Worker config:** `CLI` `--workers` (default 1); HARD fallback.
- **C. Resource awareness:** NONE.
- **D. Resume capability:** Partial — `--skip-existing` skips already-compressed
  shards.
- **E. Workload unit:** shard.
- **F. Bottleneck:** **MEDIUM** — CPU + disk heavy; parallel but default 1
  worker; no adaptive sizing (uneven shard sizes).

### 8.3 Checksum

- **Files:** `scripts/release/generate_checksums.py`
- **A. Execution model:** **sequential** loop.
- **B. Worker config:** HARD.
- **C/D/E/F:** NONE / skip-if-exists (partial) / file / **LOW** (fast SHA-256;
  large file counts make it I/O-bound, sequential acceptable).

### 8.4 Upload / publish / promote

- **Files:** `scripts/release/upload_huggingface.py`,
  `scripts/release/publish_promotion.py`, `scripts/release/promote_release.py`,
  `scripts/release/update_release_index.py`
- **A. Execution model:** **ThreadPoolExecutor** per section in
  upload_huggingface.py (workers, default 4, resume by size-match);
  publish/promote sequential.
- **B. Worker config:** `CLI` `--workers` (default 4) in upload; HARD in
  promote/publish.
- **C. Resource awareness:** NONE.
- **D. Resume capability:** Yes (upload) — remote size-match skip + retry
  with backoff + verification. Promote/publish: sequential, no checkpoint.
- **E. Workload unit:** section/file.
- **F. Bottleneck:** **MEDIUM** — network I/O; thread pool good for I/O;
  no cross-machine resume for promote/publish.

### 8.5 Download restore

- **Files:** `scripts/release/download_release.py`
- **A. Execution model:** **ThreadPoolExecutor** (HF snapshot_download
  with max_workers from config).
- **B. Worker config:** `CONFIG` `acquisition.file_workers` (4) — reuses
  acquisition key; `CLI` (via argparse).
- **C. Resource awareness:** NONE.
- **D. Resume capability:** Yes (HF cache resume + `--verify` SHA-256).
- **E. Workload unit:** file.
- **F. Bottleneck:** **LOW** — I/O-bound, cached.

---

## 9. Summary Table

| Pipeline | Parallel Model | Config | Resource Aware | Resume | Priority |
|----------|---------------|--------|----------------|--------|----------|
| Intelligence: classification (adaptive) | adaptive scheduler + ProcessPool | CONFIG | NONE | Yes (TaskRegistry) | HIGH |
| Intelligence: difficulty CLI | sequential | CLI | NONE | No | LOW |
| Intelligence: v1.2 runner | custom (ThreadPool sources + subprocess) | CONFIG + CLI | NONE | Partial (--skip) | HIGH |
| Intelligence: archived v1.1 workers | custom workers | HARD | NONE | No | ARCHIVED |
| Acquisition: downloader | sequential | HARD | NONE | Partial (cache) | MEDIUM |
| Acquisition: engine | sequential + ProcessPool load | CONFIG | NONE | Yes (checkpoint) | MEDIUM |
| ETL: source processing | sequential | HARD | NONE | Partial (registry) | LOW |
| Transform: ParallelRunner | ThreadPoolExecutor | CLI | NONE | Partial (IncrementalState) | LOW |
| Extraction: shard orchestrator | ProcessPoolExecutor | CONFIG | NONE | Partial (per-shard files) | MEDIUM |
| Extraction: wiki scripts | sequential (parallel upstream) | N/A | NONE | No | LOW |
| Validation: dataset | ProcessPoolExecutor | CONFIG | NONE | No | MEDIUM |
| Validation: schema/arch | sequential | HARD/CLI | NONE | No | LOW |
| Training Views: generator | ProcessPool load + sequential gen | CONFIG | NONE | Partial (manifest) | MEDIUM |
| Training Views: validator | ProcessPoolExecutor | CONFIG | NONE | No | MEDIUM |
| Evaluation | sequential | HARD | NONE | No | LOW |
| Release: join | sequential | HARD | NONE | Partial (manifest) | MEDIUM |
| Release: compress | ProcessPoolExecutor | CLI | NONE | Partial (--skip-existing) | MEDIUM |
| Release: checksum | sequential | HARD | NONE | Partial (skip-if-exists) | LOW |
| Release: upload | ThreadPoolExecutor | CLI | NONE | Yes (size-match) | MEDIUM |
| Release: publish/promote | sequential | HARD | NONE | No | LOW |
| Release: download | ThreadPoolExecutor | CONFIG (acq) | NONE | Yes (HF cache) | LOW |

---

## 10. Findings

### 10.1 Duplicate parallel implementations

1. **Two ProcessPool patterns for loading** — `acquisition_engine/engine.py`
   (`generate_knowledge_pack` → `_load_one`) and
   `training_view_engine/generator.py` (`_load_view_workers`) both implement
   nearly identical parallel curated-file loaders with different worker
   loaders (`_load_file_workers` vs `_load_view_workers`) and different config
   keys (`acquisition.file_workers` vs `training_views.workers`).
2. **Three per-source execution wrappers** — `ParallelRunner`
   (ThreadPool, `scripts/parallel/__init__.py`), `batch_classify_v2._classify_one`
   (ProcessPool + subprocess), `e2e_pipeline`/`automation_runner`
   (re-uses ParallelRunner but with its own config plumbing).
3. **Split logic duplicated** — `batch_classify.split_single_shard` (static
   chunking) vs `adaptive_scheduler.plan_tasks` (adaptive chunking) both
   compute line ranges; two implementations of the same idea.
4. **Worker count plumbing duplicated** — `validate_dataset.load_parallelism_config`,
   `adaptive_scheduler.load_scheduler_config`, `run_extract_all.load_config`,
   `acquisition_engine._load_file_workers`, `training_view_engine._load_view_workers`
   each parse `config/parallelism.yaml` independently (no shared loader).
5. **Retry/resume helpers duplicated** — `downloader/cache.py` skip logic,
   `upload_huggingface` size-match resume, `compress_release --skip-existing`,
   `adaptive_scheduler.TaskRegistry` — four bespoke resume mechanisms.

### 10.2 Code that should migrate into shared scheduler

- `classify_source_shards_adaptive` task-loop pattern (submit → registry →
  as_completed → deterministic merge) is the reference implementation.
- `validate_dataset.validate_one_file` + ProcessPool file fan-out.
- `training_view_engine.validator.validate_records(workers=N)` chunking.
- `run_extract_all.extract_one` per-shard fan-out.
- `ParallelRunner` per-source ThreadPool wrapper.
- `TaskRegistry` (extend to all pipelines as the universal resume layer).
- `plan_tasks` byte-aware splitting (extend beyond classification).

### 10.3 Pipelines already compatible with Adaptive Scheduler

- **Classification (v1.2)** — fully wired (planner, registry, report).
- **Validation** — file-level ProcessPool; planner-compatible (files = tasks)
  with minimal adaptation.
- **Extraction** — shard-level ProcessPool; planner-compatible (shards = tasks,
  byte-aware split applies to uneven shard sizes).
- **Training views** — record-chunk ProcessPool; planner-compatible.
- **Release compress** — shard ProcessPool; planner-compatible.

### 10.4 Pipelines requiring redesign

- **Downloader** (sequential; needs I/O task pool + resume registry).
- **Evaluation engine** (sequential; needs task-level execution, currently
  dry-run only).
- **Join/checksum/publish/promote** (sequential; low urgency, but should adopt
  the shared scheduler for uniformity + resource awareness).
- **ETL source processing** (sequential per source; adopt ParallelRunner-style
  fan-out through shared scheduler).

---

## 11. Recommendations

### Phase 1 — First migrations (highest value, lowest risk)

1. **Shared config loader** — extract one `load_parallelism_config()`
   (already in `validate_dataset.py`) into `scripts/parallel/config.py` and
   reuse everywhere (removes Finding 10.1.4).
2. **Unify TaskRegistry as the resume layer** — promote
   `adaptive_scheduler.TaskRegistry` to `scripts/parallel/registry.py`;
   wire into **validation** and **extraction** first (both are already
   planner-compatible per 10.3).
3. **Universal planner** — promote `plan_tasks` to `scripts/parallel/planner.py`
   with `workload_unit` aware task types (file / shard / record-range);
   migrate **compress_release** (uneven shard sizes) and **validate_dataset**.

### Phase 2 — Resource-aware scheduler scope

1. Add resource monitoring (psutil: RAM/CPU/disk; optional GPU via
   `nvidia-smi`/torch) to the universal planner.
2. Make `target_task_size_mb` adaptive at runtime:
   `workers = min(cores, ram_available / per_task_ram)` — the classic
   `task_size = total_bytes / (workers × 4)` rule from the adaptive design doc.
3. Wire into **training views** (memory-heavy record validation) and
   **classification** (already has the hooks in `load_scheduler_config`).
4. Optional GPU awareness for evaluation engine when full eval mode lands.

### Phase 3 — Multi-machine scaling readiness

1. TaskRegistry is already the coordination point (task_id, worker_id,
   status, timestamps). Move the registry file to a shared store
   (NFS / object store / SQLite) for multi-node workers.
2. Make tasks content-addressed (input hash + offset range) so any node can
   claim any task; results merged by deterministic task_id order.
3. Extraction and classification are the best multi-machine candidates
   (CPU-heavy, byte-splittable). Validation and training views follow.
4. Add `worker_group` → host mapping in config to pin stages to machines
    (devpc 16C/30GB for classification; Mac control-plane for orchestration).
