#!/usr/bin/env python3
"""State machine for Atlas Automation Layer v1.

Defines the finite state machine (FSM) governing the pipeline lifecycle.

Pipeline states::

    INGESTED → QUALITY_CHECK → PROVENANCE_CHECK → CONTENT_REVISION
        → VALIDATION → WAITING_HUMAN_APPROVAL → RELEASED

The state machine enforces:
  - Forward-only progression (no backward transitions)
  - Mandatory human approval before RELEASED
  - State persistence to metadata/ for durability
  - Invalid transition rejection with clear error messages
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Pipeline states
# ---------------------------------------------------------------------------


class PipelineState(str, Enum):
    """All possible pipeline states for a dataset release candidate."""

    INGESTED = "INGESTED"
    QUALITY_CHECK = "QUALITY_CHECK"
    PROVENANCE_CHECK = "PROVENANCE_CHECK"
    CONTENT_REVISION = "CONTENT_REVISION"
    VALIDATION = "VALIDATION"
    WAITING_HUMAN_APPROVAL = "WAITING_HUMAN_APPROVAL"
    FAILED = "FAILED"
    READY_FOR_RELEASE = "READY_FOR_RELEASE"
    RELEASE_REJECTED = "RELEASE_REJECTED"
    RELEASED = "RELEASED"

    def __str__(self) -> str:
        return self.value


# ---------------------------------------------------------------------------
# State ordering and valid transitions
# ---------------------------------------------------------------------------

STATE_ORDER: list[PipelineState] = [
    PipelineState.INGESTED,
    PipelineState.QUALITY_CHECK,
    PipelineState.PROVENANCE_CHECK,
    PipelineState.CONTENT_REVISION,
    PipelineState.VALIDATION,
    PipelineState.WAITING_HUMAN_APPROVAL,
    PipelineState.READY_FOR_RELEASE,
    PipelineState.RELEASE_REJECTED,
    PipelineState.FAILED,
    PipelineState.RELEASED,
]

# Index lookup for fast ordering checks
_STATE_INDEX = {s: i for i, s in enumerate(STATE_ORDER)}

# Valid transitions: (from_state, to_state) pairs
VALID_TRANSITIONS: frozenset[tuple[PipelineState, PipelineState]] = frozenset({
    (PipelineState.INGESTED, PipelineState.QUALITY_CHECK),
    (PipelineState.INGESTED, PipelineState.FAILED),
    (PipelineState.QUALITY_CHECK, PipelineState.PROVENANCE_CHECK),
    (PipelineState.QUALITY_CHECK, PipelineState.FAILED),
    (PipelineState.PROVENANCE_CHECK, PipelineState.CONTENT_REVISION),
    (PipelineState.PROVENANCE_CHECK, PipelineState.FAILED),
    (PipelineState.CONTENT_REVISION, PipelineState.VALIDATION),
    (PipelineState.CONTENT_REVISION, PipelineState.FAILED),
    (PipelineState.VALIDATION, PipelineState.WAITING_HUMAN_APPROVAL),
    (PipelineState.VALIDATION, PipelineState.FAILED),
    (PipelineState.WAITING_HUMAN_APPROVAL, PipelineState.READY_FOR_RELEASE),
    (PipelineState.WAITING_HUMAN_APPROVAL, PipelineState.RELEASE_REJECTED),
    (PipelineState.WAITING_HUMAN_APPROVAL, PipelineState.FAILED),
    (PipelineState.READY_FOR_RELEASE, PipelineState.RELEASED),
    (PipelineState.READY_FOR_RELEASE, PipelineState.FAILED),
    (PipelineState.FAILED, PipelineState.INGESTED),
})


# ---------------------------------------------------------------------------
# Transition metadata
# ---------------------------------------------------------------------------


@dataclass
class StateTransition:
    """Record of a single state transition with metadata."""

    from_state: PipelineState
    to_state: PipelineState
    timestamp: str
    triggered_by: str = "system"
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "timestamp": self.timestamp,
            "triggered_by": self.triggered_by,
            "reason": self.reason,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StateTransition:
        return cls(
            from_state=PipelineState(data["from_state"]),
            to_state=PipelineState(data["to_state"]),
            timestamp=data.get("timestamp", ""),
            triggered_by=data.get("triggered_by", "system"),
            reason=data.get("reason", ""),
            metadata=data.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class StateMachine:
    """Finite state machine for the Atlas automation pipeline.

    Manages pipeline state transitions with validation, persistence,
    and audit trail.

    Args:
        pipeline_id: Unique identifier for this pipeline run.
        root: Path to the atlas-dataset repository root (for state persistence).
        initial_state: Starting state. Defaults to INGESTED.

    Typical usage::

        sm = StateMachine("release-v0.3", ROOT)
        sm.transition_to(PipelineState.QUALITY_CHECK, triggered_by="quality_agent")
        sm.transition_to(PipelineState.PROVENANCE_CHECK,
                         triggered_by="provenance_agent")
        # ... through the pipeline ...
        # Only WAITING_HUMAN_APPROVAL can transition to RELEASED
        sm.transition_to(
            PipelineState.RELEASED,
            triggered_by="human",
            reason="Approved by reviewer after quality gate passed",
        )
    """

    def __init__(
        self,
        pipeline_id: str,
        root: str | Path,
        initial_state: PipelineState = PipelineState.INGESTED,
    ) -> None:
        self.pipeline_id = pipeline_id
        self.root = Path(root).resolve()
        self._current_state = initial_state
        self._transitions: list[StateTransition] = []
        self._error: str | None = None
        self._failure_info: dict[str, Any] | None = None

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def current_state(self) -> PipelineState:
        return self._current_state

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def transitions(self) -> list[StateTransition]:
        return list(self._transitions)

    @property
    def transition_history(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self._transitions]

    @property
    def failure_info(self) -> dict[str, Any] | None:
        """Get persisted failure details, or None if no failure occurred."""
        return self._failure_info

    def has_failed(self) -> bool:
        """Check if the pipeline has a recorded failure."""
        return self._failure_info is not None

    def set_failure(
        self,
        agent_name: str,
        reason: str,
        next_action: str = "",
    ) -> None:
        """Record failure details for the pipeline and persist immediately.

        Args:
            agent_name: The agent that failed (e.g. ``"quality"``).
            reason: Human-readable failure description.
            next_action: Recommended recovery action
                         (e.g. ``"RETRY_QUALITY"``, ``"RESET_PIPELINE"``).
        """
        self._failure_info = {
            "agent_name": agent_name,
            "reason": reason,
            "next_action": next_action,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._persist()

    def clear_failure(self) -> None:
        """Clear any recorded failure information."""
        self._failure_info = None

    # ── Core API ─────────────────────────────────────────────────────────

    def transition_to(
        self,
        target: PipelineState,
        *,
        triggered_by: str = "system",
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Attempt to transition to a new state.

        Args:
            target: The target PipelineState.
            triggered_by: Identifier for what initiated this transition.
            reason: Human-readable reason for the transition.
            metadata: Optional extra metadata to attach.

        Returns:
            True if the transition was valid and applied, False otherwise.
            Check ``self.error`` for failure reason.

        Raises:
            ValueError: If ``target`` is not a valid PipelineState.
        """
        if not isinstance(target, PipelineState):
            raise ValueError(f"Invalid target state: {target!r}")

        transition = (self._current_state, target)

        if transition not in VALID_TRANSITIONS:
            valid_targets = self._valid_targets_from_current()
            self._error = (
                f"Invalid transition: {self._current_state.value} → {target.value}. "
                f"Valid targets from {self._current_state.value}: "
                f"{valid_targets}"
            )
            return False

        # Record the transition
        now = datetime.now(timezone.utc).isoformat()
        t = StateTransition(
            from_state=self._current_state,
            to_state=target,
            timestamp=now,
            triggered_by=triggered_by,
            reason=reason,
            metadata=metadata or {},
        )
        self._transitions.append(t)
        self._current_state = target
        self._error = None

        # Persist state
        self._persist()

        return True

    def can_transition_to(self, target: PipelineState) -> bool:
        """Check if a transition is valid without applying it."""
        if not isinstance(target, PipelineState):
            return False
        return (self._current_state, target) in VALID_TRANSITIONS

    def is_after(self, state: PipelineState) -> bool:
        """Check if current state is at or after the given state in the pipeline."""
        current_idx = _STATE_INDEX.get(self._current_state, -1)
        target_idx = _STATE_INDEX.get(state, -1)
        if current_idx == -1 or target_idx == -1:
            return False
        return current_idx >= target_idx

    def is_before(self, state: PipelineState) -> bool:
        """Check if current state is before the given state in the pipeline."""
        return not self.is_after(state) and self._current_state != state

    def is_terminal(self) -> bool:
        """Check if the pipeline has reached a terminal state."""
        return self._current_state in (
            PipelineState.RELEASED,
            PipelineState.RELEASE_REJECTED,
        )

    def is_blocked(self) -> bool:
        """Check if the pipeline is blocked waiting for human approval."""
        return self._current_state in (
            PipelineState.WAITING_HUMAN_APPROVAL,
        )

    def reset(self, to_state: PipelineState = PipelineState.INGESTED) -> None:
        """Reset the state machine to a given state (for error recovery).

        Args:
            to_state: State to reset to. Defaults to INGESTED.
        """
        self._current_state = to_state
        self._transitions = []
        self._error = None
        self._failure_info = None
        self._persist()

    # ── Persistence ──────────────────────────────────────────────────────

    def _state_path(self) -> Path:
        """Path to the persistent state file for this pipeline."""
        state_dir = self.root / "metadata" / "pipeline_state"
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir / f"{self.pipeline_id}.json"

    def _persist(self) -> None:
        """Write current state to disk."""
        data = self._serialize()
        path = self._state_path()
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def load(self) -> bool:
        """Load persisted state from disk.

        Returns:
            True if state was loaded, False if no persisted state exists.
        """
        path = self._state_path()
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._deserialize(data)
            return True
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self._error = f"Failed to load persisted state: {e}"
            return False

    # ── Serialization ────────────────────────────────────────────────────

    def _serialize(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "pipeline_id": self.pipeline_id,
            "current_state": self._current_state.value,
            "transitions": [t.to_dict() for t in self._transitions],
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        if self._failure_info is not None:
            data["failure_info"] = self._failure_info
        return data

    def _deserialize(self, data: dict[str, Any]) -> None:
        self.pipeline_id = data["pipeline_id"]
        self._current_state = PipelineState(data["current_state"])
        self._transitions = [
            StateTransition.from_dict(t) for t in data.get("transitions", [])
        ]
        self._failure_info = data.get("failure_info")

    # ── Helpers ──────────────────────────────────────────────────────────

    def _valid_targets_from_current(self) -> list[str]:
        return [
            t[1].value
            for t in VALID_TRANSITIONS
            if t[0] == self._current_state
        ]

    def summary(self) -> dict[str, Any]:
        """Return a human-readable summary of the current pipeline state."""
        result: dict[str, Any] = {
            "pipeline_id": self.pipeline_id,
            "current_state": self._current_state.value,
            "total_transitions": len(self._transitions),
            "is_terminal": self.is_terminal(),
            "is_blocked_on_human_approval": self.is_blocked(),
            "has_error": self._error is not None,
            "error": self._error,
            "has_failure": self.has_failed(),
            "failure_info": self._failure_info,
            "last_transition": (
                self._transitions[-1].to_dict() if self._transitions else None
            ),
        }
        return result
