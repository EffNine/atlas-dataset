#!/usr/bin/env python3
"""
eval_dataset.py — Atlas evaluation harness (deterministic, heuristic).

Produces:
  1. A reproducible train/eval split (seeded) written to evaluation/test_sets/.
  2. A coverage + quality report (per category, per type, per difficulty,
     per language) that doubles as a release-gate dashboard.

It does NOT run a model. Model-based evaluation (perplexity, win-rate, task
accuracy) belongs in a separate harness that consumes the test split this
script emits. Keeping it model-free preserves the model-agnostic mandate and
means the gate runs in CI with zero GPU.

Usage:
  python scripts/eval_dataset.py --input curated/v0.1/atlas_v0.1.jsonl --split 0.05 --seed 42
  python scripts/eval_dataset.py --input examples/sample_dataset.jsonl --report-only
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_SETS_DIR = ROOT / "evaluation" / "test_sets"

VALID_CATEGORIES = {
    "01_foundation", "02_software_engineering", "03_system_engineering",
    "04_ai_machine_learning", "05_hardware_engineering", "06_science_engineering",
    "07_business_knowledge", "08_creative_knowledge", "09_personal_assistant",
}
TARGET_SHARE = {
    "01_foundation": 0.10, "02_software_engineering": 0.20, "03_system_engineering": 0.15,
    "04_ai_machine_learning": 0.20, "05_hardware_engineering": 0.08, "06_science_engineering": 0.10,
    "07_business_knowledge": 0.07, "08_creative_knowledge": 0.05, "09_personal_assistant": 0.05,
}
ACCEPT_SCORE = 7


def load(path: Path) -> list[dict]:
    recs = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    return recs


def make_split(records: list[dict], frac: float, seed: int) -> tuple[list[dict], list[dict]]:
    """Stratified by category so the eval set keeps the same category mix."""
    rng = random.Random(seed)
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_cat[r.get("category", "99_unknown")].append(r)
    test, train = [], []
    for cat, items in by_cat.items():
        rng.shuffle(items)
        k = max(1, round(len(items) * frac)) if len(items) > 5 else (1 if items else 0)
        k = min(k, len(items))
        test.extend(items[:k])
        train.extend(items[k:])
    rng.shuffle(test)
    rng.shuffle(train)
    return test, train


def coverage_report(records: list[dict]) -> None:
    n = len(records) or 1
    print(f"\n=== Coverage Report ({len(records)} records) ===")

    by_cat = Counter(r.get("category") for r in records)
    print("\nCategory balance vs target:")
    for c in sorted(VALID_CATEGORIES):
        share = by_cat.get(c, 0) / n
        delta = share - TARGET_SHARE.get(c, 0)
        flag = "OK" if abs(delta) < 0.05 else ("LOW" if delta < 0 else "HIGH")
        print(f"  {c:28s} {share*100:5.1f}%  target {TARGET_SHARE.get(c,0)*100:4.0f}%  [{flag}]")

    by_type = Counter(r.get("type") for r in records)
    print("\nType mix:", dict(by_type))

    by_diff = Counter(r.get("difficulty", 0) for r in records)
    print("Difficulty (0=unset):", dict(sorted(by_diff.items())))

    by_lang = Counter(r.get("language", "en") for r in records)
    print("Language:", dict(by_lang))

    scores = [int(r.get("quality_score", 0)) for r in records]
    avg = sum(scores) / len(scores) if scores else 0
    accepted = sum(1 for s in scores if s >= ACCEPT_SCORE)
    verified = sum(1 for r in records if r.get("verified"))
    print(f"\nQuality: avg={avg:.2f}  >= {ACCEPT_SCORE}: {accepted}/{len(records)} "
          f"({accepted/len(records)*100:.0f}%)  verified={verified}/{len(records)}")

    # subcategories present per category
    print("\nSubcategories present:")
    sub: dict[str, set] = defaultdict(set)
    for r in records:
        sub[r.get("category")].add(r.get("subcategory"))
    for c in sorted(VALID_CATEGORIES):
        print(f"  {c:28s} {sorted(sub.get(c, []))}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Atlas evaluation harness: split + coverage report.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--split", type=float, default=0.05, help="eval fraction (stratified)")
    ap.add_argument("--seed", type=int, default=42, help="split seed (reproducible)")
    ap.add_argument("--report-only", action="store_true", help="do not write files, just report")
    ap.add_argument("--name", default=None, help="test-set filename stem (default: derived from input)")
    args = ap.parse_args(argv)

    path = Path(args.input)
    if not path.exists():
        print(f"[eval] ERROR: input not found: {path}", file=sys.stderr)
        return 2

    records = load(path)
    coverage_report(records)

    if args.report_only:
        return 0

    if len(records) < 10:
        print("[eval] NOTE: <10 records; skipping file split (needs real volume).")
        return 0

    test, train = make_split(records, args.split, args.seed)
    TEST_SETS_DIR.mkdir(parents=True, exist_ok=True)
    stem = args.name or path.stem
    test_path = TEST_SETS_DIR / f"{stem}_test.jsonl"
    train_path = TEST_SETS_DIR / f"{stem}_train.jsonl"
    with test_path.open("w", encoding="utf-8") as f:
        for r in test:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with train_path.open("w", encoding="utf-8") as f:
        for r in train:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n[eval] wrote test={len(test)} -> {test_path}")
    print(f"[eval] wrote train={len(train)} -> {train_path}")
    print(f"[eval] seed={args.seed} split={args.split} (reproducible)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
