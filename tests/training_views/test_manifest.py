#!/usr/bin/env python3
"""Tests for manifest.py."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

ROOT = pytest.importorskip("pathlib").Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
import sys

sys.path.insert(0, str(SRC))

from atlas_training.training_views.manifest import TrainingViewManifest  # noqa: E402


def _records():
    return [{"record_id": f"rec_{i}", "content": str(i)} for i in range(5)]


def test_create_manifest_schema():
    m = TrainingViewManifest()
    manifest = m.create(
        view_id="v1",
        source_release="v0.1",
        source_records=10,
        quality_threshold=7,
        filter_counts={
            "quality_below": 2,
            "license_denied": 1,
            "lifecycle_invalid": 0,
            "eligibility_missing": 0,
            "pending_review": 0,
            "rejected": 0,
            "lineage_incomplete": 0,
        },
        records=_records(),
    )
    assert manifest["training_view_id"] == "v1"
    assert manifest["source_records"] == 10
    assert manifest["checksum"]["algorithm"] == "SHA-256"
    assert manifest["checksum"]["manifest"] != "__PENDING__"
    assert "created_at" in manifest


def test_manifest_deterministic_checksum():
    m = TrainingViewManifest()
    recs = _records()
    first = m.create(
        view_id="v1",
        source_release="v0.1",
        source_records=5,
        quality_threshold=7,
        filter_counts={},
        records=recs,
    )
    second = m.create(
        view_id="v1",
        source_release="v0.1",
        source_records=5,
        quality_threshold=7,
        filter_counts={},
        records=recs,
    )
    assert first["checksum"]["records"] == second["checksum"]["records"]
    assert first["checksum"]["manifest"] == second["checksum"]["manifest"]
    assert first["checksum"]["manifest"] != "__PENDING__"


def test_manifest_timestamp_does_not_leak_into_checksum():
    m = TrainingViewManifest()
    recs = _records()
    first = m.create(
        view_id="v1",
        source_release="v0.1",
        source_records=5,
        quality_threshold=7,
        filter_counts={},
        records=recs,
    )
    second = m.create(
        view_id="v1",
        source_release="v0.1",
        source_records=5,
        quality_threshold=7,
        filter_counts={},
        records=recs,
    )
    assert first["created_at"] != second["created_at"]
    assert first["checksum"]["manifest"] == second["checksum"]["manifest"]


def test_manifest_regeneration_from_files_is_deterministic(tmp_path):
    train = tmp_path / "train.jsonl"
    eval_ = tmp_path / "eval.jsonl"
    meta = tmp_path / "meta.json"
    train_records = [{"record_id": f"t_{i}", "text": str(i)} for i in range(10)]
    eval_records = [{"record_id": f"e_{i}", "text": str(i)} for i in range(10, 12)]
    train.write_text("\n".join(json.dumps(r, sort_keys=True) for r in train_records) + "\n", encoding="utf-8")
    eval_.write_text("\n".join(json.dumps(r, sort_keys=True) for r in eval_records) + "\n", encoding="utf-8")
    meta.write_text(
        json.dumps({"view_id": "v1", "source_release": "v0.1", "quality_threshold": 7}, ensure_ascii=False),
        encoding="utf-8",
    )

    builder = TrainingViewManifest()
    manifest_a = builder.create(
        view_id="v1",
        source_release="v0.1",
        source_records=len(train_records) + len(eval_records),
        quality_threshold=7,
        filter_counts={},
        records=train_records + eval_records,
    )
    manifest_b = builder.create(
        view_id="v1",
        source_release="v0.1",
        source_records=len(train_records) + len(eval_records),
        quality_threshold=7,
        filter_counts={},
        records=train_records + eval_records,
    )

    assert manifest_a["checksum"]["records"] == manifest_b["checksum"]["records"]
    assert manifest_a["checksum"]["manifest"] == manifest_b["checksum"]["manifest"]
    assert manifest_a["created_at"] != manifest_b["created_at"]
    assert manifest_a["checksum"]["records"] == builder._records_hash(train_records + eval_records)


def test_reconciliation_identical_materialization_is_deterministic(tmp_path):
    train = tmp_path / "train.jsonl"
    eval_ = tmp_path / "eval.jsonl"
    config = {
        "view_id": "recon-300m",
        "source_release": "recon-v0.1",
        "quality_threshold": 7,
        "filter_counts": {
            "quality_below": 0,
            "license_denied": 0,
            "lifecycle_invalid": 0,
            "eligibility_missing": 0,
            "pending_review": 0,
            "rejected": 0,
            "lineage_incomplete": 0,
        },
    }
    train_records = [{"record_id": f"t_{i}", "text": str(i)} for i in range(20)]
    eval_records = [{"record_id": f"e_{i}", "text": str(i)} for i in range(20, 25)]
    train.write_text("\n".join(json.dumps(r, sort_keys=True) for r in train_records) + "\n", encoding="utf-8")
    eval_.write_text("\n".join(json.dumps(r, sort_keys=True) for r in eval_records) + "\n", encoding="utf-8")

    builder = TrainingViewManifest()
    run_a = builder.create(
        view_id=config["view_id"],
        source_release=config["source_release"],
        source_records=len(train_records) + len(eval_records),
        quality_threshold=config["quality_threshold"],
        filter_counts=config["filter_counts"],
        records=train_records + eval_records,
    )
    run_b = builder.create(
        view_id=config["view_id"],
        source_release=config["source_release"],
        source_records=len(train_records) + len(eval_records),
        quality_threshold=config["quality_threshold"],
        filter_counts=config["filter_counts"],
        records=train_records + eval_records,
    )

    train_checksum_a = builder._records_hash(train_records)
    train_checksum_b = builder._records_hash(train_records)
    eval_checksum_a = builder._records_hash(eval_records)
    eval_checksum_b = builder._records_hash(eval_records)

    assert train_checksum_a == train_checksum_b
    assert eval_checksum_a == eval_checksum_b
    assert run_a["checksum"]["manifest"] == run_b["checksum"]["manifest"]
    assert run_a["checksum"]["records"] == run_b["checksum"]["records"]
    assert run_a["created_at"] != run_b["created_at"]


def test_full_materialization_run_is_deterministic(tmp_path):
    import hashlib as _hashlib
    import importlib.util
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "phase2b_materialize.py"
    spec = importlib.util.spec_from_file_location("phase2b_materialize", script)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    run_a_root = tmp_path / "run_a"
    run_b_root = tmp_path / "run_b"
    run_a_root.mkdir()
    run_b_root.mkdir()
    module.OUTPUT_ROOT = run_a_root  # type: ignore[attr-defined]
    assert module.main() == 0
    module.OUTPUT_ROOT = run_b_root  # type: ignore[attr-defined]
    assert module.main() == 0

    for view_id in ("code_300m_v0.1", "math_300m_v0.1", "aiml_300m_v0.1"):
        for artifact in ("train.jsonl", "eval.jsonl", "manifest.json"):
            path_a = run_a_root / view_id / artifact
            path_b = run_b_root / view_id / artifact
            assert path_a.exists()
            assert path_b.exists()
            assert (
                _hashlib.sha256(path_a.read_bytes()).hexdigest()
                == _hashlib.sha256(path_b.read_bytes()).hexdigest()
            )
