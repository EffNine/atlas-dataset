#!/usr/bin/env python3
"""qee_vs_human.py — Phase 6.3 QEE v2 vs human(proxy) calibration comparison.

Reads:
  - baseline per-example QEE v2 scores (experiments/phase6_baseline_eval/per_example_results.jsonl)
  - AI-reviewer proxy human labels (tmp, injected into calibration set)

Computes per-family and combined:
  - Pearson correlation (QEE quality_score vs human_score)
  - MAE (on 0-10 scale)
  - bias (mean QEE - mean human)
  - agreement at approve/reject threshold (>=7)
  - disagreement cases (top abs diff)

No QEE scoring logic is modified. This is analysis only.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

REPO = Path("/mnt/d/atlas-dataset")
PER_EXAMPLE = REPO / "experiments" / "phase6_baseline_eval" / "per_example_results.jsonl"
LABELS_PATH = Path("/tmp/p6b3_labels.json")


def load_rows():
    rows = []
    with PER_EXAMPLE.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def pearson(xs, ys):
    n = len(xs)
    if n == 0:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def analyze(rows, labels, name):
    pairs = []
    for r in rows:
        rid = r.get("record_id")
        if rid not in labels:
            continue
        qee = r.get("v2", {}).get("quality_score")
        human = labels[rid]
        if qee is None:
            continue
        pairs.append({
            "record_id": rid, "family": name, "category": r.get("category"),
            "qee_quality": qee, "qee_correctness": r.get("correctness"),
            "human_score": human,
            "human_verdict": "approve" if human >= 7 else "reject",
            "qee_verdict": "approve" if qee >= 7 else "reject",
        })
    n = len(pairs)
    qee_scores = [p["qee_quality"] for p in pairs]
    human_scores = [p["human_score"] for p in pairs]
    corr = pearson(qee_scores, human_scores)
    mae = sum(abs(a - b) for a, b in zip(qee_scores, human_scores)) / n
    bias = (sum(qee_scores) / n) - (sum(human_scores) / n)

    # threshold agreement (approve/reject at >= 7)
    agree = sum(1 for p in pairs if p["qee_verdict"] == p["human_verdict"])
    fa = [p["record_id"] for p in pairs if p["qee_verdict"] == "approve" and p["human_verdict"] == "reject"]
    fr = [p["record_id"] for p in pairs if p["qee_verdict"] == "reject" and p["human_verdict"] == "approve"]

    # disagreement cases: abs diff >= 4
    dis = sorted(pairs, key=lambda p: abs(p["qee_quality"] - p["human_score"]), reverse=True)

    return {
        "name": name, "n": n,
        "qee_mean": round(sum(qee_scores) / n, 3),
        "human_mean": round(sum(human_scores) / n, 3),
        "bias_qee_minus_human": round(bias, 3),
        "mae": round(mae, 3),
        "pearson_correlation": round(corr, 3) if corr is not None else None,
        "threshold_agreement_pct": round(100 * agree / n, 1) if n else None,
        "false_approvals": len(fa), "false_approval_ids": fa,
        "false_rejections": len(fr), "false_rejection_ids": fr,
        "disagreement_cases": [
            {"record_id": p["record_id"], "qee": p["qee_quality"], "human": p["human_score"]}
            for p in dis if abs(p["qee_quality"] - p["human_score"]) >= 4
        ],
        "score_dist": {
            "qee": dict(sorted(Counter(qee_scores).items())),
            "human": dict(sorted(Counter(human_scores).items())),
        },
    }


def main():
    rows = load_rows()
    labels = json.loads(LABELS_PATH.read_text())
    print(f"baseline rows: {len(rows)}, labels: {len(labels)}")

    math_rows = [r for r in rows if r.get("view_id") == "math-300m"]
    code_rows = [r for r in rows if r.get("view_id") == "code-300m"]

    result = {
        "phase": "6.3",
        "label_source": "ai-reviewer:hermes/deepseek-v4-flash (PROXY human judgement)",
        "label_scope": "30 math + 30 code samples",
        "math": analyze(math_rows, labels, "math"),
        "code": analyze(code_rows, labels, "code"),
        "combined": analyze(rows, labels, "combined"),
    }
    out = REPO / "experiments" / "phase6_baseline_eval" / "qee_vs_human.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
