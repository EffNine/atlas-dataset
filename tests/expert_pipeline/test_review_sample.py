#!/usr/bin/env python3
"""Tests for the expert pipeline review sample generator."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from expert_pipeline import review_sample as rs

from conftest import openmath_row, swe_instance

ACCESSED = "2026-08-02"


def _swe_records(n=6):
    from expert_pipeline.adapters.swebench import SwebenchAdapter

    adapter = SwebenchAdapter(accessed_at=ACCESSED)
    return [adapter.to_record(swe_instance(instance_id=f"fake__fake-{i}"), i) for i in range(n)]


def _math_records(n=6):
    from expert_pipeline.adapters.openmath import OpenMathAdapter

    adapter = OpenMathAdapter(accessed_at=ACCESSED)
    return [adapter.to_record(openmath_row(), i) for i in range(n)]


def _scored(records):
    from expert_pipeline.quality import compute_dimensions, compute_quality_score

    for r in records:
        dims = compute_dimensions(r)
        r["metadata"]["quality_score"] = compute_quality_score(dims)
    return records


def test_build_sample_structure_and_stratification():
    recs = _scored(_swe_records(6) + _math_records(6))
    sample = rs.build_sample(recs, rate=0.5, seed=42)
    assert len(sample) > 0
    # envelope keys
    for e in sample:
        assert set(e) >= {"review_id", "record_id", "source_id", "stratum",
                          "review_status", "calibration", "record"}
        assert e["review_status"] == "pending"
        assert e["assigned_reviewer"] is None
        assert e["record"]["id"] == e["record_id"]
    # review ids sequential
    ids = [e["review_id"] for e in sample]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


def test_build_sample_deterministic():
    recs = _scored(_swe_records(40) + _math_records(40))
    a = rs.build_sample(recs, rate=0.5, seed=7)
    b = rs.build_sample(recs, rate=0.5, seed=7)
    assert [e["record_id"] for e in a] == [e["record_id"] for e in b]
    c = rs.build_sample(recs, rate=0.5, seed=8)
    assert [e["record_id"] for e in a] != [e["record_id"] for e in c]


def test_stratify_proportional_per_source():
    recs = _scored(_swe_records(10) + _math_records(10))
    sample = list(rs.stratify(recs, rate=0.5, seed=1))
    by_src = {}
    for r in sample:
        by_src[r["stratum"]["source_id"]] = by_src.get(r["stratum"]["source_id"], 0) + 1
    # 10 swe -> 5, 10 math -> 5 at 50% (round)
    assert by_src.get("expert-swe-001", 0) == 5
    assert by_src.get("expert-math-002", 0) == 5


def test_quality_band_key_present():
    recs = _scored(_swe_records(10))
    for r in rs.stratify(recs, rate=0.5, seed=3):
        band = r["stratum"]["quality_band"]
        assert isinstance(band, list) and len(band) == 2
        assert band[0] <= r["metadata"]["quality_score"] <= band[1]


def test_write_sample_refuses_overwrite(tmp_path):
    out = tmp_path / "sample.jsonl"
    out.write_text("existing\n")
    with pytest.raises(FileExistsError):
        rs.write_sample([{"x": 1}], out)
    assert out.read_text() == "existing\n"


def test_write_sample_roundtrip(tmp_path):
    recs = _scored(_swe_records(4))
    sample = rs.build_sample(recs, rate=0.75, seed=5)
    out = tmp_path / "sample.jsonl"
    rs.write_sample(sample, out)
    lines = [json.loads(l) for l in out.read_text().splitlines()]
    assert len(lines) == len(sample)
    assert lines[0]["review_id"] == sample[0]["review_id"]


# --- proportional (per-domain) review rates ---


def test_resolve_rate_fallback():
    assert rs.resolve_rate("mathematics", 0.05, None) == 0.05
    assert rs.resolve_rate("mathematics", 0.05, {"software_engineering": 0.2}) == 0.05
    assert rs.resolve_rate("software_engineering", 0.05,
                           {"software_engineering": 0.2}) == 0.2
    assert rs.resolve_rate(None, 0.05, {"software_engineering": 0.2}) == 0.05


def _arch_records(n=6):
    from expert_pipeline.adapters.architecture import KepAdapter

    from conftest import kep_raw_row

    adapter = KepAdapter(accessed_at=ACCESSED)
    return [adapter.to_record(kep_raw_row(), i) for i in range(n)]


def test_domain_rates_raise_targeted_sampling():
    recs = _scored(_swe_records(10) + _math_records(10) + _arch_records(10))
    # heavier sampling for architecture docs (no machine-verifiable answers),
    # flat default elsewhere
    sample = rs.build_sample(recs, rate=0.1, seed=11,
                             domain_rates={"software_engineering": 1.0})
    per_src = {}
    for e in sample:
        per_src[e["source_id"]] = per_src.get(e["source_id"], 0) + 1
    # both SWE and KEP are software_engineering -> fully sampled at 1.0
    assert per_src.get("expert-arch-001") == 10
    assert per_src.get("expert-swe-001") == 10
    # math keeps the base rate (~1 of 10)
    assert per_src.get("expert-math-002", 0) <= 2


def test_domain_rates_recorded_in_stratum():
    recs = _scored(_arch_records(4))
    sample = list(rs.stratify(recs, rate=0.05, seed=3,
                              domain_rates={"software_engineering": 1.0}))
    assert all(r["stratum"]["sample_rate"] == 1.0 for r in sample)


def test_default_behavior_unchanged_without_domain_rates():
    recs = _scored(_swe_records(20))
    legacy = list(rs.stratify(recs, rate=0.5, seed=9))
    extended = list(rs.stratify(recs, rate=0.5, seed=9, domain_rates=None))
    assert [r["id"] for r in legacy] == [r["id"] for r in extended]
