"""Tests for eb/scoring/eb_score.py — EB Score computation."""
import pytest

from eb.scoring.eb_score import (
    SCORING_VERSION,
    EbScoreError,
    EbScoreResult,
    compute_eb_score,
    compute_improvement_percent,
)


class TestComputeEbScore:
    def test_equal_performance(self):
        """base 0.5 / model 0.5 → EB Score 1000."""
        result = compute_eb_score(0.5, 0.5)
        assert isinstance(result, EbScoreResult)
        assert result.eb_score == 1000
        assert result.improvement_percent == 0.0

    def test_improved_model(self):
        """base 0.5 / model 0.75 → EB Score 1500."""
        result = compute_eb_score(0.75, 0.5)
        assert result.eb_score == 1500
        assert result.improvement_percent == pytest.approx(50.0)

    def test_worse_model(self):
        """base 0.5 / model 0.25 → EB Score 500."""
        result = compute_eb_score(0.25, 0.5)
        assert result.eb_score == 500
        assert result.improvement_percent == pytest.approx(-50.0)

    def test_zero_baseline_raises(self):
        """Zero baseline must raise an error, not divide silently."""
        result = compute_eb_score(0.5, 0.0)
        assert isinstance(result, EbScoreError)
        assert result.reason == "zero_baseline"

    def test_zero_model_returns_zero(self):
        """Zero model performance should return EB Score 0, not crash."""
        result = compute_eb_score(0.0, 0.5)
        assert isinstance(result, EbScoreResult)
        assert result.eb_score == 0

    def test_rounding(self):
        """EB Score should be rounded to integer."""
        result = compute_eb_score(0.642, 0.50)
        assert result.eb_score == 1284

    def test_metadata_preserved(self):
        result = compute_eb_score(
            0.75, 0.5,
            baseline_run_id="baseline-001",
            benchmark_version="eb-v0.1",
            task_set_version="tasks-v0.1",
            model_name="atan-v1",
            base_model_name="Qwen2.5-7B",
        )
        assert isinstance(result, EbScoreResult)
        assert result.baseline_run_id == "baseline-001"
        assert result.benchmark_version == "eb-v0.1"
        assert result.task_set_version == "tasks-v0.1"
        assert result.model_name == "atan-v1"
        assert result.base_model_name == "Qwen2.5-7B"
        assert result.scoring_version == SCORING_VERSION


class TestComputeImprovementPercent:
    def test_no_change(self):
        assert compute_improvement_percent(0.5, 0.5) == 0.0

    def test_positive_improvement(self):
        assert compute_improvement_percent(0.75, 0.5) == pytest.approx(50.0)

    def test_negative_improvement(self):
        assert compute_improvement_percent(0.25, 0.5) == pytest.approx(-50.0)

    def test_zero_base(self):
        assert compute_improvement_percent(0.5, 0.0) == 0.0


class TestScoringVersion:
    def test_constant_exists(self):
        assert SCORING_VERSION == "eb-score-v1"
