"""Tests for baseline compatibility validation and resolution."""
import pytest

from eb.core.schema import BaselineRecord, BenchmarkRun, EnvironmentInfo, InferenceSettings, ModelMetadata
from eb.core.types import BenchmarkPartition, Capability
from eb.scoring.normalization import CompatibilityCheck, resolve_baseline, validate_compatibility


def _make_baseline(
    model_name: str = "Qwen2.5-7B",
    bench_ver: str = "eb-v0.1",
    task_ver: str = "tasks-v0.1",
    run_id: str = "baseline-001",
    scores: list[int] | None = None,
) -> BaselineRecord:
    bl = BaselineRecord(
        base_model_name=model_name,
        base_model_revision="sha abc",
        benchmark_version=bench_ver,
        task_set_version=task_ver,
        baseline_run_id=run_id,
        suite="single",
    )
    if scores:
        bl.run_scores = scores
        bl.compute_stats()
    return bl


def _make_run(
    model_name: str = "atan-v1",
    base_name: str = "Qwen2.5-7B",
    bench_ver: str = "eb-v0.1",
    task_ver: str = "tasks-v0.1",
    partitions: list[str] | None = None,
    task_hash: str | None = None,
) -> BenchmarkRun:
    return BenchmarkRun(
        run_id="run-test-001",
        benchmark_version=bench_ver,
        task_set_version=task_ver,
        model=ModelMetadata(name=model_name, revision="sha xyz"),
        base_model=ModelMetadata(name=base_name, revision="sha abc"),
        suite="single",
        partitions=[BenchmarkPartition(p) for p in (partitions or ["development"])],
        inference=InferenceSettings(seed=42),
        environment=EnvironmentInfo(hardware="test"),
        task_set_hash=task_hash,
    )


class TestValidateCompatibility:
    def test_identical_runs_are_compatible(self):
        bl = _make_baseline()
        run = _make_run()
        check = validate_compatibility(run, bl)
        assert check.compatible is True
        assert check.mismatches == []

    def test_different_benchmark_version_rejected(self):
        bl = _make_baseline(bench_ver="eb-v0.1")
        run = _make_run(bench_ver="eb-v0.2")
        check = validate_compatibility(run, bl)
        assert check.compatible is False
        assert any(f[0] == "benchmark_version" for f in check.mismatches)

    def test_different_task_set_version_rejected(self):
        bl = _make_baseline(task_ver="tasks-v0.1")
        run = _make_run(task_ver="tasks-v0.2")
        check = validate_compatibility(run, bl)
        assert check.compatible is False
        assert any(f[0] == "task_set_version" for f in check.mismatches)

    def test_different_task_set_hash_rejected(self):
        bl = _make_baseline()
        run = _make_run(task_hash="hashAAA")
        # Need to set hash on baseline too for this check to trigger
        bl.task_set_hash = "hashBBB"
        check = validate_compatibility(run, bl)
        assert check.compatible is False
        assert any(f[0] == "task_set_hash" for f in check.mismatches)

    def test_different_partition_rejected(self):
        bl = _make_baseline()
        bl.partitions = ["development", "validation"]
        run = _make_run(partitions=["development"])
        check = validate_compatibility(run, bl)
        assert check.compatible is False

    def test_different_scoring_version_rejected(self):
        bl = _make_baseline()
        bl.scoring_version = "eb-score-v0"
        run = _make_run()
        check = validate_compatibility(run, bl)
        assert check.compatible is False
        assert any(f[0] == "scoring_version" for f in check.mismatches)

    def test_errors_formatted(self):
        bl = _make_baseline(bench_ver="eb-v0.1")
        run = _make_run(bench_ver="eb-v0.2", task_ver="tasks-v0.99")
        check = validate_compatibility(run, bl)
        assert not check.compatible
        errors = check.errors
        assert len(errors) >= 2
        assert any("benchmark_version" in e for e in errors)
        assert any("task_set_version" in e for e in errors)

    def test_different_base_model_accepted_by_compatibility(self):
        """Different base model name is NOT a compatibility check — that's resolved at lookup time."""
        bl = _make_baseline(model_name="Different-Model")
        run = _make_run(base_name="Qwen2.5-7B")
        check = validate_compatibility(run, bl)
        # Compatibility checks benchmark parameters, not model identity
        # Model identity filtering happens in resolve_baseline()
        assert check.compatible is True


class TestResolveBaseline:
    def test_exact_match_resolved(self):
        bl = _make_baseline(model_name="Qwen2.5-7B", bench_ver="eb-v0.1")
        run = _make_run(base_name="Qwen2.5-7B", bench_ver="eb-v0.1")
        resolved = resolve_baseline(run, [bl])
        assert resolved is not None
        assert resolved.baseline_run_id == "baseline-001"

    def test_no_match_returns_none(self):
        bl = _make_baseline(model_name="OtherModel")
        run = _make_run(base_name="Qwen2.5-7B")
        resolved = resolve_baseline(run, [bl])
        assert resolved is None

    def test_prefers_exact_over_partial(self):
        bl_good = _make_baseline(model_name="Qwen2.5-7B", bench_ver="eb-v0.1")
        bl_bad = _make_baseline(model_name="Qwen2.5-7B", bench_ver="eb-v99")
        run = _make_run(base_name="Qwen2.5-7B", bench_ver="eb-v0.1")
        resolved = resolve_baseline(run, [bl_bad, bl_good])
        assert resolved is bl_good

    def test_multiple_baselines_same_model(self):
        bl1 = _make_baseline(model_name="M", bench_ver="v1", run_id="b1")
        bl2 = _make_baseline(model_name="M", bench_ver="v1", run_id="b2")
        run = _make_run(base_name="M", bench_ver="v1")
        resolved = resolve_baseline(run, [bl1, bl2])
        assert resolved is not None
        assert resolved.baseline_run_id in ("b1", "b2")


class TestBaselineRecordEnhanced:
    def test_new_fields_default(self):
        bl = BaselineRecord(
            base_model_name="M",
            base_model_revision="r",
            benchmark_version="v1",
            task_set_version="t1",
            baseline_run_id="b1",
        )
        assert bl.suite == ""
        assert bl.partitions == []
        assert bl.task_set_hash is None
        assert bl.scoring_version == "eb-score-v1"
        assert bl.evaluator_config_version is None
        assert bl.min_score is None
        assert bl.max_score is None

    def test_compute_stats_with_min_max(self):
        bl = BaselineRecord(
            base_model_name="M",
            base_model_revision="r",
            benchmark_version="v1",
            task_set_version="t1",
            baseline_run_id="b1",
            run_scores=[998, 1003, 1000, 1001, 999],
        )
        bl.compute_stats()
        assert bl.min_score == 998
        assert bl.max_score == 1003
        assert bl.mean == pytest.approx(1000.2)
        assert bl.error_percent is not None
