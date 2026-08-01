"""Universal Adaptive Scheduler — shared parallel subsystem.

Public API:
    get_scheduler(stage, ...) -> Scheduler
    plan(...) -> list[Task]
    Task / TaskResult / WorkerCapacity
    TaskRegistry
    load_parallelism_config / get_stage_config
    safe_worker_limit
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
