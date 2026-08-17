#!/usr/bin/env python3
"""
consensus.py — Multi-judge consensus logic for the EffNine Benchmark (EB).

Aggregates results from multiple cloud judges into a single ConsensusResult.
Handles 1, 2, or 3+ judges with robust aggregation strategies.

Tracks judge disagreement separately from model run variance.
"""

from __future__ import annotations

import statistics
from typing import Any

from ..core.schema import ConsensusResult, JudgeResult


class JudgeDisagreementError(Exception):
    """Raised when judge disagreement exceeds threshold."""


def compute_consensus(
    judge_results: list[JudgeResult],
    *,
    max_score: float = 1.0,
    disagreement_threshold_percent: float = 15.0,
) -> ConsensusResult:
    """
    Aggregate multiple judge results into a consensus.

    Aggregation strategy:
      - 1 judge: use that judge's score directly
      - 2 judges: use mean, unless disagreement > threshold → flag
      - 3+ judges: use median (robust to outliers)

    Args:
        judge_results: List of JudgeResult from individual judges.
        max_score: Maximum possible score.
        disagreement_threshold_percent: Stddev/mean * 100 threshold for flagging.

    Returns:
        ConsensusResult with aggregated score and metadata.
    """
    valid_results = [r for r in judge_results if r.status == "success" and r.score is not None]
    failed_results = [r for r in judge_results if r not in valid_results]

    if not valid_results:
        return ConsensusResult(
            final_score=None,
            judge_scores=[],
            selected_judge_count=len(judge_results),
            failed_judge_count=len(judge_results),
            flags=["all_judges_failed"],
            per_judge=[_serialize_judge(r) for r in judge_results],
        )

    scores = [r.score for r in valid_results if r.score is not None]
    n = len(scores)

    # Calculate statistics
    mean_score = sum(scores) / n
    median_score = statistics.median(scores)
    stddev_score = statistics.pstdev(scores) if n > 1 else 0.0

    # Disagreement percentage
    if mean_score != 0:
        disagreement_pct = (stddev_score / abs(mean_score)) * 100
    else:
        disagreement_pct = 0.0

    # Determine disagreement level
    disagreement_level = _classify_disagreement(disagreement_pct, disagreement_threshold_percent)
    flags: list[str] = []

    if disagreement_level in ("high", "critical"):
        flags.append("HIGH_JUDGE_DISAGREEMENT")
    if n == 1:
        flags.append("single_judge")
    if failed_results:
        flags.append(f"{len(failed_results)}_judge(s)_failed")

    # Selection: median for 3+, mean for 2
    if n >= 3:
        final_score = median_score
    else:
        final_score = mean_score

    # Check if disagreement exceeds threshold for 2-judge case
    if n == 2 and disagreement_pct > disagreement_threshold_percent:
        flags.append("disagreement_exceeds_threshold")

    return ConsensusResult(
        final_score=round(final_score, 6),
        max_score=max_score,
        judge_scores=scores,
        mean=round(mean_score, 6),
        median=round(median_score, 6),
        stddev=round(stddev_score, 6),
        disagreement_percent=round(disagreement_pct, 2),
        selected_judge_count=n,
        failed_judge_count=len(failed_results),
        disagreement_level=disagreement_level,
        flags=flags,
        per_judge=[_serialize_judge(r) for r in judge_results],
    )


def _classify_disagreement(pct: float, threshold: float) -> str:
    """Classify disagreement level based on percentage."""
    if pct >= threshold * 2:
        return "critical"
    if pct >= threshold:
        return "high"
    if pct >= threshold * 0.5:
        return "moderate"
    return "low"


def _serialize_judge(result: JudgeResult) -> dict[str, Any]:
    """Serialize a JudgeResult for consensus output."""
    return {
        "model_id": result.model_id,
        "score": result.score,
        "status": result.status,
        "reasoning_summary": result.reasoning_summary,
        "flags": result.flags,
        "error": result.error,
        "latency_s": result.latency_s,
        "confidence": result.confidence,
    }
