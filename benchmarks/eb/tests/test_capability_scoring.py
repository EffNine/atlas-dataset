"""Tests for capability-level EB score normalization."""
import pytest

from eb.core.schema import CapabilityScore
from eb.core.types import Capability
from eb.scoring.eb_score import compute_capability_eb_scores


class TestCapabilityEbScores:
    def test_basic_normalization(self):
        """Cap raw 0.897 / base raw 0.65 → EB Score ~1380."""
        model_means = {"ARCH": 0.897}
        base_means = {"ARCH": 0.65}
        result = compute_capability_eb_scores(model_means, base_means)
        assert "ARCH" in result
        assert result["ARCH"].eb_score == 1380
        assert result["ARCH"].raw_mean == 0.897
        assert result["ARCH"].task_count == 0

    def test_multiple_capabilities(self):
        model_means = {"ARCH": 0.65, "CODE": 0.50, "PLAN": 0.80}
        base_means = {"ARCH": 0.65, "CODE": 0.50, "PLAN": 0.50}
        result = compute_capability_eb_scores(model_means, base_means)
        assert result["ARCH"].eb_score == 1000
        assert result["CODE"].eb_score == 1000
        assert result["PLAN"].eb_score == 1600

    def test_zero_base_skipped(self):
        """Capabilities with zero base mean should be skipped."""
        model_means = {"ARCH": 0.5, "CODE": 0.5}
        base_means = {"ARCH": 0.0, "CODE": 0.5}
        result = compute_capability_eb_scores(model_means, base_means)
        assert "ARCH" not in result
        assert "CODE" in result
        assert result["CODE"].eb_score == 1000

    def test_task_counts(self):
        model_means = {"ARCH": 0.8}
        base_means = {"ARCH": 0.5}
        task_counts = {"ARCH": 25}
        result = compute_capability_eb_scores(model_means, base_means, task_counts=task_counts)
        assert result["ARCH"].task_count == 25

    def test_run_stats_preserved(self):
        from eb.core.schema import RepeatedRunStats
        stats = RepeatedRunStats(scores=[1380, 1375, 1385])
        stats.compute()
        model_means = {"ARCH": 0.8}
        base_means = {"ARCH": 0.5}
        stats_map = {"ARCH": stats}
        result = compute_capability_eb_scores(model_means, base_means, run_stats_map=stats_map)
        assert result["ARCH"].run_stats is not None
        assert result["ARCH"].run_stats.mean == pytest.approx(1380.0)

    def test_no_double_counting(self):
        """Each capability is normalized independently from raw means."""
        model_means = {"ARCH": 0.8, "CODE": 0.8}
        base_means = {"ARCH": 0.4, "CODE": 0.8}
        result = compute_capability_eb_scores(model_means, base_means)
        assert result["ARCH"].eb_score == 2000
        assert result["CODE"].eb_score == 1000
        # They are computed independently, not from an aggregate

    def test_empty_inputs(self):
        result = compute_capability_eb_scores({}, {})
        assert result == {}

    def test_negative_scores_rejected(self):
        model_means = {"ARCH": -0.5}
        base_means = {"ARCH": 0.5}
        result = compute_capability_eb_scores(model_means, base_means)
        assert "ARCH" not in result  # negative eb_score would be rejected by validator
