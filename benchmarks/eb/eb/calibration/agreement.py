#!/usr/bin/env python3
"""
agreement.py — Judge agreement analysis for LONG calibration fixtures.

Measures where reference labels exist:
  - absolute score error (|judge_score - reference_score|)
  - mean absolute error (MAE) across comparable samples
  - categorical agreement (reference_category vs judge_category)
  - dimension-level agreement (per-dimension MAE and agreement rate)
  - overall agreement

Reference hierarchy:
  deterministic_reference (authoritative)
      |
      v
  expert_review_required / provisional
      |
      v
  judge_output (recorded, not ground truth)

Missing reference: comparison_status = "NOT_AVAILABLE"
Do NOT fabricate human/expert labels.

LOW_AGREEMENT threshold: |judge_score - reference_score| > 0.3
This is a diagnostic flag only — it never modifies raw_task_score,
long_outcome, or any benchmark SCORE.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .fixtures import CalibrationFixture, CalibrationFixtureSet, LONG_DIMENSIONS


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOW_AGREEMENT_THRESHOLD = 0.3
"""Substantial disagreement threshold. If |judge_score - reference_score| > 0.3,
the comparison is flagged as LOW_AGREEMENT. Diagnostic only — does not modify
raw_task_score, long_outcome, or benchmark SCORE."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DimensionAgreement:
    """Agreement analysis for a single dimension across fixtures."""

    dimension: str
    reference_scores: list[float] = field(default_factory=list)
    judge_scores: list[float] = field(default_factory=list)
    absolute_errors: list[float] = field(default_factory=list)
    categorical_agreements: list[bool] = field(default_factory=list)

    @property
    def sample_count(self) -> int:
        return len(self.reference_scores)

    @property
    def mae(self) -> float | None:
        if not self.absolute_errors:
            return None
        return sum(self.absolute_errors) / len(self.absolute_errors)

    @property
    def agreement_count(self) -> int:
        return sum(1 for a in self.categorical_agreements if a)

    @property
    def agreement_rate(self) -> float | None:
        if not self.categorical_agreements:
            return None
        return sum(1 for a in self.categorical_agreements if a) / len(self.categorical_agreements)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "sample_count": self.sample_count,
            "mae": round(self.mae, 4) if self.mae is not None else None,
            "agreement_count": self.agreement_count,
            "agreement_rate": round(self.agreement_rate, 4) if self.agreement_rate is not None else None,
        }


@dataclass
class FixtureAgreement:
    """Agreement analysis for a single calibration fixture."""

    fixture_id: str
    fixture_hash: str
    outcome: str
    judge_eligible: bool
    reference_available: bool
    reference_status: str
    judge_quality: float | None
    reference_quality: float | None
    absolute_error: float | None
    low_agreement: bool
    flags: list[str] = field(default_factory=list)
    dimension_agreements: dict[str, dict[str, Any]] = field(default_factory=dict)
    comparison_status: str = "AVAILABLE"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "fixture_id": self.fixture_id,
            "fixture_hash": self.fixture_hash,
            "outcome": self.outcome,
            "judge_eligible": self.judge_eligible,
            "reference_available": self.reference_available,
            "reference_status": self.reference_status,
            "judge_quality": self.judge_quality,
            "reference_quality": self.reference_quality,
            "absolute_error": round(self.absolute_error, 4) if self.absolute_error is not None else None,
            "low_agreement": self.low_agreement,
            "flags": self.flags,
            "dimension_agreements": self.dimension_agreements,
            "comparison_status": self.comparison_status,
            "metadata": self.metadata,
        }
        return d


@dataclass
class CalibrationReport:
    """Full calibration report with overall, per-dimension, and per-fixture analysis."""

    calibration_version: str
    rubric_version: str
    judge_model: str | None
    provider: str | None
    model_version: str | None
    prompt_version: str | None
    temperature: float
    evaluation_timestamp: str
    live_judge: str  # "AVAILABLE" or "NOT_AVAILABLE"
    reference_samples: int
    judge_samples: int
    comparable_samples: int
    overall_mae: float | None
    overall_agreement_rate: float | None
    low_agreement_count: int
    dimension_analysis: dict[str, DimensionAgreement] = field(default_factory=dict)
    fixture_analysis: dict[str, FixtureAgreement] = field(default_factory=dict)
    report_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "calibration_version": self.calibration_version,
            "rubric_version": self.rubric_version,
            "judge_model": self.judge_model,
            "provider": self.provider,
            "model_version": self.model_version,
            "prompt_version": self.prompt_version,
            "temperature": self.temperature,
            "evaluation_timestamp": self.evaluation_timestamp,
            "live_judge": self.live_judge,
            "overall": {
                "reference_samples": self.reference_samples,
                "judge_samples": self.judge_samples,
                "comparable_samples": self.comparable_samples,
                "mae": round(self.overall_mae, 4) if self.overall_mae is not None else None,
                "agreement_rate": round(self.overall_agreement_rate, 4) if self.overall_agreement_rate is not None else None,
                "low_agreement_count": self.low_agreement_count,
            },
            "dimension_analysis": {k: v.to_dict() for k, v in self.dimension_analysis.items()},
            "fixture_analysis": {k: v.to_dict() for k, v in self.fixture_analysis.items()},
            "report_hash": self.report_hash,
        }

    def sha256(self) -> str:
        payload = self.to_dict()
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Agreement Analysis Engine
# ---------------------------------------------------------------------------

class AgreementAnalyzer:
    """
    Computes agreement metrics between judge outputs and reference labels
    for LONG calibration fixtures.

    Reference hierarchy (authoritative → supplemental):
      1. deterministic_reference — derived from deterministic gates
      2. expert_review_required — needs human/expert label
      3. provisional — temporary reference

    Missing reference → comparison_status = "NOT_AVAILABLE"
    Does NOT fabricate labels.
    """

    def __init__(
        self,
        fixture_set: CalibrationFixtureSet | None = None,
        calibration_version: str = "v1.0",
        rubric_version: str = "8E.1",
        judge_model: str | None = None,
        provider: str | None = None,
        model_version: str | None = None,
        prompt_version: str | None = None,
        temperature: float = 0.0,
        live_judge: str = "NOT_AVAILABLE",
    ):
        self._fixtures = fixture_set or CalibrationFixtureSet()
        self._calibration_version = calibration_version
        self._rubric_version = rubric_version
        self._judge_model = judge_model
        self._provider = provider
        self._model_version = model_version
        self._prompt_version = prompt_version
        self._temperature = temperature
        self._live_judge = live_judge
        self._judge_outputs: dict[str, dict[str, Any]] = {}
        self._dimension_stats: dict[str, DimensionAgreement] = {
            dim: DimensionAgreement(dimension=dim) for dim in LONG_DIMENSIONS
        }
        self._fixture_stats: dict[str, FixtureAgreement] = {}

    # -----------------------------------------------------------------------
    # Judge output recording
    # -----------------------------------------------------------------------

    def record_judge_output(
        self,
        fixture_id: str,
        score: float,
        criterion_scores: dict[str, float] | None = None,
        confidence: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Record a judge output for a fixture. Does NOT modify raw_task_score
        or long_outcome. This is purely diagnostic metadata.

        Args:
            fixture_id: The calibration fixture ID.
            score: Judge-computed quality score [0.0, 1.0].
            criterion_scores: Per-dimension scores from the judge.
            confidence: Judge confidence if available, else None.
            metadata: Additional metadata (provider, model, etc.).
        """
        cs = criterion_scores or {}
        self._judge_outputs[fixture_id] = {
            "score": score,
            "criterion_scores": cs,
            "confidence": confidence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }

    # -----------------------------------------------------------------------
    # Analysis
    # -----------------------------------------------------------------------

    def analyze(self) -> CalibrationReport:
        """
        Run full agreement analysis across all fixtures.

        Returns:
            CalibrationReport with overall, per-dimension, and per-fixture results.
        """
        self._fixture_stats = {}
        self._dimension_stats = {
            dim: DimensionAgreement(dimension=dim) for dim in LONG_DIMENSIONS
        }

        all_absolute_errors: list[float] = []
        all_categorical_agreements: list[bool] = []
        reference_count = 0
        judge_count = 0
        comparable_count = 0
        low_agreement_count = 0

        for fid, fixture in self._fixtures.fixtures.items():
            report = self._analyze_fixture(fid, fixture)
            self._fixture_stats[fid] = report
            self._update_dimension_stats(report)

            # Aggregate overall metrics
            if report.reference_available:
                reference_count += 1
            if report.judge_quality is not None:
                judge_count += 1
            if report.comparison_status == "AVAILABLE":
                comparable_count += 1
                if report.absolute_error is not None:
                    all_absolute_errors.append(report.absolute_error)
                if report.judge_quality is not None and report.reference_quality is not None:
                    ref_cat = self._score_to_category(report.reference_quality)
                    judge_cat = self._score_to_category(report.judge_quality)
                    all_categorical_agreements.append(ref_cat == judge_cat)
            if report.low_agreement:
                low_agreement_count += 1

        overall_mae = (
            sum(all_absolute_errors) / len(all_absolute_errors)
            if all_absolute_errors else None
        )
        overall_agreement_rate = (
            sum(1 for a in all_categorical_agreements if a) / len(all_categorical_agreements)
            if all_categorical_agreements else None
        )

        report = CalibrationReport(
            calibration_version=self._calibration_version,
            rubric_version=self._rubric_version,
            judge_model=self._judge_model,
            provider=self._provider,
            model_version=self._model_version,
            prompt_version=self._prompt_version,
            temperature=self._temperature,
            evaluation_timestamp=datetime.now(timezone.utc).isoformat(),
            live_judge=self._live_judge,
            reference_samples=reference_count,
            judge_samples=judge_count,
            comparable_samples=comparable_count,
            overall_mae=overall_mae,
            overall_agreement_rate=overall_agreement_rate,
            low_agreement_count=low_agreement_count,
            dimension_analysis=self._dimension_stats,
            fixture_analysis=self._fixture_stats,
        )
        report.report_hash = report.sha256()
        return report

    def _analyze_fixture(self, fixture_id: str, fixture: CalibrationFixture) -> FixtureAgreement:
        """Analyze agreement for a single fixture."""
        judge_out = self._judge_outputs.get(fixture_id)
        judge_quality = judge_out["score"] if judge_out else None
        judge_cs = judge_out["criterion_scores"] if judge_out else {}
        confidence = judge_out["confidence"] if judge_out else None

        # Determine reference quality from dimension references
        ref_values = [
            ref.value for ref in fixture.dimension_references.values()
            if ref.value is not None
        ]
        reference_quality = (sum(ref_values) / len(ref_values)) if ref_values else None
        reference_available = len(ref_values) > 0

        # Compute absolute error
        absolute_error: float | None = None
        if judge_quality is not None and reference_quality is not None:
            absolute_error = abs(judge_quality - reference_quality)

        # LOW_AGREEMENT flag
        low_agreement = False
        flags: list[str] = []
        if absolute_error is not None and absolute_error > LOW_AGREEMENT_THRESHOLD:
            low_agreement = True
            flags.append("LOW_AGREEMENT")

        # Dimension-level analysis
        dimension_agreements: dict[str, dict[str, Any]] = {}
        for dim in LONG_DIMENSIONS:
            ref = fixture.dimension_references.get(dim)
            judge_dim_score = judge_cs.get(dim) if judge_cs else None

            entry: dict[str, Any] = {
                "reference_score": ref.value if ref else None,
                "judge_score": judge_dim_score,
                "absolute_error": None,
                "comparison_status": "NOT_AVAILABLE",
                "confidence": confidence,
            }

            if ref is not None and ref.value is not None and judge_dim_score is not None:
                entry["absolute_error"] = round(abs(judge_dim_score - ref.value), 4)
                entry["comparison_status"] = "AVAILABLE"
                if abs(judge_dim_score - ref.value) > LOW_AGREEMENT_THRESHOLD:
                    entry["flags"] = ["LOW_AGREEMENT"]
                else:
                    entry["flags"] = []
            elif ref is None:
                entry["flags"] = ["NO_REFERENCE"]
            else:
                entry["flags"] = ["NO_JUDGE_SCORE"]

            dimension_agreements[dim] = entry

        # Comparison status
        comparison_status = "AVAILABLE"
        if not reference_available:
            comparison_status = "NOT_AVAILABLE"
        elif judge_quality is None:
            comparison_status = "NO_JUDGE_OUTPUT"

        # Metadata preservation
        metadata: dict[str, Any] = {
            "fixture_id": fixture_id,
            "fixture_hash": fixture.fixture_hash,
            "calibration_version": self._calibration_version,
            "rubric_version": self._rubric_version,
            "judge_model": self._judge_model,
            "provider": self._provider,
            "model_version": self._model_version,
            "prompt_version": self._prompt_version,
            "temperature": self._temperature,
            "evaluation_timestamp": datetime.now(timezone.utc).isoformat(),
            "judge_confidence": confidence,
        }

        return FixtureAgreement(
            fixture_id=fixture_id,
            fixture_hash=fixture.fixture_hash,
            outcome=fixture.expected_outcome,
            judge_eligible=fixture.judge_eligible,
            reference_available=reference_available,
            reference_status=fixture.reference_status,
            judge_quality=judge_quality,
            reference_quality=reference_quality,
            absolute_error=absolute_error,
            low_agreement=low_agreement,
            flags=flags,
            dimension_agreements=dimension_agreements,
            comparison_status=comparison_status,
            metadata=metadata,
        )

    def _update_dimension_stats(self, fixture_report: FixtureAgreement) -> None:
        """Update dimension-level statistics from a fixture report."""
        for dim, dim_data in fixture_report.dimension_agreements.items():
            dim_stat = self._dimension_stats.get(dim)
            if dim_stat is None:
                continue
            ref_score = dim_data.get("reference_score")
            judge_score = dim_data.get("judge_score")
            abs_err = dim_data.get("absolute_error")

            if ref_score is not None and judge_score is not None:
                dim_stat.reference_scores.append(ref_score)
                dim_stat.judge_scores.append(judge_score)
                if abs_err is not None:
                    dim_stat.absolute_errors.append(abs_err)
                ref_cat = self._score_to_category(ref_score)
                judge_cat = self._score_to_category(judge_score)
                dim_stat.categorical_agreements.append(ref_cat == judge_cat)

    def _score_to_category(self, score: float) -> str:
        """Map a score to a categorical quality label."""
        if score >= 0.8:
            return "high"
        if score >= 0.5:
            return "medium"
        if score > 0.0:
            return "low"
        return "none"

    # -----------------------------------------------------------------------
    # Categorical agreement
    # -----------------------------------------------------------------------

    def categorical_agreement(
        self,
        reference_score: float | None,
        judge_score: float | None,
    ) -> bool | None:
        """
        Compare two scores as categorical labels.

        Returns True if categories match, False if they differ,
        None if either score is missing.
        """
        if reference_score is None or judge_score is None:
            return None
        return self._score_to_category(reference_score) == self._score_to_category(judge_score)

    # -----------------------------------------------------------------------
    # MAE computation
    # -----------------------------------------------------------------------

    @staticmethod
    def mean_absolute_error(errors: list[float]) -> float | None:
        """Compute MAE from a list of absolute errors."""
        if not errors:
            return None
        return sum(errors) / len(errors)

    @staticmethod
    def absolute_error(judge: float, reference: float) -> float:
        """Compute absolute error between judge and reference score."""
        return abs(judge - reference)

    # -----------------------------------------------------------------------
    # Live judge status
    # -----------------------------------------------------------------------

    @property
    def live_judge_status(self) -> str:
        return self._live_judge

    def set_live_judge(self, available: bool, model: str | None = None, provider: str | None = None) -> None:
        """Update live judge availability status."""
        self._live_judge = "AVAILABLE" if available else "NOT_AVAILABLE"
        if model:
            self._judge_model = model
        if provider:
            self._provider = provider


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

def compute_agreement(
    fixture_set: CalibrationFixtureSet | None = None,
    judge_outputs: dict[str, dict[str, Any]] | None = None,
    calibration_version: str = "v1.0",
    rubric_version: str = "8E.1",
    judge_model: str | None = None,
    provider: str | None = None,
    model_version: str | None = None,
    prompt_version: str | None = None,
    temperature: float = 0.0,
    live_judge: str = "NOT_AVAILABLE",
) -> CalibrationReport:
    """
    One-shot agreement analysis.

    Args:
        fixture_set: Pre-loaded fixture set. If None, loads from default path.
        judge_outputs: Mapping of fixture_id → judge output dict.
        calibration_version: Calibration version string.
        rubric_version: Rubric version string.
        judge_model: Judge model identifier.
        provider: Judge provider name.
        model_version: Model version string.
        prompt_version: Prompt/rubric version string.
        temperature: Judge temperature (should be 0.0).
        live_judge: "AVAILABLE" or "NOT_AVAILABLE".

    Returns:
        CalibrationReport with full agreement analysis.
    """
    analyzer = AgreementAnalyzer(
        fixture_set=fixture_set,
        calibration_version=calibration_version,
        rubric_version=rubric_version,
        judge_model=judge_model,
        provider=provider,
        model_version=model_version,
        prompt_version=prompt_version,
        temperature=temperature,
        live_judge=live_judge,
    )

    if judge_outputs:
        for fid, output in judge_outputs.items():
            analyzer.record_judge_output(
                fixture_id=fid,
                score=output.get("score", 0.0),
                criterion_scores=output.get("criterion_scores"),
                confidence=output.get("confidence"),
                metadata=output.get("metadata"),
            )

    return analyzer.analyze()