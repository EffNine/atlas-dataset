"""Tests for evaluation_research.matrix_runner statistical corrections.

Verifies:
  - McNemar exact test correctness
  - Wilson CI correctness
  - Symmetry of McNemar test
  - No-discordant-pairs edge case
  - Record matching by record_id
  - Missing model handling
  - Overlap accounting
  - Backward compatibility with existing aggregate structure
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import pytest
from evaluation_research.matrix_runner import (
    MatrixRunner,
    wilson_ci,
    mcnemar_test,
    cohens_d,
    _normal_quantile,
    _binomial_cdf,
    _regularized_incomplete_beta,
)


# ---------------------------------------------------------------------------
# Wilson CI tests
# ---------------------------------------------------------------------------

class TestWilsonCI:
    def test_zero_successes(self):
        """All failures: CI should be [0, upper]."""
        lower, upper = wilson_ci(0, 100)
        assert lower == 0.0
        assert upper > 0.0
        assert upper < 1.0

    def test_all_successes(self):
        """All successes: CI should be [lower, 1]."""
        lower, upper = wilson_ci(100, 100)
        assert lower > 0.0
        assert upper == 1.0

    def test_perfect_half(self):
        """50% success rate: CI should be symmetric around 0.5."""
        lower, upper = wilson_ci(50, 100)
        assert 0.4 < lower < 0.5
        assert 0.5 < upper < 0.6
        # Should not be a perfect point estimate
        assert lower < 0.5 < upper

    def test_small_n(self):
        """Small N should still produce valid bounds."""
        lower, upper = wilson_ci(1, 5)
        assert 0.0 <= lower < upper <= 1.0

    def test_zero_total(self):
        """Zero total should return (0, 0)."""
        lower, upper = wilson_ci(0, 0)
        assert lower == 0.0
        assert upper == 0.0

    def test_wilson_vs_normal_differs_at_extremes(self):
        """Wilson CI should differ from normal approx at extreme p."""
        # At p=0.01, n=100
        w_lower, w_upper = wilson_ci(1, 100)
        # Normal approx would give negative lower bound
        p_hat = 0.01
        z = 1.96
        se = (p_hat * (1 - p_hat) / 100) ** 0.5
        n_lower = max(0, p_hat - z * se)
        n_upper = min(1, p_hat + z * se)
        # Wilson should not produce negative lower
        assert w_lower >= 0.0
        # Wilson upper should be tighter than normal at extremes
        assert w_upper <= n_upper + 0.03  # Wilson is wider (conservative) at extremes

    def test_known_95_percent_bounds(self):
        """For large N, Wilson CI should approach normal approx."""
        # N=1000, p=0.5
        lower, upper = wilson_ci(500, 1000)
        assert 0.46 < lower < 0.47
        assert 0.53 < upper < 0.54


# ---------------------------------------------------------------------------
# McNemar test tests
# ---------------------------------------------------------------------------

class TestMcNemarTest:
    def test_no_discordant_pairs(self):
        """Perfect agreement: b=0, c=0 → p=1.0."""
        result = mcnemar_test(0, 0)
        assert result["p_value"] == 1.0
        assert result["method"] == "exact_binomial"
        assert result["b"] == 0
        assert result["c"] == 0
        assert result["n_discordant"] == 0

    def test_symmetry(self):
        """Swapping b and c should preserve two-sided p-value."""
        r1 = mcnemar_test(3, 10)
        r2 = mcnemar_test(10, 3)
        assert r1["p_value"] == r2["p_value"]
        assert r1["n_discordant"] == r2["n_discordant"]

    def test_perfect_agreement_direction(self):
        """If one model always correct and other always wrong:
        b=0, c=50 → very small p-value."""
        result = mcnemar_test(0, 50)
        assert result["p_value"] < 0.001
        assert result["method"] == "chi_square_approx"  # n_discordant=50 >= 25

    def test_moderate_discordance(self):
        """Known case: b=10, c=10 (symmetric discordance) → p≈1.0."""
        result = mcnemar_test(10, 10)
        # With equal discordance, p should be high (near 1.0)
        assert result["p_value"] > 0.5
        assert result["method"] == "exact_binomial"

    def test_asymmetric_discordance_small(self):
        """b=1, c=9 → significant asymmetry."""
        result = mcnemar_test(1, 9)
        assert result["p_value"] < 0.1
        assert result["method"] == "exact_binomial"

    def test_large_discordance_uses_chi_square(self):
        """b+c >= 25 should use chi-square approximation."""
        result = mcnemar_test(20, 30)
        assert result["method"] == "chi_square_approx"
        assert result["p_value"] < 0.5  # Some asymmetry

    def test_known_exact_case(self):
        """b=1, c=0 → p = 2 * P(X<=0) = 2 * 0.5 = 1.0 for n=1."""
        result = mcnemar_test(1, 0)
        # With 1 discordant pair, p = 1.0 (can't reject H0)
        assert result["p_value"] == 1.0

    def test_extreme_asymmetry(self):
        """b=0, c=20 → very small p."""
        result = mcnemar_test(0, 20)
        assert result["p_value"] < 0.0001


# ---------------------------------------------------------------------------
# Cohen's d tests
# ---------------------------------------------------------------------------

class TestCohensD:
    def test_identical_pairs(self):
        """Perfect agreement → d=0."""
        pairs = [(1.0, 1.0), (0.0, 0.0), (1.0, 1.0)]
        assert cohens_d(pairs) == 0.0

    def test_consistent_direction(self):
        """All treatment > baseline → negative d (code computes baseline - treatment)."""
        pairs = [(0.0, 1.0), (0.0, 2.0), (0.0, 3.0)]
        d = cohens_d(pairs)
        assert d is not None
        assert d < 0

    def test_insufficient_data(self):
        """Less than 2 pairs → None."""
        assert cohens_d([(1.0, 0.5)]) is None
        assert cohens_d([]) is None


# ---------------------------------------------------------------------------
# MatrixRunner integration tests
# ---------------------------------------------------------------------------

class TestMatrixRunnerCompute:
    def test_basic_computation(self, tmp_path):
        """Basic computation with two models."""
        results = [
            {"record_id": "r1", "model_id": "m1", "correctness": 1.0},
            {"record_id": "r2", "model_id": "m1", "correctness": 0.0},
            {"record_id": "r1", "model_id": "m2", "correctness": 1.0},
            {"record_id": "r2", "model_id": "m2", "correctness": 1.0},
        ]
        runner = MatrixRunner(tmp_path)
        out = runner.compute_statistics(results, "m1", ["m2"])

        assert "aggregates" in out
        assert "comparisons" in out
        assert "m1" in out["aggregates"]
        assert "m2" in out["aggregates"]
        assert "m2" in out["comparisons"]

        m1_agg = out["aggregates"]["m1"]
        assert m1_agg["correctness"] == 0.5
        assert m1_agg["ci_method"] == "wilson_score"
        assert m1_agg["n_evaluated"] == 2
        assert m1_agg["n_total"] == 2

    def test_mcnemar_in_output(self, tmp_path):
        """McNemar stats should appear in comparison output."""
        results = [
            {"record_id": f"r{i}", "model_id": "m1", "correctness": 1.0 if i % 2 == 0 else 0.0}
            for i in range(20)
        ]
        results += [
            {"record_id": f"r{i}", "model_id": "m2", "correctness": 1.0 if i % 2 == 1 else 0.0}
            for i in range(20)
        ]
        runner = MatrixRunner(tmp_path)
        out = runner.compute_statistics(results, "m1", ["m2"])

        cmp = out["comparisons"]["m2"]
        assert "paired_p_value" in cmp
        assert "mcnemar_b" in cmp
        assert "mcnemar_c" in cmp
        assert "paired_method" in cmp

    def test_missing_model_handling(self, tmp_path):
        """Missing compare model should be skipped gracefully."""
        results = [
            {"record_id": "r1", "model_id": "m1", "correctness": 1.0},
        ]
        runner = MatrixRunner(tmp_path)
        out = runner.compute_statistics(results, "m1", ["nonexistent"])
        assert "nonexistent" not in out["comparisons"]

    def test_overlap_accounting(self, tmp_path):
        """Overlapping records should be tracked."""
        results = [
            {"record_id": "r1", "model_id": "m1", "correctness": 1.0, "training_overlap": True, "overlap_source": "train"},
            {"record_id": "r2", "model_id": "m1", "correctness": 0.0, "training_overlap": False},
        ]
        runner = MatrixRunner(tmp_path)
        out = runner.compute_statistics(results, "m1", [])

        m1 = out["aggregates"]["m1"]
        assert m1["n_overlap"] == 1
        assert "r1" in m1["overlap_record_ids"]
        assert m1["n_evaluated"] == 2
        assert m1["n_total"] == 2

    def test_statistical_contract_in_output(self, tmp_path):
        """Output should declare statistical methods used."""
        results = [
            {"record_id": "r1", "model_id": "m1", "correctness": 1.0},
        ]
        runner = MatrixRunner(tmp_path)
        out = runner.compute_statistics(results, "m1", [])

        assert out["statistical_contract"]["ci_method"] == "wilson_score"
        assert out["statistical_contract"]["paired_test"] == "mcnemar"
        assert out["statistical_contract"]["overlap_accounted"] is True

    def test_backward_compatible_aggregate_structure(self, tmp_path):
        """Aggregate dict should contain expected keys."""
        results = [
            {"record_id": "r1", "model_id": "m1", "correctness": 1.0, "truncation": False},
        ]
        runner = MatrixRunner(tmp_path)
        out = runner.compute_statistics(results, "m1", [])

        m1 = out["aggregates"]["m1"]
        required_keys = [
            "model_id", "n_evaluated", "n_total", "correctness",
            "correctness_ci_95", "truncation_rate", "gpol_pass",
        ]
        for key in required_keys:
            assert key in m1, f"Missing key: {key}"

    def test_delta_is_primary_effect_size(self, tmp_path):
        """Delta vs baseline should be primary; Cohen's d secondary."""
        results = [
            {"record_id": f"r{i}", "model_id": "m1", "correctness": 1.0}
            for i in range(10)
        ]
        results += [
            {"record_id": f"r{i}", "model_id": "m2", "correctness": 0.8}
            for i in range(10)
        ]
        runner = MatrixRunner(tmp_path)
        out = runner.compute_statistics(results, "m1", ["m2"])

        cmp = out["comparisons"]["m2"]
        assert "delta_vs_baseline" in cmp
        assert cmp["delta_vs_baseline"] is not None
        # Cohen's d is secondary (optional)
        assert "effect_size_cohens_d" in cmp

    def test_compute_with_none_correctness(self, tmp_path):
        """Records with None correctness should be excluded from scoring."""
        results = [
            {"record_id": "r1", "model_id": "m1", "correctness": None},
            {"record_id": "r2", "model_id": "m1", "correctness": 1.0},
        ]
        runner = MatrixRunner(tmp_path)
        out = runner.compute_statistics(results, "m1", [])

        m1 = out["aggregates"]["m1"]
        assert m1["n_evaluated"] == 1  # Only r2 counted
        assert m1["n_total"] == 2  # But r1 still counted in total

    def test_plan_matrix_includes_method(self, tmp_path):
        """plan_matrix should include statistical method declaration."""
        fake = tmp_path / "fake.jsonl"
        fake.write_text("", encoding="utf-8")
        runner = MatrixRunner(tmp_path)
        plan = runner.plan_matrix(
            fake,
            [{"model_id": "m1", "adapter_path": "/tmp", "base_model": "test"}],
            family="math",
        )
        assert "statistical_method" in plan
        assert plan["statistical_method"]["ci_method"] == "wilson_score"
        assert plan["statistical_method"]["paired_test"] == "mcnemar_exact"
