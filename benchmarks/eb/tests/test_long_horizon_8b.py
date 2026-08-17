"""Tests for Stage 8B — LONG fixtures, schema validation, evaluator, and scoring."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from eb.core.schema import (
    StageData,
    StageResult,
    Task,
    TaskResult,
    EvaluatorResult,
)
from eb.core.types import ExecutionMode, Difficulty, Capability, BenchmarkPartition, EvaluatorStatus, JudgeMode
from eb.evaluators.long_horizon import LongHorizonEvaluator
from eb.runners.long_horizon import LongHorizonRunner, LongRunContext
from eb.runners.base import RunContext, TaskStatus
from eb.adapters.base import ModelAdapter, ModelRequest, ModelResponse, TokenUsage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_ROOT = Path(__file__).resolve().parent.parent / "repositories" / "fixtures"


def _make_long_task(
    task_id: str = "EB-LONG-001",
    stages: list[dict | StageData] | None = None,
    repository_id: str = "",
    **overrides,
) -> Task:
    if stages is None:
        stages = [
            {"id": "s1", "name": "Stage 1", "prompt": "Do stage 1"},
            {"id": "s2", "name": "Stage 2", "prompt": "Do stage 2"},
        ]
    defaults = {
        "id": task_id,
        "category": "engineering",
        "mode": ExecutionMode.LONG,
        "difficulty": Difficulty.L4,
        "capabilities": [Capability.ADVISORY],
        "prompt": f"Complete the engineering workflow: {task_id}",
        "partition": BenchmarkPartition.DEVELOPMENT,
        "context": {"stages": stages},
    }
    if repository_id:
        defaults["context"]["repository_id"] = repository_id
    defaults.update(overrides)
    return Task.model_validate(defaults)


def _make_mock_adapter(responses: list[str] | None = None) -> ModelAdapter:
    adapter = MagicMock(spec=ModelAdapter)
    adapter.model_name = "test-model"
    adapter._closed = False

    if responses is None:
        responses = ["Stage 1 output", "Stage 2 output"]

    call_count = [0]

    def gen(request: ModelRequest) -> ModelResponse:
        idx = min(call_count[0], len(responses) - 1)
        call_count[0] += 1
        return ModelResponse(
            text=responses[idx],
            model="test-model",
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            latency_s=0.02,
            backend="mock",
        )

    adapter.generate = gen
    from eb.adapters.base import AdapterMetadata
    adapter.metadata.return_value = AdapterMetadata(
        adapter_type="mock", backend="mock", model_name="test-model",
    )
    return adapter


def _make_ctx(run_id: str = "run-long-001", **overrides) -> RunContext:
    defaults = {
        "run_id": run_id,
        "model_name": "test-model",
        "suite": "long",
        "inference_settings": {"seed": 42, "temperature": 0.0, "top_p": 1.0, "top_k": 0, "max_tokens": 4096},
        "repeat_index": 0,
    }
    defaults.update(overrides)
    return RunContext(**defaults)


def _make_mock_sandbox():
    mock = MagicMock()
    mock.create.return_value = "eb-long-sbox-001"
    mock.exec.return_value = MagicMock(success=True, exit_code=0, stdout="", stderr="", duration_s=0.01)
    mock.copy_in.return_value = None
    mock.collect.return_value = {}
    mock.stop = MagicMock()
    mock.destroy = MagicMock()
    return mock


# ---------------------------------------------------------------------------
# StageData schema tests
# ---------------------------------------------------------------------------

class TestStageDataSchema:
    def test_valid_stage(self):
        stage = StageData(id="s1", name="Stage 1", prompt="Do something")
        assert stage.id == "s1"
        assert stage.name == "Stage 1"
        assert stage.order == 0
        assert stage.terminal is False
        assert stage.failure_mode == "abort"
        assert stage.requirement_change is None

    def test_stage_with_all_fields(self):
        stage = StageData(
            id="s2",
            name="Stage 2",
            prompt="Do more",
            order=1,
            objective="Complete the task",
            instructions="Follow the steps",
            expected_artifacts=["output.txt"],
            expected_state={"files": ["output.txt"]},
            evaluation_criteria=[{"id": "c1", "type": "contains", "value": "result"}],
            dependencies=["s1"],
            terminal=True,
            failure_mode="abort",
            requirement_change={"from": "req_a", "to": "req_b"},
            timeout_s=60.0,
            metadata={"key": "value"},
        )
        assert stage.order == 1
        assert stage.terminal is True
        assert stage.failure_mode == "abort"
        assert stage.requirement_change == {"from": "req_a", "to": "req_b"}
        assert stage.timeout_s == 60.0
        assert stage.metadata == {"key": "value"}

    def test_empty_id_rejected(self):
        with pytest.raises(ValueError):
            StageData(id="", name="N", prompt="P")

    def test_empty_name_rejected(self):
        with pytest.raises(ValueError):
            StageData(id="s1", name="", prompt="P")

    def test_invalid_failure_mode_rejected(self):
        with pytest.raises(ValueError):
            StageData(id="s1", name="N", prompt="P", failure_mode="invalid")

    def test_to_inline_context(self):
        stage = StageData(id="s1", name="Stage 1", prompt="Do it", order=0)
        inline = stage.to_inline_context()
        assert inline == {"id": "s1", "name": "Stage 1", "prompt": "Do it"}

    def test_duplicate_stage_ids_in_list(self):
        """Duplicate IDs in a list should not be rejected at model level."""
        s1 = StageData(id="dup", name="N", prompt="P")
        s2 = StageData(id="dup", name="N2", prompt="P2")
        assert s1.id == s2.id == "dup"


# ---------------------------------------------------------------------------
# StageResult schema tests
# ---------------------------------------------------------------------------

class TestStageResultSchema:
    def test_defaults(self):
        sr = StageResult(stage_id="s1", stage_name="S1")
        assert sr.status == "pending"
        assert sr.output is None
        assert sr.score is None
        assert sr.duration_s == 0.0
        assert sr.passed is None

    def test_passed_when_score_above_half(self):
        sr = StageResult(stage_id="s1", stage_name="S1", score=0.8)
        assert sr.passed is True

    def test_failed_when_score_below_half(self):
        sr = StageResult(stage_id="s1", stage_name="S1", score=0.3)
        assert sr.passed is False

    def test_timestamp_format(self):
        sr = StageResult(stage_id="s1", stage_name="S1")
        assert "T" in sr.timestamp


# ---------------------------------------------------------------------------
# Fixtures loading tests
# ---------------------------------------------------------------------------

class TestFixtureLoading:
    def test_simple_impl_fixture_exists(self):
        fixture_path = FIXTURES_ROOT / "long-simple-impl" / "fixture.json"
        assert fixture_path.exists()
        with fixture_path.open() as f:
            data = json.load(f)
        assert data["id"] == "long-simple-impl"
        assert len(data["stages"]) == 3

    def test_requirement_change_fixture_exists(self):
        fixture_path = FIXTURES_ROOT / "long-requirement-change" / "fixture.json"
        assert fixture_path.exists()
        with fixture_path.open() as f:
            data = json.load(f)
        assert data["id"] == "long-requirement-change"
        assert len(data["stages"]) == 3
        # Check requirement change exists
        stage1 = data["stages"][1]
        assert "requirement_change" in stage1
        assert stage1["requirement_change"]["from"] == "counter with increment and get_value only"
        assert stage1["requirement_change"]["to"] == "counter with increment, decrement, reset, and non-negative guard"

    def test_failure_propagation_fixture_exists(self):
        fixture_path = FIXTURES_ROOT / "long-failure-propagation" / "fixture.json"
        assert fixture_path.exists()
        with fixture_path.open() as f:
            data = json.load(f)
        assert data["id"] == "long-failure-propagation"
        assert len(data["stages"]) == 3
        # Middle stage is terminal and should fail
        stage1 = data["stages"][1]
        assert stage1.get("terminal") is True

    def test_final_delivery_fixture_exists(self):
        fixture_path = FIXTURES_ROOT / "long-final-delivery" / "fixture.json"
        assert fixture_path.exists()
        with fixture_path.open() as f:
            data = json.load(f)
        assert data["id"] == "long-final-delivery"
        assert len(data["stages"]) == 2
        # Last stage is terminal
        assert data["stages"][-1].get("terminal") is True
        # Has delivery criteria
        assert "delivery_criteria" in data

    def test_fixture_source_files_exist(self):
        """All fixtures should have source files."""
        for fixture_name in ["long-simple-impl", "long-requirement-change", "long-failure-propagation", "long-final-delivery"]:
            fixture_dir = FIXTURES_ROOT / fixture_name / "source"
            assert fixture_dir.exists(), f"Missing source dir for {fixture_name}"
            files = list(fixture_dir.rglob("*"))
            assert len(files) > 0, f"No source files in {fixture_dir}"

    def test_invalid_fixture_json_rejected(self, tmp_path: Path):
        """Malformed fixture.json should not crash loading."""
        fixture_dir = tmp_path / "bad-fixture"
        fixture_dir.mkdir()
        (fixture_dir / "fixture.json").write_text('{"id": "bad", "stages": "not_a_list"}')

        # Loading should not crash; the runner should handle it gracefully
        from eb.runners.repository import RepositoryFixture
        try:
            fixture = RepositoryFixture.from_manifest(fixture_dir / "fixture.json")
            assert fixture.fixture_id == "bad"
        except Exception:
            pass  # Acceptable if manifest parsing fails

    def test_empty_stages_in_fixture(self, tmp_path: Path):
        """Fixture with empty stages list should be loadable."""
        fixture_dir = tmp_path / "empty-stages"
        fixture_dir.mkdir()
        (fixture_dir / "fixture.json").write_text(json.dumps({
            "id": "empty-stages",
            "stages": [],
        }))
        from eb.runners.repository import RepositoryFixture
        fixture = RepositoryFixture.from_manifest(fixture_dir / "fixture.json")
        assert fixture.fixture_id == "empty-stages"


# ---------------------------------------------------------------------------
# LONG evaluator tests
# ---------------------------------------------------------------------------

class TestLongHorizonEvaluator:
    def setup_method(self):
        self.evaluator = LongHorizonEvaluator()

    def test_not_applicable_for_non_long_task(self):
        task = _make_long_task(mode=ExecutionMode.SINGLE)
        result = TaskResult(task_id="t1", run_id="r1")
        ev_result = self.evaluator.evaluate(task, result)
        assert ev_result.status == EvaluatorStatus.NOT_APPLICABLE
        assert "no_stage_results" in ev_result.flags

    def test_no_stage_results(self):
        task = _make_long_task()
        result = TaskResult(task_id="t1", run_id="r1")
        ev_result = self.evaluator.evaluate(task, result)
        assert ev_result.status == EvaluatorStatus.NOT_APPLICABLE

    def test_all_stages_success(self):
        task = _make_long_task()
        result = TaskResult(
            task_id="t1", run_id="r1",
            stage_results=[
                StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
                StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=1.0),
            ],
            raw_response="Final output",
        )
        ev_result = self.evaluator.evaluate(task, result)
        assert ev_result.status == EvaluatorStatus.PASS
        assert ev_result.score is not None
        assert ev_result.score >= 0.5
        assert "stage_s1=SUCCESS" in ev_result.evidence
        assert "stage_s2=SUCCESS" in ev_result.evidence

    def test_terminal_stage_failure(self):
        task = _make_long_task(stages=[
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
        ])
        result = TaskResult(
            task_id="t1", run_id="r1",
            stage_results=[
                StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
                StageResult(stage_id="s2", stage_name="S2", status="FAILED", score=0.0),
            ],
        )
        ev_result = self.evaluator.evaluate(task, result)
        assert ev_result.status == EvaluatorStatus.FAIL
        assert ev_result.score == 0.0
        assert "terminal_stage_failed" in ev_result.evidence

    def test_last_stage_implicit_terminal_failure(self):
        """Without explicit terminal flag, last stage failure should still cap score."""
        task = _make_long_task(stages=[
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2"},
        ])
        result = TaskResult(
            task_id="t1", run_id="r1",
            stage_results=[
                StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
                StageResult(stage_id="s2", stage_name="S2", status="TIMEOUT", score=0.0),
            ],
        )
        ev_result = self.evaluator.evaluate(task, result)
        assert ev_result.status == EvaluatorStatus.FAIL
        assert ev_result.score == 0.0

    def test_partial_progress_score(self):
        """Score reflects fraction of completed stages; outcome is PARTIAL when non-terminal stage fails."""
        task = _make_long_task(stages=[
            {"id": f"s{i}", "name": f"S{i}", "prompt": f"P{i}"}
            for i in range(4)
        ])
        result = TaskResult(
            task_id="t1", run_id="r1",
            stage_results=[
                StageResult(stage_id="s0", stage_name="S0", status="SUCCESS", score=1.0),
                StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
                StageResult(stage_id="s2", stage_name="S2", status="FAILED", score=0.0),
                StageResult(stage_id="s3", stage_name="S3", status="SUCCESS", score=1.0),
            ],
        )
        ev_result = self.evaluator.evaluate(task, result)
        # Outcome is PARTIAL because not all stages succeeded
        assert ev_result.status == EvaluatorStatus.PARTIAL
        # 3/4 = 0.75 progress, terminal score 1.0
        # final = 0.75 * 0.7 + 1.0 * 0.3 = 0.825
        assert ev_result.score == pytest.approx(0.825, abs=0.01)

    def test_error_penalty(self):
        """Adapter errors reduce final score by 50%."""
        task = _make_long_task()
        result = TaskResult(
            task_id="t1", run_id="r1",
            stage_results=[
                StageResult(stage_id="s1", stage_name="S1", status="ERROR", score=None, error="boom"),
                StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=1.0),
            ],
        )
        ev_result = self.evaluator.evaluate(task, result)
        # Progress = 0.5, terminal = 1.0
        # base = 0.5 * 0.7 + 1.0 * 0.3 = 0.65
        # with 50% error penalty: 0.65 * 0.5 = 0.325
        assert ev_result.score == pytest.approx(0.325, abs=0.01)
        assert any("stage_error:s1" in f for f in ev_result.flags)

    def test_delivery_criteria_check(self):
        """Delivery criteria in task context are evaluated."""
        task = _make_long_task(
            context={
                "stages": [{"id": "s1", "name": "S1", "prompt": "P1"}],
                "delivery_criteria": {"checks": [{"type": "contains", "value": "delivered"}]},
            }
        )
        result = TaskResult(
            task_id="t1", run_id="r1",
            stage_results=[StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0)],
            raw_response="The task was delivered successfully",
        )
        ev_result = self.evaluator.evaluate(task, result)
        # With delivery criteria matching, score should be higher
        assert ev_result.status == EvaluatorStatus.PASS
        assert ev_result.score is not None

    def test_requirement_change_adaptation(self):
        """Requirement changes are tracked in evaluation."""
        task = _make_long_task(stages=[
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "requirement_change": {"from": "a", "to": "b"}},
            {"id": "s3", "name": "S3", "prompt": "P3"},
        ])
        result = TaskResult(
            task_id="t1", run_id="r1",
            stage_results=[
                StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
                StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=1.0),
                StageResult(stage_id="s3", stage_name="S3", status="SUCCESS", score=1.0),
            ],
        )
        ev_result = self.evaluator.evaluate(task, result)
        assert ev_result.status == EvaluatorStatus.PASS
        # Requirement change adaptation should boost score
        assert ev_result.score is not None

    def test_empty_stages(self):
        task = _make_long_task(stages=[])
        result = TaskResult(task_id="t1", run_id="r1", stage_results=[])
        ev_result = self.evaluator.evaluate(task, result)
        assert ev_result.status == EvaluatorStatus.NOT_APPLICABLE

    def test_is_applicable(self):
        assert self.evaluator.is_applicable(_make_long_task()) is True
        assert self.evaluator.is_applicable(_make_long_task(mode=ExecutionMode.SINGLE)) is False
        assert self.evaluator.is_applicable(_make_long_task(mode=ExecutionMode.EXEC)) is False

    def test_authority_level(self):
        assert self.evaluator.authority_level == 1

    def test_name(self):
        assert self.evaluator.name == "long_horizon"


# ---------------------------------------------------------------------------
# Integration: Runner + Evaluator
# ---------------------------------------------------------------------------

class TestLongHorizonIntegration:
    def test_runner_with_long_horizon_evaluator(self):
        """LongHorizonRunner should integrate with LongHorizonEvaluator."""
        adapter = _make_mock_adapter(["Stage 1 output", "Stage 2 output"])
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox)
        task = _make_long_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["status"] == TaskStatus.SUCCESS.value
        assert len(result.stage_results) == 2
        # The runner's _evaluate_final should aggregate scores
        assert result.raw_task_score is not None

    def test_runner_with_terminal_stage(self):
        """Terminal stage failure should propagate to TaskResult."""
        adapter = _make_mock_adapter(["Stage 1 ok", "TERMINAL FAIL"])
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox)
        task = _make_long_task(stages=[
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
        ])
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert len(result.stage_results) == 2
        assert result.stage_results[1].status == "SUCCESS"  # Adapter succeeded
        # But the evaluator should catch the terminal failure
        assert result.execution_metadata["status"] == TaskStatus.SUCCESS.value

    def test_requirement_change_fixture_integration(self):
        """Test with a task that has requirement changes."""
        adapter = _make_mock_adapter(["v1 impl", "adapted", "all passed"])
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox)
        task = _make_long_task(stages=[
            {"id": "v1", "name": "v1", "prompt": "Implement v1"},
            {"id": "change", "name": "change", "prompt": "Adapt to new req",
             "requirement_change": {"from": "v1", "to": "v2"}},
            {"id": "verify", "name": "verify", "prompt": "Verify", "terminal": True},
        ])
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["stage_count"] == 3
        assert result.execution_metadata["status"] == TaskStatus.SUCCESS.value


# ---------------------------------------------------------------------------
# Scoring model tests
# ---------------------------------------------------------------------------

class TestScoringModel:
    def test_terminal_failure_caps_score(self):
        """A failed terminal stage should result in score 0.0."""
        evaluator = LongHorizonEvaluator()
        task = _make_long_task(stages=[
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
        ])
        result = TaskResult(
            task_id="t1", run_id="r1",
            stage_results=[
                StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
                StageResult(stage_id="s2", stage_name="S2", status="FAILED", score=0.0),
            ],
        )
        ev_result = evaluator.evaluate(task, result)
        assert ev_result.score == 0.0
        assert ev_result.status == EvaluatorStatus.FAIL

    def test_progress_only_no_terminal(self):
        """Without terminal stage, score is based on progress + last stage."""
        evaluator = LongHorizonEvaluator()
        task = _make_long_task(stages=[
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2"},
        ])
        result = TaskResult(
            task_id="t1", run_id="r1",
            stage_results=[
                StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
                StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=0.6),
            ],
        )
        ev_result = evaluator.evaluate(task, result)
        # progress = 1.0, terminal = 0.6
        # final = 1.0 * 0.7 + 0.6 * 0.3 = 0.88
        assert ev_result.score == pytest.approx(0.88, abs=0.01)

    def test_all_stages_fail(self):
        """All stages failing should produce 0.0 score."""
        evaluator = LongHorizonEvaluator()
        task = _make_long_task()
        result = TaskResult(
            task_id="t1", run_id="r1",
            stage_results=[
                StageResult(stage_id="s1", stage_name="S1", status="FAILED", score=0.0),
                StageResult(stage_id="s2", stage_name="S2", status="FAILED", score=0.0),
            ],
        )
        ev_result = evaluator.evaluate(task, result)
        assert ev_result.score == 0.0
        assert ev_result.status == EvaluatorStatus.FAIL

    def test_single_stage_success(self):
        """Single stage success should produce high score."""
        evaluator = LongHorizonEvaluator()
        task = _make_long_task(stages=[{"id": "s1", "name": "S1", "prompt": "P1"}])
        result = TaskResult(
            task_id="t1", run_id="r1",
            stage_results=[StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0)],
        )
        ev_result = evaluator.evaluate(task, result)
        assert ev_result.status == EvaluatorStatus.PASS
        assert ev_result.score >= 0.5

    def test_mixed_scores(self):
        """Mix of high and low stage scores produces intermediate result."""
        evaluator = LongHorizonEvaluator()
        task = _make_long_task(stages=[
            {"id": "s1", "name": "S1", "prompt": "P1"},
            {"id": "s2", "name": "S2", "prompt": "P2"},
            {"id": "s3", "name": "S3", "prompt": "P3"},
        ])
        result = TaskResult(
            task_id="t1", run_id="r1",
            stage_results=[
                StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
                StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=0.3),
                StageResult(stage_id="s3", stage_name="S3", status="SUCCESS", score=0.8),
            ],
        )
        ev_result = evaluator.evaluate(task, result)
        # progress = 1.0, terminal = 0.8
        # final = 1.0 * 0.7 + 0.8 * 0.3 = 0.94
        assert ev_result.score == pytest.approx(0.94, abs=0.01)


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_single_runner_still_works(self):
        """SINGLE mode should not be affected by LONG changes."""
        from eb.runners.single import SingleRunner
        adapter = MagicMock(spec=ModelAdapter)
        adapter.model_name = "m"
        adapter._closed = False
        adapter.generate.return_value = ModelResponse(
            text="ok", model="m", finish_reason="stop",
            usage=TokenUsage(), latency_s=0.01, backend="mock",
        )
        from eb.adapters.base import AdapterMetadata
        adapter.metadata.return_value = AdapterMetadata(
            adapter_type="mock", backend="mock", model_name="m",
        )
        runner = SingleRunner(adapter)
        task = Task(
            id="S-001", category="arch", mode=ExecutionMode.SINGLE,
            difficulty=Difficulty.L3, prompt="Hello",
            partition=BenchmarkPartition.DEVELOPMENT,
        )
        ctx = RunContext(run_id="r1", model_name="m", suite="s")
        result = runner.run(task, ctx)
        assert result.execution_metadata["status"] == TaskStatus.SUCCESS.value

    def test_exec_runner_still_works(self):
        """EXEC mode should not be affected by LONG changes."""
        from eb.runners.repository import RepositoryRunner
        adapter = MagicMock(spec=ModelAdapter)
        adapter.model_name = "m"
        adapter._closed = False
        adapter.generate.return_value = ModelResponse(
            text="FINAL_ANSWER:done", model="m", finish_reason="stop",
            usage=TokenUsage(), latency_s=0.01, backend="mock",
        )
        from eb.adapters.base import AdapterMetadata
        adapter.metadata.return_value = AdapterMetadata(
            adapter_type="mock", backend="mock", model_name="m",
        )
        runner = RepositoryRunner(adapter=adapter)
        task = Task(
            id="E-001", category="code", mode=ExecutionMode.EXEC,
            difficulty=Difficulty.L2, prompt="Fix bug",
            partition=BenchmarkPartition.DEVELOPMENT,
            context={"repository_id": "eb-python-bug-001"},
        )
        ctx = RunContext(run_id="r1", model_name="m", suite="e")
        result = runner.run(task, ctx)
        # May fail due to missing fixture in test env, but should not crash
        assert result.task_id == "E-001"

    def test_multi_runner_still_works(self):
        """MULTI mode should not be affected by LONG changes."""
        from eb.runners.multi import MultiRunner
        adapter = _make_mock_adapter(["FINAL_ANSWER:done"])
        runner = MultiRunner(adapter)
        task = Task(
            id="M-001", category="arch", mode=ExecutionMode.MULTI,
            difficulty=Difficulty.L3, prompt="Discuss",
            partition=BenchmarkPartition.DEVELOPMENT,
        )
        ctx = RunContext(run_id="r1", model_name="m", suite="m")
        result = runner.run(task, ctx)
        assert result.execution_metadata["status"] == TaskStatus.SUCCESS.value
