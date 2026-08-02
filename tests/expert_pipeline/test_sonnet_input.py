#!/usr/bin/env python3
"""Tests for the Sonnet 5 blind input payload generator."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from expert_pipeline import sonnet_input as si

from conftest import openmath_row, swe_instance

ACCESSED = "2026-08-02"


def _entry(rec, i):
    return {
        "review_id": f"rev_{i:06d}",
        "record_id": rec["id"],
        "source_id": rec["source"]["source_id"],
        "stratum": {"source_id": rec["source"]["source_id"], "quality_band": [7, 8]},
        "review_status": "pending",
        "assigned_reviewer": None,
        "assigned_timestamp": None,
        "completed_timestamp": None,
        "calibration": {"auto_gate": "KEEP", "quality_score": 8, "difficulty": 3, "expert_tier": "E2"},
        "record": rec,
    }


def _swe_records(n=3):
    from expert_pipeline.adapters.swebench import SwebenchAdapter

    adapter = SwebenchAdapter(accessed_at=ACCESSED)
    return [adapter.to_record(swe_instance(instance_id=f"fake__fake-{i}"), i) for i in range(n)]


def test_blind_payload_strips_gate_values():
    recs = _swe_records(1)
    entry = _entry(recs[0], 0)
    block = si.blind_payload(entry)
    # envelope
    assert block["review_id"] == "rev_000000"
    assert block["record_id"] == recs[0]["id"]
    # no calibration, no quality_score anywhere in payload
    assert "calibration" not in block["payload"]
    assert "quality_score" not in json.dumps(block)
    assert "auto_gate" not in json.dumps(block)
    # record content intact
    for field in ("problem", "solution", "license", "provenance", "source", "messages"):
        assert field in block["payload"]


def test_generate_and_guard(tmp_path):
    recs = _swe_records(3)
    entries = [_entry(r, i) for i, r in enumerate(recs)]
    sample = tmp_path / "sample.jsonl"
    sample.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

    out = tmp_path / "input.jsonl"
    blocks = si.generate(sample, out)
    assert len(blocks) == 3
    lines = [json.loads(l) for l in out.read_text().splitlines()]
    assert len(lines) == 3
    # blind guard clean
    assert si.blind_guard(out) == []
    # record_ids preserved 1:1
    assert [b["record_id"] for b in lines] == [e["record_id"] for e in entries]


def test_generate_refuses_overwrite(tmp_path):
    recs = _swe_records(1)
    entries = [_entry(r, 0) for r in recs]
    sample = tmp_path / "sample.jsonl"
    sample.write_text(json.dumps(entries[0]) + "\n")
    out = tmp_path / "input.jsonl"
    out.write_text("existing\n")
    with pytest.raises(FileExistsError):
        si.generate(sample, out)
    assert out.read_text() == "existing\n"
