#!/usr/bin/env python3
"""
build_clean_math_eval.py — Build a clean math evaluation set excluding
training/eval overlap records.

Creates:
  evaluation/eval_sets/protocol_v2/math_eval_v2_clean.jsonl   (N=87)
  evaluation/eval_sets/protocol_v2/math_eval_v2_clean_manifest.json

The clean set = math_eval_v2 minus the 13 records that appear in M2 training.
This ensures zero training/eval overlap for ALL three models (M1, M2, M2').
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EVAL_V2_DIR = REPO / "evaluation" / "eval_sets" / "protocol_v2"
OUT_DIR = EVAL_V2_DIR

# Training views to exclude overlap from
TRAINING_VIEWS = [
    REPO / "output/training_views/math_300m_v0.1/train.jsonl",
    REPO / "output/training_views/math_m2_v0.1/train.jsonl",
    REPO / "experiments/lora_pilot_math_m2prime_v0.1/staged_train.jsonl",
]


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def sha256_of_lines(rows: list[dict]) -> str:
    """Match build_eval_v2.py convention: sort by record_id, serialize with
    sort_keys, join with \\n (no trailing newline), SHA-256."""
    sorted_rows = sorted(rows, key=lambda r: r.get("record_id", ""))
    lines = [json.dumps(r, sort_keys=True, ensure_ascii=False) for r in sorted_rows]
    blob = "\n".join(lines)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def main():
    # Load eval_v2
    eval_v2 = load_jsonl(EVAL_V2_DIR / "math_eval_v2.jsonl")
    eval_v2_ids = {r["record_id"] for r in eval_v2}
    print(f"math_eval_v2: N={len(eval_v2)}")

    # Load all training view record IDs
    train_ids = set()
    for tv_path in TRAINING_VIEWS:
        records = load_jsonl(tv_path)
        train_ids.update(r["record_id"] for r in records)
    print(f"Combined training view IDs: {len(train_ids)}")

    # Find overlap
    overlap_ids = eval_v2_ids & train_ids
    print(f"Overlap (eval ∩ training): {len(overlap_ids)}")
    print(f"Overlap IDs: {sorted(overlap_ids)}")

    # Build clean set
    clean_records = [r for r in eval_v2 if r["record_id"] not in overlap_ids]
    clean_ids = {r["record_id"] for r in clean_records}
    print(f"Clean eval set: N={len(clean_records)}")

    # Compute checksum
    checksum = sha256_of_lines(clean_records)
    print(f"Checksum: {checksum}")

    # Write clean eval set
    out_jsonl = OUT_DIR / "math_eval_v2_clean.jsonl"
    sorted_records = sorted(clean_records, key=lambda r: r["record_id"])
    with out_jsonl.open("w", encoding="utf-8") as f:
        for r in sorted_records:
            f.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")
    print(f"Wrote: {out_jsonl}")

    # Write manifest
    manifest = {
        "eval_set_id": "math_eval_v2_clean",
        "version": "v1",
        "family": "math",
        "derived_from": {
            "eval_set_id": "math_eval_v2",
            "version": "v2",
            "n_records": len(eval_v2),
            "exclusion_reason": "training_eval_overlap",
            "excluded_record_ids": sorted(overlap_ids),
            "excluded_count": len(overlap_ids),
        },
        "n_records": len(clean_records),
        "n_clean": len(clean_records),
        "n_held": 0,
        "held_record_ids": [],
        "leak_guard_holds": [],
        "record_ids": sorted(clean_ids),
        "checksum": {
            "algorithm": "SHA-256",
            "records": checksum,
        },
        "overlap_audit": {
            "m1_training_overlap": len(eval_v2_ids & {r["record_id"] for r in load_jsonl(REPO / "output/training_views/math_300m_v0.1/train.jsonl")}),
            "m2_training_overlap": len(eval_v2_ids & {r["record_id"] for r in load_jsonl(REPO / "output/training_views/math_m2_v0.1/train.jsonl")}),
            "m2prime_training_overlap": len(eval_v2_ids & {r["record_id"] for r in load_jsonl(REPO / "experiments/lora_pilot_math_m2prime_v0.1/staged_train.jsonl")}),
            "clean_for_m1": True,
            "clean_for_m2": True,
            "clean_for_m2prime": True,
        },
        "provenance": {
            "source": "derived from math_eval_v2 by excluding training overlap",
            "date": "2026-08-11",
            "purpose": "M2/M2' scaling comparison with zero training/eval overlap",
        },
    }
    out_manifest = OUT_DIR / "math_eval_v2_clean_manifest.json"
    out_manifest.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote: {out_manifest}")

    # Verify
    verify = load_jsonl(out_jsonl)
    verify_ids = {r["record_id"] for r in verify}
    assert len(verify) == 87, f"Expected 87, got {len(verify)}"
    assert verify_ids == clean_ids, "Record IDs mismatch"
    assert len(verify_ids & train_ids) == 0, "Overlap still exists!"
    print("\nVerification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
