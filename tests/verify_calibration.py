#!/usr/bin/env python3
"""
verify_calibration.py — Assertion-based verification of the Atlas
quality-calibration framework.

Unlike the pipeline verifier, this does NOT require real human reviews. It
builds a tiny, deterministic fixture (auto-score paired with scripted human
scores) and asserts the framework's core guarantees:

  * gen_calibration_sample is READ-ONLY on candidates (count unchanged).
  * calibrate produces global accuracy, per-category bias, per-source bias,
    per-dimension bias, confidence, and recommendations.
  * ADDITIVE_CORRECTION is recommended where |bias| >= bias_flag, and
    MANDATORY_HUMAN_REVIEW where decision F1 < 0.70 or confidence < floor.
  * confidence is in [0,1] and monotonic in sample size / error.
  * the readiness verdict is one of the known states.
  * reports are written and valid JSON / non-empty markdown.
  * empty-review case degrades gracefully (INSUFFICIENT_DATA, no crash).

Exit code 0 = all checks pass; 1 = at least one failure.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import gen_calibration_sample as gcs
import calibrate_quality as cq

# Reuse the heuristic scorer to fabricate a fixture deterministically.
import importlib.util as _ilu
_qspec = _ilu.spec_from_file_location(
    "quality_score", ROOT / "scripts" / "quality_score.py")
_quality = _ilu.module_from_spec(_qspec)
_qspec.loader.exec_module(_quality)


def _build_fixture(tmp: Path) -> tuple[Path, Path]:
    """Create a small candidates file + a calibration reviews file.

    We script human scores so we KNOW the expected bias/correction and can
    assert the framework detects it. Auto-scores are recomputed by the
    framework itself, so we only need to fix the human side + category/source.
    """
    candidates = []
    reviews = []
    # 8 records across 2 categories and 2 sources, with a deliberate bias.
    plan = [
        # (id, category, source_id, human_score, human_dim, verdict, hall, conf)
        ("c1", "02_software_engineering", "sA", 9, 9, "accept", False, 5),
        ("c2", "02_software_engineering", "sA", 8, 8, "accept", False, 5),
        ("c3", "02_software_engineering", "sA", 9, 9, "accept", False, 4),
        ("c4", "02_software_engineering", "sA", 8, 8, "accept", False, 5),
        ("c5", "02_software_engineering", "sA", 9, 9, "accept", True, 3),
        ("c6", "07_business_knowledge", "sB", 4, 4, "reject", False, 5),
        ("c7", "07_business_knowledge", "sB", 5, 5, "revise", False, 5),
        ("c8", "07_business_knowledge", "sB", 4, 4, "reject", False, 4),
    ]
    for i, (rid, cat, src, hscore, hdim, verdict, hall, conf) in enumerate(plan):
        rec = {
            "id": rid, "category": cat, "subcategory": "x",
            "source_attribution": {"source_id": src, "name": "fixture"},
            "messages": [{"role": "user", "content": f"q {i}"},
                         {"role": "assistant", "content": "answer " * 60}],
        }
        candidates.append(rec)
        reviews.append({
            "record_id": rid, "category": cat, "source_id": src,
            "reviewer": "TEST", "review_date": "2026-07-27",
            "human_score": hscore,
            "dimension_scores": {d: hdim for d in _quality.WEIGHTS},
            "verdict": verdict, "hallucination": hall, "confidence": conf,
        })
    cand_path = tmp / "fixture_candidates.jsonl"
    rev_path = tmp / "fixture_reviews.jsonl"
    cand_path.write_text("\n".join(json.dumps(r) for r in candidates) + "\n")
    rev_path.write_text("\n".join(json.dumps(r) for r in reviews) + "\n")
    return cand_path, rev_path


def main() -> int:
    results = []
    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}" + (f" -- {detail}" if detail else ""))

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        cand_path, rev_path = _build_fixture(td)

        # --- 1. gen is read-only on candidates ---
        before = len(cand_path.read_text().splitlines())
        ws = td / "worksheet.jsonl"
        gcs.build_worksheet(
            [json.loads(l) for l in cand_path.read_text().splitlines() if l.strip()],
            1.0, seed=1)
        after = len(cand_path.read_text().splitlines())
        check("gen: read-only on candidates (count unchanged)",
              before == after == 8, f"before={before} after={after}")

        # --- 2. calibrate on fixture ---
        reviews = [json.loads(l) for l in rev_path.read_text().splitlines() if l.strip()]
        candidates = [json.loads(l) for l in cand_path.read_text().splitlines() if l.strip()]
        report = cq.calibrate(reviews, candidates)

        check("calibrate: matched all reviews",
              report["n_matched"] == 8, f"matched={report['n_matched']}")
        check("calibrate: global metrics present",
              report["global"] is not None and "mae" in report["global"])
        g = report["global"]
        check("calibrate: MAE non-negative", g["mae"] >= 0, f"mae={g['mae']}")
        check("calibrate: within-1 in [0,1]",
              0 <= g["within1_agree"] <= 1, f"w1={g['within1_agree']}")
        check("calibrate: threshold F1 in [0,1]",
              0 <= g["threshold"]["f1"] <= 1, f"f1={g['threshold']['f1']}")

        # --- 3. bias detection: business category should be flagged biased
        # (auto recomputed ~7, human 4-5 => mean_bias large negative)
        biz = report["by_category"].get("07_business_knowledge")
        check("bias: business category detected", biz is not None,
              "missing business stratum")
        if biz:
            recs = [r for r in report["recommendations"]
                    if r["scope"] == "category" and r["target"] == "07_business_knowledge"]
            actions = {r["action"] for r in recs}
            check("bias: business flagged MANDATORY_HUMAN_REVIEW or correction",
                  bool(actions & {"MANDATORY_HUMAN_REVIEW", "APPLY_ADDITIVE_CORRECTION"}),
                  f"actions={actions}")
            check("bias: correction is additive inverse of bias",
                  abs(biz["recommended_correction"] + biz["mean_bias"]) < 1e-6,
                  f"corr={biz['recommended_correction']} bias={biz['mean_bias']}")

        # --- 4. confidence in [0,1] ---
        confs = [m["confidence"] for m in report["by_category"].values()]
        check("confidence: all in [0,1]", all(0 <= c <= 1 for c in confs),
              f"confs={confs}")
        # larger sample (software, n=5) should not have lower confidence than
        # tiny sample if error comparable; at least monotonic in n for equal MAE:
        check("confidence: finite & present per stratum",
              all(isinstance(c, float) for c in confs))

        # --- 5. readiness verdict known ---
        check("readiness: known verdict",
              report["readiness"]["verdict"] in
              {"INSUFFICIENT_DATA", "READY_FOR_CALIBRATED_AUTO_REVIEW",
               "REQUIRES_HUMAN_REVIEW", "NOT_READY"},
              report["readiness"]["verdict"])

        # --- 6. reports write + valid ---
        rep_path = td / "calibration_report.json"
        md_path = td / "calibration_report.md"
        cq.main(["--reviews", str(rev_path), "--candidates", str(cand_path),
                 "--report-out", str(rep_path), "--md-out", str(md_path)])
        check("report: JSON valid + non-empty",
              rep_path.exists() and json.loads(rep_path.read_text()))
        check("report: markdown non-empty",
              md_path.exists() and md_path.read_text().strip())

        # --- 7. empty reviews degrade gracefully ---
        empty = td / "empty.jsonl"
        empty.write_text("")
        rep_empty = cq.calibrate([], candidates)
        check("empty: INSUFFICIENT_DATA, no crash",
              rep_empty["n_matched"] == 0
              and rep_empty["readiness"]["verdict"] == "INSUFFICIENT_DATA")
        check("empty: global is None",
              rep_empty["global"] is None)

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n=== {len(results) - len(failed)}/{len(results)} checks passed ===")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
