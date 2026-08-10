#!/usr/bin/env python3
"""
Tests for scripts/experiment_framework/manifests.py

Covers:
  - DatasetManifest creation and validation
  - TrainingManifest creation and validation
  - EvaluationManifest creation and validation
  - Checksum verification
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

import pytest

# Add scripts to path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from scripts.experiment_framework.manifests import (  # noqa: E402
    DatasetManifest,
    TrainingManifest,
    EvaluationManifest,
)
from scripts.experiment_framework.config import ExperimentConfig  # noqa: E402
from scripts.experiment_framework.metadata import compute_sha256  # noqa: E402


# ===================================================================
# DatasetManifest
# ===================================================================

class TestDatasetManifest:
    def test_create_train(self, tmp_path: Path):
        train_file = tmp_path / "train.jsonl"
        train_file.write_text(
            json.dumps({"record_id": "r1", "value": 1}) + "\n"
            + json.dumps({"record_id": "r2", "value": 2}) + "\n",
            encoding="utf-8"
        )
        manifest = DatasetManifest.create(
            dataset_id="math_train_v1",
            file_path=train_file,
            split_type="train",
        )
        assert manifest.dataset_id == "math_train_v1"
        assert manifest.split_type == "train"
        assert manifest.n_records == 2
        assert manifest.raw_sha256 is not None
        assert manifest.records_sha256 is not None
        assert manifest.checksum_match is None  # no approved hash provided

    def test_create_with_approved_hash(self, tmp_path: Path):
        train_file = tmp_path / "train.jsonl"
        train_file.write_text('{"record_id": "r1"}\n', encoding="utf-8")
        approved_hash = compute_sha256(train_file)
        manifest = DatasetManifest.create(
            dataset_id="math_train_v1",
            file_path=train_file,
            split_type="train",
            approved_sha256=approved_hash,
        )
        assert manifest.checksum_match is True

    def test_create_mismatched_hash(self, tmp_path: Path):
        train_file = tmp_path / "train.jsonl"
        train_file.write_text('{"record_id": "r1"}\n', encoding="utf-8")
        manifest = DatasetManifest.create(
            dataset_id="math_train_v1",
            file_path=train_file,
            split_type="train",
            approved_sha256="0" * 64,
        )
        assert manifest.checksum_match is False

    def test_validate_pass(self, tmp_path: Path):
        train_file = tmp_path / "train.jsonl"
        train_file.write_text('{"record_id": "r1"}\n', encoding="utf-8")
        manifest = DatasetManifest.create(
            dataset_id="math_train_v1",
            file_path=train_file,
            split_type="train",
        )
        errors = manifest.validate()
        assert len(errors) == 0

    def test_validate_invalid_split_type(self):
        manifest = DatasetManifest(
            dataset_id="test",
            file_path="/tmp/test.jsonl",
            split_type="invalid",
            n_records=10,
            raw_sha256="a" * 64,
            records_sha256="b" * 64,
        )
        errors = manifest.validate()
        assert any("split_type" in e for e in errors)

    def test_validate_checksum_mismatch(self, tmp_path: Path):
        train_file = tmp_path / "train.jsonl"
        train_file.write_text('{"record_id": "r1"}\n', encoding="utf-8")
        manifest = DatasetManifest.create(
            dataset_id="math_train_v1",
            file_path=train_file,
            split_type="train",
            approved_sha256="0" * 64,
        )
        errors = manifest.validate()
        assert any("checksum mismatch" in e for e in errors)

    def test_to_dict_from_dict(self, tmp_path: Path):
        train_file = tmp_path / "train.jsonl"
        train_file.write_text('{"record_id": "r1"}\n', encoding="utf-8")
        manifest = DatasetManifest.create(
            dataset_id="math_train_v1",
            file_path=train_file,
            split_type="train",
        )
        d = manifest.to_dict()
        manifest2 = DatasetManifest.from_dict(d)
        assert manifest2.dataset_id == manifest.dataset_id
        assert manifest2.n_records == manifest.n_records


# ===================================================================
# TrainingManifest
# ===================================================================

class TestTrainingManifest:
    def test_create(self, tmp_path: Path):
        train_file = tmp_path / "train.jsonl"
        train_file.write_text('{"record_id": "r1"}\n', encoding="utf-8")
        dataset_manifest = DatasetManifest.create(
            dataset_id="math_train_v1",
            file_path=train_file,
            split_type="train",
        )
        config = ExperimentConfig("atlas-math-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1")
        manifest = TrainingManifest.create(config, dataset_manifest)
        assert manifest.experiment_id == "atlas-math-pilot-qwen7b-lora-v1"
        assert manifest.phase == "5B.1"
        assert manifest.dataset_manifest is not None
        assert manifest.git_info is not None
        assert manifest.hardware_info is not None

    def test_validate_pass(self, tmp_path: Path):
        train_file = tmp_path / "train.jsonl"
        train_file.write_text('{"record_id": "r1"}\n', encoding="utf-8")
        dataset_manifest = DatasetManifest.create(
            dataset_id="math_train_v1",
            file_path=train_file,
            split_type="train",
        )
        config = ExperimentConfig("atlas-math-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1")
        manifest = TrainingManifest.create(config, dataset_manifest)
        errors = manifest.validate()
        assert len(errors) == 0

    def test_validate_missing_dataset(self):
        config = ExperimentConfig("atlas-math-pilot-qwen7b-lora-v1", "5B.1", "math_300m_v0.1")
        manifest = TrainingManifest(
            experiment_id=config.experiment_id,
            phase=config.phase,
            config=config.to_dict(),
        )
        errors = manifest.validate()
        assert any("dataset_manifest" in e for e in errors)


# ===================================================================
# EvaluationManifest
# ===================================================================

class TestEvaluationManifest:
    def test_create(self, tmp_path: Path):
        eval_file = tmp_path / "eval.jsonl"
        eval_file.write_text(
            json.dumps({"record_id": "r1", "view_id": "math-300m"}) + "\n"
            + json.dumps({"record_id": "r2", "view_id": "math-300m"}) + "\n",
            encoding="utf-8"
        )
        manifest = EvaluationManifest.create(
            experiment_id="test-exp",
            eval_jsonl_path=eval_file,
            eval_split_id="math_eval_v1",
            engine="QEE v2",
            engine_commit="abc123",
            baseline_experiment_id="baseline_v0.2",
        )
        assert manifest.experiment_id == "test-exp"
        assert manifest.eval_split_id == "math_eval_v1"
        assert manifest.engine == "QEE v2"
        assert manifest.engine_commit == "abc123"
        assert manifest.n_eval_records == 2
        assert manifest.eval_sha256 is not None
        assert manifest.baseline_experiment_id == "baseline_v0.2"

    def test_validate_pass(self, tmp_path: Path):
        eval_file = tmp_path / "eval.jsonl"
        eval_file.write_text('{"record_id": "r1"}\n', encoding="utf-8")
        manifest = EvaluationManifest.create(
            experiment_id="test-exp",
            eval_jsonl_path=eval_file,
            eval_split_id="math_eval_v1",
        )
        errors = manifest.validate()
        assert len(errors) == 0

    def test_validate_missing_experiment_id(self):
        eval_file = Path("/tmp/fake.jsonl")
        manifest = EvaluationManifest(
            experiment_id="",
            eval_split_id="math_eval_v1",
            eval_jsonl_path=str(eval_file),
            eval_sha256="a" * 64,
            eval_records_sha256="b" * 64,
            n_eval_records=10,
            engine="QEE v2",
        )
        errors = manifest.validate()
        assert any("experiment_id" in e for e in errors)
