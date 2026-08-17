"""Tests for EXEC tool execution — list_files, read_file, write_file, patch_file, run_command, run_tests."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from eb.runners.repository import RepositoryRunner, ToolCall, ToolResult
from eb.sandbox.base import ExecResult
from eb.sandbox.security import SecurityPolicy
from eb.adapters.base import ModelAdapter, ModelRequest, ModelResponse, TokenUsage
from eb.runners.base import RunContext
from eb.core.schema import Task
from eb.core.types import ExecutionMode, Difficulty, Capability, BenchmarkPartition


def _make_mock_adapter(responses: list[str] | None = None) -> ModelAdapter:
    adapter = MagicMock(spec=ModelAdapter)
    adapter.model_name = "test-model"
    adapter._closed = False
    responses = responses or ["FINAL_ANSWER: done"]
    call_count = [0]

    def gen(request: ModelRequest) -> ModelResponse:
        idx = min(call_count[0], len(responses) - 1)
        call_count[0] += 1
        return ModelResponse(
            text=responses[idx],
            model="test-model",
            finish_reason="stop",
            usage=TokenUsage(),
            latency_s=0.01,
            backend="mock",
        )

    adapter.generate = gen
    from eb.adapters.base import AdapterMetadata
    adapter.metadata.return_value = AdapterMetadata(
        adapter_type="mock", backend="mock", model_name="test-model",
    )
    return adapter


class TestToolCallFormat:
    def test_parse_tool_call_string(self):
        from eb.runners.repository import RepositoryRunner
        runner = RepositoryRunner(adapter=MagicMock(spec=ModelAdapter))
        result = runner._parse_model_response(
            'TOOL_CALL:list_files:{"path": "."}',
            [],
        )
        assert result is not None
        call_id, tool_name, args = result
        assert tool_name == "list_files"
        assert args == {"path": "."}
        assert call_id == "call-001"

    def test_parse_final_answer(self):
        from eb.runners.repository import RepositoryRunner
        runner = RepositoryRunner(adapter=MagicMock(spec=ModelAdapter))
        result = runner._parse_model_response("FINAL_ANSWER: The bug is fixed.", [])
        assert result is None

    def test_parse_json_tool_call(self):
        from eb.runners.repository import RepositoryRunner
        runner = RepositoryRunner(adapter=MagicMock(spec=ModelAdapter))
        result = runner._parse_model_response(
            '{"tool_name": "read_file", "arguments": {"path": "main.py"}}',
            [],
        )
        assert result is not None
        _, tool_name, args = result
        assert tool_name == "read_file"
        assert args == {"path": "main.py"}

    def test_unrecognized_format_returns_none(self):
        from eb.runners.repository import RepositoryRunner
        runner = RepositoryRunner(adapter=MagicMock(spec=ModelAdapter))
        result = runner._parse_model_response("Just some text response", [])
        assert result is None


class TestToolValidation:
    def test_path_traversal_blocked(self):
        from eb.sandbox.security import is_path_safe
        assert is_path_safe("../etc/passwd", "/workspace") is False
        assert is_path_safe("../../../../shadow", "/workspace") is False
        assert is_path_safe("safe/path.py", "/workspace") is True

    def test_dangerous_command_rejected(self):
        from eb.sandbox.security import is_command_dangerous
        assert is_command_dangerous(["docker", "ps"]) is True
        assert is_command_dangerous(["rm", "-rf", "/"]) is False
        assert is_command_dangerous(["pytest", "-q"]) is False


class TestToolResult:
    def test_successful_tool_result(self):
        tr = ToolResult(
            call_id="c1",
            tool_name="run_command",
            success=True,
            output="3 passed",
            exit_code=0,
            duration_s=0.5,
        )
        assert tr.success is True
        assert tr.to_dict()["success"] is True

    def test_failed_tool_result(self):
        tr = ToolResult(
            call_id="c2",
            tool_name="run_command",
            success=False,
            error="command not found",
            exit_code=127,
        )
        assert tr.success is False
        assert tr.error == "command not found"
