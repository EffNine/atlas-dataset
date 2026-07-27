#!/usr/bin/env python3
"""
gen_calibration_sample.py — Atlas calibration-sample generator (READ-ONLY on data).

Purpose:
  Produce a *structured human-review worksheet* for the quality-calibration
  framework. A human reviewer fills in `quality_reviews.jsonl` (schema:
  schemas/quality_review_schema.json) from this worksheet. Calibration then
  measures auto-scorer vs. human agreement (scripts/calibrate_quality.py).

Design guarantees:
  * READ-ONLY on pilot candidates. It NEVER adds, removes, or modifies any
    dataset record, so the candidate count stays at 100 (no dataset growth).
  * Stdlib-only, deterministic (seeded), no network.
  * The worksheet is a REVIEW artifact, not a dataset record.

Two outputs:
  1. --worksheet-out  (default review_queue/calibration_sample.jsonl)
       The sampling manifest: which records to review, with the auto-scorer's
       current dimension breakdown as context, and a suggested review order.
       A human copies these rows into quality_reviews.jsonl and fills in the
       human fields (human_score, dimension_scores, verdict, hallucination,
       confidence, reviewer).
  2. --example-out    (default review_queue/quality_reviews.example.jsonl)
       An ILLUSTRATIVE seed of COMPLETED reviews, generated synthetically from
       the auto-score with deterministic per-category perturbation. This exists
       ONLY so the calibration harness can be demonstrated/validated end-to-end.
       It is NOT real human judgment. DELETE it before running genuine
       calibration on real human reviews.

Usage:
  python scripts/gen_calibration_sample.py --candidates curated/v0.1/pilot_candidates.jsonl
  python scripts/gen_calibration_sample.py --sample-frac 0.3 --seed 7
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

_qspec = importlib.util.spec_from_file_location("quality_score", ROOT / "scripts" / "quality_score.py")
_quality = importlib.util.module_from_spec(_qspec)
_qspec.loader.exec_module(_quality)

DIMS = list(_quality.WEIGHTS.keys())


def load_jsonl(path: Path) -> list[dict]:
    out = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def clip(v: int, lo: int = 1, hi: int = 10) -> int:
    return max(lo, min(hi, int(round(v))))


def build_worksheet(candidates: list[dict], sample_frac: float, seed: int) -> list[dict]:
    """Stratified-by-category sample, with auto dimension context. Read-only."""
    rng = random.Random(seed)
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for c in candidates:
        by_cat[c.get("category", "99_unknown")].append(c)

    picked: list[dict] = []
    for cat, items in by_cat.items():
        rng.shuffle(items)
        k = max(1, round(len(items) * sample_frac))
        k = min(k, len(items))
        picked.extend(items[:k])

    worksheet = []
    for i, c in enumerate(sorted(picked, key=lambda r: r["id"])):
        auto_score, auto_dims = _quality.score_record(c)
        sa = c.get("source_attribution", {})
        worksheet.append({
            "review_index": i + 1,
            "record_id": c["id"],
            "category": c.get("category"),
            "subcategory": c.get("subcategory"),
            "source_id": sa.get("source_id"),
            "source_name": sa.get("name"),
            "auto_overall": auto_score,
            "auto_dims": {k: round(v * 9 + 1) for k, v in auto_dims.items()},  # 0..1 -> 1..10
            "instruction": "Copy this row into quality_reviews.jsonl and fill: "
                           "human_score, dimension_scores, verdict, hallucination, "
                           "confidence, reviewer, review_date.",
        })
    return worksheet


# Illustrative per-category auto-score bias used ONLY to synthesize example
# reviews that exercise the calibration harness. NOT a real measurement.
_EXAMPLE_CATEGORY_BIAS = {
    "01_foundation": 0.0,
    "02_software_engineering": +0.6,   # auto slightly over-scores code
    "03_system_engineering": +0.4,
    "04_ai_machine_learning": -0.5,    # auto under-scores ML nuance
    "05_hardware_engineering": +0.3,
    "06_science_engineering": -0.3,
    "07_business_knowledge": -1.2,     # auto clearly under-scores business
    "08_creative_knowledge": +1.5,     # auto clearly over-scores creative
    "09_personal_assistant": 0.0,
}


def build_example_reviews(worksheet: list[dict], seed: int) -> list[dict]:
    """Synthesize ILLUSTRATIVE completed reviews. NOT real human judgment."""
    rng = random.Random(seed + 99)
    reviews = []
    for w in worksheet:
        cat = w["category"]
        bias = _EXAMPLE_CATEGORY_BIAS.get(cat, 0.0)
        noise = rng.gauss(0, 0.8)
        human_overall = clip(w["auto_overall"] + bias + noise)
        human_dims = {}
        for d in DIMS:
            a = w["auto_dims"].get(d, w["auto_overall"])
            human_dims[d] = clip(a + bias * 0.8 + rng.gauss(0, 0.7))
        verdict = "accept" if human_overall >= 7 else ("revise" if human_overall >= 5 else "reject")
        # a few hallucination flags, more likely where auto over-scores
        hall = rng.random() < (0.10 + max(0.0, bias) * 0.08)
        reviews.append({
            "record_id": w["record_id"],
            "category": cat,
            "source_id": w["source_id"],
            "reviewer": "EXAMPLE-AUTOSEED",
            "review_date": "2026-07-27",
            "human_score": human_overall,
            "dimension_scores": human_dims,
            "verdict": verdict,
            "hallucination": hall,
            "confidence": rng.randint(3, 5),
            "notes": "ILLUSTRATIVE EXAMPLE — synthetic seed, not a real human review. "
                     "Delete before genuine calibration.",
        })
    return reviews


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generate Atlas quality-calibration review worksheet.")
    ap.add_argument("--candidates", default=str(ROOT / "curated" / "v0.1" / "pilot_candidates.jsonl"))
    ap.add_argument("--worksheet-out", default=str(ROOT / "review_queue" / "calibration_sample.jsonl"))
    ap.add_argument("--example-out", default=str(ROOT / "review_queue" / "quality_reviews.example.jsonl"))
    ap.add_argument("--sample-frac", type=float, default=0.30, help="fraction of candidates to sample")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--no-example", action="store_true",
                    help="do not write the illustrative example seed (real use)")
    args = ap.parse_args(argv)

    candidates = load_jsonl(Path(args.candidates))
    if not candidates:
        print(f"[gen-cal] ERROR: no candidates at {args.candidates}", file=sys.stderr)
        return 2

    worksheet = build_worksheet(candidates, args.sample_frac, args.seed)
    Path(args.worksheet_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.worksheet_out).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in worksheet) + "\n", encoding="utf-8")
    print(f"[gen-cal] worksheet -> {args.worksheet_out}  ({len(worksheet)} records to review)")

    if not args.no_example:
        reviews = build_example_reviews(worksheet, args.seed)
        Path(args.example_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.example_out).write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in reviews) + "\n", encoding="utf-8")
        print(f"[gen-cal] EXAMPLE seed -> {args.example_out}  ({len(reviews)} ILLUSTRATIVE reviews)")
        print("[gen-cal] NOTE: example seed is synthetic. Delete it before real calibration.")

    # quick category coverage summary
    from collections import Counter
    cov = Counter(w["category"] for w in worksheet)
    print("[gen-cal] coverage by category: " + ", ".join(f"{k}:{v}" for k, v in sorted(cov.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
