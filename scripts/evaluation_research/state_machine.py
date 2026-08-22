"""state_machine.py — Research experiment state machine.

Extends the Atlas automation philosophy with research-specific states.
Preserves the WAITING_HUMAN_APPROVAL invariant at critical gates.

States:
  BENCHMARK_DISCOVERY
  → BENCHMARK_ACQUIRED
  → LICENSE_VALIDATED
  → CONTAMINATION_AUDIT
  → EVAL_SET_FROZEN
  → POLICY_CALIBRATION
  → POLICY_FROZEN
  → EVALUATION_RUNNING
  → EVALUATION_COMPLETE
  → STATISTICAL_ANALYSIS
  → HUMAN_REVIEW
  → CONCLUDED

Verdict states: PASS, FAIL, HOLD, INCONCLUSIVE — always with evidence references.
Automated system may calculate metrics, deltas, CIs, p-values, G-POL status,
contamination status — but may NOT silently turn these into scientific claims.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class ResearchState(str, Enum):
    """States for the research experiment lifecycle."""

    BENCHMARK_DISCOVERY = "BENCHMARK_DISCOVERY"
    BENCHMARK_ACQUIRED = "BENCHMARK_ACQUIRED"
    LICENSE_VALIDATED = "LICENSE_VALIDATED"
    CONTAMINATION_AUDIT = "CONTAMINATION_AUDIT"
    EVAL_SET_FROZEN = "EVAL_SET_FROZEN"
    POLICY_CALIBRATION = "POLICY_CALIBRATION"
    POLICY_FROZEN = "POLICY_FROZEN"
    EVALUATION_RUNNING = "EVALUATION_RUNNING"
    EVALUATION_COMPLETE = "EVALUATION_COMPLETE"
    STATISTICAL_ANALYSIS = "STATISTICAL_ANALYSIS"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    CONCLUDED = "CONCLUDED"

    # Verdict states (terminal)
    VERDICT_PASS = "VERDICT_PASS"
    VERDICT_FAIL = "VERDICT_FAIL"
    VERDICT_HOLD = "VERDICT_HOLD"
    VERDICT_INCONCLUSIVE = "VERDICT_INCONCLUSIVE"

    def __str__(self) -> str:
        return self.value


# Valid transitions — preserves WAITING_HUMAN_APPROVAL philosophy
# at critical gates: LICENSE_VALIDATED, EVAL_SET_FROZEN, POLICY_FROZEN, STATISTICAL_ANALYSIS
_VALID_TRANSITIONS: frozenset[tuple[ResearchState, ResearchState]] = frozenset({
    # Benchmark acquisition
    (ResearchState.BENCHMARK_DISCOVERY, ResearchState.BENCHMARK_ACQUIRED),
    (ResearchState.BENCHMARK_DISCOVERY, ResearchState.VERDICT_FAIL),

    # License validation gate (human approval required to proceed)
    (ResearchState.BENCHMARK_ACQUIRED, ResearchState.LICENSE_VALIDATED),
    (ResearchState.LICENSE_VALIDATED, ResearchState.CONTAMINATION_AUDIT),
    (ResearchState.LICENSE_VALIDATED, ResearchState.VERDICT_FAIL),

    # Contamination audit
    (ResearchState.CONTAMINATION_AUDIT, ResearchState.EVAL_SET_FROZEN),
    (ResearchState.CONTAMINATION_AUDIT, ResearchState.VERDICT_FAIL),

    # Eval set freeze gate (human approval required)
    (ResearchState.EVAL_SET_FROZEN, ResearchState.POLICY_CALIBRATION),
    (ResearchState.EVAL_SET_FROZEN, ResearchState.VERDICT_HOLD),

    # Policy calibration
    (ResearchState.POLICY_CALIBRATION, ResearchState.POLICY_FROZEN),
    (ResearchState.POLICY_CALIBRATION, ResearchState.VERDICT_HOLD),

    # Policy freeze gate (human approval required)
    (ResearchState.POLICY_FROZEN, ResearchState.EVALUATION_RUNNING),
    (ResearchState.POLICY_FROZEN, ResearchState.VERDICT_FAIL),

    # Evaluation
    (ResearchState.EVALUATION_RUNNING, ResearchState.EVALUATION_COMPLETE),
    (ResearchState.EVALUATION_RUNNING, ResearchState.VERDICT_FAIL),

    # Statistical analysis
    (ResearchState.EVALUATION_COMPLETE, ResearchState.STATISTICAL_ANALYSIS),
    (ResearchState.STATISTICAL_ANALYSIS, ResearchState.HUMAN_REVIEW),
    (ResearchState.STATISTICAL_ANALYSIS, ResearchState.VERDICT_INCONCLUSIVE),

    # Human review gate (mandatory)
    (ResearchState.HUMAN_REVIEW, ResearchState.CONCLUDED),
    (ResearchState.HUMAN_REVIEW, ResearchState.VERDICT_HOLD),
    (ResearchState.HUMAN_REVIEW, ResearchState.VERDICT_FAIL),
    (ResearchState.HUMAN_REVIEW, ResearchState.VERDICT_PASS),

    # Terminal states are final
})

# States that require human approval before proceeding
_APPROVAL_GATES: frozenset[ResearchState] = frozenset({
    ResearchState.LICENSE_VALIDATED,
    ResearchState.EVAL_SET_FROZEN,
    ResearchState.POLICY_FROZEN,
    ResearchState.HUMAN_REVIEW,
})


@dataclass(frozen=True)
class StateTransition:
    """Record of a single state transition."""
    from_state: ResearchState
    to_state: ResearchState
    timestamp: str
    triggered_by: str = "system"
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    verdict: str = ""  # PASS | FAIL | HOLD | INCONCLUSIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "timestamp": self.timestamp,
            "triggered_by": self.triggered_by,
            "reason": self.reason,
            "metadata": self.metadata,
            "verdict": self.verdict,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StateTransition":
        return cls(
            from_state=ResearchState(data["from_state"]),
            to_state=ResearchState(data["to_state"]),
            timestamp=data.get("timestamp", ""),
            triggered_by=data.get("triggered_by", "system"),
            reason=data.get("reason", ""),
            metadata=data.get("metadata", {}),
            verdict=data.get("verdict", ""),
        )


class ResearchStateMachine:
    """Research experiment state machine with human approval gates."""

    def __init__(self, experiment_id: str, root: str | Path) -> None:
        self.experiment_id = experiment_id
        self.root = Path(root).resolve()
        self._current_state = ResearchState.BENCHMARK_DISCOVERY
        self._transitions: list[StateTransition] = []
        self._error: str | None = None
        self._metadata: dict[str, Any] = {}
        self._human_approved: set[str] = set()  # gate states that have been approved

    @property
    def current_state(self) -> ResearchState:
        return self._current_state

    @property
    def transitions(self) -> list[StateTransition]:
        return list(self._transitions)

    @property
    def error(self) -> str | None:
        return self._error

    def is_at_gate(self) -> bool:
        """Check if the current state requires human approval."""
        return self._current_state in _APPROVAL_GATES

    def is_terminal(self) -> bool:
        """Check if in a terminal state."""
        return self._current_state in (
            ResearchState.CONCLUDED,
            ResearchState.VERDICT_PASS,
            ResearchState.VERDICT_FAIL,
            ResearchState.VERDICT_HOLD,
            ResearchState.VERDICT_INCONCLUSIVE,
        )

    def can_transition_to(self, target: ResearchState) -> bool:
        """Check if a transition is valid without applying it."""
        if not isinstance(target, ResearchState):
            return False
        return (self._current_state, target) in _VALID_TRANSITIONS

    def transition_to(
        self,
        target: ResearchState,
        *,
        triggered_by: str = "system",
        reason: str = "",
        metadata: dict[str, Any] | None = None,
        verdict: str = "",
    ) -> bool:
        """Attempt to transition to a new state."""
        if not isinstance(target, ResearchState):
            raise ValueError(f"Invalid target state: {target!r}")

        if self._current_state in _APPROVAL_GATES and self._current_state.value not in self._human_approved:
            # Require explicit human approval before leaving a gate state
            self._error = (
                f"State {self._current_state.value} requires human approval. "
                f"Call approve_gate('{self._current_state.value}') first."
            )
            return False

        transition = (self._current_state, target)
        if transition not in _VALID_TRANSITIONS:
            valid_targets = [
                t[1].value for t in _VALID_TRANSITIONS if t[0] == self._current_state
            ]
            self._error = (
                f"Invalid transition: {self._current_state.value} → {target.value}. "
                f"Valid: {valid_targets}"
            )
            return False

        now = datetime.now(timezone.utc).isoformat()
        t = StateTransition(
            from_state=self._current_state,
            to_state=target,
            timestamp=now,
            triggered_by=triggered_by,
            reason=reason,
            metadata=metadata or {},
            verdict=verdict,
        )
        self._transitions.append(t)
        self._current_state = target
        self._error = None
        self._persist()
        return True

    def approve_gate(self, state: ResearchState, approved_by: str,
                     comments: str = "") -> bool:
        """Grant human approval for a gate state.

        Persists the approval immediately to disk. A new FSM instance
        created after this call will see the approval via ``load()``.
        """
        if state not in _APPROVAL_GATES:
            self._error = f"{state.value} is not an approval gate state"
            return False
        if state != self._current_state:
            self._error = f"Cannot approve {state.value}; current state is {self._current_state.value}"
            return False
        self._human_approved.add(state.value)
        self._metadata[f"approval_{state.value}"] = {
            "approved_by": approved_by,
            "comments": comments,
            "approved_at": datetime.now(timezone.utc).isoformat(),
        }
        self._persist()
        return True

    def set_metadata(self, key: str, value: Any) -> None:
        """Attach arbitrary metadata to the experiment state."""
        self._metadata[key] = value

    def get_metadata(self, key: str, default: Any = None) -> Any:
        return self._metadata.get(key, default)

    def _state_path(self) -> Path:
        state_dir = self.root / "metadata" / "research_state"
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir / f"{self.experiment_id}.json"

    def _persist(self) -> None:
        data = {
            "experiment_id": self.experiment_id,
            "current_state": self._current_state.value,
            "transitions": [t.to_dict() for t in self._transitions],
            "metadata": self._metadata,
            "human_approved": sorted(self._human_approved),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        self._state_path().write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def load(self) -> bool:
        """Load persisted state from disk."""
        path = self._state_path()
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._current_state = ResearchState(data["current_state"])
            self._transitions = [
                StateTransition.from_dict(t) for t in data.get("transitions", [])
            ]
            self._metadata = data.get("metadata", {})
            self._human_approved = set(data.get("human_approved", []))
            return True
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self._error = f"Failed to load state: {e}"
            return False

    def summary(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "current_state": self._current_state.value,
            "is_at_gate": self.is_at_gate(),
            "is_terminal": self.is_terminal(),
            "n_transitions": len(self._transitions),
            "has_error": self._error is not None,
            "error": self._error,
            "last_transition": (
                self._transitions[-1].to_dict() if self._transitions else None
            ),
        }
