#!/usr/bin/env python3
"""
Atlas 500M Pilot v2 — Format-Aligned Training Data Builder

Builds v2 training views with corrected format contracts:
- Math: problem → reasoning → \boxed{answer}
- Code: issue description → unified diff patch
- Systems: kernel context → diff --git patch
- General: multi-domain baseline

Does NOT modify canonical Atlas data.
Creates pilot-specific training views under pilot/v0.2/.
"""
import json
import hashlib
import random
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path("/home/afnan/projects/active/atlas-dataset")
PILOT_V2_DIR = ROOT / "pilot" / "v0.2"
PILOT_V2_DIR.mkdir(parents=True, exist_ok=True)

# Sources
PHASE7_MATH = list((ROOT / "experiments" / "phase7_scale" / "subsets").glob("*math*.jsonl"))
P8A_MATH = list((ROOT / "experiments" / "phase8_transfer" / "subsets").glob("*.jsonl"))
SWE_BENCH_RAW = ROOT / "raw" / "p0" / "p0-swe-bench-verified" / "converted" / "test-00000-of-00001.jsonl"
KERNEL_STAGING = ROOT / "raw" / "p1" / "staging" / "p1-y9-linux-kernel.jsonl"

# Eval sets (for exclusion)
MATH_EVAL = ROOT / "evaluation" / "eval_sets" / "protocol_v2" / "math_eval_v2.jsonl"
CODE_EVAL = ROOT / "evaluation" / "eval_sets" / "protocol_v2" / "code_eval_v2.jsonl"
SYSTEMS_EVAL = ROOT / "evaluation" / "eval_sets" / "protocol_v2" / "systems_eval_v1.jsonl"

SEED = 42
random.seed(SEED)


def load_jsonl(path):
    records = []
    with open(path) as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def sha256_str(s):
    return hashlib.sha256(s.encode()).hexdigest()[:16]


# ── Load eval sets for exclusion ────────────────────────────────────────────
print("Loading eval sets for exclusion...")
math_eval_records = load_jsonl(MATH_EVAL)
code_eval_records = load_jsonl(CODE_EVAL)
systems_eval_records = load_jsonl(SYSTEMS_EVAL)

math_eval_ids = set(r.get("record_id", "") for r in math_eval_records)
code_eval_ids = set(r.get("record_id", "") for r in code_eval_records)
systems_eval_ids = set(r.get("record_id", "") for r in systems_eval_records)

# Also get SWE-bench instance IDs for exclusion
swe_bench_records = load_jsonl(SWE_BENCH_RAW)
swe_bench_instance_ids = set(r["instance_id"] for r in swe_bench_records)

# Get code eval original_ids (these are SWE-bench instance IDs)
code_eval_orig_ids = set(r.get("original_id", "") for r in code_eval_records)
print(f"  Math eval IDs: {len(math_eval_ids)}")
print(f"  Code eval IDs: {len(code_eval_ids)}")
print(f"  Systems eval IDs: {len(systems_eval_ids)}")
print(f"  SWE-bench instances: {len(swe_bench_instance_ids)}")
print(f"  Code eval orig IDs: {len(code_eval_orig_ids)}")


# ── PART 1: MATH V2 ─────────────────────────────────────────────────────────
print("\n=== Building Math v2 ===")
math_train_records = []
seen_ids = set()

for src_file in PHASE7_MATH:
    records = load_jsonl(src_file)
    for r in records:
        rid = r.get("id", r.get("record_id", ""))
        if rid in seen_ids or rid in math_eval_ids:
            continue
        seen_ids.add(rid)

        # Build chat format: simple problem → reasoning + boxed answer
        problem = r.get("problem", "")
        msgs = r.get("messages", [])

        # Find assistant message and extract boxed answer
        assistant_content = ""
        for m in msgs:
            if m["role"] == "assistant":
                assistant_content = m["content"]
                break

        if not assistant_content:
            continue

        # Extract reasoning (everything before \boxed) and final answer
        # Keep the full assistant response as-is since it already has \boxed{}
        # Transform to clean chat format
        new_messages = [
            {"role": "user", "content": problem},
            {"role": "assistant", "content": assistant_content},
        ]

        record = {
            "id": f"v2-math-{sha256_str(rid)}",
            "source": r.get("source", src_file.name),
            "category": r.get("category", "mathematics"),
            "subcategory": r.get("subcategory", "math"),
            "difficulty": r.get("difficulty", 2),
            "expert_tier": r.get("expert_tier", "E2"),
            "license": r.get("license", "CC-BY-4.0"),
            "messages": new_messages,
            "format_contract": "math_final_answer",
            "pilot_version": "v0.2",
        }
        math_train_records.append(record)

print(f"  Math v2 records: {len(math_train_records)}")

# Verify format
boxed_count = sum(1 for r in math_train_records if "\\boxed{" in r["messages"][-1]["content"])
print(f"  With \\boxed{{}}: {boxed_count}/{len(math_train_records)} ({boxed_count/len(math_train_records)*100:.1f}%)")


# ── PART 2: CODE V2 ─────────────────────────────────────────────────────────
print("\n=== Building Code v2 ===")
code_train_records = []
seen_code_ids = set()

for r in swe_bench_records:
    inst_id = r["instance_id"]
    if inst_id in code_eval_orig_ids or inst_id in seen_code_ids:
        continue
    seen_code_ids.add(inst_id)

    problem_statement = r.get("problem_statement", "")
    patch = r.get("patch", "")

    if not problem_statement or not patch:
        continue

    # Build chat format: issue → unified diff patch
    new_messages = [
        {"role": "user", "content": problem_statement},
        {"role": "assistant", "content": patch},
    ]

    record = {
        "id": f"v2-code-{sha256_str(inst_id)}",
        "source": "p0-swe-bench-verified",
        "category": "software_engineering",
        "subcategory": "patch_generation",
        "difficulty": r.get("difficulty", 2),
        "license": "MIT",
        "messages": new_messages,
        "format_contract": "code_unified_diff",
        "pilot_version": "v0.2",
        "repo": r.get("repo", ""),
        "instance_id": inst_id,
    }
    code_train_records.append(record)

print(f"  Code v2 records: {len(code_train_records)}")

# Verify format
patch_count = sum(1 for r in code_train_records if "diff --git" in r["messages"][-1]["content"])
print(f"  With diff --git: {patch_count}/{len(code_train_records)} ({patch_count/len(code_train_records)*100:.1f}%)")


# ── PART 3: SYSTEMS V2 ──────────────────────────────────────────────────────
print("\n=== Building Systems v2 ===")
kernel_records = load_jsonl(KERNEL_STAGING)
systems_train_records = []
seen_sys_ids = set()

for r in kernel_records:
    rid = r.get("id", "")
    if rid in seen_sys_ids or rid in systems_eval_ids:
        continue
    seen_sys_ids.add(rid)

    msgs = r.get("messages", [])
    if len(msgs) < 2:
        continue

    # Verify assistant response is a patch
    assistant_content = msgs[-1]["content"]
    if "diff --git" not in assistant_content:
        continue

    record = {
        "id": f"v2-systems-{sha256_str(rid)}",
        "source": r.get("source", "p1-y9-linux-kernel"),
        "category": r.get("category", "system_engineering"),
        "subcategory": r.get("subcategory", "linux_kernel"),
        "difficulty": r.get("difficulty", 2),
        "license": r.get("source", {}).get("license", "Apache-2.0") if isinstance(r.get("source"), dict) else "Apache-2.0",
        "messages": msgs,
        "format_contract": "systems_kernel_patch",
        "pilot_version": "v0.2",
    }
    systems_train_records.append(record)

print(f"  Systems v2 records: {len(systems_train_records)}")

# Verify format
diff_count = sum(1 for r in systems_train_records if "diff --git" in r["messages"][-1]["content"])
print(f"  With diff --git: {diff_count}/{len(systems_train_records)} ({diff_count/len(systems_train_records)*100:.1f}%)")


# ── PART 4: GENERAL V2 ──────────────────────────────────────────────────────
print("\n=== Building General v2 ===")
# Mix from multiple sources with balanced representation
general_records = []
seen_gen_ids = set()

# Include a mix from all sources
all_sources = [
    (math_train_records, "math"),
    (code_train_records, "code"),
    (systems_train_records, "systems"),
]

# Target ~1100 records for general arm (similar to v1)
target_general = 1100
samples_per_source = target_general // 3

for source_records, domain in all_sources:
    shuffled = source_records.copy()
    random.shuffle(shuffled)
    for r in shuffled[:samples_per_source]:
        rid = r["id"]
        if rid in seen_gen_ids:
            continue
        seen_gen_ids.add(rid)

        general_records.append({
            **r,
            "id": f"v2-general-{sha256_str(rid)}",
            "format_contract": "general_mixed",
            "domain_source": domain,
        })

print(f"  General v2 records: {len(general_records)}")


# ── SAVE TRAINING DATA ──────────────────────────────────────────────────────
print("\n=== Saving v2 training data ===")

arms = {
    "math": math_train_records,
    "code": code_train_records,
    "systems": systems_train_records,
    "general": general_records,
}

manifest_entries = {}
for arm_name, records in arms.items():
    arm_dir = PILOT_V2_DIR / arm_name
    arm_dir.mkdir(parents=True, exist_ok=True)
    train_path = arm_dir / "train.jsonl"

    # Shuffle and save
    random.shuffle(records)

    total_tokens = 0
    with open(train_path, "w") as f:
        for r in records:
            line = json.dumps(r, ensure_ascii=False)
            f.write(line + "\n")
            total_tokens += len(line) // 4  # rough estimate

    # Compute checksum
    with open(train_path, "rb") as f:
        content = f.read()
        checksum = hashlib.sha256(content).hexdigest()

    manifest_entries[arm_name] = {
        "arm_type": "general" if arm_name == "general" else "specialist",
        "record_count": len(records),
        "total_tokens_estimated": total_tokens,
        "train_path": str(train_path),
        "train_sha256": checksum,
        "format_contract": {
            "math": "problem → reasoning → \\boxed{answer}",
            "code": "issue description → unified diff patch",
            "systems": "kernel context → diff --git patch",
            "general": "multi-domain mixed",
        }[arm_name],
    }

    print(f"  {arm_name}: {len(records):,} records, ~{total_tokens:,} tokens")

# Save manifest
manifest = {
    "experiment_id": "atlas_500m_pilot_v2_format_fixed",
    "version": "v0.2",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "base_model": "Qwen/Qwen2.5-0.5B-Instruct",
    "random_seed": SEED,
    "target_tokens_per_arm": 1000000,
    "arms": manifest_entries,
    "format_contracts": {
        "math": {
            "input": "problem (single user message)",
            "reasoning": "optional step-by-step derivation",
            "final_answer": "\\boxed{answer} (machine-parseable)",
            "parser": "extract_last_boxed",
        },
        "code": {
            "input": "GitHub issue / bug description",
            "reasoning": "optional analysis",
            "final_answer": "unified diff patch (diff --git format)",
            "parser": "patch_similarity",
        },
        "systems": {
            "input": "kernel code context + commit instruction",
            "reasoning": "optional reasoning",
            "final_answer": "unified diff patch (diff --git format)",
            "parser": "patch_similarity",
        },
    },
    "contamination_controls": {
        "math_eval_excluded": len([r for r in math_train_records if r.get("id", "") in math_eval_ids]),
        "code_eval_excluded": len(code_eval_orig_ids),
        "systems_eval_excluded": len([r for r in systems_train_records if r.get("id", "") in systems_eval_ids]),
    },
}

manifest_path = ROOT / "metadata" / "pilot_manifest_v0.3.json"
with open(manifest_path, "w") as f:
    json.dump(manifest, f, indent=2)

print(f"\nManifest saved: {manifest_path}")
print("\n=== BUILD COMPLETE ===")
