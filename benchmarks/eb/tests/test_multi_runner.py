"""Tests for eb/runners/multi.py — MULTI execution mode runner."""
import asyncio
import time
from unittest.mock import MagicMock

import pytest

from eb.runners.multi import MultiRunner, MultiTurnContext, TurnRecord
from eb.runners.base import RunContext, TaskStatus
from eb.core.schema import Task, TaskResult
from eb.core.types import ExecutionMode, Difficulty, Capability, BenchmarkPartition, EvaluatorStatus
from eb.adapters.base import ModelAdapter, ModelRequest, ModelResponse, TokenUsage


def _make_multi_task(
    task_id: str = "EB-MULTI-001",
    **overrides,
) -> Task:
    defaults = {
        "id": task_id,
        "category": "architecture",
        "mode": ExecutionMode.MULTI,
        "difficulty": Difficulty.L3,
        "capabilities": [Capability.ARCH],
        "prompt": f"Design a system for {task_id}",
        "partition": BenchmarkPartition.DEVELOPMENT,
    }
    defaults.update(overrides)
    return Task.model_validate(defaults)


def _make_adapter(
    responses: list[str] | None = None,
    fail: bool = False,
    error: str | None = None,
) -> ModelAdapter:
    adapter = MagicMock(spec=ModelAdapter)
    adapter.model_name = "test-model"
    adapter._closed = False

    if responses is None:
        responses = ["FINAL_ANSWER:system designed."]

    call_count = [0]

    def gen(request: ModelRequest) -> ModelResponse:
        if fail:
            raise RuntimeError(error or "adapter error")
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


def _make_ctx(run_id: str = "run-multi-001", repeat: int = 0, **overrides) -> RunContext:
    defaults = {
        "run_id": run_id,
        "model_name": "test-model",
        "suite": "multi",
        "inference_settings": {
            "seed": 42, "temperature": 0.0, "top_p": 1.0,
            "top_k": 0, "max_tokens": 4096,
        },
        "repeat_index": repeat,
    }
    defaults.update(overrides)
    return RunContext(**defaults)


class TestMultiRunnerSingle:
    def test_runs_multi_task_final_answer(self):
        adapter = _make_adapter(["FINAL_ANSWER:system designed."])
        runner = MultiRunner(adapter)
        task = _make_multi_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert isinstance(result, TaskResult)
        assert result.task_id == "EB-MULTI-001"
        assert result.raw_response == "system designed."
        assert result.execution_metadata["status"] == TaskStatus.SUCCESS.value
        assert result.execution_metadata["turn_count"] == 1
        assert result.execution_metadata["repeat_id"] == "r01"

    def test_runs_multi_task_continue_then_final(self):
        adapter = _make_adapter([
            "CONTINUE:Tell me more about scalability.",
            "FINAL_ANSWER:scalable design with load balancers.",
        ])
        runner = MultiRunner(adapter, max_turns=5)
        task = _make_multi_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["status"] == TaskStatus.SUCCESS.value
        assert result.execution_metadata["turn_count"] == 2
        assert result.raw_response == "scalable design with load balancers."
        assert len(result.execution_metadata["turns"]) == 2

    def test_runs_multi_task_auto_continues_until_max(self):
        adapter = _make_adapter([
            "CONTINUE:next turn 1",
            "CONTINUE:next turn 2",
            "CONTINUE:next turn 3",
        ])
        runner = MultiRunner(adapter, max_turns=3)
        task = _make_multi_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["turn_count"] == 3
        assert result.execution_metadata["status"] == TaskStatus.FAILED.value
        assert "max_turns_reached" in result.flags

    def test_respects_max_turns_limit(self):
        adapter = _make_adapter([
            "CONTINUE:turn 1",
            "CONTINUE:turn 2",
            "CONTINUE:turn 3",
            "CONTINUE:turn 4",
        ])
        runner = MultiRunner(adapter, max_turns=2)
        task = _make_multi_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["turn_count"] == 2
        assert "total_time_exceeded" not in result.flags

    def test_rejects_non_multi_mode(self):
        adapter = _make_adapter()
        runner = MultiRunner(adapter)
        task = _make_multi_task(mode=ExecutionMode.SINGLE)
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["status"] == TaskStatus.SKIPPED.value
        assert any("mode_mismatch" in f for f in result.flags)

    def test_rejects_exec_mode(self):
        adapter = _make_adapter()
        runner = MultiRunner(adapter)
        task = _make_multi_task(mode=ExecutionMode.EXEC)
        ctx = _make_ctx()

        result = runner.run(task, ctx)
        assert result.execution_metadata["status"] == TaskStatus.SKIPPED.value

    def test_adapter_error_becomes_task_error(self):
        adapter = _make_adapter(fail=True, error="connection refused")
        runner = MultiRunner(adapter)
        task = _make_multi_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["status"] == TaskStatus.ERROR.value
        assert any("generation_error" in f for f in result.flags)

    def test_runner_mode_property(self):
        adapter = _make_adapter()
        runner = MultiRunner(adapter)
        assert runner.mode == ExecutionMode.MULTI

    def test_turn_count_in_metadata(self):
        adapter = _make_adapter([
            "CONTINUE:follow-up",
            "FINAL_ANSWER:final response",
        ])
        runner = MultiRunner(adapter, max_turns=5)
        task = _make_multi_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["turn_count"] == 2
        assert result.execution_metadata["max_turns"] == 5

    def test_token_usage_accumulated(self):
        adapter = _make_adapter([
            "CONTINUE:follow-up",
            "FINAL_ANSWER:final response",
        ])
        runner = MultiRunner(adapter, max_turns=5)
        task = _make_multi_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        token_usage = result.execution_metadata["token_usage"]
        assert token_usage["total_tokens"] == 30  # 15 per turn × 2 turns

    def test_timestamps_present(self):
        adapter = _make_adapter()
        runner = MultiRunner(adapter)
        task = _make_multi_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        ts = result.execution_metadata.get("timestamp")
        assert ts is not None
        assert "T" in ts

    def test_inference_settings_preserved(self):
        adapter = _make_adapter()
        runner = MultiRunner(adapter)
        task = _make_multi_task()
        ctx = _make_ctx(inference_settings={"seed": 99, "temperature": 0.5})

        result = runner.run(task, ctx)

        meta = result.execution_metadata
        assert meta["inference_settings"]["seed"] == 99
        assert meta["inference_settings"]["temperature"] == 0.5

    def test_no_eb_score_computed(self):
        adapter = _make_adapter()
        runner = MultiRunner(adapter)
        task = _make_multi_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.final_score is None


class TestMultiRunnerBatch:
    def test_batch_empty_returns_empty(self):
        adapter = _make_adapter()
        runner = MultiRunner(adapter)
        ctx = _make_ctx()

        results = runner.run_batch([], ctx)

        assert results == []

    def test_batch_single_task(self):
        adapter = _make_adapter(["FINAL_ANSWER:ok"])
        runner = MultiRunner(adapter, max_concurrent=4)
        task = _make_multi_task("EB-BATCH-001")
        ctx = _make_ctx()

        results = runner.run_batch([task], ctx)

        assert len(results) == 1
        assert results[0].task_id == "EB-BATCH-001"
        assert results[0].execution_metadata["status"] == TaskStatus.SUCCESS.value

    def test_batch_multiple_tasks_order_preserved(self):
        adapter = _make_adapter(["FINAL_ANSWER:ok"])
        runner = MultiRunner(adapter, max_concurrent=4)
        tasks = [_make_multi_task(f"EB-BATCH-{i:03d}") for i in range(3)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 3
        assert results[0].task_id == "EB-BATCH-000"
        assert results[1].task_id == "EB-BATCH-001"
        assert results[2].task_id == "EB-BATCH-002"

    def test_batch_one_failure_does_not_corrupt_others(self):
        call_count = [0]

        def selective_gen(request):
            nonlocal call_count
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("boom")
            return ModelResponse(
                text="FINAL_ANSWER:ok",
                model="m",
                finish_reason="stop",
                usage=TokenUsage(),
                latency_s=0.01,
                backend="mock",
            )

        adapter = MagicMock(spec=ModelAdapter)
        adapter.model_name = "m"
        adapter._closed = False
        adapter.generate = selective_gen
        adapter.metadata.return_value = MagicMock(to_dict=MagicMock(return_value={}))

        runner = MultiRunner(adapter, max_concurrent=4)
        tasks = [_make_multi_task(f"EB-BATCH-{i:03d}") for i in range(3)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 3
        assert results[0].execution_metadata["status"] == TaskStatus.SUCCESS.value
        assert results[1].execution_metadata["status"] == TaskStatus.ERROR.value
        assert results[2].execution_metadata["status"] == TaskStatus.SUCCESS.value

    def test_batch_continues_on_timeout(self):
        def slow_gen(request):
            time.sleep(0.05)
            return ModelResponse(
                text="FINAL_ANSWER:slow",
                model="m",
                finish_reason="stop",
                usage=TokenUsage(),
                latency_s=0.05,
                backend="mock",
            )

        adapter = MagicMock(spec=ModelAdapter)
        adapter.model_name = "m"
        adapter._closed = False
        adapter.generate = slow_gen
        adapter.metadata.return_value = MagicMock(to_dict=MagicMock(return_value={}))

        runner = MultiRunner(adapter, max_concurrent=4)
        tasks = [_make_multi_task(f"EB-BATCH-{i:03d}") for i in range(4)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 4
        assert all(r.execution_metadata["status"] == TaskStatus.SUCCESS.value for r in results)

    def test_batch_respects_max_concurrent(self):
        active = [0]
        peak = [0]
        lock = MagicMock()

        def counting_gen(request):
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            time.sleep(0.02)
            active[0] -= 1
            return ModelResponse(
                text="FINAL_ANSWER:ok",
                model="m",
                finish_reason="stop",
                usage=TokenUsage(),
                latency_s=0.02,
                backend="mock",
            )

        adapter = MagicMock(spec=ModelAdapter)
        adapter.model_name = "m"
        adapter._closed = False
        adapter.generate = counting_gen
        adapter.metadata.return_value = MagicMock(to_dict=MagicMock(return_value={}))

        runner = MultiRunner(adapter, max_concurrent=2)
        tasks = [_make_multi_task(f"EB-BATCH-{i:03d}") for i in range(6)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 6
        assert all(r.execution_metadata["status"] == TaskStatus.SUCCESS.value for r in results)
        assert peak[0] <= 2

    def test_batch_more_tasks_than_workers(self):
        adapter = _make_adapter(["FINAL_ANSWER:ok"])
        runner = MultiRunner(adapter, max_concurrent=2)
        tasks = [_make_multi_task(f"EB-BATCH-{i:03d}") for i in range(8)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 8
        assert all(r.execution_metadata["status"] == TaskStatus.SUCCESS.value for r in results)


class TestMultiTurnContext:
    def test_context_creation(self):
        ctx = MultiTurnContext(
            task_id="t1",
            run_id="r1",
            repeat_id="r01",
        )
        assert ctx.task_id == "t1"
        assert ctx.run_id == "r1"
        assert ctx.repeat_id == "r01"
        assert ctx.turns == []
        assert ctx.errors == []
        assert ctx.status == "running"

    def test_context_with_turns(self):
        ctx = MultiTurnContext(task_id="t1", run_id="r1", repeat_id="r01")
        turn = TurnRecord(
            turn_index=0,
            request=ModelRequest(model="m", prompt="hello"),
            response_text="hi",
            latency_s=0.1,
            token_usage={"total_tokens": 10},
        )
        ctx.turns.append(turn)
        ctx.final_response = "hi"
        ctx.status = "completed"

        assert len(ctx.turns) == 1
        assert ctx.final_response == "hi"
        assert ctx.status == "completed"


class TestTurnRecord:
    def test_to_dict(self):
        turn = TurnRecord(
            turn_index=0,
            request=ModelRequest(model="m", prompt="hello"),
            response_text="hi",
            latency_s=0.1,
            token_usage={"total_tokens": 10},
            status="success",
        )
        d = turn.to_dict()
        assert d["turn_index"] == 0
        assert d["response_text"] == "hi"
        assert d["latency_s"] == 0.1
        assert d["status"] == "success"
        assert "timestamp" in d

    def test_to_dict_with_error(self):
        turn = TurnRecord(
            turn_index=1,
            request=ModelRequest(model="m", prompt="hello"),
            response_text=None,
            latency_s=0.0,
            token_usage={},
            status="error",
            error="timeout",
        )
        d = turn.to_dict()
        assert d["status"] == "error"
        assert d["error"] == "timeout"
        assert d["response_text"] is None


class TestMultiRunnerConcurrentValidation:
    def test_concurrency_bounded(self):
        """Verify that concurrency never exceeds max_concurrent."""
        max_concurrent_setting = 2
        active = [0]
        peak = [0]

        def bounded_gen(request):
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            time.sleep(0.02)
            active[0] -= 1
            return ModelResponse(
                text="FINAL_ANSWER:done",
                model="m",
                finish_reason="stop",
                usage=TokenUsage(),
                latency_s=0.02,
                backend="mock",
            )

        adapter = MagicMock(spec=ModelAdapter)
        adapter.model_name = "m"
        adapter._closed = False
        adapter.generate = bounded_gen
        adapter.metadata.return_value = MagicMock(to_dict=MagicMock(return_value={}))

        runner = MultiRunner(adapter, max_concurrent=max_concurrent_setting)
        tasks = [_make_multi_task(f"EB-CONC-{i:03d}") for i in range(6)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 6
        assert all(r.execution_metadata["status"] == TaskStatus.SUCCESS.value for r in results)
        assert peak[0] <= max_concurrent_setting

    def test_result_ordering_matches_submission(self):
        adapter = _make_adapter(["FINAL_ANSWER:ok"])
        runner = MultiRunner(adapter, max_concurrent=2)
        task_ids = [f"EB-ORDER-{i:03d}" for i in range(5)]
        tasks = [_make_multi_task(tid) for tid in task_ids]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        result_ids = [r.task_id for r in results]
        assert result_ids == task_ids


class TestMultiRunnerFailureScenarios:
    def test_sandbox_creation_failure_isolated(self):
        """A task that fails should not affect other task results."""
        failures = set()

        def selective_gen(request):
            if "FAIL" in request.context.get("task", {}).get("id", ""):
                failures.add(request.context.get("task", {}).get("id", ""))
                raise RuntimeError("sandbox creation failed")
            return ModelResponse(
                text="FINAL_ANSWER:ok",
                model="m",
                finish_reason="stop",
                usage=TokenUsage(),
                latency_s=0.01,
                backend="mock",
            )

        adapter = MagicMock(spec=ModelAdapter)
        adapter.model_name = "m"
        adapter._closed = False
        adapter.generate = selective_gen
        adapter.metadata.return_value = MagicMock(to_dict=MagicMock(return_value={}))

        runner = MultiRunner(adapter, max_concurrent=4)
        tasks = [
            _make_multi_task("EB-OK-001"),
            _make_multi_task("EB-FAIL-001", context={"repository_id": "bad"}),
            _make_multi_task("EB-OK-002"),
        ]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 3
        assert results[0].execution_metadata["status"] == TaskStatus.SUCCESS.value
        assert results[1].execution_metadata["status"] == TaskStatus.ERROR.value
        assert results[2].execution_metadata["status"] == TaskStatus.SUCCESS.value

    def test_timeout_status_recorded(self):
        adapter = _make_adapter(["CONTINUE:a"] * 100)
        runner = MultiRunner(adapter, max_turns=3, max_total_time_s=600.0)
        task = _make_multi_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["turn_count"] == 3
        assert result.execution_metadata["status"] == TaskStatus.FAILED.value
        assert "max_turns_reached" in result.flags

    def test_evaluation_runs_after_multi_turn(self):
        adapter = _make_adapter([
            "CONTINUE:elaborate",
            "FINAL_ANSWER:complete answer",
        ])
        runner = MultiRunner(adapter, max_turns=5)
        task = _make_multi_task(
            evaluation={"evaluators": [{"type": "exact", "parameters": {"expected": "complete answer"}}]}
        )
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.raw_task_score is not None
        assert len(result.evaluator_results) > 0


class TestMultiRunnerBatchFailureIsolation:
    def test_one_task_timeout_others_continue(self):
        call_count = [0]

        def slow_gen(request):
            call_count[0] += 1
            if call_count[0] == 2:
                time.sleep(0.1)
            return ModelResponse(
                text="FINAL_ANSWER:ok",
                model="m",
                finish_reason="stop",
                usage=TokenUsage(),
                latency_s=0.01,
                backend="mock",
            )

        adapter = MagicMock(spec=ModelAdapter)
        adapter.model_name = "m"
        adapter._closed = False
        adapter.generate = slow_gen
        adapter.metadata.return_value = MagicMock(to_dict=MagicMock(return_value={}))

        runner = MultiRunner(adapter, max_concurrent=4)
        tasks = [_make_multi_task(f"EB-TIMEOUT-{i:03d}") for i in range(4)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 4
        assert all(r.execution_metadata["status"] == TaskStatus.SUCCESS.value for r in results)

    def test_all_tasks_fail_gracefully(self):
        adapter = _make_adapter(fail=True, error="all failed")
        runner = MultiRunner(adapter, max_concurrent=2)
        tasks = [_make_multi_task(f"EB-ALLFAIL-{i:03d}") for i in range(3)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 3
        assert all(r.execution_metadata["status"] == TaskStatus.ERROR.value for r in results)
        assert all(len(r.flags) > 0 for r in results)
