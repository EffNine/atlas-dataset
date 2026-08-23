#!/usr/bin/env python3
"""Tests for the SFT view builder (offline, synthetic fixtures)."""

from __future__ import annotations

import copy
import hashlib
import json

from expert_pipeline import sft_view

from conftest import kep_raw_row, openmath_row, score_record, swe_instance


def _make_records():
    from expert_pipeline.adapters.architecture import KepAdapter
    from expert_pipeline.adapters.openmath import OpenMathAdapter
    from expert_pipeline.adapters.swebench import SwebenchAdapter

    ACC = "2026-08-22"
    recs = []
    arch = KepAdapter(accessed_at=ACC).to_record(kep_raw_row(), 0)
    swe = SwebenchAdapter(accessed_at=ACC).to_record(swe_instance(), 0)
    math = OpenMathAdapter(accessed_at=ACC).to_record(openmath_row(), 0)
    for r in (arch, swe, math):
        score_record(r)  # fills metadata.quality_score
        r["metadata"]["quality_score"] = 8  # deterministic passing score
        recs.append(r)
    return recs


def test_gate_record_accepts_clean_record():
    rec = _make_records()[1]  # swebench
    assert sft_view.gate_record(rec, max_tokens=4096, min_quality=7) == []


def test_gate_record_rejections():
    recs = _make_records()
    # quality below threshold
    lowq = copy.deepcopy(recs[0])
    lowq["metadata"]["quality_score"] = 5
    assert "quality_below_threshold" in sft_view.gate_record(lowq, max_tokens=4096, min_quality=7)
    # license not allowed
    badlic = copy.deepcopy(recs[1])
    badlic["license"] = "CC-BY-NC-4.0"
    assert "license" in sft_view.gate_record(badlic, max_tokens=4096, min_quality=7)
    # token budget exceeded
    long_rec = copy.deepcopy(recs[1])
    long_rec["messages"][0]["content"] = "x" * (5000 * 4)
    assert "token_budget" in sft_view.gate_record(long_rec, max_tokens=4096, min_quality=7)
    # broken messages
    badmsg = copy.deepcopy(recs[1])
    badmsg["messages"] = [{"role": "user", "content": ""}]
    assert "messages" in sft_view.gate_record(badmsg, max_tokens=4096, min_quality=7)


def test_dedup_keys_original_id_and_text():
    a, b = _make_records()[0], _make_records()[0]
    assert sft_view.dedup_keys(a) == sft_view.dedup_keys(b)
    c = copy.deepcopy(a)
    c["provenance"]["original_id"] = "other/id"
    ka, kc = sft_view.dedup_keys(a), sft_view.dedup_keys(c)
    assert ka[0] != kc[0]          # oid differs
    assert ka[1] == kc[1]          # text hash still matches


def test_build_view_filters_dedups_and_manifest(tmp_path):
    recs = _make_records()
    dup = copy.deepcopy(recs[0])
    dup["id"] = "expert_arch_000999"  # same original_id -> duplicate
    lowq = copy.deepcopy(recs[2])
    lowq["metadata"]["quality_score"] = 4

    view_root = tmp_path / "atlas-sft-test"
    manifest = sft_view.build_view(recs + [dup, lowq], view_root,
                                   max_tokens=4096, min_quality=7)

    cats = {c: m["records"] for c, m in manifest["categories"].items()}
    assert set(cats) == {"architecture", "code", "math"}
    assert all(n == 1 for n in cats.values())
    assert manifest["accepted_total"] == 3
    assert sum(manifest["duplicates_skipped"].values()) == 1
    assert manifest["rejections"]["quality_below_threshold"] == 1

    # files on disk match manifest sha256 + counts
    result = sft_view.verify_view(view_root)
    assert result == {"verified": True, "problems": []}
    f = view_root / "code" / "train.jsonl"
    assert hashlib.sha256(f.read_bytes()).hexdigest() == \
        manifest["categories"]["code"]["sha256"]


def test_build_view_refuses_overwrite(tmp_path):
    recs = _make_records()
    view_root = tmp_path / "v"
    sft_view.build_view(recs[:1], view_root)
    import pytest
    with pytest.raises(FileExistsError):
        sft_view.build_view(recs[:1], view_root)


def test_verify_detects_tampering(tmp_path):
    recs = _make_records()[:1]
    view_root = tmp_path / "v"
    sft_view.build_view(recs, view_root)
    f = view_root / list(json.loads(
        (view_root / "MANIFEST.json").read_text())["categories"])[0] / "train.jsonl"
    f.write_text(f.read_text() + '{"tampered": true}\n')
    result = sft_view.verify_view(view_root)
    assert result["verified"] is False
    assert any("sha256 mismatch" in p or "record count" in p for p in result["problems"])
