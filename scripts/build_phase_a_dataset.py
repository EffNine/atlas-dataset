#!/usr/bin/env python3
"""
Build the Phase A training dataset by merging included datasets from the manifest.

Reads datasets/sft/phase_a_manifest.json and produces:
  - datasets/sft/phase_a_train.jsonl  (merged train data)
  - datasets/sft/phase_a_val.jsonl    (merged val data)
  - datasets/sft/phase_a_metadata.json (merge report)

This is the SINGLE SOURCE OF TRUTH for what goes into Phase A training.
No directory auto-discovery — only datasets explicitly included in the manifest.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ATLAS_ROOT = Path("/home/afnan/projects/active/atlas-dataset")
MODEL_ROOT = Path("/home/afnan/projects/active/model-eval-finetune")
MANIFEST_PATH = MODEL_ROOT / "datasets" / "sft" / "phase_a_manifest.json"
OUTPUT_DIR = MODEL_ROOT / "datasets" / "sft"


def main() -> int:
    if not MANIFEST_PATH.exists():
        print(f"ERROR: Manifest not found: {MANIFEST_PATH}", file=sys.stderr)
        return 1

    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    print("=" * 60, file=sys.stderr)
    print("PHASE A DATASET BUILDER", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    included = [d for d in manifest["datasets"] if d.get("included")]
    excluded = [d for d in manifest["datasets"] if not d.get("included")]

    print(f"Included: {len(included)} datasets", file=sys.stderr)
    print(f"Excluded: {len(excluded)} datasets", file=sys.stderr)

    # Validate no excluded/template data is included
    for ds in included:
        tags = ds.get("tags", [])
        if "TEMPLATE" in tags or "EXCLUDED" in tags:
            print(f"FATAL: Template/excluded dataset is marked included: {ds['name']}", file=sys.stderr)
            return 1

    # Collect records
    all_train: list[dict] = []
    all_val: list[dict] = []
    source_counts = Counter()
    source_types = Counter()
    errors = []

    for ds in included:
        name = ds["name"]
        path = Path(ds["path"])
        if not path.exists():
            errors.append(f"  MISSING: {name} ({path})")
            continue

        print(f"\nLoading {name}: {path}", file=sys.stderr)
        train_path = path if path.suffix == ".jsonl" else path / "atan_v1_train.jsonl"
        val_path = path if (path.parent / "atan_v1_val.jsonl").exists() else None
        if not train_path.exists():
            errors.append(f"  No train file: {train_path}")
            continue

        train_count = 0
        with open(train_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as e:
                    errors.append(f"  JSON error in {name}: {e}")
                    continue
                # Inject source metadata
                rec["_source"] = name
                rec.setdefault("metadata", {})["_source_dataset"] = name
                all_train.append(rec)
                train_count += 1

        source_counts[name] = train_count
        # Determine record types
        types = Counter()
        for rec in all_train[-train_count:]:
            types[rec.get("task_type", "unknown")] += 1
        source_types[name] = dict(types)

        print(f"  Loaded {train_count} train records, types: {dict(types)}", file=sys.stderr)

        # Load val if exists (try multiple patterns)
        val_file = None
        candidates = [
            path.parent / "atan_v1_val.jsonl",
            path.parent / "val.jsonl",
            path.parent / f"{path.stem.replace('train','val')}.jsonl",
        ]
        if path.suffix == ".jsonl":
            candidates = [path.parent / "atan_v1_val.jsonl", path.parent / "val.jsonl"]
        for cand in candidates:
            if cand.exists():
                val_file = cand
                break
        if val_file:
            val_count = 0
            with open(val_file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    rec["_source"] = name
                    rec.setdefault("metadata", {})["_source_dataset"] = name
                    all_val.append(rec)
                    val_count += 1
            print(f"  Loaded {val_count} val records", file=sys.stderr)

    if errors:
        print(f"\nERRORS:", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        return 1

    # Write output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    train_out = OUTPUT_DIR / "phase_a_train.jsonl"
    val_out = OUTPUT_DIR / "phase_a_val.jsonl"

    with train_out.open("w", encoding="utf-8") as f:
        for rec in all_train:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"\nWrote {train_out}: {len(all_train)} records", file=sys.stderr)

    with val_out.open("w", encoding="utf-8") as f:
        for rec in all_val:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"Wrote {val_out}: {len(all_val)} records", file=sys.stderr)

    # Compute metrics
    task_types = Counter(r.get("task_type", "unknown") for r in all_train)
    difficulties = Counter(r.get("difficulty", "unknown") for r in all_train)
    categories = Counter(r.get("category", r.get("task_type", "unknown")) for r in all_train)
    sources = Counter(r.get("_source", "unknown") for r in all_train)

    l3plus = sum(v for k, v in difficulties.items() if k in ["L3", "L4", "L5"])
    l3pct = l3plus / max(len(all_train), 1) * 100

    meta = {
        "version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_records": len(all_train),
        "val_records": len(all_val),
        "source_datasets": {
            name: {"records": count, "types": stypes}
            for name, count, stypes in zip(source_counts.keys(), source_counts.values(), source_types.values())
        },
        "task_type_distribution": dict(task_types),
        "difficulty_distribution": dict(difficulties),
        "category_distribution": dict(categories.most_common(15)),
        "l3_plus_percentage": round(l3pct, 1),
        "excluded_datasets": [d["name"] for d in excluded],
        "manifest_path": str(MANIFEST_PATH),
    }

    meta_path = OUTPUT_DIR / "phase_a_metadata.json"
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {meta_path}", file=sys.stderr)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"PHASE A DATASET READY", file=sys.stderr)
    print(f"  Train: {len(all_train):,} records", file=sys.stderr)
    print(f"  Val:   {len(all_val):,} records", file=sys.stderr)
    print(f"  L3-L5: {l3pct:.1f}%", file=sys.stderr)
    print(f"  Sources: {dict(source_counts)}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
