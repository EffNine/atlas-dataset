#!/usr/bin/env python3
"""Tests for expert pipeline validation and quality gate."""

from __future__ import annotations

import pytest

from expert_pipeline.adapters.openmath import OpenMathAdapter
from expert_pipeline.adapters.swebench import SwebenchAdapter
from expert_pipeline.quality import (
    classify_gate,
    compute_dimensions,
    compute_quality_score,
    is_gold,
)
from expert_pipeline.validation import (
    detect_duplicates,
    security_scan,
    validate_license,
    validate_provenance,
    validate_schema,
)

from conftest import openmath_row, swe_instance

ACCESSED = "2026-08-02"


def _base_record():
    adapter = SwebenchAdapter(accessed_at=ACCESSED)
    return adapter.to_record(swe_instance(), 0)


def test_schema_rejects_missing_id():
    rec = _base_record()
    rec.pop("id")
    errs = validate_schema(rec)
    assert any("missing:id" in e for e in errs)


def test_schema_rejects_bad_domain():
    rec = _base_record()
    rec["domain"] = "astrology"
    errs = validate_schema(rec)
    assert any("invalid:domain" in e for e in errs)


def test_schema_rejects_bad_difficulty():
    rec = _base_record()
    rec["difficulty"] = 0
    errs = validate_schema(rec)
    assert any("invalid:difficulty" in e for e in errs)


def test_schema_rejects_empty_messages():
    rec = _base_record()
    rec["messages"] = []
    errs = validate_schema(rec)
    assert any("invalid:messages" in e for e in errs)


def test_schema_rejects_user_only_messages():
    rec = _base_record()
    rec["messages"] = [{"role": "user", "content": "hi"}]
    errs = validate_schema(rec)
    assert any("invalid:messages" in e for e in errs)


def test_provenance_missing_original_id():
    rec = _base_record()
    rec["provenance"]["original_id"] = ""
    errs = validate_provenance(rec)
    assert any("missing:provenance.original_id" in e for e in errs)


def test_license_unknown_rejected():
    rec = _base_record()
    rec["license"] = "unknown"
    errs = validate_license(rec)
    assert any("invalid:license:unknown" in e for e in errs)


def test_license_nc_rejected():
    rec = _base_record()
    rec["license"] = "CC-BY-NC-SA-4.0"
    errs = validate_license(rec)
    assert any("invalid:license:blocked" in e for e in errs)


def test_license_mit_ok():
    rec = _base_record()
    assert validate_license(rec) == []


def test_sharealike_requires_attribution():
    rec = _base_record()
    rec["license"] = "CC-BY-SA-4.0"
    rec["attribution"] = ""
    errs = validate_license(rec)
    assert any("invalid:attribution" in e for e in errs)


def test_security_scan_catches_private_key():
    rec = _base_record()
    rec["solution"] = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpQ==\n-----END RSA PRIVATE KEY-----"
    hits = security_scan(rec)
    assert "private_key" in hits


def test_security_scan_clean():
    rec = _base_record()
    assert security_scan(rec) == {}


def test_duplicate_detection_exact_and_near():
    adapter = SwebenchAdapter(accessed_at=ACCESSED)
    a = adapter.to_record(swe_instance(), 0)
    b = adapter.to_record(swe_instance(), 1)  # same content, different idx id
    b["id"] = a["id"]  # force exact id dup
    c = adapter.to_record(swe_instance(), 2)
    c["id"] = "expert_swe_000002"
    c["problem"] = a["problem"]  # near dup content
    result = detect_duplicates([a, b, c])
    assert len(result["exact_duplicate_ids"]) == 1
    assert len(result["near_duplicate_groups"]) >= 1


def test_quality_gate_classification():
    adapter = SwebenchAdapter(accessed_at=ACCESSED)
    rec = adapter.to_record(swe_instance(), 0)
    dims = compute_dimensions(rec)
    rec["metadata"]["quality_score"] = compute_quality_score(dims)
    label = classify_gate(rec, schema_ok=True, dims=dims)
    assert label == "KEEP"


def test_gold_requires_all_dimensions():
    # Gold requires correctness >= 4, reasoning_depth >= 4, explanation >= 4.
    rec = _base_record()
    dims = {
        "correctness": 4,
        "reasoning_depth": 4,
        "explanation_quality": 4,
        "provenance_confidence": 4,
    }
    assert is_gold(rec, dims) is True
    dims["reasoning_depth"] = 3
    assert is_gold(rec, dims) is False


def test_gate_correctness_3_is_keep():
    # Regression: correctness == 3 must be KEEP (reject is <= 2).
    rec = _base_record()
    dims = {
        "correctness": 3,
        "reasoning_depth": 3,
        "explanation_quality": 3,
        "provenance_confidence": 4,
    }
    assert classify_gate(rec, schema_ok=True, dims=dims) == "KEEP"


def test_gate_correctness_2_is_reject():
    rec = _base_record()
    dims = {
        "correctness": 2,
        "reasoning_depth": 3,
        "explanation_quality": 3,
        "provenance_confidence": 4,
    }
    assert classify_gate(rec, schema_ok=True, dims=dims) == "REJECT"


def test_quality_gate_rejects_empty_solution():
    adapter = SwebenchAdapter(accessed_at=ACCESSED)
    rec = adapter.to_record(swe_instance(patch=""), 0)
    dims = compute_dimensions(rec)
    label = classify_gate(rec, schema_ok=True, dims=dims)
    assert label == "REJECT"


def test_quality_score_range():
    adapter = OpenMathAdapter(accessed_at=ACCESSED)
    rec = adapter.to_record(openmath_row(), 0)
    dims = compute_dimensions(rec)
    score = compute_quality_score(dims)
    assert 0 <= score <= 10
