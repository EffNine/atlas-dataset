#!/usr/bin/env python3
"""Universal scheduler — runtime metrics.

Collects per-run metrics: CPU%, RAM usage, disk free, throughput (tasks/s,
records/s). Writes reports/performance/{stage}_scheduler_report.json and an
optional metrics.csv for plotting.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import resource


class Monitor:
    """Lightweight runtime metric collector."""

    def __init__(self, stage: str, report_dir: str | Path = "reports/performance"):
        self.stage = stage
        self.report_dir = Path(report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.start = time.monotonic()
        self.samples: list[dict[str, Any]] = []
        self.total_tasks = 0
        self.completed_tasks = 0
        self.failed_tasks = 0
        self.total_records = 0

    def start_run(self, total_tasks: int) -> None:
        self.start = time.monotonic()
        self.total_tasks = total_tasks

    def sample(self) -> dict[str, Any]:
        ram = resource.detect_ram()
        cpu = resource.detect_cpu()
        disk = resource.disk_free(self.report_dir)
        s: dict[str, Any] = {
            "t": round(time.monotonic() - self.start, 3),
            "cpu_cores": cpu,
            "ram_used_mb": ram["used_mb"],
            "ram_avail_mb": ram["available_mb"],
            "disk_free_gb": round(disk / (1024 ** 3), 2),
            "active_tasks": self.completed_tasks + self.failed_tasks,
        }
        self.samples.append(s)
        return s

    def record_completed(self, records: int = 0) -> None:
        self.completed_tasks += 1
        self.total_records += records

    def record_failed(self) -> None:
        self.failed_tasks += 1

    def finish(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        elapsed = time.monotonic() - self.start
        throughput_tasks = self.completed_tasks / elapsed if elapsed > 0 else 0
        report: dict[str, Any] = {
            "report_metadata": {
                "report_type": f"{self.stage}_scheduler_report",
                "stage": self.stage,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "scheduler": "universal_v1",
            },
            "summary": {
                "total_tasks": self.total_tasks,
                "completed": self.completed_tasks,
                "failed": self.failed_tasks,
                "total_records": self.total_records,
                "elapsed_s": round(elapsed, 3),
                "throughput_tasks_per_s": round(throughput_tasks, 4),
                "throughput_records_per_s": round(self.total_records / elapsed, 2) if elapsed > 0 else 0.0,
            },
            "samples_count": len(self.samples),
            "samples": self.samples[-100:],  # cap samples in report
        }
        if extra:
            report["extra"] = extra
        path = self.report_dir / f"{self.stage}_scheduler_report.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        return report


# ---------------------------------------------------------------------------
# Legacy scheduler report writer (v1.x format, kept for backward compatibility)
# ---------------------------------------------------------------------------


def write_legacy_scheduler_report(
    root: str | Path,
    worker_group: str,
    shards: list[Path],
    tasks: list[Any],
    registry: Any,
    split_operations: int = 0,
    worker_utilization: float = 1.0,
    idle_time_seconds: float = 0.0,
) -> Path:
    """Write a v1.x-format scheduler performance report.

    The legacy `adaptive_scheduler.write_scheduler_report` contract is
    preserved here so the compatibility shim can forward without owning
    report business logic. `registry` must expose `summary()` (parallel
    TaskRegistry) — a shim wrapper with ``__getattr__`` forwarding also
    works.

    Returns the written report path.
    """
    total_bytes = sum(p.stat().st_size for p in shards)
    out_dir = Path(root) / "reports" / "performance"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{worker_group}_scheduler_report.json"

    largest = max((p.stat().st_size for p in shards), default=0)
    avg = int(total_bytes / len(tasks)) if tasks else 0

    # Task sizes: parallel Task exposes estimated_size_mb; legacy Task
    # exposes estimated_bytes. Accept either.
    def _task_bytes(t: Any) -> int:
        eb = getattr(t, "estimated_bytes", None)
        if eb is not None:
            return int(eb)
        emb = getattr(t, "estimated_size_mb", None)
        return int(emb * 1024 * 1024) if emb is not None else 0

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
        "task_status_counts": dict(registry.summary()),
    }
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return out_path
