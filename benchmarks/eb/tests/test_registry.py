"""Tests for core/registry.py — BenchmarkRegistry persistence."""
import json
import time
from pathlib import Path

import pytest

from eb.core.registry import BenchmarkRegistry
from eb.core.schema import BaselineRecord, BenchmarkRun, InferenceSettings, ModelMetadata
from eb.core.types import BenchmarkPartition


@pytest.fixture
def registry(tmp_eb_root: Path) -> BenchmarkRegistry:
    return BenchmarkRegistry(registry_path=tmp_eb_root / "metadata" / "benchmark_registry.json")


@pytest.fixture
def sample_run(tmp_path: Path) -> BenchmarkRun:
    return BenchmarkRun(
        run_id="run-test-001",
        benchmark_version="eb-v0.1",
        task_set_version="tasks-v0.1",
        model=ModelMetadata(name="atan-v1", revision="sha abc123"),
        base_model=ModelMetadata(name="Qwen2.5-7B", revision="sha def456"),
        suite="full",
        partitions=[BenchmarkPartition.DEVELOPMENT],
        inference=InferenceSettings(seed=42, temperature=0.0),
        environment={"hardware": "RTX5070"},
        git_commit="abc123def456",
    )


class TestRegistryPersistence:
    def test_create_and_get_run(self, registry: BenchmarkRegistry, sample_run: BenchmarkRun):
        registry.create_run(sample_run)
        retrieved = registry.get_run("run-test-001")
        assert retrieved is not None
        assert retrieved["run_id"] == "run-test-001"
        assert retrieved["model"]["name"] == "atan-v1"

    def test_get_missing_run(self, registry: BenchmarkRegistry):
        result = registry.get_run("nonexistent")
        assert result is None

    def test_list_runs_empty(self, registry: BenchmarkRegistry):
        runs = registry.list_runs()
        assert runs == []
        assert len(runs) == 0

    def test_list_runs_after_add(self, registry: BenchmarkRegistry, sample_run: BenchmarkRun):
        registry.create_run(sample_run)
        runs = registry.list_runs()
        assert len(runs) == 1
        assert runs[0]["run_id"] == "run-test-001"

    def test_list_runs_paginated(self, registry: BenchmarkRegistry, sample_run: BenchmarkRun):
        registry.create_run(sample_run)
        runs = registry.list_runs(limit=1, offset=0)
        assert len(runs) == 1
        runs = registry.list_runs(limit=1, offset=1)
        assert len(runs) == 0

    def test_summary(self, registry: BenchmarkRegistry):
        s = registry.summary()
        assert s["schema_version"] == "1.0"
        assert s["total_runs"] == 0
        assert s["total_baselines"] == 0


class TestBaseline:
    def test_set_and_get_baseline(self, registry: BenchmarkRegistry):
        br = BaselineRecord(
            base_model_name="Qwen2.5-7B",
            base_model_revision="sha def456",
            benchmark_version="eb-v0.1",
            task_set_version="tasks-v0.1",
            baseline_run_id="baseline-001",
            run_scores=[1000, 998, 1002],
        )
        br.compute_stats()
        registry.set_baseline(br)

        retrieved = registry.get_baseline("Qwen2.5-7B", "eb-v0.1")
        assert retrieved is not None
        assert retrieved.eb_score == 1000
        assert retrieved.mean == pytest.approx(1000.0)

    def test_get_missing_baseline(self, registry: BenchmarkRegistry):
        result = registry.get_baseline("unknown", "eb-v0.1")
        assert result is None

    def test_list_baselines(self, registry: BenchmarkRegistry):
        assert registry.list_baselines() == []

    def test_overwrite_baseline(self, registry: BenchmarkRegistry):
        br1 = BaselineRecord(
            base_model_name="M", base_model_revision="r1",
            benchmark_version="v1", task_set_version="t1",
            baseline_run_id="b1", run_scores=[1000],
        )
        br2 = BaselineRecord(
            base_model_name="M", base_model_revision="r2",
            benchmark_version="v1", task_set_version="t1",
            baseline_run_id="b2", run_scores=[1005],
        )
        registry.set_baseline(br1)
        registry.set_baseline(br2)
        retrieved = registry.get_baseline("M", "v1")
        assert retrieved is not None
        assert retrieved.baseline_run_id == "b2"


class TestAtomicWrite:
    def test_corruption_resistant(self, registry: BenchmarkRegistry, sample_run: BenchmarkRun):
        """Write a run, verify the file is valid JSON after close."""
        registry.create_run(sample_run)
        path = registry.path
        assert path.exists()
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        assert data["schema_version"] == "1.0"
        assert data["run_count"] == 1

    def test_reload_persists(self, tmp_eb_root: Path, sample_run: BenchmarkRun):
        """Create registry, write, reload from fresh instance."""
        path = tmp_eb_root / "metadata" / "benchmark_registry.json"
        reg1 = BenchmarkRegistry(registry_path=path)
        reg1.create_run(sample_run)
        reg1.save()

        reg2 = BenchmarkRegistry(registry_path=path)
        reg2.load()
        retrieved = reg2.get_run("run-test-001")
        assert retrieved is not None
        assert retrieved["run_id"] == "run-test-001"
