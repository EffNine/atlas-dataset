"""Tests for stability classification and repeated-run statistics."""
import pytest

from eb.core.schema import RepeatedRunStats
from eb.scoring.regression import classify_stability


class TestRepeatedRunStats:
    def test_single_run(self):
        s = RepeatedRunStats(scores=[1284])
        s.compute()
        assert s.mean == 1284.0
        assert s.median == 1284.0
        assert s.stddev == 0.0
        assert s.min_score == 1284
        assert s.max_score == 1284
        assert s.error_percent == 0.0

    def test_multiple_runs(self):
        s = RepeatedRunStats(scores=[1284, 1271, 1293, 1268, 1287])
        s.compute()
        assert s.mean == pytest.approx(1280.6)
        assert s.min_score == 1268
        assert s.max_score == 1293
        assert s.error_percent is not None
        assert 0 < s.error_percent < 5

    def test_empty(self):
        s = RepeatedRunStats()
        s.compute()
        assert s.mean is None
        assert s.stddev is None
        assert s.error_percent is None

    def test_all_same_scores(self):
        s = RepeatedRunStats(scores=[1000, 1000, 1000])
        s.compute()
        assert s.mean == 1000.0
        assert s.stddev == 0.0
        assert s.error_percent == 0.0

    def test_diverse_scores(self):
        s = RepeatedRunStats(scores=[900, 1100, 950, 1050])
        s.compute()
        assert s.mean == pytest.approx(1000.0)
        assert s.stddev > 0
        assert s.error_percent is not None
        assert s.error_percent > 0


class TestStabilityClassification:
    def test_exact_thresholds(self):
        """Verify exact boundary values."""
        # Just below 1%
        assert classify_stability(0.99) == "EXCELLENT"
        # Exactly 1%
        assert classify_stability(1.0) == "STABLE"
        # Just below 2%
        assert classify_stability(1.99) == "STABLE"
        # Exactly 2%
        assert classify_stability(2.0) == "MODERATE"
        # Just below 5%
        assert classify_stability(4.99) == "MODERATE"
        # Exactly 5%
        assert classify_stability(5.0) == "HIGH_VARIANCE"
        # Just below 10%
        assert classify_stability(9.99) == "HIGH_VARIANCE"
        # Exactly 10%
        assert classify_stability(10.0) == "UNSTABLE"

    def test_zero_is_excellent(self):
        assert classify_stability(0.0) == "EXCELLENT"

    def test_very_high_is_unstable(self):
        assert classify_stability(50.0) == "UNSTABLE"
        assert classify_stability(100.0) == "UNSTABLE"
