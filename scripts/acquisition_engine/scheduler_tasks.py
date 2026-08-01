#!/usr/bin/env python3
"""Universal Scheduler integration for AcquisitionEngine (Phase 5C).

Design: PURE WORKERS + SERIALIZED FINALIZE.

Workers are pure functions: resolve source -> license gate -> generate
records -> return data only. They NEVER write checkpoints, lifecycle,
verification logs, curated output, or mutate global state. All shared-state
writes happen in a serialized finalize stage (in engine.py execute()) that
consumes worker results in deterministic manifest order, so output is
byte-identical to the original sequential loop.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Imported lazily inside functions so this module stays importable even when
# scripts/parallel is unavailable (sequential fallback path).


def engine_task_id(batch_id: str, source_id: str) -> str:
    """Deterministic task identity: acq:engine:<batch_id>:<source_id>."""
    return f"acq:engine:{batch_id}:{source_id}"


def plan_engine_tasks(
    manifest: dict[str, Any],
    reg_by_id: dict[str, dict],
    max_records: int,
    root: str | Path,
) -> list:
    """Build one Task per (batch, source) in manifest order.

    Every manifest dataset becomes a task; the pure worker performs resolve +
    license gate internally and reports failed/skipped outcomes in its
    payload (no exceptions for expected gates). Sources whose task is already
    completed in the registry are planned anyway; the scheduler marks them
    skipped and run_engine_scheduler reports a skipped payload.
    """
    from parallel.models import Task

    tasks: list = []
    for b in manifest.get("batches", []):
        bid = b["batch_id"]
        for d in b.get("datasets", []):
            sid = d["source_id"]
            tasks.append(Task(
                task_id=engine_task_id(bid, sid),
                source=sid,
                operation="engine_source_pipeline",
                input=sid,
                estimated_size_mb=0.0,
                extra={
                    "root": str(root),
                    "batch_id": bid,
                    "dataset": d,
                    "registry_entry": reg_by_id.get(sid),
                    "max_records": max_records,
                },
            ))
    return tasks


def engine_source_task(task) -> dict[str, Any]:
    """PURE worker: resolve + license gate + generate records.

    Returns a payload dict; never writes shared state. Expected outcomes
    (not-in-registry, registry status not accepted/review, denied license)
    are returned as failed/skipped payloads — the scheduler records the task
    as completed (the work of determining the outcome succeeded). Only
    unexpected exceptions raise, triggering scheduler retry.
    """
    from .engine import generate_source_records, is_denied_license

    extra = getattr(task, "extra", {}) or {}
    sid = task.input
    bid = extra.get("batch_id", "")
    d = extra.get("dataset", {})
    reg = extra.get("registry_entry")
    max_records = int(extra.get("max_records", 100))

    if reg is None:
        return {"source_id": sid, "batch_id": bid, "status": "failed",
                "error": "Not in registry", "records": [], "attempted": 0,
                "license_blocked": False}
    reg_status = reg.get("status", "candidate")
    if reg_status not in ("accepted", "review"):
        return {"source_id": sid, "batch_id": bid, "status": "skipped",
                "error": f"Registry status '{reg_status}' not in (accepted,review)",
                "records": [], "attempted": 0, "license_blocked": False}

    lic = d.get("license", "")
    if is_denied_license(lic):
        return {"source_id": sid, "batch_id": bid, "status": "failed",
                "error": f"License denied: {lic}", "records": [],
                "attempted": 0, "license_blocked": True}

    target = d.get("target_examples", 10)
    records = generate_source_records(sid, d, reg, target, max_records)
    return {"source_id": sid, "batch_id": bid, "status": "ok",
            "records": records, "attempted": len(records),
            "license_blocked": False}


# Operational kill-switch (same pattern as Phase 5B downloader).
_SCHEDULER_ENABLED = True


def run_engine_scheduler(
    root: str | Path,
    manifest: dict[str, Any],
    reg_by_id: dict[str, dict],
    max_records: int,
    *,
    workers: int | None = None,
    registry_root: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Run engine source tasks through the Universal Scheduler.

    Returns {task_id: payload} for EVERY planned task:
      - completed this run: worker payload (records + stats)
      - skipped (registry-completed prior run): payload {"status": "skipped",
        "records": []} so the serialized finalize can mark the checkpoint
        source completed and skip regeneration (matching sequential resume)
      - failed after retries: payload with error

    Falls back to sequential planning semantics on any scheduler error: the
    returned map contains worker-style payloads computed IN-PROCESS (still
    pure), which the finalize consumes identically.
    """
    root_p = Path(root).resolve()
    tasks = plan_engine_tasks(manifest, reg_by_id, max_records, root)
    if not tasks:
        return {}

    try:
        from parallel import resource
        from parallel.scheduler import Scheduler

        if not _SCHEDULER_ENABLED:
            raise RuntimeError("scheduler disabled (kill-switch)")

        reg_root = registry_root or (root_p / "metadata" / "pipeline_state")
        sched = Scheduler(
            "acquisition",
            registry_root=str(reg_root),
            workers=workers,
            pool="process",
            max_retries=2,
        )
        print(f"[engine] scheduler: {len(tasks)} source tasks, {sched.workers} workers")
        trs = sched.run(tasks, engine_source_task)
        out: dict[str, dict[str, Any]] = {}
        for tr in trs:
            if tr.status == "completed" and isinstance(tr.result, dict):
                out[tr.task_id] = tr.result
            elif tr.status == "skipped":
                sid = tr.task_id.split(":")[-1]
                out[tr.task_id] = {"source_id": sid, "batch_id": tr.task_id.split(":")[-2],
                                   "status": "skipped", "error": "completed in prior run",
                                   "records": [], "attempted": 0, "license_blocked": False}
            else:  # failed
                sid = tr.task_id.split(":")[-1]
                out[tr.task_id] = {"source_id": sid, "batch_id": tr.task_id.split(":")[-2],
                                   "status": "failed", "error": tr.error or "task failed",
                                   "records": [], "attempted": 0, "license_blocked": False}
        return out
    except Exception as sched_exc:
        print(f"[engine] scheduler unavailable ({sched_exc}); falling back to in-process pure workers", file=sys.stderr)
        out: dict[str, dict[str, Any]] = {}
        for t in tasks:
            try:
                out[t.task_id] = engine_source_task(t)
            except Exception as exc:
                sid = t.task_id.split(":")[-1]
                out[t.task_id] = {"source_id": sid, "batch_id": t.task_id.split(":")[-2],
                                  "status": "failed", "error": str(exc),
                                  "records": [], "attempted": 0, "license_blocked": False}
        return out
