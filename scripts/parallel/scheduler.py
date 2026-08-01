#!/usr/bin/env python3
"""Universal scheduler — adaptive worker pool with backpressure + retry.

Responsibilities:
- bounded submission (never more than N tasks in flight)
- adaptive worker count from resource.safe_worker_limit()
- backpressure when RAM headroom is low
- failure retry up to max_retries (via TaskRegistry)
- deterministic result ordering by task_id
- resume: completed tasks are skipped via the registry

worker_fn contract: ``worker_fn(task) -> result``. For process pools the
function MUST be module-level and picklable (lambdas only work with
thread pools).
"""

from __future__ import annotations

import time
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Sequence

from . import resource
from .config import resolve_worker_count
from .models import Task, TaskResult
from .registry import TaskRegistry

# Backpressure: pause submission while available RAM is below this margin
# (measured in multiples of per-task RAM).
BACKPRESSURE_RAM_MULTIPLE = 2
BACKPRESSURE_POLL_S = 2.0


class SchedulerError(RuntimeError):
    pass


class Scheduler:
    """Run a batch of Tasks through an adaptive worker pool."""

    def __init__(
        self,
        stage: str,
        registry_root: str | Path = "metadata/pipeline_state",
        *,
        workers: int | None = None,
        pool: str = "process",
        max_retries: int = 2,
        per_task_ram_mb: int | None = None,
        safety_margin: float | None = None,
        worker_id: str = "",
        cfg: dict | None = None,
    ):
        self.stage = stage
        self.pool_kind = pool
        self.max_retries = max(0, int(max_retries))
        self.per_task_ram_mb = per_task_ram_mb
        self.safety_margin = safety_margin
        self.cfg = cfg
        self.worker_id = worker_id or f"{stage}-{time.strftime('%H%M%S')}"
        self.registry = TaskRegistry(registry_root, stage, max_retries=max_retries)

        # Adaptive worker count: explicit > config/env > safe limit.
        resolved = resolve_worker_count(stage, cfg, explicit=workers)
        if resolved == "auto":
            self.workers = resource.safe_worker_limit(
                per_task_ram_mb=per_task_ram_mb,
                safety_margin=safety_margin,
                cfg=cfg,
            )
        else:
            self.workers = max(1, int(resolved))
            # Still never exceed the safety margin.
            safe = resource.safe_worker_limit(
                per_task_ram_mb=per_task_ram_mb,
                safety_margin=safety_margin,
                max_workers=self.workers,
                cfg=cfg,
            )
            self.workers = safe

    # ------------------------------------------------------------------
    # main entry
    # ------------------------------------------------------------------

    def run(
        self,
        tasks: Sequence[Task],
        worker_fn: Callable[[Task], Any],
    ) -> list[TaskResult]:
        """Execute tasks, returning results sorted by task_id (deterministic).

        Completed tasks (from a prior run) are skipped. Failed tasks are
        retried up to max_retries. Results always include every task exactly
        once (skipped tasks return status='skipped').
        """
        # Resume: drop tasks already completed in a previous run.
        pending = [t for t in tasks if not self.registry.is_completed(t.task_id)]
        results: dict[str, TaskResult] = {}
        for t in tasks:
            if self.registry.is_completed(t.task_id):
                results[t.task_id] = TaskResult(
                    task_id=t.task_id, status="skipped", result=t.extra.get("_prior_result"),
                )

        # Crash recovery: re-claim stale 'running' tasks from a dead worker.
        stale = self.registry.reclaim_stale_running()
        if stale:
            print(f"[scheduler:{self.stage}] reclaimed {len(stale)} stale running task(s)")

        if not pending:
            return sorted(results.values(), key=lambda r: r.task_id)

        executor_cls = ProcessPoolExecutor if self.pool_kind == "process" else ThreadPoolExecutor
        with executor_cls(max_workers=self.workers) as ex:
            inflight: dict[Future, Task] = {}
            idx = 0

            # Bounded first batch
            for task in pending[: self.workers]:
                fut = ex.submit(self._run_attempt, task, worker_fn)
                inflight[fut] = task
                idx += 1

            while inflight:
                done = next(as_completed(inflight))
                task = inflight.pop(done)
                try:
                    tr: TaskResult = done.result()
                except Exception as exc:  # worker raised before returning
                    tr = TaskResult(task_id=task.task_id, status="failed", error=str(exc))
                self._settle(task, tr, worker_fn, ex, inflight, results)

                # Submit next if more pending (bounded)
                if idx < len(pending):
                    task = pending[idx]
                    idx += 1
                    fut = ex.submit(self._run_attempt, task, worker_fn)
                    inflight[fut] = task

        return sorted(results.values(), key=lambda r: r.task_id)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    @staticmethod
    def _run_attempt(task: Task, worker_fn: Callable[[Task], Any]) -> TaskResult:
        """Execute one attempt of a task (runs in the worker process/thread)."""
        start = time.monotonic()
        try:
            result = worker_fn(task)
            return TaskResult(
                task_id=task.task_id,
                status="completed",
                result=result,
                elapsed_s=time.monotonic() - start,
            )
        except Exception as exc:
            return TaskResult(
                task_id=task.task_id,
                status="failed",
                error=str(exc),
                elapsed_s=time.monotonic() - start,
            )

    def _settle(self, task, tr, worker_fn, ex, inflight, results) -> None:
        """Persist outcome; retry failed tasks while attempts remain."""
        if tr.status == "completed":
            self.registry.complete(task.task_id, record_count=_record_count(tr.result))
            results[task.task_id] = tr
            return

        attempts = self.registry.attempts(task.task_id)
        if attempts < self.max_retries:
            # Retry: record explicit transition, resubmit with backoff.
            self.registry.record(task.task_id, "retry", error=tr.error)
            time.sleep(min(BACKPRESSURE_POLL_S, attempts + 1))
            fut = ex.submit(self._run_attempt, task, worker_fn)
            inflight[fut] = task
        else:
            # Terminal failure.
            self.registry.fail(task.task_id, error=tr.error)
            tr.status = "failed"
            tr.attempts = attempts + 1
            results[task.task_id] = tr

    def _backpressure(self) -> None:
        """Pause submission until RAM headroom returns (bounded wait)."""
        while not resource.has_ram_headroom(cfg=self.cfg):
            time.sleep(BACKPRESSURE_POLL_S)


def _record_count(result: Any) -> int:
    """Best-effort record count from a worker result dict."""
    if isinstance(result, dict):
        for key in ("record_count", "total", "classified", "processed"):
            if key in result:
                try:
                    return int(result[key])
                except (TypeError, ValueError):
                    return 0
    return 0
