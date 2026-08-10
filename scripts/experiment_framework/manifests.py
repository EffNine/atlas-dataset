#!/usr/bin/env python3
"""
manifests.py — Dataset, training, and evaluation manifests.

Provides the three manifest types required by the Atlas Research Protocol v1.0:
  - DatasetManifest: provenance for training/eval datasets
  - TrainingManifest: full training configuration provenance
  - EvaluationManifest: evaluation setup provenance
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .metadata import compute_sha256, compute_records_sha256, git_info, hardware_info
from .config import ExperimentConfig


@dataclass
class DatasetManifest:
    """
    Provenance manifest for a dataset file (train or eval split).

    Records the raw file SHA-256 and the canonical records SHA-256,
    enabling verification that the on-disk file matches the approved
    version.
    """
    dataset_id: str
    file_path: str
    split_type: str  # "train" or "eval"
    n_records: int
    raw_sha256: str
    records_sha256: str
    approved_sha256: str | None = None
    checksum_match: bool | None = None
    leakage_audit_clean: bool = True
    generated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DatasetManifest":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def create(
        cls,
        dataset_id: str,
        file_path: Path | str,
        split_type: str,
        approved_sha256: str | None = None,
    ) -> "DatasetManifest":
        """
        Create a dataset manifest by computing checksums from a JSONL file.

        Args:
            dataset_id: Unique identifier for this dataset.
            file_path: Path to the JSONL file.
            split_type: "train" or "eval".
            approved_sha256: Expected SHA-256 for verification.

        Returns:
            DatasetManifest with computed checksums.
        """
        p = Path(file_path)
        raw_hash = compute_sha256(p)
        records_hash = compute_records_sha256(p)

        n_records = 0
        with p.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    n_records += 1

        checksum_match = None
        if approved_sha256 is not None:
            checksum_match = (raw_hash == approved_sha256)

        return cls(
            dataset_id=dataset_id,
            file_path=str(p),
            split_type=split_type,
            n_records=n_records,
            raw_sha256=raw_hash,
            records_sha256=records_hash,
            approved_sha256=approved_sha256,
            checksum_match=checksum_match,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def validate(self) -> list[str]:
        """Validate the manifest. Returns list of errors."""
        errors = []
        if self.split_type not in ("train", "eval"):
            errors.append(f"split_type must be 'train' or 'eval', got {self.split_type!r}")
        if self.n_records <= 0:
            errors.append(f"n_records must be positive, got {self.n_records}")
        if len(self.raw_sha256) != 64:
            errors.append("raw_sha256 must be a 64-character hex string")
        if len(self.records_sha256) != 64:
            errors.append("records_sha256 must be a 64-character hex string")
        if self.approved_sha256 is not None and self.checksum_match is False:
            errors.append("checksum mismatch — dataset has been modified")
        return errors


@dataclass
class TrainingManifest:
    """
    Full training provenance manifest.

    Combines the experiment config, dataset manifest, and git/hardware
    information into a single provenance record.
    """
    experiment_id: str
    phase: str
    config: dict[str, Any]
    dataset_manifest: DatasetManifest | None = None
    git_info: dict[str, Any] | None = None
    hardware_info: dict[str, Any] | None = None
    training_view_id: str | None = None
    base_model: str | None = None
    model_revision: str | None = None
    training_metrics: dict[str, Any] | None = None
    generated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "experiment_id": self.experiment_id,
            "phase": self.phase,
            "config": self.config,
            "dataset_manifest": self.dataset_manifest.to_dict() if self.dataset_manifest else None,
            "git_info": self.git_info,
            "hardware_info": self.hardware_info,
            "training_view_id": self.training_view_id,
            "base_model": self.base_model,
            "model_revision": self.model_revision,
            "training_metrics": self.training_metrics,
            "generated_at": self.generated_at,
        }
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrainingManifest":
        dataset = None
        if data.get("dataset_manifest"):
            dataset = DatasetManifest.from_dict(data["dataset_manifest"])
        return cls(
            experiment_id=data["experiment_id"],
            phase=data["phase"],
            config=data["config"],
            dataset_manifest=dataset,
            git_info=data.get("git_info"),
            hardware_info=data.get("hardware_info"),
            training_view_id=data.get("training_view_id"),
            base_model=data.get("base_model"),
            model_revision=data.get("model_revision"),
            training_metrics=data.get("training_metrics"),
            generated_at=data.get("generated_at"),
        )

    @classmethod
    def create(
        cls,
        config: ExperimentConfig,
        train_dataset_manifest: DatasetManifest,
    ) -> "TrainingManifest":
        """Create a training manifest from an experiment config and dataset manifest."""
        git = git_info()
        hw = hardware_info()
        return cls(
            experiment_id=config.experiment_id,
            phase=config.phase,
            config=config.to_dict(),
            dataset_manifest=train_dataset_manifest,
            git_info=git,
            hardware_info=hw,
            training_view_id=config.training_view_id,
            base_model=config.base_model,
            model_revision=config.model_revision,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def validate(self) -> list[str]:
        """Validate the manifest. Returns list of errors."""
        errors = []
        if not self.experiment_id:
            errors.append("experiment_id is required")
        if not self.phase:
            errors.append("phase is required")
        if not self.config:
            errors.append("config is required")
        if self.dataset_manifest is None:
            errors.append("dataset_manifest is required")
        elif self.dataset_manifest.validate():
            errors.extend(self.dataset_manifest.validate())
        return errors


@dataclass
class EvaluationManifest:
    """
    Evaluation provenance manifest.

    Records the evaluation setup: eval split, engine version, baseline
    comparison, and inference configuration.
    """
    experiment_id: str
    eval_split_id: str
    eval_jsonl_path: str
    eval_sha256: str
    eval_records_sha256: str
    n_eval_records: int
    engine: str
    engine_commit: str | None = None
    engine_patches: list[str] | None = None
    baseline_experiment_id: str | None = None
    baseline_path: str | None = None
    inference_config: dict[str, Any] | None = None
    evaluation_scope: str | None = None
    generated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationManifest":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def create(
        cls,
        experiment_id: str,
        eval_jsonl_path: Path | str,
        eval_split_id: str,
        engine: str = "QEE v2",
        engine_commit: str | None = None,
        engine_patches: list[str] | None = None,
        baseline_experiment_id: str | None = None,
        baseline_path: str | None = None,
        inference_config: dict[str, Any] | None = None,
        evaluation_scope: str | None = None,
    ) -> "EvaluationManifest":
        """
        Create an evaluation manifest from an eval split file.

        Args:
            experiment_id: Experiment identifier.
            eval_jsonl_path: Path to the eval JSONL file.
            eval_split_id: Human-readable ID for the eval split.
            engine: Evaluation engine identifier.
            engine_commit: Git commit of the evaluation engine.
            engine_patches: List of applied patches to the engine.
            baseline_experiment_id: ID of the baseline experiment to compare against.
            baseline_path: Path to the baseline results file.
            inference_config: Inference configuration used.
            evaluation_scope: Description of what is being evaluated.
        """
        p = Path(eval_jsonl_path)
        n_records = 0
        with p.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    n_records += 1

        return cls(
            experiment_id=experiment_id,
            eval_split_id=eval_split_id,
            eval_jsonl_path=str(p),
            eval_sha256=compute_sha256(p),
            eval_records_sha256=compute_records_sha256(p),
            n_eval_records=n_records,
            engine=engine,
            engine_commit=engine_commit,
            engine_patches=engine_patches,
            baseline_experiment_id=baseline_experiment_id,
            baseline_path=baseline_path,
            inference_config=inference_config,
            evaluation_scope=evaluation_scope,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def validate(self) -> list[str]:
        """Validate the manifest. Returns list of errors."""
        errors = []
        if not self.experiment_id:
            errors.append("experiment_id is required")
        if not self.eval_split_id:
            errors.append("eval_split_id is required")
        if len(self.eval_sha256) != 64:
            errors.append("eval_sha256 must be a 64-character hex string")
        if len(self.eval_records_sha256) != 64:
            errors.append("eval_records_sha256 must be a 64-character hex string")
        if self.n_eval_records <= 0:
            errors.append(f"n_eval_records must be positive, got {self.n_eval_records}")
        return errors
