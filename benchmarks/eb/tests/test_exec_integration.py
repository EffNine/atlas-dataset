"""Integration tests for Stage 6 EXEC pipeline — synthetic end-to-end test."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from eb.runners.repository import RepositoryRunner, ToolCall
from eb.runners.base import RunContext, TaskStatus
from eb.core.schema import Task, TaskResult
from eb.core.types import ExecutionMode, Difficulty, Capability, BenchmarkPartition, EvaluatorStatus
from eb.adapters.base import ModelAdapter, ModelRequest, ModelResponse, TokenUsage
from eb.sandbox.security import SecurityPolicy


def _make_mock_adapter_for_exec(responses: list[str]) -> ModelAdapter:
    """Create a mock adapter that returns a sequence of responses."""
    adapter = MagicMock(spec=ModelAdapter)
    adapter.model_name = "synthetic-agent"
    adapter._closed = False

    call_count = [0]

    def gen(request: ModelRequest) -> ModelResponse:
        idx = min(call_count[0], len(responses) - 1)
        call_count[0] += 1
        return ModelResponse(
            text=responses[idx],
            model="synthetic-agent",
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
            latency_s=0.01,
            backend="mock",
        )

    adapter.generate = gen
    from eb.adapters.base import AdapterMetadata
    adapter.metadata.return_value = AdapterMetadata(
        adapter_type="mock", backend="mock", model_name="synthetic-agent",
    )
    return adapter


def _setup_synthetic_fixture(tmp_path: Path) -> str:
    """Create a minimal synthetic repository fixture for testing."""
    fixtures_root = tmp_path / "repositories"
    fixture_dir = fixtures_root / "synthetic-fix-001"
    fixture_dir.mkdir(parents=True)

    manifest = {
        "id": "synthetic-fix-001",
        "version": "1.0",
        "language": "python",
        "framework": "pytest",
        "image": "python:3.11-slim",
        "source_path": "source",
        "test_command": "python -c 'print(1+1)'",
        "timeout": 30.0,
        "expected_base_state": {"files": ["calc.py"]},
    }
    (fixture_dir / "fixture.json").write_text(json.dumps(manifest))

    src = fixture_dir / "source"
    src.mkdir()
    (src / "calc.py").write_text("def add(a, b):\n    return a - b\n")

    tests = fixture_dir / "tests"
    tests.mkdir()
    (tests / "test_calc.py").write_text("""
def test_add():
    assert add(2, 3) == 5
""")

    return "synthetic-fix-001"


class TestSyntheticEXECSmoke:
    """End-to-end synthetic EXEC test: mock agent → sandbox → evaluation."""

    def test_mock_agent_completes_exec_task(self, tmp_path: Path, monkeypatch):
        """
        Synthetic test: mock agent returns FINAL_ANSWER after listing files.
        Proves the EXEC runner handles the full pipeline without Docker.
        """
        fixture_id = _setup_synthetic_fixture(tmp_path)
        monkeypatch.setattr("eb.runners.repository.repositories_dir", lambda *a, **k: tmp_path / "repositories")

        # Mock adapter: agent lists files, then reads, then answers
        responses = [
            "TOOL_CALL:list_files:{\"path\": \".\"}",
            "TOOL_CALL:read_file:{\"path\": \"calc.py\"}",
            "FINAL_ANSWER:I have inspected the code. The bug is in the add function.",
        ]
        adapter = _make_mock_adapter_for_exec(responses)

        # Mock the sandbox manager to avoid Docker dependency
        mock_sandbox = MagicMock()
        mock_sandbox.create.return_value = "eb-sbox-mock-001"
        mock_sandbox.exec.return_value = MagicMock(
            success=True, exit_code=0, stdout="total 8\ndrwxr-xr-x",
            stderr="", duration_s=0.01,
        )
        mock_sandbox.collect.return_value = {"git_diff": None, "changed_files": [], "workspace_snapshot": {}}
        mock_sandbox.stop = MagicMock()
        mock_sandbox.destroy = MagicMock()

        runner = RepositoryRunner(
            adapter=adapter,
            max_tool_calls=5,
            max_total_time_s=60.0,
            docker_image="python:3.11-slim",
            sandbox_manager=MagicMock(),
        )
        runner._sandbox_manager = mock_sandbox

        task = Task(
            id="EB-SYNTH-001",
            category="debug",
            mode=ExecutionMode.EXEC,
            difficulty=Difficulty.L2,
            capabilities=[Capability.CODE, Capability.DEBUG],
            prompt="Inspect the repository and report the bug.",
            partition=BenchmarkPartition.DEVELOPMENT,
            context={"repository_id": fixture_id},
        )
        ctx = RunContext(
            run_id="run-synth-001",
            model_name="synthetic-agent",
            suite="exec",
            repeat_index=0,
        )

        result = runner.run(task, ctx)

        assert result.task_id == "EB-SYNTH-001"
        assert result.execution_metadata["status"] == TaskStatus.SUCCESS.value
        assert result.repository_id == fixture_id
        assert result.docker_image == "python:3.11-slim"
        assert result.raw_response is not None
        tool_calls = result.execution_metadata.get("tool_calls", [])
        assert len(tool_calls) >= 1
        tool_names = [tc["tool_name"] for tc in tool_calls]
        assert "list_files" in tool_names
        assert "read_file" in tool_names

    def test_exec_runner_rejects_single_mode_task(self, tmp_path: Path):
        """EXEC runner must reject non-EXEC tasks."""
        adapter = _make_mock_adapter_for_exec(["FINAL_ANSWER: x"])
        runner = RepositoryRunner(adapter=adapter)
        task = Task(
            id="EB-SINGLE-999",
            category="architecture",
            mode=ExecutionMode.SINGLE,
            difficulty=Difficulty.L3,
            capabilities=[Capability.ARCH],
            prompt="Design a system",
            partition=BenchmarkPartition.DEVELOPMENT,
        )
        ctx = RunContext(run_id="r1", model_name="m", suite="test", repeat_index=0)

        result = runner.run(task, ctx)

        assert result.execution_metadata["status"] == TaskStatus.SKIPPED.value
        assert any("mode_mismatch" in f for f in result.flags)

    def test_exec_result_contains_deterministic_metadata(self, tmp_path: Path, monkeypatch):
        """Verify EXEC result contains all required metadata fields."""
        fixture_id = _setup_synthetic_fixture(tmp_path)
        monkeypatch.setattr("eb.runners.repository.repositories_dir", lambda *a, **k: tmp_path / "repositories")

        adapter = _make_mock_adapter_for_exec(["FINAL_ANSWER: done"])

        mock_sandbox = MagicMock()
        mock_sandbox.create.return_value = "eb-sbox-mock-002"
        mock_sandbox.exec.return_value = MagicMock(
            success=True, exit_code=0, stdout="", stderr="", duration_s=0.01,
        )
        mock_sandbox.collect.return_value = {}
        mock_sandbox.stop = MagicMock()
        mock_sandbox.destroy = MagicMock()

        runner = RepositoryRunner(adapter=adapter, max_tool_calls=3)
        runner._sandbox_manager = mock_sandbox

        task = Task(
            id="EB-META-001",
            category="debug",
            mode=ExecutionMode.EXEC,
            difficulty=Difficulty.L2,
            capabilities=[Capability.CODE],
            prompt="Fix bug",
            partition=BenchmarkPartition.DEVELOPMENT,
            context={"repository_id": fixture_id},
        )
        ctx = RunContext(run_id="run-meta", model_name="m", suite="exec", repeat_index=0)

        result = runner.run(task, ctx)

        meta = result.execution_metadata
        assert "repository_id" in meta
        assert "repository_hash" in meta
        assert "docker_image" in meta
        assert "sandbox_id" in meta
        assert "tool_calls" in meta
        assert "command_count" in meta
        assert "policy" in meta
        assert "timestamp" in meta
        assert "execution_time" in meta


class TestDockerUnavailableGracefulDegradation:
    """When Docker is unavailable, the runner should fail gracefully."""

    def test_runner_handles_docker_unavailable(self, tmp_path: Path, monkeypatch):
        """If Docker is unavailable, runner returns ERROR status."""
        fixture_id = _setup_synthetic_fixture(tmp_path)
        monkeypatch.setattr("eb.runners.repository.repositories_dir", lambda *a, **k: tmp_path / "repositories")

        # Make sandbox create raise
        mock_sandbox = MagicMock()
        mock_sandbox.create.side_effect = RuntimeError("Docker unavailable")

        adapter = _make_mock_adapter_for_exec(["FINAL_ANSWER: x"])
        runner = RepositoryRunner(adapter=adapter)
        runner._sandbox_manager = mock_sandbox

        task = Task(
            id="EB-NO-DOCKER",
            category="debug",
            mode=ExecutionMode.EXEC,
            difficulty=Difficulty.L2,
            capabilities=[Capability.CODE],
            prompt="Fix bug",
            partition=BenchmarkPartition.DEVELOPMENT,
            context={"repository_id": fixture_id},
        )
        ctx = RunContext(run_id="run-no-docker", model_name="m", suite="exec", repeat_index=0)

        result = runner.run(task, ctx)

        assert result.execution_metadata["status"] == TaskStatus.ERROR.value
        assert any("sandbox_start_failed" in f or "Docker" in f for f in result.flags)


class TestArtifactStructure:
    """Verify EXEC run artifacts have the expected structure."""

    def test_task_result_serializable(self):
        """TaskResult with EXEC fields must be JSON-serializable."""
        result = TaskResult(
            task_id="EB-ART-001",
            run_id="run-art-001",
            raw_response="I fixed it.",
            repository_id="test-repo",
            repository_hash="abc123",
            docker_image="python:3.11-slim",
            sandbox_id="eb-sbox-xyz",
            tool_calls=[
                {"tool_name": "list_files", "arguments": {"path": "."}, "call_id": "call-001"},
            ],
            command_count=3,
            changed_files=["src/parser.py"],
            test_summary={"passed": True, "test_count": 5},
            diff="diff --git a/x.py\n+",
            timeout_status=None,
            execution_metadata={
                "status": "SUCCESS",
                "execution_time": 1.5,
                "policy": SecurityPolicy().to_dict(),
            },
        )

        data = result.model_dump()
        assert data["task_id"] == "EB-ART-001"
        assert data["repository_id"] == "test-repo"
        assert data["tool_calls"][0]["tool_name"] == "list_files"
        assert json.dumps(data)  # Must serialize without error
