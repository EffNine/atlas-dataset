#!/usr/bin/env python3
"""Tests for human-vs-AI calibration comparison (calibration.py)."""

from __future__ import annotations

from expert_pipeline import calibration as calib
from expert_pipeline import review_mode as rm


def _human(record_id, verdict, dims=None):
    return {
        "review_id": f"rev_{record_id}",
        "record_id": record_id,
        "reviewer": "human:afnan",
        "verdict": verdict,
        "dimensions": dims or {"correctness": 4, "reasoning_depth": 4,
                               "explanation_quality": 4,
                               "provenance_confidence": 4},
        "notes": "",
        "reviewed_at": "2026-08-23T00:00:00+00:00",
        "auto_gate_snapshot": "KEEP",
    }


def _ai(record_id, decision, quality=9, confidence=0.9):
    return {
        "record_id": record_id,
        "review_mode": "ai",
        "decision": decision,
        "quality_score": quality,
        "confidence": confidence,
        "criteria": {c: 4 for c in rm.GENERIC_CRITERIA},
        "risk_flags": [],
        "reviewer": {"provider": "openai-compatible", "model": "m",
                     "version": rm.REVIEW_VERSION},
        "input_hash": "a" * 64,
        "reviewed_at": "2026-08-23T00:00:00+00:00",
        "review_version": rm.REVIEW_VERSION,
    }


def test_full_agreement():
    humans = [_human("r1", "KEEP"), _human("r2", "REJECT"),
              _human("r3", "REVISE")]
    ais = [_ai("r1", "accept"), _ai("r2", "reject"), _ai("r3", "review")]
    report = calib.compare(humans, ais)
    assert report["matched"] == 3
    assert report["verdict_agreement"]["rate"] == 1.0
    assert report["false_accept_rate"] == 0.0
    assert report["false_reject_rate"] == 0.0
    assert report["disagreement_count"] == 0


def test_false_accept_and_false_reject_detection():
    humans = [_human("r1", "REJECT"), _human("r2", "KEEP"),
              _human("r3", "KEEP")]
    ais = [_ai("r1", "accept"),          # false accept (AI accepted, human rejected)
           _ai("r2", "reject"),          # false reject (AI rejected, human kept)
           _ai("r3", "review")]          # other disagreement
    report = calib.compare(humans, ais)
    assert report["verdict_agreement"]["rate"] == 0.0
    assert len(report["false_accepts"]) == 1
    assert report["false_accepts"][0]["record_id"] == "r1"
    assert len(report["false_rejects"]) == 1
    assert report["false_rejects"][0]["record_id"] == "r2"
    assert report["false_accept_rate"] == 1 / 3
    assert report["false_reject_rate"] == 1 / 3
    assert report["disagreement_count"] == 3


def test_score_delta_and_confidence_distribution():
    humans = [
        _human("r1", "KEEP", dims={"correctness": 4, "reasoning_depth": 4,
                                   "explanation_quality": 4,
                                   "provenance_confidence": 4}),  # overall 8
        _human("r2", "KEEP", dims={"correctness": 3, "reasoning_depth": 3,
                                   "explanation_quality": 3,
                                   "provenance_confidence": 3}),  # overall 6
    ]
    ais = [_ai("r1", "accept", quality=9, confidence=0.8),
           _ai("r2", "accept", quality=7, confidence=0.5)]
    report = calib.compare(humans, ais)
    deltas = report["score_delta"]
    assert deltas["n_pairs"] == 2
    assert deltas["deltas"] == [1, 1]
    assert deltas["mean_ai_minus_human"] == 1.0
    cd = report["confidence_distribution"]
    assert cd["n"] == 2
    assert cd["min"] == 0.5 and cd["max"] == 0.8
    assert cd["below_0.5"] == 0 and cd["gte_0.7"] == 1


def test_unmatched_ids_reported():
    humans = [_human("r1", "KEEP"), _human("h_only", "KEEP")]
    ais = [_ai("r1", "accept"), _ai("ai_only", "accept")]
    report = calib.compare(humans, ais)
    assert report["matched"] == 1
    assert report["human_only"] == ["h_only"]
    assert report["ai_only"] == ["ai_only"]
    assert report["verdict_agreement"]["rate"] == 1.0


def test_empty_inputs_yield_null_rates():
    report = calib.compare([], [])
    assert report["matched"] == 0
    assert report["verdict_agreement"]["rate"] is None
    assert report["false_accept_rate"] is None


def test_append_only_human_decisions_last_wins():
    humans = [_human("r1", "REVISE"), _human("r1", "KEEP")]
    ais = [_ai("r1", "accept")]
    report = calib.compare(humans, ais)
    assert report["verdict_agreement"]["agree"] == 1
