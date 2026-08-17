#!/usr/bin/env python3
"""
regression.py — Comparison between benchmark runs for the EffNine Benchmark (EB).

Stage 5: Supports comparing two benchmark results, including:
    - Model A vs Model B
    - Trained model vs its baseline
    - Per-capability deltas
    - Stability deltas
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.schema import CapabilityScore, RepeatedRunStats
from ..core.types import Capability


# ---------------------------------------------------------------------------
# Comparison result
# ---------------------------------------------------------------------------


@dataclass
class CapabilityDelta:
    """Per-capability comparison delta."""

    capability: str
    score_a: int
    score_b: int
    delta: int
    percent_delta: float
    stability_a: str | None = None
    stability_b: str | None = None


@dataclass
class RegressionResult:
    """Result of comparing two benchmark runs."""

    run_a_id: str
    run_b_id: str
    model_a: str
    model_b: str
    eb_score_a: int
    eb_score_b: int
    score_delta: int
    percent_delta: float
    capability_deltas: list[CapabilityDelta] = field(default_factory=list)
    stability_delta: str = ""
    overall_stability_a: str = ""
    overall_stability_b: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_a_id": self.run_a_id,
            "run_b_id": self.run_b_id,
            "model_a": self.model_a,
            "model_b": self.model_b,
            "eb_score_a": self.eb_score_a,
            "eb_score_b": self.eb_score_b,
            "score_delta": self.score_delta,
            "percent_delta": self.percent_delta,
            "capability_deltas": [
                {
                    "capability": cd.capability,
                    "score_a": cd.score_a,
                    "score_b": cd.score_b,
                    "delta": cd.delta,
                    "percent_delta": cd.percent_delta,
                    "stability_a": cd.stability_a,
                    "stability_b": cd.stability_b,
                }
                for cd in self.capability_deltas
            ],
            "stability_delta": self.stability_delta,
            "overall_stability_a": self.overall_stability_a,
            "overall_stability_b": self.overall_stability_b,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Stability classification
# ---------------------------------------------------------------------------

STABILITY_THRESHOLDS: dict[str, tuple[float, float]] = {
    "EXCELLENT": (0.0, 1.0),
    "STABLE": (1.0, 2.0),
    "MODERATE": (2.0, 5.0),
    "HIGH_VARIANCE": (5.0, 10.0),
    "UNSTABLE": (10.0, float("inf")),
}


def classify_stability(error_percent: float | None) -> str:
    """
    Classify stability based on error_percent.

    Thresholds:
        error_percent < 1%      → EXCELLENT
        1% <= error_percent < 2% → STABLE
        2% <= error_percent < 5% → MODERATE
        5% <= error_percent < 10% → HIGH_VARIANCE
        error_percent >= 10%     → UNSTABLE
    """
    if error_percent is None:
        return "UNKNOWN"
    for label, (lo, hi) in STABILITY_THRESHOLDS.items():
        if lo <= error_percent < hi:
            return label
    return "UNKNOWN"


def compute_stability_delta(
    stability_a: str,
    stability_b: str,
) -> str:
    """Compute a human-readable stability delta string.

    Parameters are (stability_of_a, stability_of_b).
    Going from worse to better = improved.
    Going from better to worse = regressed.

    Stability order (best to worst): EXCELLENT < STABLE < MODERATE < HIGH_VARIANCE < UNSTABLE
    Lower index = better stability.
    """
    if stability_a == stability_b:
        return f"no change ({stability_a})"
    order = ["EXCELLENT", "STABLE", "MODERATE", "HIGH_VARIANCE", "UNSTABLE"]
    idx_a = order.index(stability_a) if stability_a in order else -1
    idx_b = order.index(stability_b) if stability_b in order else -1
    if idx_b < idx_a:
        return f"improved: {stability_a} → {stability_b}"
    elif idx_b > idx_a:
        return f"regressed: {stability_a} → {stability_b}"
    return f"changed: {stability_a} → {stability_b}"


# ---------------------------------------------------------------------------
# Comparison logic
# ---------------------------------------------------------------------------


def compare_runs(
    run_a: dict[str, Any],
    run_b: dict[str, Any],
) -> RegressionResult:
    """
    Compare two benchmark runs and produce a RegressionResult.

    Each run dict should contain at minimum:
        - run_id
        - model name (under 'model' or 'model_name')
        - overall_eb_score
        - capability_scores (optional)
        - run_stats (optional, for stability)
    """
    model_a = run_a.get("model", {}).get("name", run_a.get("model_name", "unknown"))
    model_b = run_b.get("model", {}).get("name", run_b.get("model_name", "unknown"))
    score_a = run_a.get("overall_eb_score", 0)
    score_b = run_b.get("overall_eb_score", 0)
    score_delta = score_b - score_a
    percent_delta = round((score_b / score_a - 1) * 100, 1) if score_a != 0 else 0.0

    # Capability deltas
    cap_deltas: list[CapabilityDelta] = []
    caps_a = run_a.get("capability_scores", {})
    caps_b = run_b.get("capability_scores", {})
    all_caps = set(caps_a.keys()) | set(caps_b.keys())
    for cap_key in sorted(all_caps):
        cs_a = caps_a.get(cap_key)
        cs_b = caps_b.get(cap_key)
        if cs_a is None or cs_b is None:
            continue
        if isinstance(cs_a, CapabilityScore) and isinstance(cs_b, CapabilityScore):
            delta = cs_b.eb_score - cs_a.eb_score
            pct = round((cs_b.eb_score / cs_a.eb_score - 1) * 100, 1) if cs_a.eb_score != 0 else 0.0
            stab_a = classify_stability(
                cs_a.run_stats.error_percent if cs_a.run_stats else None
            )
            stab_b = classify_stability(
                cs_b.run_stats.error_percent if cs_b.run_stats else None
            )
            cap_deltas.append(CapabilityDelta(
                capability=cap_key,
                score_a=cs_a.eb_score,
                score_b=cs_b.eb_score,
                delta=delta,
                percent_delta=pct,
                stability_a=stab_a,
                stability_b=stab_b,
            ))

    # Overall stability
    stats_a = run_a.get("run_stats")
    stats_b = run_b.get("run_stats")
    stab_a = classify_stability(stats_a.error_percent if stats_a else None)
    stab_b = classify_stability(stats_b.error_percent if stats_b else None)
    stab_delta = compute_stability_delta(stab_a, stab_b)

    notes: list[str] = []
    if score_delta > 0:
        notes.append(f"Model {model_b} scores {score_delta} points higher ({percent_delta:+.1f}%)")
    elif score_delta < 0:
        notes.append(f"Model {model_b} scores {abs(score_delta)} points lower ({percent_delta:+.1f}%)")
    else:
        notes.append("Scores are equal")

    # Check for capability regressions
    for cd in cap_deltas:
        if cd.delta < -10:
            notes.append(f"⚠ {cd.capability} regressed by {cd.delta} points ({cd.percent_delta:+.1f}%)")

    return RegressionResult(
        run_a_id=run_a.get("run_id", "unknown"),
        run_b_id=run_b.get("run_id", "unknown"),
        model_a=model_a,
        model_b=model_b,
        eb_score_a=score_a,
        eb_score_b=score_b,
        score_delta=score_delta,
        percent_delta=percent_delta,
        capability_deltas=cap_deltas,
        stability_delta=stab_delta,
        overall_stability_a=stab_a,
        overall_stability_b=stab_b,
        notes=notes,
    )


def compare_to_baseline(
    run: dict[str, Any],
    baseline_eb_score: int = 1000,
) -> RegressionResult:
    """
    Compare a trained model run against its baseline (EB Score = 1000).

    Parameters
    ----------
    run : dict
        The trained model's benchmark run data.
    baseline_eb_score : int
        The baseline EB Score (default 1000).

    Returns
    -------
    RegressionResult with baseline as run_a and the model as run_b.
    """
    baseline_run = {
        "run_id": run.get("baseline_run_id", "baseline"),
        "model_name": run.get("base_model", {}).get("name", "base"),
        "overall_eb_score": baseline_eb_score,
        "capability_scores": {},
        "run_stats": None,
    }
    return compare_runs(baseline_run, run)
