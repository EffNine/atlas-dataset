"""Tests for evaluation_research.state_machine."""
import sys
from pathlib import Path
_sys_path = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_sys_path) not in sys.path:
    sys.path.insert(0, str(_sys_path))

import pytest
from evaluation_research.state_machine import ResearchState, ResearchStateMachine


class TestResearchStateMachine:
    def test_initial_state(self, tmp_path):
        sm = ResearchStateMachine("exp-1", tmp_path)
        assert sm.current_state == ResearchState.BENCHMARK_DISCOVERY
        assert sm.is_at_gate() is False
        assert sm.is_terminal() is False

    def test_linear_progression(self, tmp_path):
        sm = ResearchStateMachine("exp-1", tmp_path)
        assert sm.transition_to(ResearchState.BENCHMARK_ACQUIRED, triggered_by="system")
        assert sm.current_state == ResearchState.BENCHMARK_ACQUIRED

    def test_gate_requires_approval(self, tmp_path):
        sm = ResearchStateMachine("exp-1", tmp_path)
        sm.transition_to(ResearchState.BENCHMARK_ACQUIRED)
        sm.transition_to(ResearchState.LICENSE_VALIDATED)
        assert sm.is_at_gate() is True
        assert sm.transition_to(ResearchState.CONTAMINATION_AUDIT) is False
        assert "human approval" in (sm.error or "")

    def test_approval_unblocks_gate(self, tmp_path):
        sm = ResearchStateMachine("exp-1", tmp_path)
        sm.transition_to(ResearchState.BENCHMARK_ACQUIRED)
        sm.transition_to(ResearchState.LICENSE_VALIDATED)
        assert sm.approve_gate(ResearchState.LICENSE_VALIDATED, approved_by="human_reviewer")
        assert sm.transition_to(ResearchState.CONTAMINATION_AUDIT)

    def test_invalid_transition_rejected(self, tmp_path):
        sm = ResearchStateMachine("exp-1", tmp_path)
        assert sm.transition_to(ResearchState.EVALUATION_COMPLETE) is False

    def test_terminal_states(self, tmp_path):
        sm = ResearchStateMachine("exp-1", tmp_path)
        sm.transition_to(ResearchState.BENCHMARK_ACQUIRED)
        sm.transition_to(ResearchState.LICENSE_VALIDATED)
        sm.approve_gate(ResearchState.LICENSE_VALIDATED, approved_by="human")
        sm.transition_to(ResearchState.CONTAMINATION_AUDIT)
        sm.transition_to(ResearchState.EVAL_SET_FROZEN)
        sm.approve_gate(ResearchState.EVAL_SET_FROZEN, approved_by="human")
        sm.transition_to(ResearchState.POLICY_CALIBRATION)
        sm.transition_to(ResearchState.POLICY_FROZEN)
        sm.approve_gate(ResearchState.POLICY_FROZEN, approved_by="human")
        sm.transition_to(ResearchState.EVALUATION_RUNNING)
        sm.transition_to(ResearchState.EVALUATION_COMPLETE)
        sm.transition_to(ResearchState.STATISTICAL_ANALYSIS)
        sm.transition_to(ResearchState.HUMAN_REVIEW)
        sm.approve_gate(ResearchState.HUMAN_REVIEW, approved_by="human")
        sm.transition_to(ResearchState.CONCLUDED)
        assert sm.is_terminal() is True

    def test_verdict_transitions(self, tmp_path):
        sm = ResearchStateMachine("exp-1", tmp_path)
        assert sm.transition_to(ResearchState.VERDICT_FAIL, verdict="FAIL")
        assert sm.is_terminal() is True

    def test_persistence(self, tmp_path):
        sm = ResearchStateMachine("exp-2", tmp_path)
        sm.transition_to(ResearchState.BENCHMARK_ACQUIRED)
        sm.set_metadata("benchmark_id", "gsm8k")
        sm._persist()
        sm2 = ResearchStateMachine("exp-2", tmp_path)
        assert sm2.load() is True
        assert sm2.current_state == ResearchState.BENCHMARK_ACQUIRED
        assert sm2.get_metadata("benchmark_id") == "gsm8k"

    def test_summary(self, tmp_path):
        sm = ResearchStateMachine("exp-1", tmp_path)
        sm.transition_to(ResearchState.BENCHMARK_ACQUIRED)
        summary = sm.summary()
        assert summary["current_state"] == "BENCHMARK_ACQUIRED"
        assert summary["n_transitions"] == 1
        assert summary["is_terminal"] is False

    def test_cannot_approve_non_gate_state(self, tmp_path):
        sm = ResearchStateMachine("exp-1", tmp_path)
        assert sm.approve_gate(ResearchState.EVALUATION_COMPLETE, approved_by="human") is False

    def test_cannot_approve_wrong_state(self, tmp_path):
        sm = ResearchStateMachine("exp-1", tmp_path)
        assert sm.approve_gate(ResearchState.LICENSE_VALIDATED, approved_by="human") is False
