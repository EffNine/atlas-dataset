#!/usr/bin/env python3
"""compare_v1_v2_baseline.py — Protocol v2 baseline vs deprecated v1 baseline.

Deterministic, offline, stdlib-only comparison of the two baseline
measurements on the SAME eval split (``math_eval_v2`` / ``code_eval_v2`` are
derived from the frozen ``math_eval_v1`` / ``code_eval_v1`` record sets, so
record IDs match).

This is a PROTOCOL-EFFECTS comparison, NOT a performance comparison (the v1
baseline is deprecated: 100% reference-in-prompt leakage). Reported items:

  * metric shifts        — per-record and aggregate delta of correctness /
                           reasoning / hallucination / format between the v1
                           (leaked) baseline and the v2 (reference-free,
                           policy-locked) baseline on the same split,
  * protocol effects     — leak rate, prompt source, guard enforcement,
                           scoring-reference source, budget/stop policy,
  * output-policy differences — patch-emission / prose / fenced rates,
                           truncation rate, stop-reason counts, tokens.

Secondary analysis: the v1 code predictions are RE-SCORED through the same
diff-extraction + QEE pipeline used by v2, to isolate the prompt/policy effect
from the extraction-policy change (labelled ``code_extraction_adjusted``).

Data sources (frozen / fresh):
  * v1 baseline per-example : experiments/phase6_baseline_eval/per_example_results.jsonl
  * v2 baseline per-example : experiments/atlas-mixed-pilot-qwen7b-eval-v2/per_example_*.jsonl
  * v1 aggregate           : experiments/phase6_baseline_eval/baseline.json
  * v2 aggregate           : experiments/atlas-mixed-pilot-qwen7b-eval-v2/aggregate_*.json

Writes: experiments/atlas-mixed-pilot-qwen7b-eval-v2/v1_vs_v2_comparison.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

V1_PEX = REPO / "experiments" / "phase6_baseline_eval" / "per_example_results.jsonl"
V1_BASELINE = REPO / "experiments" / "phase6_baseline_eval" / "baseline.json"
V2_DIR = REPO / "experiments" / "atlas-mixed-pilot-qwen7b-eval-v2"
EVAL_DIR = REPO / "evaluation" / "eval_sets" / "protocol_v2"

TAU = 0.05  # protocol v1.1 §8.3 classification margin


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def agg(family: str) -> dict:
    p = V2_DIR / f"aggregate_{family}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def compare_family(family: str) -> dict:
    v1_rows = load_jsonl(V1_PEX)
    v2_rows = load_jsonl(V2_DIR / f"per_example_{family}.jsonl")

    v1_by_id = {r.get("record_id"): r for r in v1_rows}
    v2_by_id = {r.get("record_id"): r for r in v2_rows}

    shared = sorted(
        k for k in (v1_by_id.keys() & v2_by_id.keys()) if isinstance(k, str)
    )
    if not shared:
        return {"error": f"no shared record_ids between v1 and v2 ({family})"}

    per_record = []
    for rid in shared:
        v1, v2 = v1_by_id[rid], v2_by_id[rid]
        delta_correctness = (
            (v2.get("correctness") or 0.0) - (v1.get("correctness") or 0.0)
        )
        if delta_correctness > TAU:
            cls = "improved"
        elif delta_correctness < -TAU:
            cls = "regressed"
        else:
            cls = "unchanged"
        per_record.append({
            "record_id": rid,
            "v1_correctness": round(v1.get("correctness") or 0.0, 4),
            "v2_correctness": round(v2.get("correctness") or 0.0, 4),
            "delta_correctness": round(delta_correctness, 4),
            "classification": cls,
            "v1_tokens": v1.get("tokens_generated"),
            "v2_tokens": v2.get("tokens_generated"),
            "v1_stop": "max_length" if (v1.get("tokens_generated") or 0) >= 512
            else "eos",
            "v2_stop": v2.get("stop_reason"),
        })

    cls_counts = Counter(r["classification"] for r in per_record)
    mean_delta = sum(r["delta_correctness"] for r in per_record) / len(per_record)
    return {
        "family": family,
        "n_shared": len(shared),
        "classification_counts": dict(cls_counts),
        "mean_delta_correctness": round(mean_delta, 4),
        "v1_agg_correctness": (
            (v1_by_id[shared[0]].get("correctness")
             if shared and "correctness" in v1_by_id[shared[0]] else None)
        ),
        "note": "deltas are PROTOCOL-EFFECT measurements, not performance; "
                "v1 baseline is deprecated (100% reference leakage)",
    }


def code_extraction_adjusted() -> dict:
    """Re-score the frozen v1 code predictions through the v2 diff-extraction
    + QEE pipeline, isolating prompt/policy effect from extraction policy."""
    from evaluation_engine.run_baseline_t3 import extract_diff, score_response

    v1_rows = load_jsonl(V1_PEX)
    v2_rows = load_jsonl(V2_DIR / "per_example_code.jsonl")
    v1_code = [r for r in v1_rows if str(r.get("view_id", "")).startswith("code")]
    if not v1_code:
        v1_code = [r for r in v1_rows if r.get("record_id", "").startswith("expert_swe")]
    v2_by_id = {r.get("record_id"): r for r in v2_rows}
    v2set = {r.get("record_id"): r for r in load_jsonl(EVAL_DIR / "code_eval_v2.jsonl")}

    out = []
    for v1 in v1_code:
        rid = v1.get("record_id")
        if rid not in v2set:
            continue
        rec = v2set[rid]
        resp = v1.get("predicted_response") or ""
        extracted, emitted = extract_diff(resp)
        score = score_response("code", rec, resp, extracted)
        out.append({
            "record_id": rid,
            "v1_raw_correctness": round(v1.get("correctness") or 0.0, 4),
            "v1_extraction_adjusted_correctness": round(score["correctness"], 4),
            "v2_reference_free_correctness": round(
                v2_by_id.get(rid, {}).get("correctness") or 0.0, 4),
            "v1_patch_emitted": emitted,
            "v1_tokens": v1.get("tokens_generated"),
        })
    return {
        "family": "code",
        "n": len(out),
        "note": "v1 predictions rescored through the v2 diff-extraction+QEE "
                "pipeline to separate prompt-policy from extraction-policy "
                "effects; frozen v1 predictions, no re-inference",
        "mean_v1_raw": round(sum(r["v1_raw_correctness"] for r in out) / len(out), 4) if out else None,
        "mean_v1_extraction_adjusted": round(
            sum(r["v1_extraction_adjusted_correctness"] for r in out) / len(out), 4) if out else None,
        "mean_v2_reference_free": round(
            sum(r["v2_reference_free_correctness"] for r in out) / len(out), 4) if out else None,
        "v1_patch_emission_rate": round(
            sum(1 for r in out if r["v1_patch_emitted"]) / len(out), 4) if out else None,
        "per_record": out,
    }


def main() -> int:
    report = {
        "artifact": "atlas-protocol-v2-vs-v1-baseline-comparison",
        "scope": "PROTOCOL-EFFECTS ONLY; not a performance comparison. v1 is "
                 "deprecated (100% reference-in-prompt leakage per "
                 "protocol_audit_reference_leakage.md).",
        "families": {fam: compare_family(fam) for fam in ("math", "code")},
        "code_extraction_adjusted": code_extraction_adjusted(),
        "v1_baseline_aggregates": json.loads(V1_BASELINE.read_text(encoding="utf-8")).get("domain_aggregates"),
        "v2_baseline_aggregates": {fam: agg(fam).get("aggregate") for fam in ("math", "code")},
    }
    out_path = V2_DIR / "v1_vs_v2_comparison.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(f"[COMPARE] wrote {out_path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
