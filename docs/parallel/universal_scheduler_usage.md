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
