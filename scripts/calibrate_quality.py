#!/usr/bin/env python3
"""
calibrate_quality.py — Atlas quality-calibration framework (CORE).

Compares the automated quality scorer (scripts/quality_score.py) against
structured human review (schemas/quality_review_schema.json) to measure:

  1. Scoring accuracy         — MAE, RMSE, Pearson r, Spearman rho,
                                 exact / within-1 agreement, and the
                                 accept/reject threshold decision confusion
                                 matrix (precision / recall / F1).
  2. Bias by category         — systematic over/under-scoring per category.
  3. Bias by source           — systematic error per upstream source.
  4. Bias by dimension        — where the heuristic diverges (accuracy vs
                                 technical_correctness vs ...).
  5. Confidence scores         — per-stratum reliability of the auto-scorer,
                                 used to decide which records may be bulk
                                 ingested on auto-score alone vs. which
                                 REQUIRE human review before promotion.
  6. Recommendations           — concrete, per-stratum adjustments (additive
                                 correction, mandatory human review, weight
                                 re-tuning) and a global bulk-ingestion
                                 readiness verdict.

Design guarantees (consistent with the rest of Atlas):
  * Stdlib-only. No network. Deterministic given the same inputs.
  * NEVER writes dataset records. It only reads candidates (read-only) and
    writes a calibration REPORT (metadata/calibration_report.json) + a
    markdown digest. The dataset size is unchanged by this phase.
  * Auto-scores are recomputed live from quality_score.py so they always
    reflect the CURRENT heuristic, not a stale stored field.

Usage:
  # calibrate against a human-review file (joined with pilot candidates)
  python scripts/calibrate_quality.py \
      --reviews review_queue/quality_reviews.jsonl \
      --candidates curated/v0.1/pilot_candidates.jsonl

  # write machine-readable + markdown reports
  python scripts/calibrate_quality.py \
      --reviews review_queue/quality_reviews.jsonl \
      --candidates curated/v0.1/pilot_candidates.jsonl \
      --report-out metadata/calibration_report.json \
      --md-out docs/quality_calibration_report.md

  # no reviews yet? produces a clear "no calibration data" report
  python scripts/calibrate_quality.py --candidates curated/v0.1/pilot_candidates.jsonl
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# Load the heuristic scorer (single source of truth for auto-scores).
_qspec = importlib.util.spec_from_file_location("quality_score", ROOT / "scripts" / "quality_score.py")
_quality = importlib.util.module_from_spec(_qspec)
_qspec.loader.exec_module(_quality)

ACCEPT_THRESHOLD = 7          # v0.1 gate: quality_score >= 7 AND verified
DIMS = list(_quality.WEIGHTS.keys())

# Calibration decision thresholds (tunable).
WITHIN1_TARGET = 0.80         # fraction of reviews within +/-1 of human
THRESHOLD_F1_TARGET = 0.85    # accept/reject decision F1 target
BIAS_FLAG = 1.0               # |mean(auto-human)| >= this => systematic bias
STRATUM_CONF_FLOOR = 0.60     # below this => mandatory human review for stratum
N_CONF_CAP = 10               # sample size at which stratum confidence saturates


# --------------------------------------------------------------------------- #
# I/O helpers
# --------------------------------------------------------------------------- #
def load_jsonl(path: Path) -> list[dict]:
    out = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


# --------------------------------------------------------------------------- #
# Statistics (stdlib-only)
# --------------------------------------------------------------------------- #
def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def nz(v: float) -> float:
    """Normalize -0.0 to 0.0 for clean reporting."""
    return 0.0 if abs(v) < 1e-9 else v


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = mean(xs), mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # 1-based average rank for ties
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    return pearson(_ranks(xs), _ranks(ys))


def confusion(auto_scores: list[int], human_scores: list[int], thr: int):
    """Binary accept (>=thr) decision confusion matrix."""
    tp = fp = tn = fn = 0
    for a, h in zip(auto_scores, human_scores):
        a_acc, h_acc = a >= thr, h >= thr
        if h_acc and a_acc:
            tp += 1
        elif h_acc and not a_acc:
            fn += 1
        elif not h_acc and a_acc:
            fp += 1
        else:
            tn += 1
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn}


def prf(cm: dict):
    tp, fp, fn = cm["tp"], cm["fp"], cm["fn"]
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    acc = (tp + cm["tn"]) / sum(cm.values()) if sum(cm.values()) else 0.0
    return {"precision": prec, "recall": rec, "f1": f1, "accuracy": acc}


# --------------------------------------------------------------------------- #
# Confidence / reliability model
# --------------------------------------------------------------------------- #
def stratum_confidence(mae: float, n: int) -> float:
    """Reliability of auto-score in a stratum.

    Combines expected error magnitude (1 - MAE/9) with sample-size confidence
    (sqrt(min(n,cap)/cap)) so thinly-sampled strata are not over-trusted.
    Returns 0..1.
    """
    err_factor = max(0.0, 1.0 - mae / 9.0)
    size_factor = math.sqrt(min(n, N_CONF_CAP) / N_CONF_CAP)
    return max(0.0, min(1.0, err_factor * size_factor))


def readiness_verdict(global_metrics: dict, n: int) -> tuple[str, str]:
    if n < 5:
        return ("INSUFFICIENT_DATA",
                f"Only {n} calibrated pairs; gather >=5 (target 30+) before trusting any adjustment.")
    w1 = global_metrics["within1_agree"]
    f1 = global_metrics["threshold"]["f1"]
    if w1 >= WITHIN1_TARGET and f1 >= THRESHOLD_F1_TARGET:
        return ("READY_FOR_CALIBRATED_AUTO_REVIEW",
                "Auto-score agrees with humans within tolerance; bulk ingestion may "
                "proceed with stratum-level corrections + spot-check review.")
    if w1 >= 0.60 and f1 >= 0.70:
        return ("REQUIRES_HUMAN_REVIEW",
                "Moderate agreement: auto-score usable for triage only; every promotion "
                "to curated/ needs human review. Do NOT bulk-ingest on auto-score alone.")
    return ("NOT_READY",
            "Auto-score disagrees with humans substantially; bulk ingestion is NOT "
            "authorized. Re-tune quality_score.py weights before re-calibrating.")


# --------------------------------------------------------------------------- #
# Core calibration
# --------------------------------------------------------------------------- #
def calibrate(reviews: list[dict], candidates: list[dict]) -> dict:
    cand_by_id = {c["id"]: c for c in candidates}

    pairs = []          # (auto, human, category, source, dims_auto, dims_human, record_id)
    missing = []
    for rv in reviews:
        rid = rv["record_id"]
        cand = cand_by_id.get(rid)
        if cand is None:
            missing.append(rid)
            continue
        auto_score, auto_dims = _quality.score_record(cand)
        human = int(rv["human_score"])
        pairs.append({
            "record_id": rid,
            "category": rv.get("category") or cand.get("category", "99_unknown"),
            "source_id": rv.get("source_id") or cand.get("source_attribution", {}).get("source_id", "unknown"),
            "auto": auto_score,
            "human": human,
            "auto_dims": auto_dims,
            "human_dims": rv.get("dimension_scores", {}),
            "verdict": rv.get("verdict"),
            "hallucination": rv.get("hallucination", False),
            "confidence": int(rv.get("confidence", 3)),
        })

    n = len(pairs)
    report: dict = {
        "framework": "atlas-quality-calibration",
        "version": "0.1.0",
        "date": date.today().isoformat(),
        "n_reviews": len(reviews),
        "n_matched": n,
        "n_missing_candidates": len(missing),
        "missing_candidate_ids": missing,
        "accept_threshold": ACCEPT_THRESHOLD,
        "thresholds": {"within1_target": WITHIN1_TARGET,
                        "threshold_f1_target": THRESHOLD_F1_TARGET,
                        "bias_flag": BIAS_FLAG,
                        "stratum_conf_floor": STRATUM_CONF_FLOOR},
    }

    if n == 0:
        report["global"] = None
        report["by_category"] = {}
        report["by_source"] = {}
        report["by_dimension"] = {}
        report["recommendations"] = []
        report["readiness"] = {"verdict": "INSUFFICIENT_DATA",
                               "detail": "No matched human reviews. Run gen_calibration_sample.py "
                                         "to seed a structured review set, then re-run calibration."}
        return report

    auto = [p["auto"] for p in pairs]
    human = [p["human"] for p in pairs]
    diffs = [a - h for a, h in zip(auto, human)]

    mae = mean([abs(d) for d in diffs])
    rmse = math.sqrt(mean([d * d for d in diffs]))
    exact = sum(1 for d in diffs if d == 0) / n
    within1 = sum(1 for d in diffs if abs(d) <= 1) / n
    r = pearson(auto, human)
    rho = spearman(auto, human)
    cm = confusion(auto, human, ACCEPT_THRESHOLD)
    decision = prf(cm)

    report["global"] = {
        "mae": round(mae, 3),
        "rmse": round(rmse, 3),
        "pearson_r": (round(r, 3) if r is not None else None),
        "spearman_rho": (round(rho, 3) if rho is not None else None),
        "exact_agree": round(exact, 3),
        "within1_agree": round(within1, 3),
        "mean_bias": round(mean(diffs), 3),
        "auto_mean": round(mean(auto), 2),
        "human_mean": round(mean(human), 2),
        "threshold": {**cm, **{k: round(v, 3) for k, v in decision.items()}},
        "hallucination_rate": round(sum(1 for p in pairs if p["hallucination"]) / n, 3),
    }

    # ---- bias by category ----
    report["by_category"] = _stratum_metrics(pairs, "category")
    # ---- bias by source ----
    report["by_source"] = _stratum_metrics(pairs, "source_id")
    # ---- bias by dimension ----
    report["by_dimension"] = _dimension_metrics(pairs)

    # ---- recommendations ----
    report["recommendations"] = _recommendations(pairs, report)

    verdict, detail = readiness_verdict(report["global"], n)
    report["readiness"] = {"verdict": verdict, "detail": detail}

    # top disagreements (for human review attention)
    ranked = sorted(pairs, key=lambda p: abs(p["auto"] - p["human"]), reverse=True)
    report["top_disagreements"] = [
        {"record_id": p["record_id"], "category": p["category"], "source_id": p["source_id"],
         "auto": p["auto"], "human": p["human"], "diff": p["auto"] - p["human"],
         "verdict": p["verdict"]}
        for p in ranked[: min(15, n)]
    ]
    return report


def _stratum_metrics(pairs: list[dict], key: str) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for p in pairs:
        groups[p[key]].append(p)
    out = {}
    for g, items in sorted(groups.items()):
        a = [p["auto"] for p in items]
        h = [p["human"] for p in items]
        d = [x - y for x, y in zip(a, h)]
        mae = mean([abs(x) for x in d])
        cm = confusion(a, h, ACCEPT_THRESHOLD)
        dec = prf(cm)
        bias = mean(d)
        conf = stratum_confidence(mae, len(items))
        out[g] = {
            "n": len(items),
            "auto_mean": round(mean(a), 2),
            "human_mean": round(mean(h), 2),
            "mean_bias": nz(round(bias, 3)),
            "mae": round(mae, 3),
            "within1_agree": round(sum(1 for x in d if abs(x) <= 1) / len(items), 3),
            "threshold_f1": round(dec["f1"], 3),
            "recommended_correction": nz(round(-bias, 3)),  # subtract bias to align to human
            "confidence": round(conf, 3),
            "gate": "MANDATORY_HUMAN_REVIEW" if (conf < STRATUM_CONF_FLOOR or abs(bias) >= BIAS_FLAG
                                                 or dec["f1"] < 0.70) else "AUTO_ALLOWED",
        }
    return out


def _dimension_metrics(pairs: list[dict]) -> dict:
    out = {}
    for dim in DIMS:
        a, h = [], []
        for p in pairs:
            av = p["auto_dims"].get(dim)
            hv = p["human_dims"].get(dim)
            if isinstance(av, (int, float)) and isinstance(hv, (int, float)):
                # auto_dims are 0..1; scale to 1..10 to match human 1..10 scale
                a.append(float(av) * 9.0 + 1.0)
                h.append(float(hv))
        if not a:
            continue
        d = [x - y for x, y in zip(a, h)]
        out[dim] = {
            "n": len(a),
            "auto_mean": round(mean(a), 2),
            "human_mean": round(mean(h), 2),
            "mean_bias": nz(round(mean(d), 3)),
            "mae": round(mean([abs(x) for x in d]), 3),
            "pearson_r": (round(pearson(a, h), 3) if pearson(a, h) is not None else None),
        }
    return out


def _recommendations(pairs: list[dict], report: dict) -> list[dict]:
    recs = []
    # per-stratum
    for scope, table in (("category", report["by_category"]), ("source", report["by_source"])):
        for name, m in table.items():
            if m["gate"] == "MANDATORY_HUMAN_REVIEW":
                recs.append({
                    "scope": scope, "target": name,
                    "action": "MANDATORY_HUMAN_REVIEW",
                    "reason": f"confidence={m['confidence']} (<{STRATUM_CONF_FLOOR}) "
                              f"or |bias|={abs(m['mean_bias'])} or threshold_f1={m['threshold_f1']} < 0.70",
                    "detail": "Do not bulk-ingest records in this stratum on auto-score; "
                              "require a human verdict before promotion.",
                })
            elif abs(m["mean_bias"]) >= BIAS_FLAG:
                recs.append({
                    "scope": scope, "target": name,
                    "action": "APPLY_ADDITIVE_CORRECTION",
                    "correction": m["recommended_correction"],
                    "reason": f"systematic bias mean(auto-human)={m['mean_bias']} (>= {BIAS_FLAG})",
                    "detail": f"Apply auto_score + ({m['recommended_correction']}) at ingestion "
                              f"time for this stratum, then re-verify on a fresh sample.",
                })
            else:
                recs.append({
                    "scope": scope, "target": name,
                    "action": "MONITOR",
                    "correction": 0.0,
                    "reason": f"bias={m['mean_bias']}, confidence={m['confidence']} within tolerance",
                    "detail": "No action; include in periodic re-calibration.",
                })
    # global, if a dimension is badly miscalibrated
    for dim, m in report["by_dimension"].items():
        if m["mae"] >= 2.0 and (m["pearson_r"] is None or m["pearson_r"] < 0.3):
            recs.append({
                "scope": "dimension", "target": dim,
                "action": "RETUNE_WEIGHT",
                "reason": f"dimension MAE={m['mae']}, pearson_r={m['pearson_r']} (heuristic weak here)",
                "detail": "Re-examine the heuristic for this dimension in quality_score.py; "
                          "consider a stronger signal or lowering its weight until improved.",
            })
    return recs


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def render_markdown(report: dict) -> str:
    L = []
    L.append("# Atlas Quality Calibration Report")
    L.append("")
    L.append(f"- Date: {report['date']}")
    L.append(f"- Reviews: {report['n_reviews']} (matched: {report['n_matched']}, "
             f"missing candidates: {report['n_missing_candidates']})")
    L.append(f"- Accept threshold: quality_score >= {report['accept_threshold']}")
    L.append("")
    g = report.get("global")
    if g is None:
        L.append("## Status: NO CALIBRATION DATA")
        L.append("")
        L.append("No matched human reviews. Run `python scripts/gen_calibration_sample.py` to "
                 "seed a structured review set, then re-run calibration.")
        return "\n".join(L)

    L.append("## Global Accuracy")
    L.append("")
    L.append(f"- MAE: **{g['mae']}**  RMSE: **{g['rmse']}**  Mean bias (auto-human): **{g['mean_bias']}**")
    L.append(f"- Exact agreement: {g['exact_agree']*100:.0f}%   Within-1 agreement: **{g['within1_agree']*100:.0f}%**")
    L.append(f"- Pearson r: {g['pearson_r']}   Spearman rho: {g['spearman_rho']}")
    L.append(f"- Auto mean: {g['auto_mean']}   Human mean: {g['human_mean']}")
    L.append(f"- Hallucination rate (human-flagged): {g['hallucination_rate']*100:.0f}%")
    t = g["threshold"]
    L.append("")
    L.append("### Accept/Reject Decision (threshold = %d)" % report["accept_threshold"])
    L.append(f"- Confusion: TP={t['tp']} FP={t['fp']} TN={t['tn']} FN={t['fn']}")
    L.append(f"- Precision: {t['precision']:.3f}  Recall: {t['recall']:.3f}  "
             f"F1: **{t['f1']:.3f}**  Accuracy: {t['accuracy']:.3f}")
    L.append("")

    L.append("## Readiness Verdict")
    L.append("")
    rd = report["readiness"]
    L.append(f"**{rd['verdict']}** — {rd['detail']}")
    L.append("")

    L.append("## Bias by Category")
    L.append("")
    L.append("| category | n | auto | human | bias | MAE | within-1 | F1 | conf | gate |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for k, m in report["by_category"].items():
        L.append(f"| {k} | {m['n']} | {m['auto_mean']} | {m['human_mean']} | {m['mean_bias']} | "
                 f"{m['mae']} | {m['within1_agree']} | {m['threshold_f1']} | {m['confidence']} | {m['gate']} |")
    L.append("")

    L.append("## Bias by Source")
    L.append("")
    L.append("| source | n | auto | human | bias | MAE | F1 | conf | gate |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for k, m in report["by_source"].items():
        L.append(f"| {k} | {m['n']} | {m['auto_mean']} | {m['human_mean']} | {m['mean_bias']} | "
                 f"{m['mae']} | {m['threshold_f1']} | {m['confidence']} | {m['gate']} |")
    L.append("")

    L.append("## Bias by Dimension")
    L.append("")
    L.append("| dimension | n | auto | human | bias | MAE | pearson_r |")
    L.append("|---|---|---|---|---|---|---|")
    for k, m in report["by_dimension"].items():
        L.append(f"| {k} | {m['n']} | {m['auto_mean']} | {m['human_mean']} | {m['mean_bias']} | "
                 f"{m['mae']} | {m['pearson_r']} |")
    L.append("")

    L.append("## Recommendations")
    L.append("")
    if not report["recommendations"]:
        L.append("_No recommendations (insufficient divergence)._")
    else:
        for r in report["recommendations"]:
            corr = f" correction={r.get('correction')}" if "correction" in r else ""
            L.append(f"- **[{r['action']}]** `{r['scope']}={r['target']}`{corr} — {r['reason']}")
    L.append("")

    if report.get("top_disagreements"):
        L.append("## Top Disagreements (review-priority)")
        L.append("")
        L.append("| record_id | category | source | auto | human | diff | verdict |")
        L.append("|---|---|---|---|---|---|---|")
        for p in report["top_disagreements"]:
            L.append(f"| {p['record_id']} | {p['category']} | {p['source_id']} | "
                     f"{p['auto']} | {p['human']} | {p['diff']:+d} | {p['verdict']} |")
        L.append("")
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Atlas quality-calibration framework.")
    ap.add_argument("--reviews", default=str(ROOT / "review_queue" / "quality_reviews.jsonl"),
                    help="structured human-review JSONL (schema: quality_review_schema.json)")
    ap.add_argument("--candidates", default=str(ROOT / "curated" / "v0.1" / "pilot_candidates.jsonl"),
                    help="canonical candidate records to join auto-scores against")
    ap.add_argument("--report-out", default=None, help="write machine-readable JSON report here")
    ap.add_argument("--md-out", default=None, help="write markdown digest here")
    args = ap.parse_args(argv)

    reviews = load_jsonl(Path(args.reviews))
    candidates = load_jsonl(Path(args.candidates))

    report = calibrate(reviews, candidates)

    # console summary
    print("=" * 64)
    print("ATLAS QUALITY CALIBRATION")
    print("=" * 64)
    print(f"reviews={report['n_reviews']} matched={report['n_matched']} "
          f"missing={report['n_missing_candidates']}")
    g = report.get("global")
    if g is None:
        print("STATUS: NO CALIBRATION DATA — seed reviews then re-run.")
    else:
        print(f"MAE={g['mae']}  within-1={g['within1_agree']*100:.0f}%  "
              f"threshold_F1={g['threshold']['f1']:.3f}  bias={g['mean_bias']:+}")
        print(f"READINESS: {report['readiness']['verdict']}")
        print(f"recommendations: {len(report['recommendations'])}")
    print("=" * 64)

    if args.report_out:
        Path(args.report_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"[calibrate] wrote report -> {args.report_out}")
    if args.md_out:
        Path(args.md_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md_out).write_text(render_markdown(report), encoding="utf-8")
        print(f"[calibrate] wrote digest -> {args.md_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
