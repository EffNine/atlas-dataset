"""Human-vs-AI review calibration for SFT records.

Compares human decisions (review_ui.py decision JSONL) against AI reviews
(ai_reviewer.py normalized JSONL) over the same records and reports:

- verdict agreement rate
- false accept rate  (AI accepted what the human did not accept)
- false reject rate  (AI rejected what the human accepted)
- score delta        (AI 0-10 vs human dimension-derived proxy)
- confidence distribution of matched AI reviews
- per-record disagreement list

Both sides are normalized through review_mode.py so legacy human verdicts
(KEEP/REVISE/REJECT + dimensions) and AI results share one contract.
Sample sizes are NOT policy here: humans only ever review the sample
produced by expert_pipeline.review_sample (configurable --rate/--domain-rates).

Usage:
  PYTHONPATH=scripts python -m expert_pipeline.calibration \
      --human review/..._review_decisions.jsonl \
      --ai   metadata/sft_review/<tag>/ai_reviews.jsonl \
      --report-out metadata/sft_review/<tag>/calibration_report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import review_mode as rm


def load_jsonl(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def normalize_entry(entry: dict) -> dict:
    """Return the normalized contract for either mode."""
    mode = entry.get("review_mode")
    if mode == rm.REVIEW_MODE_AI:
        return entry
    return rm.normalize_human_decision(entry)


def _human_overall(norm: dict) -> int | None:
    q = norm.get("quality_score")
    if isinstance(q, int):
        return q
    return None


def compare(human_entries: list[dict], ai_entries: list[dict]) -> dict:
    """Build the calibration report from both decision sets."""
    ai_by_id = {}
    for e in ai_entries:
        rid = e.get("record_id")
        if rid:
            ai_by_id[rid] = e
    human_by_id = {}
    for e in human_entries:
        rid = e.get("record_id")
        if rid:
            # keep latest decision per record (append-only files)
            human_by_id[rid] = e

    matched_ids = sorted(set(human_by_id) & set(ai_by_id))
    agree = 0
    false_accepts = []
    false_rejects = []
    other_disagreements = []
    deltas: list[int] = []
    confidences: list[float] = []

    for rid in matched_ids:
        h = normalize_entry(human_by_id[rid])
        a = normalize_entry(ai_by_id[rid])
        hv, av = h.get("decision"), a.get("decision")
        if av is not None and isinstance(a.get("confidence"), (int, float)):
            confidences.append(float(a["confidence"]))
        hq = _human_overall(h)
        aq = a.get("quality_score")
        if isinstance(hq, int) and isinstance(aq, int):
            deltas.append(aq - hq)
        if hv == av:
            agree += 1
            continue
        item = {
            "record_id": rid,
            "human_decision": hv,
            "ai_decision": av,
            "ai_confidence": a.get("confidence"),
            "ai_quality_score": aq,
            "human_quality_score": hq,
        }
        if av == rm.DECISION_ACCEPT and hv != rm.DECISION_ACCEPT:
            false_accepts.append(item)
        elif av == rm.DECISION_REJECT and hv == rm.DECISION_ACCEPT:
            false_rejects.append(item)
        else:
            other_disagreements.append(item)

    n = len(matched_ids)
    mean_delta = (sum(deltas) / len(deltas)) if deltas else None
    conf_dist = {
        "n": len(confidences),
        "min": min(confidences) if confidences else None,
        "max": max(confidences) if confidences else None,
        "mean": (sum(confidences) / len(confidences)) if confidences else None,
        "below_0.5": sum(1 for c in confidences if c < 0.5),
        "0.5_to_0.7": sum(1 for c in confidences if 0.5 <= c < 0.7),
        "gte_0.7": sum(1 for c in confidences if c >= 0.7),
    }
    return {
        "calibration_name": "sft_ai_vs_human",
        "matched": n,
        "human_only": sorted(set(human_by_id) - set(ai_by_id)),
        "ai_only": sorted(set(ai_by_id) - set(human_by_id)),
        "verdict_agreement": {
            "agree": agree,
            "total": n,
            "rate": (agree / n) if n else None,
        },
        "false_accepts": false_accepts,
        "false_rejects": false_rejects,
        "other_disagreements": other_disagreements,
        "false_accept_rate": (len(false_accepts) / n) if n else None,
        "false_reject_rate": (len(false_rejects) / n) if n else None,
        "disagreement_count": len(false_accepts) + len(false_rejects)
        + len(other_disagreements),
        "score_delta": {
            "n_pairs": len(deltas),
            "mean_ai_minus_human": mean_delta,
            "deltas": deltas,
        },
        "confidence_distribution": conf_dist,
    }


def write_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                    encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare human decisions vs AI reviews")
    parser.add_argument("--human", required=True,
                        help="review_ui decisions JSONL")
    parser.add_argument("--ai", required=True,
                        help="ai_reviewer results JSONL")
    parser.add_argument("--report-out", default=None,
                        help="write JSON report here (default: print only)")
    args = parser.parse_args(argv)

    human = load_jsonl(Path(args.human))
    ai = load_jsonl(Path(args.ai))
    report = compare(human, ai)
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.report_out:
        out = Path(args.report_out)
        write_report(report, out)
        print(f"report -> {out}")
    print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
