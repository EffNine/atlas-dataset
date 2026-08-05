#!/usr/bin/env python3
"""compare_v1_v2.py — QEE v1 vs v2 before/after comparison.

Phase 5A.2 verification tool. Computes, for the same human-reviewed records:

  * **before**  — QEE v1 (scripts/quality_score.py) agreement with humans,
  * **after-raw** — QEE v2 without calibration (logistic spread),
  * **after-cal** — QEE v2 with leave-one-out calibrated mapping (honest
                    out-of-sample agreement).

Reads data read-only. Writes a machine-readable report to
`metadata/evaluation/qee_v1_v2_comparison.json` and prints a summary table.

Exit code 0 on success; 2 on missing inputs.

Usage:
  python scripts/evaluation_engine/v2/compare_v1_v2.py \
      --records curated/v0.2/data/v0.2_full.jsonl \
      --reviews review/quality_reviews.jsonl \
      --out metadata/evaluation/qee_v1_v2_comparison.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluation_engine.v2.engine import QeeV2Engine  # noqa: E402
from evaluation_engine.v2.calibration import (  # noqa: E402
    load_jsonl,
    matched_pairs,
    v1_scores,
    v2_raw_scores,
    v2_loo_calibrated,
)

# Documented historical baseline from docs/evaluation/qee_human_alignment_report.md
# (engine state at Phase 5B on the same 100-record sample).
DOCUMENTED_BEFORE = {
    "source": "docs/evaluation/qee_human_alignment_report.md",
    "date": "2026-07-28",
    "qee_mean": 9.00,
    "human_mean": 6.86,
    "mean_bias": 2.14,
    "exact_agree": 0.0,
    "within1_agree": 0.02,
    "rmse": 2.177,
    "false_approvals": 16,
    "note": "QEE assigned 9 to all 100 matched records at Phase 5B.",
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--records",
                    default=str(ROOT / "curated" / "v0.2" / "data" / "v0.2_full.jsonl"))
    ap.add_argument("--reviews", default=str(ROOT / "review" / "quality_reviews.jsonl"))
    ap.add_argument("--out",
                    default=str(ROOT / "metadata" / "evaluation" / "qee_v1_v2_comparison.json"))
    ap.add_argument("--reviewer", default="AR")
    args = ap.parse_args(argv)

    records = load_jsonl(args.records)
    reviews = load_jsonl(args.reviews)
    n_matched = len(matched_pairs(records, reviews, args.reviewer))
    if n_matched == 0:
        print(f"[compare] ERROR: no matched records between {args.records} and "
              f"{args.reviews} (reviewer={args.reviewer})", file=sys.stderr)
        return 2

    engine = QeeV2Engine()

    before = v1_scores(records, reviews, args.reviewer)
    humans = [int(rev["human_score"]) for _, rev in
              matched_pairs(records, reviews, args.reviewer)]
    after_raw = v2_raw_scores(records, reviews, engine, args.reviewer)
    after_cal = v2_loo_calibrated(records, reviews, engine, args.reviewer)

    metrics = {
        "documented_phase5b": DOCUMENTED_BEFORE,
        "before_v1": _summarize(before, humans),
        "after_v2_raw": _summarize(after_raw, humans),
        "after_v2_loo_calibrated": _summarize(after_cal["predicted_scores"], humans),
        "calibration_fit": after_cal["fitted_calibration"],
        "calibration_interpretation": _calibration_interpretation(
            after_cal["fitted_calibration"], len(humans)),
        "record_count": len(humans),
        "engine_v1": "scripts/quality_score.py",
        "engine_v2": "scripts/evaluation_engine/v2/",
        "reviewer_filter": args.reviewer,
    }

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")

    print("=" * 78)
    print("QEE v1 vs v2  —  before/after comparison (n=%d)" % len(humans))
    print("=" * 78)
    _print_table(metrics)
    print("-" * 78)
    print(f"calibration fit (full sample): slope={after_cal['fitted_calibration']['slope']} "
          f"intercept={after_cal['fitted_calibration']['intercept']}")
    print(f"calibration readiness: {metrics['calibration_interpretation']}")
    print(f"report -> {args.out}")
    return 0


def _calibration_interpretation(fit: dict, n: int) -> str:
    """Honest reading of the fitted calibration.

    A near-flat slope means the current review sample is too noisy/small to
    support a reliable linear calibration, so the calibrated column should not
    be treated as a deployable gate — it is a readiness probe.
    """
    slope = fit.get("slope", 1.0)
    if abs(slope) < 0.2:
        return (
            f"fitted slope {slope:.3f} is near-flat on n={n} reviewed records: "
            "the sample is underpowered for a reliable linear calibration. "
            "Do not use the calibrated mapping for automated gating; re-fit on "
            "a larger, less noisy human review set (Phase 5C) and keep human "
            "approval mandatory."
        )
    return (
        f"fitted slope {slope:.3f} is usable on n={n} reviewed records, but "
        "re-validate against fresh human review before enabling an automated gate."
    )


def _summarize(auto: list[int], human: list[int]) -> dict:
    from evaluation_engine.v2.calibration import compute_metrics
    m = compute_metrics(auto, human)
    return {
        "auto_mean": m["auto_mean"],
        "human_mean": m["human_mean"],
        "mean_bias": m["mean_bias"],
        "mae": m["mae"],
        "rmse": m["rmse"],
        "exact_agree": m["exact_agree"],
        "within1_agree": m["within1_agree"],
        "pearson_r": m["pearson_r"],
        "spearman_rho": m["spearman_rho"],
        "false_approvals": m["false_approvals"],
        "false_rejections": m["false_rejections"],
        "auto_distribution": m["auto_distribution"],
        "distinct_auto_scores": m["distinct_auto_scores"],
    }


def _print_table(metrics: dict) -> None:
    rows = [
        ("QEE mean", "auto_mean", "{:.2f}"),
        ("Human mean", "human_mean", "{:.2f}"),
        ("Mean bias (auto-human)", "mean_bias", "{:+.3f}"),
        ("MAE", "mae", "{:.3f}"),
        ("RMSE", "rmse", "{:.3f}"),
        ("Exact agreement", "exact_agree", "{:.1%}"),
        ("Within-1 agreement", "within1_agree", "{:.1%}"),
        ("Pearson r", "pearson_r", "{:.3f}"),
        ("Spearman rho", "spearman_rho", "{:.3f}"),
        ("False approvals", "false_approvals", "{:d}"),
        ("False rejections", "false_rejections", "{:d}"),
        ("Distinct auto scores", "distinct_auto_scores", "{:d}"),
    ]
    header = ["metric", "documented\nPhase 5B", "before\n(v1)", "after raw\n(v2)", "after cal\n(v2 LOO)"]
    widths = [34, 14, 12, 12, 12]
    print(" | ".join(h.center(w) for h, w in zip(header, widths)))
    print("-" * 88)
    for label, key, fmt in rows:
        vals = []
        for section in ("documented_phase5b", "before_v1", "after_v2_raw", "after_v2_loo_calibrated"):
            v = metrics[section].get(key)
            vals.append(fmt.format(v) if v is not None else "-")
        cells = [label.ljust(34)] + [v.rjust(w - 1) for v, w in zip(vals, widths[1:])]
        print(" | ".join(cells))
    print()
    for section, label in (("before_v1", "v1"), ("after_v2_raw", "v2 raw"),
                           ("after_v2_loo_calibrated", "v2 cal")):
        dist = metrics[section]["auto_distribution"]
        print(f"  {label:8s} distribution: {dist}")


if __name__ == "__main__":
    raise SystemExit(main())
