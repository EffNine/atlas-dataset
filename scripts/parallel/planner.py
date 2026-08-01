#!/usr/bin/env python3
"""Universal scheduler — workload planner.

Converts a pipeline workload into deterministic Task objects.

Supported task kinds:
- file: one task per file
- shard: one task per shard file
- byte_range: split a single large file into byte/line-range chunks
  (adaptive splitting for large shards)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .models import Task

# Config keys per stage for splitting thresholds.
DEFAULT_TARGET_TASK_MB = 64
DEFAULT_MAX_TASK_MB = 128
DEFAULT_MIN_SPLIT_MB = 128


def _stable_key(*parts: str) -> str:
    """Deterministic task key from parts (no hashing — readable ids)."""
    return ":".join(str(p) for p in parts)


def file_tasks(
    files: Iterable[str | Path],
    source: str,
    operation: str,
    priority: int = 1,
    extra: dict[str, Any] | None = None,
) -> list[Task]:
    """One Task per file."""
    tasks: list[Task] = []
    for f in sorted(Path(p) for p in files):
        size_mb = f.stat().st_size / (1024 * 1024) if f.exists() else 0.0
        tasks.append(
            Task(
                task_id=_stable_key(source, operation, f.name),
                source=source,
                operation=operation,
                input=str(f),
                estimated_size_mb=size_mb,
                priority=priority,
                extra=dict(extra or {}),
            )
        )
    return tasks


def shard_tasks(
    shards: Iterable[str | Path],
    source: str,
    operation: str,
    priority: int = 1,
) -> list[Task]:
    """One Task per shard (same shape as file_tasks but named for shards)."""
    return file_tasks(shards, source, operation, priority=priority)


def byte_range_tasks(
    path: str | Path,
    source: str,
    operation: str,
    *,
    target_size_mb: int = DEFAULT_TARGET_TASK_MB,
    max_size_mb: int = DEFAULT_MAX_TASK_MB,
    min_split_mb: int = DEFAULT_MIN_SPLIT_MB,
    priority: int = 1,
) -> list[Task]:
    """Split one file into line-range chunk tasks.

    The file is split by *line count* (streamed, no full-file load): we first
    count lines cheaply, then emit contiguous ranges of ~target_size_mb each.
    The original file is never modified; each task carries
    offset_start/offset_end (0-indexed line boundaries).

    If the file is smaller than ``min_split_mb``, a single whole-file task is
    returned (no split).
    """
    p = Path(path)
    size_mb = p.stat().st_size / (1024 * 1024) if p.exists() else 0.0
    if size_mb < min_split_mb or size_mb <= target_size_mb:
        return file_tasks([p], source, operation, priority=priority)

    # Cheap line count (streaming, buffered).
    line_count = 0
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        for _ in f:
            line_count += 1

    n_chunks = max(1, int((size_mb + target_size_mb - 1e-9) // max(1e-9, target_size_mb)))
    chunk_size = max(1, (line_count + n_chunks - 1) // n_chunks)  # ceil -> exact count

    tasks: list[Task] = []
    start = 0
    idx = 0
    while start < line_count:
        end = min(line_count, start + chunk_size)
        tasks.append(
            Task(
                task_id=_stable_key(source, operation, f"{p.name}~{idx:04d}"),
                source=source,
                operation=operation,
                input=str(p),
                estimated_size_mb=round(size_mb / n_chunks, 2),
                priority=priority,
                offset_start=start,
                offset_end=end,
            )
        )
        start = end
        idx += 1
    return tasks


def plan_workload(
    kind: str,
    items: Iterable[str | Path] | str | Path,
    source: str,
    operation: str,
    **kwargs: Any,
) -> list[Task]:
    """Dispatch to the right planner by kind: 'file' | 'shard' | 'byte_range'."""
    if kind == "byte_range":
        return byte_range_tasks(items, source, operation, **kwargs)  # type: ignore[arg-type]
    if kind == "shard":
        return shard_tasks(items, source, operation, **kwargs)  # type: ignore[arg-type]
    return file_tasks(items, source, operation, **kwargs)  # type: ignore[arg-type]


def task_line_range_reader(task: Task):
    """Stream the line range of a byte_range task.

    Yields (index, line) for lines [offset_start, offset_end). Reads only the
    required slice — the underlying file is not modified.
    """
    start = task.offset_start or 0
    end = task.offset_end
    with open(task.input, "r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            if i < start:
                continue
            if end is not None and i >= end:
                break
            yield i, line


def read_jsonl_range(task: Task) -> list[dict]:
    """Load JSONL records for a byte_range task (for record-level workers)."""
    records: list[dict] = []
    for _i, line in task_line_range_reader(task):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records
