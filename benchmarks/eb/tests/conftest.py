"""Shared fixtures for EB tests."""
import json
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_eb_root(tmp_path: Path) -> Path:
    """Create a temporary EB root directory structure."""
    dirs = [
        "core", "adapters", "evaluators", "runners", "sandbox",
        "scoring", "judges", "reports", "factory", "tasks",
        "config", "outputs", "metadata", "tests", "docs",
        "repositories", "tasks/architecture", "tasks/debugging",
        "tasks/coding", "tasks/understanding", "tasks/planning",
        "tasks/testing", "tasks/advisory", "tasks/judgment",
        "tasks/evidence", "tasks/myeng", "tasks/agentic",
        "tasks/long_horizon",
    ]
    for d in dirs:
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    # Copy the actual eb package
    src_eb = Path(__file__).resolve().parent.parent / "eb"
    dst_eb = tmp_path / "eb"
    if dst_eb.exists():
        import shutil
        shutil.rmtree(dst_eb)
    if src_eb.exists():
        import shutil
        shutil.copytree(src_eb, dst_eb)
    # Copy core package
    src_core = Path(__file__).resolve().parent.parent / "core"
    dst_core = tmp_path / "core"
    if dst_core.exists():
        import shutil
        shutil.rmtree(dst_core)
    if src_core.exists():
        import shutil
        shutil.copytree(src_core, dst_core)
    # Copy tasks package
    src_tasks = Path(__file__).resolve().parent.parent / "tasks"
    dst_tasks = tmp_path / "tasks"
    if dst_tasks.exists():
        import shutil
        shutil.rmtree(dst_tasks)
    if src_tasks.exists():
        import shutil
        shutil.copytree(src_tasks, dst_tasks)
    # Copy config
    src_config = Path(__file__).resolve().parent.parent / "config"
    dst_config = tmp_path / "config"
    if dst_config.exists():
        import shutil
        shutil.rmtree(dst_config)
    if src_config.exists():
        import shutil
        shutil.copytree(src_config, dst_config)
    # Copy pyproject.toml
    src_pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if src_pyproject.exists():
        import shutil
        shutil.copy2(src_pyproject, tmp_path / "pyproject.toml")
    return tmp_path


@pytest.fixture
def sample_task_data() -> dict:
    """Return valid sample task data for testing."""
    return {
        "id": "EB-ARCH-001",
        "version": "1.0",
        "category": "architecture",
        "mode": "SINGLE",
        "difficulty": "L4",
        "capabilities": ["ARCH", "PLAN"],
        "tags": ["system-design", "tradeoff"],
        "prompt": "Design a distributed caching system.",
        "context": {"domain": "backend"},
        "evaluation": {"primary_mode": "RUBRIC"},
        "partition": "development",
        "metadata": {"source": "original"},
    }


@pytest.fixture
def sample_task_dir(tmp_path: Path, sample_task_data: dict) -> Path:
    """Create a temporary task directory with a valid task.json."""
    task_dir = tmp_path / "tasks" / "architecture"
    task_dir.mkdir(parents=True, exist_ok=True)
    task_file = task_dir / "task.json"
    with task_file.open("w", encoding="utf-8") as f:
        json.dump(sample_task_data, f, indent=2)
    return task_dir
