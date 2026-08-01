#!/usr/bin/env python3
"""Universal scheduler — data models.

Task / TaskResult / WorkerCapacity dataclasses shared by all pipelines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Task:
    """A unit of work produced by the planner and executed by the scheduler.

    ``task_id`` is deterministic (source:operation:key) so resume is
    idempotent and duplicate execution is prevented.
    """

    task_id: str
    source: str
    operation: str
    input: str
    estimated_size_mb: float = 0.0
    priority: int = 1
    status: str = "pending"
    offset_start: int | None = None
    offset_end: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "source": self.source,
            "operation": self.operation,
            "input": self.input,
            "estimated_size_mb": round(self.estimated_size_mb, 2),
            "priority": self.priority,
            "status": self.status,
            "offset_start": self.offset_start,
            "offset_end": self.offset_end,
            "extra": self.extra,
        }


@dataclass
class TaskResult:
    """Outcome of executing one task."""

    task_id: str
    status: str  # completed | failed | skipped
    result: Any = None
    error: str = ""
    elapsed_s: float = 0.0
    attempts: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "elapsed_s": round(self.elapsed_s, 3),
            "attempts": self.attempts,
        }


@dataclass
class WorkerCapacity:
    """Advertised capacity of a worker (used for multi-machine readiness)."""

    worker_id: str
    host: str
    capacity: int = 1
    memory_limit_mb: int = 8192
    cpu_limit: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "host": self.host,
            "capacity": self.capacity,
            "memory_limit_mb": self.memory_limit_mb,
            "cpu_limit": self.cpu_limit,
        }
