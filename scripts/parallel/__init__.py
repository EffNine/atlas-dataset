#!/usr/bin/env python3
"""Atlas v1.9 — Parallel worker pool for ETL and download stages.

Provides ``ParallelRunner``: a thin wrapper around ``concurrent.futures``
that executes per-source jobs concurrently while collecting results, errors,
and progress events.

Design constraints:
  - Stdlib-only (concurrent.futures, threading, queue)
  - Deterministic output order (sorted by source_id)
  - Streaming progress via optional callback
  - Safe defaults: max_workers=4, graceful degradation to serial on failure
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

T = TypeVar("T")

ProgressCallback = Callable[[str, str, Any], None]  # (source_id, event, payload)


@dataclass
class JobResult:
    source_id: str
    status: str        # passed | failed | skipped
    result: Any
    elapsed_s: float
    error: str = ""


@dataclass
class ParallelResult:
    results: list[JobResult] = field(default_factory=list)
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    total_elapsed_s: float = 0.0

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "total_elapsed_s": round(self.total_elapsed_s, 3),
            "results": [
                {
                    "source_id": r.source_id,
                    "status": r.status,
                    "elapsed_s": round(r.elapsed_s, 3),
                    "error": r.error,
                }
                for r in sorted(self.results, key=lambda x: x.source_id)
            ],
        }


class ParallelRunner:
    """Run per-source jobs in a thread pool.

    Args:
        max_workers: Thread pool size (default 4).
        timeout: Per-job timeout in seconds (None = unlimited).
        on_progress: Optional callback(source_id, event, payload).
    """

    def __init__(
        self,
        max_workers: int = 4,
        timeout: float | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self.max_workers = max(1, max_workers)
        self.timeout = timeout
        self.on_progress = on_progress

    def run(
        self,
        fn: Callable[[str], Any],
        source_ids: list[str],
    ) -> ParallelResult:
        """Run *fn(source_id)* for each id concurrently.

        Returns a ``ParallelResult`` with all job outcomes, sorted by
        source_id for deterministic output.
        """
        overall_start = time.monotonic()
        pr = ParallelResult()

        if not source_ids:
            return pr

        # Serial fallback for single item (no overhead)
        if len(source_ids) == 1 or self.max_workers == 1:
            for sid in source_ids:
                jr = self._run_one(fn, sid)
                pr.results.append(jr)
            self._tally(pr)
            pr.total_elapsed_s = time.monotonic() - overall_start
            return pr

        futures: dict[Any, str] = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            for sid in source_ids:
                self._emit(sid, "submitted", None)
                futures[pool.submit(self._run_one, fn, sid)] = sid

            for fut in as_completed(futures, timeout=self.timeout):
                sid = futures[fut]
                try:
                    jr: JobResult = fut.result()
                except Exception as exc:
                    jr = JobResult(
                        source_id=sid,
                        status="failed",
                        result=None,
                        elapsed_s=0.0,
                        error=str(exc),
                    )
                pr.results.append(jr)
                self._emit(sid, jr.status, jr)

        self._tally(pr)
        pr.total_elapsed_s = time.monotonic() - overall_start
        return pr

    def _run_one(self, fn: Callable[[str], Any], source_id: str) -> JobResult:
        self._emit(source_id, "started", None)
        start = time.monotonic()
        try:
            result = fn(source_id)
            elapsed = time.monotonic() - start
            # Infer status from result dict when possible
            if isinstance(result, dict):
                status = result.get("status") or "passed"
            elif hasattr(result, "status"):
                status = str(result.status)
            else:
                status = "passed"
            jr = JobResult(source_id=source_id, status=status, result=result, elapsed_s=elapsed)
        except Exception as exc:
            jr = JobResult(
                source_id=source_id,
                status="failed",
                result=None,
                elapsed_s=time.monotonic() - start,
                error=str(exc),
            )
        self._emit(source_id, jr.status, jr)
        return jr

    def _emit(self, source_id: str, event: str, payload: Any) -> None:
        if self.on_progress:
            try:
                self.on_progress(source_id, event, payload)
            except Exception:
                pass

    @staticmethod
    def _tally(pr: ParallelResult) -> None:
        for jr in pr.results:
            if jr.status in {"passed", "ok"}:
                pr.passed += 1
            elif jr.status == "skipped":
                pr.skipped += 1
            else:
                pr.failed += 1
