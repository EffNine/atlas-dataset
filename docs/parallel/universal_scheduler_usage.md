# Universal Scheduler — Usage Guide (Phase 1)

**Status:** Implemented (Phase 1 — foundation + validation pilot)
**Date:** 2026-08-01
**Architecture reference:** `docs/architecture/universal_adaptive_scheduler_v1.md`
**ADR:** ADR-015

---

## 1. What exists now

The shared parallel subsystem lives in `scripts/parallel/`:

| Module | Responsibility |
|--------|---------------|
| `config.py` | Single YAML loader for `config/parallelism.yaml`, env overrides (`ATLAS_WORKERS_*`), hardware profiles (`ATLAS_PROFILE`, hostname) |
| `resource.py` | CPU/RAM/disk detection, GPU placeholder, `safe_worker_limit()` |
| `models.py` | `Task`, `TaskResult`, `WorkerCapacity` dataclasses |
| `registry.py` | Append-only JSONL task state machine (pending/running/completed/failed/retry), crash re-claim, resume |
| `planner.py` | Workload → tasks: file / shard / byte-range |
| `scheduler.py` | Adaptive worker pool: bounded submission, backpressure, retry, deterministic ordering |
| `monitor.py` | Runtime metrics + `reports/performance/{stage}_scheduler_report.json` |
| `runner.py` | **Legacy** `ParallelRunner` (v1.9) — kept for backward compatibility |

Backward compatibility: `from parallel import ParallelRunner, JobResult, ParallelResult`
still works (moved to `runner.py`, re-exported).

---

## 2. How a pipeline developer uses the scheduler

The pattern is always the same — plan → run → collect:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))

from parallel import Scheduler, file_tasks


def my_worker(task) -> dict:
    """Module-level worker — required for process pools (pickling)."""
    # process one file:
    result = expensive_thing(Path(task.input))
    return {"record_count": result.n, "errors": result.errs}


def main():
    files = sorted(Path("data").glob("*.jsonl"))

    # 1. Plan: one task per file.
    tasks = file_tasks(files, source="my_stage", operation="my_op")

    # 2. Run: scheduler owns the pool, registry, retry, resume.
    sched = Scheduler(
        "my_stage",                       # stage key (config + registry name)
        registry_root="metadata/pipeline_state",
        workers=None,                     # None -> adaptive (config/env/safety)
        pool="process",                   # 'process' (CPU) | 'thread' (I/O)
        max_retries=2,
    )
    results = sched.run(tasks, my_worker)

    # 3. Results are sorted by task_id (deterministic).
    for tr in results:
        if tr.status == "completed":
            print(tr.task_id, tr.result)
        elif tr.status == "failed":
            print("FAILED", tr.task_id, tr.error)
```

### Worker function contract

- `worker_fn(task) -> result` — receives a `Task`, returns anything (dict
  preferred; `record_count`/`total`/`classified` keys feed the monitor).
- For **process pools** the worker must be **module-level and picklable**
  (no lambdas, no closures). Use `pool="thread"` for I/O-bound work where a
  lambda is acceptable.

### Task kinds (planner)

```python
from parallel import file_tasks, shard_tasks, byte_range_tasks

# One task per file
tasks = file_tasks(files, source="validation", operation="validate_one_file")

# Byte-range split of a large single shard into ~target_size_mb chunks
tasks = byte_range_tasks(
    big_file, source="extraction", operation="extract",
    target_size_mb=64, max_size_mb=128, min_split_mb=128,
)
# Each task carries offset_start/offset_end; stream with task_line_range_reader(task)
```

---

## 3. Configuration

`config/parallelism.yaml` remains the single source of truth. Worker counts
can be `auto` (scheduler computes from hardware) or an explicit int:

```yaml
parallelism:
  global:
    safety_margin_ram: 0.8
    default_per_task_ram_mb: 512
    disk_headroom_gb: 10
  validation:
    file_workers: 8        # or 'auto'
    chunk_size: 1000
```

Resolution precedence for a worker count:
1. CLI / explicit argument (highest)
2. `ATLAS_WORKERS_<STAGE>` env var (e.g. `ATLAS_WORKERS_VALIDATION=4`)
3. `config/parallelism.yaml`
4. `safe_worker_limit()` from detected hardware (lowest, but never violated
   — even an explicit count is capped by RAM safety)

Hardware profiles: `ATLAS_PROFILE=dev-pc` or hostname match in
`hardware_profiles` (see `config.py:HARDWARE_PROFILES`).

---

## 4. Validation pilot (Phase 1)

`scripts/validate_dataset.py` now uses the scheduler when validating
multiple files:

```bash
# Same CLI as before — execution layer is scheduler-owned.
python scripts/validate_dataset.py --input "metadata/curated/*.jsonl" --file-workers 8

# Scheduler path: adaptive workers + TaskRegistry resume + retry.
# Fallback to the old manual ProcessPoolExecutor if import fails (behavior identical).
```

**Behavior guarantees (verified by tests):**
- Same record counts, failures, and report output as the manual pool path.
- Results deterministic (sorted by task_id).
- Registry at `metadata/pipeline_state/task_registry_validation.jsonl` —
  completed tasks are skipped on re-run; stale `running` tasks re-claimed
  after 15 min lease.

---

## 5. Resume & crash recovery

- Registry is append-only JSONL. Re-run the same command and completed
  tasks are skipped (`status='skipped'` in results).
- A worker crash marks a task `failed`; the scheduler retries up to
  `max_retries` (default 2) with backoff.
- A machine reboot: tasks stuck in `running` are re-claimed to `pending`
  after `lease_seconds` (default 900 s).
- Terminal states are `completed` / `skipped` / `failed`; `retry` is only an
  intermediate transition owned by the scheduler.

---

## 6. Examples

### Example 1 — validation (real pipeline)

```bash
cd /path/to/atlas-dataset
export ATLAS_WORKERS_VALIDATION=6   # override config
python scripts/validate_dataset.py --input "data/release/*.jsonl" --quiet
# -> [validate] scheduler: validating 24 files with 6 adaptive workers...
# -> [validate] RESULT: PASS
```

### Example 2 — a new stage with byte-range tasks

```python
from parallel import Scheduler, byte_range_tasks, task_line_range_reader

def process_chunk(task):
    for idx, line in task_line_range_reader(task):
        ...  # process one JSONL line range without loading the whole file
    return {"record_count": n}

tasks = byte_range_tasks("raw/big.jsonl", source="etl", operation="chunk",
                         target_size_mb=64, min_split_mb=128)
sched = Scheduler("etl", registry_root="metadata/pipeline_state", pool="process")
results = sched.run(tasks, process_chunk)
```

### Example 3 — monitoring

```python
from parallel import Scheduler, Monitor

mon = Monitor("validation")           # writes reports/performance/validation_scheduler_report.json
sched = Scheduler("validation", registry_root="metadata/pipeline_state")
results = sched.run(tasks, my_worker)
for tr in results:
    if tr.status == "completed":
        mon.record_completed(records=_count(tr.result))
    elif tr.status == "failed":
        mon.record_failed()
report = mon.finish({"total_tasks": len(tasks)})
```

---

## 7. Current limitations (Phase 1)

- `monitor.py` exists but is **not yet wired into the validation CLI** (the
  scheduler does not call it automatically). Pipelines may use it explicitly.
- Backpressure currently pauses on low RAM only; CPU/disk backpressure is
  designed but not enforced.
- GPU detection is a placeholder (returns `present: false` unless
  nvidia-smi/torch found); no pipeline schedules on GPU yet.
- Only **validation** is migrated. Extraction, training views, acquisition,
  release remain on their existing executors (next phases).

---

## 8. Migration example: Extraction (Phase 2)

The extraction runner (`scripts/run_extract_all.py`) is the second pipeline
migrated to the Universal Scheduler. It fans out per-shard invocations of
`scripts/extract_wiki_<source>.py` (one subprocess per shard).

### Before (Phase 1 baseline)

```python
# Manual ProcessPoolExecutor — no registry, no resume, fixed workers.
with ProcessPoolExecutor(max_workers=shard_workers) as ex:
    futures = {ex.submit(extract_one, t): t for t in tasks}
    for fut in as_completed(futures):
        _, shard, out = fut.result()
        ...
```

### After (Phase 2 — scheduler)

```python
def plan_extraction_tasks(source, shards_per_source, script_dir=None):
    # one shard = one task; byte-range split supported by planner for future
    return [
        Task(
            task_id=f"extract:{source}:{s:03d}",
            source=source,
            operation="extract_wiki_shard",
            input=str(script_dir / f"extract_{source}.py"),
            extra={"shard": s},
        )
        for s in range(shards_per_source)
    ]

def extract_task(task) -> dict:
    """Module-level scheduler worker (picklable for process pools)."""
    shard = int(task.extra["shard"])
    r = subprocess.run([sys.executable, task.input, str(shard)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"shard {shard}: {r.stderr[-200:]}")
    return {"shard": shard, "output": ...}
```

CLI is unchanged — the scheduler path is automatic with a fallback:

```bash
python scripts/run_extract_all.py --all --shard-workers 8
# -> [scheduler:extraction] reclaimed N stale running task(s)   (after crash)
# -> [wiki_sys] 41/41 shards done
# registry: metadata/pipeline_state/task_registry_extraction.jsonl
```

### Behavior guarantees (verified by tests)

- **Output identical**: manual pool vs scheduler produce byte-identical
  per-shard JSONL files (SHA-256 equality).
- **One shard = one task**, deterministic `task_id` (`extract:<source>:NNN`).
- **Resume**: completed shards are skipped on re-run; a shard stuck
  `running` (crash) is re-claimed after the lease (default 900 s) and re-run.
- **Retry**: failed shards retried up to `max_retries` (default 2) with
  backoff.
- **Duplicate prevention**: completed tasks are terminal — never re-run.
- **Resource-aware**: adaptive workers capped by `safe_worker_limit()`
  (RAM margin 0.8, CPU cores, optional explicit cap).
- **Fallback preserved**: if the scheduler import fails, the runner falls
  back to the original manual ProcessPoolExecutor with identical behavior.

---

## 9. Migration example: Training Views (Phase 3)

The training view engine (`scripts/training_view_engine/`) is the third
pipeline migrated. Two parallel layers now run through the Universal
Scheduler:

1. **Curated file loading** (`generator._load_curated_records`) — file
   tasks.
2. **Record validation** (`validator.validate_records`) — record-range
   tasks.

### Task design

For validation we chose **record-range tasks** (Option B): the existing
pipeline already chunks the in-memory records list, so each task carries the
chunk in `extra` (mirroring `_validate_chunk_standalone`'s pickling
contract) plus `offset_start`/`offset_end` identifying the original range.
`task_id` encodes the offsets (`tv:validate:<start>:<end>`) so
deterministic ordering = original record order.

```python
Task(
    task_id="tv:validate:000000:000031",
    source="training_views",
    operation="validate_record_range",
    input="",                 # records travel in extra (in-memory chunks)
    offset_start=0,
    offset_end=31,
    extra={"records": chunk, "quality_threshold": 7},
)
```

For loading we chose **file tasks** (Option A):

```python
from parallel.planner import file_tasks
tasks = file_tasks(files, source="curated/v0.1", operation="load_curated_file")
# worker: _load_curated_file_task(task) -> reads task.input, returns records
```

### Behavior guarantees (verified by tests)

- **Deterministic generation**: scheduler path produces identical
  `validate_records` results to sequential (same record_ids, same validity,
  same order) — including invalid records at known positions.
- **Ordering**: task_id encodes offset ranges, so sorted results preserve
  the original record order and the sorted-files order for loading.
- **Schema preserved**: validation results keep
  `{record_id, valid, errors}`; loaded records are byte-identical.
- **Resume**: completed tasks skipped on re-run; stale `running` re-claimed
  after lease.
- **Retry**: failed record-range tasks retried up to `max_retries`.
- **Fallback**: manual ProcessPoolExecutor preserved (scheduler error → old
  path, identical behavior).
- **Resource-aware**: worker count via `safe_worker_limit()`; record chunks
  are balanced (`len(records) // (workers * 4)`); no full dataset is loaded
  twice (chunks carry slices, not duplicates).

### CLI unchanged

```bash
# dry-run still works; generation logic, filters, manifests untouched.
python scripts/training_readiness.py --dry-run
# registry: metadata/pipeline_state/task_registry_training_views.jsonl
```

---

## 10. Migration example: ETL / Transform (Phase 4)

The ETL pipeline (`scripts/etl/pipeline.py` + `extract_agent.py`) is the
fourth pipeline migrated. The ETL unit is the **source** — each source runs
extract → normalize → clean → promote as one pipeline (with a cross-file
`limit`), so splitting per-file would change semantics. We chose
**source-level tasks** (a file/batch variant of Option A).

### Task design

```python
Task(
    task_id="etl:s1",                # deterministic, sorted by source_id
    source="s1",
    operation="run_etl_for_source",
    input="s1",
    extra={"root": "...", "limit": None, "promote_atlas": True},
)
```

### Worker

```python
def etl_task(task) -> dict:
    """Module-level scheduler worker (picklable for process pools)."""
    result = run_etl_for_source(Path(task.extra["root"]), task.input,
                                limit=task.extra["limit"],
                                promote_atlas=task.extra["promote_atlas"])
    if result.status == "failed":
        raise RuntimeError(f"ETL failed: {'; '.join(result.errors)}")
    return result.to_dict()
```

### Orchestrator

`run_etl_scheduler(root, source_ids, ...)` runs all sources through the
scheduler and returns EtlResult dicts sorted by source_id. On scheduler
error it falls back to the original sequential loop (identical behavior).
`ExtractAgent.execute` now uses it.

### Behavior guarantees (verified by tests)

- **Deterministic**: extracted.jsonl + atlas_staging.jsonl byte-identical
  (SHA-256) between scheduler and sequential runs; normalized/cleaned files
  carry `created_at=utc_now()` (pre-existing pipeline behavior) so they are
  compared by record count + record ids.
- **Ordering**: results sorted by source_id (task_id order).
- **Resume**: completed sources skipped on re-run (report.json reloaded);
  stale `running` re-claimed after lease.
- **Retry**: failed source tasks retried up to `max_retries`.
- **Failure recovery**: a source with no cached files returns a `failed`
  result dict (not a crash).
- **Fallback**: sequential loop preserved on scheduler error (identical
  output).
- **Schema**: EtlResult keys + output files unchanged; immutable trees
  (curated/, raw/external/) untouched.

### CLI / agent unchanged

```bash
python scripts/automation_runner.py ... extract_agent ...
# registry: metadata/pipeline_state/task_registry_etl.jsonl
```

### Platform note (macOS)

`CacheManager` uses SQLite; forking a process that already opened a SQLite
connection segfaults on macOS (Python 3.9 fork hazard). On macOS the ETL
scheduler may fall back to the sequential executor — output is identical.
On dev-pc (Linux) fork+SQLite is safe, so the process pool is used.

---

## 11. Migration example: Acquisition — Downloader (Phase 5B)

The downloader (`scripts/downloader/`) now runs through the Universal
Scheduler. This migration is **execution orchestration only** — cache
handling, HTTP Range resume, checksum verification, and adapter logic are
unchanged.

### Deterministic task identity

```python
from downloader.scheduler_tasks import download_task_id

download_task_id("s1", "https://example.com/s1")
# -> "download:s1:9ee7ad79b2e2"   (download:<source_id>:<url_hash>)
```

Same URL → same task id (duplicate prevention via completed-skip). URL
change → new task id (never confused with the old source).

### I/O-aware worker limits

Download workers do **not** scale on CPU cores. `safe_io_worker_limit()`
returns `min(io_worker_cap, RAM margin, explicit cap)`:

```python
from parallel.resource import safe_io_worker_limit
limit = safe_io_worker_limit()   # config global.io_worker_cap (default 8)
```

The Scheduler accepts a `worker_limit_fn` for this:

```python
sched = Scheduler(
    "acquisition",
    registry_root="metadata/pipeline_state",
    pool="thread",                       # I/O-bound
    worker_limit_fn=safe_io_worker_limit,
)
```

### CLI / agent unchanged

```bash
python scripts/automation_runner.py download --mode download ...
# registry: metadata/pipeline_state/task_registry_acquisition.jsonl
# logs: metadata/download_logs/{sid}.download.json (unchanged)
```

### Fallback + kill-switch

- Any scheduler error → sequential loop (identical behavior).
- `downloader.scheduler_tasks._SCHEDULER_ENABLED = False` forces the
  fallback (operational kill-switch / test hook).
