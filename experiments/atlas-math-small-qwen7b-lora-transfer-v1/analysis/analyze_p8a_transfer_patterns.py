#!/usr/bin/env python3
"""
analyze_p8a_transfer_patterns.py — P8-A.1 transfer pattern analysis.

READ-ONLY on all inputs; writes experiments/atlas-math-small-qwen7b-lora-transfer-v1/analysis/patterns/.
No training, no dataset modification, no QEE modification.

For EVERY code_eval_v1 example, computes objective patch-structure signals
using the frozen QEE v2 code_eval helpers (is_patch / extract_added_lines /
patch_similarity), joins the P8-A post-training and Phase 6.3 baseline
per-example results, and emits:

  - per-example signal table (JSONL)
  - category summary (baseline / post / delta / improved / regressed / unchanged)
  - regression clustering inputs
  - improvement clustering inputs

Failure-mode signals per example:
  candidate_is_patch     candidate is a unified diff (vs prose)
  file_path_match        candidate --- a/<path> equals reference --- a/<path>
  added_line_overlap     patch_similarity (same metric as the scorer)
  count_ratio            candidate added-line count / reference added-line count
  candidate_added_lines  count of candidate + lines
  reference_added_lines  count of reference + lines
  hunk_count             number of @@ hunk headers in candidate
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts"))
from evaluation_engine.v2.code_eval import (  # noqa: E402
    extract_added_lines,
    is_patch,
    patch_similarity,
)

EXP = REPO / "experiments" / "atlas-math-small-qwen7b-lora-transfer-v1"
POST_EXAMPLE = EXP / "evaluation" / "post_training_per_example.jsonl"
BASE_EXAMPLE = REPO / "experiments" / "phase6_baseline_eval" / "per_example_results.jsonl"
EVAL_RECORDS = REPO / "evaluation" / "eval_sets" / "phase6_expansion_v1" / "code_eval_v1.jsonl"
OUT_DIR = EXP / "analysis" / "patterns"


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def first_path(patch: str) -> str | None:
    for line in (patch or "").splitlines():
        if line.startswith("--- a/"):
            return line[6:].strip()
    return None


def hunk_count(patch: str) -> int:
    return sum(1 for ln in (patch or "").splitlines() if ln.startswith("@@ "))


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    post = {r["record_id"]: r for r in load_jsonl(POST_EXAMPLE)}
    base = {r["record_id"]: r for r in load_jsonl(BASE_EXAMPLE)
            if r.get("view_id") == "code-300m"}
    records = {r["record_id"]: r for r in load_jsonl(EVAL_RECORDS)}

    rows = []
    for rid in sorted(post):
        p = post[rid]
        b = base.get(rid)
        rec = records.get(rid)
        if b is None:
            continue
        cand = p.get("predicted_response") or ""
        ref = p.get("reference_answer") or ""
        base_cand = b.get("predicted_response") or ""
        verif = (rec or {}).get("verification_evidence") or {}
        delta = round(p["correctness"] - b["correctness"], 4)
        if delta > 0.05:
            cls = "improved"
        elif delta < -0.05:
            cls = "regressed"
        else:
            cls = "unchanged"
        rows.append({
            "record_id": rid,
            "category": p.get("category"),
            "difficulty": p.get("difficulty"),
            "baseline_correctness": b["correctness"],
            "post_correctness": p["correctness"],
            "delta_correctness": delta,
            "classification": cls,
            "signals": {
                "candidate_is_patch": is_patch(cand),
                "base_candidate_is_patch": is_patch(base_cand),
                "candidate_file_path": first_path(cand),
                "reference_file_path": first_path(ref),
                "file_path_match": first_path(cand) == first_path(ref),
                "added_line_overlap": round(patch_similarity(ref, cand), 4),
                "count_ratio": round(len(extract_added_lines(cand)) /
                                     max(len(extract_added_lines(ref)), 1), 4),
                "candidate_added_lines": len(extract_added_lines(cand)),
                "reference_added_lines": len(extract_added_lines(ref)),
                "hunk_count": hunk_count(cand),
                "tokens_generated": p.get("tokens_generated"),
                "response_len": len(cand),
            },
            "verification": {
                "has_patch": verif.get("has_patch"),
                "has_test_patch": verif.get("has_test_patch"),
                "fail_to_pass_count": verif.get("fail_to_pass_count"),
                "pass_to_pass_count": verif.get("pass_to_pass_count"),
            },
        })

    with (OUT_DIR / "per_example_signals.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ---- category summary ----
    by_cat = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r)
    cat_summary = {}
    for cat, rs in sorted(by_cat.items()):
        n = len(rs)
        cc = Counter(r["classification"] for r in rs)
        cat_summary[cat] = {
            "n": n,
            "baseline_correctness": round(sum(r["baseline_correctness"] for r in rs) / n, 4),
            "post_correctness": round(sum(r["post_correctness"] for r in rs) / n, 4),
            "delta": round((sum(r["post_correctness"] for r in rs)
                            - sum(r["baseline_correctness"] for r in rs)) / n, 4),
            "improved": cc.get("improved", 0),
            "regressed": cc.get("regressed", 0),
            "unchanged": cc.get("unchanged", 0),
        }

    summary = {
        "n": len(rows),
        "category_summary": cat_summary,
        "global": {
            "candidate_is_patch": Counter(r["signals"]["candidate_is_patch"] for r in rows),
            "base_candidate_is_patch": Counter(r["signals"]["base_candidate_is_patch"] for r in rows),
        },
        "regressions": [r["record_id"] for r in rows if r["classification"] == "regressed"],
        "improvements": [r["record_id"] for r in rows if r["classification"] == "improved"],
    }
    out = OUT_DIR / "p8a_pattern_summary.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"n={len(rows)}")
    for cat, s in cat_summary.items():
        print(f"  {cat:<20} n={s['n']:>2} base={s['baseline_correctness']:.3f} "
              f"post={s['post_correctness']:.3f} delta={s['delta']:+.4f} "
              f"imp={s['improved']} reg={s['regressed']} unc={s['unchanged']}")
    print("candidate_is_patch:", dict(summary["global"]["candidate_is_patch"]))
    print("base_candidate_is_patch:", dict(summary["global"]["base_candidate_is_patch"]))
    print("wrote", out.relative_to(REPO))


if __name__ == "__main__":
    main()
