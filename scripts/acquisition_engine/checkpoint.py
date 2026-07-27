#!/usr/bin/env python3
"""
checkpoint.py — Atlas Acquisition Engine checkpoint/resume system.

Provides save/load/resume for deterministic, resumable batch execution.
Each checkpoint records the execution state: which batches and sources
have been completed, which are in-flight, and accumulated statistics.

Checkpoints are stored as JSON at metadata/engine_checkpoint.json and include
a sha256 checksum of the state so tampering is detectable.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Checkpoint model
# ---------------------------------------------------------------------------

@dataclass
class SourceCheckpoint:
    source_id: str
    status: str  # "pending", "resolving", "downloading", "pipelining", "validating", "completed", "failed", "skipped"
    batch_id: str
    records_processed: int = 0
    records_accepted: int = 0
    records_rejected: int = 0
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


@dataclass
class EngineCheckpoint:
    session_id: str
    engine_version: str = "0.1.0"
    mode: str = "dry-run"  # "dry-run" or "execute"
    started_at: str = ""
    updated_at: str = ""
    status: str = "created"  # "created", "running", "paused", "completed", "failed"
    current_batch: str | None = None
    completed_batches: list[str] = field(default_factory=list)
    sources: dict[str, SourceCheckpoint] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
    checksum: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["sources"] = {k: asdict(v) for k, v in self.sources.items()}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "EngineCheckpoint":
        sources = {}
        for k, v in d.get("sources", {}).items():
            sources[k] = SourceCheckpoint(**v)
        d["sources"] = sources
        return cls(**{k: v for k, v in d.items() if k != "checksum"})


# ---------------------------------------------------------------------------
# Checkpoint manager
# ---------------------------------------------------------------------------

class CheckpointManager:
    """Manages checkpoint save/load/resume for the Acquisition Engine."""

    def __init__(self, checkpoint_dir: str | Path):
        self.dir = Path(checkpoint_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._current: EngineCheckpoint | None = None

    @property
    def checkpoint_path(self) -> Path:
        return self.dir / "engine_checkpoint.json"

    def _compute_checksum(self, data: dict) -> str:
        raw = json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
        return hashlib.sha256(raw).hexdigest()

    def create(
        self,
        session_id: str,
        mode: str = "dry-run",
        batches: list[str] | None = None,
        source_ids: list[str] | None = None,
    ) -> EngineCheckpoint:
        now = datetime.now(timezone.utc).isoformat()
        sources = {}
        if source_ids:
            for sid in source_ids:
                sources[sid] = SourceCheckpoint(
                    source_id=sid,
                    status="pending",
                    batch_id="",
                )
        # Assign batch groups if provided
        if batches and source_ids:
            # Simple round-robin assignment
            for i, sid in enumerate(source_ids):
                if sid in sources:
                    sources[sid].batch_id = batches[i % len(batches)]

        cp = EngineCheckpoint(
            session_id=session_id,
            mode=mode,
            started_at=now,
            updated_at=now,
            status="created",
            sources=sources,
        )
        d = cp.to_dict()
        d.pop("checksum", None)
        cp.checksum = self._compute_checksum(d)
        self._current = cp
        self._save()
        return cp

    def _save(self) -> None:
        if self._current is None:
            return
        d = self._current.to_dict()
        d.pop("checksum", None)
        d["checksum"] = self._compute_checksum(d)
        self.checkpoint_path.write_text(
            json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def load(self) -> EngineCheckpoint | None:
        if not self.checkpoint_path.exists():
            return None
        try:
            raw = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            stored_checksum = raw.pop("checksum", "")
            computed = self._compute_checksum(raw)
            if stored_checksum and stored_checksum != computed:
                raise RuntimeError(
                    f"Checkpoint checksum mismatch: stored={stored_checksum}, "
                    f"computed={computed}. File may be tampered or corrupted."
                )
            cp = EngineCheckpoint.from_dict(raw)
            cp.checksum = stored_checksum
            self._current = cp
            return cp
        except (json.JSONDecodeError, KeyError) as e:
            raise RuntimeError(f"Failed to load checkpoint: {e}")

    def get(self) -> EngineCheckpoint | None:
        return self._current

    def update_source_status(
        self,
        source_id: str,
        status: str,
        records_processed: int | None = None,
        records_accepted: int | None = None,
        records_rejected: int | None = None,
        error: str | None = None,
    ) -> None:
        if self._current is None:
            raise RuntimeError("No active checkpoint to update")
        if source_id not in self._current.sources:
            self._current.sources[source_id] = SourceCheckpoint(
                source_id=source_id, status=status, batch_id=""
            )
        sc = self._current.sources[source_id]
        sc.status = status
        if status in ("downloading", "pipelining", "validating", "resolving"):
            sc.started_at = sc.started_at or datetime.now(timezone.utc).isoformat()
        if status in ("completed", "failed", "skipped"):
            sc.completed_at = datetime.now(timezone.utc).isoformat()
        if records_processed is not None:
            sc.records_processed = records_processed
        if records_accepted is not None:
            sc.records_accepted = records_accepted
        if records_rejected is not None:
            sc.records_rejected = records_rejected
        if error is not None:
            sc.error = error
        self._current.updated_at = datetime.now(timezone.utc).isoformat()
        self._save()

    def set_batch_completed(self, batch_id: str) -> None:
        if self._current is None:
            return
        if batch_id not in self._current.completed_batches:
            self._current.completed_batches.append(batch_id)
        self._current.updated_at = datetime.now(timezone.utc).isoformat()
        self._save()

    def set_current_batch(self, batch_id: str | None) -> None:
        if self._current is None:
            return
        self._current.current_batch = batch_id
        self._current.updated_at = datetime.now(timezone.utc).isoformat()
        self._save()

    def set_status(self, status: str) -> None:
        if self._current is None:
            return
        self._current.status = status
        self._current.updated_at = datetime.now(timezone.utc).isoformat()
        self._save()

    def update_stats(self, stats: dict[str, Any]) -> None:
        if self._current is None:
            return
        self._current.stats.update(stats)
        self._current.updated_at = datetime.now(timezone.utc).isoformat()
        self._save()

    def resume_candidates(self) -> list[str]:
        """Return source_ids that are still pending or failed (resumable)."""
        if self._current is None:
            return []
        return [
            sid
            for sid, sc in self._current.sources.items()
            if sc.status in ("pending", "failed")
        ]

    def completed_sources(self) -> list[str]:
        if self._current is None:
            return []
        return [sid for sid, sc in self._current.sources.items() if sc.status == "completed"]

    def summary(self) -> dict[str, Any]:
        if self._current is None:
            # Try to load from disk (cross-process persistence)
            try:
                loaded = self.load()
                if loaded is not None:
                    self._current = loaded
                else:
                    return {"status": "no_checkpoint"}
            except (RuntimeError, Exception):
                return {"status": "no_checkpoint"}
        cp = self._current
        total = len(cp.sources)
        completed = sum(1 for s in cp.sources.values() if s.status == "completed")
        failed = sum(1 for s in cp.sources.values() if s.status == "failed")
        pending = sum(1 for s in cp.sources.values() if s.status == "pending")
        return {
            "session_id": cp.session_id,
            "mode": cp.mode,
            "status": cp.status,
            "total_sources": total,
            "completed": completed,
            "failed": failed,
            "pending": pending,
            "completed_batches": cp.completed_batches,
            "current_batch": cp.current_batch,
            "updated_at": cp.updated_at,
        }
