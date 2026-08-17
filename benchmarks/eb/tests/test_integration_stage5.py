"""
Synthetic integration test for Stage 5: full baseline → trained-model normalization pipeline.

This test creates synthetic baseline and trained-model runs with known raw scores,
then validates the complete EB Score computation pipeline end-to-end.

BASE MODEL raw scores: [0.5, 0.6, 0.4]  →  mean = 0.5
TRAINED MODEL raw scores: [0.75, 0.9, 0.6]  →  mean = 0.75

Expected:
    base_raw_mean = 0.5
    model_raw_mean = 0.75
    EB Score = round(1000 * 0.75 / 0.5) = 1500
    improvement = +50.0%
"""
import pytest
import json
from pathlib import Path

from eb.core.schema import (
    BaselineRecord,
    BenchmarkRun,
    CapabilityScore,
    EvaluatorResult,
    EnvironmentInfo,
    InferenceSettings,
    ModelMetadata,
    RepeatedRunStats,
    TaskResult,
)
from eb.core.types import BenchmarkPartition, Capability, EvaluatorStatus, JudgeMode
from eb.scoring.eb_score import (
    SCORING_VERSION,
    EbScoreResult,
    compute_capability_eb_scores,
    compute_eb_score,
    compute_improvement_percent,
)
from eb.scoring.normalization import validate_compatibility, resolve_baseline
from eb.scoring.regression import compare_runs, compare_to_baseline, classify_stability


# ---------------------------------------------------------------------------
# Synthetic data factories
# ---------------------------------------------------------------------------


def _make_eval_result(score: float, status=EvaluatorStatus.PASS) -> EvaluatorResult:
    return EvaluatorResult(
        evaluator="synthetic",
        mode=JudgeMode.DETERMINISTIC,
        status=status,
        score=score,
        max_score=1.0,
        normalized_score=score,
        authoritative_level=1,
    )


def _make_task_result(task_id: str, score: float, run_id: str = "synthetic") -> TaskResult:
    return TaskResult(
        task_id=task_id,
        run_id=run_id,
        raw_task_score=score,
        evaluator_results=[_make_eval_result(score)],
    )


def _make_baseline_run() -> tuple[BaselineRecord, list[float]]:
    """Create a synthetic baseline run with known raw scores [0.5, 0.6, 0.4]."""
    raw_scores = [0.5, 0.6, 0.4]
    mean = sum(raw_scores) / len(raw_scores)  # 0.5

    bl = BaselineRecord(
        base_model_name="Qwen2.5-7B",
        base_model_revision="sha base123",
        benchmark_version="eb-v0.1",
        task_set_version="tasks-v0.1",
        baseline_run_id="baseline-synthetic-001",
        suite="single",
        partitions=["development"],
        task_set_hash="synthetic-hash-abc",
        scoring_version=SCORING_VERSION,
    )
    # Baseline run_scores are in EB-score units (1000-scale)
    eb_ref = round(1000 * mean)  # 500
    bl.run_scores = [eb_ref, eb_ref, eb_ref]  # 3 repeats
    bl.compute_stats()
    return bl, raw_scores


def _make_trained_run() -> tuple[BenchmarkRun, list[float]]:
    """Create a synthetic trained model run with known raw scores [0.75, 0.9, 0.6]."""
    raw_scores = [0.75, 0.9, 0.6]
    mean = sum(raw_scores) / len(raw_scores)  # 0.75

    task_results = []
    for i, score in enumerate(raw_scores):
        tr = _make_task_result(f"task-{i+1}", score)
        task_results.append(tr)

    run = BenchmarkRun(
        run_id="trained-synthetic-001",
        benchmark_version="eb-v0.1",
        task_set_version="tasks-v0.1",
        model=ModelMetadata(name="atan-v1", revision="sha train456"),
        base_model=ModelMetadata(name="Qwen2.5-7B", revision="sha base123"),
        suite="single",
        partitions=[BenchmarkPartition.DEVELOPMENT],
        inference=InferenceSettings(seed=42),
        environment=EnvironmentInfo(hardware="synthetic"),
        task_results=task_results,
        task_set_hash="synthetic-hash-abc",
        scoring_version=SCORING_VERSION,
    )
    return run, raw_scores


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------


class TestSyntheticIntegration:
    def test_full_pipeline(self):
        """End-to-end: baseline → trained model → EB Score computation."""
        # Step 1: Create baseline
        baseline, base_raw = _make_baseline_run()
        assert baseline.mean == pytest.approx(500.0)  # EB-score units
        assert baseline.eb_score == 1000  # Always normalized to 1000

        # Step 2: Create trained model run
        run, model_raw = _make_trained_run()
        assert run.overall_eb_score is None  # Not yet normalized

        # Step 3: Validate compatibility
        check = validate_compatibility(run, baseline)
        assert check.compatible is True, f"Incompatible: {check.errors}"

        # Step 4: Compute EB Score
        # Base raw mean in raw terms: baseline.mean / 1000 = 0.5
        base_raw_mean = baseline.mean / 1000.0
        model_raw_mean = sum(model_raw) / len(model_raw)

        result = compute_eb_score(
            model_raw_mean=model_raw_mean,
            base_raw_mean=base_raw_mean,
            baseline_run_id=baseline.baseline_run_id,
            benchmark_version=run.benchmark_version,
            task_set_version=run.task_set_version,
            model_name=run.model.name,
            base_model_name=baseline.base_model_name,
        )

        assert isinstance(result, EbScoreResult)
        assert result.eb_score == 1500, f"Expected 1500, got {result.eb_score}"
        assert result.improvement_percent == pytest.approx(50.0)
        assert result.base_raw_mean == pytest.approx(0.5)
        assert result.model_raw_mean == pytest.approx(0.75)

        # Step 5: Verify assignment to run
        run.overall_eb_score = result.eb_score
        run.run_status = "BENCHMARK_COMPLETE"
        assert run.overall_eb_score == 1500
        assert run.is_normalized is True

    def test_capability_normalization(self):
        """Capability-level normalization works correctly."""
        # Base: ARCH=0.65, CODE=0.50
        # Trained: ARCH=0.897, CODE=0.75
        model_means = {"ARCH": 0.897, "CODE": 0.75}
        base_means = {"ARCH": 0.65, "CODE": 0.50}
        task_counts = {"ARCH": 10, "CODE": 8}

        caps = compute_capability_eb_scores(model_means, base_means, task_counts=task_counts)

        assert caps["ARCH"].eb_score == 1380  # round(1000 * 0.897 / 0.65)
        assert caps["ARCH"].raw_mean == 0.897
        assert caps["ARCH"].task_count == 10
        assert caps["CODE"].eb_score == 1500  # round(1000 * 0.75 / 0.50)
        assert caps["CODE"].task_count == 8

    def test_regression_comparison(self):
        """Compare trained model against baseline produces correct delta."""
        baseline, _ = _make_baseline_run()
        run, _ = _make_trained_run()

        # Build run dicts for comparison
        run_data = {
            "run_id": run.run_id,
            "model": {"name": run.model.name},
            "base_model": {"name": run.base_model.name},
            "overall_eb_score": 1500,
            "capability_scores": {},
            "run_stats": RepeatedRunStats(scores=[1500]),
        }
        run_data["run_stats"].compute()

        baseline_data = {
            "run_id": baseline.baseline_run_id,
            "model": {"name": baseline.base_model_name},
            "overall_eb_score": 1000,
            "capability_scores": {},
        }

        result = compare_runs(baseline_data, run_data)
        assert result.score_delta == 500
        assert result.percent_delta == pytest.approx(50.0)
        assert result.model_a == baseline.base_model_name
        assert result.model_b == run.model.name

    def test_vs_baseline_comparison(self):
        """compare_to_baseline helper works."""
        run, _ = _make_trained_run()
        run_data = {
            "run_id": run.run_id,
            "baseline_run_id": "baseline-synthetic-001",
            "model": {"name": run.model.name},
            "base_model": {"name": run.base_model.name},
            "overall_eb_score": 1500,
            "capability_scores": {},
        }
        result = compare_to_baseline(run_data, baseline_eb_score=1000)
        assert result.score_delta == 500
        assert result.percent_delta == pytest.approx(50.0)

    def test_baseline_resolution(self):
        """Baseline resolution finds the correct baseline."""
        baseline, _ = _make_baseline_run()
        run, _ = _make_trained_run()

        resolved = resolve_baseline(run, [baseline])
        assert resolved is not None
        assert resolved.baseline_run_id == "baseline-synthetic-001"
        assert resolved.base_model_name == "Qwen2.5-7B"

    def test_incompatible_baseline_rejected(self):
        """Incompatible baseline is rejected."""
        baseline, _ = _make_baseline_run()
        baseline.benchmark_version = "eb-v99"  # Mismatch

        run, _ = _make_trained_run()
        check = validate_compatibility(run, baseline)
        assert check.compatible is False
        assert any("benchmark_version" in e for e in check.errors)

    def test_stability_classification(self):
        """Stability classification is correct for known error percentages."""
        assert classify_stability(0.5) == "EXCELLENT"
        assert classify_stability(1.5) == "STABLE"
        assert classify_stability(3.0) == "MODERATE"
        assert classify_stability(7.0) == "HIGH_VARIANCE"
        assert classify_stability(15.0) == "UNSTABLE"

    def test_improvement_percent_matches_formula(self):
        """Improvement percent = (model/base - 1) * 100 = EB Score - 1000 expressed as percent."""
        for base, model in [(0.5, 0.75), (0.6, 0.48), (0.8, 1.0)]:
            imp = compute_improvement_percent(model, base)
            eb = round(1000 * model / base)
            # improvement_percent is the percentage, EB Score - 1000 is the point delta
            # They relate by: improvement_percent = (eb - 1000) / 10
            expected_from_eb = (eb - 1000) / 10.0
            assert imp == pytest.approx(expected_from_eb, abs=0.1), f"base={base}, model={model}"

    def test_report_output_contains_expected_fields(self):
        """Machine-readable report contains all required fields."""
        from eb.reports.generator import generate_machine_report

        run_data = {
            "model": "atan-v1",
            "base_model": "Qwen2.5-7B",
            "benchmark_version": "eb-v0.1",
            "task_set_version": "tasks-v0.1",
            "repeats": 3,
            "overall_eb_score": 1500,
            "base_raw_mean": 0.5,
            "model_raw_mean": 0.75,
            "improvement_percent": 50.0,
            "error_percent": 0.8,
            "scoring_version": SCORING_VERSION,
            "task_set_hash": "synthetic-hash-abc",
            "baseline_run_id": "baseline-synthetic-001",
        }
        report = generate_machine_report(run_data)
        assert report["overall_eb_score"] == 1500
        assert report["scoring_version"] == SCORING_VERSION
        assert report["benchmark_compatibility"]["benchmark_version"] == "eb-v0.1"
        assert report["baseline"]["eb_score"] == 1000
