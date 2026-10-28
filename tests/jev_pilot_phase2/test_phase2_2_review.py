#!/usr/bin/env python3
"""Phase 2.2 tests: deterministic selection, blinded package (opaque IDs, sealed
separation, zero leakage), review-schema validation incl. evidence rule,
agreement math, adjudication, error-matrix math, HOLD states, source non-mutation.

Run:  .venv/bin/python -m pytest tests/jev_pilot_phase2/test_phase2_2_review.py -q

All reviews in this file are SYNTHETIC fixtures in tmp dirs — never written to
phase2.2/reviews/. Nothing here fabricates real calibration reviews.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
P22_DIR = ROOT / "experiments" / "jev-pilot-atlas-v0.1" / "phase2.2"
sys.path.insert(0, str(P22_DIR))

import phase2_2_review as p22  # noqa: E402


def _clean_answers(**over):
    ans = {d: ("no" if d == "correctness" else "yes" if d == "problematic" else "no")
           for d in p22.DIMS}
    # default: fully clean (correctness=yes, everything else=no)
    ans = {d: ("yes" if d == "correctness" else "no") for d in p22.DIMS}
    ans.update(over)
    return ans


def _ev_for(answers: dict) -> dict:
    return {d: (f"evidence pinpointing {d} defect here" if answers[d] == p22.FINDING_VALUE[d] else "")
            for d in p22.DIMS}


def _make_review(batch: str, reviewer: str, answers: dict | None = None) -> dict:
    answers = answers or _clean_answers()
    return {
        "schema_version": "human-review-v2",
        "batch_id": batch,
        "reviewer_id": reviewer,
        "reviewed_at": "2026-09-18T10:00:00+00:00",
        "criteria_version": "phase2.2-defects-v1",
        "reference_version": "taxonomy_reference_v1",
        "blinded_to_jev": True,
        "blinded_to_prior_labels": True,
        "labels": dict(answers),
        "evidence": _ev_for(answers),
    }


def _write(tmp: Path, batch: str, reviewer: str, answers: dict | None = None) -> Path:
    p = tmp / f"{batch}__{reviewer}.json"
    p.write_text(json.dumps(_make_review(batch, reviewer, answers)))
    return p


def _real_batches() -> set:
    return p22.batch_set()


# ---------------------------------------------------------------- selection


def test_selection_deterministic_28_with_groups():
    a = p22.select_subset()
    b = p22.select_subset()
    assert a == b
    assert len(a) == 28
    assert len({r["record_id"] for r in a}) == 28
    groups = {r["group"] for r in a}
    assert groups == {"R-retest-flagged", "F-fresh-flagged", "C-clean-control"}
    assert sum(1 for r in a if r["group"] == "R-retest-flagged") == 12
    assert sum(1 for r in a if r["group"] == "F-fresh-flagged") == 12
    assert sum(1 for r in a if r["group"] == "C-clean-control") == 4


def test_selection_retest_subset_of_84_and_fresh_disjoint():
    rows = p22.select_subset()
    in84 = p22.load_in84()
    r = [x for x in rows if x["group"] == "R-retest-flagged"]
    f = [x for x in rows if x["group"] == "F-fresh-flagged"]
    assert all(x["record_id"] in in84 for x in r)
    assert all(x["record_id"] not in in84 for x in f)
    assert all(x["jev"]["flags"] for x in r + f)  # every R/F row is JEV-flagged


def test_selection_does_not_modify_phase2():
    before = {p.name: p.read_bytes() for p in (p22.P2).glob("*.json")}
    p22.select_subset()
    after = {p.name: p.read_bytes() for p in (p22.P2).glob("*.json")}
    assert before == after


# ---------------------------------------------------------------- package / blinding


def test_build_package_deterministic_opaque_and_blinded(tmp_path):
    rows = p22.select_subset()
    sa = p22.build_package(rows, tmp_path / "a", sealed_dir=tmp_path / "sa-sealed")
    sb = p22.build_package(rows, tmp_path / "b", sealed_dir=tmp_path / "sb-sealed")
    assert [r["batch_id"] for r in sa["rows"]] == [r["batch_id"] for r in sb["rows"]]
    rec_files = sorted((tmp_path / "a" / "records").glob("*.json"))
    assert len(rec_files) == 28
    assert [p.stem for p in rec_files] == [f"P22-{i + 1:03d}" for i in range(28)]
    for p in rec_files:
        obj = json.loads(p.read_text())
        # opaque envelope: exact top-level key whitelist (dimension names legitimately
        # occur INSIDE defect_criteria/messages, so the check is positional, not global)
        assert set(obj) == {"batch_id", "content_sha256", "criteria_version", "defect_criteria",
                            "reference_version", "source", "category_label", "subcategory_label",
                            "license", "messages", "note"}, f"envelope keys changed in {p.name}"
        assert set(obj["defect_criteria"]) == set(p22.DIMS) | {"evidence_rule"}
        blob = json.dumps(obj).lower()
        for leak in ("low_jev", "flagged", "outliers", "noul"):
            assert leak not in blob, f"value leak '{leak}' in {p.name}"
        assert "messages" in obj and len(obj["messages"]) >= 2


def test_sealed_map_join_back(tmp_path):
    rows = p22.select_subset()
    p22.build_package(rows, tmp_path / "pkg", sealed_dir=tmp_path / "sealed")
    # sealed files live beside the package dir, never inside review_package/
    assert not list((tmp_path / "pkg").rglob("*.sealed.json"))
    assert (tmp_path / "sealed" / "record_map.sealed.json").exists()
    assert (tmp_path / "sealed" / "selection_manifest.sealed.json").exists()
    sm = json.loads((tmp_path / "sealed" / "record_map.sealed.json").read_text())
    assert sm["sealed"] is True
    assert len(sm["map"]) == 28
    assert set(sm["map"]) == {f"P22-{i + 1:03d}" for i in range(28)}


# ---------------------------------------------------------------- validation


def test_validate_accepts_good_review():
    batches = _real_batches()
    bid = sorted(batches)[0]
    assert p22.validate_review(_make_review(bid, "r1"), batches, f"{bid}__r1.json") == []


def test_validate_rejects_missing_evidence_for_findings():
    batches = _real_batches()
    bid = sorted(batches)[0]
    obj = _make_review(bid, "r1", _clean_answers(correctness="no"))
    obj["evidence"]["correctness"] = "wrong"
    errs = p22.validate_review(obj, batches, f"{bid}__r1.json")
    assert any("evidence.correctness" in e for e in errs)
    obj2 = _make_review(bid, "r1", _clean_answers(factual_technical_error="yes"))
    obj2["evidence"]["factual_technical_error"] = ""
    assert any("evidence.factual_technical_error" in e
               for e in p22.validate_review(obj2, batches, f"{bid}__r1.json"))


def test_validate_rejects_unblinding_and_bad_ids():
    batches = _real_batches()
    bid = sorted(batches)[0]
    leaked = _make_review(bid, "r1")
    leaked["jev_signals"] = {"quality": 1.0}
    assert any("forbidden extra fields" in e for e in p22.validate_review(leaked, batches, f"{bid}__r1.json"))
    raw_id = _make_review(bid, "r1")
    raw_id["batch_id"] = "v2-code-0000000000000000"
    assert any("batch_id" in e for e in p22.validate_review(raw_id, batches, "x__r1.json"))
    unblinded = _make_review(bid, "r1")
    unblinded["blinded_to_prior_labels"] = False
    assert any("blinded_to_prior_labels" in e
               for e in p22.validate_review(unblinded, batches, f"{bid}__r1.json"))


def test_two_reviewer_requirement_end_to_end(tmp_path):
    batches = sorted(_real_batches())[:3]
    lab = tmp_path / "reviews"
    lab.mkdir()
    # build_package wrote the real manifest; validate against tmp dir needs batches override:
    for b in batches:
        _write(lab, b, "r1")
    # validate_reviews reads real manifest batches (28); tmp dir covers 3 -> rest empty
    st = p22.validate_reviews(reviews_dir=lab)
    assert st["n_batches"] == 28
    assert st["n_batches_one_reviewer"] == 3
    assert st["meets_two_reviewer_requirement"] is False
    for b in batches:
        _write(lab, b, "r2", _clean_answers(problematic="yes"))
    st = p22.validate_reviews(reviews_dir=lab)
    assert st["violations"] == []  # evidence auto-provided by fixture for the yes
    adj = p22.build_adjudication_list(st, reviews_dir=lab)
    assert adj["n_disagreements"] == 3
    assert all(i["resolution"] == "pending_third_reviewer" for i in adj["items"])
    assert adj["items"][0]["votes"]["problematic"]["r1"]["verdict"] == "no"


# ---------------------------------------------------------------- agreement + error analysis


def test_agreement_known_kappa_and_hold(tmp_path):
    lab = tmp_path / "reviews"
    lab.mkdir()
    st = p22.validate_reviews(reviews_dir=lab)
    assert p22.compute_agreement(st, reviews_dir=lab)["status"] == "HOLD_NO_PAIRED_REVIEWS"
    batches = sorted(_real_batches())[:4]
    votes = [("yes", "yes"), ("yes", "no"), ("no", "yes"), ("no", "no")]
    for b, (va, vb) in zip(batches, votes):
        _write(lab, b, "r1", _clean_answers(correctness=va))
        _write(lab, b, "r2", _clean_answers(correctness=vb))
    st = p22.validate_reviews(reviews_dir=lab)
    agr = p22.compute_agreement(st, reviews_dir=lab)
    assert agr["status"] == "COMPUTED"
    assert agr["dimensions"]["correctness"]["raw_agreement"] == 0.5
    assert agr["dimensions"]["correctness"]["cohens_kappa"] == 0.0


def test_error_matrix_math_and_hold(tmp_path):
    lab = tmp_path / "reviews"
    lab.mkdir()
    st = p22.validate_reviews(reviews_dir=lab)
    err = p22.error_analysis(st, reviews_dir=lab, adjudicated_dir=tmp_path / "adj")
    assert err["status"] == "HOLD_NO_GOLD"
    assert err["matrix"] == {"TP_flagged_defect": None, "FP_flagged_clean": None,
                             "FN_clean_defect": None, "TN_clean_clean": None}
    # craft: 2 batches agreed defect + flagged, 2 agreed clean + flagged
    sel = json.loads((p22.P22 / "selection_manifest.sealed.json").read_text())
    flagged_batches = [r["batch_id"] for r in sel["rows"] if r["jev"]["flags"]][:4]
    assert len(flagged_batches) == 4
    defect = _clean_answers(correctness="no")  # defect via correctness
    clean = _clean_answers()
    for b in flagged_batches[:2]:
        _write(lab, b, "r1", defect)
        _write(lab, b, "r2", defect)
    for b in flagged_batches[2:]:
        _write(lab, b, "r1", clean)
        _write(lab, b, "r2", clean)
    st = p22.validate_reviews(reviews_dir=lab)
    err = p22.error_analysis(st, reviews_dir=lab, adjudicated_dir=tmp_path / "adj")
    assert err["status"] == "COMPUTED"
    assert err["matrix"] == {"TP_flagged_defect": 2, "FP_flagged_clean": 2,
                             "FN_clean_defect": 0, "TN_clean_clean": 0}
    assert err["metrics"]["precision"] == 0.5
    assert err["metrics"]["recall"] == 1.0
    assert err["metrics"]["fnr"] == 0.0
    assert err["metrics"]["fpr"] == 1.0  # FP=2, TN=0: defined; undefined only when FP+TN==0
    disagree = [i for i in err["items"] if i["cell"] == "FP_flagged_clean"]
    assert len(disagree) == 2
    assert all(i["analyst_reason_selected"] is None and i["resolution"] == "pending_analyst"
               for i in disagree)


def test_disputed_dims_excluded_without_adjudication(tmp_path):
    batches = sorted(_real_batches())[:1]
    lab = tmp_path / "reviews"
    lab.mkdir()
    _write(lab, batches[0], "r1", _clean_answers())
    _write(lab, batches[0], "r2", _clean_answers(problematic="yes"))
    st = p22.validate_reviews(reviews_dir=lab)
    gold, prov = p22.load_gold(st, reviews_dir=lab, adjudicated_dir=tmp_path / "adj")
    assert "problematic" not in gold[batches[0]]
    assert prov[batches[0]]["problematic"] == "disputed_unadjudicated_excluded"


def test_tooling_never_mutates_source_or_phase2(tmp_path):
    p2_before = {p.name: p.read_bytes() for p in p22.P2.glob("*.json")}
    p22.build_package(p22.select_subset(), tmp_path / "pkg", sealed_dir=tmp_path / "sealed")
    assert {p.name: p.read_bytes() for p in p22.P2.glob("*.json")} == p2_before
    src = json.loads((p22.P2 / "source_file_sha256.json").read_text())
    for relpath, recorded in src["files"].items():
        h = hashlib.sha256()
        with open(ROOT / relpath, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        assert h.hexdigest() == recorded, f"source modified: {relpath}"
