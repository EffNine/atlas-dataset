"""Tests for evaluation_engine.v2.engine — QEE v2 engine schema, determinism,
answer-type dispatch, adversarial integration, and calibration tooling.

Existing evaluation cases (v1 QEE public contract) are preserved: v2 keeps the
same ``evaluate_record`` / ``score_record`` shape and dimension keys. The full
pre-existing suite must still pass (run the repository suite; this file adds
v2 coverage only).
"""

from __future__ import annotations

import pytest

from evaluation_engine.v2.calibration import (
    compute_metrics,
    fit_affine,
)
from evaluation_engine.v2.engine import (
    QeeV2Engine,
    WEIGHTS,
    detect_type,
    evaluate_record,
    score_record,
)


def _rec(category="04_ai_machine_learning", question="What is X?",
         answer="X is a thing.", canonical=None):
    rec = {
        "id": "t_" + category[:2] + "_0",
        "category": category,
        "subcategory": "test",
        "difficulty": 1,
        "canonical_answer": canonical or answer,
        "messages": [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ],
    }
    return rec


MATH_QUESTION = "Simplify (3x^2+2x-5)+(2x^2-4x-1)-(x^2+x+1)."
MATH_ANSWER = "The result is 4x^2-3x-7."
CODE_QUESTION = "Implement a function add(a, b) that returns a + b."
CODE_ANSWER = "def add(a, b):\n    return a + b\n"


class TestTypeDispatch:
    def test_math(self):
        assert detect_type(_rec("06_science_engineering", MATH_QUESTION, MATH_ANSWER),
                           MATH_QUESTION, MATH_ANSWER) == "math"

    def test_code_with_fence(self):
        assert detect_type(_rec("02_software_engineering", CODE_QUESTION, CODE_ANSWER),
                           CODE_QUESTION, CODE_ANSWER) == "code"

    def test_debugging_process_not_code(self):
        q = "What is the first step when debugging?"
        a = "Reproduce the failure deterministically, then isolate the cause."
        assert detect_type(_rec("02_software_engineering", q, a), q, a) == "semantic"

    def test_semantic_default(self):
        q = "Why restate the user's goal before answering?"
        a = "It confirms shared understanding and catches ambiguity."
        assert detect_type(_rec("01_foundation", q, a), q, a) == "semantic"


class TestEngineContract:
    def test_score_record_shape(self):
        score, dims = score_record(_rec())
        assert isinstance(score, int)
        assert 1 <= score <= 10
        assert set(dims) == set(WEIGHTS)
        assert all(0.0 <= v <= 1.0 for v in dims.values())

    def test_evaluate_record_shape(self):
        ev = evaluate_record(_rec())
        for key in ("quality_score", "quality_continuous", "raw_continuous",
                    "answer_type", "correctness", "dimensions", "rationale",
                    "flags", "explanation", "calibration", "method"):
            assert key in ev, key
        assert len(ev["rationale"]) == len(WEIGHTS)

    def test_deterministic(self):
        a = evaluate_record(_rec())
        b = evaluate_record(_rec())
        assert a == b

    def test_read_only(self):
        rec = _rec()
        snapshot = dict(rec)
        evaluate_record(rec)
        assert rec == snapshot

    def test_math_record_correct(self):
        rec = _rec("06_science_engineering", MATH_QUESTION, MATH_ANSWER,
                   canonical="4x^2 - 3x - 7")
        ev = evaluate_record(rec)
        assert ev["answer_type"] == "math"
        assert ev["correct"] is True
        assert ev["correctness"] == 1.0

    def test_math_record_wrong(self):
        rec = _rec("06_science_engineering", MATH_QUESTION,
                   "The result is 4x^2-3x.", canonical="4x^2 - 3x - 7")
        ev = evaluate_record(rec)
        assert ev["answer_type"] == "math"
        assert ev["correct"] is False

    def test_code_record_correct(self):
        rec = _rec("02_software_engineering", CODE_QUESTION, CODE_ANSWER,
                   canonical=CODE_ANSWER)
        ev = evaluate_record(rec)
        assert ev["answer_type"] == "code"
        assert ev["correct"] is True


class TestAdversarialIntegration:
    def test_keyword_stuffed_math_wrong(self):
        rec = _rec(
            "06_science_engineering", MATH_QUESTION,
            "It combines x squared terms like 3x^2 and 2x^2 and -x^2, and "
            "linear terms like 2x, -4x, -x.",
            canonical="4x^2 - 3x - 7")
        ev = evaluate_record(rec)
        assert ev["correct"] is False
        assert ev["correctness"] < 0.5

    def test_keyword_stuffed_semantic_flagged(self):
        q = "RAG embeddings retrieval"
        rec = _rec(
            "04_ai_machine_learning", q,
            "RAG embeddings. Embeddings. RAG retrieval. embeddings retrieval "
            "rag embeddings and retrieval.",
            canonical="Dense vectors; similarity decides.")
        ev = evaluate_record(rec)
        assert ev["answer_type"] == "semantic"
        assert "possible_keyword_stuffing" in ev["flags"]

    def test_different_wording_math(self):
        rec = _rec("06_science_engineering", MATH_QUESTION,
                   "four x squared minus three x minus seven",
                   canonical="4x^2 - 3x - 7")
        assert evaluate_record(rec)["correct"] is True


class TestCalibrationTools:
    def test_compute_metrics(self):
        m = compute_metrics([7, 7, 8], [6, 7, 8])
        assert m["n"] == 3
        assert m["mean_bias"] == pytest.approx(0.333, abs=0.001)
        assert m["within1_agree"] == 1.0
        # record 1: auto=7, human=6 -> false approval (auto >= 7, human < 7)
        assert m["false_approvals"] == 1
        assert m["false_rejections"] == 0

    def test_fit_affine(self):
        xs = [0.0, 0.5, 1.0]
        ys = [0.0, 0.5, 1.0]
        slope, intercept = fit_affine(xs, ys)
        assert slope == pytest.approx(1.0, abs=1e-6)
        assert intercept == pytest.approx(0.0, abs=1e-6)

    def test_fit_affine_constant(self):
        # Degenerate input must not divide by zero.
        slope, intercept = fit_affine([0.5, 0.5, 0.5], [0.2, 0.3, 0.4])
        assert (slope, intercept) == (1.0, 0.0)

    def test_engine_calibrated_mapping(self):
        eng = QeeV2Engine(calibration={"enabled": True, "slope": 1.0, "intercept": 0.0})
        rec = _rec()
        score, dims = eng.score_record(rec)
        assert 1 <= score <= 10
        assert set(dims) == set(WEIGHTS)
