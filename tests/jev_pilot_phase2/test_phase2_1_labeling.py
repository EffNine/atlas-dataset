#!/usr/bin/env python3
"""Phase 2.1 tests: unique-record dedup, blinded package, two-labeler validation,
agreement math, adjudication, calibration HOLD/COMPUTED, and source non-mutation.

Run:  .venv/bin/python -m pytest tests/jev_pilot_phase2/test_phase2_1_labeling.py -q

All human labels in this file are SYNTHETIC fixtures in tmp dirs — never written
to phase2/human_labels/. Nothing here fabricates real calibration labels.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
P2_DIR = ROOT / "experiments" / "jev-pilot-atlas-v0.1" / "phase2"
sys.path.insert(0, str(P2_DIR))

import phase2_1_labeling as p21  # noqa: E402


def _manifest():
    return p21.load_manifest()


def _make_label(row: dict, labeler: str, correctness="yes", problematic="no",
                category="yes") -> dict:
    return {
        "schema_version": "human-label-v1",
        "record_id": row["record_id"],
        "arm": row["arm"],
        "content_sha256": row["content_sha256"],
        "labeler_id": labeler,
        "labeled_at": "2026-09-18T10:00:00+00:00",
        "criteria_version": "phase2-calibration-v1",
        "reference_version": "taxonomy_reference_v1",
        "blinded_to_jev": True,
        "labels": {"correctness": correctness, "problematic": problematic,
                   "category_correct": category},
    }


def _write(tmp: Path, row: dict, labeler: str, **kw) -> Path:
    obj = _make_label(row, labeler, **kw)
    p = tmp / f"{row['record_id']}__{labeler}.json"
    p.write_text(json.dumps(obj))
    return p


# ---------------------------------------------------------------- units


def test_unique_records_84_with_strata_preserved():
    units = p21.unique_records(_manifest())
    assert len(units) == 84
    # every manifest row is covered exactly once per stratum entry
    rows = _manifest()["records"]
    assert sum(len(u["strata"]) for u in units) == len(rows) == 96
    # the 9 known repeated ids carry >1 stratum
    multi = [u for u in units if len(u["strata"]) > 1]
    assert len(multi) == 9


def test_build_package_deterministic_and_blinded(tmp_path):
    a = p21.build_package(tmp_path / "a")
    b = p21.build_package(tmp_path / "b")
    assert a["n_unique_records"] == 84 == b["n_unique_records"]
    assert a["records"] == b["records"]
    assert a["blinded"] is True
    rec_files = sorted((tmp_path / "a" / "records").glob("*.json"))
    assert len(rec_files) == 84

    def keys_deep(o):
        found = set()
        if isinstance(o, dict):
            for k, v in o.items():
                found.add(k)
                found |= keys_deep(v)
        elif isinstance(o, list):
            for v in o:
                found |= keys_deep(v)
        return found

    for p in rec_files:
        obj = json.loads(p.read_text())
        # no Jev signal payload may appear anywhere in the blinded package:
        # scan keys precisely (the word 'jev' alone occurs in the blinding note)
        blob = json.dumps(obj).lower()
        for leak in ("jev_signals", "noul", "consistent_category", "training_value", "adherence"):
            assert leak not in blob, f"Jev leakage '{leak}' in {p.name}"
        assert "flags" not in keys_deep(obj), f"Jev 'flags' key in {p.name}"
        assert "strata" not in keys_deep(obj), f"stratum name would leak Jev's view in {p.name}"
        assert "messages" in obj and len(obj["messages"]) >= 2


def test_validate_accepts_good_label(tmp_path):
    m = _manifest()
    idx = p21.manifest_index(m)
    row = m["records"][0]
    obj = _make_label(row, "labeler-a")
    assert p21.validate_label(obj, idx, f"{row['record_id']}__labeler-a.json") == []


def test_validate_rejects_bad_labels(tmp_path):
    m = _manifest()
    idx = p21.manifest_index(m)
    row = m["records"][0]
    base = f"{row['record_id']}__labeler-a.json"

    bad_enum = _make_label(row, "labeler-a", correctness="maybe")
    assert any("correctness" in e for e in p21.validate_label(bad_enum, idx, base))

    bad_sha = _make_label(row, "labeler-a")
    bad_sha["content_sha256"] = "deadbeef:deadbeef"
    assert any("content_sha256" in e for e in p21.validate_label(bad_sha, idx, base))

    bad_arm = _make_label(row, "labeler-a")
    bad_arm["arm"] = "code" if row["arm"] != "code" else "math"
    assert any("arm" in e for e in p21.validate_label(bad_arm, idx, base))

    unblinded = _make_label(row, "labeler-a")
    unblinded["blinded_to_jev"] = False
    assert any("blinded_to_jev" in e for e in p21.validate_label(unblinded, idx, base))

    leaked = _make_label(row, "labeler-a")
    leaked["jev_signals"] = {"quality": 3.0}
    assert any("forbidden" in e for e in p21.validate_label(leaked, idx, base))

    unknown = _make_label(row, "labeler-a")
    unknown["record_id"] = "v2-nope-0000000000000000"
    assert any("unknown record_id" in e for e in p21.validate_label(unknown, idx, base))

    fname_mismatch = _make_label(row, "labeler-a")
    assert any("filename" in e for e in p21.validate_label(fname_mismatch, idx, "wrong_name.json"))

    bad_time = _make_label(row, "labeler-a")
    bad_time["labeled_at"] = "next Tuesday"
    assert any("labeled_at" in e for e in p21.validate_label(bad_time, idx, base))


def test_two_labeler_requirement_end_to_end(tmp_path):
    m = _manifest()
    rows = m["records"][:3]
    lab = tmp_path / "labels"
    lab.mkdir()
    for r in rows:
        _write(lab, r, "labeler-a")
    st = p21.validate_labels(labels_dir=lab, manifest=m)
    assert st["n_records_one_labeler"] == 3
    assert st["meets_two_labeler_requirement"] is False
    for r in rows:
        _write(lab, r, "labeler-b", correctness="no")  # disagree on purpose
    st = p21.validate_labels(labels_dir=lab, manifest=m)
    assert st["n_records_one_labeler"] == 0
    assert st["n_records_unlabeled"] == st["n_unique_records"] - 3
    assert st["labeler_ids_seen"] == ["labeler-a", "labeler-b"]
    assert st["violations"] == []


def test_agreement_math_known_kappa(tmp_path):
    m = _manifest()
    rows = m["records"][:4]
    lab = tmp_path / "labels"
    lab.mkdir()
    # correctness: A=yes,yes,no,no  B=yes,no,yes,no -> po=0.5, pe=0.5, kappa=0
    # problematic + category_correct: full agreement -> kappa=1
    # correctness: A=yes,yes,no,no  B=yes,no,yes,no -> po=0.5, pe=0.5, kappa=0
    # problematic + category_correct: agreed with variance (yes,yes,no,no both)
    #   -> po=1, pe=0.5, kappa=1
    votes = [("yes", "yes"), ("yes", "no"), ("no", "yes"), ("no", "no")]
    for i, (r, (va, vb)) in enumerate(zip(rows, votes)):
        pv = "yes" if i < 2 else "no"
        _write(lab, r, "labeler-a", correctness=va, problematic=pv, category=pv)
        _write(lab, r, "labeler-b", correctness=vb, problematic=pv, category=pv)
    st = p21.validate_labels(labels_dir=lab, manifest=m)
    agr = p21.compute_agreement(st, labels_dir=lab)
    assert agr["status"] == "COMPUTED"
    assert agr["dimensions"]["correctness"]["raw_agreement"] == 0.5
    assert agr["dimensions"]["correctness"]["cohens_kappa"] == 0.0
    assert agr["dimensions"]["problematic"]["raw_agreement"] == 1.0
    assert agr["dimensions"]["problematic"]["cohens_kappa"] == 1.0
    assert agr["full_agreement"]["n_full_agree"] == 2  # rows 0 and 3 agree on all dims


def test_adjudication_lists_only_disagreements(tmp_path):
    m = _manifest()
    rows = m["records"][:2]
    lab = tmp_path / "labels"
    lab.mkdir()
    _write(lab, rows[0], "labeler-a", problematic="yes")
    _write(lab, rows[0], "labeler-b", problematic="no")
    _write(lab, rows[1], "labeler-a")
    _write(lab, rows[1], "labeler-b")
    st = p21.validate_labels(labels_dir=lab, manifest=m)
    adj = p21.build_adjudication_list(st, labels_dir=lab)
    assert adj["n_disagreements"] == 1
    assert adj["items"][0]["record_id"] == rows[0]["record_id"]
    assert adj["items"][0]["disagreed_dimensions"] == ["problematic"]
    assert adj["items"][0]["resolution"] == "pending_third_labeler"


def test_calibrate_hold_without_labels(tmp_path):
    m = _manifest()
    lab = tmp_path / "labels"
    lab.mkdir()
    st = p21.validate_labels(labels_dir=lab, manifest=m)
    cal = p21.calibrate(st, m, labels_dir=lab, adjudicated_dir=tmp_path / "adj")
    assert cal["status"] == "INCONCLUSIVE_NO_HUMAN_LABELS"
    assert cal["n_gold_records"] == 0
    assert cal["dimensions"] == {}


def test_calibrate_computed_matches_hand_counted_confusion(tmp_path):
    m = _manifest()
    idx = p21.manifest_index(m)
    pos = [r for r in m["records"] if r["jev_signals"]["problematic"] >= 0.5][:3]
    neg = [r for r in m["records"] if r["jev_signals"]["problematic"] < 0.5][:3]
    rows = pos + neg
    assert len(rows) == 6  # genuinely mixed fixture
    lab = tmp_path / "labels"
    lab.mkdir()
    # gold: problematic=yes iff jev problematic >= 0.5 (both labelers agree)
    for r in rows:
        v = "yes" if r["jev_signals"]["problematic"] >= 0.5 else "no"
        _write(lab, r, "labeler-a", problematic=v)
        _write(lab, r, "labeler-b", problematic=v)
    st = p21.validate_labels(labels_dir=lab, manifest=m)
    cal = p21.calibrate(st, m, labels_dir=lab, adjudicated_dir=tmp_path / "adj")
    assert cal["status"] == "COMPUTED"
    assert cal["n_gold_records"] == 6
    dim = next(d for d in cal["dimensions"] if d["dimension"] == "problematic")
    cell = next(s for s in dim["sweep"] if s["threshold"] == 0.5)
    n_pos = sum(1 for r in rows if r["jev_signals"]["problematic"] >= 0.5)
    assert cell["confusion"] == {"tp": n_pos, "fp": 0, "tn": 6 - n_pos, "fn": 0}
    assert cell["precision"] == 1.0 and cell["recall"] == 1.0
    assert dim["jev_score_distribution"]["human_positive"]["n"] == n_pos


def test_disputed_unadjudicated_dims_excluded(tmp_path):
    m = _manifest()
    row = m["records"][0]
    lab = tmp_path / "labels"
    lab.mkdir()
    _write(lab, row, "labeler-a", problematic="yes")
    _write(lab, row, "labeler-b", problematic="no")
    st = p21.validate_labels(labels_dir=lab, manifest=m)
    gold, prov = p21.load_gold(st, labels_dir=lab, adjudicated_dir=tmp_path / "adj")
    assert "problematic" not in gold[row["record_id"]]
    assert gold[row["record_id"]]["correctness"] == "yes"  # agreed dims kept
    assert prov[row["record_id"]]["problematic"] == "disputed_unadjudicated_excluded"


def test_tooling_never_fabricates_or_mutates_source(tmp_path):    # manifest untouched: still fully pending, zero human labels
    m = _manifest()
    assert all(r["labeling_status"] == "pending" for r in m["records"])
    assert all(r.get("human_labels") is None for r in m["records"])
    # pilot source bytes unchanged after package build
    p21.build_package(tmp_path / "pkg")
    src = json.loads((P2_DIR / "source_file_sha256.json").read_text())
    for relpath, recorded in src["files"].items():
        h = hashlib.sha256()
        with open(ROOT / relpath, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        assert h.hexdigest() == recorded, f"source modified: {relpath}"


# ---------------------------------------------------------------- 6. interactive labeling helper


def test_build_label_object_passes_validation(tmp_path):
    m = _manifest()
    idx = p21.manifest_index(m)
    row = m["records"][0]
    obj = p21.build_label_object(row, "labeler-a",
                                 {"correctness": "yes", "problematic": "no", "category_correct": "yes"},
                                 notes="looks fine")
    assert p21.validate_label(obj, idx, f"{row['record_id']}__labeler-a.json") == []
    assert obj["content_sha256"] == row["content_sha256"]  # sha copied, never recomputed
    assert obj["blinded_to_jev"] is True


def test_write_label_writes_valid_file_and_refuses_overwrite(tmp_path):
    m = _manifest()
    row = m["records"][0]
    lab = tmp_path / "labels"
    answers = {"correctness": "yes", "problematic": "no", "category_correct": "yes"}
    path = p21.write_label(row, "labeler-a", answers, labels_dir=lab, manifest=m)
    assert path.name == f"{row['record_id']}__labeler-a.json"
    st = p21.validate_labels(labels_dir=lab, manifest=m)
    assert st["violations"] == []
    assert st["per_record"][row["record_id"]] == ["labeler-a"]
    # overwrite refused
    try:
        p21.write_label(row, "labeler-a", answers, labels_dir=lab, manifest=m)
        raise AssertionError("expected ValueError on overwrite")
    except ValueError:
        pass


def test_write_label_rejects_bad_answers_without_writing(tmp_path):
    m = _manifest()
    row = m["records"][0]
    lab = tmp_path / "labels"
    try:
        p21.write_label(row, "labeler-a",
                        {"correctness": "maybe", "problematic": "no", "category_correct": "yes"},
                        labels_dir=lab, manifest=m)
        raise AssertionError("expected ValueError on bad answer")
    except ValueError:
        pass
    assert not list(lab.glob("*.json")) if lab.is_dir() else True


def test_pending_for_labeler_tracks_progress(tmp_path):
    m = _manifest()
    rows = m["records"][:2]
    lab = tmp_path / "labels"
    lab.mkdir()
    st = p21.validate_labels(labels_dir=lab, manifest=m)
    assert len(p21.pending_for_labeler("labeler-a", st)) == st["n_unique_records"]
    answers = {"correctness": "yes", "problematic": "no", "category_correct": "yes"}
    p21.write_label(rows[0], "labeler-a", answers, labels_dir=lab, manifest=m)
    st = p21.validate_labels(labels_dir=lab, manifest=m)
    pending = p21.pending_for_labeler("labeler-a", st)
    assert rows[0]["record_id"] not in pending
    assert len(pending) == st["n_unique_records"] - 1


def test_render_record_blinded_has_content_no_jev(tmp_path):
    pkg = tmp_path / "pkg"
    p21.build_package(pkg)
    m = _manifest()
    rid = m["records"][0]["record_id"]
    text = p21.render_record_blinded(rid, package_dir=pkg, manifest=m)
    low = text.lower()
    assert "--- user ---" in low and "--- assistant ---" in low
    for leak in ("jev_signals", "noul", "consistent_category", "training_value", "adherence"):
        assert leak not in low, f"Jev leakage '{leak}' in rendered view"
    assert rid in text
