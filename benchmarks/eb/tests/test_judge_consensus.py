"""Tests for eb/judges/consensus.py — Multi-judge consensus."""
import pytest

from eb.core.schema import JudgeResult
from eb.judges.consensus import compute_consensus, JudgeDisagreementError


class TestComputeConsensus:
    def test_one_judge(self):
        results = [JudgeResult(model_id="m1", score=0.8, status="success")]
        consensus = compute_consensus(results)
        assert consensus.final_score == 0.8
        assert consensus.selected_judge_count == 1
        assert "single_judge" in consensus.flags
        assert consensus.mean == 0.8
        assert consensus.median == 0.8
        assert consensus.stddev == 0.0
        assert consensus.disagreement_percent == 0.0

    def test_two_judges_same_score(self):
        results = [
            JudgeResult(model_id="m1", score=0.75, status="success"),
            JudgeResult(model_id="m2", score=0.75, status="success"),
        ]
        consensus = compute_consensus(results)
        assert consensus.final_score == 0.75
        assert consensus.mean == 0.75
        assert consensus.median == 0.75
        assert consensus.stddev == 0.0
        assert consensus.disagreement_percent == 0.0

    def test_two_judges_different_scores(self):
        results = [
            JudgeResult(model_id="m1", score=0.6, status="success"),
            JudgeResult(model_id="m2", score=0.8, status="success"),
        ]
        consensus = compute_consensus(results)
        assert consensus.final_score == 0.7  # mean for 2 judges
        assert consensus.mean == 0.7
        assert consensus.stddev == 0.1
        assert consensus.disagreement_percent == pytest.approx(14.29, abs=0.1)

    def test_three_judges_median(self):
        results = [
            JudgeResult(model_id="m1", score=0.5, status="success"),
            JudgeResult(model_id="m2", score=0.7, status="success"),
            JudgeResult(model_id="m3", score=0.9, status="success"),
        ]
        consensus = compute_consensus(results)
        assert consensus.final_score == 0.7  # median
        assert consensus.mean == 0.7
        assert consensus.median == 0.7

    def test_three_judges_with_outlier(self):
        """Median should be robust to outlier scores."""
        results = [
            JudgeResult(model_id="m1", score=0.5, status="success"),
            JudgeResult(model_id="m2", score=0.55, status="success"),
            JudgeResult(model_id="m3", score=0.95, status="success"),  # outlier
        ]
        consensus = compute_consensus(results)
        assert consensus.final_score == 0.55  # median, not mean
        assert consensus.mean == pytest.approx(0.667, abs=0.01)

    def test_high_disagreement_flagged(self):
        results = [
            JudgeResult(model_id="m1", score=0.2, status="success"),
            JudgeResult(model_id="m2", score=0.9, status="success"),
        ]
        consensus = compute_consensus(results, disagreement_threshold_percent=15.0)
        assert "HIGH_JUDGE_DISAGREEMENT" in consensus.flags
        assert consensus.disagreement_level in ("high", "critical")

    def test_disagreement_exceeds_threshold_two_judges(self):
        results = [
            JudgeResult(model_id="m1", score=0.3, status="success"),
            JudgeResult(model_id="m2", score=0.8, status="success"),
        ]
        consensus = compute_consensus(results, disagreement_threshold_percent=10.0)
        assert "disagreement_exceeds_threshold" in consensus.flags

    def test_all_judges_fail(self):
        results = [
            JudgeResult(model_id="m1", status="error", error="timeout"),
            JudgeResult(model_id="m2", status="error", error="rate_limit"),
        ]
        consensus = compute_consensus(results)
        assert consensus.final_score is None
        assert "all_judges_failed" in consensus.flags
        assert consensus.failed_judge_count == 2

    def test_some_judges_fail(self):
        results = [
            JudgeResult(model_id="m1", score=0.7, status="success"),
            JudgeResult(model_id="m2", status="error", error="timeout"),
            JudgeResult(model_id="m3", score=0.8, status="success"),
        ]
        consensus = compute_consensus(results)
        assert consensus.final_score == 0.75  # mean of 2 valid
        assert consensus.selected_judge_count == 2
        assert consensus.failed_judge_count == 1
        assert "1_judge(s)_failed" in consensus.flags

    def test_mixed_success_and_error(self):
        results = [
            JudgeResult(model_id="m1", score=0.6, status="success"),
            JudgeResult(model_id="m2", score=None, status="malformed", error="bad json"),
        ]
        consensus = compute_consensus(results)
        assert consensus.final_score == 0.6
        assert consensus.selected_judge_count == 1
        assert consensus.failed_judge_count == 1

    def test_per_judge_includes_failed(self):
        results = [
            JudgeResult(model_id="m1", score=0.7, status="success"),
            JudgeResult(model_id="m2", status="error", error="boom"),
        ]
        consensus = compute_consensus(results)
        assert len(consensus.per_judge) == 2
        assert consensus.per_judge[0]["model_id"] == "m1"
        assert consensus.per_judge[1]["model_id"] == "m2"
        assert consensus.per_judge[1]["error"] == "boom"

    def test_empty_list(self):
        consensus = compute_consensus([])
        assert consensus.final_score is None
        assert consensus.selected_judge_count == 0

    def test_disagreement_level_classification(self):
        # Low
        r1 = [JudgeResult(model_id="m1", score=0.5, status="success")]
        c1 = compute_consensus(r1)
        assert c1.disagreement_level == "low"

        # Moderate (stddev/mean = 0.075, threshold 15)
        r2 = [
            JudgeResult(model_id="m1", score=0.5, status="success"),
            JudgeResult(model_id="m2", score=0.575, status="success"),
        ]
        c2 = compute_consensus(r2, disagreement_threshold_percent=15.0)
        assert c2.disagreement_level in ("low", "moderate")

    def test_max_score_preserved(self):
        results = [JudgeResult(model_id="m1", score=0.8, max_score=10.0, status="success")]
        consensus = compute_consensus(results, max_score=10.0)
        assert consensus.max_score == 10.0
        assert consensus.final_score == 0.8

    def test_judge_scores_are_floats(self):
        results = [
            JudgeResult(model_id="m1", score=0.5, status="success"),
            JudgeResult(model_id="m2", score=0.5, status="success"),
        ]
        consensus = compute_consensus(results)
        assert all(isinstance(s, float) for s in consensus.judge_scores)
