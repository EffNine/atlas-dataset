#!/usr/bin/env python3
"""
validate_quality_engine.py — Validate the new Quality Evaluation Engine (QEE)
against the FROZEN calibration baseline (metadata/calibration_baseline_v0.1.json).

This is a READ-ONLY comparison. It never modifies knowledge objects, the review
file, the frozen baseline, or any dataset artifact. It recomputes the
calibration statistics using the CURRENT quality_score.py (the new engine) and
diffs them against the frozen reference values captured in Phase 3C.1.

Why this matters:
  The frozen baseline recorded that the OLD scorer assigned 7.0 to every record
  (zero variance), so Pearson/Spearman were undefined (null) and "100%
  within-1 agreement" was an artifact of compression. The new QEE must show:
    * real score variance (>= 3 distinct scores),
    * a DEFINED, POSITIVE correlation with human review (Pearson/Spearman not null),
    * bounded error (MAE/RMSE) and a sensible agreement profile,
  while NOT modifying any reviewed input.

Outputs a machine-readable validation report to
  metadata/quality_engine_validation.json   (NEW artifact; baseline untouched)

Exit code 0 = validation criteria met; 1 = at least one criterion failed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

_cq_spec = importlib.util.spec_from_file_location(
    "calibrate_quality", ROOT / "scripts" / "calibrate_quality.py")
_cq = importlib.util.module_from_spec(_cq_spec)
_cq_spec.loader.exec_module(_cq)


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return num / (dx * dy) if dx and dy else None


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    return pearson(_cq._ranks(xs), _cq._ranks(ys))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reviews", default=str(ROOT / "review" / "quality_reviews.jsonl"))
    ap.add_argument("--candidates", default=str(ROOT / "curated" / "v0.1" / "pilot_candidates.jsonl"))
    ap.add_argument("--baseline", default=str(ROOT / "metadata" / "calibration_baseline_v0.1.json"))
    ap.add_argument("--report-out", default=str(ROOT / "metadata" / "quality_engine_validation.json"))
    ap.add_argument("--min-pearson", type=float, default=0.30,
                    help="minimum acceptable Pearson r (must be defined + positive)")
    ap.add_argument("--min-distinct-scores", type=int, default=3,
                    help="minimum distinct auto-score values (variance gate)")
    args = ap.parse_args()

    reviews = load_jsonl(Path(args.reviews))
    candidates = load_jsonl(Path(args.candidates))
    frozen = load_json(Path(args.baseline))

    # Recompute calibration with the CURRENT (new) engine.
    report = _cq.calibrate(reviews, candidates)
    g = report["global"]

    # Per-record auto/human pairs for direct correlation.
    cand_by_id = {c["id"]: c for c in candidates}
    auto, human = [], []
    for rv in reviews:
        cand = cand_by_id.get(rv["record_id"])
        if cand is None:
            continue
        a, _ = _cq._quality.score_record(cand)
        auto.append(float(a))
        human.append(float(int(rv["human_score"])))

    r = pearson(auto, human)
    rho = spearman(auto, human)
    distinct = len(set(auto))

    # Build the new AI score distribution (1..10).
    ai_dist = {str(s): auto.count(float(s)) for s in range(1, 11)}
    ai_dist = {k: v for k, v in ai_dist.items() if v}

    old_ai = frozen["ai_score_distribution"]
    old_r = frozen["correlation_metrics"]["pearson_r"]
    old_within1 = frozen["correlation_metrics"]["within1_agree"]
    old_f1 = g  # placeholder; use report's threshold f1 below

    # Criteria
    criteria = []
    def crit(name, ok, detail):
        criteria.append({"name": name, "pass": bool(ok), "detail": detail})

    crit("variance: >= %d distinct auto-scores" % args.min_distinct_scores,
         distinct >= args.min_distinct_scores,
         f"distinct={distinct} dist={ai_dist}")
    crit("correlation: Pearson r defined (was %s)" % old_r,
         r is not None, f"pearson_r={r}")
    crit("correlation: Pearson r >= %.2f" % args.min_pearson,
         r is not None and r >= args.min_pearson, f"pearson_r={r}")
    crit("correlation: Spearman rho defined",
         rho is not None, f"spearman_rho={rho}")
    crit("error: MAE finite and < 2.0",
         isinstance(g["mae"], (int, float)) and g["mae"] < 2.0, f"mae={g['mae']}")
    crit("error: RMSE finite and < 2.5",
         isinstance(g["rmse"], (int, float)) and g["rmse"] < 2.5, f"rmse={g['rmse']}")
    crit("agreement: mean_bias within +/-1 (no massive offset)",
         abs(g["mean_bias"]) <= 1.0, f"mean_bias={g['mean_bias']}")
    crit("inputs unchanged: reviewed count == frozen",
         report["n_matched"] == frozen["reviewed_record_count"],
         f"matched={report['n_matched']} frozen={frozen['reviewed_record_count']}")

    passed = all(c["pass"] for c in criteria)

    validation = {
        "artifact": "quality-engine-validation",
        "dataset_version": "v0.1",
        "baseline_reference": "metadata/calibration_baseline_v0.1.json",
        "engine": "Quality Evaluation Engine (scripts/quality_score.py)",
        "reviewed_record_count": report["n_matched"],
        "frozen_baseline": {
            "ai_score_distribution": old_ai,
            "pearson_r": old_r,
            "within1_agree": old_within1,
            "threshold_f1": frozen["correlation_metrics"].get("threshold_f1"),
            "mean_bias": frozen["bias_metrics"]["global_mean_bias"],
        },
        "new_engine": {
            "ai_score_distribution": ai_dist,
            "distinct_scores": distinct,
            "auto_mean": round(sum(auto) / len(auto), 3),
            "human_mean": round(sum(human) / len(human), 3),
            "pearson_r": (round(r, 3) if r is not None else None),
            "spearman_rho": (round(rho, 3) if rho is not None else None),
            "exact_agree": g["exact_agree"],
            "within1_agree": g["within1_agree"],
            "mae": g["mae"],
            "rmse": g["rmse"],
            "mean_bias": g["mean_bias"],
            "threshold_f1": g["threshold"]["f1"],
            "readiness_verdict": report["readiness"]["verdict"],
        },
        "criteria": criteria,
        "passed": passed,
    }
    Path(args.report_out).write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")

    # Console summary
    print("=" * 70)
    print("QUALITY ENGINE VALIDATION vs FROZEN BASELINE")
    print("=" * 70)
    print(f"frozen AI distribution : {old_ai}  (distinct={len(old_ai)})")
    print(f"new    AI distribution : {ai_dist}  (distinct={distinct})")
    print(f"frozen Pearson r      : {old_r}")
    print(f"new    Pearson r      : {r}")
    print(f"new    Spearman rho   : {rho}")
    print(f"MAE={g['mae']}  RMSE={g['rmse']}  mean_bias={g['mean_bias']}  "
          f"within1={g['within1_agree']}  F1={g['threshold']['f1']}")
    print("-" * 70)
    for c in criteria:
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['name']} -- {c['detail']}")
    print("-" * 70)
    print(f"RESULT: {'ALL CRITERIA PASSED' if passed else 'VALIDATION FAILED'}")
    print(f"report -> {args.report_out}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
