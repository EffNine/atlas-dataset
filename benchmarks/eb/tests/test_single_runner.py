"""Tests for eb/runners/single.py — SINGLE mode runner."""
import pytest
from unittest.mock import MagicMock

from eb.runners.single import SingleRunner
from eb.runners.base import RunContext, TaskStatus
from eb.core.schema import Task, TaskResult
from eb.core.types import ExecutionMode, Difficulty, Capability, BenchmarkPartition, EvaluatorStatus
from eb.adapters.base import ModelAdapter, ModelRequest, ModelResponse, TokenUsage


def _make_task(task_id: str = "EB-TEST-001", mode: ExecutionMode = ExecutionMode.SINGLE) -> Task:
    return Task(
        id=task_id,
        category="architecture",
        mode=mode,
        difficulty=Difficulty.L3,
        capabilities=[Capability.ARCH],
        prompt=f"Describe {task_id}",
        partition=BenchmarkPartition.DEVELOPMENT,
    )


def _make_adapter(fail: bool = False, text: str = "response text", error: str | None = None) -> ModelAdapter:
    adapter = MagicMock(spec=ModelAdapter)
    adapter.model_name = "test-model"
    adapter._closed = False

    def gen(request: ModelRequest) -> ModelResponse:
        if adapter._closed:
            return ModelResponse(text="", model="test-model", error="Adapter has been closed", backend="test")
        if fail:
            raise RuntimeError(error or "adapter error")
        return ModelResponse(
            text=text,
            model="test-model",
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            latency_s=0.05,
            backend="test",
        )

    adapter.generate = gen
    meta_mock = MagicMock()
    meta_mock.to_dict.return_value = {"adapter_type": "test", "backend": "test"}
    adapter.metadata.return_value = meta_mock
    return adapter


def _make_ctx(run_id: str = "run-001", repeat: int = 0, **overrides) -> RunContext:
    defaults = {
        "run_id": run_id,
        "model_name": "test-model",
        "suite": "single",
        "inference_settings": {"seed": 42, "temperature": 0.0, "top_p": 1.0, "top_k": 0, "max_tokens": 4096},
        "repeat_index": repeat,
    }
    defaults.update(overrides)
    return RunContext(**defaults)


class TestSingleRunner:
    def test_runs_single_task(self):
        adapter = _make_adapter()
        runner = SingleRunner(adapter)
        task = _make_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert isinstance(result, TaskResult)
        assert result.task_id == "EB-TEST-001"
        assert result.run_id == "run-001"
        assert result.raw_response == "response text"
        assert result.execution_metadata["status"] == TaskStatus.SUCCESS.value
        assert result.execution_metadata["repeat_id"] == "r01"
        assert result.execution_metadata["adapter"] == "test"

    def test_preserves_inference_metadata(self):
        adapter = _make_adapter()
        runner = SingleRunner(adapter)
        task = _make_task()
        ctx = _make_ctx(inference_settings={"seed": 99, "temperature": 0.5, "top_p": 0.9, "top_k": 50, "max_tokens": 2048})

        result = runner.run(task, ctx)

        meta = result.execution_metadata
        assert meta["inference_settings"]["seed"] == 99
        assert meta["inference_settings"]["temperature"] == 0.5
        assert meta["inference_settings"]["max_tokens"] == 2048
        assert meta["token_usage"]["total_tokens"] == 15
        assert meta["latency_s"] > 0

    def test_preserves_repeat_id(self):
        adapter = _make_adapter()
        runner = SingleRunner(adapter)
        task = _make_task()

        ctx0 = _make_ctx(repeat=0)
        r0 = runner.run(task, ctx0)
        assert r0.execution_metadata["repeat_id"] == "r01"

        ctx1 = _make_ctx(repeat=1)
        r1 = runner.run(task, ctx1)
        assert r1.execution_metadata["repeat_id"] == "r02"

        ctx2 = _make_ctx(repeat=9)
        r2 = runner.run(task, ctx2)
        assert r2.execution_metadata["repeat_id"] == "r10"

    def test_rejects_non_single_mode(self):
        adapter = _make_adapter()
        runner = SingleRunner(adapter)
        task = _make_task(mode=ExecutionMode.MULTI)
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["status"] == TaskStatus.SKIPPED.value
        assert any("mode_mismatch" in f for f in result.flags)

    def test_rejects_exec_mode(self):
        adapter = _make_adapter()
        runner = SingleRunner(adapter)
        task = _make_task(mode=ExecutionMode.EXEC)
        ctx = _make_ctx()

        result = runner.run(task, ctx)
        assert result.execution_metadata["status"] == TaskStatus.SKIPPED.value

    def test_rejects_long_mode(self):
        adapter = _make_adapter()
        runner = SingleRunner(adapter)
        task = _make_task(mode=ExecutionMode.LONG)
        ctx = _make_ctx()

        result = runner.run(task, ctx)
        assert result.execution_metadata["status"] == TaskStatus.SKIPPED.value

    def test_adapter_error_becomes_task_error(self):
        adapter = _make_adapter(fail=True, error="connection refused")
        runner = SingleRunner(adapter)
        task = _make_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["status"] == TaskStatus.ERROR.value
        assert any("generation_error" in f for f in result.flags)
        assert result.raw_response is None

    def test_adapter_returns_error_response(self):
        adapter = MagicMock(spec=ModelAdapter)
        adapter.model_name = "test-model"
        adapter._closed = False
        adapter.generate.return_value = ModelResponse(
            text="",
            model="test-model",
            error="rate limited",
            backend="test",
        )
        adapter.metadata.return_value = MagicMock(to_dict=MagicMock(return_value={}))

        runner = SingleRunner(adapter)
        task = _make_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["status"] == TaskStatus.ERROR.value
        assert any("adapter_error" in f for f in result.flags)

    def test_runner_mode_property(self):
        adapter = _make_adapter()
        runner = SingleRunner(adapter)
        assert runner.mode == ExecutionMode.SINGLE

    def test_closed_adapter(self):
        adapter = _make_adapter()
        adapter.close()
        # MagicMock.close() doesn't actually set _closed, set it manually
        adapter._closed = True
        runner = SingleRunner(adapter)
        task = _make_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)
        assert result.execution_metadata["status"] == TaskStatus.ERROR.value

    def test_task_result_no_eb_score(self):
        """Stage 3 must not compute EB Score (final_score stays None)."""
        adapter = _make_adapter()
        runner = SingleRunner(adapter)
        task = _make_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)
        assert result.final_score is None
        # Evaluators run but may produce NOT_APPLICABLE when no expected answer
        assert all(
            e.status in (EvaluatorStatus.NOT_APPLICABLE, EvaluatorStatus.PASS, EvaluatorStatus.FAIL)
            for e in result.evaluator_results
        )

    def test_timestamps_present(self):
        adapter = _make_adapter()
        runner = SingleRunner(adapter)
        task = _make_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)
        ts = result.execution_metadata.get("timestamp")
        assert ts is not None
        assert "T" in ts  # ISO format


class TestSingleRunnerBatch:
    def test_batch_extracts_success_and_failures(self):
        adapter = _make_adapter()
        runner = SingleRunner(adapter)
        tasks = [_make_task(f"EB-TEST-{i:03d}") for i in range(3)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)
        assert len(results) == 3
        assert all(r.execution_metadata["status"] == TaskStatus.SUCCESS.value for r in results)

    def test_batch_continues_on_failure(self):
        call_count = 0

        def failing_gen(request):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                raise RuntimeError("boom")
            return ModelResponse(text="ok", model="m", finish_reason="stop", usage=TokenUsage(), backend="test")

        adapter = MagicMock(spec=ModelAdapter)
        adapter.model_name = "m"
        adapter._closed = False
        adapter.generate = failing_gen
        adapter.metadata.return_value = MagicMock(to_dict=MagicMock(return_value={}))

        runner = SingleRunner(adapter)
        tasks = [_make_task(f"EB-TEST-{i:03d}") for i in range(3)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)
        assert len(results) == 3
        # First task failed, rest succeeded
        assert results[0].execution_metadata["status"] == TaskStatus.ERROR.value
        assert results[1].execution_metadata["status"] == TaskStatus.SUCCESS.value
        assert results[2].execution_metadata["status"] == TaskStatus.SUCCESS.value
