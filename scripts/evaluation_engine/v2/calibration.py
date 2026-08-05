"""calibration.py — v1-vs-v2 before/after comparison and calibration fitting.

Phase 5A.2 deliverable tooling:

* Recompute QEE v1 metrics on human-reviewed records (the "before").
* Compute QEE v2 metrics — raw rubric correctness and calibrated mapping
  (the "after").
* Fit a deterministic affine calibration (raw continuous -> human-aligned
  continuous) and evaluate it with leave-one-out cross-validation so reported
  agreement is an honest out-of-sample estimate, not a circular in-sample fit.

Calibration is a *measurement and fitting tool* only: Atlas still requires
human approval for every release. The fitted parameters must be re-validated
against fresh human review before any automated gate uses them.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]  # <repo>/scripts/evaluation_engine/v2 -> repo
SCRIPTS = ROOT / "scripts"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from .engine import QeeV2Engine  # noqa: E402


def load_v1_engine():
    """Load scripts/quality_score.py (v1) without importing it as a package."""
    spec = importlib.util.spec_from_file_location(
        "quality_score", SCRIPTS / "quality_score.py")
    if spec is None or spec.loader is None:
        raise ImportError("cannot locate scripts/quality_score.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_jsonl(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def matched_pairs(records: list[dict], reviews: list[dict],
                  reviewer: str | None = "AR") -> list[tuple[dict, dict]]:
    """Return (record, review) pairs for records present in both inputs."""
    by_id = {r.get("id"): r for r in records}
    pairs = []
    for rev in reviews:
        if reviewer and rev.get("reviewer") != reviewer:
            continue
        rec = by_id.get(rev.get("record_id"))
        if rec is not None:
            pairs.append((rec, rev))
    return pairs


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
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
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    return pearson(_ranks(xs), _ranks(ys))


def compute_metrics(auto: list[int], human: list[int],
                    threshold: int = 7) -> dict[str, Any]:
    """Compute the standard alignment metric set (matches calibration_report)."""
    n = len(auto)
    diffs = [a - h for a, h in zip(auto, human)]
    mae = sum(abs(d) for d in diffs) / n if n else 0.0
    rmse = math.sqrt(sum(d * d for d in diffs) / n) if n else 0.0
    exact = sum(1 for d in diffs if d == 0) / n if n else 0.0
    within1 = sum(1 for d in diffs if abs(d) <= 1) / n if n else 0.0
    bias = sum(diffs) / n if n else 0.0
    tp = fp = tn = fn = 0
    for a, h in zip(auto, human):
        if h >= threshold and a >= threshold:
            tp += 1
        elif h >= threshold and a < threshold:
            fn += 1
        elif h < threshold and a >= threshold:
            fp += 1
        else:
            tn += 1
    from collections import Counter
    auto_dist = {str(k): v for k, v in sorted(Counter(auto).items())}
    human_dist = {str(k): v for k, v in sorted(Counter(human).items())}
    r = pearson([float(x) for x in auto], [float(x) for x in human])
    rho = spearman([float(x) for x in auto], [float(x) for x in human])
    return {
        "n": n,
        "auto_mean": round(sum(auto) / n, 3) if n else 0.0,
        "human_mean": round(sum(human) / n, 3) if n else 0.0,
        "mean_bias": round(bias, 3),
        "mae": round(mae, 3),
        "rmse": round(rmse, 3),
        "exact_agree": round(exact, 3),
        "within1_agree": round(within1, 3),
        "pearson_r": (round(r, 3) if r is not None else None),
        "spearman_rho": (round(rho, 3) if rho is not None else None),
        "false_approvals": fp,
        "false_rejections": fn,
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "auto_distribution": auto_dist,
        "human_distribution": human_dist,
        "distinct_auto_scores": len(set(auto)),
    }


# --------------------------------------------------------------------------- #
# Calibration fitting
# --------------------------------------------------------------------------- #
def fit_affine(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Least-squares fit y = slope*x + intercept. Degenerate -> (1, 0)."""
    n = len(xs)
    if n < 2:
        return 1.0, 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx <= 1e-12:
        return 1.0, 0.0
    slope = sxy / sxx
    intercept = my - slope * mx
    return slope, intercept


def clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def v1_scores(records: list[dict], reviews: list[dict],
              reviewer: str = "AR") -> list[int]:
    """QEE v1 integer scores for the matched pairs."""
    v1 = load_v1_engine()
    pairs = matched_pairs(records, reviews, reviewer)
    return [v1.score_record(rec)[0] for rec, _ in pairs]


def v2_raw_scores(records: list[dict], reviews: list[dict],
                  engine: QeeV2Engine | None = None,
                  reviewer: str = "AR") -> list[int]:
    """QEE v2 scores without calibration (logistic spread only)."""
    engine = engine or QeeV2Engine()
    pairs = matched_pairs(records, reviews, reviewer)
    return [engine.score_record(rec)[0] for rec, _ in pairs]


def v2_loo_calibrated(records: list[dict], reviews: list[dict],
                      engine: QeeV2Engine | None = None,
                      reviewer: str = "AR",
                      threshold: int = 7) -> dict[str, Any]:
    """Leave-one-out calibrated v2 scores.

    For each record, the affine calibration is fit on the other 99 pairs and
    applied to this record, so the reported agreement is out-of-sample.
    Returns a dict with predicted scores, fitted params, and metrics.
    """
    engine = engine or QeeV2Engine()
    pairs = matched_pairs(records, reviews, reviewer)
    raws = [engine.evaluate_record(rec)["raw_continuous"] for rec, _ in pairs]
    humans = [int(rev["human_score"]) for _, rev in pairs]
    ys = [(h - 1) / 9.0 for h in humans]

    predicted: list[int] = []
    for i in range(len(pairs)):
        train_x = raws[:i] + raws[i + 1:]
        train_y = ys[:i] + ys[i + 1:]
        slope, intercept = fit_affine(train_x, train_y)
        continuous = clamp01(raws[i] * slope + intercept)
        predicted.append(int(max(1, min(10, round(1 + continuous * 9)))))

    full_slope, full_intercept = fit_affine(raws, ys)
    return {
        "predicted_scores": predicted,
        "human_scores": humans,
        "fitted_calibration": {
            "slope": round(full_slope, 4),
            "intercept": round(full_intercept, 4),
            "note": "full-sample fit; for deployment re-validate on fresh "
                    "human review before enabling an automated gate",
        },
        "metrics": compute_metrics(predicted, humans, threshold=threshold),
    }


def calibrate_record(rec: dict, engine: QeeV2Engine,
                     slope: float, intercept: float) -> int:
    """Apply an explicit calibration to a single record (for testing)."""
    raw = engine.evaluate_record(rec)["raw_continuous"]
    continuous = clamp01(raw * slope + intercept)
    return int(max(1, min(10, round(1 + continuous * 9))))
