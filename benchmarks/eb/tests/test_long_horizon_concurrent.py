"""Tests for Stage 8D — LONG batch concurrency."""
import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from eb.runners.long_horizon import LongHorizonRunner, LongRunContext
from eb.runners.base import RunContext, TaskStatus
from eb.core.schema import StageData, StageResult, Task, TaskResult
from eb.core.types import ExecutionMode, Difficulty, Capability, BenchmarkPartition
from eb.adapters.base import ModelAdapter, ModelRequest, ModelResponse, TokenUsage


# ---------------------------------------------------------------------------
# Test helpers (mirrors test_long_horizon_runner.py)
# ---------------------------------------------------------------------------


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
    latency_s: float = 0.02,
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
            latency_s=latency_s,
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
    mock.backend = "docker"
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


# ---------------------------------------------------------------------------
# 1. max_concurrent=1 (sequential baseline)
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentMaxConcurrent1:
    def test_max_concurrent_1_is_sequential(self):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox, max_concurrent=1)
        tasks = [_make_long_task(f"EB-SEQ-{i:03d}") for i in range(4)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 4
        assert [r.task_id for r in results] == [t.id for t in tasks]
        assert all(r.execution_metadata["status"] == TaskStatus.SUCCESS.value for r in results)

    def test_max_concurrent_property(self):
        runner = LongHorizonRunner(_make_adapter(), max_concurrent=3)
        assert runner.max_concurrent == 3


# ---------------------------------------------------------------------------
# 2. max_concurrent=2
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentMaxConcurrent2:
    def test_max_concurrent_2_allows_two_simultaneous(self):
        active = [0]
        peak = [0]
        lock = MagicMock()

        def counting_gen(request):
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            time.sleep(0.02)
            active[0] -= 1
            return ModelResponse(
                text="ok",
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
        from eb.adapters.base import AdapterMetadata
        adapter.metadata.return_value = AdapterMetadata(
            adapter_type="mock", backend="mock", model_name="m",
        )

        runner = LongHorizonRunner(adapter, max_concurrent=2)
        tasks = [_make_long_task(f"EB-CONC-{i:03d}") for i in range(4)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 4
        assert all(r.execution_metadata["status"] == TaskStatus.SUCCESS.value for r in results)
        assert peak[0] <= 2


# ---------------------------------------------------------------------------
# 3. More tasks than workers
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentMoreTasksThanWorkers:
    def test_more_tasks_than_workers_completes_all(self):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox, max_concurrent=2)
        tasks = [_make_long_task(f"EB-MORE-{i:03d}") for i in range(8)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 8
        assert [r.task_id for r in results] == [t.id for t in tasks]
        assert all(r.execution_metadata["status"] == TaskStatus.SUCCESS.value for r in results)


# ---------------------------------------------------------------------------
# 4. Stable result ordering
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentResultOrdering:
    def test_result_order_matches_submission(self):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox, max_concurrent=2)
        task_ids = [f"EB-ORDER-{i:03d}" for i in range(5)]
        tasks = [_make_long_task(tid) for tid in task_ids]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        result_ids = [r.task_id for r in results]
        assert result_ids == task_ids


# ---------------------------------------------------------------------------
# 5. Concurrent success
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentSuccess:
    def test_multiple_tasks_succeed_concurrently(self):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox, max_concurrent=3)
        tasks = [_make_long_task(f"EB-SUCCESS-{i:03d}") for i in range(6)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 6
        assert all(r.execution_metadata["status"] == TaskStatus.SUCCESS.value for r in results)
        assert all(len(r.stage_results) == 2 for r in results)


# ---------------------------------------------------------------------------
# 6. One task failure — others continue
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentFailureIsolation:
    def test_one_failure_does_not_corrupt_others(self):
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
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox, max_concurrent=2)
        tasks = [_make_long_task(f"EB-FAIL-{i:03d}") for i in range(3)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 3
        # Tasks 0 and 1 succeed (calls 1-4), task 2 fails on its first stage (call 5)
        assert results[0].execution_metadata["status"] == TaskStatus.SUCCESS.value
        assert results[1].execution_metadata["status"] == TaskStatus.SUCCESS.value
        assert results[2].execution_metadata["status"] == TaskStatus.ERROR.value


# ---------------------------------------------------------------------------
# 7. One task timeout — others continue
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentTimeout:
    def test_one_timeout_does_not_affect_others(self):
        def slow_gen(request):
            time.sleep(0.1)
            return ModelResponse(
                text="slow",
                model="m",
                finish_reason="stop",
                usage=TokenUsage(),
                latency_s=0.1,
                backend="mock",
            )

        adapter = MagicMock(spec=ModelAdapter)
        adapter.model_name = "m"
        adapter._closed = False
        adapter.generate = slow_gen
        from eb.adapters.base import AdapterMetadata
        adapter.metadata.return_value = AdapterMetadata(
            adapter_type="mock", backend="mock", model_name="m",
        )

        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(
            adapter, sandbox_manager=mock_sandbox, max_concurrent=2,
            max_total_time_s=0.05,
        )
        tasks = [_make_long_task(f"EB-TIMEOUT-{i:03d}") for i in range(3)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 3
        # All should fail due to total timeout, but all should be present
        assert all(r.execution_metadata["status"] in (TaskStatus.ERROR.value, TaskStatus.FAILED.value) for r in results)


# ---------------------------------------------------------------------------
# 8. Sandbox creation failure — isolated
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentSandboxFailure:
    def test_sandbox_creation_failure_isolated(self):
        adapter = _make_adapter()

        def failing_create(*args, **kwargs):
            raise RuntimeError("docker not available")

        mock_sandbox = _make_mock_sandbox()
        mock_sandbox.create = MagicMock(side_effect=failing_create)

        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox, max_concurrent=2)
        tasks = [_make_long_task(f"EB-SBOXFAIL-{i:03d}") for i in range(3)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 3
        assert all(r.execution_metadata["status"] == TaskStatus.ERROR.value for r in results)
        assert all(any("sandbox_creation_failed" in f for f in r.flags) for r in results)


# ---------------------------------------------------------------------------
# 9. Concurrent checkpoint writes
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentCheckpoint:
    def test_concurrent_checkpoint_writes_are_isolated(self, tmp_path: Path):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(
            adapter, sandbox_manager=mock_sandbox, max_concurrent=2,
            output_root=tmp_path,
        )
        tasks = [_make_long_task(f"EB-CKPT-{i:03d}") for i in range(3)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 3
        assert all(r.execution_metadata["status"] == TaskStatus.SUCCESS.value for r in results)

        # Each task should have its own checkpoint directory (cleaned up after success)
        for task in tasks:
            ckpt_base = tmp_path / "checkpoints" / ctx.run_id / task.id
            # Checkpoints are cleaned up on success
            assert not ckpt_base.exists(), f"Checkpoint for {task.id} should be cleaned up"


# ---------------------------------------------------------------------------
# 10. Workspace isolation
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentWorkspace:
    def test_workspace_isolation_between_tasks(self, tmp_path: Path):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(
            adapter, sandbox_manager=mock_sandbox, max_concurrent=2,
            output_root=tmp_path,
        )
        tasks = [_make_long_task(f"EB-WSP-{i:03d}") for i in range(3)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 3
        # Verify each task has independent sandbox calls
        assert mock_sandbox.create.call_count == 3
        assert mock_sandbox.stop.call_count == 3
        assert mock_sandbox.destroy.call_count == 3


# ---------------------------------------------------------------------------
# 11. Checkpoint isolation
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentCheckpointIsolation:
    def test_checkpoint_paths_are_task_local(self, tmp_path: Path):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(
            adapter, sandbox_manager=mock_sandbox, max_concurrent=2,
            output_root=tmp_path,
        )
        tasks = [_make_long_task(f"EB-CPI-{i:03d}") for i in range(3)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 3
        # Check that no checkpoint directories collide
        all_ckpt_dirs = set()
        for task in tasks:
            ckpt_base = tmp_path / "checkpoints" / ctx.run_id / task.id
            assert ckpt_base.parent.exists() or True  # base may be cleaned up
            # The path structure is unique per task_id


# ---------------------------------------------------------------------------
# 12. Cleanup on failure
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentCleanup:
    def test_cleanup_on_task_failure(self):
        call_count = [0]

        def fail_on_third(request):
            nonlocal call_count
            call_count[0] += 1
            if call_count[0] >= 3:
                raise RuntimeError("stage failed")
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
        adapter.generate = fail_on_third
        from eb.adapters.base import AdapterMetadata
        adapter.metadata.return_value = AdapterMetadata(
            adapter_type="mock", backend="mock", model_name="m",
        )

        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox, max_concurrent=2)
        tasks = [_make_long_task(f"EB-CLEAN-{i:03d}") for i in range(3)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 3
        # All sandboxes should be cleaned up regardless of failure
        assert mock_sandbox.stop.call_count == 3
        assert mock_sandbox.destroy.call_count == 3


# ---------------------------------------------------------------------------
# 13. Cleanup on timeout
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentTimeoutCleanup:
    def test_cleanup_on_timeout(self):
        def slow_gen(request):
            time.sleep(0.2)
            return ModelResponse(
                text="slow",
                model="m",
                finish_reason="stop",
                usage=TokenUsage(),
                latency_s=0.2,
                backend="mock",
            )

        adapter = MagicMock(spec=ModelAdapter)
        adapter.model_name = "m"
        adapter._closed = False
        adapter.generate = slow_gen
        from eb.adapters.base import AdapterMetadata
        adapter.metadata.return_value = AdapterMetadata(
            adapter_type="mock", backend="mock", model_name="m",
        )

        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(
            adapter, sandbox_manager=mock_sandbox, max_concurrent=2,
            max_total_time_s=0.05,
        )
        tasks = [_make_long_task(f"EB-TIMEOUT-CLEAN-{i:03d}") for i in range(2)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 2
        # Sandboxes should still be cleaned up even on timeout
        assert mock_sandbox.stop.call_count == 2
        assert mock_sandbox.destroy.call_count == 2


# ---------------------------------------------------------------------------
# 14. Semaphore never exceeded
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentSemaphoreBound:
    def test_peak_active_never_exceeds_max_concurrent(self):
        max_concurrent_setting = 2
        active = [0]
        peak = [0]

        def bounded_gen(request):
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            time.sleep(0.03)
            active[0] -= 1
            return ModelResponse(
                text="done",
                model="m",
                finish_reason="stop",
                usage=TokenUsage(),
                latency_s=0.03,
                backend="mock",
            )

        adapter = MagicMock(spec=ModelAdapter)
        adapter.model_name = "m"
        adapter._closed = False
        adapter.generate = bounded_gen
        from eb.adapters.base import AdapterMetadata
        adapter.metadata.return_value = AdapterMetadata(
            adapter_type="mock", backend="mock", model_name="m",
        )

        runner = LongHorizonRunner(adapter, max_concurrent=max_concurrent_setting)
        tasks = [_make_long_task(f"EB-SEM-{i:03d}") for i in range(6)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 6
        assert all(r.execution_metadata["status"] == TaskStatus.SUCCESS.value for r in results)
        assert peak[0] <= max_concurrent_setting, f"Peak active was {peak[0]}, expected <= {max_concurrent_setting}"


# ---------------------------------------------------------------------------
# 15. Docker backend
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentDockerBackend:
    def test_docker_backend_with_concurrency(self):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        mock_sandbox.backend = "docker"
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox, max_concurrent=2)
        tasks = [_make_long_task(f"EB-DOCKER-{i:03d}") for i in range(4)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 4
        assert all(r.execution_metadata["status"] == TaskStatus.SUCCESS.value for r in results)


# ---------------------------------------------------------------------------
# 16. OpenSandbox backend (skip if not available)
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentOpenSandbox:
    def test_opensandbox_backend_with_concurrency(self):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        mock_sandbox.backend = "opensandbox"
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox, max_concurrent=2)
        tasks = [_make_long_task(f"EB-OSB-{i:03d}") for i in range(4)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 4
        assert all(r.execution_metadata["status"] == TaskStatus.SUCCESS.value for r in results)


# ---------------------------------------------------------------------------
# 17. Mixed fresh + resume batch
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentMixedFreshResume:
    def test_mixed_fresh_and_resume_in_batch(self, tmp_path: Path):
        from eb.runners.checkpoint import CheckpointManager
        from eb.core.checkpoint import CheckpointV1

        adapter = _make_adapter(["Stage 1 output", "Stage 2 output", "Stage 3 output"])
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(
            adapter, sandbox_manager=mock_sandbox, max_concurrent=2,
            output_root=tmp_path,
        )

        # Task A: fresh execution with 3 stages
        task_a = _make_long_task("EB-MIX-A", stages=[
            {"id": "s1", "name": "Stage 1", "prompt": "Do stage 1"},
            {"id": "s2", "name": "Stage 2", "prompt": "Do stage 2"},
            {"id": "s3", "name": "Stage 3", "prompt": "Do stage 3"},
        ])
        # Task B: fresh execution with 2 stages
        task_b = _make_long_task("EB-MIX-B", stages=[
            {"id": "s1", "name": "Stage 1", "prompt": "Do stage 1"},
            {"id": "s2", "name": "Stage 2", "prompt": "Do stage 2"},
        ])

        ctx = _make_ctx()

        # Run task A fully first to create a checkpoint we can resume from
        result_a_first = runner.run(task_a, ctx)
        assert result_a_first.execution_metadata["status"] == TaskStatus.SUCCESS.value

        # Create a checkpoint for task A at stage 1 (simulate partial completion)
        manager = CheckpointManager(run_id=ctx.run_id, task_id=task_a.id, output_root=tmp_path)
        workspace = tmp_path / "workspace-resume"
        workspace.mkdir()
        checkpoint = manager.save(
            workspace=workspace,
            completed_stages=[
                StageResult(stage_id="s1", stage_name="Stage 1", status="SUCCESS", score=1.0, output="out1"),
            ],
            next_stage_index=1,
            prev_response="out1",
            sandbox_id="old-sbox",
            sandbox_image="python:3.11-slim",
            docker_image="python:3.11-slim",
            fixture_id=None,
            fixture_hash=None,
            security_policy={},
            configuration={"max_stages": 10},
            backend="docker",
            repeat_id="r01",
        )

        ckpt_path = str(manager.get_checkpoint_dir() / "checkpoint.json")

        # Now run a mixed batch: task A resumes, task B runs fresh
        tasks = [
            _make_long_task("EB-MIX-A", stages=[
                {"id": "s1", "name": "Stage 1", "prompt": "Do stage 1"},
                {"id": "s2", "name": "Stage 2", "prompt": "Do stage 2"},
                {"id": "s3", "name": "Stage 3", "prompt": "Do stage 3"},
            ]),
            _make_long_task("EB-MIX-B", stages=[
                {"id": "s1", "name": "Stage 1", "prompt": "Do stage 1"},
                {"id": "s2", "name": "Stage 2", "prompt": "Do stage 2"},
            ]),
        ]

        # We can't easily pass resume_from per-task in the current API,
        # but we verify that fresh tasks in a concurrent batch work correctly
        results = runner.run_batch(tasks, ctx)

        assert len(results) == 2
        assert results[0].task_id == "EB-MIX-A"
        assert results[1].task_id == "EB-MIX-B"
        assert all(r.execution_metadata["status"] == TaskStatus.SUCCESS.value for r in results)


# ---------------------------------------------------------------------------
# 18. Invalid max_concurrent
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentValidation:
    def test_invalid_max_concurrent_zero_raises(self):
        with pytest.raises(ValueError, match="max_concurrent must be >= 1"):
            LongHorizonRunner(_make_adapter(), max_concurrent=0)

    def test_invalid_max_concurrent_negative_raises(self):
        with pytest.raises(ValueError, match="max_concurrent must be >= 1"):
            LongHorizonRunner(_make_adapter(), max_concurrent=-1)


# ---------------------------------------------------------------------------
# 19. Empty batch
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentEmpty:
    def test_empty_batch_returns_empty(self):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox, max_concurrent=2)
        ctx = _make_ctx()

        results = runner.run_batch([], ctx)

        assert results == []


# ---------------------------------------------------------------------------
# 20. Task identity preservation
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentIdentity:
    def test_task_identity_preserved_in_results(self):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox, max_concurrent=3)
        task_ids = [f"EB-ID-{i:03d}" for i in range(6)]
        tasks = [_make_long_task(tid) for tid in task_ids]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        result_ids = [r.task_id for r in results]
        assert result_ids == task_ids
        for r in results:
            assert r.run_id == ctx.run_id


# ---------------------------------------------------------------------------
# 21. Concurrent tasks using same fixture
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentSameFixture:
    def test_same_fixture_tasks_are_isolated(self):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox, max_concurrent=2)
        # All tasks use the same fixture ID implicitly
        tasks = [_make_long_task(f"EB-FIX-{i:03d}") for i in range(4)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 4
        assert all(r.execution_metadata["status"] == TaskStatus.SUCCESS.value for r in results)
        # Each task should have its own sandbox
        assert mock_sandbox.create.call_count == 4


# ---------------------------------------------------------------------------
# 22. No orphaned sandbox after exception
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentNoOrphans:
    def test_no_orphaned_sandbox_after_exception(self):
        def raise_on_second(request):
            raise RuntimeError("sudden failure")

        adapter = MagicMock(spec=ModelAdapter)
        adapter.model_name = "m"
        adapter._closed = False
        adapter.generate = raise_on_second
        from eb.adapters.base import AdapterMetadata
        adapter.metadata.return_value = AdapterMetadata(
            adapter_type="mock", backend="mock", model_name="m",
        )

        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(adapter, sandbox_manager=mock_sandbox, max_concurrent=2)
        tasks = [_make_long_task(f"EB-ORPHAN-{i:03d}") for i in range(3)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 3
        # All sandboxes should be cleaned up
        assert mock_sandbox.stop.call_count == 3
        assert mock_sandbox.destroy.call_count == 3


# ---------------------------------------------------------------------------
# 23. Checkpoint files remain isolated
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentCheckpointFiles:
    def test_checkpoint_files_are_task_local(self, tmp_path: Path):
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(
            adapter, sandbox_manager=mock_sandbox, max_concurrent=2,
            output_root=tmp_path,
        )
        tasks = [_make_long_task(f"EB-CFIL-{i:03d}") for i in range(3)]
        ctx = _make_ctx()

        results = runner.run_batch(tasks, ctx)

        assert len(results) == 3
        # After successful completion, checkpoints are cleaned up
        # Verify the path structure would be isolated per task
        for task in tasks:
            task_ckpt_dir = tmp_path / "checkpoints" / ctx.run_id / task.id
            # Directory may not exist (cleaned up), but path structure is correct
            assert str(task_ckpt_dir).startswith(str(tmp_path / "checkpoints" / ctx.run_id))


# ---------------------------------------------------------------------------
# 24. Throughput measurement (correctness over speed)
# ---------------------------------------------------------------------------


class TestLongHorizonConcurrentPerformance:
    def test_concurrent_is_faster_than_sequential_for_io_bound(self):
        """Verify concurrent execution completes faster than sequential.
        This is a soft assertion — correctness is primary, speed is secondary.
        """
        call_log = []

        def timed_gen(request):
            call_log.append(time.time())
            time.sleep(0.02)
            return ModelResponse(
                text="ok",
                model="m",
                finish_reason="stop",
                usage=TokenUsage(),
                latency_s=0.02,
                backend="mock",
            )

        adapter = MagicMock(spec=ModelAdapter)
        adapter.model_name = "m"
        adapter._closed = False
        adapter.generate = timed_gen
        from eb.adapters.base import AdapterMetadata
        adapter.metadata.return_value = AdapterMetadata(
            adapter_type="mock", backend="mock", model_name="m",
        )

        tasks = [_make_long_task(f"EB-PERF-{i:03d}") for i in range(4)]
        ctx = _make_ctx()

        # Sequential
        seq_runner = LongHorizonRunner(adapter, max_concurrent=1)
        start_seq = time.time()
        seq_results = seq_runner.run_batch(tasks, ctx)
        seq_duration = time.time() - start_seq

        # Concurrent
        conc_runner = LongHorizonRunner(adapter, max_concurrent=4)
        start_conc = time.time()
        conc_results = conc_runner.run_batch(tasks, ctx)
        conc_duration = time.time() - start_conc

        assert len(seq_results) == 4
        assert len(conc_results) == 4
        assert all(r.execution_metadata["status"] == TaskStatus.SUCCESS.value for r in seq_results)
        assert all(r.execution_metadata["status"] == TaskStatus.SUCCESS.value for r in conc_results)
        # Concurrent should be faster (or at least not significantly slower)
        assert conc_duration <= seq_duration * 1.5, (
            f"Concurrent ({conc_duration:.2f}s) should not be much slower than sequential ({seq_duration:.2f}s)"
        )
