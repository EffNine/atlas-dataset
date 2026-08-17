"""Tests for core/manifest.py — BenchmarkRunManifest and task-set hashing."""
import json
from pathlib import Path

import pytest

from eb.core.manifest import (
    BenchmarkRunManifest,
    TaskSetManifest,
    compute_sha256,
    compute_records_sha256,
)
from eb.core.schema import InferenceSettings, ModelMetadata


class TestSHA256Helpers:
    def test_compute_sha256(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        h = compute_sha256(f)
        assert len(h) == 64
        assert h == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"

    def test_compute_records_sha256(self, tmp_path: Path):
        f = tmp_path / "tasks.jsonl"
        records = [
            {"id": "b", "value": 2},
            {"id": "a", "value": 1},
        ]
        with f.open("w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")
        h = compute_records_sha256(f)
        assert len(h) == 64
        # Should be deterministic
        h2 = compute_records_sha256(f)
        assert h == h2


class TestTaskSetManifest:
    def test_empty_dir(self, tmp_path: Path):
        task_dir = tmp_path / "tasks"
        task_dir.mkdir()
        manifest = TaskSetManifest(task_set_version="v1", task_dir=str(task_dir))
        manifest.compute_from_dir(task_dir)
        assert manifest.n_tasks == 0
        assert manifest.raw_sha256 is None

    def test_single_task(self, tmp_path: Path):
        task_dir = tmp_path / "tasks" / "architecture"
        task_dir.mkdir(parents=True)
        task_file = task_dir / "task.json"
        task_file.write_text(json.dumps({"id": "EB-ARCH-001", "partition": "development"}), encoding="utf-8")

        manifest = TaskSetManifest(task_set_version="v1", task_dir=str(task_dir))
        manifest.compute_from_dir(task_dir)
        assert manifest.n_tasks == 1
        assert manifest.raw_sha256 is not None
        assert len(manifest.raw_sha256) == 64
        assert manifest.records_sha256 is not None
        assert "development" in manifest.partitions

    def test_checksums_stable(self, tmp_path: Path):
        task_dir = tmp_path / "tasks" / "coding"
        task_dir.mkdir(parents=True)
        task_file = task_dir / "task.json"
        task_file.write_text(json.dumps({"id": "EB-CODE-001", "partition": "development"}), encoding="utf-8")

        m1 = TaskSetManifest(task_set_version="v1", task_dir=str(task_dir))
        m1.compute_from_dir(task_dir)
        m2 = TaskSetManifest(task_set_version="v1", task_dir=str(task_dir))
        m2.compute_from_dir(task_dir)
        assert m1.raw_sha256 == m2.raw_sha256
        assert m1.records_sha256 == m2.records_sha256


class TestBenchmarkRunManifest:
    def test_create_manifest(self, tmp_path: Path):
        task_dir = tmp_path / "tasks"
        task_dir.mkdir()
        (task_dir / "task.json").write_text(
            json.dumps({"id": "EB-ARCH-001", "partition": "development"}),
            encoding="utf-8",
        )

        manifest = BenchmarkRunManifest.create(
            run_id="run-001",
            benchmark_version="eb-v0.1",
            task_set_version="tasks-v0.1",
            task_dir=task_dir,
            model=ModelMetadata(name="atan-v1", revision="sha1"),
            base_model=ModelMetadata(name="Qwen2.5-7B", revision="sha2"),
            suite="full",
            partitions=["development"],
            inference=InferenceSettings(seed=42, temperature=0.0),
            git_commit="abc123",
        )
        assert manifest.run_id == "run-001"
        assert manifest.benchmark_version == "eb-v0.1"
        assert manifest.task_set_manifest.n_tasks == 1
        assert manifest.manifest_sha256 is not None
        assert len(manifest.manifest_sha256) == 64
        assert manifest.git_commit == "abc123"

    def test_to_dict(self, tmp_path: Path):
        task_dir = tmp_path / "tasks"
        task_dir.mkdir()
        manifest = BenchmarkRunManifest.create(
            run_id="r1",
            benchmark_version="eb-v0.1",
            task_set_version="t1",
            task_dir=task_dir,
            model=ModelMetadata(name="m", revision="r"),
            base_model=ModelMetadata(name="base", revision="r"),
            suite="full",
            partitions=[],
            inference=InferenceSettings(),
        )
        d = manifest.to_dict()
        assert d["run_id"] == "r1"
        assert "task_set_manifest" in d
