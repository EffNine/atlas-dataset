# Universal Scheduler Phase 5 — Acquisition Migration Design

**Date:** 2026-08-01
**Status:** PROPOSED — audit complete, awaiting review before implementation
**Audit reference:** `reports/parallelism/atlas_acquisition_audit.md`
**Architecture reference:** `docs/architecture/universal_adaptive_scheduler_v1.md`

---

## 1. Objective

Migrate the acquisition pipeline's sequential execution loops to the
Universal Scheduler (`scripts/parallel/`) while:

- preserving acquisition logic, license gates, record generation, cache
  semantics, and output schemas exactly;
- adding adaptive workers, bounded submission, retry, TaskRegistry
  checkpoint/resume, and crash recovery;
- keeping the original sequential loops as fallback (backward compatible).

**Explicitly out of scope:** dataset changes, HF operations, release
changes, production acquisition runs, cache internals.

---

## 2. Target Architecture

### 2.1 Shared subsystem reuse

| `scripts/parallel/` module | Use in acquisition |
|---------------------------|--------------------|
| `config.py` | Replace `engine._load_file_workers()` hand parser with `load_parallelism_config()` / `resolve_worker_count("acquisition")` |
| `resource.py` | `safe_worker_limit()` for adaptive workers; disk headroom rule |
| `models.py` | `Task`, `TaskResult` |
| `registry.py` | `TaskRegistry` stage `"acquisition"` |
| `planner.py` | `file_tasks` for knowledge-pack loading; source-level task builders |
| `scheduler.py` | `Scheduler(stage="acquisition", pool=...)` |
| `monitor.py` | Optional per-run report |

### 2.2 Two schedulers, two pools

Because download is I/O-bound and engine record generation is CPU-ish:

| Migration | Pool | Rationale |
|-----------|------|-----------|
| `DownloadAgent` | `thread` | Network I/O; also avoids macOS SQLite fork segfault and serializes SQLite index writes via GIL |
| `AcquisitionEngine.execute` | `process` (fallback sequential on Mac) | CPU record generation; same pattern as Phases 1–4 |

---

## 3. Task Model

### 3.1 Download task

```python
Task(
    task_id="acq:download:{source_id}",
    source=source_id,
    operation="download_source",
    input=source_id,
    estimated_size_mb=0.0,          # unknown until adapter resolves URLs
    priority=1,
    extra={
        "root": str(root),
        "source": registry_entry,   # serialized source dict
        "adapter": "huggingface",   # selected adapter name
        "dry_run": False,
    },
)
```

- `output_target`: implicit — cache object + `metadata/download_logs/{sid}.download.json`
  (the worker writes them exactly as today).

### 3.2 Engine source task

```python
Task(
    task_id="acq:engine:{batch_id}:{source_id}",
    source=source_id,
    operation="engine_source_pipeline",
    input=source_id,
    extra={
        "root": str(root),
        "batch_id": bid,
        "dataset": manifest_dataset,   # serialized
        "registry_entry": reg,
        "max_records": N,
    },
)
```

- `output_target`: implicit — `curated/v0.1/pilot_candidates.jsonl` (batch
  append) + per-source checkpoint status.

---

## 4. Planner Strategy

### 4.1 `plan_download_tasks(source_ids, root, ...)`

One Task per source (source-level, Option A). Deterministic `task_id`
(`acq:download:<sid>`) → sorted results preserve source order, and
completed-skip prevents duplicate acquisition.

### 4.2 `plan_engine_tasks(manifest, max_records, ...)`

One Task per (batch, source). Deterministic `task_id`
(`acq:engine:<bid>:<sid>`). Batch completion derived from per-source task
statuses (all completed → batch completed).

### 4.3 Knowledge-pack loading (cleanup)

Use existing `parallel.planner.file_tasks` + scheduler — removes the
duplicate `_load_one` ProcessPool loader.

---

## 5. Registry Usage

- Stage name: `"acquisition"` → `metadata/pipeline_state/task_registry_acquisition.jsonl`.
- State mapping (engine checkpoint ↔ registry):

| Engine `SourceCheckpoint.status` | Registry status |
|----------------------------------|-----------------|
| pending | pending |
| resolving / downloading / pipelining | running |
| completed | completed |
| failed (permanent) | failed (after retries exhausted) |
| skipped | skipped |
| — (crash mid-download) | running → **re-claimed to pending** after lease (new capability) |

- **Resume**: completed tasks skipped; stale `running` re-claimed after
  lease (default 900 s) — fixes the current engine gap.
- **Duplicate prevention**: deterministic task_ids make double-acquisition
  impossible on rerun.

---

## 6. Worker Implementation

### 6.1 `download_task(task) -> dict`

```python
def download_task(task):
    """Module-level (picklable). Wraps today's per-source download logic."""
    extra = task.extra
    source = extra["source"]
    adapter = select_adapter(source, adapters_for(root))
    if adapter is None:
        raise RuntimeError(f"no adapter for {task.source}")
    result = adapter.download(source, dry_run=extra["dry_run"])
    if result.status == DownloadStatus.FAILED:
        raise RuntimeError(f"download failed: {result.errors}")
    if not extra["dry_run"]:
        _write_download_log(task.source, result)   # unchanged function
    return {"source_id": task.source, "status": result.status.value,
            "files": result.files, "entries": [...], "errors": result.errors}
```

### 6.2 `engine_source_task(task) -> dict`

```python
def engine_source_task(task):
    """Module-level (picklable). Wraps today's per-source engine pipeline."""
    extra = task.extra
    # resolve registry -> license gate -> generate records -> dedup -> score
    # (extracted verbatim from AcquisitionEngine.execute inner loop)
    # returns per-source stats; raises RuntimeError on gate failure
```

**Key rule:** the worker bodies are extracted **verbatim** from the current
sequential loops — no logic changes, only relocation into module-level
functions.

---

## 7. Backward Compatibility

1. `AcquisitionEngine.execute()` / `resume()` keep their public signatures.
2. `CheckpointManager` becomes a **facade**: it still reads/writes
   `metadata/engine_checkpoint.json` in the same shape, but derives
   completed-batch/source state from the TaskRegistry (single source of
   truth) OR keeps its own file and syncs both — the contract test enforces
   equivalence.
3. `DownloadAgent.execute()` keeps its exact `AgentResult` payload shape.
4. Fallback: any scheduler import error → original sequential loop
   (identical output; same pattern as Phases 1–4).
5. Cache, adapters, license constants, lifecycle, integrity, provenance —
   **untouched**.

---

## 8. Resource Awareness

| Rule | Enforcement |
|------|-------------|
| Adaptive workers | `Scheduler(workers=None)` → `safe_worker_limit()` |
| RAM safety | 0.8 margin; per-task `default_per_task_ram_mb` (512) |
| Disk headroom | scheduler `disk_headroom_gb` (10 GB) rule; cache is content-addressed (re-download cheap) |
| No full-corpus load | source-level tasks stream per source |
| No duplicate writes | deterministic task_ids; completed-skip; per-source `download.log` written once |

---

## 9. Failure Scenarios

| Scenario | Handling |
|----------|----------|
| Worker crash mid-download | partial file kept (`raw/.cache/partial`); task failed → retry → Range resume; registry `running` re-claimed after lease |
| Machine reboot | registry completed-skip + lease re-claim on restart |
| Disk full | disk headroom rule pauses submission; cache objects verified before commit |
| Duplicate task execution | deterministic task_id + completed-skip (test: same source twice → second run skipped) |
| Network interruption | existing `download_with_resume` retry/backoff unchanged |
| License gate failure | worker raises → retry → terminal failed; engine marks source failed (same as today) |

---

## 10. Implementation Plan

### Phase 5B — Downloader migration (IMPLEMENTED)

**Constraints applied (approved):**
1. **Scheduler = execution orchestration only.** Cache handling, HTTP Range
   resume, checksum verification, and adapter logic stay in
   `downloader/cache.py` + `downloader/adapters/`. `scheduler_tasks.py`
   only plans/executes — the worker calls the unchanged `adapter.download`
   and `_write_download_log`.
2. **Deterministic task identity:** `download:<source_id>:<url_hash>` —
   `url_hash` is a 12-char SHA-256 of the source URL. Same URL → same task
   (duplicate prevention); URL change → new task (never mistaken for a
   duplicate of the old source).
3. **engine_checkpoint.json retained.** The downloader does not write it;
   the AcquisitionEngine facade migration (Phase 5C) will implement the
   TaskRegistry adapter on top of the existing checkpoint file. Nothing in
   5B removes or alters `metadata/engine_checkpoint.json`.
4. **I/O-aware scheduling:** `resource.safe_io_worker_limit()` —
   `min(io_worker_cap (config, default 8), RAM margin, explicit cap)`.
   Downloader workers do NOT scale on CPU cores (bandwidth/disk/memory are
   the limiting factors). Scheduler accepts `worker_limit_fn` for this.

**Implementation:**
- `scripts/downloader/scheduler_tasks.py`: `download_task_id`,
  `plan_download_tasks`, `download_task` (module-level worker),
  `run_download_scheduler` (thread pool + `safe_io_worker_limit` +
  TaskRegistry + sequential fallback). `_SCHEDULER_ENABLED` kill-switch.
- `scripts/parallel/resource.py`: `safe_io_worker_limit()`.
- `scripts/parallel/config.py`: `global.io_worker_cap` default 8.
- `scripts/parallel/scheduler.py`: `worker_limit_fn` param + in-run task_id
  dedupe (fixes terminal-state registry error on duplicate input sources).
- `scripts/downloader/download_agent.py`: `execute()` uses
  `run_download_scheduler` with sequential fallback (identical behavior).

**Tests:** `tests/test_scheduler_acquisition.py` (15 tests: task identity,
I/O-aware limits, end-to-end, retry, resume, cache-conflict prevention,
fallback).

### Phase 5C — Engine pipeline migration (NEXT — not started)

1. Add `acquisition_engine/scheduler_tasks.py`: `engine_source_task`,
   `plan_engine_tasks`, `run_engine_scheduler` (with sequential fallback).
2. Swap `execute()` inner loop; **`CheckpointManager` facade that keeps
   `metadata/engine_checkpoint.json`** and adapts TaskRegistry state into
   the same checkpoint shape (constraint 3).
3. Tests: resume-equivalence contract, license gate preserved, dedup
   preserved, record counts identical, failed-source recovery.
4. Verify: `pytest`, arch validator, ad-hoc probe.

### Phase 5D — Cleanup

1. `generate_knowledge_pack` loader → `parallel` file tasks.
2. `_load_file_workers()` → shared `parallel.config`.
3. Remove duplicate loader.

### Deliverables per phase

- Implementation commits (separate per phase).
- `tests/test_scheduler_acquisition.py`.
- `reports/parallelism/scheduler_phase5_acquisition_report.json`.
- Docs update: `docs/parallel/universal_scheduler_usage.md` section
  "Migration example: Acquisition".

---

## 11. Test Requirements

| Test | Covers |
|------|--------|
| `test_plan_download_tasks` | one source = one task; deterministic ids; sorted |
| `test_download_retry_then_completed` | transient failure retried |
| `test_download_terminal_failure` | after max_retries → failed; registry terminal |
| `test_resume_skips_cached` | rerun skips completed sources |
| `test_cache_conflict_prevention` | same source_id twice → no double download |
| `test_engine_resume_equivalence` | CheckpointManager vs registry statuses match |
| `test_engine_license_gate_preserved` | denied license → failed, not crash |
| `test_engine_dedup_preserved` | duplicate records rejected identically |
| `test_output_identity` | old vs new → same hashes (modulo `utc_now`) |
| `test_fallback` | scheduler import error → sequential identical |

---

## 12. Verification Strategy

- Full pytest suite (Phases 1–4 must stay green).
- `validate_architecture.py` PASS.
- Fresh ad-hoc verification probe (temp-file pattern used in Phases 1–4).
- No production acquisition run; all tests use fixtures under `tmp_path`.

## 13. Rollback Strategy

- Each phase = additive scheduler path + preserved fallback.
- Rollback = revert the swap commit; behavior identical to pre-migration.
- No dataset/release/HF mutation at any point.
