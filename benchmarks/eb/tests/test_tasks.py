"""Tests for tasks/loader.py and tasks/registry.py."""
import json
from pathlib import Path

import pytest

from eb.tasks.loader import load_task, load_tasks_from_dir, iter_task_dirs
from eb.tasks.registry import TaskRegistry
from eb.core.types import ExecutionMode, Capability, Difficulty, BenchmarkPartition


class TestTaskLoader:
    def test_load_single_task(self, sample_task_dir: Path):
        task = load_task(sample_task_dir / "task.json")
        assert task.id == "EB-ARCH-001"
        assert task.mode == ExecutionMode.SINGLE
        assert task.difficulty == Difficulty.L4

    def test_load_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_task("/nonexistent/path/task.json")

    def test_load_tasks_from_dir(self, sample_task_dir: Path):
        tasks = load_tasks_from_dir(sample_task_dir)
        assert len(tasks) == 1
        assert tasks[0].id == "EB-ARCH-001"

    def test_load_tasks_from_empty_dir(self, tmp_path: Path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        tasks = load_tasks_from_dir(empty_dir)
        assert tasks == []

    def test_iter_task_dirs(self, tmp_path: Path):
        dirs = tmp_path / "tasks"
        (dirs / "architecture").mkdir(parents=True, exist_ok=True)
        (dirs / "coding").mkdir(parents=True, exist_ok=True)
        (dirs / "_hidden").mkdir(parents=True, exist_ok=True)
        pairs = list(iter_task_dirs(dirs))
        names = [name for _, name in pairs]
        assert "architecture" in names
        assert "coding" in names
        assert "_hidden" not in names


class TestTaskRegistry:
    def test_load_and_filter_by_mode(self, sample_task_dir: Path):
        reg = TaskRegistry()
        n = reg.load_from_dir(sample_task_dir.parent)
        assert n >= 1
        single_tasks = list(reg.iter_by_mode(ExecutionMode.SINGLE))
        assert len(single_tasks) > 0
        assert all(t.mode == ExecutionMode.SINGLE for t in single_tasks)

    def test_filter_by_capability(self, sample_task_dir: Path):
        reg = TaskRegistry()
        reg.load_from_dir(sample_task_dir.parent)
        arch_tasks = list(reg.iter_by_capability(Capability.ARCH))
        assert len(arch_tasks) > 0
        assert all(Capability.ARCH in t.capabilities for t in arch_tasks)

    def test_filter_by_partition(self, sample_task_dir: Path):
        reg = TaskRegistry()
        reg.load_from_dir(sample_task_dir.parent)
        dev_tasks = list(reg.iter_by_partition(BenchmarkPartition.DEVELOPMENT))
        assert len(dev_tasks) > 0

    def test_iter_filtered_multi_criteria(self, sample_task_dir: Path):
        reg = TaskRegistry()
        reg.load_from_dir(sample_task_dir.parent)
        results = reg.iter_filtered(
            mode=ExecutionMode.SINGLE,
            capabilities=[Capability.ARCH],
            partitions=[BenchmarkPartition.DEVELOPMENT],
        )
        assert len(results) > 0
        for t in results:
            assert t.mode == ExecutionMode.SINGLE
            assert Capability.ARCH in t.capabilities
            assert t.partition == BenchmarkPartition.DEVELOPMENT

    def test_len_and_iter(self, sample_task_dir: Path):
        reg = TaskRegistry()
        reg.load_from_dir(sample_task_dir.parent)
        assert len(reg) >= 1
        ids = [t.id for t in reg]
        assert "EB-ARCH-001" in ids

    def test_get_by_id(self, sample_task_dir: Path):
        reg = TaskRegistry()
        reg.load_from_dir(sample_task_dir.parent)
        task = reg.get("EB-ARCH-001")
        assert task is not None
        assert task.id == "EB-ARCH-001"

    def test_get_missing(self, sample_task_dir: Path):
        reg = TaskRegistry()
        reg.load_from_dir(sample_task_dir.parent)
        assert reg.get("NONEXISTENT") is None
