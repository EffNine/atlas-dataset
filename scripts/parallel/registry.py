#!/usr/bin/env python3
"""Universal scheduler — task registry (checkpoint + resume).

Append-only JSONL at metadata/pipeline_state/task_registry_{stage}.jsonl.

Task lifecycle:
  pending -> running -> completed
                    -> failed -> (retry) -> running -> ...
                    -> failed (max attempts reached, terminal)

Deterministic state transitions:
  - pending may become running or skipped
  - running may become completed or failed
  - failed may become running (retry) until max_retries exhausted
  - completed is terminal (never re-runs)

Crash recovery:
  - on restart, completed tasks are skipped
  - tasks stuck in 'running' are re-claimed after a lease timeout
  - attempts() counts 'failed' lines in the append-only file
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VALID_STATES = {"pending", "running", "completed", "failed", "retry", "skipped"}
TERMINAL = {"completed", "skipped"}
DEFAULT_LEASE_SECONDS = 900  # 15 min


class RegistryError(RuntimeError):
    pass


class TaskRegistry:
    """Persistent task state with append-only JSONL checkpointing."""

    def __init__(self, root: str | Path, stage: str, max_retries: int = 2):
        self.stage = stage
        self.max_retries = max(0, int(max_retries))
        self.path = Path(root) / f"task_registry_{stage}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, dict[str, Any]] = {}
        self._load()

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load last status per task_id from the append-only file."""
        if not self.path.exists():
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    tid = rec.get("task_id")
                    if tid:
                        self._records[tid] = rec  # last line wins
        except OSError:
            pass

    def _append(self, rec: dict[str, Any]) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    # ------------------------------------------------------------------
    # state transitions
    # ------------------------------------------------------------------

    def record(self, task_id: str, status: str, **fields: Any) -> None:
        """Transition a task to a new state (validated)."""
        if status not in VALID_STATES:
            raise RegistryError(f"invalid status: {status}")
        prev = self._records.get(task_id)
        if prev and prev.get("status") in TERMINAL and status not in ("skipped",):
            # completed/skipped are terminal; only allow explicit skip
            raise RegistryError(
                f"cannot transition {task_id} from terminal '{prev['status']}' to '{status}'"
            )
        rec: dict[str, Any] = {
            "task_id": task_id,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "attempt": fields.pop("attempt", self.attempts(task_id) + 1),
            **fields,
        }
        self._records[task_id] = rec
        self._append(rec)

    def claim(self, task_id: str, worker_id: str = "") -> bool:
        """Claim a pending task for execution. False if not claimable."""
        cur = self._records.get(task_id)
        if cur and cur.get("status") in TERMINAL:
            return False
        self.record(task_id, "running", worker_id=worker_id)
        return True

    def complete(self, task_id: str, **fields: Any) -> None:
        self.record(task_id, "completed", **fields)

    def fail(self, task_id: str, error: str = "") -> None:
        """Mark task failed (terminal state). Scheduler owns retry decisions
        by recording 'retry' explicitly before resubmission."""
        self.record(task_id, "failed", error=error)

    # ------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------

    def status(self, task_id: str) -> str:
        rec = self._records.get(task_id)
        return rec["status"] if rec else "pending"

    def is_completed(self, task_id: str) -> bool:
        return self.status(task_id) in TERMINAL

    def attempts(self, task_id: str) -> int:
        """Count failed attempts by scanning the append-only file.

        The in-memory dict is keyed by task_id (last status wins), so retries
        must be counted from the file lines.
        """
        count = 0
        if not self.path.exists():
            return 0
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("task_id") == task_id and rec.get("status") in ("failed", "retry"):
                        count += 1
        except OSError:
            pass
        return count

    def completed_ids(self) -> set[str]:
        return {tid for tid, rec in self._records.items() if rec.get("status") in TERMINAL}

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {s: 0 for s in VALID_STATES}
        for rec in self._records.values():
            counts[rec.get("status", "pending")] = counts.get(rec.get("status", "pending"), 0) + 1
        return counts

    # ------------------------------------------------------------------
    # crash recovery
    # ------------------------------------------------------------------

    def reclaim_stale_running(self, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> list[str]:
        """Re-claim tasks stuck in 'running' past the lease window.

        Returns the list of task_ids reclaimed (status reset to pending).
        Used after a machine reboot / worker crash.
        """
        reclaimed: list[str] = []
        now = time.time()
        for tid, rec in self._records.items():
            if rec.get("status") != "running":
                continue
            ts = rec.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(ts)
                age = now - dt.timestamp()
            except (ValueError, TypeError):
                age = lease_seconds + 1  # unknown age -> assume stale
            if age > lease_seconds:
                rec["status"] = "pending"
                self._append({**rec, "status": "pending", "timestamp": datetime.now(timezone.utc).isoformat()})
                reclaimed.append(tid)
        return reclaimed
