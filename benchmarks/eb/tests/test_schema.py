"""Tests for core/schema.py — Pydantic model validation."""
import pytest

from eb.core.schema import (
    BaselineRecord,
    BenchmarkRun,
    CapabilityScore,
    EvaluatorResult,
    EnvironmentInfo,
    InferenceSettings,
    ModelMetadata,
    RepeatedRunStats,
    Task,
    TaskEvaluationConfig,
    TaskResult,
)
from eb.core.types import (
    BenchmarkPartition,
    Capability,
    Difficulty,
    ExecutionMode,
    JudgeMode,
)


class TestTaskSchema:
    def test_valid_task(self, sample_task_data: dict):
        task = Task.model_validate(sample_task_data)
        assert task.id == "EB-ARCH-001"
        assert task.mode == ExecutionMode.SINGLE
        assert task.difficulty == Difficulty.L4
        assert task.partition == BenchmarkPartition.DEVELOPMENT
        assert len(task.capabilities) == 2
        assert Capability.ARCH in task.capabilities

    def test_string_mode_coercion(self):
        data = {
            "id": "EB-CODE-001",
            "category": "coding",
            "mode": "EXEC",
            "difficulty": "L2",
            "prompt": "Write a function.",
            "evaluation": {"primary_mode": "DETERMINISTIC"},
            "partition": "development",
        }
        task = Task.model_validate(data)
        assert task.mode == ExecutionMode.EXEC
        assert task.difficulty == Difficulty.L2
        assert task.evaluation.primary_mode == JudgeMode.DETERMINISTIC

    def test_empty_id_rejected(self):
        data = {"id": "", "category": "x", "mode": "SINGLE", "difficulty": "L1", "prompt": "p"}
        with pytest.raises(ValueError):
            Task.model_validate(data)

    def test_missing_required_fields(self):
        with pytest.raises(Exception):  # pydantic validation error
            Task.model_validate({"id": "X"})

    def test_sha256_stability(self, sample_task_data: dict):
        task1 = Task.model_validate(sample_task_data)
        task2 = Task.model_validate(sample_task_data)
        assert task1.sha256() == task2.sha256()

    def test_long_id_rejected(self):
        data = {
            "id": "A" * 129,
            "category": "x",
            "mode": "SINGLE",
            "difficulty": "L1",
            "prompt": "p",
        }
        with pytest.raises(ValueError):
            Task.model_validate(data)


class TestEvaluatorResult:
    def test_defaults(self):
        r = EvaluatorResult(evaluator="exact", mode=JudgeMode.DETERMINISTIC, score=1.0)
        assert r.evidence == []
        assert r.flags == []
        assert r.details == {}

    def test_with_evidence(self):
        r = EvaluatorResult(
            evaluator="code",
            mode=JudgeMode.DETERMINISTIC,
            score=0.8,
            evidence=["compiles", "tests_pass"],
            flags=["partial"],
        )
        assert len(r.evidence) == 2
        assert "compiles" in r.evidence


class TestTaskResult:
    def test_passed_when_score_above_half(self):
        r = TaskResult(task_id="T1", run_id="R1", final_score=0.7)
        assert r.passed is True

    def test_failed_when_score_below_half(self):
        r = TaskResult(task_id="T1", run_id="R1", final_score=0.3)
        assert r.passed is False

    def test_none_when_no_score(self):
        r = TaskResult(task_id="T1", run_id="R1")
        assert r.passed is None


class TestRepeatedRunStats:
    def test_compute_single_run(self):
        s = RepeatedRunStats(scores=[1284])
        s.compute()
        assert s.mean == 1284.0
        assert s.median == 1284.0
        assert s.stddev == 0.0
        assert s.error_percent == 0.0

    def test_compute_multiple_runs(self):
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


class TestCapabilityScore:
    def test_valid(self):
        cs = CapabilityScore(capability=Capability.ARCH, eb_score=1382, raw_mean=1.382, task_count=25)
        assert cs.eb_score == 1382

    def test_zero_score_rejected(self):
        with pytest.raises(ValueError):
            CapabilityScore(capability=Capability.ARCH, eb_score=0, raw_mean=0.0, task_count=0)

    def test_negative_score_rejected(self):
        with pytest.raises(ValueError):
            CapabilityScore(capability=Capability.ARCH, eb_score=-5, raw_mean=0.0, task_count=0)


class TestBaselineRecord:
    def test_compute_stats(self):
        br = BaselineRecord(
            base_model_name="Qwen2.5-7B",
            base_model_revision="abc123",
            benchmark_version="eb-v0.1",
            task_set_version="tasks-v0.1",
            baseline_run_id="run-001",
            run_scores=[1000, 998, 1002, 1001, 999],
        )
        br.compute_stats()
        assert br.mean == pytest.approx(1000.0)
        assert br.eb_score == 1000
        assert br.error_percent is not None

    def test_add_score_recomputes(self):
        br = BaselineRecord(
            base_model_name="M",
            base_model_revision="r",
            benchmark_version="v1",
            task_set_version="t1",
            baseline_run_id="b1",
        )
        br.add_score(1000)
        br.add_score(1002)
        assert br.mean == pytest.approx(1001.0)
        assert len(br.run_scores) == 2


class TestBenchmarkRun:
    def test_compute_eb_score(self):
        run = BenchmarkRun(
            run_id="r1",
            benchmark_version="eb-v0.1",
            task_set_version="t-v1",
            model=ModelMetadata(name="atan-v1", revision="abc"),
            base_model=ModelMetadata(name="Qwen2.5-7B", revision="def"),
            suite="full",
            inference=InferenceSettings(seed=42),
            environment=EnvironmentInfo(hardware="RTX5070"),
        )
        run.add_run_result(TaskResult(task_id="t1", run_id="r1", raw_task_score=1.284))
        run.add_run_result(TaskResult(task_id="t2", run_id="r1", raw_task_score=1.150))
        score = run.compute_eb_score(baseline_score=1000)
        assert score > 0
        assert run.overall_eb_score == score

    def test_to_dict_serializes_enums(self):
        run = BenchmarkRun(
            run_id="r1",
            benchmark_version="eb-v0.1",
            task_set_version="t-v1",
            model=ModelMetadata(name="m", revision="r"),
            base_model=ModelMetadata(name="base", revision="r"),
            suite="full",
            inference=InferenceSettings(),
            environment=EnvironmentInfo(hardware="test"),
        )
        d = run.to_dict()
        assert isinstance(d["run_id"], str)
        assert "capability_scores" in d
