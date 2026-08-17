#!/usr/bin/env python3
"""
loader.py — Load benchmark tasks from JSON files.

Tasks are organized by capability category under tasks/<category>/.
Each task is a JSON file (task.json) with the standard Task schema fields.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from ..core.schema import Task
from ..core.types import BenchmarkPartition, ExecutionMode, Capability, Difficulty


def load_task(path: Path | str) -> Task:
    """Load a single task from a JSON file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Task file not found: {p}")
    with p.open(encoding="utf-8") as f:
        data = json.load(f)
    return Task.model_validate(data)


def load_tasks_from_dir(dir_path: Path | str) -> list[Task]:
    """Load all tasks from a directory (recursively).

    Looks for task.json files in the directory and subdirectories.
    """
    d = Path(dir_path)
    tasks: list[Task] = []
    for task_file in sorted(d.rglob("task.json")):
        try:
            task = load_task(task_file)
            tasks.append(task)
        except Exception as e:
            # Log but don't fail on individual task load errors
            print(f"[eb] WARNING: failed to load {task_file}: {e}", flush=True)
    return tasks


def iter_task_dirs(dir_path: Path | str) -> Iterator[tuple[Path, str]]:
    """Iterate over capability subdirectories in a task directory.

    Yields (directory_path, category_name) for each subdirectory.
    """
    d = Path(dir_path)
    if not d.exists():
        return
    for subdir in sorted(d.iterdir()):
        if subdir.is_dir() and not subdir.name.startswith("_"):
            yield subdir, subdir.name
