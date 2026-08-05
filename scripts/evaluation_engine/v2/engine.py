"""engine.py — QEE v2 engine: schema-compatible scoring with verifiable
correctness signals.

Problem addressed
-----------------
QEE v1 scored every record with the same lexical heuristics, so correctness
was never actually verified: math was judged by "has a number", code by "has a
fence", prose by "has keywords". v2 dispatches by answer type:

  * **math**       -> ``MathAnswerEvaluator``  (extraction, normalization,
                      equivalent-expression checking),
  * **code/patch** -> ``CodeAnswerEvaluator``  (syntax, structural similarity,
                      patch alignment, unit tests),
  * **semantic**   -> ``SemanticAnswerEvaluator`` (rubric, anti-stuffing).

The public contract mirrors ``quality_score.py`` for drop-in use by
calibration/report tooling:

  * ``evaluate_record(rec) -> dict`` with ``quality_score`` (int 1..10),
    ``quality_continuous`` (0..1), ``dimensions`` (7 keys, 0..1 each),
    ``rationale``, ``flags``, ``explanation``,
  * ``score_record(rec) -> (int, dict[dim -> 0..1])``.

The seven dimension keys and the default weights are identical to v1 so that
existing schemas and calibration consumers keep working.

Calibration
-----------
A linear calibration ``quality_continuous -> human-aligned continuous`` may be
applied via ``calibration={"enabled": True, "slope": ..., "intercept": ...}``.
See ``calibration.py`` for fitting; the mapping never runs unsupervised without
a fitted, human-validated model (the human approval gate is unchanged).
"""

from __future__ import annotations

import re
from typing import Any

from .code_eval import CodeAnswerEvaluator
from .math_eval import MathAnswerEvaluator
from .semantic_eval import SemanticAnswerEvaluator

# Mirror of the v1 dimension set and weights (schema stability).
WEIGHTS = {
    "accuracy": 0.20,
    "completeness": 0.15,
    "technical_correctness": 0.20,
    "clarity": 0.15,
    "usefulness": 0.15,
    "originality": 0.05,
    "relevance": 0.10,
}

_MATH_HINT_RE = re.compile(
    r"(?i)(\b(solve|compute|evaluate|simplify|integrate|differentiate|derive|"
    r"calculate)\b|\$|\\boxed|\\frac|x\^|\^2|\b\d+\s*[+\-*/^=]\s*\d|"
    r"\b(integral|derivative|equation|polynomial|quadratic)\b|"
    r"\b(sum|product)\s+of\b)"
)
_ANSWER_CODE_RE = re.compile(
    r"(?is)(```|diff --git|^--- a/|^\+\+\+ b/|\bdef\s+[a-z_]\w*\s*\(|"
    r"\bfunction\s+[a-z_]\w*\s*\(|\bclass\s+[A-Z]\w*:)"
)
_QUESTION_CODE_RE = re.compile(
    r"(?i)(\bimplement\s+[a-z_][\w.]*(?:\s*\(|\s+in\b)|"
    r"write (a|the) (function|method|class|code|script|program|module|file)|"
    r"fix (this|the) (bug|code|error)|compile(?: this)?|syntax error|"
    r"stack trace|regression test|pull request|github issue)"
)


def assistant_text(rec: dict) -> str:
    return "\n".join(m["content"] for m in rec.get("messages", []) if m.get("role") == "assistant")


def user_text(rec: dict) -> str:
    return "\n".join(m["content"] for m in rec.get("messages", []) if m.get("role") == "user")


def detect_type(rec: dict, question: str, answer: str) -> str:
    """Classify an answer as math, code, or semantic.

    Code is only chosen when the answer actually contains code/patch artifacts
    (or the question unambiguously requests code). Process questions that merely
    mention debugging stay semantic to avoid mis-scoring them as code.
    """
    cat = str(rec.get("category", ""))
    answer_has_code = bool(_ANSWER_CODE_RE.search(answer or ""))
    question_asks_code = bool(_QUESTION_CODE_RE.search(question or ""))

    if answer_has_code or question_asks_code:
        return "code"

    math_q = _MATH_HINT_RE.search(question or "")
    math_a = _MATH_HINT_RE.search(answer or "")
    if cat.startswith(("05_", "06_")):
        if math_q or math_a:
            return "math"
    if math_q and math_a:
        return "math"
    return "semantic"


class QeeV2Engine:
    """QEE v2 evaluation engine with backward-compatible scoring API."""

    def __init__(self,
                 math_evaluator: MathAnswerEvaluator | None = None,
                 code_evaluator: CodeAnswerEvaluator | None = None,
                 semantic_evaluator: SemanticAnswerEvaluator | None = None,
                 weights: dict[str, float] | None = None,
                 calibration: dict[str, Any] | None = None) -> None:
        self.math = math_evaluator or MathAnswerEvaluator()
        self.code = code_evaluator or CodeAnswerEvaluator()
        self.semantic = semantic_evaluator or SemanticAnswerEvaluator()
        self.weights = dict(weights or WEIGHTS)
        # calibration: {"enabled": bool, "slope": float, "intercept": float}
        self.calibration = calibration or {"enabled": False, "slope": 1.0,
                                           "intercept": 0.0}

    # ------------------------------------------------------------------ #
    # Answer-type dispatch
    # ------------------------------------------------------------------ #
    def _type_result(self, atype: str, question: str, reference: str,
                     answer: str):
        if atype == "math":
            res = self.math.evaluate(question=question, reference=reference,
                                     candidate=answer)
            return atype, res
        if atype == "code":
            res = self.code.evaluate(question=question, reference=reference,
                                     candidate=answer)
            return atype, res
        res = self.semantic.evaluate(question=question, reference=reference,
                                     answer=answer)
        return atype, res

    # ------------------------------------------------------------------ #
    # Dimension assembly (schema-compatible with v1)
    # ------------------------------------------------------------------ #
    def _dimensions(self, atype: str, result, question: str,
                    reference: str, answer: str) -> dict[str, dict]:
        if atype == "math":
            correctness = result.score
            d = {
                "accuracy": correctness,
                "technical_correctness": correctness,
                "completeness": min(1.0, correctness + 0.1
                                    if correctness < 1.0 else 1.0),
                "clarity": 0.8 if result.extracted_candidate else 0.4,
                "usefulness": correctness,
                "originality": 0.7 if result.method != "no_final_answer" else 0.4,
                "relevance": 0.9 if result.extracted_candidate else 0.3,
            }
            return {k: {"score": round(v, 3), "reason": result.reason}
                    for k, v in d.items()}

        if atype == "code":
            correctness = result.score
            struct = result.details.get("structural_similarity",
                                        result.details.get("patch_similarity"))
            d = {
                "accuracy": correctness,
                "technical_correctness": correctness,
                "completeness": min(1.0, correctness * 0.9 + 0.1),
                "clarity": (0.9 if result.method != "syntax" else 0.5),
                "usefulness": correctness,
                "originality": 0.6,
                "relevance": 0.85 if struct is not None else 0.5,
            }
            return {k: {"score": round(v, 3), "reason": result.reason}
                    for k, v in d.items()}

        # semantic
        criteria = result.criteria
        return {
            "accuracy": {"score": round(result.score, 3), "reason": result.reason},
            "completeness": {"score": criteria.get("coverage", {}).get("score", 0.5),
                             "reason": criteria.get("coverage", {}).get("reason", "")},
            "technical_correctness": {"score": criteria.get("specificity", {}).get("score", 0.5),
                                      "reason": criteria.get("specificity", {}).get("reason", "")},
            "clarity": {"score": criteria.get("clarity", {}).get("score", 0.5),
                        "reason": criteria.get("clarity", {}).get("reason", "")},
            "usefulness": {"score": round(min(1.0, result.score * 0.9 + 0.1), 3),
                           "reason": result.reason},
            "originality": {"score": criteria.get("novelty", {}).get("score", 0.5),
                            "reason": criteria.get("novelty", {}).get("reason", "")},
            "relevance": {"score": criteria.get("coverage", {}).get("score", 0.5),
                          "reason": criteria.get("coverage", {}).get("reason", "")},
        }

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def evaluate_record(self, rec: dict, reference: str | None = None) -> dict:
        answer = assistant_text(rec)
        question = user_text(rec)
        ref = reference if reference is not None else (rec.get("canonical_answer") or "")
        atype = detect_type(rec, question, answer)

        _, result = self._type_result(atype, question, ref, answer)

        dim_breakdown = self._dimensions(atype, result, question, ref, answer)
        dims = {k: v["score"] for k, v in dim_breakdown.items()}

        raw_continuous = sum(self.weights[k] * dims[k] for k in self.weights)
        continuous, score = self._map_to_scale(raw_continuous)

        rationale = [
            {"dimension": k, "score": dims[k], "reason": dim_breakdown[k]["reason"]}
            for k in self.weights
        ]

        flags: list[str] = []
        if result.correct is False:
            flags.append("incorrect")
        elif result.correct is None:
            flags.append("unverifiable")
        if result.score < 0.4:
            flags.append("low_correctness")
        if atype == "semantic" and dims["originality"] < 0.6:
            flags.append("possible_keyword_stuffing")

        explanation = (
            f"type={atype}; correctness={result.score:.2f}; "
            f"raw_continuous={raw_continuous:.3f} "
            f"(calibrated={self.calibration.get('enabled', False)}); "
            f"quality_score={score}; flags={flags}"
        )

        return {
            "quality_score": score,
            "quality_continuous": round(continuous, 4),
            "raw_continuous": round(raw_continuous, 4),
            "answer_type": atype,
            "correctness": round(result.score, 4),
            "correct": result.correct,
            "dimensions": {k: round(v, 3) for k, v in dims.items()},
            "rationale": rationale,
            "flags": flags,
            "explanation": explanation,
            "calibration": dict(self.calibration),
            "method": result.method if hasattr(result, "method") else "rubric",
        }

    def score_record(self, rec: dict) -> tuple[int, dict]:
        """Backward-compatible API: (int quality_score, {dim: 0..1})."""
        ev = self.evaluate_record(rec)
        return ev["quality_score"], ev["dimensions"]

    # ------------------------------------------------------------------ #
    # Scale mapping
    # ------------------------------------------------------------------ #
    def _map_to_scale(self, raw: float) -> tuple[float, int]:
        """Map raw continuous quality to the calibrated 1..10 scale.

        Uncalibrated: linear 1..10 convention (identical to v1) so the raw
        signals are directly comparable. Calibrated: fitted affine mapping
        ``raw*slope + intercept`` produced by calibration.py.
        """
        if self.calibration.get("enabled"):
            slope = float(self.calibration.get("slope", 1.0))
            intercept = float(self.calibration.get("intercept", 0.0))
            continuous = max(0.0, min(1.0, raw * slope + intercept))
        else:
            continuous = max(0.0, min(1.0, raw))
        score = int(max(1, min(10, round(1 + continuous * 9))))
        return round(continuous, 4), score


def evaluate_record(rec: dict) -> dict:
    """Module-level convenience using a default QEE v2 engine."""
    return QeeV2Engine().evaluate_record(rec)


def score_record(rec: dict) -> tuple[int, dict]:
    return QeeV2Engine().score_record(rec)
