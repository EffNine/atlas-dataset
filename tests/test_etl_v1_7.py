#!/usr/bin/env python3
"""Tests for Atlas ETL v1.7 — Extract → Normalize → Clean."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))

from etl.types import RawRecord  # noqa: E402
from etl.normalizer import normalize_record, to_atlas_record  # noqa: E402
from etl.cleaners import run_cleaners  # noqa: E402
from etl.extractors.json_extractors import JsonlExtractor  # noqa: E402
from etl.extractors.text_extractors import HtmlExtractor, MarkdownExtractor  # noqa: E402
from etl.pipeline import run_etl_for_source  # noqa: E402
from etl.extract_agent import ExtractAgent  # noqa: E402
from downloader.cache import CacheManager  # noqa: E402
from automation.base_agent import AgentStatus  # noqa: E402


@pytest.fixture()
def atlas_root(tmp_path: Path) -> Path:
    root = tmp_path / "atlas"
    (root / "raw" / ".cache").mkdir(parents=True)
    (root / "metadata").mkdir()
    (root / "curated").mkdir()
    (root / "review_queue").mkdir()
    (root / "training_views").mkdir()
    (root / "raw" / "external").mkdir(parents=True)
    return root


def test_jsonl_extract_normalize_clean(tmp_path: Path):
    path = tmp_path / "sample.jsonl"
    rows = [
        {"id": "a1", "question": "What is 2+2?", "answer": "4"},
        {"id": "a2", "question": "What is 2+2?", "answer": "4"},  # dup
        {"id": "a3", "question": "Email me at test@example.com", "answer": "ok"},
        {"id": "a4", "question": "", "answer": ""},  # malformed
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    raw = JsonlExtractor().extract(path, source_ref="test:jsonl")
    assert len(raw) == 4

    canonical = [
        normalize_record(r, source_id="t1", source_name="test", license="MIT",
                         category="06_science_engineering", subcategory="mathematics")
        for r in raw
    ]
    assert all(c.record_type == "qa" for c in canonical)

    cleaned = run_cleaners(canonical)
    assert cleaned.stats["dropped"] >= 2  # dup + malformed
    assert cleaned.stats["output"] >= 1
    # email redacted, not dropped
    email_recs = [c for c in cleaned.records if "example.com" in repr(c.content) or "REDACTED_EMAIL" in repr(c.content)]
    assert email_recs
    assert "REDACTED_EMAIL" in repr(email_recs[0].content)

    atlas = to_atlas_record(cleaned.records[0], seq=1)
    assert atlas["verified"] is False
    assert atlas["source"]["license"] == "MIT"
    assert len(atlas["messages"]) >= 2


def test_html_and_markdown_extractors(tmp_path: Path):
    html = tmp_path / "page.html"
    html.write_text("<html><head><title>Doc</title></head><body><p>Hello Atlas</p></body></html>", encoding="utf-8")
    md = tmp_path / "guide.md"
    md.write_text("# Intro\n\nHello\n\n## Next\n\nWorld\n", encoding="utf-8")

    html_recs = HtmlExtractor().extract(html)
    assert html_recs[0].content["title"] == "Doc"
    assert "Hello Atlas" in html_recs[0].content["text"]

    md_recs = MarkdownExtractor().extract(md)
    assert len(md_recs) >= 2


def test_etl_pipeline_from_cache(atlas_root: Path):
    # Seed registry + cache a JSONL as if downloaded
    (atlas_root / "metadata" / "source_registry.json").write_text(
        json.dumps({
            "sources": [{
                "id": "t1",
                "name": "test/qa",
                "url": "https://example.com/qa",
                "license": "MIT",
                "category": "06_science_engineering",
                "subcategory_hint": "mathematics",
                "status": "accepted",
            }]
        }),
        encoding="utf-8",
    )
    cache = CacheManager(atlas_root)
    payload = "\n".join(
        json.dumps({
            "question": f"What is the result of problem number {i} in detail?",
            "answer": f"The detailed answer for problem {i} is {i * 2}.",
        })
        for i in range(5)
    ).encode("utf-8") + b"\n"
    entry = cache.put_bytes(
        "huggingface:t1:data.jsonl",
        payload,
        adapter="huggingface",
        metadata={"filename": "data.jsonl"},
    )
    (atlas_root / "metadata" / "download_logs").mkdir(parents=True)
    (atlas_root / "metadata" / "download_logs" / "t1.download.json").write_text(
        json.dumps({
            "source_id": "t1",
            "adapter": "huggingface",
            "status": "downloaded",
            "entries": [entry.to_dict()],
            "files": [{"filename": "data.jsonl", "source_ref": entry.source_ref}],
        }),
        encoding="utf-8",
    )

    result = run_etl_for_source(atlas_root, "t1", limit=3)
    assert result.status == "passed"
    assert result.extracted == 3
    assert result.cleaned == 3
    assert result.atlas_records == 3
    out = Path(result.output_dir)
    assert (out / "extracted.jsonl").exists()
    assert (out / "cleaned.jsonl").exists()
    assert (out / "atlas_staging.jsonl").exists()
    assert (out / "report.json").exists()
    # immutable trees untouched
    assert list((atlas_root / "curated").iterdir()) == []
    assert list((atlas_root / "raw" / "external").iterdir()) == []


def test_extract_agent(atlas_root: Path):
    (atlas_root / "metadata" / "source_registry.json").write_text(
        json.dumps({"sources": [{"id": "t1", "name": "t", "license": "MIT",
                                 "category": "01_foundation", "subcategory_hint": "general"}]}),
        encoding="utf-8",
    )
    cache = CacheManager(atlas_root)
    entry = cache.put_bytes(
        "documentation:t1",
        b"<html><title>T</title><body><p>Content here for atlas</p></body></html>",
        adapter="documentation",
        metadata={"filename": "index.html"},
    )
    (atlas_root / "metadata" / "download_logs").mkdir()
    (atlas_root / "metadata" / "download_logs" / "t1.download.json").write_text(
        json.dumps({"source_id": "t1", "entries": [entry.to_dict()], "files": []}),
        encoding="utf-8",
    )
    agent = ExtractAgent(atlas_root, config={"source_ids": ["t1"]})
    result = agent.execute()
    assert result.status == AgentStatus.PASSED
    assert result.data["totals"]["cleaned"] >= 1
