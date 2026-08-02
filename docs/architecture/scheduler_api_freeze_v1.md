# Scheduler API Freeze v1

**Status:** Active  
**Version:** v1.0  
**Effective:** Atlas v1.9  
**Removal target for legacy:** Atlas v2.0

---

## 1. Purpose

Define the permanent, stable public API for the Universal Scheduler subsystem. All pipelines MUST use these interfaces. No pipeline may import from sub-modules directly or maintain its own parallel execution logic.

---

## 2. Public API

### 2.1 Allowed Imports

All pipelines MUST import from `parallel` package root:

```python
# Data models
from parallel import Task, TaskResult, WorkerCapacity

# Scheduler
from parallel import Scheduler, get_scheduler

# Registry (checkpoint/resume/retry)
from parallel import TaskRegistry

# Configuration
from parallel import load_parallelism_config
from parallel import resolve_worker_count, get_stage_config, get_global_config
from parallel import get_hardware_profile

# Resource detection
from parallel import safe_worker_limit, detect_cpu, detect_ram, detect_gpu
from parallel import disk_free, has_ram_headroom

# Task planning
from parallel import file_tasks, shard_tasks, byte_range_tasks
from parallel import plan_workload, read_jsonl_range, task_line_range_reader

# Monitor (optional)
from parallel import Monitor

# Test utility (e2e only)
from parallel import ParallelRunner, ParallelResult, JobResult
```

### 2.2 Forbidden Direct Imports

The following are INTERNAL IMPLEMENTATION. Do not import from sub-modules:

```python
# FORBIDDEN — use parallel.* instead
from parallel.config import load_parallelism_config  # ← import from parallel, not parallel.config
from parallel.scheduler import Scheduler            # ← import from parallel, not parallel.scheduler
from parallel.registry import TaskRegistry          # ← import from parallel, not parallel.registry
```

All of the above ARE available through `parallel.__init__.py` (the public API). Importing from sub-modules directly is permitted for internal scheduler development only.

---

## 3. Worker Resolution Precedence

```
CLI/Code: resolve_worker_count(stage, cfg, explicit=N)
    ↓
Environment: ATLAS_WORKERS_<STAGE_UPPER>
    ↓
Hardware profile: ATLAS_PROFILE or hostname match
    ↓
YAML config: config/parallelism.yaml
    ↓
Safe default: resource detection (cpu_cores, ram)
```

### Example Usage

```python
from parallel import resolve_worker_count, load_parallelism_config

cfg = load_parallelism_config()

# Method 1: Use resolve_worker_count (preferred)
workers = resolve_worker_count("validation", cfg)
if workers == "auto":
    workers = 1  # safe default

# Method 2: CLI override
workers = resolve_worker_count("validation", cfg, explicit=args.workers)

# Method 3: With environment override
# ATLAS_WORKERS_VALIDATION=16 python script.py
# → workers = 16
```

---

## 4. Pipeline Lifecycle

Every scheduler pipeline MUST follow this lifecycle:

```
Plan    → Generate deterministic Task objects (planner)
Registry → Register tasks with TaskRegistry (checkpoint/resume)
Scheduler → Execute via Scheduler.run() (adaptive workers, backpressure, retry)
Worker  → Pure function: worker_fn(Task) -> result
Result  → Collect TaskResults sorted by task_id (deterministic)
Finalize → Serialized merge/writes (after scheduler completes)
Monitor → Optional: Monitor for performance metrics
Complete → Write report, close
```

### 4.1 Minimal Pattern

```python
from parallel import Task, Scheduler, file_tasks, load_parallelism_config, resolve_worker_count

def worker_fn(task):
    """Pure function — no shared writes."""
    return {"records": load_file(task.input)}

tasks = file_tasks(files, source="stage", operation="op")
cfg = load_parallelism_config()
workers = resolve_worker_count("stage", cfg)
if workers == "auto":
    workers = 4

sched = Scheduler(
    "stage",
    registry_root="metadata/pipeline_state",
    workers=workers,
    pool="process",
    max_retries=2,
)
results = sched.run(tasks, worker_fn)
# results are sorted by task_id (deterministic)
```

### 4.2 What Workers MUST NOT Do

Workers are PURE FUNCTIONS. They must NOT:
- Write to shared state (files, registries, checkpoints)
- Modify global variables
- Perform deduplication or lifecycle transitions
- Write to output directories

All shared-state operations happen in the **serialized finalize** phase after `Scheduler.run()` returns.

---

## 5. Fallback Execution

Migrated pipelines retain a manual `ProcessPoolExecutor` fallback for crash safety:

```python
try:
    # Primary: universal scheduler path
    results = scheduler.run(tasks, worker_fn)
except Exception as exc:
    # Fallback: manual executor (identical behavior)
    print(f"scheduler unavailable ({exc}); falling back", file=sys.stderr)
    from concurrent.futures import ProcessPoolExecutor, as_completed
    with ProcessPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(worker_fn, tasks))
```

Fallback paths are intentional and preserved. They must NOT be removed.

---

## 6. Deprecated Modules

The following modules emit deprecation warnings and forward to the universal scheduler:

| Deprecated | Replacement | Removal Target |
|-----------|-------------|----------------|
| `scripts/intelligence/adaptive_scheduler.py` | `parallel.config`, `parallel.registry`, `parallel.planner` | v2.0 |
| `scripts/intelligence/batch_classify.py` | `scripts/intelligence/batch_classify_v2.py` | v2.0 |

All deprecated modules emit `DeprecationWarning` on import or first use.

---

## 7. Backward Compatibility Guarantees

| Aspect | Guarantee |
|--------|-----------|
| SHA256 outputs | Unchanged |
| Deterministic ordering | Results sorted by task_id |
| Retry behavior | Same max_retries, same terminal failure logic |
| Resume behavior | Same registry-based skip logic |
| Fallback execution | Same output as primary path |
| Config precedence | CLI > env > profile > YAML > safe default |
| Public API | Stable — no breaking changes in v1.x |

---

## 8. Architecture Consistency Checklist

Every scheduler pipeline must satisfy:

- [ ] Uses `resolve_worker_count()` for worker resolution
- [ ] Uses `load_parallelism_config()` for config loading
- [ ] Uses `Scheduler.run()` for execution (or fallback)
- [ ] Worker function is pure (no shared writes)
- [ ] Finalize is serialized (after scheduler completes)
- [ ] Results are deterministic (sorted by task_id)
- [ ] Fallback path exists and is tested
- [ ] No direct sub-module imports from pipelines

---

## 9. Internal Scheduler Modules

These are internal implementation details. Do not depend on their API stability:

```
parallel.config       — YAML loader, env overrides, hardware profiles
parallel.resource     — CPU/RAM/disk detection, safe worker limits
parallel.models       — Task, TaskResult, WorkerCapacity dataclasses
parallel.planner      — Task generation (file/shard/byte_range)
parallel.registry     — TaskRegistry (append-only JSONL checkpoint)
parallel.scheduler    — Scheduler (adaptive workers, backpressure, retry)
parallel.monitor      — Monitor (runtime metrics, reports)
parallel.runner       — ParallelRunner (test utility, ThreadPoolExecutor)
```

---

## 10. Version History

| Version | Date | Change |
|---------|------|--------|
| v1.0 | 2026-08-02 | Initial freeze — API stabilized |