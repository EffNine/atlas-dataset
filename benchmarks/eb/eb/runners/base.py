#!/usr/bin/env python3
"""
base.py — Abstract runner interface for the EffNine Benchmark (EB).

Defines the contract that all execution-mode runners must implement.
The runner orchestrates task execution but does not compute final scores.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from ..core.schema import Task, TaskResult
from ..core.types import ExecutionMode


class TaskStatus(str, Enum):
    """Outcome status of a single task execution."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


@dataclass
class RunContext:
    """Mutable context passed through the run pipeline."""

    run_id: str
    model_name: str
    suite: str
    inference_settings: dict[str, Any] = field(default_factory=dict)
    repeat_index: int = 0
    start_time: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    extra: dict[str, Any] = field(default_factory=dict)


class Runner(ABC):
    """Abstract base for all execution-mode runners."""

    @property
    @abstractmethod
    def mode(self) -> ExecutionMode:
        """The ExecutionMode this runner handles."""
        ...

    @abstractmethod
    def run(self, task: Task, ctx: RunContext) -> TaskResult:
        """
        Execute a single task and return its result.

        The runner must:
          1. Build the model request from the task
          2. Invoke the model adapter
          3. Normalize the response
          4. Create a TaskResult with execution metadata
          5. Preserve evidence (raw response, latency, settings)

        The runner must NOT compute EB Score.
        """
        ...

    def run_batch(self, tasks: list[Task], ctx: RunContext) -> list[TaskResult]:
        """
        Execute multiple tasks sequentially. Override for parallel execution.

        A single task failure must not abort the entire batch.
        """
        results = []
        for task in tasks:
            try:
                result = self.run(task, ctx)
            except Exception as e:
                result = TaskResult(
                    task_id=task.id,
                    run_id=ctx.run_id,
                    raw_response=None,
                    flags=[f"runner_error: {type(e).__name__}: {e}"],
                    execution_metadata={"status": TaskStatus.ERROR.value},
                )
            results.append(result)
        return results
