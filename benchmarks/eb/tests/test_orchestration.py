"""Tests for eb/runners/orchestration.py — Run orchestration end-to-end."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from eb.runners.orchestration import RunOrchestrator, RunSummary
from eb.runners.single import SingleRunner
from eb.core.schema import Task, InferenceSettings, TaskResult
from eb.core.types import ExecutionMode, Difficulty, Capability, BenchmarkPartition
from eb.adapters.base import ModelAdapter, ModelRequest, ModelResponse, TokenUsage
from eb.core.registry import BenchmarkRegistry


def _make_task(task_id: str = "EB-ARCH-001") -> Task:
    return Task(
        id=task_id,
        category="architecture",
        mode=ExecutionMode.SINGLE,
        difficulty=Difficulty.L3,
        capabilities=[Capability.ARCH],
        prompt=f"Describe {task_id}",
        partition=BenchmarkPartition.DEVELOPMENT,
    )


def _make_mock_adapter(text: str = "generated response") -> ModelAdapter:
    from eb.adapters.base import AdapterMetadata
    adapter = MagicMock(spec=ModelAdapter)
    adapter.model_name = "test-model"
    adapter._closed = False

    def gen(req: ModelRequest) -> ModelResponse:
        return ModelResponse(
            text=text,
            model="test-model",
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=8, completion_tokens=12, total_tokens=20),
            latency_s=0.03,
            backend="mock",
        )

    adapter.generate = gen
    real_meta = AdapterMetadata(
        adapter_type="mock",
        backend="mock",
        model_name="test-model",
        supported_settings=["seed", "temperature", "top_p", "top_k", "max_tokens"],
    )
    adapter.metadata.return_value = real_meta
    return adapter


class TestOrchestratorSmoke:
    def test_single_task_execution(self, tmp_eb_root: Path, tmp_path: Path, monkeypatch):
        """End-to-end smoke test: 1 task → mock adapter → artifacts → registry."""
        # Create a sample task
        task_dir = tmp_eb_root / "tasks" / "architecture"
        task_dir.mkdir(parents=True, exist_ok=True)
        task = _make_task("EB-SMOKE-001")
        with (task_dir / "task.json").open("w") as f:
            json.dump(task.model_dump(), f, indent=2)

        monkeypatch.setattr("eb.paths._EB_ROOT_CACHE", {"eb_root": tmp_eb_root})

        # Mock the adapter factory
        mock_adapter = _make_mock_adapter("smoke test response")
        mock_factory = MagicMock()
        mock_factory.create_adapter.return_value = mock_adapter
        mock_factory.list_models.return_value = ["test-model"]

        orchestrator = RunOrchestrator(
            model_name="test-model",
            suite="smoke",
            partitions=["development"],
            repeats=1,
            adapter_factory=mock_factory,
            output_dir=tmp_path / "outputs",
        )

        summary = orchestrator.run()

        assert isinstance(summary, RunSummary)
        assert summary.tasks_selected == 1
        assert summary.tasks_executed == 1
        assert summary.successes == 1
        assert summary.errors == 0
        assert summary.skipped == 0
        assert summary.elapsed_s >= 0
        assert summary.artifact_dir.exists()

        # Verify artifacts
        artifact_dir = summary.artifact_dir
        assert (artifact_dir / "manifest.json").exists()
        assert (artifact_dir / "results.jsonl").exists()
        assert (artifact_dir / "run.json").exists()

        # Verify results.jsonl has one line
        results_lines = (artifact_dir / "results.jsonl").read_text().strip().split("\n")
        assert len(results_lines) == 1
        result = json.loads(results_lines[0])
        assert result["task_id"] == "EB-SMOKE-001"
        assert result["raw_response"] == "smoke test response"
        assert result["run_id"] == summary.run_id

        # Verify manifest
        manifest = json.loads((artifact_dir / "manifest.json").read_text())
        assert manifest["run_id"] == summary.run_id
        assert manifest["model"]["name"] == "test-model"

        # Verify run.json
        run_info = json.loads((artifact_dir / "run.json").read_text())
        assert run_info["run_id"] == summary.run_id
        assert run_info["model"] == "test-model"
        assert run_info["repeats"] == 1

        # Verify registry update
        registry = BenchmarkRegistry(registry_path=tmp_eb_root / "metadata" / "benchmark_registry.json")
        registry.load()
        stored = registry.get_run(summary.run_id)
        assert stored is not None
        assert stored["run_id"] == summary.run_id
        assert stored["model"]["name"] == "test-model"

        mock_adapter.close()

    def test_multiple_repeats_preserved(self, tmp_eb_root: Path, tmp_path: Path, monkeypatch):
        """Multiple repeats produce distinguishable results."""
        task_dir = tmp_eb_root / "tasks" / "architecture"
        task_dir.mkdir(parents=True, exist_ok=True)
        task = _make_task("EB-REP-001")
        with (task_dir / "task.json").open("w") as f:
            json.dump(task.model_dump(), f, indent=2)

        monkeypatch.setattr("eb.paths._EB_ROOT_CACHE", {"eb_root": tmp_eb_root})

        mock_adapter = _make_mock_adapter()
        # Override generate to produce different responses per call
        call_count = [0]
        orig_gen = mock_adapter.generate
        def counting_gen(request):
            call_count[0] += 1
            return ModelResponse(
                text=f"response-{call_count[0]}",
                model="m",
                finish_reason="stop",
                usage=TokenUsage(),
                latency_s=0.01,
                backend="mock",
            )
        mock_adapter.generate = counting_gen

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

        assert summary.tasks_executed == 3  # 1 task × 3 repeats
        results_lines = (summary.artifact_dir / "results.jsonl").read_text().strip().split("\n")
        assert len(results_lines) == 3

        repeat_ids = [json.loads(l)["execution_metadata"]["repeat_id"] for l in results_lines]
        assert repeat_ids == ["r01", "r02", "r03"]

        mock_adapter.close()

    def test_executes_multi_tasks(self, tmp_eb_root: Path, tmp_path: Path, monkeypatch):
        """MULTI tasks are now executed alongside SINGLE tasks."""
        task_dir = tmp_eb_root / "tasks"
        (task_dir / "architecture").mkdir(parents=True, exist_ok=True)
        (task_dir / "coding").mkdir(parents=True, exist_ok=True)

        single_task = _make_task("EB-SINGLE-001")
        multi_task = _make_task("EB-MULTI-001")
        multi_task.mode = ExecutionMode.MULTI

        with (task_dir / "architecture" / "task.json").open("w") as f:
            json.dump(single_task.model_dump(), f)
        with (task_dir / "coding" / "task.json").open("w") as f:
            json.dump(multi_task.model_dump(), f)

        monkeypatch.setattr("eb.paths._EB_ROOT_CACHE", {"eb_root": tmp_eb_root})

        mock_adapter = _make_mock_adapter("ok")
        mock_factory = MagicMock()
        mock_factory.create_adapter.return_value = mock_adapter
        mock_factory.list_models.return_value = ["m"]

        orchestrator = RunOrchestrator(
            model_name="m",
            suite="mixed",
            partitions=["development"],
            repeats=1,
            adapter_factory=mock_factory,
            output_dir=tmp_path / "outputs",
        )
        summary = orchestrator.run()

        assert summary.tasks_selected == 2
        assert summary.skipped == 0
        assert summary.successes == 2

        mock_adapter.close()

    def test_no_tasks_produces_empty_run(self, tmp_eb_root: Path, tmp_path: Path, monkeypatch):
        """Empty task set produces a valid but empty run."""
        monkeypatch.setattr("eb.paths._EB_ROOT_CACHE", {"eb_root": tmp_eb_root})

        mock_adapter = _make_mock_adapter()
        mock_factory = MagicMock()
        mock_factory.create_adapter.return_value = mock_adapter
        mock_factory.list_models.return_value = ["m"]

        orchestrator = RunOrchestrator(
            model_name="m",
            suite="empty",
            partitions=["development"],
            repeats=1,
            adapter_factory=mock_factory,
            output_dir=tmp_path / "outputs",
        )
        summary = orchestrator.run()

        assert summary.tasks_selected == 0
        assert summary.tasks_executed == 0
        assert summary.artifact_dir.exists()

        mock_adapter.close()

    def test_run_prints_config(self, tmp_eb_root: Path, tmp_path: Path, monkeypatch, capsys):
        """CLI output should include model, suite, repeats info."""
        monkeypatch.setattr("eb.paths._EB_ROOT_CACHE", {"eb_root": tmp_eb_root})

        mock_adapter = _make_mock_adapter()
        mock_factory = MagicMock()
        mock_factory.create_adapter.return_value = mock_adapter
        mock_factory.list_models.return_value = ["m"]

        orchestrator = RunOrchestrator(
            model_name="atan-v1",
            suite="single",
            partitions=["development"],
            repeats=3,
            seed=99,
            temperature=0.7,
            adapter_factory=mock_factory,
            output_dir=tmp_path / "outputs",
        )
        summary = orchestrator.run()

        captured = capsys.readouterr()
        assert "atan-v1" in captured.out
        assert "single" in captured.out
        assert "3" in captured.out

        mock_adapter.close()
