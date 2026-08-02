"""Universal Scheduler v1 — Atlas parallel execution subsystem.

**Scheduler API Freeze v1** — These are the ONLY public interfaces.
Everything else is internal implementation. Pipelines MUST import from
this module, never from sub-modules directly.

## Worker Resolution Precedence

CLI override (explicit=)
  ↓
Environment: ATLAS_WORKERS_<STAGE>
  ↓
Hardware profile (ATLAS_PROFILE or hostname match)
  ↓
YAML config (config/parallelism.yaml)
  ↓
Safe default (resource detection)

## Public API

Task / TaskResult / WorkerCapacity — data models
Scheduler — adaptive worker pool with backpressure + retry
TaskRegistry — append-only JSONL checkpoint + resume
load_parallelism_config — single YAML loader
resolve_worker_count — unified worker resolution
plan_workload / file_tasks / shard_tasks — deterministic task generation
safe_worker_limit — resource-aware worker cap
"""

from .config import (
    get_global_config,
    get_hardware_profile,
    get_stage_config,
    load_parallelism_config,
    resolve_worker_count,
)
from .models import Task, TaskResult, WorkerCapacity
from .planner import (
    byte_range_tasks,
    file_tasks,
    plan_workload,
    read_jsonl_range,
    shard_tasks,
    task_line_range_reader,
)
from .registry import TaskRegistry
from .resource import (
    detect_cpu,
    detect_gpu,
    detect_ram,
    disk_free,
    has_ram_headroom,
    safe_worker_limit,
)
from .runner import JobResult, ParallelResult, ParallelRunner  # backward compat (v1.9)
from .scheduler import Scheduler


def get_scheduler(stage: str, **kwargs):
    """Convenience factory for a stage scheduler."""
    return Scheduler(stage, **kwargs)


__all__ = [
    "Scheduler",
    "Task",
    "TaskResult",
    "WorkerCapacity",
    "TaskRegistry",
    "ParallelRunner",
    "ParallelResult",
    "JobResult",
    "get_scheduler",
    "load_parallelism_config",
    "get_stage_config",
    "get_global_config",
    "resolve_worker_count",
    "get_hardware_profile",
    "safe_worker_limit",
    "detect_cpu",
    "detect_ram",
    "detect_gpu",
    "disk_free",
    "has_ram_headroom",
    "file_tasks",
    "shard_tasks",
    "byte_range_tasks",
    "plan_workload",
    "read_jsonl_range",
    "task_line_range_reader",
]
