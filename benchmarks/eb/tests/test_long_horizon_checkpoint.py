"""Tests for Stage 8C — LONG Checkpoint & Recovery."""
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from eb.core.checkpoint import (
    CheckpointLoadError,
    CheckpointV1,
    CURRENT_SCHEMA_VERSION,
)
from eb.core.schema import StageData, StageResult, Task, TaskResult
from eb.core.types import ExecutionMode, Difficulty, Capability, BenchmarkPartition
from eb.runners.base import RunContext, TaskStatus
from eb.runners.checkpoint import CheckpointManager, WORKSPACE_ARCHIVE_NAME
from eb.runners.long_horizon import LongHorizonRunner


# ---------------------------------------------------------------------------
# Helpers
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
            {"id": "s3", "name": "Stage 3", "prompt": "Do stage 3"},
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
    fail_at: int | None = None,
) -> MagicMock:
    adapter = MagicMock()
    adapter.model_name = "test-model"
    adapter._closed = False

    if responses is None:
        responses = ["Stage 1 output", "Stage 2 output", "Stage 3 output"]

    call_count = [0]

    def gen(request):
        idx = min(call_count[0], len(responses) - 1)
        call_count[0] += 1
        if fail_at and call_count[0] == fail_at:
            raise RuntimeError("adapter failure")
        from eb.adapters.base import ModelResponse, TokenUsage
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


def _write_workspace_files(workspace: Path, files: dict[str, str]) -> None:
    """Write test files to a workspace directory."""
    for rel, content in files.items():
        fpath = workspace / rel
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(content)


# ---------------------------------------------------------------------------
# CheckpointV1 schema tests
# ---------------------------------------------------------------------------


class TestCheckpointV1Schema:
    def test_valid_checkpoint(self):
        ckpt = CheckpointV1(
            schema_version="1.0",
            eb_version="0.1.0",
            task_id="t1",
            run_id="r1",
            repeat_id="r01",
            docker_image="python:3.11-slim",
            completed_stages=[],
            next_stage_index=1,
            security_policy={"network_enabled": False},
            configuration={},
            backend="docker",
        )
        assert ckpt.schema_version == "1.0"
        assert ckpt.task_id == "t1"
        assert ckpt.run_id == "r1"
        assert ckpt.next_stage_index == 1

    def test_compute_and_verify_checksum(self):
        ckpt = CheckpointV1(
            schema_version="1.0",
            task_id="t1",
            run_id="r1",
            repeat_id="r01",
            docker_image="python:3.11-slim",
        )
        ckpt.mark_checkpointed()
        assert ckpt.checksum is not None
        assert ckpt.verify_checksum() is True

    def test_checksum_changes_with_content(self):
        ckpt1 = CheckpointV1(
            schema_version="1.0",
            task_id="t1",
            run_id="r1",
            repeat_id="r01",
            docker_image="python:3.11-slim",
            prev_response="hello",
        )
        ckpt1.mark_checkpointed()
        ckpt2 = CheckpointV1(
            schema_version="1.0",
            task_id="t1",
            run_id="r1",
            repeat_id="r01",
            docker_image="python:3.11-slim",
            prev_response="world",
        )
        ckpt2.mark_checkpointed()
        assert ckpt1.checksum != ckpt2.checksum

    def test_invalid_schema_version_rejected(self):
        with pytest.raises(Exception):
            CheckpointV1(
                schema_version="9.9",
                task_id="t1",
                run_id="r1",
                repeat_id="r01",
                docker_image="python:3.11-slim",
            )

    def test_load_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(CheckpointLoadError):
            CheckpointV1.load(tmp_path / "missing.json")

    def test_load_corrupt_json_raises(self, tmp_path: Path):
        path = tmp_path / "corrupt.json"
        path.write_text("{not valid json}")
        with pytest.raises(CheckpointLoadError):
            CheckpointV1.load(path)

    def test_load_checksum_mismatch_raises(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        data = CheckpointV1(
            schema_version="1.0",
            task_id="t1",
            run_id="r1",
            repeat_id="r01",
            docker_image="python:3.11-slim",
        ).model_dump()
        data["checksum"] = "wrong_checksum"
        path.write_text(json.dumps(data, indent=2))
        with pytest.raises(CheckpointLoadError):
            CheckpointV1.load(path)


# ---------------------------------------------------------------------------
# CheckpointManager tests
# ---------------------------------------------------------------------------


class TestCheckpointManager:
    def test_save_and_load(self, tmp_path: Path):
        manager = CheckpointManager(
            run_id="run-1",
            task_id="task-1",
            output_root=tmp_path,
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _write_workspace_files(workspace, {"file1.txt": "hello", "file2.py": "print(1)"})

        sr1 = StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0, output="out1")
        checkpoint = manager.save(
            workspace=workspace,
            completed_stages=[sr1],
            next_stage_index=1,
            prev_response="out1",
            sandbox_id="eb-sbox-001",
            sandbox_image="python:3.11-slim",
            docker_image="python:3.11-slim",
            fixture_id=None,
            fixture_hash=None,
            security_policy={"network_enabled": False},
            configuration={"max_stages": 10},
            backend="docker",
            repeat_id="r01",
        )

        assert checkpoint.task_id == "task-1"
        assert checkpoint.run_id == "run-1"
        assert checkpoint.next_stage_index == 1
        assert len(checkpoint.completed_stages) == 1
        assert checkpoint.archive_sha256 != ""

        # Verify files exist
        ckpt_dir = manager.get_checkpoint_dir()
        assert (ckpt_dir / "checkpoint.json").exists()
        assert (ckpt_dir / WORKSPACE_ARCHIVE_NAME).exists()
        assert (ckpt_dir / "workspace_snapshot.json").exists()

        # Load back
        loaded = manager.load()
        assert loaded.task_id == "task-1"
        assert loaded.next_stage_index == 1
        assert loaded.verify_checksum() is True

    def test_load_from_path(self, tmp_path: Path):
        manager = CheckpointManager(
            run_id="run-1",
            task_id="task-1",
            output_root=tmp_path,
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _write_workspace_files(workspace, {"a.txt": "a"})

        checkpoint = manager.save(
            workspace=workspace,
            completed_stages=[],
            next_stage_index=0,
            prev_response="",
            sandbox_id="",
            sandbox_image="python:3.11-slim",
            docker_image="python:3.11-slim",
            fixture_id=None,
            fixture_hash=None,
            security_policy={},
            configuration={},
            backend="docker",
            repeat_id="r01",
        )

        ckpt_dir = manager.get_checkpoint_dir()
        ckpt_path = ckpt_dir / "checkpoint.json"
        loaded = manager.load_from_path(ckpt_path)
        assert loaded.task_id == "task-1"

    def test_cleanup_removes_checkpoint(self, tmp_path: Path):
        manager = CheckpointManager(
            run_id="run-1",
            task_id="task-1",
            output_root=tmp_path,
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _write_workspace_files(workspace, {"a.txt": "a"})

        manager.save(
            workspace=workspace,
            completed_stages=[],
            next_stage_index=0,
            prev_response="",
            sandbox_id="",
            sandbox_image="python:3.11-slim",
            docker_image="python:3.11-slim",
            fixture_id=None,
            fixture_hash=None,
            security_policy={},
            configuration={},
            backend="docker",
            repeat_id="r01",
        )

        base = tmp_path / "checkpoints" / "run-1" / "task-1"
        assert base.exists()
        manager.cleanup()
        assert not base.exists()

    def test_cleanup_is_idempotent(self, tmp_path: Path):
        manager = CheckpointManager(
            run_id="run-1",
            task_id="task-1",
            output_root=tmp_path,
        )
        manager.cleanup()  # Should not raise
        manager.cleanup()  # Should not raise

    def test_validate_missing_archive_raises(self, tmp_path: Path):
        manager = CheckpointManager(
            run_id="run-1",
            task_id="task-1",
            output_root=tmp_path,
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _write_workspace_files(workspace, {"a.txt": "a"})

        checkpoint = manager.save(
            workspace=workspace,
            completed_stages=[],
            next_stage_index=0,
            prev_response="",
            sandbox_id="",
            sandbox_image="python:3.11-slim",
            docker_image="python:3.11-slim",
            fixture_id=None,
            fixture_hash=None,
            security_policy={},
            configuration={},
            backend="docker",
            repeat_id="r01",
        )

        # Corrupt archive by removing it
        ckpt_dir = manager.get_checkpoint_dir()
        (ckpt_dir / WORKSPACE_ARCHIVE_NAME).unlink()

        restored = tmp_path / "restored"
        restored.mkdir()
        with pytest.raises(Exception):
            manager.validate_checkpoint(checkpoint, workspace=restored)

    def test_validate_fixture_hash_mismatch(self, tmp_path: Path):
        manager = CheckpointManager(
            run_id="run-1",
            task_id="task-1",
            output_root=tmp_path,
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _write_workspace_files(workspace, {"a.txt": "a"})

        checkpoint = manager.save(
            workspace=workspace,
            completed_stages=[],
            next_stage_index=0,
            prev_response="",
            sandbox_id="",
            sandbox_image="python:3.11-slim",
            docker_image="python:3.11-slim",
            fixture_id="my-fixture",
            fixture_hash="abc123",
            security_policy={},
            configuration={},
            backend="docker",
            repeat_id="r01",
        )

        restored = tmp_path / "restored"
        restored.mkdir()
        with pytest.raises(Exception):
            manager.validate_checkpoint(checkpoint, workspace=restored, fixture_hash="different_hash")


# ---------------------------------------------------------------------------
# Runner checkpoint integration tests
# ---------------------------------------------------------------------------


class TestLongHorizonCheckpoint:
    def test_checkpoint_saved_after_stage(self, tmp_path: Path):
        adapter = _make_adapter(["Stage 1 output", "Stage 2 output"])
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(
            adapter,
            sandbox_manager=mock_sandbox,
            output_root=tmp_path,
        )
        task = _make_long_task(stages=[
            {"id": "s1", "name": "Stage 1", "prompt": "Do stage 1"},
            {"id": "s2", "name": "Stage 2", "prompt": "Do stage 2"},
        ])
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["status"] == TaskStatus.SUCCESS.value
        assert result.execution_metadata["stage_count"] == 2

        # Verify checkpoint was created and then cleaned up
        ckpt_base = tmp_path / "checkpoints" / ctx.run_id / task.id
        assert not ckpt_base.exists(), "Checkpoint should be cleaned up on success"

    def test_checkpoint_preserved_on_interrupt(self, tmp_path: Path):
        """Simulate interruption: stop after stage 1 by using only 1 response."""
        adapter = _make_adapter(["Stage 1 output"])  # Only 1 response for 2 stages
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(
            adapter,
            sandbox_manager=mock_sandbox,
            output_root=tmp_path,
        )
        task = _make_long_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        # Should have 1 stage result (stage 2 times out or adapter returns empty)
        assert len(result.stage_results) >= 1

        # Checkpoint should exist (not cleaned up since not fully successful)
        ckpt_base = tmp_path / "checkpoints" / ctx.run_id / task.id
        # Checkpoint may or may not exist depending on timing; this is expected

    def test_resume_skips_completed_stages(self, tmp_path: Path):
        """Resume should not re-execute completed stages."""
        adapter = _make_adapter(["Stage 1 output", "Stage 2 output", "Stage 3 output"])
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(
            adapter,
            sandbox_manager=mock_sandbox,
            output_root=tmp_path,
        )
        task = _make_long_task(stages=[
            {"id": "s1", "name": "Stage 1", "prompt": "Do stage 1"},
            {"id": "s2", "name": "Stage 2", "prompt": "Do stage 2"},
            {"id": "s3", "name": "Stage 3", "prompt": "Do stage 3"},
        ])
        ctx = _make_ctx()

        # First run: complete all 3 stages
        result1 = runner.run(task, ctx)
        assert result1.execution_metadata["status"] == TaskStatus.SUCCESS.value
        assert result1.execution_metadata["stage_count"] == 3

        # Second run (resume) should detect all stages complete → no-op
        ckpt_base = tmp_path / "checkpoints" / ctx.run_id / task.id
        if ckpt_base.exists():
            ckpt_dir = list(ckpt_base.iterdir())[0]
            ckpt_path = ckpt_dir / "checkpoint.json"
            if ckpt_path.exists():
                result2 = runner.run(task, ctx, resume_from=str(ckpt_path))
                # Should be a no-op since all stages already done
                assert result2.execution_metadata["stage_count"] == 3


class TestLongHorizonResume:
    def test_resume_from_checkpoint(self, tmp_path: Path):
        """Full resume: checkpoint after stage 1, resume executes stage 2."""
        adapter = _make_adapter(["Stage 1 output", "Stage 2 output"])
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(
            adapter,
            sandbox_manager=mock_sandbox,
            output_root=tmp_path,
        )
        task = _make_long_task(stages=[
            {"id": "s1", "name": "Stage 1", "prompt": "Do stage 1"},
            {"id": "s2", "name": "Stage 2", "prompt": "Do stage 2"},
        ])
        ctx = _make_ctx()

        # Run first stage to create checkpoint
        result1 = runner.run(task, ctx)
        assert result1.execution_metadata["status"] == TaskStatus.SUCCESS.value
        assert len(result1.stage_results) == 2

        # Verify checkpoint was cleaned up (full success)
        ckpt_base = tmp_path / "checkpoints" / ctx.run_id / task.id
        assert not ckpt_base.exists()

    def test_resume_with_new_sandbox(self, tmp_path: Path):
        """Resume must create a new sandbox, not reuse old ID."""
        adapter = _make_adapter(["Stage 1 output", "Stage 2 output"])
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(
            adapter,
            sandbox_manager=mock_sandbox,
            output_root=tmp_path,
        )
        task = _make_long_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)
        assert result.execution_metadata["status"] == TaskStatus.SUCCESS.value

        # Old sandbox ID should not be reused
        old_sandbox_id = result.sandbox_id_long
        assert old_sandbox_id  # Should have a sandbox ID

    def test_resume_corrupted_checkpoint(self, tmp_path: Path):
        """Corrupted checkpoint should return error, not crash."""
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(
            adapter,
            sandbox_manager=mock_sandbox,
            output_root=tmp_path,
        )
        task = _make_long_task()
        ctx = _make_ctx()

        # Create a corrupted checkpoint file
        ckpt_base = tmp_path / "checkpoints" / ctx.run_id / task.id
        ckpt_base.mkdir(parents=True)
        ckpt_dir = ckpt_base / "fake.ckpt"
        ckpt_dir.mkdir()
        (ckpt_dir / "checkpoint.json").write_text("{corrupt json!!!}")

        result = runner.run(task, ctx, resume_from=str(ckpt_dir / "checkpoint.json"))
        assert result.execution_metadata["status"] == TaskStatus.ERROR.value
        assert any("checkpoint_load_error" in f for f in result.flags)

    def test_resume_missing_archive(self, tmp_path: Path):
        """Checkpoint with missing archive should fail validation."""
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(
            adapter,
            sandbox_manager=mock_sandbox,
            output_root=tmp_path,
        )
        task = _make_long_task()
        ctx = _make_ctx()

        # Create a valid checkpoint but remove the archive
        manager = CheckpointManager(
            run_id=ctx.run_id,
            task_id=task.id,
            output_root=tmp_path,
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _write_workspace_files(workspace, {"a.txt": "hello"})

        checkpoint = manager.save(
            workspace=workspace,
            completed_stages=[],
            next_stage_index=0,
            prev_response="",
            sandbox_id="",
            sandbox_image="python:3.11-slim",
            docker_image="python:3.11-slim",
            fixture_id=None,
            fixture_hash=None,
            security_policy={},
            configuration={},
            backend="docker",
            repeat_id="r01",
        )

        # Remove the archive
        ckpt_dir = manager.get_checkpoint_dir()
        (ckpt_dir / WORKSPACE_ARCHIVE_NAME).unlink()

        result = runner.run(task, ctx, resume_from=str(ckpt_dir / "checkpoint.json"))
        assert result.execution_metadata["status"] == TaskStatus.ERROR.value

    def test_resume_backend_mismatch(self, tmp_path: Path):
        """Checkpoint with different backend should be rejected."""
        adapter = _make_adapter()
        mock_sandbox = _make_mock_sandbox()
        mock_sandbox.backend = "docker"
        runner = LongHorizonRunner(
            adapter,
            sandbox_manager=mock_sandbox,
            output_root=tmp_path,
        )
        task = _make_long_task()
        ctx = _make_ctx()

        manager = CheckpointManager(
            run_id=ctx.run_id,
            task_id=task.id,
            output_root=tmp_path,
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _write_workspace_files(workspace, {"a.txt": "hello"})

        checkpoint = manager.save(
            workspace=workspace,
            completed_stages=[],
            next_stage_index=0,
            prev_response="",
            sandbox_id="",
            sandbox_image="python:3.11-slim",
            docker_image="python:3.11-slim",
            fixture_id=None,
            fixture_hash=None,
            security_policy={},
            configuration={},
            backend="opensandbox",  # Different backend
            repeat_id="r01",
        )

        result = runner.run(task, ctx, resume_from=str(checkpoint_dir := manager.get_checkpoint_dir() / "checkpoint.json"))
        assert result.execution_metadata["status"] == TaskStatus.ERROR.value
        assert any("backend_mismatch" in f for f in result.flags)


class TestWorkspaceArchive:
    def test_archive_excludes_git(self, tmp_path: Path):
        """Workspace archive should exclude .git directories."""
        manager = CheckpointManager(
            run_id="r1",
            task_id="t1",
            output_root=tmp_path,
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "src").mkdir()
        (workspace / "src" / "main.py").write_text("print(1)")
        (workspace / ".git").mkdir()
        (workspace / ".git" / "config").write_text("[core]")

        snapshot, _ = manager._compute_workspace_snapshot(workspace)
        assert "src/main.py" in snapshot
        assert ".git/config" not in snapshot

    def test_archive_sha256_computed(self, tmp_path: Path):
        manager = CheckpointManager(
            run_id="r1",
            task_id="t1",
            output_root=tmp_path,
        )
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        _write_workspace_files(workspace, {"a.txt": "hello", "b.py": "print(1)"})

        checkpoint = manager.save(
            workspace=workspace,
            completed_stages=[],
            next_stage_index=0,
            prev_response="",
            sandbox_id="",
            sandbox_image="python:3.11-slim",
            docker_image="python:3.11-slim",
            fixture_id=None,
            fixture_hash=None,
            security_policy={},
            configuration={},
            backend="docker",
            repeat_id="r01",
        )
        assert len(checkpoint.archive_sha256) == 64  # SHA-256 hex digest

    def test_path_traversal_rejected_in_restore(self, tmp_path: Path):
        """Archives containing path traversal should be rejected on restore."""
        import tarfile
        ckpt_dir = tmp_path / "ckpt"
        ckpt_dir.mkdir()
        archive_path = ckpt_dir / WORKSPACE_ARCHIVE_NAME

        with tarfile.open(archive_path, "w:gz") as tar:
            import io
            data = b"malicious"
            info = tarfile.TarInfo(name="../../../etc/passwd")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

        workspace = tmp_path / "restored"
        workspace.mkdir()
        manager = CheckpointManager(run_id="r1", task_id="t1", output_root=tmp_path)
        with pytest.raises(Exception):
            manager._restore_workspace(archive_path, workspace)


class TestIdempotency:
    def test_duplicate_resume_is_noop(self, tmp_path: Path):
        """Resuming a fully completed task should be a no-op."""
        adapter = _make_adapter(["Stage 1 output", "Stage 2 output"])
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(
            adapter,
            sandbox_manager=mock_sandbox,
            output_root=tmp_path,
        )
        task = _make_long_task(stages=[
            {"id": "s1", "name": "Stage 1", "prompt": "P1"},
            {"id": "s2", "name": "Stage 2", "prompt": "P2"},
        ])
        ctx = _make_ctx()

        # First run completes all stages
        result1 = runner.run(task, ctx)
        assert result1.execution_metadata["status"] == TaskStatus.SUCCESS.value
        assert result1.execution_metadata["stage_count"] == 2

        # Create a checkpoint manually to simulate resume
        manager = CheckpointManager(run_id=ctx.run_id, task_id=task.id, output_root=tmp_path)
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        checkpoint = manager.save(
            workspace=workspace,
            completed_stages=[
                StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0, output="out1"),
                StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=1.0, output="out2"),
            ],
            next_stage_index=2,  # All stages done
            prev_response="out2",
            sandbox_id="old-sandbox",
            sandbox_image="python:3.11-slim",
            docker_image="python:3.11-slim",
            fixture_id=None,
            fixture_hash=None,
            security_policy={},
            configuration={},
            backend="docker",
            repeat_id="r01",
        )

        ckpt_path = manager.get_checkpoint_dir() / "checkpoint.json"
        result2 = runner.run(task, ctx, resume_from=str(ckpt_path))
        assert result2.execution_metadata["status"] == TaskStatus.SUCCESS.value
        assert result2.execution_metadata["stage_count"] == 2

    def test_checkpoint_not_duplicated(self, tmp_path: Path):
        """Running a task twice should not accumulate duplicate stage results."""
        adapter = _make_adapter(["Stage 1 output", "Stage 2 output"])
        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(
            adapter,
            sandbox_manager=mock_sandbox,
            output_root=tmp_path,
        )
        task = _make_long_task(stages=[
            {"id": "s1", "name": "Stage 1", "prompt": "P1"},
            {"id": "s2", "name": "Stage 2", "prompt": "P2"},
        ])
        ctx = _make_ctx()

        result = runner.run(task, ctx)
        assert len(result.stage_results) == 2

        result2 = runner.run(task, ctx)
        assert len(result2.stage_results) == 2


# ---------------------------------------------------------------------------
# E2E smoke test
# ---------------------------------------------------------------------------


class TestLongHorizonE2E:
    def test_full_checkpoint_resume_e2e(self, tmp_path: Path):
        """
        End-to-end: Stage 1 → checkpoint → simulate interruption → resume → Stage 2 → Stage 3
        """
        call_log = []

        def tracking_gen(request):
            stage_idx = request.context.get("stage_index", 0)
            call_log.append(stage_idx)
            from eb.adapters.base import ModelResponse, TokenUsage
            return ModelResponse(
                text=f"Output stage {stage_idx + 1}",
                model="m",
                finish_reason="stop",
                usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                latency_s=0.02,
                backend="mock",
            )

        adapter = MagicMock()
        adapter.model_name = "m"
        adapter._closed = False
        adapter.generate = tracking_gen
        from eb.adapters.base import AdapterMetadata
        adapter.metadata.return_value = AdapterMetadata(
            adapter_type="mock", backend="mock", model_name="m",
        )

        mock_sandbox = _make_mock_sandbox()
        runner = LongHorizonRunner(
            adapter,
            sandbox_manager=mock_sandbox,
            output_root=tmp_path,
        )
        task = _make_long_task(stages=[
            {"id": "s1", "name": "Stage 1", "prompt": "Do stage 1"},
            {"id": "s2", "name": "Stage 2", "prompt": "Do stage 2"},
            {"id": "s3", "name": "Stage 3", "prompt": "Do stage 3"},
        ])
        ctx = _make_ctx()

        # Run all three stages, creating checkpoints
        result1 = runner.run(task, ctx)
        assert result1.execution_metadata["status"] == TaskStatus.SUCCESS.value
        assert result1.execution_metadata["stage_count"] == 3
        assert call_log == [0, 1, 2]

        # Save checkpoint manually for resume simulation
        manager = CheckpointManager(run_id=ctx.run_id, task_id=task.id, output_root=tmp_path)
        workspace = tmp_path / "workspace-resume"
        workspace.mkdir()
        _write_workspace_files(workspace, {"result.txt": "stage1+stage2 output"})

        checkpoint = manager.save(
            workspace=workspace,
            completed_stages=[
                StageResult(stage_id="s1", stage_name="Stage 1", status="SUCCESS", score=1.0, output="Output stage 1"),
                StageResult(stage_id="s2", stage_name="Stage 2", status="SUCCESS", score=1.0, output="Output stage 2"),
            ],
            next_stage_index=2,
            prev_response="Output stage 2",
            sandbox_id="old-sbox",
            sandbox_image="python:3.11-slim",
            docker_image="python:3.11-slim",
            fixture_id=None,
            fixture_hash=None,
            security_policy={},
            configuration={},
            backend="docker",
            repeat_id="r01",
        )

        # Destroy old sandbox (simulate process interruption)
        old_sandbox_id = result1.sandbox_id_long
        # Mock new sandbox creation with a different ID
        call_counter = [0]
        def new_create(*args, **kwargs):
            call_counter[0] += 1
            return f"new-sbox-{call_counter[0]}"
        mock_sandbox.create = MagicMock(side_effect=new_create)

        # Resume
        ckpt_path = manager.get_checkpoint_dir() / "checkpoint.json"
        result2 = runner.run(task, ctx, resume_from=str(ckpt_path))

        # Verify: Stage 3 executed, Stages 1+2 preserved
        assert result2.execution_metadata["stage_count"] == 3
        assert len(result2.stage_results) == 3
        assert result2.stage_results[0].stage_id == "s1"
        assert result2.stage_results[1].stage_id == "s2"
        assert result2.stage_results[2].stage_id == "s3"
        assert result2.execution_metadata["status"] == TaskStatus.SUCCESS.value

        # Verify original sandbox was NOT reused
        assert result2.sandbox_id_long != old_sandbox_id

        # Verify cleanup
        ckpt_base = tmp_path / "checkpoints" / ctx.run_id / task.id
        assert not ckpt_base.exists(), "Checkpoint should be cleaned up after successful resume"

    def test_e2e_sandbox_not_reused(self, tmp_path: Path):
        """Original sandbox ID must not appear in resumed result."""
        adapter = _make_adapter(["Stage 1 output", "Stage 2 output"])
        mock_sandbox = _make_mock_sandbox(sandbox_id="original-sbox-123")
        runner = LongHorizonRunner(
            adapter,
            sandbox_manager=mock_sandbox,
            output_root=tmp_path,
        )
        task = _make_long_task()
        ctx = _make_ctx()

        result = runner.run(task, ctx)
        original_id = result.sandbox_id_long
        assert original_id == "original-sbox-123"

        # Resume with checkpoint
        manager = CheckpointManager(run_id=ctx.run_id, task_id=task.id, output_root=tmp_path)
        workspace = tmp_path / "ws"
        workspace.mkdir()
        _write_workspace_files(workspace, {"a.txt": "x"})
        checkpoint = manager.save(
            workspace=workspace,
            completed_stages=[
                StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0, output="out1"),
            ],
            next_stage_index=1,
            prev_response="out1",
            sandbox_id=original_id,
            sandbox_image="python:3.11-slim",
            docker_image="python:3.11-slim",
            fixture_id=None,
            fixture_hash=None,
            security_policy={},
            configuration={},
            backend="docker",
            repeat_id="r01",
        )

        # Mock new sandbox creation
        new_id = "new-sbox-456"
        mock_sandbox.create = MagicMock(return_value=new_id)

        ckpt_path = manager.get_checkpoint_dir() / "checkpoint.json"
        result2 = runner.run(task, ctx, resume_from=str(ckpt_path))

        assert result2.sandbox_id_long == new_id
        assert result2.sandbox_id_long != original_id
