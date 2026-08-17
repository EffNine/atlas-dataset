#!/usr/bin/env python3
"""
registry.py — Task registry for the EffNine Benchmark (EB).

Provides filtered access to tasks by mode, capability, difficulty, and partition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from ..core.schema import Task
from ..core.types import BenchmarkPartition, Capability, Difficulty, ExecutionMode
from .loader import load_task, load_tasks_from_dir


@dataclass
class TaskRegistry:
    """In-memory registry of benchmark tasks with filtered access."""

    _tasks: dict[str, Task] = field(default_factory=dict)
    _loaded: bool = False

    def load_from_dir(self, dir_path: Path | str) -> int:
        """Load all tasks from a directory. Returns count loaded."""
        tasks = load_tasks_from_dir(dir_path)
        for t in tasks:
            self._tasks[t.id] = t
        self._loaded = True
        return len(tasks)

    def get(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    def iter_by_mode(self, mode: ExecutionMode) -> Iterator[Task]:
        """Iterate tasks matching an execution mode."""
        for t in self._tasks.values():
            if t.mode == mode:
                yield t

    def iter_by_capability(self, capability: Capability) -> Iterator[Task]:
        """Iterate tasks that include a given capability."""
        for t in self._tasks.values():
            if capability in t.capabilities:
                yield t

    def iter_by_difficulty(self, difficulty: Difficulty) -> Iterator[Task]:
        """Iterate tasks matching a difficulty level."""
        for t in self._tasks.values():
            if t.difficulty == difficulty:
                yield t

    def iter_by_partition(self, partition: BenchmarkPartition) -> Iterator[Task]:
        """Iterate tasks in a given partition."""
        for t in self._tasks.values():
            if t.partition == partition:
                yield t

    def iter_filtered(
        self,
        *,
        mode: ExecutionMode | None = None,
        capabilities: list[Capability] | None = None,
        difficulty: Difficulty | None = None,
        partitions: list[BenchmarkPartition] | None = None,
    ) -> list[Task]:
        """Filter tasks by multiple criteria."""
        results = []
        for t in self._tasks.values():
            if mode is not None and t.mode != mode:
                continue
            if capabilities is not None and not any(c in t.capabilities for c in capabilities):
                continue
            if difficulty is not None and t.difficulty != difficulty:
                continue
            if partitions is not None and t.partition not in partitions:
                continue
            results.append(t)
        return results

    def __len__(self) -> int:
        return len(self._tasks)

    def __iter__(self) -> Iterator[Task]:
        return iter(self._tasks.values())
