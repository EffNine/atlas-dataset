#!/usr/bin/env python3
"""Tests for the expert pipeline runner (dry-run, no-overwrite, report)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import expert_pipeline.runner as runner
from expert_pipeline.adapters.base import SourceAdapter

from conftest import swe_instance

ACCESSED = "2026-08-02"


class _FakeSweAdapter(SourceAdapter):
    """Offline SWE adapter: two synthetic rows, no network."""

    source_id = "expert-swe-001"
    source_name = "SWE-bench verified"
    source_url = "https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified"
    source_license = "MIT"
    domain = "software_engineering"
    expert_tier = "E2"
    id_prefix = "expert_swe"

    def iter_raw(self, limit=None):
        for i in range(limit if limit is not None else 2):
            yield swe_instance(instance_id=f"fake__fake-{i}")

    def to_record(self, raw, idx):
        from expert_pipeline.adapters.swebench import SwebenchAdapter

        return SwebenchAdapter(accessed_at=ACCESSED).to_record(raw, idx)


def test_runner_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ADAPTERS", {"swebench": _FakeSweAdapter})
    monkeypatch.setattr(runner, "MANIFEST_PATH", tmp_path / "manifest.json")
    monkeypatch.setattr(runner, "RECORDS_PATH", tmp_path / "records.jsonl")
    monkeypatch.setattr(runner, "QUALITY_REPORT_PATH", tmp_path / "quality.json")

    report = runner.run_pilot(sources=["swebench"], limits={"swebench": 2},
                              dry_run=True, accessed_at=ACCESSED)
    assert report["dry_run"] is True
    assert report["records_checked"] == 2
    assert not (tmp_path / "manifest.json").exists()
    assert not (tmp_path / "records.jsonl").exists()
    assert not (tmp_path / "quality.json").exists()


def test_runner_writes_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ADAPTERS", {"swebench": _FakeSweAdapter})
    monkeypatch.setattr(runner, "MANIFEST_PATH", tmp_path / "manifest.json")
    monkeypatch.setattr(runner, "RECORDS_PATH", tmp_path / "records.jsonl")
    monkeypatch.setattr(runner, "QUALITY_REPORT_PATH", tmp_path / "quality.json")

    report = runner.run_pilot(sources=["swebench"], limits={"swebench": 2},
                              dry_run=False, accessed_at=ACCESSED)
    assert report["dry_run"] is False
    records = [json.loads(l) for l in (tmp_path / "records.jsonl").read_text().splitlines()]
    assert len(records) == 2
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["total_records"] == 2
    quality = json.loads((tmp_path / "quality.json").read_text())
    assert quality["schema"]["pass_rate"] == 1.0
    assert quality["quality"]["gate"]["KEEP"] == 2


def test_runner_tagged_output_paths(tmp_path, monkeypatch):
    """run_pilot with explicit paths writes the batch to those exact files
    and the manifest records_file points at them."""
    monkeypatch.setattr(runner, "ADAPTERS", {"swebench": _FakeSweAdapter})
    records_path = tmp_path / "records_batch.jsonl"
    manifest_path = tmp_path / "manifest_batch.json"

    report = runner.run_pilot(sources=["swebench"], limits={"swebench": 2},
                              dry_run=False, accessed_at=ACCESSED,
                              records_path=records_path,
                              manifest_path=manifest_path,
                              report_path=tmp_path / "quality_batch.json")
    assert report["dry_run"] is False
    assert records_path.exists() and manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["records_file"] == str(records_path)


def test_resolve_output_paths():
    from expert_pipeline.constants import MANIFEST_PATH, QUALITY_REPORT_PATH, RECORDS_PATH

    assert runner._resolve_output_paths(None) == (
        RECORDS_PATH, MANIFEST_PATH, QUALITY_REPORT_PATH)
    rec, man, rep = runner._resolve_output_paths("architecture-v0.1")
    assert rec.name == "records_atlas_expert_architecture-v0.1.jsonl"
    assert man.name == "manifest_atlas_expert_architecture-v0.1.json"
    assert rep.name == "quality_atlas_expert_architecture-v0.1.json"


def test_runner_refuses_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ADAPTERS", {"swebench": _FakeSweAdapter})
    records_path = tmp_path / "records.jsonl"
    records_path.write_text("existing\n")
    monkeypatch.setattr(runner, "MANIFEST_PATH", tmp_path / "manifest.json")
    monkeypatch.setattr(runner, "RECORDS_PATH", records_path)
    monkeypatch.setattr(runner, "QUALITY_REPORT_PATH", tmp_path / "quality.json")

    with pytest.raises(FileExistsError):
        runner.run_pilot(sources=["swebench"], dry_run=False, accessed_at=ACCESSED)
    # existing file untouched
    assert records_path.read_text() == "existing\n"


def test_runner_unknown_source_rejected():
    with pytest.raises(ValueError):
        runner.run_pilot(sources=["nope"], dry_run=True)
