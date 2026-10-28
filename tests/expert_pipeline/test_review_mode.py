#!/usr/bin/env python3
"""Tests for the dual-mode review contract (review_mode.py)."""

from __future__ import annotations

import pytest

from expert_pipeline import review_mode as rm


def _criteria(**overrides):
    base = {c: 4 for c in rm.GENERIC_CRITERIA}
    base.update(overrides)
    return base


# --- decision logic -------------------------------------------------------

def test_decide_accepts_high_quality_high_confidence_clean():
    v = rm.decide(_criteria(), quality_score=9, confidence=0.9,
                  risk_flags=[])
    assert v["decision"] == "accept"


def test_decide_rejects_blocking_risk_flag_even_when_excellent():
    v = rm.decide(_criteria(), 10, 1.0, ["security_concern"])
    assert v["decision"] == "reject"
    assert any("blocking_risk_flag" in r for r in v["reasons"])


def test_decide_rejects_weak_criterion():
    v = rm.decide(_criteria(correctness=2), 8, 0.9, [])
    assert v["decision"] == "reject"


def test_decide_rejects_low_overall_score():
    v = rm.decide(_criteria(), 5, 0.95, [])
    assert v["decision"] == "reject"


def test_decide_routes_low_confidence_to_review_not_accept():
    v = rm.decide(_criteria(), 9, 0.4, [])
    assert v["decision"] == "review"
    assert any("confidence" in r for r in v["reasons"])


def test_decide_routes_conflicting_criteria_to_review():
    v = rm.decide(_criteria(correctness=5, completeness=2), 8, 0.9, [])
    # completeness=2 is below the reject floor -> reject wins (explicit rule)
    assert v["decision"] == "reject"
    v2 = rm.decide(_criteria(correctness=5, completeness=3), 8, 0.9, [])
    assert v2["decision"] == "review"
    assert any("spread" in r for r in v2["reasons"])


def test_decide_non_blocking_risk_flag_routes_to_review():
    v = rm.decide(_criteria(), 9, 0.9, ["verbose_style"])
    assert v["decision"] == "review"


def test_uncertainty_never_becomes_accept():
    # borderline score + mediocre confidence + flag => review
    v = rm.decide(_criteria(), 7, 0.69, ["minor_gap"])
    assert v["decision"] == "review"


# --- category rubrics -----------------------------------------------------

def test_agentic_and_aiml_extend_generic_criteria():
    for c in ("task_completion", "tool_use_correctness",
              "observation_consistency", "trajectory_coherence",
              "final_answer_correctness"):
        assert c in rm.criteria_for_category("agentic")
    for c in ("scientific_consistency", "context_preservation",
              "answer_validity", "unsupported_claims"):
        assert c in rm.criteria_for_category("aiml")
    assert set(rm.GENERIC_CRITERIA) <= set(rm.criteria_for_category("math"))
    assert set(rm.GENERIC_CRITERIA) <= set(rm.criteria_for_category("code"))


# --- validation -----------------------------------------------------------

def _valid_ai_result():
    return {
        "record_id": "expert_agentic_000001",
        "review_mode": "ai",
        "decision": "accept",
        "quality_score": 9,
        "confidence": 0.85,
        "criteria": {c: 4 for c in rm.criteria_for_category("agentic")},
        "risk_flags": [],
        "reviewer": {"provider": "openai-compatible", "model": "test-model",
                     "version": rm.REVIEW_VERSION},
        "input_hash": "a" * 64,
        "reviewed_at": "2026-08-23T00:00:00+00:00",
        "review_version": rm.REVIEW_VERSION,
    }


def test_validate_accepts_wellformed_ai_result():
    assert rm.validate_review_result(_valid_ai_result()) == []


@pytest.mark.parametrize("mutate,problem", [
    (lambda r: r.update(decision="pass"), "invalid:decision"),
    (lambda r: r.update(quality_score=11), "invalid:quality_score"),
    (lambda r: r.update(confidence=1.5), "invalid:confidence"),
    (lambda r: r.update(criteria={}), "invalid:criteria"),
    (lambda r: r.update(criteria={"correctness": 9}), "invalid:criteria_values"),
    (lambda r: r.update(reviewer={"provider": "x"}), "invalid:reviewer"),
    (lambda r: r.update(input_hash="short"), "invalid:input_hash"),
    (lambda r: r.update(review_mode="auto"), "invalid:review_mode"),
])
def test_validate_catches_malformed_results(mutate, problem):
    result = _valid_ai_result()
    mutate(result)
    problems = rm.validate_review_result(result)
    assert any(p.startswith(problem) for p in problems)


def test_human_normalized_decision_is_valid():
    legacy = {
        "review_id": "rev_000001",
        "record_id": "expert_arch_000002",
        "reviewer": "human:afnan",
        "verdict": "KEEP",
        "dimensions": {"correctness": 4, "reasoning_depth": 3,
                       "explanation_quality": 4, "provenance_confidence": 4},
        "notes": "",
        "reviewed_at": "2026-08-22T23:49:55+00:00",
        "auto_gate_snapshot": "KEEP",
    }
    norm = rm.normalize_human_decision(legacy)
    assert norm["review_mode"] == "human"
    assert norm["decision"] == "accept"
    assert norm["legacy_verdict"] == "KEEP"
    assert norm["quality_score"] == round((4 + 3 + 4 + 4) / 4 * 2)  # 7.5 -> 8
    assert rm.validate_review_result(norm) == []
    assert rm.normalize_human_decision({**legacy, "verdict": "REJECT"})["decision"] == "reject"
    assert rm.normalize_human_decision({**legacy, "verdict": "REVISE"})["decision"] == "review"


# --- fail-safe ------------------------------------------------------------

def test_reviewer_failure_result_never_accepts():
    rec = {"id": "expert_aiml_000123"}
    res = rm.reviewer_failure_result(rec, RuntimeError("boom"),
                                     now_iso="2026-08-23T00:00:00+00:00")
    assert res["decision"] == "review"
    assert res["decision_source"] == "reviewer_failure"
    assert "reviewer_failure" in res["risk_flags"]
    assert res["confidence"] == 0.0


def test_input_hash_deterministic():
    rec = {"id": "x", "problem": "p"}
    assert rm.input_hash(rec) == rm.input_hash(dict(rec))
    assert len(rm.input_hash(rec)) == 64
