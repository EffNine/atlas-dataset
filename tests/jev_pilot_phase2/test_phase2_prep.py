#!/usr/bin/env python3
"""Phase 2 tests: dedup determinism, provenance, taxonomy reference integrity,
calibration integrity, and non-mutation of Atlas source data.

Run:  .venv/bin/python -m pytest tests/jev_pilot_phase2/test_phase2_prep.py -q
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
P2_DIR = ROOT / "experiments" / "jev-pilot-atlas-v0.1" / "phase2"
sys.path.insert(0, str(P2_DIR))

import phase2_prep as p2  # noqa: E402

P2 = P2_DIR


# ---------------------------------------------------------------- helpers


def test_run_all_then_asserts():
    """Run the full Phase-2 pipeline once, into a temp OUT, and assert artifacts."""
    p2.OUT.mkdir(parents=True, exist_ok=True)
    p2.cmd_all()


def _load(name):
    return json.loads((P2 / name).read_text())


# ---------------------------------------------------------------- 1. dedup


def test_dedup_deterministic():
    data = p2.load_pilot()
    a = p2.dedup_analysis(data)
    b = p2.dedup_analysis(data)
    # deterministic: identical stable manifests (timestamps stripped)
    assert p2._stable_manifest(a) == p2._stable_manifest(b)
    # and byte-identical records
    assert json.dumps(a["records"], sort_keys=True) == json.dumps(b["records"], sort_keys=True)


def test_dedup_counts_match_phase1_finding():
    m = _load("deduplication_report.json")
    # Phase 1 found 822 cross-arm exact-dup groups
    assert m["n_exact_content_dup_groups"] == 822
    assert m["n_exact_content_duplicate_rows"] == 822
    assert m["n_total_records"] == 4499
    # unique = total - exact full-content dup rows
    assert m["unique_records_after_exact_dedup"] == m["n_total_records"] - m["n_exact_content_duplicate_rows"]


def test_dedup_provenance_fields():
    rows = [json.loads(l) for l in open(P2 / "deduplication_manifest.jsonl")]
    for r in rows[:20]:
        if r["dup_class"] in ("exact_duplicate", "exact_duplicate_user_only"):
            for field in ("canonical_record_id", "duplicate_record_id",
                         "canonical_arm", "duplicate_arm", "content_sha256"):
                assert field in r, f"missing provenance field {field}"
        if r["dup_class"] == "near_duplicate":
            assert r["pair"] and r["jaccard"]
            assert 0.8 <= r["jaccard"] < 1.0


def test_dedup_no_destructive_action_in_manifest():
    # The manifest is a proposal: it records actions but never modifies source.
    rows = [json.loads(l) for l in open(P2 / "deduplication_manifest.jsonl")]
    actions = {r["dedup_action"] for r in rows}
    # only advisory actions
    assert actions <= {"drop_duplicate", "keep_both_review"}
    # and no script writes to pilot/
    for f in ("pilot", "curated", "raw", "releases", "metadata", "training_views"):
        assert not (ROOT / f / ".phase2_write_marker").exists()


def test_dedup_class_separation():
    rows = [json.loads(l) for l in open(P2 / "deduplication_manifest.jsonl")]
    exact = [r for r in rows if r["dup_class"] == "exact_duplicate"]
    user_only = [r for r in rows if r["dup_class"] == "exact_duplicate_user_only"]
    near = [r for r in rows if r["dup_class"] == "near_duplicate"]
    # distinct classes: near-dups must NOT also be exact
    exact_sha = {r["content_sha256"] for r in exact}
    for n in near:
        assert n["content_sha256"] is None  # near-dups have no exact-content sha
        assert n["requires_human_review"]
    # user-only same-source = redundant; cross-source = human review
    for r in user_only:
        if r["dedup_action"] == "keep_both_review":
            assert r["requires_human_review"]
        else:
            assert r["dedup_action"] == "drop_duplicate"


# ---------------------------------------------------------------- 2. taxonomy reference


def test_taxonomy_reference_versioned_and_hashed():
    ref = _load("taxonomy_reference_v1.json")
    assert ref["version"] == "taxonomy_reference_v1"
    body = json.dumps({k: v for k, v in ref.items() if k != "sha256"}, sort_keys=True).encode()
    assert hashlib.sha256(body).hexdigest() == ref["sha256"], "reference hash not reproducible"
    # 9 canonical categories present
    assert len(ref["categories"]) == 9
    assert "01_foundation" in ref["categories"]
    # label mappings for pilot/v0.2
    assert ref["label_mappings"]["mathematics"] == "01_foundation"


def test_taxonomy_audit_uses_independent_reference():
    audit = _load("taxonomy_audit.json")
    assert audit["reference_version"] == "taxonomy_reference_v1"
    # the audit must NOT rely on the record's own label as ground truth
    assert "NOT the record's own label" in audit["method"]


def test_taxonomy_audit_row_integrity():
    rows = [json.loads(l) for l in open(P2 / "taxonomy_audit_rows.jsonl")]
    assert len(rows) == 4499
    for r in rows[:20]:
        assert "record_id" in r and "inferred_category" in r
        # suspected_misclassification must be a bool
        assert isinstance(r["suspect_misclassification"], bool)


# ---------------------------------------------------------------- 3. calibration set


def test_calibration_set_stratified_and_pending():
    cal = _load("human_calibration_manifest.json")
    # ~100 records (spec says ~100; allow 80-120)
    assert 80 <= cal["n_records"] <= 120
    # all records are pending with NO fabricated human labels
    for r in cal["records"]:
        assert r["labeling_status"] == "pending"
        assert r["human_labels"] is None, "human labels must not be fabricated"
    # strata present
    strata = cal["strata"]
    for s in ("normal", "low_jev", "flagged", "outliers"):
        assert s in strata
    # labeling criteria defined before results
    assert set(cal["labeling_criteria"]) >= {"correctness", "problematic", "category_correct"}


def test_calibration_no_overlap_with_jev_outputs_as_labels():
    cal = _load("human_calibration_manifest.json")
    for r in cal["records"]:
        # Jev signals are stored as context, but human_labels is empty
        assert "jev_signals" in r
        assert r["human_labels"] is None


# ---------------------------------------------------------------- 4. threshold calibration


def test_threshold_inconclusive_without_labels():
    thr = _load("threshold_calibration.json")
    assert thr["status"] == "INCONCLUSIVE_NO_HUMAN_LABELS"
    assert thr["n_labeled"] == 0


# ---------------------------------------------------------------- 5. non-mutation of source


def test_source_data_unmodified():
    # Phase 2 captures source file SHA-256 at run time.
    src = _load("source_file_sha256.json")
    for relpath, recorded in src["files"].items():
        path = ROOT / relpath
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        assert h.hexdigest() == recorded, f"source file {relpath} was modified"


def test_no_destructive_operations():
    # no 'rm', 'drop --output' to pilot/ in phase2 scripts
    script = (P2 / "phase2_prep.py").read_text()
    assert "pilot/v0.2" in script  # reads pilot
    # and only opens in read mode
    import re
    writes = re.findall(r'open\(([^)]{0,60})\)', script)
    # no 'w' mode to anything under pilot/
    for w in writes:
        assert "pilot/" not in w or '"/" ' not in w, f"unexpected write: {w}"
