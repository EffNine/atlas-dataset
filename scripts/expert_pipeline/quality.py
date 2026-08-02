"""Quality gate scoring for the Atlas Expert pipeline.

Deterministic calibration heuristics (no LLM), mirroring the validated
Phase 0.5 calibration scripts. Scores are 1-5 per dimension; a composite
0-10 quality_score is derived from the dimension mean (x2, clamped).

Dimension scores are computed only from measured record fields.
"""

from __future__ import annotations

import re
from typing import Any

from .constants import (
    GATE_KEEP_MIN_CORRECTNESS,
    GATE_KEEP_MIN_PROVENANCE,
    GATE_REJECT_MAX_CORRECTNESS,
    GATE_REJECT_MAX_PROVENANCE,
    GOLD_MIN,
    SCORER_VERSION,
)

REASON_MARKERS = re.compile(r"\b(because|therefore|so |step|first|then|thus|hence)\b", re.I)
MATH_MARKERS = re.compile(r"\$|\\boxed|\\frac|\\\\begin|\\\\end")


def _len(s: Any) -> int:
    return len((s or "").strip())


def _has_expected_answer(rec: dict) -> bool:
    return bool((rec.get("extraction") or {}).get("has_expected_answer"))


def _problem_source(rec: dict) -> str:
    return (rec.get("extraction") or {}).get("problem_source") or ""


def score_correctness(rec: dict) -> int:
    """Correctness: verification evidence + content substance."""
    solution = (rec.get("solution") or "").strip()
    method = (rec.get("verification") or {}).get("method", "")
    if method == "gold_patch":
        # SWE-bench style: gold patch + test counts
        if not solution:
            return 2
        ex = rec.get("extraction") or {}
        if ex.get("fail_to_pass_count", 0) >= 1 and ex.get("pass_to_pass_count", 0) >= 1:
            return 5
        if ex.get("fail_to_pass_count", 0) >= 1:
            return 4
        return 3
    # OpenMath / generic solution-set style
    if not solution:
        return 1
    if len(solution) < 50:
        return 2
    if len(solution) >= 300 and _has_expected_answer(rec):
        return 4
    return 3


def score_reasoning_depth(rec: dict) -> int:
    method = (rec.get("verification") or {}).get("method", "")
    solution = (rec.get("solution") or "").strip()
    problem = (rec.get("problem") or "").strip()
    if method == "gold_patch":
        files = rec.get("extraction") or {}
        files = files.get("files_changed") or []
        score = 1
        if len(problem) >= 200:
            score += 1
        if len(problem) >= 600:
            score += 1
        if len(solution.splitlines()) >= 10:
            score += 1
        if len(files) >= 2 or len(solution.splitlines()) >= 40:
            score += 1
        return min(5, score)

    lines = [l for l in solution.splitlines() if l.strip()]
    score = 1
    if len(solution) >= 200:
        score += 1
    if len(solution) >= 500:
        score += 1
    if len(lines) >= 6:
        score += 1
    if REASON_MARKERS.search(solution):
        score += 1
    if MATH_MARKERS.search(solution) or len(problem) >= 200:
        score = min(5, score + 1)
    return min(5, score)


def score_explanation_quality(rec: dict) -> int:
    method = (rec.get("verification") or {}).get("method", "")
    solution = (rec.get("solution") or "").strip()
    if method == "gold_patch":
        lines = solution.splitlines()
        if not lines:
            return 1
        hunks = solution.count("@@")
        score = 1
        if len(lines) >= 5:
            score += 1
        if len(lines) >= 15:
            score += 1
        if hunks >= 1:
            score += 1
        if hunks >= 3 or len(lines) >= 40:
            score += 1
        return min(5, score)

    lines = [l for l in solution.splitlines() if l.strip()]
    if not solution:
        return 1
    score = 1
    if len(solution) >= 150:
        score += 1
    if len(solution) >= 400:
        score += 1
    if len(lines) >= 4:
        score += 1
    if MATH_MARKERS.search(solution) or len(lines) >= 8:
        score += 1
    return min(5, score)


def score_provenance_confidence(rec: dict) -> int:
    """Source trust + verification evidence; needs_review caps below 5."""
    v = rec.get("verification") or {}
    if v.get("method") and v.get("evidence"):
        return 4
    if v.get("method"):
        return 3
    return 2


def compute_dimensions(rec: dict) -> dict:
    return {
        "correctness": score_correctness(rec),
        "reasoning_depth": score_reasoning_depth(rec),
        "explanation_quality": score_explanation_quality(rec),
        "provenance_confidence": score_provenance_confidence(rec),
    }


def compute_quality_score(dims: dict) -> int:
    mean = sum(dims.values()) / len(dims)
    return max(0, min(10, round(2 * mean)))


def classify_gate(rec: dict, schema_ok: bool, dims: dict) -> str:
    """Return KEEP / REVIEW / REJECT per quality gate v0.1.

    REJECT: schema/legal failure, or correctness <= 2, or
    provenance_confidence <= 1 (per quality gate 3.2).
    KEEP: correctness >= 3 and provenance_confidence >= 3 and not rejected.
    """
    license_ok = rec.get("license") not in (None, "", "unknown")
    if not schema_ok or not license_ok \
            or dims["correctness"] <= GATE_REJECT_MAX_CORRECTNESS \
            or dims["provenance_confidence"] <= GATE_REJECT_MAX_PROVENANCE:
        return "REJECT"
    if dims["correctness"] >= GATE_KEEP_MIN_CORRECTNESS \
            and dims["provenance_confidence"] >= GATE_KEEP_MIN_PROVENANCE:
        return "KEEP"
    return "REVIEW"


def is_gold(rec: dict, dims: dict) -> bool:
    if dims["correctness"] < GOLD_MIN["correctness"]:
        return False
    if dims["reasoning_depth"] < GOLD_MIN["reasoning_depth"]:
        return False
    if dims["explanation_quality"] < GOLD_MIN["explanation_quality"]:
        return False
    return bool((rec.get("verification") or {}).get("evidence"))


def scorer_version() -> str:
    return SCORER_VERSION
