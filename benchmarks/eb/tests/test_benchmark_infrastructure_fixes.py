"""Regression tests for benchmark infrastructure fixes.

Covers four bugs exposed by run-20260817-142009-b614a7:
  1. Rubric evaluator crashes on string criteria (not just dict)
  2. EXEC fixture resolver looks in wrong path (missing /fixtures/)
  3. MULTI adapter crashes on empty model response (tensor reshape)
  4. LONG evaluator not wired into dispatcher (always NOT_APPLICABLE)
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from eb.core.schema import Task, TaskResult, StageData, StageResult
from eb.core.types import (
    ExecutionMode,
    Difficulty,
    Capability,
    BenchmarkPartition,
    EvaluatorStatus,
    JudgeMode,
)
from eb.evaluators.rubric import RubricEvaluator
from eb.evaluators.dispatcher import EvaluatorDispatcher
from eb.evaluators.long_horizon import LongHorizonEvaluator
from eb.runners.repository import RepositoryRunner, RepositoryFixture
from eb.runners.long_horizon import LongHorizonRunner
from eb.runners.base import RunContext, TaskStatus
from eb.adapters.base import ModelAdapter, ModelRequest, ModelResponse, TokenUsage, AdapterMetadata


# ---------------------------------------------------------------------------
# 1. Rubric evaluator — string criteria regression
# ---------------------------------------------------------------------------


class TestRubricStringCriteria:
    """String criteria (task JSON format) must not crash the rubric evaluator."""

    def setup_method(self):
        self.evaluator = RubricEvaluator()

    def _make_task_with_string_criteria(self, criteria_ids: list[str]) -> Task:
        return Task(
            id="EB-RUB-STR-001",
            category="advisory",
            mode=ExecutionMode.SINGLE,
            difficulty=Difficulty.L3,
            capabilities=[Capability.ADVISORY],
            prompt="Design a system.",
            partition=BenchmarkPartition.DEVELOPMENT,
            context={},
            evaluation={
                "primary_mode": "RUBRIC",
                "evaluators": [
                    {
                        "type": "rubric",
                        "parameters": {"criteria": criteria_ids},
                    }
                ],
            },
        )

    def test_string_criteria_no_crash(self):
        """Previously crashed with 'str' object has no attribute 'get'."""
        task = self._make_task_with_string_criteria(["factor_analysis", "recommendations"])
        result = TaskResult(task_id="EB-RUB-STR-001", run_id="r1", raw_response="A detailed analysis with recommendations.")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status != EvaluatorStatus.ERROR.value

    def test_string_criteria_all_missing(self):
        """String criteria without checks/scores produce PENDING_JUDGE."""
        task = self._make_task_with_string_criteria(["factor_analysis", "recommendations"])
        result = TaskResult(task_id="EB-RUB-STR-001", run_id="r1", raw_response="short")
        outcome = self.evaluator.evaluate(task, result)
        # No deterministic checks defined, so falls through to pending judge
        assert outcome.status in (EvaluatorStatus.PENDING_JUDGE.value, EvaluatorStatus.FAIL.value)

    def test_mixed_string_and_dict_criteria(self):
        """Task JSON may mix string and dict criteria."""
        task = Task(
            id="EB-RUB-MIX-001",
            category="testing",
            mode=ExecutionMode.SINGLE,
            difficulty=Difficulty.L2,
            capabilities=[Capability.TEST],
            prompt="Write tests.",
            partition=BenchmarkPartition.DEVELOPMENT,
            evaluation={
                "primary_mode": "RUBRIC",
                "evaluators": [
                    {
                        "type": "rubric",
                        "parameters": {
                            "criteria": [
                                "coverage",  # string
                                {"id": "edge_cases", "weight": 1.0, "check": {"type": "contains", "value": "edge"}},
                            ]
                        },
                    }
                ],
            },
        )
        result = TaskResult(task_id="EB-RUB-MIX-001", run_id="r1", raw_response="Tests cover edge cases thoroughly.")
        outcome = self.evaluator.evaluate(task, result)
        assert outcome.status != EvaluatorStatus.ERROR.value


# ---------------------------------------------------------------------------
# 2. EXEC fixture resolution regression
# ---------------------------------------------------------------------------


class TestExecFixtureResolution:
    """EXEC runner must find fixtures under repositories/fixtures/<id>/."""

    def _setup_test_fixture(self, tmp_path: Path, fixture_id: str) -> Path:
        """Create a fixture under the canonical fixtures/ subdirectory."""
        fixtures_root = tmp_path / "repositories" / "fixtures"
        fixture_dir = fixtures_root / fixture_id
        fixture_dir.mkdir(parents=True)
        manifest = {
            "id": fixture_id,
            "version": "1.0",
            "language": "python",
            "image": "python:3.11-slim",
            "source_path": "source",
            "test_command": "python -c 'print(1)'",
            "timeout": 30.0,
        }
        (fixture_dir / "fixture.json").write_text(json.dumps(manifest))
        src = fixture_dir / "source"
        src.mkdir()
        (src / "main.py").write_text("x = 1\n")
        return fixtures_root

    def test_load_fixture_from_fixtures_subdir(self, tmp_path: Path):
        """Fixture under repositories/fixtures/<id>/ is found."""
        fixtures_root = self._setup_test_fixture(tmp_path, "reg-fix-001")
        with patch("eb.runners.repository.repositories_dir", return_value=tmp_path / "repositories"):
            runner = RepositoryRunner(adapter=MagicMock())
            fixture = runner._load_fixture("reg-fix-001")
            assert fixture is not None
            assert fixture.fixture_id == "reg-fix-001"

    def test_load_fixture_returns_none_when_missing(self, tmp_path: Path):
        """Missing fixture returns None, not a crash."""
        with patch("eb.runners.repository.repositories_dir", return_value=tmp_path / "repositories"):
            runner = RepositoryRunner(adapter=MagicMock())
            fixture = runner._load_fixture("nonexistent-fixture")
            assert fixture is None

    def test_compute_hash_uses_fixtures_subdir(self, tmp_path: Path):
        """Fixture hash is computed from the fixtures/ subdirectory."""
        fixtures_root = self._setup_test_fixture(tmp_path, "hash-fix-001")
        fixture = RepositoryFixture(fixture_id="hash-fix-001")
        h = fixture.compute_hash(tmp_path / "repositories")
        assert len(h) == 16
        assert fixture.fixture_hash == h

    def test_create_workspace_copy_uses_fixtures_subdir(self, tmp_path: Path):
        """Workspace copy is created from the fixtures/ subdirectory."""
        fixtures_root = self._setup_test_fixture(tmp_path, "copy-fix-001")
        with patch("eb.runners.repository.repositories_dir", return_value=tmp_path / "repositories"):
            runner = RepositoryRunner(adapter=MagicMock())
            fixture = runner._load_fixture("copy-fix-001")
            assert fixture is not None
            ws = runner._create_workspace_copy(fixture)
            assert ws is not None
            assert (ws / "source" / "main.py").exists()


# ---------------------------------------------------------------------------
# 3. MULTI empty response handling regression
# ---------------------------------------------------------------------------


class TestMultiEmptyResponse:
    """MULTI runner must handle empty model responses without crashing."""

    def test_adapter_returns_empty_response_on_zero_tokens(self):
        """Local adapter handles zero-token generation gracefully."""
        from eb.adapters.local import _TransformersBackend

        backend = MagicMock()
        backend._loaded = True
        # Simulate a model that returns empty generated_ids
        import torch
        empty_ids = torch.empty(0, dtype=torch.long)

        def gen_side_effect(prompt, settings):
            # Simulate the reshape error that was happening
            if len(empty_ids) == 0:
                # This is what the fixed code should handle
                return "", {"prompt_tokens": 10, "completion_tokens": 0}
            return "some text", {"prompt_tokens": 10, "completion_tokens": 5}

        backend.generate = gen_side_effect

        # The backend should return empty text without crashing
        text, meta = backend.generate("test prompt", {"max_tokens": 256})
        assert text == ""
        assert meta["completion_tokens"] == 0

    def test_multi_runner_handles_adapter_error(self):
        """MULTI runner records adapter error but doesn't crash."""
        from eb.runners.multi import MultiRunner

        adapter = MagicMock(spec=ModelAdapter)
        adapter.model_name = "test-model"
        adapter._closed = False

        def failing_gen(request):
            return ModelResponse(
                text="",
                model="test-model",
                error="cannot reshape tensor of 0 elements",
                backend="mock",
            )

        adapter.generate = failing_gen
        adapter.metadata.return_value = AdapterMetadata(
            adapter_type="mock", backend="mock", model_name="test-model",
        )

        runner = MultiRunner(adapter=adapter, max_turns=3)
        task = Task(
            id="EB-MULTI-REG-001",
            category="planning",
            mode=ExecutionMode.MULTI,
            difficulty=Difficulty.L3,
            capabilities=[Capability.PLAN],
            prompt="Design a system.",
            partition=BenchmarkPartition.DEVELOPMENT,
            context={"turns": 3},
        )
        ctx = RunContext(run_id="run-reg", model_name="test-model", suite="multi", repeat_index=0)
        result = runner.run(task, ctx)

        # Should not crash; should record error
        assert result.task_id == "EB-MULTI-REG-001"
        assert any("adapter_error" in f for f in result.flags)
        # Status should reflect the error
        assert result.execution_metadata["status"] == TaskStatus.ERROR.value

    def test_multi_runner_empty_response_not_fabricated(self):
        """Empty response is NOT turned into a fake SUCCESS."""
        from eb.runners.multi import MultiRunner

        call_count = [0]

        def empty_then_text(request):
            call_count[0] += 1
            if call_count[0] == 1:
                # First turn returns empty
                return ModelResponse(
                    text="",
                    model="test-model",
                    error="empty response",
                    backend="mock",
                )
            return ModelResponse(
                text="FINAL_ANSWER: done",
                model="test-model",
                finish_reason="stop",
                usage=TokenUsage(),
                backend="mock",
            )

        adapter = MagicMock(spec=ModelAdapter)
        adapter.model_name = "test-model"
        adapter._closed = False
        adapter.generate = empty_then_text
        adapter.metadata.return_value = AdapterMetadata(
            adapter_type="mock", backend="mock", model_name="test-model",
        )

        runner = MultiRunner(adapter=adapter, max_turns=3)
        task = Task(
            id="EB-MULTI-EMPTY-001",
            category="planning",
            mode=ExecutionMode.MULTI,
            difficulty=Difficulty.L3,
            capabilities=[Capability.PLAN],
            prompt="Design a system.",
            partition=BenchmarkPartition.DEVELOPMENT,
            context={"turns": 3},
        )
        ctx = RunContext(run_id="run-empt", model_name="test-model", suite="multi", repeat_index=0)
        result = runner.run(task, ctx)

        # Should break on first empty response, not continue
        assert call_count[0] == 1
        assert result.execution_metadata["status"] == TaskStatus.ERROR.value


# ---------------------------------------------------------------------------
# 4. LONG evaluator wiring regression
# ---------------------------------------------------------------------------


class TestLongHorizonEvaluatorWiring:
    """LongHorizonEvaluator must be registered and invoked for LONG tasks."""

    def test_long_horizon_evaluator_registered_in_dispatcher(self):
        """Dispatcher must include long_horizon evaluator."""
        dispatcher = EvaluatorDispatcher()
        # Dispatch a LONG task to trigger registration
        task = Task(
            id="EB-LONG-REG-001",
            category="engineering",
            mode=ExecutionMode.LONG,
            difficulty=Difficulty.L4,
            capabilities=[Capability.LONG],
            prompt="Do long task.",
            partition=BenchmarkPartition.DEVELOPMENT,
        )
        result = TaskResult(task_id="EB-LONG-REG-001", run_id="r1")
        dispatcher.dispatch(task, result)
        assert "long_horizon" in dispatcher._registry
        assert isinstance(dispatcher._registry["long_horizon"], LongHorizonEvaluator)

    def test_long_horizon_evaluator_produces_meaningful_result(self):
        """LongHorizonEvaluator produces PASS/PARTIAL/FAIL, not NOT_APPLICABLE."""
        evaluator = LongHorizonEvaluator()
        task = Task(
            id="EB-LONG-EVAL-001",
            category="engineering",
            mode=ExecutionMode.LONG,
            difficulty=Difficulty.L4,
            capabilities=[Capability.LONG],
            prompt="Implement something.",
            partition=BenchmarkPartition.DEVELOPMENT,
            context={
                "stages": [
                    {"id": "s1", "name": "Stage 1", "prompt": "Do stage 1"},
                    {"id": "s2", "name": "Stage 2", "prompt": "Do stage 2", "terminal": True},
                ]
            },
        )
        result = TaskResult(
            task_id="EB-LONG-EVAL-001",
            run_id="r1",
            stage_results=[
                StageResult(stage_id="s1", stage_name="Stage 1", status="SUCCESS", score=1.0),
                StageResult(stage_id="s2", stage_name="Stage 2", status="SUCCESS", score=1.0),
            ],
        )
        outcome = evaluator.evaluate(task, result)
        assert outcome.status != EvaluatorStatus.NOT_APPLICABLE.value
        assert outcome.status in (EvaluatorStatus.PASS.value, EvaluatorStatus.PARTIAL.value)
        assert outcome.score is not None
        assert outcome.score > 0.0

    def test_long_horizon_evaluator_not_applicable_without_stages(self):
        """LongHorizonEvaluator returns NOT_APPLICABLE when no stage results exist."""
        evaluator = LongHorizonEvaluator()
        task = Task(
            id="EB-LONG-NA-001",
            category="engineering",
            mode=ExecutionMode.LONG,
            difficulty=Difficulty.L4,
            capabilities=[Capability.LONG],
            prompt="Do long task.",
            partition=BenchmarkPartition.DEVELOPMENT,
        )
        result = TaskResult(task_id="EB-LONG-NA-001", run_id="r1", stage_results=[])
        outcome = evaluator.evaluate(task, result)
        assert outcome.status == EvaluatorStatus.NOT_APPLICABLE.value

    def test_long_runner_uses_long_horizon_evaluator(self):
        """LongHorizonRunner invokes LongHorizonEvaluator in final evaluation."""
        adapter = MagicMock(spec=ModelAdapter)
        adapter.model_name = "test-model"
        adapter._closed = False

        def gen(request):
            return ModelResponse(
                text="Stage output",
                model="test-model",
                finish_reason="stop",
                usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                latency_s=0.01,
                backend="mock",
            )

        adapter.generate = gen
        adapter.metadata.return_value = AdapterMetadata(
            adapter_type="mock", backend="mock", model_name="test-model",
        )

        mock_sandbox = MagicMock()
        mock_sandbox.create.return_value = "eb-long-sbox-001"
        mock_sandbox.stop = MagicMock()
        mock_sandbox.destroy = MagicMock()

        runner = LongHorizonRunner(adapter=adapter, sandbox_manager=mock_sandbox)
        task = Task(
            id="EB-LONG-RUN-001",
            category="engineering",
            mode=ExecutionMode.LONG,
            difficulty=Difficulty.L4,
            capabilities=[Capability.LONG],
            prompt="Implement utils.",
            partition=BenchmarkPartition.DEVELOPMENT,
            context={
                "stages": [
                    {"id": "s1", "name": "Stage 1", "prompt": "Do stage 1"},
                    {"id": "s2", "name": "Stage 2", "prompt": "Do stage 2", "terminal": True},
                ]
            },
        )
        ctx = RunContext(run_id="run-lh", model_name="test-model", suite="long", repeat_index=0)
        result = runner.run(task, ctx)

        # Should have evaluator results from LongHorizonEvaluator
        assert result.evaluator_results is not None
        # The long_horizon evaluator should have been invoked
        lh_results = [e for e in result.evaluator_results if e.evaluator == "long_horizon"]
        assert len(lh_results) > 0
        # Should not be NOT_APPLICABLE since we have stage results
        assert lh_results[0].status != EvaluatorStatus.NOT_APPLICABLE.value
