#!/usr/bin/env python3
"""Universal Scheduler integration for the downloader (Phase 5B).

Execution orchestration ONLY — cache handling, HTTP Range resume, checksum
verification, and adapter logic stay in downloader/cache.py + adapters/.
This module adds:

- deterministic task identity: download:<source_id>:<url_hash>
- I/O-aware worker limits (bandwidth/disk/memory, not CPU cores)
- TaskRegistry checkpoint/resume/retry via the Universal Scheduler
- sequential fallback (identical behavior) on any scheduler error
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Callable

# Imported lazily inside functions to keep the downloader importable even
# when scripts/parallel is unavailable (fallback path).


def _url_hash(url: str) -> str:
    """Short deterministic hash of the source URL for task identity."""
    return hashlib.sha256((url or "").encode("utf-8")).hexdigest()[:12]


def download_task_id(source_id: str, url: str) -> str:
    """Deterministic task identity: download:<source_id>:<url_hash>."""
    return f"download:{source_id}:{_url_hash(url)}"


def plan_download_tasks(
    sources: list[dict[str, Any]],
    *,
    dry_run: bool = False,
) -> list:
    """Build one Task per source with deterministic identity.

    task_id = download:<source_id>:<url_hash> — the url_hash guards against
    a registry entry whose URL changes between runs (new task, not a
    duplicate of the old one), while the source_id prefix keeps per-source
    identity obvious.
    """
    from parallel.models import Task

    tasks: list = []
    for source in sorted(sources, key=lambda s: str(s.get("id") or s.get("source_id") or "")):
        sid = str(source.get("id") or source.get("source_id") or "")
        url = str(source.get("url") or "")
        tasks.append(Task(
            task_id=download_task_id(sid, url),
            source=sid,
            operation="download_source",
            input=sid,
            estimated_size_mb=0.0,  # unknown until adapter resolves URLs
            extra={
                "source": source,
                "dry_run": dry_run,
                "url_hash": _url_hash(url),
            },
        ))
    return tasks


def download_task(task) -> dict[str, Any]:
    """Universal Scheduler worker: download one source.

    Module-level (picklable for process pools; also safe in thread pools).
    Mirrors the per-source logic in DownloadAgent.execute exactly:
    select adapter -> adapter.download -> (optional) write download log.
    Raises on failure so the scheduler retries and marks the registry entry.

    NOTE: this function is called with a *pre-built adapters list* via
    functools.partial in run_download_scheduler — the adapters are not
    picklable (they hold CacheManager/SQLite state), so the scheduler uses
    a thread pool where the partial is shared in-process.
    """
    extra = getattr(task, "extra", {}) or {}
    source = extra.get("source", {})
    dry_run = bool(extra.get("dry_run", False))

    # These are injected by run_download_scheduler via partial.
    adapters = _WORKER_CTX.get("adapters")
    cache = _WORKER_CTX.get("cache")
    write_log = _WORKER_CTX.get("write_log")

    if adapters is None or cache is None or write_log is None:
        raise RuntimeError("download_task context not initialized (adapters/cache/write_log)")

    from .adapters import select_adapter

    sid = str(source.get("id") or source.get("source_id") or "")
    adapter = select_adapter(source, adapters)
    if adapter is None:
        raise RuntimeError(f"no adapter supports source '{sid}'")

    result = adapter.download(source, dry_run=dry_run)
    if result.status.value == "failed":
        raise RuntimeError(f"download failed for {sid}: {'; '.join(result.errors)}")

    payload = {
        "source_id": sid,
        "adapter": adapter.name,
        "status": result.status.value,
        "summary": result.summary,
        "url": result.url,
        "files": result.files,
        "errors": result.errors,
        "warnings": result.warnings,
        "entries": [e.to_dict() for e in result.entries],
    }

    if not dry_run and result.status.value != "failed":
        write_log(sid, result)
    return payload


# Worker-context: populated per-run (thread-pool shared state; NOT pickled).
_WORKER_CTX: dict[str, Any] = {}

# Operational kill-switch: set False to force the sequential fallback even
# when the scheduler imports cleanly (also used by tests).
_SCHEDULER_ENABLED = True


def run_download_scheduler(
    root: str | Path,
    sources: list[dict[str, Any]],
    adapters: list,
    cache,
    write_log: Callable[[str, Any], None],
    *,
    dry_run: bool = False,
    workers: int | None = None,
    registry_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Run downloads through the Universal Scheduler (I/O-aware).

    Returns per-source payload dicts (same shape as DownloadAgent.execute
    builds today), in deterministic task_id order. Falls back to the
    sequential loop on any scheduler error.

    Uses a THREAD pool (downloads are I/O-bound; also avoids the macOS
    SQLite fork segfault and serializes SQLite index writes via the GIL).
    Worker count comes from resource.safe_io_worker_limit (bandwidth/disk/
    memory aware), not CPU cores.
    """
    root_p = Path(root).resolve()
    tasks = plan_download_tasks(sources, dry_run=dry_run)
    if not tasks:
        return []

    # Populate worker context (threads share it in-process).
    _WORKER_CTX["adapters"] = adapters
    _WORKER_CTX["cache"] = cache
    _WORKER_CTX["write_log"] = write_log

    try:
        from functools import partial

        from parallel import resource
        from parallel.scheduler import Scheduler

        if not _SCHEDULER_ENABLED:
            raise RuntimeError("scheduler disabled (kill-switch)")

        reg_root = registry_root or (root_p / "metadata" / "pipeline_state")
        sched = Scheduler(
            "acquisition",
            registry_root=str(reg_root),
            workers=workers,
            pool="thread",               # I/O-bound
            max_retries=2,
            worker_limit_fn=resource.safe_io_worker_limit,
        )
        print(f"[downloader] scheduler: {len(tasks)} source tasks, {sched.workers} I/O-aware workers")
        results: list[dict[str, Any]] = []
        trs = sched.run(tasks, download_task)
        for tr in trs:
            if tr.status == "completed" and isinstance(tr.result, dict):
                results.append(tr.result)
            elif tr.status == "failed":
                sid = tr.task_id.split(":")[1]
                results.append({
                    "source_id": sid,
                    "adapter": "",
                    "status": "failed",
                    "summary": f"scheduler task failed: {tr.error}",
                    "url": "",
                    "files": [],
                    "errors": [tr.error],
                    "warnings": [],
                    "entries": [],
                })
            # skipped: completed in a prior run — reload download log if present
            elif tr.status == "skipped":
                sid = tr.task_id.split(":")[1]
                log_path = root_p / "metadata" / "download_logs" / f"{sid}.download.json"
                try:
                    log = json.loads(log_path.read_text(encoding="utf-8"))
                    results.append({
                        "source_id": sid,
                        "adapter": log.get("adapter", ""),
                        "status": log.get("status", "cached"),
                        "summary": log.get("summary", "completed in prior run"),
                        "url": log.get("url", ""),
                        "files": log.get("files", []),
                        "errors": log.get("errors", []),
                        "warnings": log.get("warnings", []),
                        "entries": log.get("entries", []),
                    })
                except (OSError, json.JSONDecodeError):
                    results.append({
                        "source_id": sid,
                        "adapter": "",
                        "status": "skipped",
                        "summary": "completed in prior run (download log missing)",
                        "url": "",
                        "files": [],
                        "errors": [],
                        "warnings": [],
                        "entries": [],
                    })
        return results
    except Exception as sched_exc:
        print(f"[downloader] scheduler unavailable ({sched_exc}); falling back to sequential", file=sys.stderr)
        results = []
        from .adapters import select_adapter

        for source in sorted(sources, key=lambda s: str(s.get("id") or s.get("source_id") or "")):
            sid = str(source.get("id") or source.get("source_id") or "")
            adapter = select_adapter(source, adapters)
            if adapter is None:
                results.append({
                    "source_id": sid, "adapter": "", "status": "skipped",
                    "summary": "no adapter supports this source", "url": source.get("url"),
                    "files": [], "errors": [], "warnings": [], "entries": [],
                })
                continue
            try:
                result = adapter.download(source, dry_run=dry_run)
                payload = {
                    "source_id": sid, "adapter": adapter.name,
                    "status": result.status.value, "summary": result.summary,
                    "url": result.url, "files": result.files,
                    "errors": result.errors, "warnings": result.warnings,
                    "entries": [e.to_dict() for e in result.entries],
                }
                if result.status.value == "failed":
                    payload["summary"] = f"download failed: {'; '.join(result.errors)}"
                elif not dry_run:
                    write_log(sid, result)
                results.append(payload)
            except Exception as exc:
                results.append({
                    "source_id": sid, "adapter": adapter.name, "status": "failed",
                    "summary": str(exc), "url": source.get("url"),
                    "files": [], "errors": [str(exc)], "warnings": [], "entries": [],
                })
        return results
