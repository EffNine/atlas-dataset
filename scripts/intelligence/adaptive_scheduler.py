#!/usr/bin/env python3
"""Adaptive workload scheduler for Atlas parallel processing.

Turns "one shard per worker" into "one balanced workload task per worker":

- Discovers shards and estimates byte sizes
- Splits large shards into virtual line-offset chunks (streaming, never
  modifies the original file)
- Produces a deterministic task queue
- Persists task state to metadata/pipeline_state/task_registry.jsonl for
  resume / crash safety
- Writes a scheduler performance report to reports/performance/

Usage (library):
    from adaptive_scheduler import (
        load_scheduler_config,
        plan_tasks,
        TaskRegistry,
        write_scheduler_report,
    )

This module is read-only with respect to dataset content: it only reads
shard files (stat + optional line counting) and writes pipeline_state /
report JSONL. It never writes to raw/ or curated/.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Task model
# ---------------------------------------------------------------------------


@dataclass
class Task:
    """One balanced workload unit (a whole shard or a line-range chunk)."""

    task_id: str
    source: str
    input_file: str
    offset_start: int
    offset_end: int          # -1 = to EOF
    estimated_bytes: int
    worker_group: str = "stage2"
    status: str = "pending"  # pending | running | completed | failed

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "source": self.source,
            "input_file": self.input_file,
            "offset_start": self.offset_start,
            "offset_end": self.offset_end,
            "estimated_bytes": self.estimated_bytes,
            "worker_group": self.worker_group,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Task":
        return cls(
            task_id=d["task_id"],
            source=d["source"],
            input_file=d["input_file"],
            offset_start=d.get("offset_start", 0),
            offset_end=d.get("offset_end", -1),
            estimated_bytes=d.get("estimated_bytes", 0),
            worker_group=d.get("worker_group", "stage2"),
            status=d.get("status", "pending"),
        )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def load_scheduler_config(config: dict | None = None) -> dict:
    """Load adaptive scheduler settings from config/parallelism.yaml.

    Falls back to sane defaults (which preserve one-task-per-small-shard
    behaviour) when the config is missing keys or the file is absent.
    """
    if config is None:
        config = _load_yaml()
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


def _load_yaml() -> dict:
    try:
        import yaml

        repo = Path(__file__).resolve().parents[2]
        cfg_path = repo / "config" / "parallelism.yaml"
        if cfg_path.exists():
            with open(cfg_path, "r") as f:
                return yaml.safe_load(f) or {}
    except Exception:
        pass
    return {}


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def count_lines(path: Path) -> int:
    """Count lines in a JSONL file (single streaming pass)."""
    n = 0
    with open(path, "r", encoding="utf-8") as f:
        for _ in f:
            n += 1
    return n


def plan_tasks(
    source: str,
    shards: list[Path],
    cfg: dict,
    worker_group: str = "stage2",
) -> list[Task]:
    """Build a deterministic balanced task queue for one source.

    Rules:
    - shards are sorted by name for determinism
    - a shard <= target_task_size_mb becomes one whole-file task
    - a shard >= min_split_size_mb (and split_large_shards) is split into
      line-offset chunks of ~target_task_size_mb
    - a large shard with split disabled becomes one task (allowed up to
      max_task_size_mb)
    - no task exceeds max_task_size_mb (split if needed)

    Args:
        source: Source label.
        shards: Input shard files.
        cfg: Scheduler config dict from load_scheduler_config().
        worker_group: stage1 | stage2.

    Returns:
        Deterministic task list (sorted by task_id).
    """
    target_bytes = cfg["target_task_size_mb"] * 1024 * 1024
    max_bytes = cfg["max_task_size_mb"] * 1024 * 1024
    min_split_bytes = cfg["min_split_size_mb"] * 1024 * 1024
    split_enabled = cfg["split_large_shards"]

    tasks: list[Task] = []

    for shard in sorted(shards, key=lambda p: p.name):
        size = shard.stat().st_size
        # Split large shards (>= min_split) when enabled; also split any
        # shard that would exceed max_task_size even if splitting is off.
        needs_split = (
            size >= min_split_bytes and split_enabled
        ) or size > max_bytes

        if not needs_split:
            tasks.append(
                Task(
                    task_id=f"{source}_{shard.stem}",
                    source=source,
                    input_file=str(shard),
                    offset_start=0,
                    offset_end=-1,
                    estimated_bytes=size,
                    worker_group=worker_group,
                )
            )
            continue

        # Split: count lines once, then emit chunk tasks of ~target_bytes.
        line_count = count_lines(shard)
        n_chunks = max(1, (size + target_bytes - 1) // target_bytes)
        # cap chunks by line count
        n_chunks = min(n_chunks, max(1, line_count))
        chunk_lines = max(1, (line_count + n_chunks - 1) // n_chunks)

        for i in range(n_chunks):
            start = i * chunk_lines
            end = start + chunk_lines if i < n_chunks - 1 else line_count
            frac = (end - start) / max(line_count, 1)
            tasks.append(
                Task(
                    task_id=f"{source}_chunk{i:04d}_{shard.stem}",
                    source=source,
                    input_file=str(shard),
                    offset_start=start,
                    offset_end=end,
                    estimated_bytes=int(size * frac),
                    worker_group=worker_group,
                )
            )

    tasks.sort(key=lambda t: t.task_id)
    return tasks


# ---------------------------------------------------------------------------
# Task registry (resume / crash safety)
# ---------------------------------------------------------------------------


class TaskRegistry:
    """Append-only JSONL registry of task state.

    Path: metadata/pipeline_state/task_registry.jsonl (per worker_group
    suffix to avoid cross-stage collisions).
    """

    def __init__(self, root: Path, worker_group: str = "stage2") -> None:
        self.root = Path(root)
        self.worker_group = worker_group
        self.path = (
            self.root
            / "metadata"
            / "pipeline_state"
            / f"task_registry_{worker_group}.jsonl"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    self._records[rec["task_id"]] = rec
                except (json.JSONDecodeError, KeyError):
                    continue

    def record(
        self,
        task: Task,
        status: str,
        worker_id: str = "",
        output_file: str = "",
        record_count: int = 0,
    ) -> None:
        rec = {
            "task_id": task.task_id,
            "status": status,
            "source": task.source,
            "input_file": task.input_file,
            "offset_start": task.offset_start,
            "offset_end": task.offset_end,
            "output_file": output_file,
            "record_count": record_count,
            "worker_id": worker_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._records[task.task_id] = rec
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def is_completed(self, task_id: str) -> bool:
        return self._records.get(task_id, {}).get("status") == "completed"

    def is_failed(self, task_id: str) -> bool:
        return self._records.get(task_id, {}).get("status") == "failed"

    def attempts(self, task_id: str) -> int:
        """Count failed attempts for a task by scanning the append-only file.

        The in-memory dict is keyed by task_id (last status wins), so
        retries must be counted from the file, not the dict.
        """
        if not self.path.exists():
            return 0
        n = 0
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("task_id") == task_id and rec.get("status") == "failed":
                    n += 1
        return n

    def completed_count(self) -> int:
        return sum(1 for r in self._records.values() if r["status"] == "completed")

    def status_counts(self) -> dict[str, int]:
        counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
        for r in self._records.values():
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        return counts


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def write_scheduler_report(
    root: Path,
    worker_group: str,
    shards: list[Path],
    tasks: list[Task],
    registry: TaskRegistry,
    split_operations: int,
    worker_utilization: float = 1.0,
    idle_time_seconds: float = 0.0,
) -> Path:
    """Write reports/performance/{worker_group}_scheduler_report.json."""
    total_bytes = sum(p.stat().st_size for p in shards)
    out_dir = Path(root) / "reports" / "performance"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{worker_group}_scheduler_report.json"

    largest = max((p.stat().st_size for p in shards), default=0)
    avg = int(total_bytes / len(tasks)) if tasks else 0

    report = {
        "schema_version": "1.0",
        "worker_group": worker_group,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_shards": len(shards),
        "total_bytes": total_bytes,
        "generated_tasks": len(tasks),
        "average_task_size_bytes": avg,
        "worker_utilization": round(worker_utilization, 4),
        "idle_time_estimate_seconds": round(idle_time_seconds, 1),
        "largest_shard_bytes": largest,
        "split_operations": split_operations,
        "task_status_counts": registry.status_counts(),
    }
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return out_path
