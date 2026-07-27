#!/usr/bin/env python3
"""
lifecycle.py — Atlas Acquisition Engine lifecycle state machine.

Tracks every record through a defined lifecycle:
  raw → processing → curated → review → released

Each transition is recorded with a timestamp and recorded in the record's
lineage. The state machine enforces valid transitions and prevents invalid
ones (e.g. raw → released without going through curated and review).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Valid lifecycle states and transitions
# ---------------------------------------------------------------------------

LIFECYCLE_STATES = [
    "raw",           # Just ingested, no processing done
    "processing",    # Being cleaned, deduplicated, scored
    "curated",       # Passed pipeline, meets quality gate, not yet reviewed
    "review",        # In human review queue
    "approved",      # Human-approved, ready for release
    "released",      # Included in a versioned release
    "archived",      # Superseded or deprecated, kept for lineage
    "rejected",      # Failed quality gate or human review
]

# Valid transitions: from -> [to states]
VALID_TRANSITIONS: dict[str, list[str]] = {
    "raw":          ["processing", "rejected"],
    "processing":   ["curated", "rejected", "raw"],
    "curated":      ["review", "processing", "rejected"],
    "review":       ["approved", "rejected", "needs_revision"],
    "needs_revision": ["review", "rejected", "curated"],
    "approved":     ["released", "review"],
    "released":     ["archived"],
    "archived":     [],
    "rejected":     ["raw"],  # can re-enter pipeline if re-evaluated
}


def is_valid_transition(from_state: str, to_state: str) -> bool:
    """Check if a lifecycle transition is valid."""
    allowed = VALID_TRANSITIONS.get(from_state, [])
    return to_state in allowed


def validate_lifecycle_transition(
    record_id: str, from_state: str, to_state: str
) -> str | None:
    """
    Validate a lifecycle transition. Returns None if valid, or an error string.
    """
    if from_state not in LIFECYCLE_STATES:
        return f"Unknown from_state '{from_state}' for record {record_id}"
    if to_state not in LIFECYCLE_STATES:
        return f"Unknown to_state '{to_state}' for record {record_id}"
    if not is_valid_transition(from_state, to_state):
        return (
            f"Invalid transition for record {record_id}: "
            f"'{from_state}' -> '{to_state}'. "
            f"Allowed: {VALID_TRANSITIONS.get(from_state, [])}"
        )
    return None


# ---------------------------------------------------------------------------
# Lifecycle tracking
# ---------------------------------------------------------------------------

class LifecycleTracker:
    """
    Tracks lifecycle state for records in a dataset.

    The tracker reads/writes a lifecycle registry at
    metadata/lifecycle_state.json that maps record IDs to their
    current state and transition history.
    """

    def __init__(self, metadata_dir: str | Path):
        self.registry_path = Path(metadata_dir) / "lifecycle_state.json"
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self._state: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self.registry_path.exists():
            try:
                data = json.loads(self.registry_path.read_text(encoding="utf-8"))
                self._state = data.get("records", {})
            except (json.JSONDecodeError, KeyError):
                self._state = {}

    def _save(self) -> None:
        data = {
            "generated": datetime.now(timezone.utc).isoformat(),
            "record_count": len(self._state),
            "records": self._state,
        }
        self.registry_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def get_record_state(self, record_id: str) -> str | None:
        """Get the current lifecycle state of a record."""
        entry = self._state.get(record_id)
        return entry.get("state") if entry else None

    def transition(
        self,
        record_id: str,
        to_state: str,
        source: str = "engine",
        reason: str = "",
    ) -> dict[str, Any]:
        """
        Transition a record to a new lifecycle state.

        Args:
            record_id: The record's unique ID
            to_state: Target lifecycle state
            source: Source of the transition ("engine", "human", "auto")
            reason: Optional reason for the transition

        Returns:
            Transition record with timestamp, from_state, to_state

        Raises:
            ValueError: If the transition is invalid
        """
        entry = self._state.setdefault(record_id, {
            "state": "raw",
            "history": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        from_state = entry["state"]

        error = validate_lifecycle_transition(record_id, from_state, to_state)
        if error:
            raise ValueError(error)

        now = datetime.now(timezone.utc).isoformat()
        transition = {
            "from": from_state,
            "to": to_state,
            "timestamp": now,
            "source": source,
            "reason": reason,
        }
        entry["history"].append(transition)
        entry["state"] = to_state
        entry["updated_at"] = now
        self._save()
        return transition

    def batch_transition(
        self,
        record_ids: list[str],
        to_state: str,
        source: str = "engine",
        reason: str = "",
    ) -> dict[str, list[dict[str, Any]]]:
        """Transition multiple records in batch. Returns {record_id: [transitions]}."""
        results: dict[str, list[dict[str, Any]]] = {}
        errors: list[str] = []
        for rid in record_ids:
            try:
                t = self.transition(rid, to_state, source, reason)
                results.setdefault(rid, []).append(t)
            except ValueError as e:
                errors.append(str(e))
        if errors:
            raise ValueError(
                f"Batch transition had {len(errors)} error(s): {errors[0]}"
            )
        return results

    def state_summary(self) -> dict[str, int]:
        """Return counts of records in each lifecycle state."""
        counts: dict[str, int] = {s: 0 for s in LIFECYCLE_STATES}
        for entry in self._state.values():
            s = entry.get("state", "raw")
            counts[s] = counts.get(s, 0) + 1
        return counts

    def all_records_in_state(self, state: str) -> list[str]:
        """Return all record IDs in a given state."""
        return [
            rid
            for rid, entry in self._state.items()
            if entry.get("state") == state
        ]

    def transition_history(self, record_id: str) -> list[dict[str, Any]]:
        """Get full transition history for a record."""
        entry = self._state.get(record_id, {})
        return entry.get("history", [])

    def report(self) -> dict[str, Any]:
        """Generate a full lifecycle report."""
        summary = self.state_summary()
        return {
            "generated": datetime.now(timezone.utc).isoformat(),
            "total_records": len(self._state),
            "state_summary": summary,
            "states_with_records": {k: v for k, v in summary.items() if v > 0},
        }
