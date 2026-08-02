#!/usr/bin/env python3
"""Tests for expert pipeline adapters (synthetic fixtures, offline)."""

from __future__ import annotations

import pytest

from expert_pipeline.adapters.arxiv import ArxivAdapter, _check_retraction
from expert_pipeline.adapters.openmath import OpenMathAdapter
from expert_pipeline.adapters.swebench import SwebenchAdapter
from expert_pipeline.validation import validate_provenance, validate_schema

from conftest import arxiv_paper, openmath_row, score_record, swe_instance

ACCESSED = "2026-08-02"


def test_swebench_record_schema_and_provenance():
    adapter = SwebenchAdapter(accessed_at=ACCESSED)
    rec = adapter.to_record(swe_instance(), 0)
    assert rec["id"] == "expert_swe_000000"
    assert rec["domain"] == "software_engineering"
    assert rec["expert_tier"] == "E2"
    assert rec["license"] == "MIT"
    assert rec["difficulty"] == 3  # "15 min - 1 hour" -> 3
    assert rec["verification"]["method"] == "gold_patch"
    assert rec["verification"]["status"] == "verified"
    assert rec["verification"]["evidence"] == "FAIL_TO_PASS=1, PASS_TO_PASS=2"
    assert rec["metadata"]["model_generated"] is False
    assert rec["curated"] is False
    score_record(rec)
    assert validate_schema(rec) == []
    assert validate_provenance(rec) == []


def test_swebench_difficulty_mapping():
    adapter = SwebenchAdapter(accessed_at=ACCESSED)
    rec = adapter.to_record(swe_instance(difficulty=">4 hours"), 1)
    assert rec["difficulty"] == 5
    rec2 = adapter.to_record(swe_instance(difficulty="<15 min fix"), 2)
    assert rec2["difficulty"] == 2
    rec3 = adapter.to_record(swe_instance(difficulty="unknown-label"), 3)
    assert rec3["difficulty"] == 3  # default


def test_swebench_deterministic_ids():
    adapter = SwebenchAdapter(accessed_at=ACCESSED)
    a = adapter.to_record(swe_instance(), 0)
    b = adapter.to_record(swe_instance(), 0)
    assert a["id"] == b["id"]
    assert a["provenance"]["original_id"] == "django__django-11099"


def test_openmath_record():
    adapter = OpenMathAdapter(accessed_at=ACCESSED)
    rec = adapter.to_record(openmath_row(), 0)
    assert rec["id"] == "expert_math_000000"
    assert rec["domain"] == "mathematics"
    assert rec["license"] == "CC-BY-4.0"
    assert rec["metadata"]["model_generated"] is True
    assert rec["metadata"]["synthetic"] is True
    assert rec["verification"]["status"] == "needs_review"
    assert rec["extraction"]["problem_source"] == "augmented_math"
    score_record(rec)
    assert validate_schema(rec) == []
    assert validate_provenance(rec) == []


def test_openmath_original_id_deterministic():
    adapter = OpenMathAdapter(accessed_at=ACCESSED)
    a = adapter.to_record(openmath_row(), 0)
    b = adapter.to_record(openmath_row(), 0)
    assert a["provenance"]["original_id"] == b["provenance"]["original_id"]
    assert a["provenance"]["original_id"].startswith("expert_math_002_")


def test_arxiv_record():
    adapter = ArxivAdapter(accessed_at=ACCESSED)
    rec = adapter.to_record(arxiv_paper(), 0)
    assert rec["id"] == "expert_aiml_arxiv_0000"
    assert rec["domain"] == "ai_machine_learning"
    assert rec["expert_tier"] == "E1"
    assert rec["license"] == "arXiv non-exclusive license"
    assert rec["provenance"]["original_id"] == "2607.28608v1"
    assert rec["source"]["url"] == "https://arxiv.org/abs/2607.28608v1"
    assert rec["metadata"]["model_generated"] is False
    assert rec["metadata"]["subdomains"]  # non-empty
    score_record(rec)
    assert validate_schema(rec) == []
    assert validate_provenance(rec) == []


def test_arxiv_retraction_check_marker_detection(monkeypatch):
    def fake_get(url: str, timeout: int = 30) -> str:
        return "This paper has been retracted. Please see the retraction notice."
    monkeypatch.setattr("expert_pipeline.adapters.arxiv._http_get", fake_get)
    result = _check_retraction("https://arxiv.org/abs/0000.00000")
    assert result["checked"] is True
    assert "retracted" in result["retraction_markers"]


def test_arxiv_retraction_check_clean(monkeypatch):
    def fake_get(url: str, timeout: int = 30) -> str:
        return "We present a new method."
    monkeypatch.setattr("expert_pipeline.adapters.arxiv._http_get", fake_get)
    result = _check_retraction("https://arxiv.org/abs/0000.00001")
    assert result["checked"] is True
    assert result["retraction_markers"] == []


def test_arxiv_iter_raw_paginates_and_limits(monkeypatch):
    """iter_raw must distribute across categories and stop at the limit."""
    import expert_pipeline.adapters.arxiv as axmod

    calls: list[tuple[str, int]] = []

    def fake_query(category, start=0, max_results=500):
        calls.append((category, start))
        # Each page: 2 primary-category entries for this category + 1 other
        entries = []
        for i in range(2):
            entries.append({
                "arxiv_id": f"{category.replace('.', '')}-{start}-{i}",
                "title": f"Paper {category} {start} {i}",
                "abstract": "We propose a method with sufficient length to pass the quality gate and provide real content for the abstract field of this synthetic test record.",
                "published": "2026-07-30T17:59:56Z",
                "updated": "2026-07-30T18:00:00Z",
                "primary_category": category,
                "categories": [category],
                "authors": ["Jane Doe"],
                "comment": "",
                "doi": "",
                "journal_ref": "",
            })
        entries.append({
            "arxiv_id": "other-1", "title": "Other", "abstract": "other",
            "published": "2026-07-30T17:59:56Z", "updated": "2026-07-30T18:00:00Z",
            "primary_category": "hep-th", "categories": ["hep-th"],
            "authors": ["Other Author"], "comment": "", "doi": "", "journal_ref": "",
        })
        return entries

    monkeypatch.setattr(axmod, "_query_arxiv", fake_query)
    adapter = ArxivAdapter(accessed_at=ACCESSED)
    rows = list(adapter.iter_raw(limit=6))  # ceil(6/4)=2 per category
    assert len(rows) == 6
    cats = [r["primary_category"] for r in rows]
    assert cats.count("cs.LG") == 2
    assert cats.count("cs.CL") == 2
    assert cats.count("cs.AI") == 2
    assert cats.count("stat.ML") == 0  # limit reached before stat.ML
    # pagination: the cs.LG page did NOT advance to start=500 (enough on page 0)
    assert ("cs.LG", 0) in calls
    assert ("cs.LG", 500) not in calls
