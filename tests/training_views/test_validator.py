#!/usr/bin/env python3
"""Tests for validator.py."""

from __future__ import annotations

import pytest

ROOT = pytest.importorskip("pathlib").Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
import sys

sys.path.insert(0, str(SRC))

from atlas_training.training_views.validator import TrainingViewValidator  # noqa: E402


def _valid_record(record_id="rec_1"):
    return {
        "view_id": "v1",
        "record_id": record_id,
        "source": "test",
        "license": "MIT",
        "quality_score": 8,
        "category": "01_foundation",
        "messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}],
        "lineage": {
            "source_attribution": "src_1",
            "knowledge_object": "ko_1",
            "curated_release": "v0.1",
            "training_view": "v1",
        },
    }


def test_validator_schema_pass():
    v = TrainingViewValidator()
    assert v.validate_schema(_valid_record()) == []


def test_validator_schema_fail():
    v = TrainingViewValidator()
    rec = _valid_record()
    rec.pop("messages")
    errors = v.validate_schema(rec)
    assert errors


def test_validator_duplicates():
    v = TrainingViewValidator()
    recs = [_valid_record("r1"), _valid_record("r1")]
    errors = v.validate_duplicates(recs)
    assert errors
    assert "r1" in errors[0]


def test_validator_licenses():
    v = TrainingViewValidator()
    recs = [_valid_record(), _valid_record("r2")]
    recs[1]["license"] = "unknown"
    errors = v.validate_licenses(recs)
    assert len(errors) == 1
    assert "r2" in errors[0]


def test_validator_split_leakage():
    v = TrainingViewValidator()
    train = [_valid_record("r1")]
    validation = [_valid_record("r1")]
    eval_ = [_valid_record("r2")]
    errors = v.validate_split_leakage(train, validation, eval_)
    assert errors
    assert "r1" in errors[0]


def test_validator_provenance_pass():
    v = TrainingViewValidator()
    assert v.validate_provenance([_valid_record()]) == []


def test_validator_provenance_fail():
    v = TrainingViewValidator()
    rec = _valid_record()
    rec["lineage"].pop("source_attribution")
    errors = v.validate_provenance([rec])
    assert errors
