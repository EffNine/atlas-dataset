#!/usr/bin/env python3
"""Tests for Atlas Automation Layer v1 — state machine and approval gate.

Covers:
  - All valid state transitions (6 forward transitions)
  - All invalid state transitions (backward, skipped, wrong target)
  - Approval gate: create, approve, deny, check
  - Approval blocking: cannot reach RELEASED without human sign-off
  - State machine persistence (load/save round-trip)
  - State machine is_terminal, is_blocked, is_after, is_before helpers
  - Agent interface contract (abstract method enforcement)
  - Pipeline orchestrator: full pipeline flow
  - Pipeline orchestrator: approval integration
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

# Ensure the scripts directory is importable
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from automation.state_machine import (
    PipelineState,
    StateTransition,
    StateMachine,
    VALID_TRANSITIONS,
    STATE_ORDER,
)
from automation.approval_gate import (
    ApprovalGate,
    ApprovalRequest,
    ApprovalDecision,
    ApproverRole,
)
from automation.base_agent import BaseAgent, AgentResult, AgentStatus
from automation.pipeline_orchestrator import (
    PipelineOrchestrator,
    PipelineResult,
    PipelineStatus,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_temp_root() -> Path:
    """Create a temporary atlas root with scripts copied (needed for production agents)."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "metadata").mkdir(parents=True, exist_ok=True)
    # Copy scripts so production agents (quality, validation) resolve imports
    (tmp / "scripts").mkdir(exist_ok=True)
    src = Path(__file__).resolve().parent.parent / "scripts"
    for item in src.iterdir():
        if item.is_file() and item.suffix == ".py" and not item.name.startswith("_"):
            (tmp / "scripts" / item.name).write_text(
                item.read_text(encoding="utf-8"), encoding="utf-8"
            )
    auto_dst = tmp / "scripts" / "automation"
    auto_dst.mkdir(exist_ok=True)
    for item in (src / "automation").iterdir():
        if item.is_file() and item.suffix == ".py":
            (auto_dst / item.name).write_text(
                item.read_text(encoding="utf-8"), encoding="utf-8"
            )
    return tmp


def _full_transition_sequence(sm: StateMachine) -> list[tuple[PipelineState, bool]]:
    """Run all valid forward transitions and return (target, success) pairs."""
    results = []
    for target in [
        PipelineState.QUALITY_CHECK,
        PipelineState.PROVENANCE_CHECK,
        PipelineState.CONTENT_REVISION,
        PipelineState.VALIDATION,
        PipelineState.WAITING_HUMAN_APPROVAL,
        PipelineState.READY_FOR_RELEASE,
        PipelineState.RELEASED,
    ]:
        ok = sm.transition_to(target, triggered_by="test")
        results.append((target, ok))
    return results


# ===================================================================
# State Machine: Valid Transitions
# ===================================================================


def test_initial_state():
    """State machine starts at INGESTED."""
    sm = StateMachine("test-pipeline", _make_temp_root())
    assert sm.current_state == PipelineState.INGESTED
    assert not sm.is_terminal()
    assert not sm.is_blocked()


def test_full_valid_sequence():
    """All 6 forward transitions succeed in order."""
    sm = StateMachine("test-pipeline", _make_temp_root())
    results = _full_transition_sequence(sm)
    assert all(ok for _, ok in results), f"Failed: {results}"
    assert sm.current_state == PipelineState.RELEASED
    assert sm.is_terminal()
    assert sm.error is None


def test_valid_transition_leaves_no_error():
    """Successful transitions clear the error field."""
    sm = StateMachine("test-pipeline", _make_temp_root())
    sm.transition_to(PipelineState.QUALITY_CHECK)
    assert sm.error is None


def test_transition_from_states_are_mutually_exclusive():
    """Each non-terminal state now has FAILED as an additional valid target.
    Forward transitions remain mutually exclusive.
    WAITING_HUMAN_APPROVAL has 3 targets (READY_FOR_RELEASE, RELEASE_REJECTED, FAILED).
    FAILED has 5 targets (INGESTED, QUALITY_CHECK, PROVENANCE_CHECK, CONTENT_REVISION, VALIDATION)."""
    for from_state in STATE_ORDER:
        if from_state in (PipelineState.RELEASED, PipelineState.RELEASE_REJECTED):
            continue  # terminal — no targets
        targets = [t[1] for t in VALID_TRANSITIONS if t[0] == from_state]
        if from_state == PipelineState.WAITING_HUMAN_APPROVAL:
            assert len(targets) == 3, (
                f"{from_state} should have 3 valid targets, got {targets}"
            )
            assert PipelineState.FAILED in targets
        elif from_state == PipelineState.FAILED:
            assert len(targets) == 5, (
                f"FAILED should have exactly 5 valid targets, got {targets}"
            )
            assert PipelineState.INGESTED in targets
            assert PipelineState.QUALITY_CHECK in targets
            assert PipelineState.PROVENANCE_CHECK in targets
            assert PipelineState.CONTENT_REVISION in targets
            assert PipelineState.VALIDATION in targets
        else:
            # Each non-terminal, non-WAITING, non-FAILED state has 2 targets:
            # its natural forward progression + FAILED
            assert len(targets) == 2, (
                f"{from_state} should have 2 valid targets (forward + FAILED), got {targets}"
            )
            assert PipelineState.FAILED in targets


def test_released_is_terminal():
    """RELEASED has no outgoing transitions."""
    released_targets = [
        t for t in VALID_TRANSITIONS if t[0] == PipelineState.RELEASED
    ]
    assert len(released_targets) == 0, f"RELEASED should have no targets: {released_targets}"


def test_transition_history_records_each_step():
    """Each transition is recorded in the history."""
    sm = StateMachine("test-pipeline", _make_temp_root())
    sm.transition_to(PipelineState.QUALITY_CHECK, triggered_by="quality_agent",
                     reason="Quality check passed")
    sm.transition_to(PipelineState.PROVENANCE_CHECK, triggered_by="test",
                     reason="Provenance OK")
    assert len(sm.transitions) == 2
    assert sm.transitions[0].from_state == PipelineState.INGESTED
    assert sm.transitions[0].to_state == PipelineState.QUALITY_CHECK
    assert sm.transitions[0].triggered_by == "quality_agent"
    assert sm.transitions[1].from_state == PipelineState.QUALITY_CHECK
    assert sm.transition_history[1]["reason"] == "Provenance OK"


def test_transition_with_metadata():
    """Transition metadata is recorded."""
    sm = StateMachine("test-pipeline", _make_temp_root())
    sm.transition_to(
        PipelineState.QUALITY_CHECK,
        triggered_by="test",
        reason="Test",
        metadata={"score": 9, "records": 100},
    )
    assert sm.transitions[0].metadata["score"] == 9
    assert sm.transitions[0].metadata["records"] == 100


# ===================================================================
# State Machine: Invalid Transitions
# ===================================================================


def test_cannot_skip_state():
    """Cannot skip from INGESTED directly to VALIDATION."""
    sm = StateMachine("test-pipeline", _make_temp_root())
    ok = sm.transition_to(PipelineState.VALIDATION)
    assert not ok
    assert sm.error is not None
    assert "Invalid transition" in sm.error


def test_cannot_go_backward():
    """Cannot transition backward in the pipeline."""
    sm = StateMachine("test-pipeline", _make_temp_root())
    sm.transition_to(PipelineState.QUALITY_CHECK)
    ok = sm.transition_to(PipelineState.INGESTED)
    assert not ok
    assert "Invalid transition" in sm.error


def test_cannot_skip_approval_to_released():
    """Cannot go directly from VALIDATION to RELEASED."""
    sm = StateMachine("test-pipeline", _make_temp_root())
    sm.transition_to(PipelineState.QUALITY_CHECK)
    sm.transition_to(PipelineState.PROVENANCE_CHECK)
    sm.transition_to(PipelineState.CONTENT_REVISION)
    sm.transition_to(PipelineState.VALIDATION)
    # Try to skip WAITING_HUMAN_APPROVAL
    ok = sm.transition_to(PipelineState.RELEASED)
    assert not ok
    assert sm.current_state == PipelineState.VALIDATION


def test_cannot_transition_from_released():
    """RELEASED is terminal — no transitions from it."""
    sm = StateMachine("test-pipeline", _make_temp_root())
    _full_transition_sequence(sm)
    assert sm.is_terminal()
    ok = sm.transition_to(PipelineState.INGESTED)
    assert not ok


def test_can_transition_to_returns_false_for_invalid():
    """can_transition_to returns False for invalid targets."""
    sm = StateMachine("test-pipeline", _make_temp_root())
    assert sm.can_transition_to(PipelineState.VALIDATION) is False
    assert sm.can_transition_to(PipelineState.QUALITY_CHECK) is True


def test_can_transition_to_rejects_non_enum():
    """can_transition_to returns False for non-PipelineState values."""
    sm = StateMachine("test-pipeline", _make_temp_root())
    assert sm.can_transition_to("INVALID") is False  # type: ignore
    assert sm.can_transition_to(None) is False  # type: ignore


def test_only_released_from_waiting():
    """From WAITING_HUMAN_APPROVAL, valid targets are READY_FOR_RELEASE,
    RELEASE_REJECTED, and FAILED."""
    sm = StateMachine("test-pipeline", _make_temp_root())
    sm.transition_to(PipelineState.QUALITY_CHECK)
    sm.transition_to(PipelineState.PROVENANCE_CHECK)
    sm.transition_to(PipelineState.CONTENT_REVISION)
    sm.transition_to(PipelineState.VALIDATION)
    sm.transition_to(PipelineState.WAITING_HUMAN_APPROVAL)
    # Try to go somewhere invalid (backward)
    ok = sm.transition_to(PipelineState.INGESTED)
    assert not ok
    assert sm.error is not None
    # Valid transitions from WAITING_HUMAN_APPROVAL
    assert sm.can_transition_to(PipelineState.READY_FOR_RELEASE)
    assert sm.can_transition_to(PipelineState.RELEASE_REJECTED)
    assert sm.can_transition_to(PipelineState.FAILED)
    # RELEASED is NOT directly reachable — must go through READY_FOR_RELEASE
    assert not sm.can_transition_to(PipelineState.RELEASED)


# ===================================================================
# State Machine: Helper Properties
# ===================================================================


def test_is_after():
    """is_after correctly identifies progression."""
    sm = StateMachine("test-pipeline", _make_temp_root())
    assert sm.is_after(PipelineState.INGESTED)  # at INGESTED, >= INGESTED
    assert not sm.is_after(PipelineState.QUALITY_CHECK)
    sm.transition_to(PipelineState.QUALITY_CHECK)
    assert sm.is_after(PipelineState.INGESTED)
    assert sm.is_after(PipelineState.QUALITY_CHECK)


def test_is_before():
    """is_before correctly identifies position."""
    sm = StateMachine("test-pipeline", _make_temp_root())
    assert sm.is_before(PipelineState.QUALITY_CHECK)
    assert not sm.is_before(PipelineState.INGESTED)  # at INGESTED, not before
    sm.transition_to(PipelineState.QUALITY_CHECK)
    assert sm.is_before(PipelineState.PROVENANCE_CHECK)
    assert not sm.is_before(PipelineState.INGESTED)


def test_is_blocked_only_in_waiting():
    """is_blocked is True only in WAITING_HUMAN_APPROVAL."""
    sm = StateMachine("test-pipeline", _make_temp_root())
    assert not sm.is_blocked()
    sm.transition_to(PipelineState.QUALITY_CHECK)
    assert not sm.is_blocked()
    sm.transition_to(PipelineState.PROVENANCE_CHECK)
    assert not sm.is_blocked()
    sm.transition_to(PipelineState.CONTENT_REVISION)
    assert not sm.is_blocked()
    sm.transition_to(PipelineState.VALIDATION)
    assert not sm.is_blocked()
    sm.transition_to(PipelineState.WAITING_HUMAN_APPROVAL)
    assert sm.is_blocked()


def test_is_terminal_only_in_released_or_rejected():
    """is_terminal is True only in RELEASED or RELEASE_REJECTED."""
    sm = StateMachine("test-pipeline", _make_temp_root())
    assert not sm.is_terminal()
    sm.transition_to(PipelineState.QUALITY_CHECK)
    assert not sm.is_terminal()
    _full_transition_sequence(sm)
    assert sm.current_state == PipelineState.RELEASED
    assert sm.is_terminal()
    # RELEASE_REJECTED is also terminal
    sm2 = StateMachine("test-rejected", _make_temp_root())
    sm2.transition_to(PipelineState.QUALITY_CHECK)
    sm2.transition_to(PipelineState.PROVENANCE_CHECK)
    sm2.transition_to(PipelineState.CONTENT_REVISION)
    sm2.transition_to(PipelineState.VALIDATION)
    sm2.transition_to(PipelineState.WAITING_HUMAN_APPROVAL)
    sm2.transition_to(PipelineState.RELEASE_REJECTED)
    assert sm2.is_terminal()


# ===================================================================
# State Machine: Persistence
# ===================================================================


def test_state_persistence_round_trip():
    """State machine persists to and loads from disk correctly."""
    tmp = _make_temp_root()
    sm = StateMachine("test-persist", tmp)
    sm.transition_to(PipelineState.QUALITY_CHECK)
    sm.transition_to(PipelineState.PROVENANCE_CHECK)

    # New instance loading from same root
    sm2 = StateMachine("test-persist", tmp)
    loaded = sm2.load()
    assert loaded
    assert sm2.current_state == PipelineState.PROVENANCE_CHECK
    assert len(sm2.transitions) == 2
    assert sm2.transitions[0].to_state == PipelineState.QUALITY_CHECK
    assert sm2.transitions[1].to_state == PipelineState.PROVENANCE_CHECK


def test_state_persistence_file_exists():
    """Persisted state file is written to metadata/pipeline_state/."""
    tmp = _make_temp_root()
    sm = StateMachine("test-persist-file", tmp)
    sm.transition_to(PipelineState.QUALITY_CHECK)
    persisted_path = tmp / "metadata" / "pipeline_state" / "test-persist-file.json"
    assert persisted_path.exists()
    data = json.loads(persisted_path.read_text())
    assert data["pipeline_id"] == "test-persist-file"
    assert data["current_state"] == "QUALITY_CHECK"


def test_state_persistence_no_file():
    """Loading with no existing state returns False."""
    sm = StateMachine("test-nonexistent", _make_temp_root())
    assert sm.load() is False
    assert sm.current_state == PipelineState.INGESTED


def test_state_reset():
    """reset() returns to INGESTED and clears history."""
    sm = StateMachine("test-reset", _make_temp_root())
    sm.transition_to(PipelineState.QUALITY_CHECK)
    sm.transition_to(PipelineState.PROVENANCE_CHECK)
    sm.reset()
    assert sm.current_state == PipelineState.INGESTED
    assert len(sm.transitions) == 0
    assert sm.error is None


def test_state_summary():
    """summary() returns a useful dict."""
    sm = StateMachine("test-summary", _make_temp_root())
    summary = sm.summary()
    assert summary["pipeline_id"] == "test-summary"
    assert summary["current_state"] == "INGESTED"
    assert summary["is_terminal"] is False
    assert summary["is_blocked_on_human_approval"] is False
    assert summary["has_error"] is False
    assert summary["total_transitions"] == 0
    assert summary["has_failure"] is False
    assert summary["failure_info"] is None


# ===================================================================
# State Machine: Failure Persistence
# ===================================================================


def test_failure_info_none_by_default():
    """Pipeline with no failures has no failure info."""
    sm = StateMachine("test-fail-default", _make_temp_root())
    assert sm.failure_info is None
    assert not sm.has_failed()
    sm.load()
    assert sm.failure_info is None
    assert not sm.has_failed()


def test_set_failure_persists_info():
    """set_failure() records all required fields."""
    sm = StateMachine("test-fail-set", _make_temp_root())
    sm.set_failure(
        agent_name="quality",
        reason="Quality score below threshold",
        next_action="RETRY_QUALITY",
    )
    assert sm.has_failed()
    fi = sm.failure_info
    assert fi is not None
    assert fi["agent_name"] == "quality"
    assert fi["reason"] == "Quality score below threshold"
    assert fi["next_action"] == "RETRY_QUALITY"
    assert "timestamp" in fi


def test_failure_persistence_survives_load():
    """Failure info is persisted and survives a state machine reload."""
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="atlas-test-fail-"))
    (tmp / "metadata").mkdir(parents=True, exist_ok=True)

    sm1 = StateMachine("test-persist-fail", tmp)
    sm1.set_failure(agent_name="validation", reason="Schema validation failed",
                    next_action="RETRY_VALIDATION")

    sm2 = StateMachine("test-persist-fail", tmp)
    loaded = sm2.load()
    assert loaded
    assert sm2.has_failed()
    fi = sm2.failure_info
    assert fi is not None
    assert fi["agent_name"] == "validation"
    assert fi["reason"] == "Schema validation failed"
    assert fi["next_action"] == "RETRY_VALIDATION"

    import shutil
    shutil.rmtree(str(tmp), ignore_errors=True)


def test_clear_failure_removes_info():
    """clear_failure() removes failure info."""
    sm = StateMachine("test-fail-clear", _make_temp_root())
    sm.set_failure(agent_name="quality", reason="Test failure")
    assert sm.has_failed()
    sm.clear_failure()
    assert not sm.has_failed()
    assert sm.failure_info is None


def test_reset_clears_failure():
    """reset() clears failure info."""
    sm = StateMachine("test-fail-reset", _make_temp_root())
    sm.set_failure(agent_name="quality", reason="Test failure")
    assert sm.has_failed()
    sm.reset()
    assert not sm.has_failed()
    assert sm.current_state == PipelineState.INGESTED


def test_transition_to_failed_state():
    """Can transition to FAILED from any forward state."""
    sm = StateMachine("test-to-failed", _make_temp_root())
    ok = sm.transition_to(PipelineState.FAILED)
    assert ok
    assert sm.current_state == PipelineState.FAILED


def test_failed_state_retry_to_ingested():
    """Can reset from FAILED back to INGESTED."""
    sm = StateMachine("test-failed-retry", _make_temp_root())
    sm.transition_to(PipelineState.FAILED)
    assert sm.current_state == PipelineState.FAILED
    ok = sm.transition_to(PipelineState.INGESTED)
    assert ok
    assert sm.current_state == PipelineState.INGESTED


def test_failed_not_terminal():
    """FAILED is NOT a terminal state — a reset is possible."""
    sm = StateMachine("test-failed-term", _make_temp_root())
    sm.transition_to(PipelineState.FAILED)
    assert not sm.is_terminal()
    assert not sm.is_blocked()


def test_summary_includes_failure():
    """summary() includes failure info when present."""
    sm = StateMachine("test-summary-fail", _make_temp_root())
    sm.set_failure(agent_name="provenance", reason="Unresolved provenance records",
                   next_action="REVIEW_PROVENANCE_RECORDS")
    summary = sm.summary()
    assert summary["has_failure"] is True
    assert summary["failure_info"] is not None
    assert summary["failure_info"]["agent_name"] == "provenance"


# ===================================================================
# Approval Gate
# ===================================================================


def test_approval_create_request():
    """Create an approval request in PENDING state."""
    gate = ApprovalGate(_make_temp_root())
    req = gate.create_request("test-pipeline")
    assert req.pipeline_id == "test-pipeline"
    assert req.is_pending
    assert req.decision == ApprovalDecision.PENDING


def test_approval_approve():
    """Approve a pipeline request."""
    gate = ApprovalGate(_make_temp_root())
    gate.create_request("test-pipeline")
    result = gate.approve("test-pipeline", decided_by="reviewer_alice",
                          role=ApproverRole.REVIEWER, comments="LGTM")
    assert result is True
    assert gate.is_releasable("test-pipeline") is True
    req = gate.get_request("test-pipeline")
    assert req.is_approved
    assert req.decided_by == "reviewer_alice"
    assert req.comments == "LGTM"


def test_approval_deny():
    """Deny a pipeline request."""
    gate = ApprovalGate(_make_temp_root())
    gate.create_request("test-pipeline")
    result = gate.deny("test-pipeline", decided_by="reviewer_bob",
                       role=ApproverRole.MAINTAINER, comments="Need more data")
    assert result is True
    assert gate.is_releasable("test-pipeline") is False
    req = gate.get_request("test-pipeline")
    assert req.is_denied
    assert req.decided_by == "reviewer_bob"


def test_approval_approve_nonexistent():
    """Approving a non-existent pipeline returns False."""
    gate = ApprovalGate(_make_temp_root())
    result = gate.approve("nonexistent", decided_by="test")
    assert result is False


def test_approval_check_gate_no_request():
    """check_approval_gate returns helpful message when no request exists."""
    gate = ApprovalGate(_make_temp_root())
    check = gate.check_approval_gate("test-pipeline")
    assert check["approved"] is False
    assert "no approval request" in check["message"].lower()


def test_approval_check_gate_approved():
    """check_approval_gate returns approved=True when request is approved."""
    gate = ApprovalGate(_make_temp_root())
    gate.create_request("test-pipeline")
    gate.approve("test-pipeline", decided_by="reviewer_alice")
    check = gate.check_approval_gate("test-pipeline")
    assert check["approved"] is True
    assert "approved" in check["message"].lower()


def test_approval_check_gate_denied():
    """check_approval_gate returns approved=False when request is denied."""
    gate = ApprovalGate(_make_temp_root())
    gate.create_request("test-pipeline")
    gate.deny("test-pipeline", decided_by="reviewer_bob")
    check = gate.check_approval_gate("test-pipeline")
    assert check["approved"] is False
    assert "denied" in check["message"].lower()


def test_approval_check_gate_pending():
    """check_approval_gate returns approved=False when request is pending."""
    gate = ApprovalGate(_make_temp_root())
    gate.create_request("test-pipeline")
    check = gate.check_approval_gate("test-pipeline")
    assert check["approved"] is False
    assert "awaiting" in check["message"].lower()


def test_approval_persistence():
    """Approval gate persists to and loads from disk."""
    tmp = _make_temp_root()
    gate1 = ApprovalGate(tmp)
    gate1.create_request("test-pipeline")
    gate1.approve("test-pipeline", decided_by="reviewer_alice")

    gate2 = ApprovalGate(tmp)
    assert gate2.is_releasable("test-pipeline") is True
    req = gate2.get_request("test-pipeline")
    assert req.is_approved
    assert req.decided_by == "reviewer_alice"


def test_approval_list_requests():
    """list_requests returns all known requests."""
    gate = ApprovalGate(_make_temp_root())
    gate.create_request("pipeline-1")
    gate.create_request("pipeline-2")
    requests = gate.list_requests()
    assert len(requests) >= 2


def test_approval_rescind():
    """reject_or_rescind resets a decision to PENDING."""
    gate = ApprovalGate(_make_temp_root())
    gate.create_request("test-pipeline")
    gate.approve("test-pipeline", decided_by="reviewer_alice")
    assert gate.is_releasable("test-pipeline")
    gate.reject_or_rescind("test-pipeline")
    assert not gate.is_releasable("test-pipeline")
    req = gate.get_request("test-pipeline")
    assert req.is_pending


# ===================================================================
# Approval Blocking: RELEASED Gate
# ===================================================================


def test_approval_mandatory_before_released():
    """Human approval is mandatory before RELEASED — cannot bypass.

    The state machine *permits* the FSM transition (WAITING_HUMAN_APPROVAL
    → RELEASED). The ORCHESTRATOR enforces that the approval gate check
    passes before calling that transition.
    """
    tmp = _make_temp_root()
    sm = StateMachine("test-mandatory", tmp)
    # Progress through all states
    sm.transition_to(PipelineState.QUALITY_CHECK)
    sm.transition_to(PipelineState.PROVENANCE_CHECK)
    sm.transition_to(PipelineState.CONTENT_REVISION)
    sm.transition_to(PipelineState.VALIDATION)
    sm.transition_to(PipelineState.WAITING_HUMAN_APPROVAL)
    # The state machine allows READY_FOR_RELEASE and RELEASE_REJECTED from WAITING
    # RELEASED is NOT directly reachable — must go through READY_FOR_RELEASE first
    assert sm.can_transition_to(PipelineState.READY_FOR_RELEASE)
    assert not sm.can_transition_to(PipelineState.RELEASED)


def test_orchestrator_blocks_release_without_approval():
    """Pipeline orchestrator blocks release when no human approval exists."""
    tmp = _make_temp_root()
    (tmp / "curated" / "v0.1").mkdir(parents=True, exist_ok=True)
    pilot = tmp / "curated" / "v0.1" / "pilot_candidates.jsonl"
    # Use a record that passes quality evaluation (>= 7)
    rec = {
        "id": "test_001",
        "category": "01_foundation",
        "subcategory": "instruction-following",
        "type": "instruction",
        "source": {"name": "test", "license": "MIT"},
        "messages": [
            {"role": "user", "content": "Explain the concept of encapsulation in object-oriented programming."},
            {"role": "assistant", "content": (
                "Encapsulation is a fundamental OOP principle that bundles data and methods "
                "into a single class unit, restricting direct access to internal state. "
                "For example, a BankAccount class uses private _balance and public "
                "deposit()/withdraw() methods to enforce validation rules. "
                "This provides information hiding, maintainability, and security benefits."
            )},
        ],
        "verified": False,
        "quality_score": 9,
        "tags": ["oop"],
        "difficulty": 1,
        "language": "en",
        "notes": "test record",
    }
    pilot.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    orch = PipelineOrchestrator("test-no-approval", tmp)
    # Run to approval (should stop at WAITING_HUMAN_APPROVAL)
    result = orch.run_to_approval()
    assert result.status == PipelineStatus.BLOCKED_ON_APPROVAL
    assert result.current_state == PipelineState.WAITING_HUMAN_APPROVAL.value
    assert not orch.state_machine.is_terminal()

    # Now try full pipeline — should still block
    result2 = orch.run_full_pipeline()
    assert result2.status == PipelineStatus.BLOCKED_ON_APPROVAL
    assert not orch.state_machine.is_terminal()


def test_orchestrator_release_with_approval():
    """Pipeline orchestrator releases when human approval is granted."""
    tmp = _make_temp_root()
    (tmp / "curated" / "v0.1").mkdir(parents=True, exist_ok=True)
    pilot = tmp / "curated" / "v0.1" / "pilot_candidates.jsonl"
    rec = {
        "id": "test_001",
        "category": "01_foundation",
        "subcategory": "instruction-following",
        "type": "instruction",
        "source": {"name": "test", "license": "MIT"},
        "messages": [
            {"role": "user", "content": "Explain the concept of encapsulation in object-oriented programming."},
            {"role": "assistant", "content": (
                "Encapsulation is a fundamental OOP principle that bundles data and methods "
                "into a single class unit, restricting direct access to internal state. "
                "For example, a BankAccount class uses private _balance and public "
                "deposit()/withdraw() methods to enforce validation rules. "
                "This provides information hiding, maintainability, and security benefits."
            )},
        ],
        "verified": False,
        "quality_score": 9,
        "tags": ["oop"],
        "difficulty": 1,
        "language": "en",
        "notes": "test record",
    }
    pilot.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    orch = PipelineOrchestrator("test-with-approval", tmp)

    # Run to approval gate
    result1 = orch.run_to_approval()
    assert result1.status == PipelineStatus.BLOCKED_ON_APPROVAL

    # Grant human approval
    orch.approve_release(
        decided_by="reviewer_alice",
        role=ApproverRole.REVIEWER,
        comments="All checks passed",
    )

    # Now run full pipeline — should complete
    result2 = orch.run_full_pipeline()
    assert result2.status == PipelineStatus.COMPLETED, f"Got {result2.status}: {result2.errors}"
    assert orch.state_machine.is_terminal()
    assert orch.state_machine.current_state == PipelineState.RELEASED


def test_approval_denied_blocks_release():
    """Denied approval prevents release even if requested."""
    tmp = _make_temp_root()
    (tmp / "curated" / "v0.1").mkdir(parents=True, exist_ok=True)
    pilot = tmp / "curated" / "v0.1" / "pilot_candidates.jsonl"
    rec = {
        "id": "test_001",
        "category": "01_foundation",
        "subcategory": "instruction-following",
        "type": "instruction",
        "source": {"name": "test", "license": "MIT"},
        "messages": [
            {"role": "user", "content": "Explain the concept of encapsulation in object-oriented programming."},
            {"role": "assistant", "content": (
                "Encapsulation is a fundamental OOP principle that bundles data and methods "
                "into a single class unit, restricting direct access to internal state. "
                "For example, a BankAccount class uses private _balance and public "
                "deposit()/withdraw() methods to enforce validation rules. "
                "This provides information hiding, maintainability, and security benefits."
            )},
        ],
        "verified": False,
        "quality_score": 9,
        "tags": ["oop"],
        "difficulty": 1,
        "language": "en",
        "notes": "test record",
    }
    pilot.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    orch = PipelineOrchestrator("test-denied", tmp)
    orch.run_to_approval()
    orch.deny_release(
        decided_by="reviewer_bob",
        role=ApproverRole.REVIEWER,
        comments="Quality gate not met",
    )
    # Full pipeline should not release
    result = orch.run_full_pipeline()
    assert result.status == PipelineStatus.BLOCKED_ON_APPROVAL
    assert not orch.state_machine.is_terminal()


# ===================================================================
# Base Agent Interface
# ===================================================================


def test_base_agent_abstract():
    """BaseAgent cannot be instantiated directly (it's abstract)."""
    import traceback
    try:
        BaseAgent("/tmp")  # type: ignore
        assert False, "Should have raised TypeError"
    except TypeError:
        pass  # Expected — cannot instantiate abstract class


def test_agent_result_properties():
    """AgentResult convenience properties work correctly."""
    passed = AgentResult("test", AgentStatus.PASSED)
    assert passed.passed
    assert not passed.failed

    failed = AgentResult("test", AgentStatus.FAILED)
    assert failed.failed
    assert not failed.passed

    pending = AgentResult("test", AgentStatus.PENDING)
    assert not pending.passed
    assert not pending.failed


def test_agent_result_serialization():
    """AgentResult to_dict() produces a clean dict."""
    result = AgentResult(
        agent_name="test_agent",
        status=AgentStatus.PASSED,
        summary="Everything OK",
        data={"count": 5},
        errors=[],
        warnings=["minor issue"],
    )
    d = result.to_dict()
    assert d["agent_name"] == "test_agent"
    assert d["status"] == "passed"
    assert d["summary"] == "Everything OK"
    assert d["data"]["count"] == 5
    assert d["warnings"] == ["minor issue"]


# ===================================================================
# Pipeline Orchestrator
# ===================================================================


def test_orchestrator_initial_state():
    """Orchestrator starts with the pipeline at INGESTED."""
    orch = PipelineOrchestrator("test-init", _make_temp_root())
    assert orch.state_machine.current_state == PipelineState.INGESTED
    status = orch.get_status()
    assert status["state"]["current_state"] == "INGESTED"


def test_orchestrator_reset():
    """reset_pipeline returns to initial state."""
    tmp = _make_temp_root()
    orch = PipelineOrchestrator("test-reset", tmp)
    orch.state_machine.transition_to(PipelineState.QUALITY_CHECK)
    assert orch.state_machine.current_state != PipelineState.INGESTED
    orch.reset_pipeline()
    assert orch.state_machine.current_state == PipelineState.INGESTED


def test_orchestrator_request_approval():
    """request_human_approval creates a pending approval request."""
    orch = PipelineOrchestrator("test-req", _make_temp_root())
    req = orch.request_human_approval(requested_by="system")
    assert req["pipeline_id"] == "test-req"
    assert req["decision"] == "pending"


# ===================================================================
# State Transition: VALID_TRANSITIONS completeness
# ===================================================================


def test_all_states_in_valid_transitions():
    """Every non-terminal state appears as a source in VALID_TRANSITIONS."""
    terminal_states = {PipelineState.RELEASED, PipelineState.RELEASE_REJECTED}
    for state in STATE_ORDER:
        if state in terminal_states:
            continue
        sources = {t[0] for t in VALID_TRANSITIONS}
        assert state in sources, f"{state} missing from VALID_TRANSITIONS"


def test_state_order_is_complete():
    """STATE_ORDER contains all PipelineState values."""
    assert set(STATE_ORDER) == set(PipelineState)


def test_valid_transitions_counts():
    """There are 20 valid transitions: 8 forward, 7 state→FAILED, 5 FAILED→X."""
    forward = 8  # original forward-only transitions
    to_failed = 7  # each non-terminal, non-FAILED state → FAILED
    from_failed = 5  # FAILED → INGESTED, QUALITY_CHECK, PROVENANCE_CHECK, CONTENT_REVISION, VALIDATION
    expected = forward + to_failed + from_failed
    assert len(VALID_TRANSITIONS) == expected, (
        f"Expected {expected} transitions ({forward} forward + {to_failed} to FAILED + "
        f"{from_failed} from FAILED), got {len(VALID_TRANSITIONS)}"
    )


# ===================================================================
# Validation Agent (v1.1 Production)
# ===================================================================


def _make_validation_env() -> tuple[Path, Path]:
    """Create a temp atlas root with a small curated dataset.

    Returns (root, dataset_path).
    """
    tmp = Path(tempfile.mkdtemp())
    (tmp / "metadata").mkdir()
    (tmp / "curated" / "v0.1").mkdir(parents=True)
    (tmp / "scripts").mkdir()
    # Symlink or copy scripts so imports resolve
    import importlib.util
    src = Path(__file__).resolve().parent.parent / "scripts"
    for item in src.iterdir():
        if item.is_file() and item.suffix == ".py" and not item.name.startswith("_"):
            (tmp / "scripts" / item.name).write_text(
                item.read_text(encoding="utf-8"), encoding="utf-8"
            )
    return tmp, tmp / "curated" / "v0.1" / "pilot_candidates.jsonl"


def _write_dataset(path: Path, records: list[dict]) -> None:
    """Write records as JSONL to path."""
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n",
        encoding="utf-8",
    )


_VALID_RECORD = {
    "id": "01_foundation_instruction_0001",
    "category": "01_foundation",
    "subcategory": "instruction-following",
    "type": "instruction",
    "source": {"name": "test", "license": "MIT", "date": "2026-01-01"},
    "messages": [
        {"role": "user", "content": "What is Python?"},
        {"role": "assistant", "content": "Python is a programming language."},
    ],
    "language": "en",
    "difficulty": 1,
    "tags": ["python"],
    "quality_score": 9,
    "verified": True,
    "notes": "Test record",
}


# ── Basic validation ──────────────────────────────────────────────────────


def test_validation_agent_accepts_valid_record():
    """A structurally valid record passes all checks."""
    tmp, dspath = _make_validation_env()
    _write_dataset(dspath, [_VALID_RECORD])
    try:
        agent = __import__("automation.validation_agent", fromlist=["ValidationAgent"]).ValidationAgent(tmp)
        result = agent.execute()
        assert result.passed, f"Expected PASS, got FAIL: {result.summary}"
        assert result.data["stats"]["valid"] == 1
        assert result.data["stats"]["with_errors"] == 0
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_validation_agent_rejects_bad_id():
    """Invalid record IDs are caught by structural errors."""
    tmp, dspath = _make_validation_env()
    rec = dict(_VALID_RECORD, id="BAD ID WITH SPACES")
    _write_dataset(dspath, [rec])
    try:
        agent = __import__("automation.validation_agent", fromlist=["ValidationAgent"]).ValidationAgent(tmp)
        result = agent.execute()
        assert not result.passed
        assert result.data["stats"]["with_errors"] == 1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_validation_agent_rejects_missing_fields():
    """Records missing required fields are flagged."""
    tmp, dspath = _make_validation_env()
    rec = {"id": "test_001"}  # Bare minimum — missing most fields
    _write_dataset(dspath, [rec])
    try:
        agent = __import__("automation.validation_agent", fromlist=["ValidationAgent"]).ValidationAgent(tmp)
        result = agent.execute()
        assert not result.passed
        assert result.data["stats"]["with_errors"] >= 1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── License gate ──────────────────────────────────────────────────────────


def test_validation_agent_rejects_denied_license():
    """Records with denied licenses (NC/proprietary) are caught."""
    tmp, dspath = _make_validation_env()
    rec = dict(_VALID_RECORD)
    rec["source"] = {"name": "bad", "license": "CC-BY-NC-4.0"}
    _write_dataset(dspath, [rec])
    try:
        agent = __import__("automation.validation_agent", fromlist=["ValidationAgent"]).ValidationAgent(tmp)
        result = agent.execute()
        assert not result.passed
        any_denied = any("Denied license" in err for r in result.data["records"] for err in r["errors"])
        assert any_denied, "Expected 'Denied license' error"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_validation_agent_allows_safe_licenses():
    """Records with safe licenses (MIT, Apache, CC-BY) pass the gate."""
    tmp, dspath = _make_validation_env()
    rec = dict(_VALID_RECORD, id="test_safe_lic")
    rec["source"] = {"name": "src", "license": "CC-BY-4.0"}
    _write_dataset(dspath, [rec])
    try:
        agent = __import__("automation.validation_agent", fromlist=["ValidationAgent"]).ValidationAgent(tmp)
        result = agent.execute()
        # Single record — should pass
        assert result.passed
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Duplicates ────────────────────────────────────────────────────────────


def test_validation_agent_detects_duplicate_ids():
    """Duplicate record IDs are detected."""
    tmp, dspath = _make_validation_env()
    rec1 = dict(_VALID_RECORD, id="dup_001")
    rec2 = dict(_VALID_RECORD, id="dup_001",
                messages=[{"role": "user", "content": "other"}, {"role": "assistant", "content": "stuff"}])
    _write_dataset(dspath, [rec1, rec2])
    try:
        agent = __import__("automation.validation_agent", fromlist=["ValidationAgent"]).ValidationAgent(tmp)
        result = agent.execute()
        assert not result.passed
        assert "dup_001" in result.data.get("duplicate_ids", [])
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_validation_agent_detects_duplicate_content():
    """Records with identical message content are flagged."""
    tmp, dspath = _make_validation_env()
    rec1 = dict(_VALID_RECORD, id="cnt_001")
    rec2 = dict(_VALID_RECORD, id="cnt_002")
    _write_dataset(dspath, [rec1, rec2])
    try:
        agent = __import__("automation.validation_agent", fromlist=["ValidationAgent"]).ValidationAgent(tmp)
        result = agent.execute()
        assert not result.passed
        assert result.data["stats"]["with_errors"] >= 1
        any_dup = any("Duplicate content" in err for r in result.data["records"] for err in r["errors"])
        assert any_dup, "Expected 'Duplicate content' error"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── JSON parse errors ─────────────────────────────────────────────────────


def test_validation_agent_reports_parse_errors():
    """Lines that aren't valid JSON are reported as parse errors."""
    tmp, dspath = _make_validation_env()
    dspath.write_text(
        json.dumps(_VALID_RECORD) + "\n"
        + "not valid json\n"
        + json.dumps(dict(_VALID_RECORD, id="test_002")) + "\n",
        encoding="utf-8",
    )
    try:
        agent = __import__("automation.validation_agent", fromlist=["ValidationAgent"]).ValidationAgent(tmp)
        result = agent.execute()
        assert not result.passed
        assert len(result.data["parse_errors"]) == 1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Strict curated gate ───────────────────────────────────────────────────


def test_validation_agent_strict_gate():
    """With strict=True, records below threshold fail."""
    tmp, dspath = _make_validation_env()
    rec = dict(_VALID_RECORD, quality_score=3, verified=False)
    _write_dataset(dspath, [rec])
    try:
        agent = __import__("automation.validation_agent", fromlist=["ValidationAgent"]).ValidationAgent(tmp,
            config={"strict": True, "min_quality": 7})
        result = agent.execute()
        assert not result.passed
        # Should have at least "Record not verified" and "quality_score 3 < 7"
        score_caught = any("quality_score" in err for r in result.data["records"] for err in r["errors"])
        verified_caught = any("not verified" in err for r in result.data["records"] for err in r["errors"])
        assert score_caught, "Strict gate should catch low quality_score"
        assert verified_caught, "Strict gate should catch unverified records"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_validation_agent_strict_gate_passes():
    """With strict=True, high-quality verified records pass."""
    tmp, dspath = _make_validation_env()
    rec = dict(_VALID_RECORD, quality_score=9, verified=True)
    _write_dataset(dspath, [rec])
    try:
        agent = __import__("automation.validation_agent", fromlist=["ValidationAgent"]).ValidationAgent(tmp,
            config={"strict": True})
        result = agent.execute()
        assert result.passed
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Schema type detection ─────────────────────────────────────────────────


def test_validation_agent_auto_detects_ko_schema():
    """schema_type='auto' detects knowledge_object records."""
    tmp, dspath = _make_validation_env()
    ko_rec = dict(_VALID_RECORD, id="ko_test_001",
                  knowledge_type="fact",
                  source_attribution={"source_id": "s1", "name": "n", "url": "", "license": "MIT", "attribution_text": "a"},
                  canonical_answer="test",
                  license="MIT",
                  lineage={"source": "s", "transformations": [], "knowledge_object": "id",
                           "curated_dataset": "v0.1", "training_view": "qwen", "future_model": "m"},
                  training_view_eligibility={"qwen": True, "llama": True, "deepseek": True},
                  verification_status="pending",
                  metadata={"test": True})
    _write_dataset(dspath, [ko_rec])
    try:
        agent = __import__("automation.validation_agent", fromlist=["ValidationAgent"]).ValidationAgent(tmp,
            config={"schema_type": "auto"})
        result = agent.execute()
        assert result.data["schema_type"] == "knowledge_object"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_validation_agent_auto_detects_base_schema():
    """schema_type='auto' detects base-schema records."""
    tmp, dspath = _make_validation_env()
    _write_dataset(dspath, [_VALID_RECORD])
    try:
        agent = __import__("automation.validation_agent", fromlist=["ValidationAgent"]).ValidationAgent(tmp,
            config={"schema_type": "auto"})
        result = agent.execute()
        assert result.data["schema_type"] == "base"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Pipeline integration ──────────────────────────────────────────────────


def test_orchestrator_passes_through_validation():
    """Orchestrator advances through validation with a valid dataset."""
    tmp, dspath = _make_validation_env()
    valid_rec = dict(_VALID_RECORD, id="vtest_001",
                     messages=[{"role": "user", "content": "Explain encapsulation in OOP."},
                               {"role": "assistant", "content": (
                                   "Encapsulation bundles data and methods into a class unit, "
                                   "restricting direct access to internal state. A BankAccount "
                                   "class uses private fields with public deposit/withdraw "
                                   "methods that enforce validation rules like non-negative "
                                   "balances. This provides information hiding and maintainability."
                               )}])
    _write_dataset(dspath, [valid_rec])
    try:
        orch = __import__("automation.pipeline_orchestrator", fromlist=["PipelineOrchestrator"]).PipelineOrchestrator(
            "test-val-pass", tmp)
        result = orch.run_to_approval()
        # Should reach WAITING_HUMAN_APPROVAL (validation passed)
        assert result.current_state == "WAITING_HUMAN_APPROVAL", f"Got {result.current_state}: {result.summary}"
        assert "validation" in result.agent_results
        assert result.agent_results["validation"].passed
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_orchestrator_blocks_on_validation_failure():
    """Orchestrator blocks pipeline when validation fails."""
    tmp, dspath = _make_validation_env()
    bad_rec = {
        "id": "bad",
        "category": "invalid",
        "subcategory": "none",
        "type": "unknown",
        "source": {"name": "t", "license": "MIT"},
        "messages": [{"role": "user", "content": "Explain encapsulation in OOP."},
                      {"role": "assistant", "content": (
                          "Encapsulation bundles data and methods into a class unit, "
                          "restricting direct access to internal state. A BankAccount "
                          "class uses private fields with public deposit/withdraw "
                          "methods that enforce validation rules like non-negative "
                          "balances. This provides information hiding and maintainability."
                      )}],
        "quality_score": 9,
        "verified": False,
        "tags": [],
        "difficulty": 1,
        "language": "en",
        "notes": "bad record",
    }  # category "invalid" causes structural errors
    _write_dataset(dspath, [bad_rec])
    try:
        orch = __import__("automation.pipeline_orchestrator", fromlist=["PipelineOrchestrator"]).PipelineOrchestrator(
            "test-val-block", tmp)
        result = orch.run_to_approval()
        # Should NOT reach WAITING_HUMAN_APPROVAL — blocked at VALIDATION
        assert result.current_state != "WAITING_HUMAN_APPROVAL"
        assert "validation" in result.agent_results
        assert not result.agent_results["validation"].passed
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Error summary ─────────────────────────────────────────────────────────


def test_validation_agent_error_summary():
    """Error summary aggregates patterns across records."""
    tmp, dspath = _make_validation_env()
    recs = [
        {"id": "bad_001"},  # Missing fields -> category, type, etc.
        {"id": "bad_002"},  # Same pattern
        dict(_VALID_RECORD, id="good_001"),
    ]
    _write_dataset(dspath, recs)
    try:
        agent = __import__("automation.validation_agent", fromlist=["ValidationAgent"]).ValidationAgent(tmp)
        result = agent.execute()
        summary = result.data["error_summary"]
        assert summary["total_records"] == 3
        assert summary["unique_error_patterns"] > 0
        # "category invalid" should appear twice
        assert any("category" in k for k in summary["error_patterns"])
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── No-op: no dataset found ───────────────────────────────────────────────


def test_validation_agent_skips_when_no_dataset():
    """Agent returns SKIPPED when no dataset file exists."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "metadata").mkdir()
    (tmp / "curated" / "v0.1").mkdir(parents=True)
    (tmp / "scripts").mkdir()
    try:
        agent = __import__("automation.validation_agent", fromlist=["ValidationAgent"]).ValidationAgent(tmp)
        result = agent.execute()
        assert result.status.value == "skipped"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ===================================================================
# Quality Agent (v1.2 Production)
# ===================================================================


def _quality_env() -> tuple[Path, Path]:
    """Create temp atlas root with scripts copied for quality engine."""
    tmp = Path(tempfile.mkdtemp())
    for d in ("metadata", "curated/v0.1", "tmp", "scripts"):
        (tmp / d).mkdir(parents=True, exist_ok=True)
    src = Path(__file__).resolve().parent.parent / "scripts"
    for item in src.iterdir():
        if item.is_file() and item.suffix == ".py" and not item.name.startswith("_"):
            (tmp / "scripts" / item.name).write_text(
                item.read_text(encoding="utf-8"), encoding="utf-8"
            )
    auto_dst = tmp / "scripts" / "automation"
    auto_dst.mkdir(exist_ok=True)
    for item in (src / "automation").iterdir():
        if item.is_file() and item.suffix == ".py":
            (auto_dst / item.name).write_text(
                item.read_text(encoding="utf-8"), encoding="utf-8"
            )
    return tmp, tmp / "curated" / "v0.1" / "pilot_candidates.jsonl"


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )


# A complete record that should score well on all 7 dimensions
_HIGH_QUALITY_RECORD = {
    "id": "01_foundation_reasoning_0001",
    "category": "01_foundation",
    "subcategory": "reasoning",
    "type": "instruction",
    "source": {"name": "test", "license": "MIT"},
    "messages": [
        {
            "role": "user",
            "content": "Explain the concept of encapsulation in object-oriented programming.",
        },
        {
            "role": "assistant",
            "content": (
                "Encapsulation is a fundamental principle of object-oriented programming "
                "that bundles data (attributes) and methods (functions) that operate on "
                "that data into a single unit called a class. It restricts direct access "
                "to an object's internal state, exposing only what is necessary through "
                "controlled public interfaces.\n\n"
                "For example, a BankAccount class might have a private _balance field that "
                "can only be modified through deposit() and withdraw() methods, which "
                "enforce validation rules like preventing negative balances.\n\n"
                "```python\n"
                "class BankAccount:\n"
                "    def __init__(self):\n"
                "        self._balance = 0\n"
                "    def deposit(self, amount):\n"
                "        if amount > 0:\n"
                "            self._balance += amount\n"
                "    def get_balance(self):\n"
                "        return self._balance\n"
                "```\n\n"
                "The key benefits of encapsulation include: reduced complexity through "
                "information hiding, increased maintainability by decoupling interface "
                "from implementation, and improved security by preventing unauthorized "
                "access to internal state."
            ),
        },
    ],
    "language": "en",
    "difficulty": 2,
    "tags": ["oop", "encapsulation", "python"],
    "quality_score": 9,
    "verified": True,
    "notes": "Quality test record — high quality.",
}

# A record that should score poorly (short, boilerplate, no substance)
_LOW_QUALITY_RECORD = {
    "id": "99_generic_trash_9999",
    "category": "01_foundation",
    "subcategory": "instruction-following",
    "type": "instruction",
    "source": {"name": "test", "license": "MIT"},
    "messages": [
        {"role": "user", "content": "What is AI?"},
        {"role": "assistant", "content": "Sure, here is a definition of AI."},
    ],
    "language": "en",
    "difficulty": 0,
    "tags": [],
    "quality_score": 3,
    "verified": False,
    "notes": "Quality test record — low quality.",
}


# ── Basic evaluation ──────────────────────────────────────────────────────


def test_quality_agent_scores_high_quality_record():
    """A well-structured, example-rich record scores >= 7."""
    tmp, dspath = _quality_env()
    _write_jsonl(dspath, [_HIGH_QUALITY_RECORD])
    try:
        agent = __import__("automation.quality_agent", fromlist=["QualityAgent"]).QualityAgent(tmp)
        result = agent.execute()
        assert result.passed, f"Expected PASS, got FAIL: {result.summary}"
        agg = result.data["aggregate"]
        assert agg["mean_score"] >= 7, f"Mean score {agg['mean_score']} < 7"
        assert agg["total_below_threshold"] == 0
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_quality_agent_scores_low_quality_record():
    """A short, boilerplate record scores < 7 and may fail the pipeline."""
    tmp, dspath = _quality_env()
    _write_jsonl(dspath, [_LOW_QUALITY_RECORD])
    try:
        agent = __import__("automation.quality_agent", fromlist=["QualityAgent"]).QualityAgent(tmp)
        result = agent.execute()
        agg = result.data["aggregate"]
        assert agg["mean_score"] < 7, (
            f"Expected low score, got {agg['mean_score']}"
        )
        # With the low record, pipeline-level threshold check may or may not
        # fail depending on mean vs threshold; check the score itself.
        assert agg["min_score_observed"] < 7
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_quality_agent_fails_when_below_threshold():
    """Pipeline FAILS when mean quality_score < min_score."""
    tmp, dspath = _quality_env()
    _write_jsonl(dspath, [_LOW_QUALITY_RECORD])
    try:
        agent = __import__("automation.quality_agent", fromlist=["QualityAgent"]).QualityAgent(
            tmp, config={"min_score": 7}
        )
        result = agent.execute()
        assert not result.passed, "Expected FAIL for low score"
        assert any("mean quality score" in e.lower() for e in result.errors), (
            f"Expected mean-score error, got {result.errors}"
        )
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_quality_agent_returns_per_record_dimensions():
    """Per-record results include dimension breakdown and rationale."""
    tmp, dspath = _quality_env()
    _write_jsonl(dspath, [_HIGH_QUALITY_RECORD])
    try:
        agent = __import__("automation.quality_agent", fromlist=["QualityAgent"]).QualityAgent(tmp)
        result = agent.execute()
        records = result.data["records"]
        assert len(records) == 1
        rec = records[0]
        assert "dimensions" in rec
        assert len(rec["dimensions"]) == 7  # accuracy, completeness, etc.
        assert "flags" in rec
        assert "confidence" in rec
        assert "rationale" in rec
        assert len(rec["rationale"]) == 7
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Dimension evaluation ──────────────────────────────────────────────────


def test_quality_agent_dimension_names():
    """The 7 expected dimension names are all present."""
    tmp, dspath = _quality_env()
    _write_jsonl(dspath, [_HIGH_QUALITY_RECORD])
    try:
        agent = __import__("automation.quality_agent", fromlist=["QualityAgent"]).QualityAgent(tmp)
        result = agent.execute()
        dims = result.data.get("dimension_averages", {})
        expected = {
            "accuracy", "completeness", "technical_correctness",
            "clarity", "usefulness", "originality", "relevance",
        }
        assert set(dims.keys()) == expected, (
            f"Expected {expected}, got {set(dims.keys())}"
        )
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_quality_agent_technical_dimension_detects_code():
    """Records with code blocks score higher on technical_correctness."""
    tmp, dspath = _quality_env()
    _write_jsonl(dspath, [_HIGH_QUALITY_RECORD])  # has code fence
    try:
        agent = __import__("automation.quality_agent", fromlist=["QualityAgent"]).QualityAgent(tmp)
        result = agent.execute()
        dims = result.data["dimension_averages"]
        assert dims.get("technical_correctness", 0) >= 0.7, (
            f"Expected high technical_correctness, got {dims.get('technical_correctness')}"
        )
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_quality_agent_originality_detects_boilerplate():
    """Boilerplate openers lower the originality dimension."""
    tmp, dspath = _quality_env()
    _write_jsonl(dspath, [_LOW_QUALITY_RECORD])  # starts with "Sure, here is..."
    try:
        agent = __import__("automation.quality_agent", fromlist=["QualityAgent"]).QualityAgent(tmp)
        result = agent.execute()
        dims = result.data["dimension_averages"]
        # originality should be low (< 0.7) due to boilerplate
        assert dims.get("originality", 1.0) < 0.7, (
            f"Expected low originality for boilerplate, got {dims.get('originality')}"
        )
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Issue flags ───────────────────────────────────────────────────────────


def test_quality_agent_detects_boilerplate_flag():
    """Records with boilerplate openers get flagged."""
    tmp, dspath = _quality_env()
    _write_jsonl(dspath, [_LOW_QUALITY_RECORD])
    try:
        agent = __import__("automation.quality_agent", fromlist=["QualityAgent"]).QualityAgent(tmp)
        result = agent.execute()
        flags = result.data.get("issue_flags", {})
        assert "boilerplate_opener" in flags, (
            f"Expected boilerplate_opener flag, got {flags}"
        )
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_quality_agent_detects_very_short_flag():
    """Very short answers get flagged."""
    tmp, dspath = _quality_env()
    rec = dict(_LOW_QUALITY_RECORD, id="shorty",
               messages=[{"role": "user", "content": "hi"},
                         {"role": "assistant", "content": "ok."}])
    _write_jsonl(dspath, [rec])
    try:
        agent = __import__("automation.quality_agent", fromlist=["QualityAgent"]).QualityAgent(tmp)
        result = agent.execute()
        flags = result.data.get("issue_flags", {})
        assert "very_short_answer" in flags
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Aggregate statistics ──────────────────────────────────────────────────


def test_quality_agent_aggregate_stats():
    """Aggregate statistics are computed correctly across multiple records."""
    tmp, dspath = _quality_env()
    _write_jsonl(dspath, [_HIGH_QUALITY_RECORD, _LOW_QUALITY_RECORD])
    try:
        agent = __import__("automation.quality_agent", fromlist=["QualityAgent"]).QualityAgent(tmp)
        result = agent.execute()
        agg = result.data["aggregate"]
        assert agg["total_below_threshold"] >= 1
        assert agg["min_score_observed"] < agg["max_score_observed"]
        assert agg["mean_score"] > 0
        # Score distribution should have 2 entries
        assert len(agg["score_distribution"]) >= 2, (
            f"Expected >=2 distinct scores, got {agg['score_distribution']}"
        )
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_quality_agent_output_shape():
    """Agent output data dict has the expected top-level keys."""
    tmp, dspath = _quality_env()
    _write_jsonl(dspath, [_HIGH_QUALITY_RECORD])
    try:
        agent = __import__("automation.quality_agent", fromlist=["QualityAgent"]).QualityAgent(tmp)
        result = agent.execute()
        assert "checked_path" in result.data
        assert "total_records" in result.data
        assert "aggregate" in result.data
        assert "dimension_averages" in result.data
        assert "issue_flags" in result.data
        assert "records" in result.data
        assert "threshold" in result.data
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Parse errors ──────────────────────────────────────────────────────────


def test_quality_agent_reports_parse_errors():
    """Malformed JSON lines are reported, not silently dropped."""
    tmp, dspath = _quality_env()
    dspath.write_text(
        json.dumps(_HIGH_QUALITY_RECORD) + "\n"
        + "not valid json\n"
        + json.dumps(dict(_HIGH_QUALITY_RECORD, id="test_002")) + "\n",
        encoding="utf-8",
    )
    try:
        agent = __import__("automation.quality_agent", fromlist=["QualityAgent"]).QualityAgent(tmp)
        result = agent.execute()
        assert len(result.data.get("parse_errors", [])) == 1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Pipeline integration ──────────────────────────────────────────────────


def test_orchestrator_passes_through_quality():
    """Orchestrator advances through quality evaluation with high-quality data."""
    tmp, dspath = _quality_env()
    _write_jsonl(dspath, [_HIGH_QUALITY_RECORD])
    try:
        orch = __import__("automation.pipeline_orchestrator", fromlist=["PipelineOrchestrator"]).PipelineOrchestrator(
            "test-qual-pass", tmp
        )
        result = orch.run_to_approval()
        assert "quality" in result.agent_results, (
            f"Quality agent not in results: {list(result.agent_results.keys())}"
        )
        quality_result = result.agent_results["quality"]
        assert quality_result.passed, f"Quality agent failed: {quality_result.summary}"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_orchestrator_blocks_on_quality_failure():
    """Orchestrator blocks the pipeline when quality is below threshold."""
    tmp, dspath = _quality_env()
    _write_jsonl(dspath, [_LOW_QUALITY_RECORD])
    try:
        orch = __import__("automation.pipeline_orchestrator", fromlist=["PipelineOrchestrator"]).PipelineOrchestrator(
            "test-qual-block", tmp
        )
        result = orch.run_to_approval()
        assert "quality" in result.agent_results
        quality_result = result.agent_results["quality"]
        assert not quality_result.passed, (
            f"Quality should fail for low-quality data, got: {quality_result.summary}"
        )
        # Pipeline should not reach WAITING_HUMAN_APPROVAL
        assert result.current_state != "WAITING_HUMAN_APPROVAL", (
            f"Pipeline should not advance past quality failure, got {result.current_state}"
        )
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── No-op: no dataset found ───────────────────────────────────────────────


def test_quality_agent_skips_when_no_dataset():
    """Agent returns SKIPPED when no dataset file exists."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "metadata").mkdir()
    (tmp / "curated" / "v0.1").mkdir(parents=True)
    (tmp / "scripts").mkdir()
    try:
        agent = __import__("automation.quality_agent", fromlist=["QualityAgent"]).QualityAgent(tmp)
        result = agent.execute()
        assert result.status.value == "skipped"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ===================================================================
# Revision Agent (v1.3 Production)
# ===================================================================


def _revision_env() -> tuple[Path, Path]:
    """Create temp atlas root with scripts copied for revision agent."""
    tmp = Path(tempfile.mkdtemp())
    for d in ("metadata", "curated/v0.1", "tmp", "scripts"):
        (tmp / d).mkdir(parents=True, exist_ok=True)
    src = Path(__file__).resolve().parent.parent / "scripts"
    for item in src.iterdir():
        if item.is_file() and item.suffix == ".py" and not item.name.startswith("_"):
            (tmp / "scripts" / item.name).write_text(
                item.read_text(encoding="utf-8"), encoding="utf-8"
            )
    auto_dst = tmp / "scripts" / "automation"
    auto_dst.mkdir(exist_ok=True)
    for item in (src / "automation").iterdir():
        if item.is_file() and item.suffix == ".py":
            (auto_dst / item.name).write_text(
                item.read_text(encoding="utf-8"), encoding="utf-8"
            )
    return tmp, tmp / "curated" / "v0.1" / "pilot_candidates.jsonl"


def _write_revision_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )


# A complete, well-written record that should pass without revisions
_REVISION_HIGH_QUALITY = {
    "id": "01_foundation_reasoning_0001", "category": "01_foundation",
    "subcategory": "reasoning", "type": "instruction",
    "source": {"name": "t", "license": "MIT"},
    "messages": [
        {"role": "user", "content": "Explain encapsulation in OOP."},
        {"role": "assistant", "content": (
            "Encapsulation is a fundamental OOP principle that bundles data and methods "
            "into a single class unit. A BankAccount class uses private _balance and "
            "public deposit()/withdraw() methods. Benefits include information hiding, "
            "maintainability, and security.\n\n"
            "```python\nclass BankAccount:\n    def __init__(self):\n        self._balance = 0\n    def deposit(self, amount):\n        if amount > 0:\n            self._balance += amount\n    def get_balance(self):\n        return self._balance\n```"
        )},
    ],
    "language": "en", "difficulty": 2, "tags": ["oop"],
    "quality_score": 9, "verified": True, "notes": "high quality",
}

# A low-quality record that should trigger multiple revision proposals
_REVISION_LOW_QUALITY = {
    "id": "99_generic_trash_9999", "category": "01_foundation",
    "subcategory": "inst", "type": "instruction",
    "source": {"name": "t", "license": "MIT"},
    "messages": [
        {"role": "user", "content": "What is AI?"},
        {"role": "assistant", "content": "Sure, here is a definition of AI."},
    ],
    "language": "en", "difficulty": 0, "tags": [],
    "quality_score": 3, "verified": False, "notes": "low quality",
}

# A record that's technically valid but very short — should trigger completeness proposals
_REVISION_SHORT = {
    "id": "short_record_001", "category": "01_foundation",
    "subcategory": "reasoning", "type": "instruction",
    "source": {"name": "t", "license": "MIT"},
    "messages": [
        {"role": "user", "content": "What is a stack?"},
        {"role": "assistant", "content": "A stack is a LIFO data structure."},
    ],
    "language": "en", "difficulty": 1, "tags": [],
    "quality_score": 5, "verified": False, "notes": "short",
}


# ── Basic revision: high quality ──────────────────────────────────────────


def test_revision_agent_high_quality_passes():
    """A high-quality record generates no revision proposals (generate_all=False)."""
    tmp, dspath = _revision_env()
    _write_revision_jsonl(dspath, [_REVISION_HIGH_QUALITY])
    try:
        agent = __import__("automation.revision_agent", fromlist=["RevisionAgent"]).RevisionAgent(
            tmp, config={"generate_all": False})
        result = agent.execute()
        assert result.passed
        assert result.data["aggregate"]["proposal_count"] == 0
        assert result.data["aggregate"]["passed_count"] == 1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_revision_agent_high_quality_has_pass_status():
    """High-quality records (generate_all=False) have status PASS."""
    tmp, dspath = _revision_env()
    _write_revision_jsonl(dspath, [_REVISION_HIGH_QUALITY])
    try:
        agent = __import__("automation.revision_agent", fromlist=["RevisionAgent"]).RevisionAgent(
            tmp, config={"generate_all": False})
        result = agent.execute()
        rec = result.data["records"][0]
        assert rec["status"] == "PASS"
        assert rec["requires_human_review"] is False
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Basic revision: low quality ───────────────────────────────────────────


def test_revision_agent_low_quality_generates_proposals():
    """A low-quality record generates at least one revision proposal."""
    tmp, dspath = _revision_env()
    _write_revision_jsonl(dspath, [_REVISION_LOW_QUALITY])
    try:
        agent = __import__("automation.revision_agent", fromlist=["RevisionAgent"]).RevisionAgent(tmp)
        result = agent.execute()
        assert result.data["aggregate"]["proposal_count"] == 1
        rec = result.data["records"][0]
        assert rec["status"] == "PROPOSAL_CREATED"
        assert len(rec["revision_proposals"]) >= 1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_revision_agent_low_quality_has_issues():
    """Low-quality records have issues_detected populated."""
    tmp, dspath = _revision_env()
    _write_revision_jsonl(dspath, [_REVISION_LOW_QUALITY])
    try:
        agent = __import__("automation.revision_agent", fromlist=["RevisionAgent"]).RevisionAgent(tmp)
        result = agent.execute()
        rec = result.data["records"][0]
        assert len(rec["issues_detected"]) >= 1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Revision categories ───────────────────────────────────────────────────


def test_revision_agent_completeness_proposal():
    """Short records trigger completeness-area proposals."""
    tmp, dspath = _revision_env()
    _write_revision_jsonl(dspath, [_REVISION_SHORT])
    try:
        agent = __import__("automation.revision_agent", fromlist=["RevisionAgent"]).RevisionAgent(tmp)
        result = agent.execute()
        proposals = result.data["records"][0]["revision_proposals"]
        completeness = [p for p in proposals if p["area"] == "completeness"]
        assert len(completeness) >= 1, (
            f"Expected completeness proposal, got areas: {[p['area'] for p in proposals]}"
        )
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_revision_agent_technical_depth_proposal():
    """Records without technical terms trigger technical_depth proposals."""
    tmp, dspath = _revision_env()
    # A record with very short non-technical answer
    rec = dict(_REVISION_SHORT, id="no_tech",
               messages=[{"role":"user","content":"hi"},{"role":"assistant","content":"ok."}])
    _write_revision_jsonl(dspath, [rec])
    try:
        agent = __import__("automation.revision_agent", fromlist=["RevisionAgent"]).RevisionAgent(tmp)
        result = agent.execute()
        proposals = result.data["records"][0]["revision_proposals"]
        tech = [p for p in proposals if p["area"] == "technical_depth"]
        assert len(tech) >= 1
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_revision_agent_clarity_proposal():
    """Boilerplate openers trigger clarity-area proposals."""
    tmp, dspath = _revision_env()
    _write_revision_jsonl(dspath, [_REVISION_LOW_QUALITY])  # "Sure, here is..."
    try:
        agent = __import__("automation.revision_agent", fromlist=["RevisionAgent"]).RevisionAgent(tmp)
        result = agent.execute()
        proposals = result.data["records"][0]["revision_proposals"]
        clarity = [p for p in proposals if p["area"] == "clarity"]
        # The boilerplate_opener flag should produce a clarity proposal
        assert len(clarity) >= 1, (
            f"Expected clarity proposal, got: {[p['area'] for p in proposals]}"
        )
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Multiple issues → multiple proposals ──────────────────────────────────


def test_revision_agent_multiple_issues_multiple_proposals():
    """A record with multiple issues generates proposals across categories."""
    tmp, dspath = _revision_env()
    # Use a record that will fail on multiple dimensions
    rec = {
        "id": "multi_issue", "category": "01_foundation",
        "subcategory": "inst", "type": "instruction",
        "source": {"name": "t", "license": "MIT"},
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "SURE HERE IS AN ANSWER IN ALLCAPS"},
        ],
        "language": "en", "difficulty": 0, "tags": [],
        "quality_score": 1, "verified": False, "notes": "bad",
    }
    _write_revision_jsonl(dspath, [rec])
    try:
        agent = __import__("automation.revision_agent", fromlist=["RevisionAgent"]).RevisionAgent(tmp)
        result = agent.execute()
        proposals = result.data["records"][0]["revision_proposals"]
        areas = {p["area"] for p in proposals}
        assert len(proposals) >= 2, f"Expected >=2 proposals, got {len(proposals)}"
        # Should have proposals in at least 2 different categories
        assert len(areas) >= 2, f"Expected >=2 areas, got {areas}"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Proposal schema ───────────────────────────────────────────────────────


def test_revision_agent_proposal_schema():
    """Each revision proposal has area, problem, and suggestion."""
    tmp, dspath = _revision_env()
    _write_revision_jsonl(dspath, [_REVISION_LOW_QUALITY])
    try:
        agent = __import__("automation.revision_agent", fromlist=["RevisionAgent"]).RevisionAgent(tmp)
        result = agent.execute()
        rec = result.data["records"][0]
        for p in rec["revision_proposals"]:
            assert "area" in p, f"Missing 'area' in proposal: {p}"
            assert "problem" in p, f"Missing 'problem' in proposal: {p}"
            assert "suggestion" in p, f"Missing 'suggestion' in proposal: {p}"
            assert p["area"] in (
                "completeness", "technical_depth", "clarity", "usefulness"
            ), f"Invalid area: {p['area']}"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_revision_agent_output_schema():
    """RecordRevision output has the expected top-level keys."""
    tmp, dspath = _revision_env()
    _write_revision_jsonl(dspath, [_REVISION_LOW_QUALITY])
    try:
        agent = __import__("automation.revision_agent", fromlist=["RevisionAgent"]).RevisionAgent(tmp)
        result = agent.execute()
        rec = result.data["records"][0]
        for key in ("record_id", "status", "quality_score", "issues_detected",
                     "revision_proposals", "confidence", "requires_human_review"):
            assert key in rec, f"Missing key '{key}' in record output: {list(rec.keys())}"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Missing quality data handling ─────────────────────────────────────────


def test_revision_agent_empty_dataset():
    """Agent handles empty datasets gracefully."""
    tmp, dspath = _revision_env()
    _write_revision_jsonl(dspath, [])
    try:
        agent = __import__("automation.revision_agent", fromlist=["RevisionAgent"]).RevisionAgent(tmp)
        result = agent.execute()
        assert result.status.value == "skipped"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_revision_agent_no_dataset():
    """Agent returns SKIPPED when no dataset exists."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "metadata").mkdir()
    (tmp / "curated" / "v0.1").mkdir(parents=True)
    (tmp / "scripts").mkdir()
    try:
        agent = __import__("automation.revision_agent", fromlist=["RevisionAgent"]).RevisionAgent(tmp)
        result = agent.execute()
        assert result.status.value == "skipped"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Persistence output ────────────────────────────────────────────────────


def test_revision_agent_writes_proposals_to_disk():
    """Revision proposals are written to metadata/pipeline_revisions/."""
    tmp, dspath = _revision_env()
    _write_revision_jsonl(dspath, [_REVISION_LOW_QUALITY])
    try:
        agent = __import__("automation.revision_agent", fromlist=["RevisionAgent"]).RevisionAgent(tmp)
        result = agent.execute(context={"pipeline_id": "test-revision-persist"})
        proposals_path = Path(result.data["proposals_path"])
        assert proposals_path.exists(), f"File not found: {proposals_path}"
        data = json.loads(proposals_path.read_text(encoding="utf-8"))
        assert data["pipeline_id"] == "test-revision-persist"
        assert len(data["records"]) == 1
        assert data["records"][0]["status"] == "PROPOSAL_CREATED"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_revision_agent_proposals_in_metadata_dir():
    """Proposals file is written under metadata/, never curated/."""
    tmp, dspath = _revision_env()
    _write_revision_jsonl(dspath, [_REVISION_LOW_QUALITY])
    try:
        agent = __import__("automation.revision_agent", fromlist=["RevisionAgent"]).RevisionAgent(tmp)
        result = agent.execute(context={"pipeline_id": "test-revision-path"})
        proposals_path = Path(result.data["proposals_path"])
        assert proposals_path.exists(), f"File not found: {proposals_path}"
        # Resolve both paths to handle /private/var -> /var symlink
        tmp_resolved = tmp.resolve()
        rel = proposals_path.resolve().relative_to(tmp_resolved)
        assert rel.parts[0] == "metadata", (
            f"Proposals path outside metadata/: {rel}"
        )
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Pipeline integration ──────────────────────────────────────────────────


def test_orchestrator_passes_through_revision():
    """Orchestrator advances through revision with high-quality data."""
    tmp, dspath = _revision_env()
    _write_revision_jsonl(dspath, [_REVISION_HIGH_QUALITY])
    try:
        orch = __import__("automation.pipeline_orchestrator", fromlist=["PipelineOrchestrator"]).PipelineOrchestrator(
            "test-rev-pass", tmp
        )
        result = orch.run_to_approval()
        assert "revision" in result.agent_results
        rev_result = result.agent_results["revision"]
        assert rev_result.passed, f"Revision agent failed: {rev_result.summary}"
        # Should reach WAITING_HUMAN_APPROVAL (revision is advisory, doesn't block)
        assert result.current_state == "WAITING_HUMAN_APPROVAL", (
            f"Pipeline should reach approval, got {result.current_state}: {result.summary}"
        )
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_orchestrator_advances_with_low_quality_revision():
    """Orchestrator advances even when revision proposes changes."""
    tmp, dspath = _revision_env()
    _write_revision_jsonl(dspath, [_REVISION_LOW_QUALITY])
    try:
        # Lower the quality threshold so the pipeline reaches the revision stage
        orch = __import__("automation.pipeline_orchestrator", fromlist=["PipelineOrchestrator"]).PipelineOrchestrator(
            "test-rev-low", tmp,
            config={"agents": {"quality": {"min_score": 5}}}
        )
        result = orch.run_to_approval()
        assert "revision" in result.agent_results, (
            f"Revision agent not in results: {list(result.agent_results.keys())} "
            f"(state={result.current_state})"
        )
        rev_result = result.agent_results["revision"]
        # Revision passes even with proposals (it's advisory)
        assert rev_result.passed, f"Revision should pass even with proposals: {rev_result.summary}"
        assert rev_result.data["aggregate"]["proposal_count"] >= 1
        # Pipeline still advances through to approval
        assert result.current_state == "WAITING_HUMAN_APPROVAL", (
            f"Pipeline should reach approval despite proposals, got {result.current_state}"
        )
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Immutable directory protection ────────────────────────────────────────


def test_revision_agent_immutable_dirs_protected():
    """Revision agent never writes to curated/, review_queue/, training_views/, raw/."""
    tmp, dspath = _revision_env()
    _write_revision_jsonl(dspath, [_REVISION_LOW_QUALITY])
    try:
        agent = __import__("automation.revision_agent", fromlist=["RevisionAgent"]).RevisionAgent(tmp)
        result = agent.execute()
        proposals_path = Path(result.data["proposals_path"])
        tmp_resolved = tmp.resolve()
        rel = str(proposals_path.resolve().relative_to(tmp_resolved))
        assert rel.startswith("metadata/"), (
            f"Output path outside metadata/: {rel}"
        )
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ===================================================================
# Release Manager (v1.4)
# ===================================================================


def test_release_manager_all_gates_pass():
    """All gates pass → release succeeds."""
    agent_results = {
        "quality": {"status": "passed", "summary": "Quality OK"},
        "provenance": {"status": "passed", "summary": "Provenance OK"},
        "revision": {"status": "passed", "summary": "Revision OK"},
        "validation": {"status": "passed", "summary": "Validation OK"},
    }
    approval_status = {"approved": True, "decision": "approved",
                       "decided_by": "reviewer_alice", "comments": "LGTM"}
    tmp = Path(tempfile.mkdtemp())
    (tmp / "metadata").mkdir(parents=True, exist_ok=True)
    try:
        agent = __import__("automation.release_manager", fromlist=["ReleaseManager"]).ReleaseManager(tmp)
        result = agent.execute(context={
            "pipeline_id": "test-release-pass",
            "agent_results": agent_results,
            "approval_status": approval_status,
        })
        assert result.passed
        assert result.data["status"] == "READY_FOR_RELEASE"
        assert result.data["gates"]["quality"] == "PASS"
        assert result.data["gates"]["human_approval"] == "APPROVED"
        assert len(result.data["failed_gates"]) == 0
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_release_manager_validation_failure_blocks():
    """Validation failure → release blocked."""
    agent_results = {
        "quality": {"status": "passed", "summary": "OK"},
        "provenance": {"status": "passed", "summary": "OK"},
        "revision": {"status": "passed", "summary": "OK"},
        "validation": {"status": "failed", "summary": "FAILED", "errors": ["bad record"]},
    }
    approval_status = {"approved": True, "decision": "approved"}
    tmp = Path(tempfile.mkdtemp())
    (tmp / "metadata").mkdir(parents=True, exist_ok=True)
    try:
        agent = __import__("automation.release_manager", fromlist=["ReleaseManager"]).ReleaseManager(tmp)
        result = agent.execute(context={
            "pipeline_id": "test-release-val-fail",
            "agent_results": agent_results,
            "approval_status": approval_status,
        })
        assert not result.passed
        assert result.data["status"] == "RELEASE_REJECTED"
        assert "validation" in result.data["failed_gates"]
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_release_manager_missing_approval_blocks():
    """Missing human approval → release blocked."""
    agent_results = {
        "quality": {"status": "passed"},
        "provenance": {"status": "passed"},
        "revision": {"status": "passed"},
        "validation": {"status": "passed"},
    }
    approval_status = {"approved": False, "decision": "pending"}
    tmp = Path(tempfile.mkdtemp())
    (tmp / "metadata").mkdir(parents=True, exist_ok=True)
    try:
        agent = __import__("automation.release_manager", fromlist=["ReleaseManager"]).ReleaseManager(tmp)
        result = agent.execute(context={
            "pipeline_id": "test-release-no-approval",
            "agent_results": agent_results,
            "approval_status": approval_status,
        })
        assert not result.passed
        assert result.data["status"] == "RELEASE_REJECTED"
        assert "human_approval" in result.data["failed_gates"]
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_release_manager_human_rejection():
    """Human rejection → release rejected with appropriate next_action."""
    agent_results = {
        "quality": {"status": "passed"},
        "provenance": {"status": "passed"},
        "revision": {"status": "passed"},
        "validation": {"status": "passed"},
    }
    approval_status = {"approved": False, "decision": "denied",
                       "decided_by": "reviewer_bob", "comments": "Not ready"}
    tmp = Path(tempfile.mkdtemp())
    (tmp / "metadata").mkdir(parents=True, exist_ok=True)
    try:
        agent = __import__("automation.release_manager", fromlist=["ReleaseManager"]).ReleaseManager(tmp)
        result = agent.execute(context={
            "pipeline_id": "test-release-denied",
            "agent_results": agent_results,
            "approval_status": approval_status,
        })
        assert not result.passed
        assert result.data["status"] == "RELEASE_REJECTED"
        assert result.data["next_action"] == "RETURN_TO_REVISION_QUEUE"
        assert "human_approval" in result.data["failed_gates"]
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_release_manager_provenance_failure():
    """Provenance failure → release blocked."""
    agent_results = {
        "quality": {"status": "passed"},
        "provenance": {"status": "failed", "summary": "Unresolved records"},
        "revision": {"status": "passed"},
        "validation": {"status": "passed"},
    }
    approval_status = {"approved": True, "decision": "approved"}
    tmp = Path(tempfile.mkdtemp())
    (tmp / "metadata").mkdir(parents=True, exist_ok=True)
    try:
        agent = __import__("automation.release_manager", fromlist=["ReleaseManager"]).ReleaseManager(tmp)
        result = agent.execute(context={
            "pipeline_id": "test-release-prov-fail",
            "agent_results": agent_results,
            "approval_status": approval_status,
        })
        assert not result.passed
        assert "provenance" in result.data["failed_gates"]
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_release_manager_manifest_generation():
    """Release manifest is written to disk with correct metadata."""
    agent_results = {
        "quality": {"status": "passed"},
        "provenance": {"status": "passed"},
        "revision": {"status": "passed"},
        "validation": {"status": "passed"},
    }
    approval_status = {"approved": True, "decision": "approved"}
    tmp = Path(tempfile.mkdtemp())
    (tmp / "metadata" / "releases").mkdir(parents=True, exist_ok=True)
    try:
        agent = __import__("automation.release_manager", fromlist=["ReleaseManager"]).ReleaseManager(tmp)
        result = agent.execute(context={
            "pipeline_id": "test-release-manifest",
            "agent_results": agent_results,
            "approval_status": approval_status,
        })
        manifest_path = Path(result.data["manifest_path"])
        assert manifest_path.exists(), f"Manifest not found: {manifest_path}"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["release_id"] == "test-release-manifest"
        assert manifest["status"] == "READY_FOR_RELEASE"
        assert manifest["gates"]["human_approval"] == "APPROVED"
        assert "checksum" in manifest
        assert "manifest_checksum" in manifest
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_release_manager_report_generation():
    """Release report is written to disk with agent summaries."""
    agent_results = {
        "quality": {"status": "passed", "summary": "All good"},
        "validation": {"status": "failed", "summary": "Bad record", "errors": ["err1"]},
    }
    approval_status = {"approved": True, "decision": "approved"}
    tmp = Path(tempfile.mkdtemp())
    (tmp / "metadata" / "releases").mkdir(parents=True, exist_ok=True)
    try:
        agent = __import__("automation.release_manager", fromlist=["ReleaseManager"]).ReleaseManager(tmp)
        result = agent.execute(context={
            "pipeline_id": "test-release-report",
            "agent_results": agent_results,
            "approval_status": approval_status,
        })
        report_path = Path(result.data["report_path"])
        assert report_path.exists(), f"Report not found: {report_path}"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["release_id"] == "test-release-report"
        assert "agent_summaries" in report
        assert "quality" in report["agent_summaries"]
        assert "approval_details" in report
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_release_manager_checksum_generation():
    """Checksum is deterministic and present in output."""
    agent_results = {
        "quality": {"status": "passed"},
        "provenance": {"status": "passed"},
        "revision": {"status": "passed"},
        "validation": {"status": "passed"},
    }
    approval_status = {"approved": True, "decision": "approved"}
    tmp = Path(tempfile.mkdtemp())
    (tmp / "metadata").mkdir(parents=True, exist_ok=True)
    try:
        agent = __import__("automation.release_manager", fromlist=["ReleaseManager"]).ReleaseManager(tmp)
        result1 = agent.execute(context={
            "pipeline_id": "test-release-checksum",
            "agent_results": agent_results,
            "approval_status": approval_status,
        })
        result2 = agent.execute(context={
            "pipeline_id": "test-release-checksum",
            "agent_results": agent_results,
            "approval_status": approval_status,
        })
        assert result1.data["checksum"] == result2.data["checksum"], (
            "Checksums should be deterministic"
        )
        assert len(result1.data["checksum"]) == 64  # SHA-256 hex
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_release_manager_persistence_recovery():
    """Manifest survives disk load and contains all expected fields."""
    agent_results = {
        "quality": {"status": "passed"},
        "provenance": {"status": "passed"},
        "revision": {"status": "passed"},
        "validation": {"status": "passed"},
    }
    approval_status = {"approved": True, "decision": "approved"}
    tmp = Path(tempfile.mkdtemp())
    (tmp / "metadata" / "releases").mkdir(parents=True, exist_ok=True)
    try:
        agent = __import__("automation.release_manager", fromlist=["ReleaseManager"]).ReleaseManager(tmp)
        agent.execute(context={
            "pipeline_id": "test-release-recover",
            "agent_results": agent_results,
            "approval_status": approval_status,
        })
        # Load from disk
        manifest_path = tmp / "metadata" / "releases" / "test-release-recover_manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["release_id"] == "test-release-recover"
        assert manifest["status"] == "READY_FOR_RELEASE"
        assert manifest["gates"]["validation"] == "PASS"
        assert manifest["gates"]["human_approval"] == "APPROVED"
        assert manifest["generated_by"] == "release_manager.py"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_release_manager_state_machine_integration():
    """State machine integration — READY_FOR_RELEASE → RELEASED."""
    sm = __import__("automation.state_machine", fromlist=["StateMachine", "PipelineState"]).StateMachine
    ps = __import__("automation.state_machine", fromlist=["PipelineState"]).PipelineState
    tmp = Path(tempfile.mkdtemp())
    (tmp / "metadata").mkdir(parents=True, exist_ok=True)
    try:
        machine = sm("test-sm-release", tmp)
        machine.transition_to(ps.QUALITY_CHECK)
        machine.transition_to(ps.PROVENANCE_CHECK)
        machine.transition_to(ps.CONTENT_REVISION)
        machine.transition_to(ps.VALIDATION)
        machine.transition_to(ps.WAITING_HUMAN_APPROVAL)
        machine.transition_to(ps.READY_FOR_RELEASE)
        machine.transition_to(ps.RELEASED)
        assert machine.is_terminal()
        assert machine.current_state == ps.RELEASED
        assert len(machine.transitions) == 7
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_release_manager_immutable_dir_protection():
    """Release artifacts go to metadata/releases/, never curated/."""
    agent_results = {
        "quality": {"status": "passed"},
        "provenance": {"status": "passed"},
        "revision": {"status": "passed"},
        "validation": {"status": "passed"},
    }
    approval_status = {"approved": True, "decision": "approved"}
    tmp = Path(tempfile.mkdtemp())
    (tmp / "metadata" / "releases").mkdir(parents=True, exist_ok=True)
    try:
        agent = __import__("automation.release_manager", fromlist=["ReleaseManager"]).ReleaseManager(tmp)
        result = agent.execute(context={
            "pipeline_id": "test-release-protect",
            "agent_results": agent_results,
            "approval_status": approval_status,
        })
        for key in ("manifest_path", "report_path"):
            p = Path(result.data[key])
            rel = str(p.resolve().relative_to(tmp.resolve()))
            assert rel.startswith("metadata/"), (
                f"{key} outside metadata/: {rel}"
            )
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Pipeline integration ──────────────────────────────────────────────────


def test_orchestrator_full_release_flow():
    """Orchestrator completes full release flow with approval."""
    tmp, dspath = _quality_env()
    _write_jsonl(dspath, [_HIGH_QUALITY_RECORD])
    try:
        orch = __import__("automation.pipeline_orchestrator", fromlist=["PipelineOrchestrator"]).PipelineOrchestrator(
            "test-full-release", tmp
        )
        # Run to approval
        r1 = orch.run_to_approval()
        assert r1.current_state == "WAITING_HUMAN_APPROVAL", (
            f"Expected WAITING_HUMAN_APPROVAL, got {r1.current_state}"
        )
        # Grant approval
        orch.approve_release(
            decided_by="reviewer_alice",
            role=__import__("automation.approval_gate", fromlist=["ApproverRole"]).ApproverRole.REVIEWER,
            comments="All good",
        )
        # Full pipeline should complete
        r2 = orch.run_full_pipeline()
        assert r2.status == __import__("automation.pipeline_orchestrator", fromlist=["PipelineStatus"]).PipelineStatus.COMPLETED, (
            f"Expected COMPLETED, got {r2.status}: {r2.errors}"
        )
        assert orch.state_machine.is_terminal()
        # Release manager should be in results
        assert "release" in r2.agent_results or orch.state_machine.current_state == __import__(
            "automation.state_machine", fromlist=["PipelineState"]
        ).PipelineState.RELEASED
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_orchestrator_release_rejected_without_approval():
    """Orchestrator stays blocked when no human approval exists (ReleaseManager not called)."""
    tmp, dspath = _quality_env()
    _write_jsonl(dspath, [_HIGH_QUALITY_RECORD])
    try:
        orch = __import__("automation.pipeline_orchestrator", fromlist=["PipelineOrchestrator"]).PipelineOrchestrator(
            "test-no-approval-v2", tmp
        )
        r1 = orch.run_to_approval()
        # Without approval, pipeline stays at WAITING_HUMAN_APPROVAL
        assert r1.current_state == "WAITING_HUMAN_APPROVAL", (
            f"Expected WAITING_HUMAN_APPROVAL, got {r1.current_state}"
        )
        assert r1.status == __import__("automation.pipeline_orchestrator", fromlist=["PipelineStatus"]).PipelineStatus.BLOCKED_ON_APPROVAL
        # Run full — still blocked (no approval given)
        r2 = orch.run_full_pipeline()
        assert r2.status == __import__("automation.pipeline_orchestrator", fromlist=["PipelineStatus"]).PipelineStatus.BLOCKED_ON_APPROVAL
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
