#!/usr/bin/env python3
"""Tests for Atlas v1.8 Transform → Views → Release Builder."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))

from transform import run_transform, transform_record  # noqa: E402
from etl.types import CanonicalRecord  # noqa: E402
from view_builder import build_views  # noqa: E402
from release_builder import build_release  # noqa: E402
from publish_agent import PublishAgent  # noqa: E402
from automation.base_agent import AgentStatus  # noqa: E402


@pytest.fixture()
def atlas_root(tmp_path: Path) -> Path:
    root = tmp_path / "atlas"
    (root / "metadata" / "etl" / "c1").mkdir(parents=True)
    (root / "curated").mkdir()
    (root / "configs" / "formatting").mkdir(parents=True)
    # copy templates from real repo
    src = ROOT / "configs" / "formatting" / "templates.json"
    (root / "configs" / "formatting" / "templates.json").write_text(
        src.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return root


def _seed_cleaned(root: Path, n: int = 20) -> None:
    rows = []
    for i in range(n):
        rows.append({
            "id": f"c1_row_{i:04d}",
            "source": "openai/gsm8k",
            "license": "MIT",
            "content": {
                "question": f"What is {i}+{i}?",
                "answer": f"Step: <<{i}+{i}={i*2}>>\n#### {i*2}",
            },
            "created_at": "2026-07-29T00:00:00+00:00",
            "lineage": ["extract:parquet", "normalize:v1.7", "clean:dedup"],
            "metadata": {
                "category": "06_science_engineering",
                "subcategory": "mathematics",
                "source_url": "https://huggingface.co/datasets/openai/gsm8k",
            },
            "source_id": "c1",
            "record_type": "qa",
        })
    path = root / "metadata" / "etl" / "c1" / "cleaned.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_transform_qa_emits_reasoning_and_knowledge():
    rec = CanonicalRecord(
        id="x1",
        source="gsm8k",
        license="MIT",
        content={"question": "2+2?", "answer": "<<2+2=4>>\n#### 4"},
        created_at="t",
        lineage=[],
        metadata={"category": "06_science_engineering", "subcategory": "mathematics"},
        source_id="c1",
        record_type="qa",
    )
    out = transform_record(rec)
    types = {t.training_type for t in out}
    assert "reasoning" in types
    assert "knowledge" in types


def test_publish_pipeline(atlas_root: Path):
    _seed_cleaned(atlas_root, n=20)
    # Point convert_format templates at tmp root by writing under cwd-relative... 
    # convert_format uses ROOT=parents[1] of convert_format.py (real repo). That's fine.

    agent = PublishAgent(
        atlas_root,
        config={
            "source_ids": ["c1"],
            "version": "v0.3-test",
            "models": ["qwen", "llama", "deepseek"],
            "allow_staging": True,
            "limit": 20,
        },
    )
    # Monkeypatch convert_format templates path is real repo — OK
    result = agent.execute()
    assert result.status == AgentStatus.PASSED
    assert (atlas_root / "metadata" / "etl" / "c1" / "transformed.jsonl").exists()
    assert (atlas_root / "metadata" / "views" / "v0.3-test" / "qwen" / "train.jsonl").exists()
    assert (atlas_root / "metadata" / "release_bundles" / "v0.3-test" / "manifest.json").exists()
    assert (atlas_root / "metadata" / "release_bundles" / "v0.3-test" / "README.md").exists()
    # immutable
    assert list((atlas_root / "curated").iterdir()) == []


def test_production_views_blocked_without_approval(atlas_root: Path):
    _seed_cleaned(atlas_root, n=5)
    run_transform(atlas_root, "c1")
    result = build_views(
        atlas_root,
        version="v0.3-prod",
        source_ids=["c1"],
        allow_staging=False,
        curated_version=None,
    )
    # Without curated_version, allow_staging=False still loads staging then filters
    # Our build_views: if not allow_staging OR curated_version → filter production eligible
    assert result.status in {"blocked", "failed"}
