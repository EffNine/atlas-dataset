"""Tests for evaluation orchestration — SINGLE task with evaluators end-to-end."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from eb.runners.single import SingleRunner
from eb.runners.base import RunContext, TaskStatus
from eb.runners.orchestration import RunOrchestrator
from eb.core.schema import Task, TaskResult
from eb.core.types import ExecutionMode, Difficulty, Capability, BenchmarkPartition, EvaluatorStatus
from eb.adapters.base import ModelAdapter, ModelRequest, ModelResponse, TokenUsage
from eb.evaluators.dispatcher import EvaluatorDispatcher


def _make_task(task_id: str = "EB-E2E-001", **overrides) -> Task:
    defaults = {
        "id": task_id,
        "category": "architecture",
        "mode": ExecutionMode.SINGLE,
        "difficulty": Difficulty.L3,
        "capabilities": [Capability.ARCH],
        "prompt": f"Task {task_id}",
        "partition": BenchmarkPartition.DEVELOPMENT,
        "context": {},
    }
    defaults.update(overrides)
    return Task.model_validate(defaults)


def _make_adapter(text: str = "response text") -> ModelAdapter:
    adapter = MagicMock(spec=ModelAdapter)
    adapter.model_name = "test-model"
    adapter._closed = False

    def gen(request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            text=text,
            model="test-model",
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=5, completion_tokens=10, total_tokens=15),
            latency_s=0.02,
            backend="mock",
        )

    adapter.generate = gen
    from eb.adapters.base import AdapterMetadata
    adapter.metadata.return_value = AdapterMetadata(
        adapter_type="mock", backend="mock", model_name="test-model",
    )
    return adapter


def _make_ctx(run_id: str = "run-e2e", repeat: int = 0) -> RunContext:
    return RunContext(
        run_id=run_id,
        model_name="test-model",
        suite="e2e",
        inference_settings={"seed": 42, "temperature": 0.0, "top_p": 1.0, "top_k": 0, "max_tokens": 4096},
        repeat_index=repeat,
    )


class TestEvaluationOrchestration:
    def test_single_task_with_exact_evaluator(self):
        """SINGLE task with exact evaluator produces raw_task_score."""
        adapter = _make_adapter("correct answer")
        runner = SingleRunner(adapter)
        task = _make_task(context={"expected": "correct answer"})
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.raw_task_score is not None
        assert result.raw_task_score == 1.0
        assert len(result.evaluator_results) == 1
        assert result.evaluator_results[0].status == EvaluatorStatus.PASS
        assert result.final_score is None  # Stage 3 does not compute EB Score

    def test_single_task_with_multiple_evaluators(self):
        """Task with multiple evaluators preserves all results."""
        adapter = _make_adapter("answer with claim X")
        runner = SingleRunner(adapter)
        task = _make_task(
            context={"expected": "answer with claim X"},
            evaluation={
                "evaluators": [
                    {"type": "exact", "required": True, "parameters": {"expected": "answer with claim X"}},
                    {"type": "evidence", "required": False, "parameters": {"required_claims": ["claim X"]}},
                ]
            }
        )
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert len(result.evaluator_results) == 2
        assert result.raw_task_score is not None
        # Both evaluators should pass
        for ev in result.evaluator_results:
            assert ev.status != EvaluatorStatus.ERROR

    def test_results_artifact_contains_evaluator_results(self, tmp_path: Path, monkeypatch):
        """Final artifact includes evaluator results."""
        task_dir = tmp_path / "tasks" / "architecture"
        task_dir.mkdir(parents=True, exist_ok=True)
        task = _make_task("EB-ART-001", context={"expected": "yes"})
        with (task_dir / "task.json").open("w") as f:
            json.dump(task.model_dump(), f)

        monkeypatch.setattr("eb.paths._EB_ROOT_CACHE", {"eb_root": tmp_path})

        mock_adapter = _make_adapter("yes")
        mock_factory = MagicMock()
        mock_factory.create_adapter.return_value = mock_adapter
        mock_factory.list_models.return_value = ["m"]

        orchestrator = RunOrchestrator(
            model_name="m",
            suite="test",
            partitions=["development"],
            repeats=1,
            adapter_factory=mock_factory,
            output_dir=tmp_path / "outputs",
        )
        summary = orchestrator.run()

        # Check results.jsonl
        results_lines = (summary.artifact_dir / "results.jsonl").read_text().strip().split("\n")
        assert len(results_lines) == 1
        record = json.loads(results_lines[0])
        assert "evaluator_results" in record
        assert len(record["evaluator_results"]) > 0
        assert record["evaluator_results"][0]["evaluator"] == "exact"
        assert record["evaluator_results"][0]["status"] == "PASS"
        assert "raw_task_score" in record

        # Check raw_scores.json exists
        raw_path = summary.artifact_dir / "raw_scores.json"
        assert raw_path.exists()
        raw_data = json.loads(raw_path.read_text())
        assert "task_scores" in raw_data
        assert "capability_scores" in raw_data
        assert raw_data["overall_task_count"] == 1

        mock_adapter.close()

    def test_task_result_preserves_raw_score(self):
        """TaskResult has raw_task_score set by runner."""
        adapter = _make_adapter("hi")
        runner = SingleRunner(adapter)
        task = _make_task(context={"expected": "hi"})
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.raw_task_score is not None
        assert isinstance(result.raw_task_score, float)
        assert result.evaluator_results  # Has evaluator outputs

    def test_no_eb_score_computed(self):
        """Stage 3 must NOT compute EB Score (final_score stays None)."""
        adapter = _make_adapter("answer")
        runner = SingleRunner(adapter)
        task = _make_task(context={"expected": "answer"})
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.final_score is None
        assert result.raw_task_score is not None

    def test_evaluator_error_does_not_crash_runner(self):
        """If an evaluator errors, the runner still produces a TaskResult."""
        adapter = _make_adapter("response")
        dispatcher = EvaluatorDispatcher()
        # Register a broken evaluator
        from eb.evaluators.base import Evaluator
        from eb.core.types import JudgeMode
        class BadEvaluator(Evaluator):
            @property
            def name(self): return "bad"
            @property
            def authority_level(self): return 1
            @property
            def supported_modes(self): return [JudgeMode.DETERMINISTIC]
            def is_applicable(self, task): return True
            def evaluate(self, task, result):
                raise ValueError("broken")
        dispatcher.register(BadEvaluator())

        runner = SingleRunner(adapter, dispatcher=dispatcher)
        task = _make_task(evaluation={
            "evaluators": [{"type": "bad", "required": False}]
        })
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.task_id == task.id
        assert result.execution_metadata["status"] == TaskStatus.SUCCESS.value
        # The bad evaluator result should be present with ERROR status
        bad_results = [e for e in result.evaluator_results if e.evaluator == "bad"]
        assert len(bad_results) == 1
        assert bad_results[0].status == EvaluatorStatus.ERROR

    def test_not_applicable_evaluator(self):
        """When exact evaluator has no expected answer, it returns NOT_APPLICABLE."""
        adapter = _make_adapter("some text")
        runner = SingleRunner(adapter)
        task = _make_task(context={})  # No expected answer
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        exact_results = [e for e in result.evaluator_results if e.evaluator == "exact"]
        assert len(exact_results) == 1
        assert exact_results[0].status == EvaluatorStatus.NOT_APPLICABLE
        # raw_task_score should be None when no applicable evaluators
        assert result.raw_task_score is None

    def test_repeated_runs_preserve_repeat_level_data(self, tmp_path: Path, monkeypatch):
        """Multiple repeats produce distinguishable raw scores."""
        task_dir = tmp_path / "tasks" / "architecture"
        task_dir.mkdir(parents=True, exist_ok=True)
        task = _make_task("EB-REP-001", context={"expected": "answer"})
        with (task_dir / "task.json").open("w") as f:
            json.dump(task.model_dump(), f)

        monkeypatch.setattr("eb.paths._EB_ROOT_CACHE", {"eb_root": tmp_path})

        call_count = [0]
        def counting_gen(request):
            call_count[0] += 1
            return ModelResponse(
                text=f"answer-{call_count[0]}",
                model="m", finish_reason="stop", usage=TokenUsage(),
                latency_s=0.01, backend="mock",
            )

        mock_adapter = _make_adapter()
        mock_adapter.generate = counting_gen
        from eb.adapters.base import AdapterMetadata
        mock_adapter.metadata.return_value = AdapterMetadata(
            adapter_type="mock", backend="mock", model_name="m",
        )
        mock_factory = MagicMock()
        mock_factory.create_adapter.return_value = mock_adapter
        mock_factory.list_models.return_value = ["m"]

        orchestrator = RunOrchestrator(
            model_name="m",
            suite="repeats",
            partitions=["development"],
            repeats=3,
            adapter_factory=mock_factory,
            output_dir=tmp_path / "outputs",
        )
        summary = orchestrator.run()

        raw_path = summary.artifact_dir / "raw_scores.json"
        raw_data = json.loads(raw_path.read_text())
        ts = raw_data["task_scores"]["EB-REP-001"]
        assert len(ts["repeat_scores"]) == 3
        assert ts["task_count"] == 3

        mock_adapter.close()
