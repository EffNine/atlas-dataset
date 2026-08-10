# Atlas Acquisition Pipeline — Audit Report (Phase 5A)

**Date:** 2026-08-01
**Status:** READ-ONLY AUDIT — no code changed, no dataset/release/HF operations
**Scope:** `scripts/acquisition_engine/`, `scripts/downloader/`, ETL ingestion path
**Purpose:** Baseline for Universal Scheduler Phase 5 (acquisition migration)

---

## 1. Current Architecture Map

### 1.1 Entry points

| Entry | Module | Purpose |
|-------|--------|---------|
| `AcquisitionEngine.execute()` | `scripts/acquisition_engine/engine.py` | Batch ingestion from acquisition manifest (batches → sources → records) with checkpoint resume |
| `AcquisitionEngine.dry_run()` | `engine.py` | Plan-only pass (no writes) |
| `AcquisitionEngine.resume()` | `engine.py` | Resume from `metadata/engine_checkpoint.json` |
| `DownloadAgent.execute()` | `scripts/downloader/download_agent.py` | Download acquired sources into content-addressable cache |
| `ExtractAgent.execute()` | `scripts/etl/extract_agent.py` (already scheduler-migrated, Phase 4) | Extract → Normalize → Clean cached downloads into staging JSONL |
| CLI: `atlas.py acq/plan/download/etl/...` | `scripts/atlas.py`, `scripts/automation_runner.py` | Orchestration commands |

### 1.2 Execution flow

```
AcquisitionEngine.execute()
  └─ load acquisition manifest (batches → datasets → source_ids)
  └─ CheckpointManager: create/resume engine_checkpoint.json
  └─ for each batch:
       for each source:
         resolve registry → license gate → download (simulated) →
         generate records → dedup → quality score → lifecycle →
         checkpoint source status (completed/failed/skipped)
  └─ validate output → write curated/v0.1/pilot_candidates.jsonl
  └─ checksums + verification log

DownloadAgent.execute()
  └─ load sources from registry
  └─ for each source (sequential):
       select adapter (hf/github/arxiv/stackexchange/documentation)
       adapter.download(source) → CacheManager.download_url/put_bytes
       → content-addressed cache (raw/.cache/objects/{aa}/{sha256})
       → write metadata/download_logs/{sid}.download.json

ExtractAgent.execute()  [Phase 4 migrated → run_etl_scheduler]
  └─ read cache files from download logs → extract → normalize → clean → promote
```

### 1.3 Worker model

| Component | Model | Notes |
|-----------|-------|-------|
| `AcquisitionEngine.execute` | **Sequential** loop (batch → source) | Per-source `checkpoint_mgr.update_source_status` |
| `AcquisitionEngine.generate_knowledge_pack` | **ProcessPoolExecutor** — only for parallel curated-file *loading* (`_load_one`) | `file_workers` from config |
| `DownloadAgent.execute` | **Sequential** loop (source → adapter.download) | No executor |
| `CacheManager` | Sequential I/O per call | SQLite index + content-addressed objects |
| `ExtractAgent` | **Universal Scheduler** (Phase 4) | Source-level tasks, registry, retry |

### 1.4 Data flow

```
source_registry.json (sources)
    │
    ▼
DownloadAgent → raw/.cache/objects/{aa}/{sha}  (content-addressed, verified)
    │
    ▼
metadata/download_logs/{sid}.download.json    (per-source log)
    │
    ▼
ExtractAgent → metadata/etl/{sid}/{extracted,normalized,cleaned,atlas_staging}.jsonl
    │
    ▼
AcquisitionEngine → curated/v0.1/pilot_candidates.jsonl  (engine path, synthetic)
```

Two largely independent ingestion paths:
1. **Engine path** (`AcquisitionEngine.execute`) — synthetic record generation from the acquisition manifest (pilot; real downloads "simulated").
2. **Downloader path** (`DownloadAgent` → `ExtractAgent`) — real external source acquisition via adapters → cache → ETL.

---

## 2. Parallelism Inventory

### 2.1 Executors present

| Location | Executor | Workload unit | Worker count source |
|----------|----------|---------------|---------------------|
| `acquisition_engine/engine.py:782` | ProcessPoolExecutor | curated file (load only) | `_load_file_workers()` → config `acquisition.file_workers` (default 1) |
| `etl/extract_agent.py` (Phase 4) | Universal Scheduler | source | config `parallelism` (adaptive) |
| `downloader/*` | **none** | — | — |

### 2.2 Hardcoded worker counts

- `engine.py _load_file_workers()`: reads config, fallback `1` — **not hardcoded**, but the only parallel point.
- No hardcoded `max_workers` in downloader.
- Phase 4 ETL uses the scheduler (no manual counts).

### 2.3 Custom worker loops

- `AcquisitionEngine.execute`: manual per-source loop with `update_source_status` state machine (checkpoint-driven, sequential).
- `DownloadAgent.execute`: manual per-source loop (sequential, no state machine — status collected into lists).

### 2.4 Duplicated parallel helpers (from Phase-1 audit finding, still valid)

1. **Parallel curated-file loader duplicated**: `acquisition_engine.engine.generate_knowledge_pack` (`_load_one` closure + ProcessPool) vs `training_view_engine.generator._load_curated_records` (Phase 3, now scheduler-based) — same pattern, separate implementations.
2. **Config parsing duplicated**: `_load_file_workers()` in engine.py still hand-parses `config/parallelism.yaml` — should use `parallel.config.load_parallelism_config()` (Phase 1 shared loader).
3. **Resume mechanisms diverged**: `CheckpointManager` (engine JSON checkpoint) vs `TaskRegistry` (scheduler JSONL) — two resume systems coexist.
4. **Source-status state machine duplicated in spirit**: engine's `SourceCheckpoint.status` (pending/resolving/downloading/pipelining/validating/completed/failed/skipped) parallels scheduler registry states (pending/running/completed/failed/retry).

---

## 3. Resume and Recovery Analysis

### 3.1 Current checkpoint mechanism

- **`CheckpointManager`** (`acquisition_engine/checkpoint.py`):
  - Single JSON file: `metadata/engine_checkpoint.json`.
  - `EngineCheckpoint`: session_id, status, current_batch, completed_batches, per-source `SourceCheckpoint{status, records_processed, records_accepted, error}`.
  - `_save()` writes the whole document; `_compute_checksum()` guards integrity.
  - `resume()`: skips completed batches and completed sources; re-runs the rest.
- **Downloader resume**: `CacheManager.download_url` skips already-cached source_refs (no re-download) unless `force`; HTTP `Range` resume in `http_util.download_with_resume` for partial transfers; `partial/{ref}.partial` files.

### 3.2 Partial download handling

- HTTP Range resume: partial file kept in `raw/.cache/partial/{ref}.partial`; on retry, `Range: bytes={existing}-`; if server ignores Range, restart from scratch.
- Checksum mismatch → partial deleted, raises `ValueError` (no corrupt object is committed).

### 3.3 Crash recovery behavior

- **Engine**: a crash mid-batch leaves checkpoint at "running"; `resume()` re-enters and skips completed sources. Completed batches skipped via `completed_batches`. No lease-based re-claim (a source stuck "downloading" is NOT re-claimed automatically — the checkpoint status persists as-is).
- **Downloader**: no checkpoint file; re-run uses cache-existence skip + partial resume. Source status is derived from cache/logs on each run.
- **ETL (Phase 4)**: scheduler registry handles crash recovery (completed skip, stale `running` re-claim after lease).

### 3.4 Retry behavior

- **Downloader**: `CacheManager` retry/backoff in `download_with_resume` (max_retries default 3, backoff_base 0.5s); `fetch_bytes` retries transient errors (5xx/429/408), not permanent 4xx.
- **Engine**: no retry — a failed source is marked `failed` and skipped on resume (must be re-run explicitly).
- **ETL (Phase 4)**: scheduler retry (max_retries=2) per source.

---

## 4. Scheduler Migration Design (Proposal)

### 4.1 Overall strategy

Migrate the **two sequential loops** to the Universal Scheduler:

1. **`DownloadAgent.execute`** — source-level tasks (one Task per source; worker runs `adapter.download`).
2. **`AcquisitionEngine.execute`** — source-level tasks per batch (worker runs the per-source pipeline: resolve → license → generate → dedup → score).

Keep the existing `CheckpointManager` as the **compatibility layer** on top of the scheduler registry (see 4.6), or migrate resume semantics to `TaskRegistry` with a thin checkpoint adapter.

### 4.2 Task model

```python
Task(
    task_id="acq:download:arxiv_123",        # deterministic source-level id
    source="arxiv_123",
    operation="download_source",             # or "engine_source_pipeline"
    input="arxiv_123",                       # source_id
    estimated_size_mb=0.0,                   # unknown pre-download; set 0 / optional
    priority=1,
    status="pending",
    extra={
        "root": "...",
        "source": {...},                     # registry entry (serialized)
        "adapter": "arxiv",
        "dry_run": False,
        "limit": None,
        "promote_atlas": True,
    },
)
```

Every task carries `task_id`, `operation`, `input`, `estimated_size`, `output_target` (per the Phase-5 spec).

### 4.3 Planner strategy

- **Downloader**: `plan_download_tasks(source_ids, ...)` → one Task per source (source-level, Option A — the download unit is a source; splitting a single adapter download is not meaningful).
- **Engine**: `plan_engine_tasks(batch_id, sources, ...)` → one Task per (batch, source).
- Future: byte-range/record-range only if a source download becomes a bulk multi-file job (then each file → Task).

### 4.4 Registry usage

- Stage: `"acquisition"` → `metadata/pipeline_state/task_registry_acquisition.jsonl`.
- Task states map to engine semantics:
  - `pending` ↔ engine "pending"
  - `running` ↔ "resolving/downloading/pipelining"
  - `completed` ↔ "completed"
  - `failed`/`retry` ↔ "failed" (retryable) / "skipped" (permanent)
- **Crash recovery**: scheduler lease-based re-claim of stale `running` (fixes the engine gap where a source stuck mid-download is never re-claimed).
- **Duplicate prevention**: deterministic task_ids + completed-skip (fixes double-acquisition risk).

### 4.5 Worker implementation

```python
def download_task(task) -> dict:        # module-level, picklable
    """Run DownloadAgent per-source logic for one Task."""
    # resolve source, select adapter, adapter.download(source, dry_run=...)
    # return {source_id, status, files, entries, errors, ...}
    # raise on failure so scheduler retries

def engine_source_task(task) -> dict:   # module-level, picklable
    """Run AcquisitionEngine per-source pipeline for one Task."""
    # registry resolve → license gate → generate records → dedup → score
    # return per-source stats
    # raise on failure so scheduler retries
```

Both workers are **module-level** (picklable) and wrap existing functions — extraction logic, license gates, record generation, and schemas stay untouched.

### 4.6 Backward compatibility

- Keep `CheckpointManager` as-is for the engine's public API (`execute()`, `resume()`): it becomes a thin facade that (a) creates a scheduler run, (b) reads registry states to answer "completed batches/sources", (c) writes the same `engine_checkpoint.json` shape for downstream consumers (tests, `atlas.py`).
- `DownloadAgent.execute()` keeps its exact AgentResult shape; the internal loop swaps to `run_download_scheduler()`.
- Fallback: sequential loops preserved on scheduler import error (identical to Phases 1–4 pattern).
- `generate_knowledge_pack`'s inline ProcessPool loader → `parallel` file tasks (removes the duplicate loader; same output).

### 4.7 Resource awareness

- Adaptive workers via `safe_worker_limit()` (RAM margin 0.8, CPU cores) — the downloader is I/O-bound (thread pool) while the engine pipeline is CPU-ish (process pool).
- Per-task RAM estimate: `default_per_task_ram_mb` (512).
- Download disk headroom: scheduler `disk_headroom_gb` rule (never fill cache disk); cache objects are content-addressed so re-downloads are cheap.
- No full-corpus load: source-level tasks stream per source.

---

## 5. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Data corruption** (cache object half-written) | MEDIUM | CacheManager already commits only after SHA-256 verify; scheduler retry reuses partial resume. Do NOT change cache commit semantics. |
| **Cache conflicts** (two tasks writing same source_ref concurrently) | HIGH | Content-addressed paths are deterministic (same URL+content → same object); SQLite index writes must be serialized. Use thread pool for downloads (GIL serializes sqlite writes) OR add a per-source lock / registry claim. **Never** run two tasks for the same source_id. |
| **Duplicate acquisition** (same source downloaded twice) | MEDIUM | Deterministic task_id + completed-skip prevents re-download; cache-existence skip already prevents re-put. Verify with a "download then rerun" test. |
| **License/provenance errors** | MEDIUM | License gate runs inside the worker (unchanged logic); provenance fields (`source_attribution`, `lineage`) written by existing code. Do not reorder gates. |
| **Migration risk: engine checkpoint semantics drift** | MEDIUM | Keep `CheckpointManager` facade; add a contract test: `resume()` after scheduler run returns identical completed-source sets. |
| **macOS SQLite fork segfault** (observed Phase 4) | LOW (Mac only) | Downloader uses thread pool (no fork); engine process pool may fall back to sequential on Mac — output identical. devpc Linux unaffected. |
| **Network-block safety** | MEDIUM | `install_network_block()` used by engine dry-run; ensure scheduler workers inherit the blocked opener only when intended (tests) — never in real download mode. |

---

## 6. Migration Plan

### Phase 5B — Downloader migration (first)

- **Implement**: `plan_download_tasks`, `download_task`, `run_download_scheduler` in `downloader/`; swap `DownloadAgent.execute` loop with fallback.
- **Tests** (`tests/test_scheduler_acquisition.py`): task planning, cache conflict prevention (same source twice), resume (cached skip), retry, deterministic ordering, fallback.
- **Verification**: old vs new download on fixture → same files, same hashes, same cache entries.

### Phase 5C — Engine pipeline migration (second)

- **Implement**: `engine_source_task`, `plan_engine_tasks`, scheduler-run inside `execute()`; `CheckpointManager` facade reads registry.
- **Tests**: resume-equivalence contract (checkpoint statuses match), license gate preserved, dedup preserved, record counts identical, failed-source recovery.
- **Verification**: dry-run + execute on manifest fixture → identical `pilot_candidates.jsonl` hashes (modulo `utc_now` fields), same stats.

### Phase 5D — Cleanup

- Replace `generate_knowledge_pack` inline loader with `parallel` file tasks.
- Migrate `_load_file_workers()` to shared `parallel.config.load_parallelism_config()`.
- Remove duplicate loader (training views already migrated).

### Test requirements

- All Phase 1–4 suites must stay green (scheduler regression).
- New `tests/test_scheduler_acquisition.py` covering: planning, worker limits, retry, resume, failed-task recovery, deterministic output, **cache conflict prevention**, fallback.

### Verification strategy

- `pytest` full suite + architecture validator + fresh ad-hoc verification probe (same as Phases 1–4).
- Phase 5B report: `reports/parallelism/scheduler_phase5_acquisition_report.json`.

### Rollback strategy

- Each phase is an additive scheduler path with the **original sequential loop preserved as fallback** — rollback = revert the swap (one commit), identical behavior.
- No dataset/release/HF changes at any point; all writes stay inside `metadata/`, `raw/.cache/`, `curated/v0.1/` test fixtures only.

---

## 7. Summary Table

| Component | Current model | Workers | Resume | Scheduler target |
|-----------|--------------|---------|--------|------------------|
| `AcquisitionEngine.execute` | sequential loop + CheckpointManager | 1 (config loader unused here) | JSON checkpoint, no lease | source tasks + registry |
| `generate_knowledge_pack` load | ProcessPool (duplicate loader) | config file_workers | none | parallel file tasks |
| `DownloadAgent.execute` | sequential loop | 1 | cache-existence + Range resume | source tasks + registry |
| `CacheManager` | sequential I/O | 1 | partial resume + verify | unchanged (safety-critical) |
| `ExtractAgent` | **scheduler (Phase 4)** | adaptive | registry | already migrated |

**Audit verdict:** acquisition is migratable with low risk if (a) download tasks stay source-level, (b) cache commit semantics are untouched, (c) CheckpointManager becomes a facade, (d) per-source task identity prevents concurrent same-source tasks. Design doc follows.
