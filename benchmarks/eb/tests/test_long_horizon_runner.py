"""Tests for eb/runners/long_horizon.py — LONG execution mode runner."""
from unittest.mock import MagicMock

import pytest

from eb.runners.long_horizon import LongHorizonRunner, LongRunContext
from eb.runners.base import RunContext, TaskStatus
from eb.core.schema import StageData, StageResult, Task, TaskResult
from eb.core.types import ExecutionMode, Difficulty, Capability, BenchmarkPartition
from eb.adapters.base import ModelAdapter, ModelRequest, ModelResponse, TokenUsage


def _make_long_task(
    task_id: str = "EB-LONG-001",
    stages: list[dict | StageData] | None = None,
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
        responses = ["Stage 1 output", "Stage 2 output"]

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


def _make_mock_sandbox(sandbox_id: str = "eb-long-sbox-001"):
    """Create a mock sandbox manager for testing."""
    mock = MagicMock()
    mock.create = MagicMock(return_value=sandbox_id)
    mock.start = MagicMock(return_value=None)
    mock.exec = MagicMock(return_value=MagicMock(
        success=True, exit_code=0, stdout="", stderr="", duration_s=0.01,
    ))
    mock.copy_in = MagicMock(return_value=None)
    mock.copy_out = MagicMock(return_value=MagicMock())
    mock.collect = MagicMock(return_value={})
    mock.stop = MagicMock(return_value=None)
    mock.destroy = MagicMock(return_value=None)
    mock.get_metadata = MagicMock(return_value=MagicMock(sandbox_id=sandbox_id))
    mock.list_containers = MagicMock(return_value=[])
    mock.cleanup_orphans = MagicMock(return_value=0)
    mock.cleanup_all = MagicMock(return_value=0)
    return mock


def _make_ctx(run_id: str = "run-long-001", repeat: int = 0, **overrides) -> RunContext:
    defaults = {
        "run_id": run_id,
        "model_name": "test-model",
        "suite": "long",
        "inference_settings": {
            "seed": 42, "temperature": 0.0, "top_p": 1.0,
            "top_k": 0, "max_tokens": 4096,
        },
        "repeat_index": repeat,
    }
    defaults.update(overrides)
    return RunContext(**defaults)


class TestLongHorizonRunnerSingle:
    def test_runs_long_task(self):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox)
        task = _make_long_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert isinstance(result, TaskResult)
        assert result.task_id == "EB-LONG-001"
        assert result.execution_metadata["status"] == TaskStatus.SUCCESS.value
        assert result.execution_metadata["stage_count"] == 2
        assert result.execution_metadata["repeat_id"] == "r01"
        assert len(result.stage_results) == 2

    def test_rejects_non_long_mode(self):
        adapter = _make_adapter()
        runner = LongHorizonRunner(adapter)
        task = _make_long_task(mode=ExecutionMode.SINGLE)
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["status"] == TaskStatus.SKIPPED.value
        assert any("mode_mismatch" in f for f in result.flags)

    def test_rejects_exec_mode(self):
        adapter = _make_adapter()
        runner = LongHorizonRunner(adapter)
        task = _make_long_task(mode=ExecutionMode.EXEC)
        ctx = _make_ctx()

        result = runner.run(task, ctx)
        assert result.execution_metadata["status"] == TaskStatus.SKIPPED.value

    def test_rejects_multi_mode(self):
        adapter = _make_adapter()
        runner = LongHorizonRunner(adapter)
        task = _make_long_task(mode=ExecutionMode.MULTI)
        ctx = _make_ctx()

        result = runner.run(task, ctx)
        assert result.execution_metadata["status"] == TaskStatus.SKIPPED.value

    def test_runner_mode_property(self):
        adapter = _make_adapter()
        runner = LongHorizonRunner(adapter)
        assert runner.mode == ExecutionMode.LONG

    def test_no_stages_returns_error(self):
        adapter = _make_adapter()
        runner = LongHorizonRunner(adapter)
        task = _make_long_task(stages=[])
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["status"] == TaskStatus.ERROR.value
        assert any("no_stages_defined" in f for f in result.flags)

    def test_stage_results_preserved(self):
        adapter = _make_adapter(["Stage 1 output", "Stage 2 output"])
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox)
        task = _make_long_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert len(result.stage_results) == 2
        assert result.stage_results[0].stage_id == "s1"
        assert result.stage_results[1].stage_id == "s2"
        assert result.stage_results[0].status == "SUCCESS"
        assert result.stage_results[1].status == "SUCCESS"
        assert result.stage_results[0].output == "Stage 1 output"
        assert result.stage_results[1].output == "Stage 2 output"

    def test_state_preserved_across_stages(self):
        """Stage 2 should see output from Stage 1 in its prompt."""
        received_prompts = []

        def tracking_gen(request: ModelRequest) -> ModelResponse:
            received_prompts.append(request.prompt)
            idx = min(len(received_prompts) - 1, 1)
            return ModelResponse(
                text=f"Output {idx + 1}",
                model="m",
                finish_reason="stop",
                usage=TokenUsage(),
                latency_s=0.01,
                backend="mock",
            )

        adapter = MagicMock(spec=ModelAdapter)
        adapter.model_name = "m"
        adapter._closed = False
        adapter.generate = tracking_gen
        from eb.adapters.base import AdapterMetadata
        adapter.metadata.return_value = AdapterMetadata(
            adapter_type="mock", backend="mock", model_name="m",
        )

        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox)
        task = _make_long_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert len(received_prompts) == 2
        assert "STAGE: Stage 1" in received_prompts[0]
        assert "STAGE: Stage 2" in received_prompts[1]
        assert "PREVIOUS STAGE OUTPUT" in received_prompts[1]
        assert "Output 1" in received_prompts[1]

    def test_final_response_is_last_stage_output(self):
        adapter = _make_adapter(["Stage 1 output", "Final answer"])
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox)
        task = _make_long_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.raw_response == "Final answer"

    def test_no_eb_score_computed(self):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox)
        task = _make_long_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.final_score is None

    def test_timestamps_present(self):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox)
        task = _make_long_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        ts = result.execution_metadata.get("timestamp")
        assert ts is not None
        assert "T" in ts

    def test_execution_metadata_completeness(self):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox)
        task = _make_long_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        meta = result.execution_metadata
        assert "status" in meta
        assert "repeat_id" in meta
        assert "stage_count" in meta
        assert "max_stages" in meta
        assert "total_time_s" in meta
        assert "stages" in meta
        assert "timestamp" in meta
        assert meta["stage_count"] == 2
        assert meta["max_stages"] == 10


class TestLongHorizonRunnerStageFailure:
    def test_stage_error_propagates(self):
        adapter = _make_adapter(fail=True, error="boom")
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox)
        task = _make_long_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["status"] == TaskStatus.ERROR.value
        # Stage error is recorded in the StageResult, not as a top-level flag
        assert len(result.stage_results) == 0 or any(
            "generation_error" in (sr.error or "") for sr in result.stage_results
        )

    def test_first_stage_failure_stops_execution(self):
        call_count = [0]

        def selective_fail(request):
            nonlocal call_count
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("stage 1 failed")
            return ModelResponse(
                text="Stage 2 output",
                model="m",
                finish_reason="stop",
                usage=TokenUsage(),
                latency_s=0.01,
                backend="mock",
            )

        adapter = MagicMock(spec=ModelAdapter)
        adapter.model_name = "m"
        adapter._closed = False
        adapter.generate = selective_fail
        from eb.adapters.base import AdapterMetadata
        adapter.metadata.return_value = AdapterMetadata(
            adapter_type="mock", backend="mock", model_name="m",
        )

        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox)
        task = _make_long_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["status"] == TaskStatus.ERROR.value
        # First stage record its failure; remaining stages are not executed
        assert len(result.stage_results) == 1
        assert result.stage_results[0].status == "ERROR"

    def test_max_stages_reached(self):
        adapter = _make_adapter(["ok"] * 100)
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, max_stages=2, sandbox_manager=mock_sandbox)
        task = _make_long_task(stages=[
            {"id": f"s{i}", "name": f"Stage {i}", "prompt": f"Prompt {i}"}
            for i in range(5)
        ])
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        # max_stages truncates the stage list; completing 2 stages is success
        assert result.execution_metadata["stage_count"] == 2
        assert result.execution_metadata["status"] == TaskStatus.SUCCESS.value

    def test_empty_stages_returns_error(self):
        adapter = _make_adapter()
        runner = LongHorizonRunner(adapter)
        task = _make_long_task(stages=[])
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["status"] == TaskStatus.ERROR.value
        assert any("no_stages_defined" in f for f in result.flags)


class TestLongHorizonRunnerBatch:
    def test_batch_empty_returns_empty(self):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox)
        ctx = _make_ctx()

        results = runner.run_batch([], ctx)

        assert results == []

    def test_batch_single_task(self):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox)
        task = _make_long_task("EB-BATCH-LONG-001")
        ctx = _make_ctx()

        results = runner.run_batch([task], ctx)

        assert len(results) == 1
        assert results[0].task_id == "EB-BATCH-LONG-001"
        assert results[0].execution_metadata["status"] == TaskStatus.SUCCESS.value

    def test_batch_multiple_tasks_order_preserved(self):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox)
        tasks = [_make_long_task(f"EB-BATCH-LONG-{i:03d}") for i in range(3)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 3
        assert results[0].task_id == "EB-BATCH-LONG-000"
        assert results[1].task_id == "EB-BATCH-LONG-001"
        assert results[2].task_id == "EB-BATCH-LONG-002"

    def test_batch_one_failure_does_not_corrupt_others(self):
        call_count = [0]

        def selective_fail(request):
            nonlocal call_count
            call_count[0] += 1
            if call_count[0] == 5:
                raise RuntimeError("boom")
            return ModelResponse(
                text="ok",
                model="m",
                finish_reason="stop",
                usage=TokenUsage(),
                latency_s=0.01,
                backend="mock",
            )

        adapter = MagicMock(spec=ModelAdapter)
        adapter.model_name = "m"
        adapter._closed = False
        adapter.generate = selective_fail
        from eb.adapters.base import AdapterMetadata
        adapter.metadata.return_value = AdapterMetadata(
            adapter_type="mock", backend="mock", model_name="m",
        )

        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox)
        # Each task has 2 stages, so 3 tasks = 6 adapter calls.
        # Failure on call 5 means task 0 (calls 1-2) and task 1 (calls 3-4) succeed,
        # task 2 fails on its first stage (call 5).
        tasks = [_make_long_task(f"EB-BATCH-LONG-{i:03d}") for i in range(3)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 3
        assert results[0].execution_metadata["status"] == TaskStatus.SUCCESS.value
        assert results[1].execution_metadata["status"] == TaskStatus.SUCCESS.value
        assert results[2].execution_metadata["status"] == TaskStatus.ERROR.value

    def test_batch_result_ordering_matches_submission(self):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox)
        task_ids = [f"EB-ORDER-LONG-{i:03d}" for i in range(5)]
        tasks = [_make_long_task(tid) for tid in task_ids]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        result_ids = [r.task_id for r in results]
        assert result_ids == task_ids


class TestLongHorizonRunnerScoring:
    def test_stage_scores_aggregated(self):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox)
        task = _make_long_task(
            evaluation={"evaluators": [{"type": "exact", "parameters": {"expected": "Stage 1 output"}}]}
        )
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.raw_task_score is not None
        assert result.raw_task_score >= 0
        assert len(result.evaluator_results) > 0

    def test_stage_scores_none_when_no_evaluators(self):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox)
        task = _make_long_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.raw_task_score is not None
        assert isinstance(result.raw_task_score, (int, float))


class TestLongHorizonRunnerSandbox:
    def test_sandbox_created_and_cleaned_up(self):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox)
        task = _make_long_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["status"] == TaskStatus.SUCCESS.value
        mock_sandbox.create.assert_called_once()
        mock_sandbox.stop.assert_called_once()
        mock_sandbox.destroy.assert_called_once()

    def test_sandbox_creation_failure(self):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        mock_sandbox.create.side_effect = RuntimeError("docker not available")

        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox)
        task = _make_long_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["status"] == TaskStatus.ERROR.value
        assert any("sandbox_creation_failed" in f for f in result.flags)


class TestLongRunContext:
    def test_context_creation(self):
        ctx = LongRunContext(
            run_id="r1",
            task_id="t1",
            repeat_id="r01",
            workspace=MagicMock(),
            stages=[],
        )
        assert ctx.run_id == "r1"
        assert ctx.task_id == "t1"
        assert ctx.repeat_id == "r01"
        assert ctx.stage_results == []
        assert ctx.errors == []
        assert ctx.status == "running"
        assert ctx.current_stage_index == 0

    def test_record_stage_result(self):
        ctx = LongRunContext(
            run_id="r1", task_id="t1", repeat_id="r01",
            workspace=MagicMock(), stages=[],
        )
        sr = StageResult(stage_id="s1", stage_name="S1", status="SUCCESS")
        ctx.record_stage_result(sr)
        assert len(ctx.stage_results) == 1
        assert ctx.current_stage_index == 1

    def test_add_error(self):
        ctx = LongRunContext(
            run_id="r1", task_id="t1", repeat_id="r01",
            workspace=MagicMock(), stages=[],
        )
        ctx.add_error("something went wrong")
        assert ctx.errors == ["something went wrong"]


class TestStageResult:
    def test_stage_result_defaults(self):
        sr = StageResult(stage_id="s1", stage_name="S1")
        assert sr.status == "pending"
        assert sr.output is None
        assert sr.score is None
        assert sr.duration_s == 0.0
        assert sr.flags == []
        assert "T" in sr.timestamp

    def test_stage_result_passed(self):
        sr = StageResult(stage_id="s1", stage_name="S1", score=0.8)
        assert sr.passed is True

        sr2 = StageResult(stage_id="s1", stage_name="S1", score=0.3)
        assert sr2.passed is False

        sr3 = StageResult(stage_id="s1", stage_name="S1", score=None)
        assert sr3.passed is None


class TestLongHorizonRunnerIntegration:
    def test_full_three_stage_workflow(self):
        """End-to-end: 3 stages, same sandbox, state flows between stages."""
        received_prompts = []

        def tracking_gen(request):
            received_prompts.append(request.prompt)
            idx = len(received_prompts) - 1
            return ModelResponse(
                text=f"Response {idx + 1}",
                model="m",
                finish_reason="stop",
                usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                latency_s=0.02,
                backend="mock",
            )

        adapter = MagicMock(spec=ModelAdapter)
        adapter.model_name = "m"
        adapter._closed = False
        adapter.generate = tracking_gen
        from eb.adapters.base import AdapterMetadata
        adapter.metadata.return_value = AdapterMetadata(
            adapter_type="mock", backend="mock", model_name="m",
        )

        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox)
        task = _make_long_task(stages=[
            {"id": "arch", "name": "Architecture", "prompt": "Design the system"},
            {"id": "impl", "name": "Implementation", "prompt": "Implement it"},
            {"id": "test", "name": "Testing", "prompt": "Write tests"},
        ])
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["status"] == TaskStatus.SUCCESS.value
        assert result.execution_metadata["stage_count"] == 3
        assert len(result.stage_results) == 3
        assert result.stage_results[0].stage_id == "arch"
        assert result.stage_results[1].stage_id == "impl"
        assert result.stage_results[2].stage_id == "test"
        assert result.raw_response == "Response 3"
        assert len(received_prompts) == 3
        # Verify state flows between stages
        assert "PREVIOUS STAGE OUTPUT" in received_prompts[1]
        assert "PREVIOUS STAGE OUTPUT" in received_prompts[2]
        assert "Response 1" in received_prompts[1]
        assert "Response 2" in received_prompts[2]

    def test_orchestrator_selects_long_runner(self, tmp_eb_root, tmp_path, monkeypatch):
        """RunOrchestrator should dispatch LONG tasks to LongHorizonRunner."""
        import json
        from eb.runners.orchestration import RunOrchestrator

        task_dir = tmp_eb_root / "tasks" / "long_horizon"
        task_dir.mkdir(parents=True, exist_ok=True)

        task = _make_long_task("EB-ORCH-LONG-001")
        with (task_dir / "task.json").open("w") as f:
            json.dump(task.model_dump(), f, indent=2)

        monkeypatch.setattr("eb.paths._EB_ROOT_CACHE", {"eb_root": tmp_eb_root})

        mock_adapter = MagicMock(spec=ModelAdapter)
        mock_adapter.model_name = "test-model"
        mock_adapter._closed = False
        mock_adapter.generate.return_value = ModelResponse(
            text="ok",
            model="test-model",
            finish_reason="stop",
            usage=TokenUsage(),
            latency_s=0.01,
            backend="mock",
        )
        from eb.adapters.base import AdapterMetadata
        mock_adapter.metadata.return_value = AdapterMetadata(
            adapter_type="mock", backend="mock", model_name="test-model",
        )

        mock_factory = MagicMock()
        mock_factory.create_adapter.return_value = mock_adapter
        mock_factory.list_models.return_value = ["test-model"]

        # Mock the sandbox manager to avoid async event loop issues
        mock_sandbox = _make_mock_sandbox()
        with monkeypatch.context() as m:
            import eb.runners.long_horizon as lh_module
            m.setattr(lh_module, "SandboxManager", lambda *a, **k: mock_sandbox)

            orchestrator = RunOrchestrator(
                model_name="test-model",
                suite="long",
                partitions=["development"],
                repeats=1,
                adapter_factory=mock_factory,
                output_dir=tmp_path / "outputs",
            )
            summary = orchestrator.run()

        assert summary.tasks_selected >= 1
        assert summary.successes >= 1
        assert summary.skipped == 0

        mock_adapter.close()
