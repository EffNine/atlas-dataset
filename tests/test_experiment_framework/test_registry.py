#!/usr/bin/env python3
"""
Tests for scripts/experiment_framework/registry.py

Covers:
  - ExperimentRecord creation
  - Registry CRUD operations
  - Query methods (by status, family, tier, phase)
  - Summary statistics
  - Persistence round-trip
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

# Add scripts to path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from scripts.experiment_framework.registry import (  # noqa: E402
    ExperimentRegistry,
    ExperimentRecord,
    ExperimentStatus,
)
from scripts.experiment_framework.config import ExperimentConfig  # noqa: E402


# ===================================================================
# ExperimentRecord
# ===================================================================

class TestExperimentRecord:
    def test_from_config(self):
        config = ExperimentConfig("atlas-math-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1")
        record = ExperimentRecord.from_config(config)
        assert record.experiment_id == "atlas-math-pilot-qwen7b-lora-v1"
        assert record.family == "math"
        assert record.tier == "pilot"
        assert record.status == ExperimentStatus.CREATED
        assert record.created_at is not None
        assert record.updated_at is not None

    def test_from_dict(self):
        data = {
            "experiment_id": "test-exp",
            "phase": "5B.1",
            "family": "math",
            "tier": "pilot",
            "target": "qwen7b",
            "scope": "lora",
            "version": 1,
            "status": "TRAINING_COMPLETED",
            "created_at": "2026-08-01T00:00:00+00:00",
            "updated_at": "2026-08-02T00:00:00+00:00",
            "training_view_id": "math_300m_v0.1",
            "base_model": "Qwen/Qwen2.5-7B-Instruct",
            "seed": 42,
        }
        record = ExperimentRecord.from_dict(data)
        assert record.experiment_id == "test-exp"
        assert record.status == ExperimentStatus.TRAINING_COMPLETED
        assert record.seed == 42

    def test_update(self):
        config = ExperimentConfig("atlas-math-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1")
        record = ExperimentRecord.from_config(config)
        old_updated = record.updated_at
        record.update(status=ExperimentStatus.TRAINING_COMPLETED, notes="test note")
        assert record.status == ExperimentStatus.TRAINING_COMPLETED
        assert record.notes == "test note"
        assert record.updated_at >= old_updated

    def test_to_dict_round_trip(self):
        config = ExperimentConfig("atlas-math-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1")
        record = ExperimentRecord.from_config(config)
        d = record.to_dict()
        record2 = ExperimentRecord.from_dict(d)
        assert record2.experiment_id == record.experiment_id
        assert record2.status == record.status


# ===================================================================
# ExperimentRegistry
# ===================================================================

class TestExperimentRegistry:
    @pytest.fixture
    def registry(self, tmp_path: Path):
        return ExperimentRegistry(registry_path=tmp_path / "registry.json")

    def test_create_and_get(self, registry: ExperimentRegistry):
        config = ExperimentConfig("atlas-math-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1")
        record = registry.create(config)
        assert record.experiment_id == "atlas-math-pilot-qwen7b-lora-v1"
        retrieved = registry.get("atlas-math-pilot-qwen7b-lora-v1")
        assert retrieved is not None
        assert retrieved.experiment_id == record.experiment_id

    def test_get_missing(self, registry: ExperimentRegistry):
        assert registry.get("nonexistent") is None

    def test_update(self, registry: ExperimentRegistry):
        config = ExperimentConfig("atlas-code-pilot-qwen7b-lora-v1", "5B.2", "code_300m_v0.1")
        registry.create(config)
        record = registry.update(
            "atlas-code-pilot-qwen7b-lora-v1",
            status=ExperimentStatus.TRAINING_COMPLETED,
            git_commit="abc123",
        )
        assert record.status == ExperimentStatus.TRAINING_COMPLETED
        assert record.git_commit == "abc123"

    def test_update_missing(self, registry: ExperimentRegistry):
        with pytest.raises(KeyError):
            registry.update("nonexistent")

    def test_delete(self, registry: ExperimentRegistry):
        config = ExperimentConfig("atlas-math-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1")
        registry.create(config)
        assert registry.delete("atlas-math-pilot-qwen7b-lora-v1") is True
        assert registry.get("atlas-math-pilot-qwen7b-lora-v1") is None

    def test_delete_missing(self, registry: ExperimentRegistry):
        assert registry.delete("nonexistent") is False

    def test_list_by_family(self, registry: ExperimentRegistry):
        registry.create(ExperimentConfig("atlas-math-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1"))
        registry.create(ExperimentConfig("atlas-math-small-qwen7b-lora-v1", "5B.2", "math_300m_v0.1"))
        registry.create(ExperimentConfig("atlas-code-pilot-qwen7b-lora-v1", "5B.2", "code_300m_v0.1"))
        math_exps = registry.list_by_family("math")
        assert len(math_exps) == 2
        code_exps = registry.list_by_family("code")
        assert len(code_exps) == 1

    def test_list_by_tier(self, registry: ExperimentRegistry):
        registry.create(ExperimentConfig("atlas-math-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1"))
        registry.create(ExperimentConfig("atlas-math-small-qwen7b-lora-v1", "5B.2", "math_300m_v0.1"))
        pilots = registry.list_by_tier("pilot")
        assert len(pilots) == 1
        smalls = registry.list_by_tier("small")
        assert len(smalls) == 1

    def test_list_by_status(self, registry: ExperimentRegistry):
        config = ExperimentConfig("atlas-math-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1")
        registry.create(config)
        registry.update("atlas-math-pilot-qwen7b-lora-v1", status=ExperimentStatus.HOLD)
        holds = registry.list_by_status(ExperimentStatus.HOLD)
        assert len(holds) == 1
        assert holds[0].experiment_id == "atlas-math-pilot-qwen7b-lora-v1"

    def test_list_active(self, registry: ExperimentRegistry):
        registry.create(ExperimentConfig("atlas-math-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1"))
        registry.create(ExperimentConfig("atlas-code-pilot-qwen7b-lora-v1", "5B.2", "code_300m_v0.1"))
        registry.update("atlas-code-pilot-qwen7b-lora-v1", status=ExperimentStatus.CANCELLED)
        active = registry.list_active()
        assert len(active) == 1
        assert active[0].experiment_id == "atlas-math-pilot-qwen7b-lora-v1"

    def test_list_completed(self, registry: ExperimentRegistry):
        config = ExperimentConfig("atlas-math-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1")
        registry.create(config)
        registry.update("atlas-math-pilot-qwen7b-lora-v1", status=ExperimentStatus.ANALYSIS_COMPLETED)
        completed = registry.list_completed()
        assert len(completed) == 1

    def test_list_holds(self, registry: ExperimentRegistry):
        config = ExperimentConfig("atlas-math-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1")
        registry.create(config)
        registry.update("atlas-math-pilot-qwen7b-lora-v1", status=ExperimentStatus.HOLD, hold_reason="waiting for GPU")
        holds = registry.list_holds()
        assert len(holds) == 1
        assert holds[0].hold_reason == "waiting for GPU"

    def test_persistence(self, registry: ExperimentRegistry):
        config = ExperimentConfig("atlas-math-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1")
        registry.create(config)
        registry.save()

        # Reload from disk
        registry2 = ExperimentRegistry(registry_path=registry.path)
        registry2.load()
        assert registry2.get("atlas-math-pilot-qwen7b-lora-v1") is not None
        assert registry2.get("atlas-math-pilot-qwen7b-lora-v1").family == "math"

    def test_len(self, registry: ExperimentRegistry):
        assert len(registry) == 0
        registry.create(ExperimentConfig("atlas-math-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1"))
        assert len(registry) == 1

    def test_contains(self, registry: ExperimentRegistry):
        registry.create(ExperimentConfig("atlas-math-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1"))
        assert "atlas-math-pilot-qwen7b-lora-v1" in registry
        assert "nonexistent" not in registry

    def test_summary(self, registry: ExperimentRegistry):
        registry.create(ExperimentConfig("atlas-math-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1"))
        registry.create(ExperimentConfig("atlas-code-small-qwen7b-lora-v1", "5B.2", "code_300m_v0.1"))
        registry.update("atlas-code-small-qwen7b-lora-v1", status=ExperimentStatus.HOLD)
        summary = registry.summary()
        assert summary["total_experiments"] == 2
        assert summary["by_family"]["math"] == 1
        assert summary["by_family"]["code"] == 1
        assert summary["by_status"]["HOLD"] == 1

    def test_iter(self, registry: ExperimentRegistry):
        registry.create(ExperimentConfig("atlas-math-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1"))
        ids = [r.experiment_id for r in registry]
        assert len(ids) == 1
        assert ids[0] == "atlas-math-pilot-qwen7b-lora-v1"
