#!/usr/bin/env python3
"""
registry.py — Experiment registry for tracking all Atlas experiments.

Provides a central registry that tracks experiment creation, status, and
metadata. The registry is persisted as a JSON file and supports querying
by experiment_id, phase, family, tier, and status.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from .config import ExperimentConfig


class ExperimentStatus(str, Enum):
    """Experiment lifecycle status."""
    CREATED = "CREATED"
    CONFIGURED = "CONFIGURED"
    TRAINING_STARTED = "TRAINING_STARTED"
    TRAINING_COMPLETED = "TRAINING_COMPLETED"
    TRAINING_FAILED = "TRAINING_FAILED"
    EVALUATION_STARTED = "EVALUATION_STARTED"
    EVALUATION_COMPLETED = "EVALUATION_COMPLETED"
    EVALUATION_FAILED = "EVALUATION_FAILED"
    ANALYSIS_COMPLETED = "ANALYSIS_COMPLETED"
    HOLD = "HOLD"
    CANCELLED = "CANCELLED"


@dataclass
class ExperimentRecord:
    """A single entry in the experiment registry."""
    experiment_id: str
    phase: str
    family: str
    tier: str
    target: str
    scope: str
    version: int
    status: ExperimentStatus
    created_at: str  # ISO 8601
    updated_at: str  # ISO 8601
    config_path: str | None = None
    training_view_id: str | None = None
    base_model: str | None = None
    model_revision: str | None = None
    train_jsonl_sha256: str | None = None
    eval_jsonl_sha256: str | None = None
    adapter_sha256: str | None = None
    git_commit: str | None = None
    git_commit_short: str | None = None
    seed: int | None = None
    hold_reason: str | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperimentRecord":
        status_val = data.get("status", "CREATED")
        if isinstance(status_val, str):
            status_val = ExperimentStatus(status_val)
        return cls(
            experiment_id=data["experiment_id"],
            phase=data["phase"],
            family=data["family"],
            tier=data["tier"],
            target=data["target"],
            scope=data["scope"],
            version=data["version"],
            status=status_val,
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            config_path=data.get("config_path"),
            training_view_id=data.get("training_view_id"),
            base_model=data.get("base_model"),
            model_revision=data.get("model_revision"),
            train_jsonl_sha256=data.get("train_jsonl_sha256"),
            eval_jsonl_sha256=data.get("eval_jsonl_sha256"),
            adapter_sha256=data.get("adapter_sha256"),
            git_commit=data.get("git_commit"),
            git_commit_short=data.get("git_commit_short"),
            seed=data.get("seed"),
            hold_reason=data.get("hold_reason"),
            notes=data.get("notes"),
        )

    @classmethod
    def from_config(cls, config: ExperimentConfig, status: ExperimentStatus = ExperimentStatus.CREATED) -> "ExperimentRecord":
        """Create a new registry record from an ExperimentConfig."""
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            experiment_id=config.experiment_id,
            phase=config.phase,
            family=config.family,
            tier=config.tier,
            target=config.target,
            scope=config.scope,
            version=config.version,
            status=status,
            created_at=now,
            updated_at=now,
            config_path=None,
            training_view_id=config.training_view_id,
            base_model=config.base_model,
            model_revision=config.model_revision,
            seed=config.training.seed,
        )

    def update(self, **kwargs: Any) -> None:
        """Update fields in-place and refresh updated_at."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.updated_at = datetime.now(timezone.utc).isoformat()


class ExperimentRegistry:
    """
    Central registry for tracking all Atlas experiments.

    The registry is persisted as a JSON file under metadata/experiment_registry.json.
    It supports:
      - Creating new experiment records
      - Updating experiment status and metadata
      - Querying experiments by various criteria
      - Listing experiments by family, tier, status, etc.
    """

    SCHEMA_VERSION = "1.0"
    REGISTRY_KEY = "experiment_registry.json"

    def __init__(self, registry_path: str | Path | None = None):
        self._path = Path(registry_path) if registry_path else None
        self._records: dict[str, ExperimentRecord] = {}
        self._loaded = False

    @property
    def path(self) -> Path:
        if self._path is None:
            from ..atlas_paths import metadata_dir
            self._path = metadata_dir() / self.REGISTRY_KEY
        return self._path

    def load(self) -> None:
        """Load the registry from disk."""
        if not self.path.exists():
            self._records = {}
            self._loaded = True
            return
        with self.path.open(encoding="utf-8") as f:
            data = json.load(f)
        if data.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError(
                f"Registry schema version mismatch: expected {self.SCHEMA_VERSION}, "
                f"got {data.get('schema_version')}"
            )
        self._records = {
            rec["experiment_id"]: ExperimentRecord.from_dict(rec)
            for rec in data.get("experiments", [])
        }
        self._loaded = True

    def save(self) -> None:
        """Save the registry to disk."""
        if not self._loaded:
            self.load()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": self.SCHEMA_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "experiment_count": len(self._records),
            "experiments": [rec.to_dict() for rec in self._records.values()],
        }
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")

    def create(self, config: ExperimentConfig) -> ExperimentRecord:
        """Create a new experiment record from configuration."""
        if not self._loaded:
            self.load()
        record = ExperimentRecord.from_config(config)
        self._records[config.experiment_id] = record
        self.save()
        return record

    def get(self, experiment_id: str) -> ExperimentRecord | None:
        """Get an experiment record by ID."""
        if not self._loaded:
            self.load()
        return self._records.get(experiment_id)

    def update(self, experiment_id: str, **kwargs: Any) -> ExperimentRecord:
        """Update an experiment record."""
        if not self._loaded:
            self.load()
        if experiment_id not in self._records:
            raise KeyError(f"Experiment {experiment_id!r} not found in registry")
        record = self._records[experiment_id]
        record.update(**kwargs)
        self._records[experiment_id] = record
        self.save()
        return record

    def delete(self, experiment_id: str) -> bool:
        """Remove an experiment record (soft delete — only removes from registry, not artifacts)."""
        if not self._loaded:
            self.load()
        if experiment_id in self._records:
            del self._records[experiment_id]
            self.save()
            return True
        return False

    def list_by_status(self, status: ExperimentStatus) -> list[ExperimentRecord]:
        """List all experiments with the given status."""
        if not self._loaded:
            self.load()
        return [rec for rec in self._records.values() if rec.status == status]

    def list_by_family(self, family: str) -> list[ExperimentRecord]:
        """List all experiments for a given family."""
        if not self._loaded:
            self.load()
        return [rec for rec in self._records.values() if rec.family == family]

    def list_by_tier(self, tier: str) -> list[ExperimentRecord]:
        """List all experiments for a given tier."""
        if not self._loaded:
            self.load()
        return [rec for rec in self._records.values() if rec.tier == tier]

    def list_by_phase(self, phase: str) -> list[ExperimentRecord]:
        """List all experiments for a given phase."""
        if not self._loaded:
            self.load()
        return [rec for rec in self._records.values() if rec.phase == phase]

    def list_active(self) -> list[ExperimentRecord]:
        """List all experiments that are not terminal (HOLD, CANCELLED, etc.)."""
        if not self._loaded:
            self.load()
        terminal = {ExperimentStatus.HOLD, ExperimentStatus.CANCELLED}
        return [rec for rec in self._records.values() if rec.status not in terminal]

    def list_completed(self) -> list[ExperimentRecord]:
        """List all experiments that have reached a completed status."""
        if not self._loaded:
            self.load()
        completed = {
            ExperimentStatus.TRAINING_COMPLETED,
            ExperimentStatus.EVALUATION_COMPLETED,
            ExperimentStatus.ANALYSIS_COMPLETED,
        }
        return [rec for rec in self._records.values() if rec.status in completed]

    def list_holds(self) -> list[ExperimentRecord]:
        """List all experiments currently on HOLD."""
        if not self._loaded:
            self.load()
        return [rec for rec in self._records.values() if rec.status == ExperimentStatus.HOLD]

    def __len__(self) -> int:
        if not self._loaded:
            self.load()
        return len(self._records)

    def __iter__(self) -> Iterator[ExperimentRecord]:
        if not self._loaded:
            self.load()
        return iter(self._records.values())

    def __contains__(self, experiment_id: str) -> bool:
        if not self._loaded:
            self.load()
        return experiment_id in self._records

    def summary(self) -> dict[str, Any]:
        """Return a summary of the registry state."""
        if not self._loaded:
            self.load()
        status_counts: dict[str, int] = {}
        family_counts: dict[str, int] = {}
        tier_counts: dict[str, int] = {}
        for rec in self._records.values():
            status_counts[rec.status.value] = status_counts.get(rec.status.value, 0) + 1
            family_counts[rec.family] = family_counts.get(rec.family, 0) + 1
            tier_counts[rec.tier] = tier_counts.get(rec.tier, 0) + 1
        return {
            "schema_version": self.SCHEMA_VERSION,
            "total_experiments": len(self._records),
            "by_status": status_counts,
            "by_family": family_counts,
            "by_tier": tier_counts,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
