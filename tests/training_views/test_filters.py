#!/usr/bin/env python3
"""Tests for filters.py."""

from __future__ import annotations

import pytest

ROOT = pytest.importorskip("pathlib").Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
import sys

sys.path.insert(0, str(SRC))

from atlas_training.training_views.filters import LicenseFilter, QualityFilter, DifficultyFilter, DomainFilter, ProvenanceFilter, TrainingViewFilters  # noqa: E402


def _base_record(**overrides):
    rec = {
        "id": "rec_1",
        "source": {"source_id": "expert-swe-001", "name": "test"},
        "license": "MIT",
        "quality_score": 8,
        "difficulty": 3,
        "lineage": {
            "source": "test",
            "transformations": ["clean"],
            "knowledge_object": "ko_1",
            "curated_dataset": "curated/v0.1",
            "training_view": "all",
            "future_model": "future",
        },
        "messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}],
        "category": "01_foundation",
    }
    rec.update(overrides)
    return rec


def test_license_filter_allowed():
    assert LicenseFilter.is_allowed("MIT") is True
    assert LicenseFilter.is_allowed("Apache-2.0") is True
    assert LicenseFilter.is_allowed("CC-BY-4.0") is True


def test_license_filter_denied():
    assert LicenseFilter.is_allowed("unknown") is False
    assert LicenseFilter.is_allowed("CC-BY-NC-SA") is False
    assert LicenseFilter.is_allowed("CC-BY-NC") is False
    assert LicenseFilter.is_allowed("") is False


def test_quality_filter_pass():
    f = QualityFilter(min_quality=7)
    assert f.passes(_base_record()) is True


def test_quality_filter_fail():
    f = QualityFilter(min_quality=7)
    rec = _base_record(quality_score=6)
    assert f.passes(rec) is False
    assert f.passes(_base_record(quality_score="bad")) is False


def test_difficulty_filter_pass():
    f = DifficultyFilter()
    assert f.passes(_base_record(), min_difficulty=1, max_difficulty=10) is True


def test_difficulty_filter_fail():
    f = DifficultyFilter()
    assert f.passes(_base_record(difficulty=0), min_difficulty=1, max_difficulty=10) is False


def test_domain_filter_pass():
    f = DomainFilter()
    assert f.passes(_base_record(), allowed_source_ids=["expert-swe-001"]) is True


def test_domain_filter_empty_allowed():
    f = DomainFilter()
    assert f.passes(_base_record(), allowed_source_ids=[]) is True


def test_domain_filter_fail():
    f = DomainFilter()
    assert f.passes(_base_record(), allowed_source_ids=["other"]) is False


def test_provenance_filter_pass():
    assert ProvenanceFilter.passes(_base_record()) is True


def test_provenance_filter_fail():
    assert ProvenanceFilter.passes(_base_record(lineage={"source": "test"})) is False


def test_training_view_filters_eligible():
    f = TrainingViewFilters(min_quality=7)
    assert f.is_eligible(_base_record(), {"difficulty_range": [1, 10]}) is True


def test_training_view_filters_reject_license():
    f = TrainingViewFilters(min_quality=7)
    rec = _base_record(license="unknown")
    assert f.is_eligible(rec, {"difficulty_range": [1, 10]}) is False


def test_training_view_filters_reject_domain():
    f = TrainingViewFilters(min_quality=7)
    rec = _base_record(source={"source_id": "other"})
    assert f.is_eligible(rec, {"difficulty_range": [1, 10], "source_ids": ["expert-swe-001"]}) is False
