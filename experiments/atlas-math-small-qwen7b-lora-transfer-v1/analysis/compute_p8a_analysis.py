#!/usr/bin/env python3
"""
compute_p8a_analysis.py — Atlas P8-A cross-domain transfer analysis.

Reads the P8-A post-training code evaluation and the Phase 6.3 same-split
baseline, then produces:

  - baseline comparison (aggregate + per-example deltas)
  - transfer delta (delta_cross^{M->C})
  - per-example analysis (improved / regressed / unchanged)
  - positive / neutral / negative transfer classification (protocol v1.1 S8.3)
  - transfer ratio TR_{M->C} (N/A HOLD: in-domain gain not measured because
    evaluation is restricted to code_eval_v1 per mission scope)
  - regression analysis
  - final answer reliability (code: patch-format + extraction reliability)

Deterministic, stdlib-only. READ-ONLY on inputs; writes analysis/ only.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path("/mnt/d/atlas-dataset")
EXP = REPO / "experiments" / "atlas-math-small-qwen7b-lora-transfer-v1"
POST_EXAMPLE = EXP / "evaluation" / "post_training_per_example.jsonl"
BASELINE_EXAMPLE = REPO / "experiments" / "phase6_baseline_eval" / "per_example_results.jsonl"
POST_AGG = EXP / "evaluation" / "post_training.json"
OUT_DIR = EXP / "analysis"

TAU = 0.05
METRICS = ["correctness", "reasoning_quality", "hallucination_rate",
           "answer_format_consistency"]


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def agg(rows: list[dict]) -> dict:
    n = len(rows) or 1
    return {
        "correctness": round(sum(r["correctness"] for r in rows) / n, 4),
        "reasoning_quality": round(sum(r["reasoning_quality"] for r in rows) / n, 4),
        "hallucination_rate": round(sum(r["hallucination_rate"] for r in rows) / n, 4),
        "answer_format_consistency": round(
            sum(r["answer_format_consistency"] for r in rows) / n, 4),
        "evaluated_examples": len(rows),
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    post_rows = load_jsonl(POST_EXAMPLE)
    baseline_rows = [r for r in load_jsonl(BASELINE_EXAMPLE)
                     if r.get("view_id") == "code-300m"]

    post_valid = [r for r in post_rows if r.get("correctness") is not None]
    base_valid = [r for r in baseline_rows if r.get("correctness") is not None]
    if not post_valid or not base_valid:
        raise SystemExit("missing valid per-example rows (post or baseline)")

    base_by_id = {r["record_id"]: r for r in base_valid}
    post_by_id = {r["record_id"]: r for r in post_valid}
    common = sorted(set(base_by_id) & set(post_by_id))

    if len(common) != 100:
        print(f"WARNING: common eval records = {len(common)} (expected 100)")

    # ---- baseline comparison (aggregate) ----
    baseline_agg = agg([base_by_id[c] for c in common])
    post_agg = agg([post_by_id[c] for c in common])

    # ---- transfer delta ----
    delta = {}
    for m in METRICS:
        b = baseline_agg[m]
        p = post_agg[m]
        delta[m] = round(p - b, 4)

    delta_cross = delta["correctness"]

    # ---- per-example analysis ----
    per_example = []
    for rid in common:
        b = base_by_id[rid]
        p = post_by_id[rid]
        d = round(p["correctness"] - b["correctness"], 4)
        if d > TAU:
            cls = "improved"
        elif d < -TAU:
            cls = "regressed"
        else:
            cls = "unchanged"
        per_example.append({
            "record_id": rid,
            "category": b.get("category"),
            "difficulty": b.get("difficulty"),
            "baseline_correctness": b["correctness"],
            "post_correctness": p["correctness"],
            "delta_correctness": d,
            "classification": cls,
            "baseline_method": b.get("v2", {}).get("method"),
            "post_method": p.get("v2", {}).get("method"),
        })

    cls_counts = Counter(e["classification"] for e in per_example)
    improved_ids = sorted(e["record_id"] for e in per_example if e["classification"] == "improved")
    regressed_ids = sorted(e["record_id"] for e in per_example if e["classification"] == "regressed")
    unchanged_ids = sorted(e["record_id"] for e in per_example if e["classification"] == "unchanged")

    top_gains = sorted(per_example, key=lambda e: -e["delta_correctness"])[:10]
    top_regressions = sorted(per_example, key=lambda e: e["delta_correctness"])[:10]

    # ---- transfer type (protocol v1.1 S8.3, tau = 0.05) ----
    if delta_cross >= TAU and cls_counts["improved"] > cls_counts["regressed"]:
        transfer_type = "positive"
    elif delta_cross <= -TAU and cls_counts["regressed"] > cls_counts["improved"]:
        transfer_type = "negative"
    elif abs(delta_cross) < TAU:
        transfer_type = "neutral"
    else:
        transfer_type = "UNDETERMINED"

    # ---- transfer ratio (HOLD: in-domain gain not measured) ----
    transfer_ratio = {
        "value": None,
        "status": "N/A (HOLD)",
        "reason": ("delta_in^M (in-domain gain on math_eval_v1) is not measured "
                   "because P8-A evaluation is restricted to code_eval_v1 only. "
                   "TR = delta_cross / delta_in is therefore undefined; fail-closed."),
    }

    # ---- regression analysis ----
    regressions = {
        "count": cls_counts["regressed"],
        "mean_delta_of_regressed": round(
            statistics.mean(e["delta_correctness"] for e in per_example
                            if e["classification"] == "regressed"), 4) if cls_counts["regressed"] else None,
        "max_regression": min((e["delta_correctness"] for e in per_example), default=0.0),
        "records": regressed_ids,
    }
    # correlation between difficulty and delta
    diff_delta = {}
    for e in per_example:
        d = str(e["difficulty"])
        diff_delta.setdefault(d, []).append(e["delta_correctness"])
    regression_by_difficulty = {
        d: round(sum(vals) / len(vals), 4) for d, vals in sorted(diff_delta.items())
    }

    # ---- final answer reliability (code) ----
    post_methods = Counter(p.get("v2", {}).get("method") for p in post_valid)
    patch_like = sum(1 for p in post_valid
                     if p.get("v2", {}).get("method") in ("patch", "syntax_structural",
                                                          "syntax_structural_tests", "text_similarity"))
    final_answer_reliability = {
        "method_distribution": dict(sorted(post_methods.items())),
        "patch_or_similarity_fraction": round(patch_like / len(post_valid), 4) if post_valid else None,
        "format_consistency": post_agg["answer_format_consistency"],
        "note": ("code answers are scored by patch added-line similarity / structural "
                 "similarity, not final-answer extraction; format_consistency and "
                 "patch-production fraction are the reliability proxies."),
    }

    report = {
        "experiment_id": "atlas-math-small-qwen7b-lora-transfer-v1",
        "sprint": "P8-A",
        "direction": "Math -> Code",
        "research_question": "RQ1: Does math-domain instruction tuning improve code evaluation performance?",
        "tau": TAU,
        "n_eval": len(common),
        "baseline_aggregate": baseline_agg,
        "post_training_aggregate": post_agg,
        "delta": delta,
        "delta_cross_m_to_c": delta_cross,
        "per_example_classification_counts": dict(cls_counts),
        "improved_ids": improved_ids,
        "regressed_ids": regressed_ids,
        "unchanged_ids": unchanged_ids,
        "top_gains": top_gains,
        "top_regressions": top_regressions,
        "transfer_type": transfer_type,
        "transfer_ratio": transfer_ratio,
        "regression_analysis": {
            "regression_by_difficulty": regression_by_difficulty,
            **regressions,
        },
        "final_answer_reliability": final_answer_reliability,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    out = OUT_DIR / "p8a_transfer_analysis.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (OUT_DIR / "p8a_per_example_deltas.jsonl").open("w", encoding="utf-8") as f:
        for e in per_example:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    print(f"baseline: {baseline_agg}")
    print(f"post:     {post_agg}")
    print(f"delta:    {delta}")
    print(f"delta_cross M->C = {delta_cross}")
    print(f"classification: {dict(cls_counts)}")
    print(f"transfer_type: {transfer_type}")
    print(f"transfer_ratio: {transfer_ratio['value']} ({transfer_ratio['status']})")
    print(f"wrote {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
