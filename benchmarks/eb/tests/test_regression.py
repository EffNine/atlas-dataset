"""Tests for eb/scoring/regression.py — Run comparison."""
import pytest

from eb.scoring.regression import (
    CapabilityDelta,
    RegressionResult,
    classify_stability,
    compare_runs,
    compare_to_baseline,
    compute_stability_delta,
)


class TestClassifyStability:
    def test_excellent(self):
        assert classify_stability(0.5) == "EXCELLENT"
        assert classify_stability(0.0) == "EXCELLENT"

    def test_stable(self):
        assert classify_stability(1.5) == "STABLE"

    def test_moderate(self):
        assert classify_stability(3.0) == "MODERATE"

    def test_high_variance(self):
        assert classify_stability(7.0) == "HIGH_VARIANCE"

    def test_unstable(self):
        assert classify_stability(10.0) == "UNSTABLE"
        assert classify_stability(15.0) == "UNSTABLE"

    def test_null_is_unknown(self):
        assert classify_stability(None) == "UNKNOWN"

    def test_boundary_excellent_to_stable(self):
        assert classify_stability(0.999) == "EXCELLENT"
        assert classify_stability(1.0) == "STABLE"

    def test_boundary_stable_to_moderate(self):
        assert classify_stability(1.999) == "STABLE"
        assert classify_stability(2.0) == "MODERATE"

    def test_boundary_moderate_to_high(self):
        assert classify_stability(4.999) == "MODERATE"
        assert classify_stability(5.0) == "HIGH_VARIANCE"

    def test_boundary_high_to_unstable(self):
        assert classify_stability(9.999) == "HIGH_VARIANCE"
        assert classify_stability(10.0) == "UNSTABLE"


class TestComputeStabilityDelta:
    def test_no_change(self):
        assert compute_stability_delta("EXCELLENT", "EXCELLENT") == "no change (EXCELLENT)"

    def test_improved(self):
        result = compute_stability_delta("MODERATE", "STABLE")
        assert "improved" in result

    def test_regressed(self):
        result = compute_stability_delta("STABLE", "MODERATE")
        assert "regressed" in result


class TestCompareRuns:
    def test_simple_comparison(self):
        run_a = {
            "run_id": "run-a",
            "model": {"name": "model-a"},
            "overall_eb_score": 1000,
            "capability_scores": {},
        }
        run_b = {
            "run_id": "run-b",
            "model": {"name": "model-b"},
            "overall_eb_score": 1284,
            "capability_scores": {},
        }
        result = compare_runs(run_a, run_b)
        assert isinstance(result, RegressionResult)
        assert result.score_delta == 284
        assert result.percent_delta == pytest.approx(28.4)
        assert result.model_a == "model-a"
        assert result.model_b == "model-b"

    def test_capability_deltas(self):
        from eb.core.schema import CapabilityScore
        from eb.core.types import Capability

        run_a = {
            "run_id": "run-a",
            "model": {"name": "m-a"},
            "overall_eb_score": 1000,
            "capability_scores": {
                "ARCH": CapabilityScore(capability=Capability.ARCH, eb_score=1382, raw_mean=1.382, task_count=10),
                "CODE": CapabilityScore(capability=Capability.CODE, eb_score=1000, raw_mean=1.0, task_count=10),
            },
        }
        run_b = {
            "run_id": "run-b",
            "model": {"name": "m-b"},
            "overall_eb_score": 1100,
            "capability_scores": {
                "ARCH": CapabilityScore(capability=Capability.ARCH, eb_score=1500, raw_mean=1.5, task_count=10),
                "CODE": CapabilityScore(capability=Capability.CODE, eb_score=850, raw_mean=0.85, task_count=10),
            },
        }
        result = compare_runs(run_a, run_b)
        assert len(result.capability_deltas) == 2
        arch = next(cd for cd in result.capability_deltas if cd.capability == "ARCH")
        assert arch.delta == 118
        code = next(cd for cd in result.capability_deltas if cd.capability == "CODE")
        assert code.delta == -150

    def test_notes_generated(self):
        run_a = {"run_id": "a", "model": {"name": "a"}, "overall_eb_score": 1000, "capability_scores": {}}
        run_b = {"run_id": "b", "model": {"name": "b"}, "overall_eb_score": 1200, "capability_scores": {}}
        result = compare_runs(run_a, run_b)
        assert len(result.notes) > 0
        assert "200" in result.notes[0] or "higher" in result.notes[0].lower()

    def test_to_dict(self):
        run_a = {"run_id": "a", "model": {"name": "a"}, "overall_eb_score": 1000, "capability_scores": {}}
        run_b = {"run_id": "b", "model": {"name": "b"}, "overall_eb_score": 1000, "capability_scores": {}}
        result = compare_runs(run_a, run_b)
        d = result.to_dict()
        assert d["score_delta"] == 0
        assert d["percent_delta"] == 0.0


class TestCompareToBaseline:
    def test_vs_baseline(self):
        run = {
            "run_id": "run-trained",
            "baseline_run_id": "baseline-001",
            "model": {"name": "atan-v1"},
            "base_model": {"name": "Qwen2.5-7B"},
            "overall_eb_score": 1284,
            "capability_scores": {},
        }
        result = compare_to_baseline(run, baseline_eb_score=1000)
        assert result.score_delta == 284
        assert result.percent_delta == pytest.approx(28.4)
        assert result.model_a == "Qwen2.5-7B"
        assert result.model_b == "atan-v1"
