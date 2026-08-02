#!/usr/bin/env python3
"""
ADAPTIVE_SCHEDULER — DEPRECATED (v1.9)

This module is a backward-compatibility shim. It has been superseded by
the Universal Scheduler in ``scripts/parallel/``.

**Migration path:**

  Old:  from adaptive_scheduler import TaskRegistry, plan_tasks, load_scheduler_config
  New:  from parallel.registry import TaskRegistry
        from parallel.planner import plan_workload, byte_range_tasks
        from parallel.config import load_parallelism_config, resolve_worker_count

**Shim policy (Phase 5D):** this module contains NO business logic. All
implementations live in ``scripts/parallel/``; this file forwards to them so
existing import paths continue to work. It emits a ``DeprecationWarning`` on
use and will be removed in Atlas v2.0.

**Removal target:** Atlas v2.0
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

_DEPRECATION_MSG = (
    "adaptive_scheduler is deprecated and will be removed in Atlas v2.0. "
    "Use scripts/parallel/ instead:\n"
    "  load_scheduler_config  -> parallel.config.load_parallelism_config\n"
    "  TaskRegistry           -> parallel.registry.TaskRegistry\n"
    "  plan_tasks             -> parallel.planner.plan_workload\n"
    "  count_lines            -> parallel.planner.task_line_range_reader\n"
)


def _warn() -> None:
    warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)


# ---------------------------------------------------------------------------
# Config loader — forwards to parallel.config (honors an explicit config dict)
# ---------------------------------------------------------------------------


def load_scheduler_config(config: dict | None = None) -> dict:
    """DEPRECATED: Use parallel.config.load_parallelism_config() instead.

    Returns a legacy-format dict compatible with batch_classify_v2.
    If ``config`` is provided it is used directly (may contain a
    ``parallelism.classification`` section); otherwise the on-disk unified
    config is loaded.
    """
    _warn()
    if config is None:
        from parallel.config import load_parallelism_config as _load
        config = _load()
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
# TaskRegistry — forwards to parallel.registry (legacy method surface)
# ---------------------------------------------------------------------------


class TaskRegistry:
    """DEPRECATED: Use parallel.registry.TaskRegistry instead.

    Wraps the canonical registry, preserving the legacy on-disk location
    (``root/metadata/pipeline_state/task_registry_{stage}.jsonl``) and the
    legacy ``record(task, status, ...)`` call shape (accepts a Task object
    or a task_id string). No state machine logic lives here.
    """

    def __init__(self, root: str | Path, worker_group: str = "stage2",
                 max_retries: int = 2) -> None:
        _warn()
        from parallel.registry import TaskRegistry as _RealRegistry
        self._impl = _RealRegistry(
            Path(root) / "metadata" / "pipeline_state",
            worker_group,
            max_retries=max_retries,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._impl, name)

    @staticmethod
    def _tid(task: Any) -> str:
        return getattr(task, "task_id", task)

    def record(self, task: Any, status: str, worker_id: str = "",
               output_file: str = "", record_count: int = 0) -> None:
        """Record a transition. Legacy tolerated duplicate terminal records."""
        _warn()
        tid = self._tid(task)
        try:
            self._impl.record(tid, status, worker_id=worker_id,
                              output_file=output_file, record_count=record_count)
        except Exception:
            # Legacy semantics: dict keyed by task_id, last-wins, count stays 1.
            pass

    def is_completed(self, task_id: str) -> bool:
        _warn()
        return self._impl.is_completed(task_id)

    def is_failed(self, task_id: str) -> bool:
        _warn()
        return self._impl.status(task_id) == "failed"

    def attempts(self, task_id: str) -> int:
        _warn()
        return self._impl.attempts(task_id)

    def completed_count(self) -> int:
        _warn()
        return len(self._impl.completed_ids())

    def status_counts(self) -> dict[str, int]:
        _warn()
        return self._impl.summary()

    def reclaim_stale_running(self, lease_seconds: int = 900) -> list[str]:
        _warn()
        return self._impl.reclaim_stale_running(lease_seconds=lease_seconds)


# ---------------------------------------------------------------------------
# Task dataclass — forwards to parallel.models (legacy field names)
# ---------------------------------------------------------------------------


class Task:
    """DEPRECATED: Use parallel.models.Task instead.

    Wraps the canonical Task model, exposing the legacy field surface:
    ``task_id``, ``source``, ``input_file`` (canonical ``input``),
    ``offset_start``, ``offset_end``, ``estimated_bytes`` (canonical
    ``estimated_size_mb``), ``worker_group`` (canonical ``operation``) and
    ``status``. ``to_dict`` returns the legacy dict shape so downstream
    workers that read ``task["input_file"]`` keep working.
    """

    def __init__(self, task_id: str, source: str, input_file: str,
                 offset_start: int, offset_end: int, estimated_bytes: int,
                 worker_group: str = "stage2", status: str = "pending"):
        _warn()
        from parallel.models import Task as _RealTask
        self._impl = _RealTask(
            task_id=task_id,
            source=source,
            operation=worker_group,
            input=input_file,
            estimated_size_mb=(estimated_bytes or 0) / (1024 * 1024),
            offset_start=offset_start,
            offset_end=offset_end,
            status=status,
        )

    @property
    def task_id(self) -> str:
        return self._impl.task_id

    @property
    def source(self) -> str:
        return self._impl.source

    @property
    def input_file(self) -> str:
        return self._impl.input

    @property
    def input(self) -> str:
        return self._impl.input

    @property
    def offset_start(self) -> int | None:
        return self._impl.offset_start

    @property
    def offset_end(self) -> int | None:
        return self._impl.offset_end

    @property
    def estimated_bytes(self) -> float:
        return self._impl.estimated_size_mb * 1024 * 1024

    @property
    def worker_group(self) -> str:
        return self._impl.operation

    @worker_group.setter
    def worker_group(self, value: str) -> None:
        self._impl.operation = value

    @property
    def status(self) -> str:
        return self._impl.status

    @status.setter
    def status(self, value: str) -> None:
        self._impl.status = value

    def to_dict(self) -> dict[str, Any]:
        """Legacy dict shape (input_file key, bytes) for downstream workers."""
        _warn()
        return {
            "task_id": self._impl.task_id,
            "source": self._impl.source,
            "input_file": self._impl.input,
            "offset_start": self._impl.offset_start,
            "offset_end": self._impl.offset_end,
            "estimated_bytes": int(self._impl.estimated_size_mb * 1024 * 1024),
            "worker_group": self._impl.operation,
            "status": self._impl.status,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Task":
        """Build from a legacy task dict (accepts input_file or input)."""
        _warn()
        return cls(
            task_id=d["task_id"],
            source=d["source"],
            input_file=d.get("input_file", d.get("input", "")),
            offset_start=d.get("offset_start", 0),
            offset_end=d.get("offset_end", -1),
            estimated_bytes=d.get("estimated_bytes", 0) or int(d.get("estimated_size_mb", 0) * 1024 * 1024),
            worker_group=d.get("worker_group", d.get("operation", "stage2")),
            status=d.get("status", "pending"),
        )


# ---------------------------------------------------------------------------
# Planning — forwards to parallel.planner (legacy task_id/field naming)
# ---------------------------------------------------------------------------


def plan_tasks(
    source: str,
    shards: list[Path],
    cfg: dict,
    worker_group: str = "stage2",
) -> list[Task]:
    """DEPRECATED: Use parallel.planner.plan_workload() instead.

    Plans one legacy Task per whole file (``{source}_{stem}``) or chunk
    tasks (``{source}_chunk{i:04d}_{stem}``) using the canonical planner for
    the split math (line counting, offsets). The legacy ``split_large_shards``
    flag is honored as the whole-vs-split gate; chunking itself is delegated
    to ``parallel.planner.byte_range_tasks``.
    """
    _warn()
    from parallel.planner import byte_range_tasks as _canonical_split
    from parallel.planner import file_tasks as _canonical_whole

    clf = (cfg or {}).get("parallelism", {}).get("classification", {}) if cfg and "parallelism" in cfg else (cfg or {})
    target_mb = int(clf.get("target_task_size_mb", 512))
    max_mb = int(clf.get("max_task_size_mb", 1024))
    min_split_mb = int(clf.get("min_split_size_mb", 2048))
    split_enabled = bool(clf.get("split_large_shards", True))
    min_split_bytes = min_split_mb * 1024 * 1024
    max_bytes = max_mb * 1024 * 1024

    tasks: list[Task] = []
    for shard in sorted(shards, key=lambda p: p.name):
        size = shard.stat().st_size
        needs_split = (size >= min_split_bytes and split_enabled) or size > max_bytes
        if needs_split:
            planned = _canonical_split(
                shard, source=source, operation=worker_group,
                target_size_mb=target_mb, max_size_mb=max_mb, min_split_mb=min_split_mb,
            )
        else:
            planned = _canonical_whole([shard], source=source, operation=worker_group)

        stem = Path(shard).stem
        if len(planned) == 1 and planned[0].offset_start is None:
            # Whole-file task (canonical file_tasks has no offsets)
            t = planned[0]
            tasks.append(Task(
                task_id=f"{source}_{stem}",
                source=source,
                input_file=t.input,
                offset_start=0,
                offset_end=-1,
                estimated_bytes=int(t.estimated_size_mb * 1024 * 1024),
                worker_group=worker_group,
            ))
        else:
            for i, t in enumerate(planned):
                tasks.append(Task(
                    task_id=f"{source}_chunk{i:04d}_{stem}",
                    source=source,
                    input_file=t.input,
                    offset_start=t.offset_start or 0,
                    offset_end=t.offset_end or -1,
                    estimated_bytes=int(t.estimated_size_mb * 1024 * 1024),
                    worker_group=worker_group,
                ))

    tasks.sort(key=lambda t: t.task_id)
    return tasks


def count_lines(path: str | Path) -> int:
    """DEPRECATED: Use parallel.planner.task_line_range_reader() instead."""
    _warn()
    n = 0
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for _ in f:
            n += 1
    return n


def write_scheduler_report(
    root: str | Path,
    worker_group: str,
    shards: list[Path],
    tasks: list[Task],
    registry: TaskRegistry,
    split_operations: int = 0,
    worker_utilization: float = 1.0,
    idle_time_seconds: float = 0.0,
) -> Path:
    """DEPRECATED: Reports are now written by parallel.monitor.Monitor.

    Forwards to the canonical legacy-format report writer so the old
    ``reports/performance/{worker_group}_scheduler_report.json`` shape is
    preserved for existing consumers.
    """
    _warn()
    from parallel.monitor import write_legacy_scheduler_report as _write
    return _write(
        root, worker_group, shards, tasks, registry,
        split_operations=split_operations,
        worker_utilization=worker_utilization,
        idle_time_seconds=idle_time_seconds,
    )
