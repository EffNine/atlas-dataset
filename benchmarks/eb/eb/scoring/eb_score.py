#!/usr/bin/env python3
"""
eb_score.py — EB Score computation for the EffNine Benchmark (EB).

Stage 5: Computes normalized EB Score from raw benchmark performance
relative to a base-model baseline. Does NOT re-run evaluation.

Formula:
    EB Score = round(1000 * model_raw_mean / base_raw_mean)

Improvement:
    improvement_percent = (model_raw_mean / base_raw_mean - 1) * 100

Handles base_raw_mean == 0 safely (raises ValueError).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.schema import CapabilityScore, RepeatedRunStats
from ..core.types import Capability


# ---------------------------------------------------------------------------
# Scoring version — part of baseline compatibility
# ---------------------------------------------------------------------------

SCORING_VERSION = "eb-score-v1"


# ---------------------------------------------------------------------------
# EB Score result
# ---------------------------------------------------------------------------


@dataclass
class EbScoreResult:
    """Result of EB Score computation for a single model run."""

    eb_score: int
    base_raw_mean: float
    model_raw_mean: float
    improvement_percent: float
    baseline_run_id: str | None
    benchmark_version: str
    task_set_version: str
    scoring_version: str = SCORING_VERSION
    model_name: str = ""
    base_model_name: str = ""
    run_stats: RepeatedRunStats | None = None
    capability_scores: dict[str, CapabilityScore] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class EbScoreError:
    """Structured error when EB Score cannot be computed."""

    reason: str
    detail: str
    base_raw_mean: float | None = None
    model_raw_mean: float | None = None


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_eb_score(
    model_raw_mean: float,
    base_raw_mean: float,
    *,
    baseline_run_id: str | None = None,
    benchmark_version: str = "",
    task_set_version: str = "",
    model_name: str = "",
    base_model_name: str = "",
    run_stats: RepeatedRunStats | None = None,
    capability_scores: dict[str, CapabilityScore] | None = None,
) -> EbScoreResult | EbScoreError:
    """
    Compute the normalized EB Score.

    Parameters
    ----------
    model_raw_mean : float
        Overall raw mean performance of the trained model.
    base_raw_mean : float
        Overall raw mean performance of the base model baseline.
    baseline_run_id : str, optional
        ID of the baseline run.
    benchmark_version : str
        Benchmark version string.
    task_set_version : str
        Task set version string.
    model_name : str
        Name of the trained model.
    base_model_name : str
        Name of the base model.
    run_stats : RepeatedRunStats, optional
        Repeated-run statistics for the model.
    capability_scores : dict, optional
        Per-capability EB scores.

    Returns
    -------
    EbScoreResult on success, EbScoreError on failure.
    """
    if base_raw_mean == 0:
        return EbScoreError(
            reason="zero_baseline",
            detail="Base model raw mean is zero; cannot normalize EB Score.",
            base_raw_mean=0.0,
            model_raw_mean=model_raw_mean,
        )

    if model_raw_mean == 0:
        # Zero model performance is a valid result, not an error
        return EbScoreResult(
            eb_score=0,
            base_raw_mean=base_raw_mean,
            model_raw_mean=0.0,
            improvement_percent=-100.0,
            baseline_run_id=baseline_run_id,
            benchmark_version=benchmark_version,
            task_set_version=task_set_version,
            model_name=model_name,
            base_model_name=base_model_name,
            run_stats=run_stats,
            capability_scores=capability_scores or {},
        )

    eb_score = round(1000 * model_raw_mean / base_raw_mean)
    improvement_percent = (model_raw_mean / base_raw_mean - 1) * 100

    return EbScoreResult(
        eb_score=eb_score,
        base_raw_mean=base_raw_mean,
        model_raw_mean=model_raw_mean,
        improvement_percent=round(improvement_percent, 1),
        baseline_run_id=baseline_run_id,
        benchmark_version=benchmark_version,
        task_set_version=task_set_version,
        model_name=model_name,
        base_model_name=base_model_name,
        run_stats=run_stats,
        capability_scores=capability_scores or {},
    )


def compute_capability_eb_scores(
    capability_raw_means: dict[str, float],
    base_raw_means: dict[str, float],
    task_counts: dict[str, int] | None = None,
    run_stats_map: dict[str, RepeatedRunStats] | None = None,
) -> dict[str, CapabilityScore]:
    """
    Compute per-capability EB scores normalized against base model.

    Each capability is normalized independently:
        cap_eb_score = round(1000 * model_raw_mean / base_raw_mean)

    Parameters
    ----------
    capability_raw_means : dict
        Mapping of capability key → model raw mean.
    base_raw_means : dict
        Mapping of capability key → base model raw mean.
    task_counts : dict, optional
        Mapping of capability key → task count.
    run_stats_map : dict, optional
        Mapping of capability key → RepeatedRunStats.

    Returns
    -------
    dict mapping capability key → CapabilityScore
    """
    task_counts = task_counts or {}
    run_stats_map = run_stats_map or {}
    result: dict[str, CapabilityScore] = {}

    for cap_key, model_mean in capability_raw_means.items():
        base_mean = base_raw_means.get(cap_key)
        if base_mean is None or base_mean == 0:
            continue
        eb = round(1000 * model_mean / base_mean)
        if eb <= 0:
            continue
        cs = CapabilityScore(
            capability=Capability(cap_key),
            eb_score=eb,
            raw_mean=model_mean,
            task_count=task_counts.get(cap_key, 0),
            run_stats=run_stats_map.get(cap_key),
        )
        result[cap_key] = cs

    return result


def compute_improvement_percent(model_raw_mean: float, base_raw_mean: float) -> float:
    """Compute improvement percentage relative to baseline."""
    if base_raw_mean == 0:
        return 0.0
    return round((model_raw_mean / base_raw_mean - 1) * 100, 1)
