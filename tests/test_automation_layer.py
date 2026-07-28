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
    """Create a temporary directory that looks like an atlas-dataset root."""
    tmp = Path(tempfile.mkdtemp())
    (tmp / "metadata").mkdir(parents=True, exist_ok=True)
    (tmp / "scripts").mkdir(exist_ok=True)
    return tmp


def _full_transition_sequence(sm: StateMachine) -> list[tuple[PipelineState, bool]]:
    """Run all valid transitions and return (target, success) pairs."""
    results = []
    for target in [
        PipelineState.QUALITY_CHECK,
        PipelineState.PROVENANCE_CHECK,
        PipelineState.CONTENT_REVISION,
        PipelineState.VALIDATION,
        PipelineState.WAITING_HUMAN_APPROVAL,
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
    """Each state transitions to exactly one specific next state."""
    for from_state in STATE_ORDER[:-1]:  # All except RELEASED
        targets = [
            t[1] for t in VALID_TRANSITIONS if t[0] == from_state
        ]
        assert len(targets) == 1, (
            f"{from_state} should have exactly 1 valid target, got {targets}"
        )


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
    """From WAITING_HUMAN_APPROVAL, only RELEASED is allowed."""
    sm = StateMachine("test-pipeline", _make_temp_root())
    sm.transition_to(PipelineState.QUALITY_CHECK)
    sm.transition_to(PipelineState.PROVENANCE_CHECK)
    sm.transition_to(PipelineState.CONTENT_REVISION)
    sm.transition_to(PipelineState.VALIDATION)
    sm.transition_to(PipelineState.WAITING_HUMAN_APPROVAL)
    # Try to go somewhere else
    ok = sm.transition_to(PipelineState.INGESTED)
    assert not ok
    assert sm.error is not None  # Generic invalid transition error


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


def test_is_terminal_only_in_released():
    """is_terminal is True only in RELEASED."""
    sm = StateMachine("test-pipeline", _make_temp_root())
    assert not sm.is_terminal()
    sm.transition_to(PipelineState.QUALITY_CHECK)
    assert not sm.is_terminal()
    _full_transition_sequence(sm)
    assert sm.current_state == PipelineState.RELEASED
    assert sm.is_terminal()


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
    # The state machine allows the FSM transition
    assert sm.can_transition_to(PipelineState.RELEASED)
    # But the ORCHESTRATOR gate blocks it
    gate = __import__("automation.approval_gate", fromlist=["ApprovalGate"]).ApprovalGate(tmp)
    assert gate.is_releasable("test-mandatory") is False
    assert sm.can_transition_to(PipelineState.RELEASED)


def test_orchestrator_blocks_release_without_approval():
    """Pipeline orchestrator blocks release when no human approval exists."""
    tmp = _make_temp_root()
    (tmp / "curated" / "v0.1").mkdir(parents=True, exist_ok=True)
    # Create a minimal dataset so agents don't skip
    pilot = tmp / "curated" / "v0.1" / "pilot_candidates.jsonl"
    rec = {
        "id": "test_001",
        "category": "01_foundation",
        "type": "instruction",
        "source": {"name": "test", "license": "MIT"},
        "messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
        "quality_score": 9,
        "verified": False,
        "verification_status": "pending",
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
        "type": "instruction",
        "source": {"name": "test", "license": "MIT"},
        "messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
        "quality_score": 9,
        "verified": False,
        "verification_status": "pending",
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
        "type": "instruction",
        "source": {"name": "test", "license": "MIT"},
        "messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
        "quality_score": 9,
        "verified": False,
        "verification_status": "pending",
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
    for state in STATE_ORDER[:-1]:  # Exclude RELEASED
        sources = {t[0] for t in VALID_TRANSITIONS}
        assert state in sources, f"{state} missing from VALID_TRANSITIONS"


def test_state_order_is_complete():
    """STATE_ORDER contains all PipelineState values."""
    assert set(STATE_ORDER) == set(PipelineState)


def test_valid_transitions_counts():
    """There are exactly 6 valid transitions (6 edges for 7 nodes)."""
    assert len(VALID_TRANSITIONS) == 6, (
        f"Expected 6 transitions, got {len(VALID_TRANSITIONS)}"
    )
