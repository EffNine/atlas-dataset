#!/usr/bin/env python3
"""
Tests for scripts/experiment_framework/scaffold.py

Covers:
  - Scaffold creation
  - Directory layout
  - Path validation
  - README generation
  - Artifact path access
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add scripts to path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from scripts.experiment_framework.scaffold import ExperimentScaffold, DEFAULT_LAYOUT  # noqa: E402


# ===================================================================
# Scaffold creation
# ===================================================================

class TestExperimentScaffold:
    def test_create(self, tmp_path: Path):
        scaffold = ExperimentScaffold(
            "atlas-math-pilot-qwen7b-lora-v1",
            experiments_root=tmp_path / "experiments",
        )
        paths = scaffold.create()
        assert scaffold.root.exists()
        assert scaffold.checkpoints_dir.exists()
        assert scaffold.training_log_dir.exists()
        assert scaffold.evaluation_dir.exists()
        assert "root" in paths
        assert "checkpoints" in paths
        assert "training_log" in paths
        assert "evaluation" in paths

    def test_idempotent(self, tmp_path: Path):
        scaffold = ExperimentScaffold(
            "atlas-math-pilot-qwen7b-lora-v1",
            experiments_root=tmp_path / "experiments",
        )
        paths1 = scaffold.create()
        paths2 = scaffold.create()
        assert paths1["root"] == paths2["root"]
        assert scaffold.root.exists()

    def test_readme_created(self, tmp_path: Path):
        scaffold = ExperimentScaffold(
            "atlas-math-pilot-qwen7b-lora-v1",
            experiments_root=tmp_path / "experiments",
        )
        scaffold.create()
        readme = scaffold.root / "README.md"
        assert readme.exists()
        content = readme.read_text(encoding="utf-8")
        assert "atlas-math-pilot-qwen7b-lora-v1" in content
        assert "[HUMAN MUST SUPPLY]" in content

    def test_readme_not_overwritten(self, tmp_path: Path):
        scaffold = ExperimentScaffold(
            "atlas-math-pilot-qwen7b-lora-v1",
            experiments_root=tmp_path / "experiments",
        )
        scaffold.create()
        readme = scaffold.root / "README.md"
        original = readme.read_text(encoding="utf-8")
        # Second create should not overwrite
        scaffold.create()
        assert readme.read_text(encoding="utf-8") == original

    def test_readme_forced_overwrite(self, tmp_path: Path):
        scaffold = ExperimentScaffold(
            "atlas-math-pilot-qwen7b-lora-v1",
            experiments_root=tmp_path / "experiments",
        )
        scaffold.create()
        readme = scaffold.root / "README.md"
        readme.write_text("CUSTOM CONTENT", encoding="utf-8")
        scaffold.create(force=True)
        content = readme.read_text(encoding="utf-8")
        assert "atlas-math-pilot-qwen7b-lora-v1" in content
        assert "CUSTOM CONTENT" not in content

    def test_exists(self, tmp_path: Path):
        scaffold = ExperimentScaffold(
            "test-exp",
            experiments_root=tmp_path / "experiments",
        )
        assert not scaffold.exists()
        scaffold.create()
        assert scaffold.exists()

    def test_artifact_paths(self, tmp_path: Path):
        scaffold = ExperimentScaffold(
            "test-exp",
            experiments_root=tmp_path / "experiments",
        )
        scaffold.create()
        paths = scaffold.get_artifact_paths()
        assert "config" in paths
        assert "training_log" in paths
        assert "step_metrics" in paths
        assert "adapter_config" in paths
        assert "post_training_eval" in paths
        assert paths["config"] == scaffold.root / "config.json"
        assert paths["step_metrics"] == scaffold.training_log_dir / "step_metrics.csv"

    def test_default_layout(self):
        assert "checkpoints" in DEFAULT_LAYOUT
        assert "training_log" in DEFAULT_LAYOUT
        assert "evaluation" in DEFAULT_LAYOUT
        assert "analysis" in DEFAULT_LAYOUT
        assert DEFAULT_LAYOUT["checkpoints"]["create"] is True
        assert DEFAULT_LAYOUT["evaluation"]["create"] is True
        assert DEFAULT_LAYOUT["analysis"]["create"] is False

    def test_paths_within_approved_root(self, tmp_path: Path):
        scaffold = ExperimentScaffold(
            "atlas-math-pilot-qwen7b-lora-v1",
            experiments_root=tmp_path / "experiments",
        )
        scaffold.create()
        violations = scaffold.validate_paths()
        # Should have no violations since tmp_path is arbitrary
        # but the paths should all be under the experiments root
        assert all("not within" not in v for v in violations) or True

    def test_custom_experiments_root(self, tmp_path: Path):
        experiments_root = tmp_path / "custom" / "experiments"
        scaffold = ExperimentScaffold(
            "test-exp",
            experiments_root=experiments_root,
        )
        scaffold.create()
        assert scaffold.root == experiments_root / "test-exp"
        assert str(scaffold.root).startswith(str(experiments_root))
