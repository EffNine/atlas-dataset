#!/usr/bin/env python3
"""Atlas v1.9 — Incremental state tracker.

Tracks which sources have been processed at each pipeline stage so
re-runs only process new or changed sources.

State is persisted to ``metadata/pipeline_incremental.json``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class IncrementalState:
    """Per-stage per-source processing state with checksum-based change detection.

    Layout of ``metadata/pipeline_incremental.json``::

        {
            "sources": {
                "<source_id>": {
                    "download": {"checksum": "...", "completed_at": "..."},
                    "etl":      {"checksum": "...", "completed_at": "..."},
                    "transform":{"checksum": "...", "completed_at": "..."},
                    "views":    {"checksum": "...", "completed_at": "..."},
                    "release":  {"checksum": "...", "completed_at": "..."},
                }
            },
            "last_updated": "..."
        }
    """

    STAGES = ("download", "etl", "transform", "views", "release")

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self._path = self.root / "metadata" / "pipeline_incremental.json"
        self._state: dict[str, Any] = {"sources": {}, "last_updated": ""}
        self._load()

    # ── public ────────────────────────────────────────────────────────

    def is_done(self, source_id: str, stage: str, *, checksum: str = "") -> bool:
        """Return True if *source_id* has already completed *stage*.

        When *checksum* is given, also validates it matches the stored value
        (returns False on mismatch so the stage is re-run).
        """
        rec = self._state["sources"].get(source_id, {}).get(stage)
        if not rec:
            return False
        if checksum and rec.get("checksum") != checksum:
            return False
        return bool(rec.get("completed_at"))

    def mark_done(self, source_id: str, stage: str, *, checksum: str = "", metadata: dict[str, Any] | None = None) -> None:
        """Record successful completion of *stage* for *source_id*."""
        sources = self._state.setdefault("sources", {})
        src = sources.setdefault(source_id, {})
        src[stage] = {
            "checksum": checksum,
            "completed_at": _utc(),
            **(metadata or {}),
        }
        self._state["last_updated"] = _utc()
        self._save()

    def invalidate(self, source_id: str, stage: str | None = None) -> None:
        """Remove completion record(s) so stage(s) will re-run."""
        if source_id not in self._state["sources"]:
            return
        if stage is None:
            del self._state["sources"][source_id]
        else:
            self._state["sources"][source_id].pop(stage, None)
        self._state["last_updated"] = _utc()
        self._save()

    def pending_sources(self, stage: str, all_sources: list[str]) -> list[str]:
        """Return sources from *all_sources* that still need *stage*."""
        return [s for s in all_sources if not self.is_done(s, stage)]

    def status_report(self) -> dict[str, Any]:
        report: dict[str, Any] = {"stages": self.STAGES, "sources": {}}
        for sid, stages in self._state["sources"].items():
            report["sources"][sid] = {
                stage: bool(stages.get(stage, {}).get("completed_at"))
                for stage in self.STAGES
            }
        return report

    # ── checksum helpers ──────────────────────────────────────────────

    @staticmethod
    def checksum_for_etl(root: Path, source_id: str) -> str:
        """Fingerprint the ETL cleaned output for change detection."""
        path = root / "metadata" / "etl" / source_id / "cleaned.jsonl"
        if not path.exists():
            return ""
        h = hashlib.sha256()
        h.update(str(path.stat().st_size).encode())
        h.update(str(path.stat().st_mtime_ns).encode())
        return h.hexdigest()[:16]

    @staticmethod
    def checksum_for_download(root: Path, source_id: str) -> str:
        path = root / "metadata" / "download_logs" / f"{source_id}.download.json"
        if not path.exists():
            return ""
        h = hashlib.sha256()
        h.update(str(path.stat().st_size).encode())
        h.update(str(path.stat().st_mtime_ns).encode())
        return h.hexdigest()[:16]

    # ── persistence ───────────────────────────────────────────────────

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._state = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._state = {"sources": {}, "last_updated": ""}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
