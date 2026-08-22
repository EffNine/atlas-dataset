#!/usr/bin/env python3
"""
Atlas 500M Pilot v3 — Data Preparation Script

Deterministically samples additional data to reach 5M effective training tokens
per arm. Preserves v2 pilot data as the base layer.

Sources:
  - Math:     nemotron math proofs (raw/p1/p1-nemotron-math-proofs-v2/)
  - Code:     SWE-Smith (raw/p1/p1-swe-smith-mini/)
  - Systems:  Linux kernel patches (raw/p1/p1-y9-linux-kernel/)
  - General:  Mix of all three sources
"""
import json
import hashlib
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

import torch

ROOT = Path("/home/afnan/projects/active/atlas-dataset")
V2_PILOT = ROOT / "pilot" / "v0.2"
RAW_MATH = ROOT / "raw" / "p1" / "p1-nemotron-math-proofs-v2" / "src" / "train.jsonl"
RAW_KERN_HIGH = ROOT / "raw" / "p1" / "p1-y9-linux-kernel" / "src" / "high_score.jsonl"
RAW_KERN_PREM = ROOT / "raw" / "p1" / "p1-y9-linux-kernel" / "src" / "premium_reasoning.jsonl"
RAW_SWE_DIR = ROOT / "raw" / "p1" / "p1-swe-smith-mini" / "src" / "data"
OUTPUT_DIR = ROOT / "experiments" / "atlas-500m-pilot-v3-scale" / "data"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SEED = 42
TARGET_TOKENS = 5_000_000

# Eval set IDs to exclude from training
EVAL_IDS = set()
for eval_file in [
    "evaluation/eval_sets/protocol_v2/math_eval_v2.jsonl",
    "evaluation/eval_sets/protocol_v2/code_eval_v2.jsonl",
    "evaluation/eval_sets/protocol_v2/systems_eval_v2.jsonl",
]:
    with open(ROOT / eval_file) as f:
        for line in f:
            r = json.loads(line)
            EVAL_IDS.add(r.get("record_id", ""))

# Also exclude v2 pilot IDs (they are the base)
V2_PILOT_IDS = set()
for arm in ["general", "math", "code", "systems"]:
    with open(V2_PILOT / arm / "train.jsonl") as f:
        for line in f:
            r = json.loads(line)
            V2_PILOT_IDS.add(r.get("id", r.get("record_id", "")))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def estimate_tokens_record(record, source):
    """Estimate token count for a record."""
    if source == "nemotron":
        content = record.get("messages", [])[-1].get("content", "") if record.get("messages") else ""
        return max(1, int(len(content.split()) * 1.3))
    elif source == "linux_kernel":
        text = record.get("instruction", "") + "\n" + record.get("input", "") + "\n" + record.get("output", "")
        return max(1, int(len(text.split()) * 1.3))
    elif source == "swe_smith":
        msgs = record.get("messages", [])
        text = " ".join(m.get("content", "") for m in msgs if isinstance(m, dict))
        return max(1, int(len(text.split()) * 1.3))
    return 100


def load_nemotron_math():
    """Load nemotron math proofs, return list of records in Atlas message format."""
    records = []
    with open(RAW_MATH) as f:
        for line in f:
            r = json.loads(line)
            uid = r.get("uuid", r.get("id", ""))
            if uid in EVAL_IDS:
                continue
            msgs = r.get("messages", [])
            if not msgs:
                continue
            # Ensure final answer has boxed format
            assistant_content = msgs[-1].get("content", "")
            record = {
                "id": f"v3-math-nemotron-{uid}",
                "source": "nemotron-math-proofs-v2",
                "category": "mathematics",
                "subcategory": r.get("subset", "default"),
                "difficulty": r.get("metadata", {}).get("difficulty", "unknown") if r.get("metadata") else "unknown",
                "license": r.get("license", "unknown"),
                "messages": msgs,
                "format_contract": "boxed",
                "pilot_version": "v3",
            }
            records.append(record)
    return records


def load_linux_kernel():
    """Load linux kernel patches, return list of records in Atlas message format."""
    records = []
    for path in [RAW_KERN_HIGH, RAW_KERN_PREM]:
        with open(path) as f:
            for line in f:
                r = json.loads(line)
                commit = r.get("commit_hash", "")
                if not commit:
                    continue
                instruction = r.get("instruction", "")
                input_text = r.get("input", "")
                output_text = r.get("output", "")
                content = f"{instruction}\n\n{input_text}" if input_text else instruction
                record = {
                    "id": f"v3-sys-kern-{commit}",
                    "source": "linux-kernel-patches",
                    "category": "system_engineering",
                    "subcategory": "kernel",
                    "difficulty": "expert",
                    "license": "proprietary",
                    "messages": [
                        {"role": "user", "content": content},
                        {"role": "assistant", "content": output_text},
                    ],
                    "format_contract": "diff_patch",
                    "pilot_version": "v3",
                    "commit_hash": commit,
                }
                records.append(record)
    return records


def load_swe_smith():
    """Load SWE-Smith data from parquet files."""
    import pyarrow.parquet as pq
    records = []
    files = sorted(os.listdir(RAW_SWE_DIR))
    for fname in files:
        if not fname.endswith(".parquet"):
            continue
        pf = pq.read_table(os.path.join(RAW_SWE_DIR, fname))
        df = pf.to_pandas()
        for _, row in df.iterrows():
            iid = row["instance_id"]
            if iid in EVAL_IDS:
                continue
            msgs = row["messages"]
            if not isinstance(msgs, list):
                continue
            record = {
                "id": f"v3-code-swe-{iid}",
                "source": "swe-smith-mini",
                "category": "software_engineering",
                "subcategory": "patch_generation",
                "difficulty": "expert",
                "license": "proprietary",
                "messages": msgs,
                "format_contract": "unified_diff",
                "pilot_version": "v3",
                "instance_id": iid,
            }
            records.append(record)
    return records


def deterministic_sample(records, n, seed):
    """Deterministically sample n records from records using seed."""
    if n >= len(records):
        return records[:]
    rng = list(range(len(records)))
    # Simple but deterministic shuffle using hash-based ordering
    hashed = [(hash((seed, i)) & 0xFFFFFFFF, i) for i in rng]
    hashed.sort()
    sampled = [records[h[1]] for h in hashed[:n]]
    return sampled


def build_arm_data(arm):
    """Build training data for a given arm, returning (records, stats)."""
    print(f"\n{'='*60}")
    print(f"Building {arm} arm data")
    print(f"{'='*60}")

    # Load v2 pilot base data
    v2_path = V2_PILOT / arm / "train.jsonl"
    v2_records = []
    v2_tokens = 0
    if v2_path.exists():
        with open(v2_path) as f:
            for line in f:
                r = json.loads(line)
                v2_records.append(r)
                v2_tokens += estimate_tokens_record(r, "v2_pilot")
        print(f"  V2 pilot: {len(v2_records)} records, ~{v2_tokens:,} tokens")
    else:
        print(f"  V2 pilot: NOT FOUND")

    needed_tokens = max(0, TARGET_TOKENS - v2_tokens)
    print(f"  Need ~{needed_tokens:,} more tokens to reach {TARGET_TOKENS:,}")

    new_records = []
    source_stats = {}

    if arm == "math":
        all_math = load_nemotron_math()
        print(f"  Nemotron math pool: {len(all_math)} records")
        # Estimate avg tokens
        sample = all_math[:100]
        avg_tok = sum(estimate_tokens_record(r, "nemotron") for r in sample) / len(sample)
        n_sample = min(len(all_math), int(needed_tokens / avg_tok) + 100)
        new_records = deterministic_sample(all_math, n_sample, SEED)
        new_tokens = sum(estimate_tokens_record(r, "nemotron") for r in new_records)
        source_stats = {"nemotron_math_proofs": {"records": len(new_records), "tokens": new_tokens}}
        print(f"  Sampled: {len(new_records)} records, ~{new_tokens:,} tokens")

    elif arm == "code":
        all_code = load_swe_smith()
        print(f"  SWE-Smith pool: {len(all_code)} records")
        sample = all_code[:100]
        avg_tok = sum(estimate_tokens_record(r, "swe_smith") for r in sample) / len(sample)
        n_sample = min(len(all_code), int(needed_tokens / avg_tok) + 100)
        new_records = deterministic_sample(all_code, n_sample, SEED)
        new_tokens = sum(estimate_tokens_record(r, "swe_smith") for r in new_records)
        source_stats = {"swe_smith": {"records": len(new_records), "tokens": new_tokens}}
        print(f"  Sampled: {len(new_records)} records, ~{new_tokens:,} tokens")

    elif arm == "systems":
        all_sys = load_linux_kernel()
        print(f"  Linux kernel pool: {len(all_sys)} records")
        sample = all_sys[:100]
        avg_tok = sum(estimate_tokens_record(r, "linux_kernel") for r in sample) / len(sample)
        n_sample = min(len(all_sys), int(needed_tokens / avg_tok) + 100)
        new_records = deterministic_sample(all_sys, n_sample, SEED)
        new_tokens = sum(estimate_tokens_record(r, "linux_kernel") for r in new_records)
        source_stats = {"linux_kernel_patches": {"records": len(new_records), "tokens": new_tokens}}
        print(f"  Sampled: {len(new_records)} records, ~{new_tokens:,} tokens")

    elif arm == "general":
        # Proportional mix: ~1/3 from each source
        all_math = load_nemotron_math()
        all_code = load_swe_smith()
        all_sys = load_linux_kernel()

        per_source = needed_tokens // 3
        math_avg = sum(estimate_tokens_record(r, "nemotron") for r in all_math[:100]) / 100
        code_avg = sum(estimate_tokens_record(r, "swe_smith") for r in all_code[:100]) / 100
        sys_avg = sum(estimate_tokens_record(r, "linux_kernel") for r in all_sys[:100]) / 100

        n_math = min(len(all_math), int(per_source / math_avg) + 50)
        n_code = min(len(all_code), int(per_source / code_avg) + 50)
        n_sys = min(len(all_sys), int(per_source / sys_avg) + 50)

        samp_math = deterministic_sample(all_math, n_math, SEED)
        samp_code = deterministic_sample(all_code, n_code, SEED)
        samp_sys = deterministic_sample(all_sys, n_sys, SEED)

        new_records = samp_math + samp_code + samp_sys
        new_tokens_math = sum(estimate_tokens_record(r, "nemotron") for r in samp_math)
        new_tokens_code = sum(estimate_tokens_record(r, "swe_smith") for r in samp_code)
        new_tokens_sys = sum(estimate_tokens_record(r, "linux_kernel") for r in samp_sys)

        source_stats = {
            "nemotron_math_proofs": {"records": len(samp_math), "tokens": new_tokens_math},
            "swe_smith": {"records": len(samp_code), "tokens": new_tokens_code},
            "linux_kernel_patches": {"records": len(samp_sys), "tokens": new_tokens_sys},
        }
        print(f"  Math samples: {len(samp_math)} records, ~{new_tokens_math:,} tokens")
        print(f"  Code samples: {len(samp_code)} records, ~{new_tokens_code:,} tokens")
        print(f"  Sys samples: {len(samp_sys)} records, ~{new_tokens_sys:,} tokens")
        print(f"  Total new: {len(new_records)} records, ~{new_tokens_math + new_tokens_code + new_tokens_sys:,} tokens")

    # Combine v2 + new
    all_records = v2_records + new_records

    # Write output
    out_path = OUTPUT_DIR / f"{arm}_train.jsonl"
    with open(out_path, "w") as f:
        for r in all_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Compute actual tokens from file
    actual_tokens = 0
    for r in all_records:
        actual_tokens += estimate_tokens_record(r, arm if arm != "general" else "v2_pilot")
    # Recount from actual content
    actual_tokens = 0
    with open(out_path) as f:
        for line in f:
            r = json.loads(line)
            actual_tokens += estimate_tokens_record(r, arm)

    repeat_factor = actual_tokens / v2_tokens if v2_tokens > 0 else 0
    effective_epochs = actual_tokens / TARGET_TOKENS if TARGET_TOKENS > 0 else 0

    stats = {
        "arm": arm,
        "v2_records": len(v2_records),
        "v2_tokens": v2_tokens,
        "new_records": len(new_records),
        "new_tokens": sum(estimate_tokens_record(r, arm) for r in new_records),
        "total_records": len(all_records),
        "total_tokens": actual_tokens,
        "target_tokens": TARGET_TOKENS,
        "repeat_factor": round(actual_tokens / (v2_tokens + 1), 2),
        "effective_epochs": round(actual_tokens / TARGET_TOKENS, 2),
        "source_stats": source_stats,
        "output_file": str(out_path),
        "output_sha256": sha256_file(out_path),
    }

    stats_path = OUTPUT_DIR / f"{arm}_data_stats.json"
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)

    print(f"  TOTAL: {len(all_records)} records, {actual_tokens:,} tokens")
    print(f"  Repeat factor: {stats['repeat_factor']:.2f}x")
    print(f"  Output: {out_path}")
    print(f"  SHA256: {stats['output_sha256']}")

    return stats


def main():
    print("="*60)
    print("Atlas 500M Pilot v3 — Data Preparation")
    print(f"Target tokens per arm: {TARGET_TOKENS:,}")
    print(f"Seed: {SEED}")
    print("="*60)

    all_stats = {}
    for arm in ["general", "math", "code", "systems"]:
        stats = build_arm_data(arm)
        all_stats[arm] = stats

    # Write summary
    summary = {
        "experiment": "atlas-500m-pilot-v3-scale",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "target_tokens": TARGET_TOKENS,
        "arms": all_stats,
    }
    with open(OUTPUT_DIR / "data_prep_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n{'='*60}")
    print("DATA PREPARATION COMPLETE")
    print(f"{'='*60}")
    for arm, s in all_stats.items():
        print(f"  {arm:10s}: {s['total_records']:5d} records, {s['total_tokens']:>10,} tokens, {s['repeat_factor']:.2f}x repeat")
    print(f"\nSummary saved to {OUTPUT_DIR / 'data_prep_summary.json'}")


if __name__ == "__main__":
    main()
