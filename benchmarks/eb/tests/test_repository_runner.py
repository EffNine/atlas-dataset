"""Tests for eb/runners/repository.py — EXEC runner, tool protocol, bounded execution."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from eb.runners.repository import (
    RepositoryRunner,
    RepositoryFixture,
    ToolCall,
    ToolResult,
    ExecRunContext,
)
from eb.runners.base import RunContext, TaskStatus
from eb.core.schema import Task, TaskResult
from eb.core.types import ExecutionMode, Difficulty, Capability, BenchmarkPartition
from eb.adapters.base import ModelAdapter, ModelRequest, ModelResponse, TokenUsage
from eb.sandbox.security import SecurityPolicy


def _make_exec_task(
    task_id: str = "EB-EXEC-001",
    repository_id: str = "eb-python-bug-001",
    **overrides,
) -> Task:
    defaults = {
        "id": task_id,
        "category": "debug",
        "mode": ExecutionMode.EXEC,
        "difficulty": Difficulty.L2,
        "capabilities": [Capability.CODE, Capability.DEBUG],
        "prompt": f"Fix the bug in {repository_id}",
        "partition": BenchmarkPartition.DEVELOPMENT,
        "context": {"repository_id": repository_id},
    }
    defaults.update(overrides)
    return Task.model_validate(defaults)


def _make_mock_adapter(
    responses: list[str] | None = None,
    fail: bool = False,
) -> ModelAdapter:
    adapter = MagicMock(spec=ModelAdapter)
    adapter.model_name = "test-model"
    adapter._closed = False

    if responses is None:
        responses = ["FINAL_ANSWER: Bug fixed."]

    call_count = [0]

    def gen(request: ModelRequest) -> ModelResponse:
        if fail:
            raise RuntimeError("adapter failure")
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


def _make_ctx(run_id: str = "run-exec-001", repeat: int = 0, **overrides) -> RunContext:
    defaults = {
        "run_id": run_id,
        "model_name": "test-model",
        "suite": "exec",
        "inference_settings": {
            "seed": 42, "temperature": 0.0, "top_p": 1.0,
            "top_k": 0, "max_tokens": 4096,
        },
        "repeat_index": repeat,
    }
    defaults.update(overrides)
    return RunContext(**defaults)


class TestToolProtocol:
    def test_tool_call_serialization(self):
        tc = ToolCall(tool_name="read_file", arguments={"path": "src/main.py"}, call_id="call-001")
        d = tc.to_dict()
        assert d["tool_name"] == "read_file"
        assert d["arguments"] == {"path": "src/main.py"}
        assert d["call_id"] == "call-001"
        assert "T" in d["timestamp"]

    def test_tool_result_serialization(self):
        tr = ToolResult(
            call_id="call-001",
            tool_name="run_command",
            success=True,
            output="PASSED",
            exit_code=0,
            duration_s=0.5,
        )
        d = tr.to_dict()
        assert d["success"] is True
        assert d["output"] == "PASSED"
        assert d["exit_code"] == 0
        assert d["truncated"] is False

    def test_tool_result_truncation(self):
        tr = ToolResult(
            call_id="call-002",
            tool_name="run_command",
            success=True,
            output="x" * 3000,
            truncated=True,
        )
        d = tr.to_dict()
        assert len(d["output"]) <= 2000
        assert d["truncated"] is True


class TestExecRunContext:
    def test_record_tool_call(self):
        ctx = ExecRunContext(
            run_id="r1", task_id="t1", repeat_id="r01", workspace=Path("/tmp"),
        )
        call = ToolCall(tool_name="list_files", arguments={"path": "."})
        ctx.record_tool_call(call)
        assert len(ctx.tool_history) == 1
        assert ctx.tool_history[0].tool_name == "list_files"

    def test_record_command(self):
        from eb.sandbox.base import ExecResult
        ctx = ExecRunContext(
            run_id="r1", task_id="t1", repeat_id="r01", workspace=Path("/tmp"),
        )
        result = ExecResult(command=["pytest", "-q"], exit_code=0, stdout="3 passed", duration_s=1.2)
        ctx.record_command(["pytest", "-q"], result)
        assert len(ctx.command_history) == 1
        assert ctx.command_history[0]["exit_code"] == 0


class TestRepositoryRunner:
    def test_mode_property(self):
        adapter = _make_mock_adapter()
        runner = RepositoryRunner(adapter=adapter)
        assert runner.mode == ExecutionMode.EXEC

    def test_rejects_non_exec_task(self):
        adapter = _make_mock_adapter()
        runner = RepositoryRunner(adapter=adapter)
        task = _make_exec_task(mode=ExecutionMode.SINGLE)
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["status"] == TaskStatus.SKIPPED.value
        assert any("mode_mismatch" in f for f in result.flags)

    def test_missing_fixture_returns_error(self):
        adapter = _make_mock_adapter()
        runner = RepositoryRunner(adapter=adapter)
        task = _make_exec_task(repository_id="nonexistent-fixture")
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["status"] == TaskStatus.ERROR.value
        assert any("fixture_not_found" in f for f in result.flags)

    def test_bounded_tool_calls(self, tmp_path: Path, monkeypatch):
        """Runner should respect max_tool_calls limit."""
        # Create a fake fixture
        fixtures_root = tmp_path / "repositories"
        fixture_dir = fixtures_root / "bounded-test-001"
        fixture_dir.mkdir(parents=True)
        (fixture_dir / "fixture.json").write_text(json.dumps({
            "id": "bounded-test-001",
            "image": "python:3.11-slim",
            "test_command": "pytest -q",
        }))
        src = fixture_dir / "source"
        src.mkdir()
        (src / "main.py").write_text("x = 1\n")

        monkeypatch.setattr("eb.paths.repositories_dir", lambda *a, **k: fixtures_root)

        # Model keeps requesting tool calls
        responses = [
            "TOOL_CALL:list_files:{\"path\": \".\"}",
            "TOOL_CALL:read_file:{\"path\": \"main.py\"}",
            "TOOL_CALL:run_command:{\"command\": [\"python\", \"-c\", \"print(1)\"]}",
        ]
        adapter = _make_mock_adapter(responses=responses)
        runner = RepositoryRunner(adapter=adapter, max_tool_calls=2)
        task = _make_exec_task(repository_id="bounded-test-001")
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["status"] in (TaskStatus.SUCCESS.value, TaskStatus.ERROR.value)
        tool_calls = result.execution_metadata.get("tool_calls", [])
        assert len(tool_calls) <= 2

    def test_timeout_status_recorded(self, tmp_path: Path, monkeypatch):
        """When tool calls exceed limit, timeout_status should be EXCEEDED."""
        fixtures_root = tmp_path / "repositories"
        fixture_dir = fixtures_root / "timeout-test-001"
        fixture_dir.mkdir(parents=True)
        (fixture_dir / "fixture.json").write_text(json.dumps({
            "id": "timeout-test-001",
            "image": "python:3.11-slim",
            "test_command": "pytest -q",
        }))
        src = fixture_dir / "source"
        src.mkdir()
        (src / "main.py").write_text("x = 1\n")

        monkeypatch.setattr("eb.runners.repository.repositories_dir", lambda *a, **k: fixtures_root)

        responses = [
            "TOOL_CALL:list_files:{\"path\": \".\"}",
            "TOOL_CALL:read_file:{\"path\": \"main.py\"}",
        ]
        adapter = _make_mock_adapter(responses=responses)
        runner = RepositoryRunner(adapter=adapter, max_tool_calls=1)

        mock_sandbox = MagicMock()
        mock_sandbox.create.return_value = "eb-sbox-timeout"
        mock_sandbox.exec.return_value = MagicMock(
            success=True, exit_code=0, stdout="", stderr="", duration_s=0.01,
        )
        mock_sandbox.collect.return_value = {}
        mock_sandbox.stop = MagicMock()
        mock_sandbox.destroy = MagicMock()
        runner._sandbox_manager = mock_sandbox

        task = _make_exec_task(repository_id="timeout-test-001")
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.execution_metadata["timeout_status"] == "EXCEEDED"


class TestPathValidation:
    def test_path_traversal_rejected_in_tools(self, tmp_path: Path, monkeypatch):
        """Path traversal should be rejected by tool execution."""
        fixtures_root = tmp_path / "repositories"
        fixture_dir = fixtures_root / "path-test-001"
        fixture_dir.mkdir(parents=True)
        (fixture_dir / "fixture.json").write_text(json.dumps({
            "id": "path-test-001",
            "image": "python:3.11-slim",
            "test_command": "pytest -q",
        }))
        src = fixture_dir / "source"
        src.mkdir()
        (src / "main.py").write_text("x = 1\n")

        monkeypatch.setattr("eb.runners.repository.repositories_dir", lambda *a, **k: fixtures_root)

        adapter = _make_mock_adapter(responses=["TOOL_CALL:read_file:{\"path\": \"../etc/passwd\"}"])
        runner = RepositoryRunner(adapter=adapter, max_tool_calls=5)
        task = _make_exec_task(repository_id="path-test-001")
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        # Should not crash; tool call should be rejected
        assert result.task_id == "EB-EXEC-001"


class TestRunnerIntegration:
    def test_final_answer_without_tool_calls(self, tmp_path: Path, monkeypatch):
        """Model can return FINAL_ANSWER without any tool calls."""
        fixtures_root = tmp_path / "repositories"
        fixture_dir = fixtures_root / "answer-test-001"
        fixture_dir.mkdir(parents=True)
        (fixture_dir / "fixture.json").write_text(json.dumps({
            "id": "answer-test-001",
            "image": "python:3.11-slim",
            "test_command": "pytest -q",
        }))
        src = fixture_dir / "source"
        src.mkdir()
        (src / "main.py").write_text("x = 1\n")

        monkeypatch.setattr("eb.runners.repository.repositories_dir", lambda *a, **k: fixtures_root)

        adapter = _make_mock_adapter(responses=["FINAL_ANSWER:The bug is in line 5."])
        runner = RepositoryRunner(adapter=adapter, max_tool_calls=5)

        mock_sandbox = MagicMock()
        mock_sandbox.create.return_value = "eb-sbox-answer"
        mock_sandbox.exec.return_value = MagicMock(
            success=True, exit_code=0, stdout="", stderr="", duration_s=0.01,
        )
        mock_sandbox.collect.return_value = {}
        mock_sandbox.stop = MagicMock()
        mock_sandbox.destroy = MagicMock()
        runner._sandbox_manager = mock_sandbox

        task = _make_exec_task(repository_id="answer-test-001")
        ctx = _make_ctx()

        result = runner.run(task, ctx)

        assert result.raw_response is not None
        assert "The bug is in line 5" in result.raw_response
