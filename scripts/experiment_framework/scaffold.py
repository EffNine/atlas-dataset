#!/usr/bin/env python3
"""
scaffold.py — Experiment directory scaffold generator.

Creates the standardized directory layout for new Atlas QLoRA experiments.
The layout follows the protocol requirements and ensures all artifacts
are written under experiments/{experiment_id}/.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Standard directory layout
# ---------------------------------------------------------------------------

DEFAULT_LAYOUT: dict[str, dict[str, Any]] = {
    "checkpoints": {
        "description": "QLoRA adapter checkpoints (adapter_config.json, adapter_model.safetensors)",
        "create": True,
    },
    "training_log": {
        "description": "Training logs (step_metrics.csv, console.log)",
        "create": True,
    },
    "evaluation": {
        "description": "Evaluation artifacts (post_training.json, per_example results, adapter_metadata.json)",
        "create": True,
    },
    "analysis": {
        "description": "Transfer analysis and per-example deltas (optional, created on demand)",
        "create": False,
    },
}


class ExperimentScaffold:
    """
    Creates and manages the directory scaffold for an experiment.

    The scaffold provides:
      - Standardized directory layout
      - Required artifact paths
      - Validation that paths are within approved write roots
      - Idempotent creation (safe to call multiple times)
    """

    def __init__(
        self,
        experiment_id: str,
        experiments_root: Path | None = None,
        layout: dict[str, dict[str, Any]] | None = None,
    ):
        self.experiment_id = experiment_id
        self._experiments_root = experiments_root
        self._layout = layout or DEFAULT_LAYOUT
        self._paths: dict[str, Path] = {}

    @property
    def root(self) -> Path:
        """Root directory for this experiment."""
        if self._experiments_root is None:
            from ..atlas_paths import get_root
            root = get_root()
            return root / "experiments" / self.experiment_id
        return self._experiments_root / self.experiment_id

    @property
    def checkpoints_dir(self) -> Path:
        return self.root / "checkpoints"

    @property
    def training_log_dir(self) -> Path:
        return self.root / "training_log"

    @property
    def evaluation_dir(self) -> Path:
        return self.root / "evaluation"

    @property
    def analysis_dir(self) -> Path:
        return self.root / "analysis"

    def get_path(self, name: str) -> Path | None:
        """Get a named path from the scaffold."""
        return self._paths.get(name)

    def create(self, force: bool = False) -> dict[str, Path]:
        """
        Create the experiment directory scaffold.

        Args:
            force: If True, recreate existing directories.

        Returns:
            Dictionary of path names to Path objects.
        """
        self.root.mkdir(parents=True, exist_ok=True)

        paths = {
            "root": self.root,
            "checkpoints": self.checkpoints_dir,
            "training_log": self.training_log_dir,
            "evaluation": self.evaluation_dir,
        }

        for name, path in paths.items():
            path.mkdir(parents=True, exist_ok=True)
            self._paths[name] = path

        # Optionally create analysis dir
        if self._layout.get("analysis", {}).get("create", False):
            self.analysis_dir.mkdir(parents=True, exist_ok=True)
            self._paths["analysis"] = self.analysis_dir

        # Create README if it doesn't exist
        readme_path = self.root / "README.md"
        if not readme_path.exists() or force:
            self._write_scaffold_readme(readme_path)

        return paths

    def _write_scaffold_readme(self, path: Path) -> None:
        """Write a default README for the experiment scaffold."""
        content = f"""# Experiment: `{self.experiment_id}`

> **Phase:** [HUMAN MUST SUPPLY]
> **Status:** CREATED
> **Date:** [HUMAN MUST SUPPLY]
> **Research Question:** [HUMAN MUST SUPPLY]

---

## Purpose

[HUMAN MUST SUPPLY — describe what this experiment investigates]

---

## Configuration

See `config.json` for the full training configuration.

| Parameter | Value |
|-----------|-------|
| Base model | [HUMAN MUST SUPPLY] |
| Quantization | NF4 4-bit + double quant |
| LoRA | r=8, alpha=16, dropout=0.05 |
| Seed | 42 |
| Max steps | [HUMAN MUST SUPPLY] |

---

## Expected Artifacts

| Artifact | Path |
|----------|------|
| Config | `config.json` |
| Training log | `training_log.json` |
| Step metrics | `training_log/step_metrics.csv` |
| Adapter | `checkpoints/` |
| Evaluation | `evaluation/post_training.json` |
| Per-example results | `evaluation/post_training_per_example.jsonl` |
| Transfer analysis | `analysis/p8a_transfer_analysis.json` (if applicable) |

---

## Reproducibility Checklist

Before claiming results, verify:

- [ ] Git commit recorded and `git status` clean
- [ ] Training view file SHA-256 recorded
- [ ] Manifest records checksum matches on-disk records
- [ ] Eval split SHA-256 recorded
- [ ] Model revision recorded
- [ ] Full training config recorded
- [ ] Random seed recorded and applied
- [ ] Evaluation engine version + commit recorded
- [ ] Inference config recorded
- [ ] Hardware + software versions recorded
- [ ] Baseline recorded for the same eval split
- [ ] Determinism spot-check passed
- [ ] Outputs written under `experiments/{self.experiment_id}/` only
- [ ] No dataset/view/release artifact modified

---

## Notes

[HUMAN MUST SUPPLY]
"""
        path.write_text(content, encoding="utf-8")

    def validate_paths(self) -> list[str]:
        """
        Validate that all scaffold paths are within approved write roots.

        Returns a list of violations (empty if all paths are valid).
        """
        from ..atlas_paths import is_write_safe, get_root
        violations = []
        root = get_root()
        for name, path in self._paths.items():
            if not is_write_safe(path, root):
                violations.append(f"Path {name!r} ({path}) is not within an approved write root")
        return violations

    def exists(self) -> bool:
        """Check if the experiment root directory exists."""
        return self.root.exists()

    def get_artifact_paths(self) -> dict[str, Path]:
        """Return all expected artifact paths for this experiment."""
        return {
            "config": self.root / "config.json",
            "training_log": self.root / "training_log.json",
            "step_metrics": self.training_log_dir / "step_metrics.csv",
            "console_log": self.training_log_dir / "console.log",
            "adapter_config": self.checkpoints_dir / "adapter_config.json",
            "adapter_model": self.checkpoints_dir / "adapter_model.safetensors",
            "post_training_eval": self.evaluation_dir / "post_training.json",
            "per_example_eval": self.evaluation_dir / "post_training_per_example.jsonl",
            "adapter_metadata": self.evaluation_dir / "adapter_metadata.json",
            "comparison_metrics": self.evaluation_dir / "comparison_metrics.json",
        }
