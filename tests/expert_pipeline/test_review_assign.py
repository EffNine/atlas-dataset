#!/usr/bin/env python3
"""Tests for the AI reviewer assignment generator."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from expert_pipeline import review_assign as ra

from conftest import swe_instance

ACCESSED = "2026-08-02"


def _sample_entry(record_id, source_id, band):
    return {
        "review_id": f"rev_{abs(hash(record_id)) % 1000000:06d}",
        "record_id": record_id,
        "source_id": source_id,
        "stratum": {"source_id": source_id, "quality_band": band},
        "review_status": "pending",
        "assigned_reviewer": None,
        "assigned_timestamp": None,
        "completed_timestamp": None,
        "calibration": {"auto_gate": "KEEP", "quality_score": 8},
        "record": {"id": record_id, "source": {"source_id": source_id}, "metadata": {}},
    }


def _sample_file(tmp_path, n=5):
    entries = [
        _sample_entry(f"expert_swe_{i:06d}", "expert-swe-001", [7, 8]) for i in range(n)
    ]
    entries.append(_sample_entry("expert_swe_000009", "expert-swe-001", [5, 6]))
    p = tmp_path / "sample.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return p


def test_generate_assignments_basic(tmp_path):
    sample = _sample_file(tmp_path, n=3)
    assignments = ra.generate_assignments(sample, assigned_at="2026-08-02T00:00:00+00:00")
    assert len(assignments) == 4
    for a in assignments:
        assert a["assigned_reviewer"] == "ai-reviewer:claude-sonnet-5"
        assert a["review_status"] == "assigned"
        assert a["completed_timestamp"] is None
        assert a["assigned_timestamp"] == "2026-08-02T00:00:00+00:00"
        assert a["record_id"]


def test_generate_priority_boundary():
    # boundary band 5-6 -> high; normal band -> normal
    sample_lines = [
        json.dumps(_sample_entry("expert_swe_000001", "expert-swe-001", [5, 6])),
        json.dumps(_sample_entry("expert_swe_000002", "expert-swe-001", [9, 10])),
    ]
    p = Path("/tmp/priority_sample_test.jsonl")
    p.write_text("\n".join(sample_lines) + "\n")
    try:
        assignments = ra.generate_assignments(p, assigned_at="2026-08-02T00:00:00+00:00")
        prio = {a["record_id"]: a["priority"] for a in assignments}
        assert prio["expert_swe_000001"] == "high"
        assert prio["expert_swe_000002"] == "normal"
    finally:
        p.unlink(missing_ok=True)


def test_write_refuses_overwrite(tmp_path):
    out = tmp_path / "assignments.json"
    out.write_text("{}")
    with pytest.raises(FileExistsError):
        ra.write_assignments([{"a": 1}], out)
    assert out.read_text() == "{}"


def test_summarize_counts(tmp_path):
    sample = _sample_file(tmp_path, n=3)
    assignments = ra.generate_assignments(sample, assigned_at="2026-08-02T00:00:00+00:00")
    s = ra.summarize(assignments)
    assert s["total"] == 4
    assert s["reviewer"] == "ai-reviewer:claude-sonnet-5"
    assert s["per_status"] == {"assigned": 4}
    assert s["per_priority"] == {"normal": 3, "high": 1}
