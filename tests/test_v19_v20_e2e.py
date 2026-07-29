#!/usr/bin/env python3
"""Tests for Atlas v1.9 (parallel, incremental) and v2.0 (e2e pipeline)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))

from parallel import ParallelRunner, JobResult  # noqa: E402
from incremental import IncrementalState  # noqa: E402
from e2e_pipeline import E2EPipeline  # noqa: E402
from downloader.cache import CacheManager  # noqa: E402
from automation.base_agent import AgentStatus  # noqa: E402


# ── Parallel runner ───────────────────────────────────────────────────


def test_parallel_runner_all_pass():
    runner = ParallelRunner(max_workers=2)
    results = runner.run(lambda sid: {"status": "passed", "sid": sid}, ["a", "b", "c"])
    assert results.passed == 3
    assert results.failed == 0


def test_parallel_runner_one_fails():
    def job(sid):
        if sid == "b":
            raise RuntimeError("boom")
        return {"status": "passed"}

    runner = ParallelRunner(max_workers=2)
    results = runner.run(job, ["a", "b", "c"])
    assert results.failed == 1
    assert results.passed == 2
    failed = [r for r in results.results if r.status == "failed"]
    assert failed[0].source_id == "b"
    assert "boom" in failed[0].error


def test_parallel_runner_serial_fallback():
    order = []
    runner = ParallelRunner(max_workers=1)
    runner.run(lambda sid: order.append(sid) or {"status": "passed"}, ["x", "y", "z"])
    assert order == ["x", "y", "z"]


def test_parallel_runner_empty():
    runner = ParallelRunner()
    results = runner.run(lambda sid: {"status": "passed"}, [])
    assert results.passed == 0


# ── Incremental state ─────────────────────────────────────────────────


def test_incremental_mark_and_check(tmp_path: Path):
    state = IncrementalState(tmp_path)
    assert not state.is_done("s1", "etl")
    state.mark_done("s1", "etl", checksum="abc123")
    assert state.is_done("s1", "etl")
    assert state.is_done("s1", "etl", checksum="abc123")
    assert not state.is_done("s1", "etl", checksum="wrong")


def test_incremental_pending(tmp_path: Path):
    state = IncrementalState(tmp_path)
    state.mark_done("s1", "etl")
    state.mark_done("s2", "etl")
    pending = state.pending_sources("etl", ["s1", "s2", "s3"])
    assert pending == ["s3"]


def test_incremental_invalidate(tmp_path: Path):
    state = IncrementalState(tmp_path)
    state.mark_done("s1", "etl")
    state.invalidate("s1", "etl")
    assert not state.is_done("s1", "etl")


def test_incremental_persists(tmp_path: Path):
    state1 = IncrementalState(tmp_path)
    state1.mark_done("s1", "download", checksum="x")
    state2 = IncrementalState(tmp_path)
    assert state2.is_done("s1", "download", checksum="x")


def test_incremental_status_report(tmp_path: Path):
    state = IncrementalState(tmp_path)
    state.mark_done("s1", "etl")
    report = state.status_report()
    assert "s1" in report["sources"]
    assert report["sources"]["s1"]["etl"] is True
    assert report["sources"]["s1"]["download"] is False


# ── E2E pipeline (dry-run) ────────────────────────────────────────────


@pytest.fixture()
def atlas_root(tmp_path: Path) -> Path:
    root = tmp_path / "atlas"
    for d in ["raw/.cache", "metadata/acquisition_logs", "metadata/download_logs",
               "metadata/etl/c1", "curated", "configs/formatting"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    # Templates
    src = ROOT / "configs" / "formatting" / "templates.json"
    (root / "configs" / "formatting" / "templates.json").write_text(
        src.read_text(encoding="utf-8"), encoding="utf-8"
    )
    # Acquisition log for c1
    (root / "metadata" / "acquisition_logs" / "c1.acquisition.json").write_text(
        json.dumps({"source_id": "c1", "status": "acquired"}), encoding="utf-8"
    )
    # Registry
    (root / "metadata" / "source_registry.json").write_text(
        json.dumps({"sources": [{"id": "c1", "name": "openai/gsm8k",
                                 "url": "https://huggingface.co/datasets/openai/gsm8k",
                                 "license": "MIT", "category": "06_science_engineering",
                                 "subcategory_hint": "mathematics", "status": "accepted"}]}),
        encoding="utf-8",
    )
    return root


def test_e2e_dry_run(atlas_root: Path):
    agent = E2EPipeline(
        atlas_root,
        config={
            "version": "v0.3-dry",
            "dry_run": True,
            "source_ids": ["c1"],
            "max_workers": 2,
        },
    )
    result = agent.execute()
    assert result.status == AgentStatus.PASSED
    data = result.data
    assert data["dry_run"] is True
    assert "download" in data["stages_run"]
    assert "etl" in data["stages_run"]
    # dry-run = planned dicts, not real writes
    assert data["stage_results"]["download"].get("status") or data["stage_results"]["download"].get("planned") is not None
    assert (atlas_root / "metadata" / "e2e_reports" / "v0.3-dry.json").exists()


def test_e2e_live_with_seeded_etl(atlas_root: Path):
    # Seed cleaned ETL artifacts so we can skip download+etl
    rows = [
        {"id": f"r{i}", "source": "gsm8k", "license": "MIT",
         "content": {"question": f"What is {i} times 3?", "answer": f"<<{i}*3={i*3}>>\n#### {i*3}"},
         "created_at": "2026-07-29T00:00:00+00:00", "lineage": ["extract:parquet"],
         "metadata": {"category": "06_science_engineering", "subcategory": "mathematics"},
         "source_id": "c1", "record_type": "qa"}
        for i in range(10)
    ]
    (atlas_root / "metadata" / "etl" / "c1" / "cleaned.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    (atlas_root / "metadata" / "etl" / "c1" / "atlas_staging.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )

    agent = E2EPipeline(
        atlas_root,
        config={
            "version": "v0.3-live",
            "dry_run": False,
            "source_ids": ["c1"],
            "skip_download": True,
            "skip_etl": True,
            "max_workers": 2,
            "limit": 10,
        },
    )
    result = agent.execute()
    assert result.status == AgentStatus.PASSED
    assert (atlas_root / "metadata" / "release_bundles" / "v0.3-live" / "manifest.json").exists()
    assert (atlas_root / "metadata" / "views" / "v0.3-live" / "qwen" / "train.jsonl").exists()
    # Incremental: re-run should mark release as done
    state = IncrementalState(atlas_root)
    assert state.is_done("c1", "release")


def test_e2e_incremental_skips_done(atlas_root: Path):
    state = IncrementalState(atlas_root)
    state.mark_done("c1", "download")
    state.mark_done("c1", "etl")
    state.mark_done("c1", "transform")

    events: list[str] = []
    agent = E2EPipeline(
        atlas_root,
        config={
            "version": "v0.3-inc",
            "dry_run": True,
            "source_ids": ["c1"],
        },
    )
    result = agent.execute()
    assert result.status == AgentStatus.PASSED
    # Download + ETL show as planned/skipped because dry_run
    dl = result.data["stage_results"]["download"]
    # Since all done, pending should be []
    assert dl.get("planned") == [] or dl.get("status") == "skipped"
