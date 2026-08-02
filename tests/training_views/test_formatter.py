#!/usr/bin/env python3
"""Tests for formatter.py."""

from __future__ import annotations

import pytest

ROOT = pytest.importorskip("pathlib").Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
import sys

sys.path.insert(0, str(SRC))

from atlas_training.training_views.formatter import TrainingViewFormatter  # noqa: E402


def _record():
    return {
        "id": "ko_1",
        "source": {"name": "test"},
        "license": "MIT",
        "quality_score": 8,
        "category": "01_foundation",
        "subcategory": "general-reasoning",
        "difficulty": 2,
        "knowledge_type": "factual",
        "messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}],
        "training_view_eligibility": {"qwen": True, "llama": True},
        "source_attribution": {"source_id": "src_1"},
        "lineage": {
            "source": "test",
            "transformations": ["clean"],
            "knowledge_object": "ko_1",
            "curated_dataset": "curated/v0.1",
            "training_view": "all",
            "future_model": "future",
        },
    }


def test_format_required_fields():
    fmt = TrainingViewFormatter(view_id="v1", curated_release="v0.1")
    rec = fmt.format(_record())
    assert rec["view_id"] == "v1"
    assert rec["record_id"] == "ko_1"
    assert rec["messages"] == _record()["messages"]
    assert rec["eligibility"] == {"qwen": True, "llama": True}


def test_format_trimmed_lineage():
    fmt = TrainingViewFormatter(view_id="v1", curated_release="v0.1")
    rec = fmt.format(_record())
    assert rec["lineage"]["curated_release"] == "v0.1"
    assert rec["lineage"]["training_view"] == "v1"
    assert rec["lineage"]["source_attribution"] == "src_1"
    assert "transformations" not in rec["lineage"]


def test_format_batch():
    fmt = TrainingViewFormatter(view_id="v1", curated_release="v0.1")
    recs = fmt.format_batch([_record(), _record()])
    assert len(recs) == 2
    assert recs[0]["record_id"] == recs[1]["record_id"] == "ko_1"


def test_format_missing_fields():
    fmt = TrainingViewFormatter(view_id="v1", curated_release="v0.1")
    rec = fmt.format({"id": "x"})
    assert rec["record_id"] == "x"
    assert rec["messages"] == []
