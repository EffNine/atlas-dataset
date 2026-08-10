#!/usr/bin/env python3
"""build_human_calibration_set.py — Phase 6.3 human calibration set builder.

Selects 30 math + 30 code samples from the Phase 6.2 expanded eval sets for
human review, with:
  - deterministic random selection (seeded) for reproducibility,
  - provenance preserved (record_id, original_id, source, difficulty, category),
  - NO training-view overlap (guaranteed: eval sets are already train-disjoint;
    this additionally asserts it),
  - reference answers included for human grading.

Output: experiments/phase6_baseline_eval/human_review_calibration_set.json

No QEE scoring is performed here. The set is for human labeling only.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path

REPO = Path("/mnt/d/atlas-dataset")
EVAL_SETS = REPO / "evaluation" / "eval_sets" / "phase6_expansion_v1"
TRAIN_VIEWS = REPO / "output" / "training_views"
OUT_DIR = REPO / "experiments" / "phase6_baseline_eval"

SAMPLE_PER_FAMILY = 30
SEED = 20260804


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def train_ids(view_dir: str) -> set:
    ids = set()
    p = TRAIN_VIEWS / view_dir / "train.jsonl"
    if p.exists():
        for r in load_jsonl(p):
            ids.add(r.get("record_id"))
    return ids


def main():
    rng = random.Random(SEED)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    config = {
        "math": {"eval": EVAL_SETS / "math_eval_v1.jsonl", "train_view": "math_300m_v0.1"},
        "code": {"eval": EVAL_SETS / "code_eval_v1.jsonl", "train_view": "code_300m_v0.1"},
    }

    samples = []
    stats = {}
    for fam, cfg in config.items():
        eval_rows = load_jsonl(cfg["eval"])
        t_ids = train_ids(cfg["train_view"])
        assert not (t_ids & {r.get("record_id") for r in eval_rows}), \
            f"{fam}: eval/train overlap present!"
        # deterministic random sample
        pool = list(eval_rows)
        rng.shuffle(pool)
        picked = pool[:SAMPLE_PER_FAMILY]
        picked.sort(key=lambda r: r.get("record_id"))

        for r in picked:
            for m in (r.get("messages") or []):
                if m.get("role") == "assistant":
                    ref = (m.get("content") or "").strip()
                    break
            else:
                ref = r.get("solution") or ""
            samples.append({
                "record_id": r.get("record_id"),
                "view_id": r.get("view_id"),
                "family": fam,
                "category": r.get("category"),
                "difficulty": r.get("difficulty"),
                "original_id": r.get("original_id"),
                "source_id": r.get("source_id"),
                "source_name": r.get("source_name"),
                "license": r.get("license"),
                "problem": r.get("problem"),
                "reference_answer": ref,
                "verification_evidence": r.get("verification_evidence"),
                "review_verdict": r.get("review_verdict"),
                # human-fill fields
                "human_score": None,
                "human_verdict": None,
                "human_notes": "",
                "human_reviewer": None,
                "human_reviewed_at": None,
            })
        cats = {}
        for s in picked:
            cats[s.get("category")] = cats.get(s.get("category"), 0) + 1
        stats[fam] = {"n": len(picked), "categories": cats}

    out = {
        "calibration_set_id": "phase6-human-calibration-v1",
        "version": "v1",
        "seed": SEED,
        "sampling": "deterministic_random_shuffle",
        "n_math": SAMPLE_PER_FAMILY,
        "n_code": SAMPLE_PER_FAMILY,
        "train_overlap": "none (asserted disjoint from training-view train.jsonl)",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "instructions": (
            "For each record: assign human_score (0-10 correctness/quality) and "
            "human_verdict (approve/reject). Compare against the reference answer. "
            "Fill human_notes, human_reviewer, human_reviewed_at."
        ),
        "stats": stats,
        "samples": samples,
    }
    out_path = OUT_DIR / "human_review_calibration_set.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {out_path} with {len(samples)} samples")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
