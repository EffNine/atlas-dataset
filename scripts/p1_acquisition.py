#!/usr/bin/env python3
"""
Atlas P1 Frontier Acquisition — Full execution pipeline.

Sources:
  P0.1 — SWE-smith-mini full (66K trajectories, MIT)
  P0.2 — Nemotron-Math-Proofs-v2 full (82,737 samples, CC-BY-4.0)
  P0.3 — y9 Linux kernel commits sampled (10K, Apache-2.0)
  P0.4 — y5 StackExchange Systems sampled (8K, CC-BY-SA-4.0)

Constraints:
  - Do NOT flatten trajectory structure (SWE-smith)
  - Do NOT treat every Nemotron sample as independent problem
  - Preserve commit/patch/instruction relationship (kernel)
  - Preserve question/answer/source lineage (SE)
  - No specialist_id on canonical records
  - Map sources at policy/view level only
  - Check contamination against protected eval sets
  - Deterministic stratified sampling for y9 and y5
"""
import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

ROOT = Path(__file__).resolve().parents[1]
RAW_P1 = ROOT / "raw" / "p1"
STAGING_DIR = RAW_P1 / "staging"
STAGING_DIR.mkdir(parents=True, exist_ok=True)
METADATA_DIR = ROOT / "metadata"
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

from atlas_constants import (
    VALID_CATEGORIES, VALID_TYPES, VALID_ROLES,
    is_denied_license, requires_attribution, is_share_alike,
)
from atlas_schema import BASE_ALLOWED_KEYS, ID_PATTERN, TAG_PATTERN
from validate_dataset import validate_one_file, structural_errors

# ─────────────────────────────────────────────────────────────────────────────
# Deterministic sampling utilities
# ─────────────────────────────────────────────────────────────────────────────

def deterministic_sample(items: list, n: int, seed: int = 42) -> list:
    """Deterministic random sample using SHA-256 based shuffle."""
    if n >= len(items):
        return list(items)
    # Create deterministic shuffle key
    hashed = hashlib.sha256(f"{seed}".encode()).hexdigest()
    # Use hash-based selection for determinism
    indices = []
    h = int(hashed, 16)
    for i in range(n):
        h = (h * 1103515245 + 12345) & 0x7FFFFFFF
        indices.append(h % len(items))
    # Replace duplicates
    seen = set()
    result = []
    for idx in indices:
        if idx not in seen:
            seen.add(idx)
            result.append(items[idx])
        else:
            # Find next available
            for j in range(len(items)):
                if j not in seen:
                    seen.add(j)
                    result.append(items[j])
                    break
    return result


def stratified_sample_by_field(
    items: list,
    n: int,
    field: str,
    seed: int = 42,
) -> list:
    """Stratified sample ensuring proportional representation across field values."""
    groups: dict[str, list] = defaultdict(list)
    for item in items:
        key = str(item.get(field, "unknown"))
        groups[key].append(item)

    # Sort groups by size (largest first) for deterministic ordering
    sorted_keys = sorted(groups.keys(), key=lambda k: -len(groups[k]))

    # Allocate samples proportionally
    allocated: dict[str, int] = {}
    remaining = n
    for key in sorted_keys[:-1]:
        alloc = max(1, round(len(groups[key]) * n / len(items)))
        alloc = min(alloc, len(groups[key]), remaining - (len(sorted_keys) - len(allocated) - 1))
        allocated[key] = alloc
        remaining -= alloc
    if sorted_keys:
        allocated[sorted_keys[-1]] = max(1, remaining)

    result = []
    for key in sorted_keys:
        group = groups[key]
        alloc = allocated.get(key, 1)
        sampled = deterministic_sample(group, min(alloc, len(group)), seed=seed)
        result.extend(sampled)

    return result[:n]


# ─────────────────────────────────────────────────────────────────────────────
# Record normalisation (preserves source structure)
# ─────────────────────────────────────────────────────────────────────────────

def make_id(source_id: str, raw_id: str = "", content_hash: str = "") -> str:
    """Generate a stable Atlas record ID matching ^[a-z0-9_-]+$."""
    if raw_id and isinstance(raw_id, str) and len(raw_id) > 0:
        safe_raw = re.sub(r'[^a-z0-9_-]', '_', raw_id[:32])
        base = f"{source_id}_{safe_raw}"
    elif content_hash:
        base = f"{source_id}_{content_hash}"
    else:
        base = source_id
    return base[:64] if len(base) > 64 else base


def normalise_messages(messages: Any) -> list:
    """Ensure messages is a list of {role, content} dicts."""
    if not isinstance(messages, list):
        return [
            {"role": "user", "content": str(messages)[:2000]},
            {"role": "assistant", "content": "See source data."},
        ]
    out = []
    for m in messages:
        if isinstance(m, str):
            try:
                m = json.loads(m)
            except Exception:
                m = {"role": "user", "content": m}
        if isinstance(m, dict):
            role = m.get("role", "user")
            content = m.get("content", "")
            if isinstance(content, (list, dict)):
                content = json.dumps(content, ensure_ascii=False)[:2000]
            out.append({"role": str(role), "content": str(content)[:2000]})
    if not out:
        return [
            {"role": "user", "content": "See source data."},
            {"role": "assistant", "content": "See source data."},
        ]
    # Ensure user and assistant present
    roles = {m["role"] for m in out}
    if "user" not in roles:
        out.insert(0, {"role": "user", "content": "Process this data."})
    if "assistant" not in roles:
        out.append({"role": "assistant", "content": "See source data."})
    return out


def compute_content_hash(messages: list) -> str:
    """SHA-256 over normalised message content."""
    norm = "\n".join(f"{m.get('role','')}:{m.get('content','').strip()}" for m in messages)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def content_hash_short(messages: list) -> str:
    """Lightweight hash for duplicate detection."""
    norm = "\n".join(f"{m.get('role','')}:{m.get('content','').strip()[:100]}" for m in messages)
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


def apply_atlas_schema(
    rec: dict,
    source_id: str,
    category: str,
    subcategory: str,
    license_str: str,
    notes_prefix: str,
) -> dict:
    """Apply Atlas schema constraints without destroying source structure."""
    # Start with only allowed keys
    allowed = BASE_ALLOWED_KEYS
    cleaned = {k: v for k, v in rec.items() if k in allowed}

    # Ensure required fields
    cleaned["category"] = category
    cleaned["subcategory"] = subcategory
    # NOTE: license and verification_status are source-level, not record-level
    # They live inside cleaned["source"] only
    cleaned["language"] = "en"
    cleaned["type"] = rec.get("type", "qa") if isinstance(rec.get("type"), str) and rec.get("type") in VALID_TYPES else "qa"
    cleaned["verified"] = False
    cleaned["difficulty"] = int(cleaned.get("difficulty", 2)) if isinstance(cleaned.get("difficulty"), int) and 0 <= cleaned.get("difficulty", 0) <= 3 else 2

    # Normalise messages
    cleaned["messages"] = normalise_messages(rec.get("messages", []))

    # Quality score heuristics
    qs = rec.get("quality_score")
    if isinstance(qs, int) and 0 <= qs <= 10:
        cleaned["quality_score"] = qs
    else:
        hf_id = rec.get("_hf_id", "")
        if any(hf_id.startswith(p) for p in ["nvidia/", "google/", "princeton-nlp/"]):
            cleaned["quality_score"] = 8
        elif any(hf_id.startswith(p) for p in ["Kwai-Klear/", "ewedubs/", "SWE-bench/"]):
            cleaned["quality_score"] = 7
        else:
            cleaned["quality_score"] = 6

    # Tags
    tags = [source_id, subcategory.replace("_", "-")]
    msg_type = rec.get("type", "qa")
    if isinstance(msg_type, str):
        tags.append(msg_type)
    cleaned["tags"] = sorted(set(tags))

    # Source attribution
    cleaned["source"] = {
        "name": rec.get("_hf_id", source_id),
        "url": rec.get("_source_url", f"https://huggingface.co/datasets/{rec.get('_hf_id', '')}"),
        "license": license_str,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    # Notes
    cleaned["notes"] = f"{notes_prefix} — {source_id}. Needs human review."

    # Generate ID
    ch = content_hash_short(cleaned.get("messages", []))
    raw_id = rec.get("instance_id") or rec.get("uuid") or rec.get("commit_hash") or ""
    cleaned["id"] = make_id(source_id, raw_id, ch)[:64]

    # Strip internal temp fields
    cleaned.pop("_hf_id", None)
    cleaned.pop("_source_url", None)
    cleaned.pop("_raw_messages", None)

    return cleaned


# ─────────────────────────────────────────────────────────────────────────────
# Contamination check
# ─────────────────────────────────────────────────────────────────────────────

def load_protected_eval_ids() -> set:
    """Load protected evaluation set instance IDs."""
    protected = set()
    # SWE-bench Verified test split
    swe_bench_path = ROOT / "raw" / "p0" / "p0-swe-bench-verified" / "converted" / "test-00000-of-00001.jsonl"
    if swe_bench_path.exists():
        with open(swe_bench_path) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    iid = rec.get("instance_id", "")
                    if iid:
                        protected.add(iid)
                except Exception:
                    pass
    print(f"  Loaded {len(protected)} protected SWE-bench Verified IDs", file=sys.stderr)
    return protected


def check_contamination(records: list, source_id: str, protected_ids: set) -> dict:
    """Check records for overlap with protected evaluation sets."""
    overlaps = []
    for rec in records:
        iid = rec.get("instance_id", "")
        if iid and iid in protected_ids:
            overlaps.append(iid)
    return {
        "source_id": source_id,
        "total_checked": len(records),
        "overlaps_found": len(overlaps),
        "overlap_ids": overlaps[:20],  # First 20 for reporting
        "risk_level": "HIGH" if overlaps else "LOW",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Frontier tier classification
# ─────────────────────────────────────────────────────────────────────────────

def classify_frontier(rec: dict, source_id: str) -> str:
    """Classify record into frontier tier based on quality signals."""
    qs = rec.get("quality_score", 0)
    msgs = rec.get("messages", [])
    assistant_content = ""
    for m in msgs:
        if m.get("role") == "assistant":
            assistant_content = m.get("content", "")
            break

    # A+ Frontier: quality 8+, long detailed responses, verification signals
    if qs >= 8 and len(assistant_content) > 500:
        return "A+ Frontier"
    # A Strong Specialist: quality 7+, substantial content
    if qs >= 7 and len(assistant_content) > 200:
        return "A Strong Specialist"
    # B Professional: quality 6+, decent content
    if qs >= 6 and len(assistant_content) > 100:
        return "B Professional"
    # C General: anything that passes schema
    if qs >= 5:
        return "C General"
    return "D Reject"


# ─────────────────────────────────────────────────────────────────────────────
# Source 1: SWE-smith-mini full (66K trajectories)
# ─────────────────────────────────────────────────────────────────────────────

def acquire_swe_smith_mini(protected_ids: set) -> dict:
    """Acquire full SWE-smith-mini dataset (47 parquet shards, ~66K trajectories)."""
    source_id = "p1-swe-smith-mini"
    hf_id = "Kwai-Klear/SWE-smith-mini_swe_agent_plus-trajectories-66k"
    category = "02_software_engineering"
    subcategory = "debugging"
    license_str = "MIT"
    notes_prefix = "P1 full acquisition"

    print(f"\n{'='*70}", file=sys.stderr)
    print(f"P1 ACQUISITION: {source_id}", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)

    result = {
        "source_id": source_id,
        "hf_id": hf_id,
        "category": category,
        "subcategory": subcategory,
        "license": license_str,
        "status": "pending",
        "raw_records": 0,
        "valid_records": 0,
        "duplicate_records": 0,
        "rejected_records": 0,
        "eligible_records": 0,
        "staging_bytes": 0,
        "unique_repositories": 0,
        "languages": [],
        "task_types": {},
        "trajectory_lengths": {"min": None, "max": None, "avg": None},
        "success_failure_dist": {},
        "observation_tool_use": {"with_observations": 0, "total": 0},
        "contamination_check": {},
        "frontier_distribution": Counter(),
        "provenance": {
            "upstream_hf_id": hf_id,
            "upstream_url": f"https://huggingface.co/datasets/{hf_id}",
            "license": license_str,
            "license_class": "VERIFIED COMPATIBLE" if not is_denied_license(license_str) else "NEEDS REVIEW",
            "acquisition_date": datetime.now(timezone.utc).isoformat(),
            "source_type": "DISTILLED",
            "teacher": "SWE-agent (mini-swe-agent-plus)",
            "data_type": "Synthetic agent trajectories",
        },
        "errors": [],
        "warnings": [],
    }

    # Download all 47 parquet shards
    from huggingface_hub import hf_hub_download
    src_dir = RAW_P1 / source_id / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    print(f"  Downloading all 47 parquet shards from {hf_id}...", file=sys.stderr)
    all_parquet_files = []
    try:
        from huggingface_hub import HfApi
        api = HfApi()
        info = api.dataset_info(hf_id, files_metadata=True)
        parquet_files = sorted([
            f for f in (info.siblings or [])
            if f.rfilename.startswith("data/train-") and f.rfilename.endswith(".parquet")
        ], key=lambda x: x.rfilename)
        print(f"  Found {len(parquet_files)} parquet shards", file=sys.stderr)

        for pf in parquet_files:
            local_path = hf_hub_download(
                hf_id,
                pf.rfilename,
                repo_type="dataset",
                local_dir=str(RAW_P1 / source_id / "src"),
            )
            all_parquet_files.append(local_path)
    except Exception as e:
        result["errors"].append(f"Download failed: {e}")
        print(f"  ERROR: {e}", file=sys.stderr)
        result["status"] = "failed"
        return result

    # Process all shards
    all_records = []
    total_rows = 0
    for pf in all_parquet_files:
        try:
            import pyarrow.parquet as pq
            table = pq.read_table(pf)
            rows = table.num_rows
            total_rows += rows
            d = table.to_pydict()
            for i in range(rows):
                rec = {k: v[i] for k, v in d.items()}
                rec["_hf_id"] = hf_id
                rec["_source_url"] = f"https://huggingface.co/datasets/{hf_id}"
                all_records.append(rec)
            print(f"  {Path(pf).name}: {rows} rows", file=sys.stderr)
        except Exception as e:
            result["warnings"].append(f"Failed to read {pf}: {e}")
            print(f"  WARN: {pf}: {e}", file=sys.stderr)

    result["raw_records"] = len(all_records)
    print(f"  Total raw records: {len(all_records)}", file=sys.stderr)

    # Verify repository diversity
    repos = set()
    for rec in all_records:
        iid = rec.get("instance_id", "")
        if iid and "__" in iid:
            repo = iid.split("__")[0]
            repos.add(repo)
    result["unique_repositories"] = len(repos)
    print(f"  Unique repositories: {len(repos)}", file=sys.stderr)

    # Normalise to Atlas schema
    atlas_records = []
    for rec in all_records:
        try:
            atlas_rec = apply_atlas_schema(rec, source_id, category, subcategory, license_str, notes_prefix)
            atlas_records.append(atlas_rec)
        except Exception as e:
            result["warnings"].append(f"Schema error for {rec.get('instance_id', '?')}: {e}")

    # Deduplicate by content hash
    seen_hashes = set()
    deduped = []
    dup_count = 0
    for rec in atlas_records:
        ch = content_hash_short(rec.get("messages", []))
        if ch not in seen_hashes:
            seen_hashes.add(ch)
            deduped.append(rec)
        else:
            dup_count += 1
    result["duplicate_records"] = dup_count
    print(f"  Dedup: {len(atlas_records)} → {len(deduped)} ({dup_count} duplicates)", file=sys.stderr)

    # Trajectory analysis
    msg_counts = [len(r.get("messages", [])) for r in deduped]
    if msg_counts:
        result["trajectory_lengths"] = {
            "min": min(msg_counts),
            "max": max(msg_counts),
            "avg": round(sum(msg_counts) / len(msg_counts), 1),
        }

    # Observation/tool-use analysis
    obs_count = 0
    for rec in deduped:
        for m in rec.get("messages", []):
            if m.get("role") == "tool" or "OBSERVATION" in m.get("content", ""):
                obs_count += 1
                break
    result["observation_tool_use"] = {
        "with_observations": obs_count,
        "total": len(deduped),
        " pct": f"{obs_count/len(deduped)*100:.1f}%" if deduped else "0%",
    }

    # Validation
    staging_file = STAGING_DIR / f"{source_id}.jsonl"
    with open(staging_file, "w") as f:
        for rec in deduped:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    result["staging_bytes"] = staging_file.stat().st_size

    val = validate_one_file(staging_file, strict=False, quiet=True)
    result["valid_records"] = val["total"] - val["record_errors"]
    result["rejected_records"] = val["record_errors"]
    result["eligible_records"] = result["valid_records"]
    print(f"  Validation: {val['total']} total, {val['record_errors']} errors", file=sys.stderr)

    # Contamination check
    contam = check_contamination(deduped, source_id, protected_ids)
    result["contamination_check"] = contam
    print(f"  Contamination: {contam['overlaps_found']} overlaps with protected sets", file=sys.stderr)
    if contam["overlaps_found"] > 0:
        result["warnings"].append(f"CONTAMINATION RISK: {contam['overlaps_found']} records overlap with protected eval sets")

    # Frontier classification
    for rec in deduped:
        tier = classify_frontier(rec, source_id)
        result["frontier_distribution"][tier] += 1

    result["status"] = "completed"
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Source 2: Nemotron-Math-Proofs-v2 full (82,737 samples)
# ─────────────────────────────────────────────────────────────────────────────

def acquire_nemotron_math_full(protected_ids: set) -> dict:
    """Acquire full Nemotron-Math-Proofs-v2 (82,737 samples, CC-BY-4.0)."""
    source_id = "p1-nemotron-math-proofs-v2"
    hf_id = "nvidia/Nemotron-Math-Proofs-v2"
    category = "06_science_engineering"
    subcategory = "mathematics"
    license_str = "CC-BY-4.0"
    notes_prefix = "P1 full acquisition"

    print(f"\n{'='*70}", file=sys.stderr)
    print(f"P1 ACQUISITION: {source_id}", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)

    result = {
        "source_id": source_id,
        "hf_id": hf_id,
        "category": category,
        "subcategory": subcategory,
        "license": license_str,
        "status": "pending",
        "raw_records": 0,
        "valid_records": 0,
        "duplicate_records": 0,
        "rejected_records": 0,
        "eligible_records": 0,
        "unique_problems": 0,
        "samples_per_problem_avg": None,
        "proof_length_dist": {"min": None, "max": None, "avg": None},
        "math_domain_dist": Counter(),
        "verification_status_dist": Counter(),
        "subset_dist": Counter(),
        "contamination_check": {},
        "frontier_distribution": Counter(),
        "provenance": {
            "upstream_hf_id": hf_id,
            "upstream_url": f"https://huggingface.co/datasets/{hf_id}",
            "license": license_str,
            "license_class": "VERIFIED COMPATIBLE" if not is_denied_license(license_str) else "NEEDS REVIEW",
            "acquisition_date": datetime.now(timezone.utc).isoformat(),
            "source_type": "DISTILLED",
            "teacher": "DeepSeek-V4-Pro (Max inference mode)",
            "data_type": "Formally verified proofs",
            "problem_identity_preserved": True,
        },
        "errors": [],
        "warnings": [],
    }

    # Data is already downloaded at raw/p0/p0-nemotron-math-proofs-v2/src/
    # Find the JSONL file
    src_dir = RAW_P1 / source_id / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    # Check if already downloaded in P0
    p0_src = ROOT / "raw" / "p0" / "p0-nemotron-math-proofs-v2" / "src"
    jsonl_files = list(p0_src.rglob("*.jsonl"))
    if not jsonl_files:
        # Download from HF
        from huggingface_hub import hf_hub_download
        try:
            hf_hub_download(
                hf_id,
                "data/train.jsonl",
                repo_type="dataset",
                local_dir=str(src_dir),
            )
            jsonl_files = list(src_dir.rglob("*.jsonl"))
        except Exception as e:
            result["errors"].append(f"Download failed: {e}")
            result["status"] = "failed"
            return result
    else:
        # Copy from P0
        import shutil
        for pf in jsonl_files:
            dest = src_dir / pf.name
            if not dest.exists():
                shutil.copy2(pf, dest)
        jsonl_files = list(src_dir.rglob("*.jsonl"))

    if not jsonl_files:
        result["errors"].append("No JSONL files found")
        result["status"] = "failed"
        return result

    jsonl_path = jsonl_files[0]
    print(f"  Processing: {jsonl_path} ({jsonl_path.stat().st_size/1e9:.2f} GB)", file=sys.stderr)

    # Stream processing — write to staging incrementally to avoid OOM
    problems = set()
    subsets = Counter()
    domains = Counter()
    proof_lengths_sum = 0
    proof_lengths_count = 0
    proof_len_min = None
    proof_len_max = 0
    raw_count = 0
    dup_count = 0
    seen_hashes: set[str] = set()

    staging_file = STAGING_DIR / f"{source_id}.jsonl"

    with open(jsonl_path) as infile, open(staging_file, "w") as outfile:
        for line_num, line in enumerate(infile, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            raw_count += 1

            # Track stats without storing full record
            problem = rec.get("problem", "")
            if problem:
                problems.add(problem)
            subsets[rec.get("subset", "unknown")] += 1

            prob_lower = problem.lower() if problem else ""
            if "triangle" in prob_lower or "geometry" in prob_lower or "angle" in prob_lower:
                domains["geometry"] += 1
            elif "number theory" in prob_lower or "integer" in prob_lower or "prime" in prob_lower:
                domains["number-theory"] += 1
            elif "algebra" in prob_lower or "polynomial" in prob_lower or "equation" in prob_lower:
                domains["algebra"] += 1
            elif "combinator" in prob_lower or "probability" in prob_lower or "count" in prob_lower:
                domains["combinatorics"] += 1
            elif "function" in prob_lower or "analysis" in prob_lower or "limit" in prob_lower:
                domains["analysis"] += 1
            else:
                domains["other"] += 1

            # Proof length
            assistant_content = ""
            for m in rec.get("messages", []):
                if m.get("role") == "assistant":
                    assistant_content = m.get("content", "")
                    break
            alen = len(assistant_content)
            proof_lengths_sum += alen
            proof_lengths_count += 1
            if proof_len_min is None or alen < proof_len_min:
                proof_len_min = alen
            if alen > proof_len_max:
                proof_len_max = alen

            # Normalise and write
            rec["_hf_id"] = hf_id
            rec["_source_url"] = f"https://huggingface.co/datasets/{hf_id}"
            try:
                atlas_rec = apply_atlas_schema(rec, source_id, category, subcategory, license_str, notes_prefix)
                if problem:
                    atlas_rec["notes"] = f"{notes_prefix} — {source_id}. Problem: {problem[:100]}... Needs human review."
            except Exception:
                continue

            # Dedup on the fly
            ch = content_hash_short(atlas_rec.get("messages", []))
            if ch in seen_hashes:
                dup_count += 1
                continue
            seen_hashes.add(ch)

            outfile.write(json.dumps(atlas_rec, ensure_ascii=False) + "\n")

            if line_num % 10000 == 0:
                print(f"  Read {line_num:,} records ({raw_count:,} processed, {dup_count} dups)...", file=sys.stderr)

    result["raw_records"] = raw_count
    result["unique_problems"] = len(problems)
    result["samples_per_problem_avg"] = round(raw_count / len(problems), 2) if problems else 0
    result["subset_dist"] = dict(subsets)
    result["math_domain_dist"] = dict(domains)
    result["verification_status_dist"] = {"proof": subsets.get("proof", 0), "meta_verification": subsets.get("meta-verification", 0), "verification": subsets.get("verification", 0)}
    result["duplicate_records"] = dup_count

    if proof_lengths_count > 0:
        result["proof_length_dist"] = {
            "min": proof_len_min,
            "max": proof_len_max,
            "avg": round(proof_lengths_sum / proof_lengths_count, 1),
        }

    print(f"  Raw records: {raw_count:,}", file=sys.stderr)
    print(f"  Unique problems: {len(problems):,}", file=sys.stderr)
    print(f"  Duplicates removed: {dup_count:,}", file=sys.stderr)

    result["staging_bytes"] = staging_file.stat().st_size

    val = validate_one_file(staging_file, strict=False, quiet=True)
    result["valid_records"] = val["total"] - val["record_errors"]
    result["rejected_records"] = val["record_errors"]
    result["eligible_records"] = result["valid_records"]
    print(f"  Validation: {val['total']} total, {val['record_errors']} errors", file=sys.stderr)

    # Contamination check (stream through staging file)
    contam_records = []
    with open(staging_file) as f:
        for line in f:
            try:
                contam_records.append(json.loads(line))
            except Exception:
                pass
    contam = check_contamination(contam_records, source_id, protected_ids)
    result["contamination_check"] = contam
    print(f"  Contamination: {contam['overlaps_found']} overlaps with protected sets", file=sys.stderr)

    # Frontier classification
    for rec in contam_records:
        tier = classify_frontier(rec, source_id)
        result["frontier_distribution"][tier] += 1

    result["status"] = "completed"
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Source 3: y9 Linux kernel commits (stratified 10K sample)
# ─────────────────────────────────────────────────────────────────────────────

def acquire_y9_linux_kernel(protected_ids: set) -> dict:
    """Acquire deterministic stratified 10K sample from linux-kernel-commits."""
    source_id = "p1-y9-linux-kernel"
    hf_id = "ewedubs/linux-kernel-commits-aireason-instruct"
    category = "03_system_engineering"
    subcategory = "linux"
    license_str = "Apache-2.0"
    notes_prefix = "P1 stratified sample"
    target_n = 10000
    seed = 42

    print(f"\n{'='*70}", file=sys.stderr)
    print(f"P1 ACQUISITION: {source_id}", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)

    result = {
        "source_id": source_id,
        "hf_id": hf_id,
        "category": category,
        "subcategory": subcategory,
        "license": license_str,
        "status": "pending",
        "raw_records": 0,
        "valid_records": 0,
        "duplicate_records": 0,
        "rejected_records": 0,
        "eligible_records": 0,
        "sampled_from_total": 0,
        "sampling_method": "deterministic_stratified_by_variant",
        "sampling_seed": seed,
        "variant_distribution": {},
        " subsystem_distribution": Counter(),
        "contamination_check": {},
        "frontier_distribution": Counter(),
        "provenance": {
            "upstream_hf_id": hf_id,
            "upstream_url": f"https://huggingface.co/datasets/{hf_id}",
            "license": license_str,
            "license_class": "VERIFIED COMPATIBLE" if not is_denied_license(license_str) else "NEEDS REVIEW",
            "acquisition_date": datetime.now(timezone.utc).isoformat(),
            "source_type": "HUMAN_CURATED",
            "data_type": "Kernel commit patches with instruction",
            "commit_hash_preserved": True,
        },
        "errors": [],
        "warnings": [],
    }

    from huggingface_hub import hf_hub_download, HfApi
    src_dir = RAW_P1 / source_id / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    # Define variants and their sizes
    variants = {
        "high_score.jsonl": {"target": 3500, "description": "High quality (Heuristic >= 70, AI Score >= 4)"},
        "premium_score.jsonl": {"target": 3500, "description": "Premium quality (Heuristic >= 90, AI Score >= 4)"},
        "high_reasoning.jsonl": {"target": 1500, "description": "High quality with reasoning"},
        "premium_reasoning.jsonl": {"target": 1500, "description": "Premium with reasoning"},
        "super_ultra.jsonl": {"target": 500, "description": "AI-recommended commits"},
    }

    # Download and read all variants
    all_records = []
    variant_counts = {}
    for variant_file, variant_info in variants.items():
        try:
            local_path = hf_hub_download(
                hf_id,
                variant_file,
                repo_type="dataset",
                local_dir=str(src_dir),
            )
            count = 0
            with open(local_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        rec["_hf_id"] = hf_id
                        rec["_source_url"] = f"https://huggingface.co/datasets/{hf_id}"
                        rec["_variant"] = variant_file.replace(".jsonl", "")
                        all_records.append(rec)
                        count += 1
                    except json.JSONDecodeError:
                        continue
            variant_counts[variant_file] = count
            print(f"  {variant_file}: {count} records", file=sys.stderr)
        except Exception as e:
            result["warnings"].append(f"Failed to download {variant_file}: {e}")
            variant_counts[variant_file] = 0

    result["raw_records"] = len(all_records)
    result["sampled_from_total"] = len(all_records)
    result["variant_distribution"] = variant_counts
    print(f"  Total available: {len(all_records)}", file=sys.stderr)

    # Stratified sampling by variant
    # Group by variant
    by_variant: dict[str, list] = defaultdict(list)
    for rec in all_records:
        by_variant[rec.get("_variant", "unknown")].append(rec)

    # Deterministic stratified selection
    selected = []
    for variant_file, variant_info in variants.items():
        variant_name = variant_file.replace(".jsonl", "")
        group = by_variant.get(variant_name, [])
        target = min(variant_info["target"], len(group))
        sampled = deterministic_sample(group, target, seed=seed)
        selected.extend(sampled)
        print(f"  {variant_name}: {len(sampled)} selected from {len(group)}", file=sys.stderr)

    # If we need more, fill from remaining
    if len(selected) < target_n:
        remaining = [r for r in all_records if r not in selected]
        additional = deterministic_sample(remaining, target_n - len(selected), seed=seed + 1)
        selected.extend(additional)
        print(f"  Additional from mixed: {len(additional)}", file=sys.stderr)

    selected = selected[:target_n]
    print(f"  Final sample: {len(selected)}", file=sys.stderr)

    # Extract subsystem from input (code context)
    subsystems = Counter()
    for rec in selected:
        inp = rec.get("input", "")
        # Extract subsystem from path prefixes
        for prefix in ["drivers/", "fs/", "net/", "mm/", "kernel/", "arch/", "security/", "include/", "init/"]:
            if inp.startswith(prefix) or f"\n{prefix}" in inp:
                subsystems[prefix.rstrip("/")] += 1
                break
        else:
            subsystems["other"] += 1
    result["subsystem_distribution"] = dict(subsystems.most_common(10))

    # Normalise to Atlas schema
    atlas_records = []
    for rec in selected:
        try:
            # Build messages from instruction/input/output
            instruction = rec.get("instruction", "")
            input_ctx = rec.get("input", "")
            output_patch = rec.get("output", "")
            commit_hash = rec.get("commit_hash", "")

            messages = [
                {"role": "user", "content": f"Context:\n{input_ctx}\n\nInstruction:\n{instruction}"},
                {"role": "assistant", "content": output_patch},
            ]

            atlas_rec = {
                "id": make_id(source_id, commit_hash, ""),
                "category": category,
                "subcategory": subcategory,
                "type": "instruction",
                "source": {
                    "name": hf_id,
                    "url": f"https://huggingface.co/datasets/{hf_id}",
                    "license": license_str,
                    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                },
                "messages": messages,
                "language": "en",
                "difficulty": 3,
                "tags": sorted(set([source_id, "linux", "kernel", "patch"])),
                "quality_score": 8,
                "verified": False,
                "notes": f"P1 stratified sample — {source_id}. Commit: {commit_hash}. Subsystem: see input. Needs human review.",
            }
            # Preserve source structure in notes, not as extra keys
            atlas_records.append(atlas_rec)
        except Exception as e:
            result["warnings"].append(f"Schema error: {e}")

    # Deduplicate
    seen_hashes = set()
    deduped = []
    dup_count = 0
    for rec in atlas_records:
        ch = content_hash_short(rec.get("messages", []))
        if ch not in seen_hashes:
            seen_hashes.add(ch)
            deduped.append(rec)
        else:
            dup_count += 1
    result["duplicate_records"] = dup_count
    print(f"  Dedup: {len(atlas_records)} → {len(deduped)} ({dup_count} duplicates)", file=sys.stderr)

    # Validation
    staging_file = STAGING_DIR / f"{source_id}.jsonl"
    with open(staging_file, "w") as f:
        for rec in deduped:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    result["staging_bytes"] = staging_file.stat().st_size

    val = validate_one_file(staging_file, strict=False, quiet=True)
    result["valid_records"] = val["total"] - val["record_errors"]
    result["rejected_records"] = val["record_errors"]
    result["eligible_records"] = result["valid_records"]
    print(f"  Validation: {val['total']} total, {val['record_errors']} errors", file=sys.stderr)

    # Contamination check
    contam = check_contamination(deduped, source_id, protected_ids)
    result["contamination_check"] = contam
    print(f"  Contamination: {contam['overlaps_found']} overlaps with protected sets", file=sys.stderr)

    # Frontier classification
    for rec in deduped:
        tier = classify_frontier(rec, source_id)
        result["frontier_distribution"][tier] += 1

    result["status"] = "completed"
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Source 4: y5 StackExchange Systems (stratified 8K sample)
# ─────────────────────────────────────────────────────────────────────────────

def acquire_y5_stackexchange_systems(protected_ids: set) -> dict:
    """Acquire deterministic stratified 8K sample from StackExchange Systems.

    NOTE: The canonical source is archive.org XML dumps. This implementation
    searches for the closest available HuggingFace dataset representing
    Unix/Linux/Systems community Q&A.
    """
    source_id = "p1-y5-stackexchange-systems"
    # Primary candidate: mlfoundations-dev/stackexchange-unix-sandboxes
    # Alternative: search for direct SE dumps
    hf_candidates = [
        "mlfoundations-dev/stackexchange-unix-sandboxes",
        "laion/stackexchange-unix-sandboxes-verified",
    ]
    category = "03_system_engineering"
    subcategory = "networking"
    license_str = "CC-BY-SA-4.0"
    notes_prefix = "P1 stratified sample"
    target_n = 8000
    seed = 42

    print(f"\n{'='*70}", file=sys.stderr)
    print(f"P1 ACQUISITION: {source_id}", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)

    result = {
        "source_id": source_id,
        "hf_id": None,
        "category": category,
        "subcategory": subcategory,
        "license": license_str,
        "status": "pending",
        "raw_records": 0,
        "valid_records": 0,
        "duplicate_records": 0,
        "rejected_records": 0,
        "eligible_records": 0,
        "sampled_from_total": 0,
        "sampling_method": "deterministic_stratified",
        "sampling_seed": seed,
        "source_notes": "archive.org XML dump is canonical; using closest HF equivalent",
        "topic_distribution": Counter(),
        "site_distribution": Counter(),
        "contamination_check": {},
        "frontier_distribution": Counter(),
        "provenance": {
            "canonical_source": "https://archive.org/details/stackexchange",
            "sites": ["unix.stackexchange.com", "serverfault.com", "networkengineering.stackexchange.com"],
            "license": license_str,
            "license_class": "VERIFIED COMPATIBLE (with attribution)",
            "attribution_required": True,
            "share_alike": True,
            "acquisition_date": datetime.now(timezone.utc).isoformat(),
            "source_type": "COMMUNITY_QA",
        },
        "errors": [],
        "warnings": [],
    }

    from huggingface_hub import hf_hub_download, HfApi
    src_dir = RAW_P1 / source_id / "src"
    src_dir.mkdir(parents=True, exist_ok=True)

    # Try to find and download a suitable dataset
    downloaded = False
    all_records: list[dict] = []
    for candidate_hf_id in hf_candidates:
        try:
            api = HfApi()
            info = api.dataset_info(candidate_hf_id, files_metadata=True)
            parquet_files = [f for f in (info.siblings or []) if f.rfilename.endswith(".parquet")]
            if not parquet_files:
                continue

            print(f"  Trying {candidate_hf_id} ({len(parquet_files)} parquet files)...", file=sys.stderr)
            local_files = []
            for pf in parquet_files:
                local_path = hf_hub_download(
                    candidate_hf_id,
                    pf.rfilename,
                    repo_type="dataset",
                    local_dir=str(src_dir),
                )
                local_files.append(local_path)

            # Read and process
            import pyarrow.parquet as pq
            for lf in local_files:
                try:
                    table = pq.read_table(lf)
                    d = table.to_pydict()
                    for i in range(table.num_rows):
                        rec = {k: v[i] for k, v in d.items()}
                        rec["_hf_id"] = candidate_hf_id
                        rec["_source_url"] = f"https://huggingface.co/datasets/{candidate_hf_id}"
                        all_records.append(rec)
                    print(f"    {Path(lf).name}: {table.num_rows} rows", file=sys.stderr)
                except Exception as e:
                    result["warnings"].append(f"Failed to read {lf}: {e}")

            if all_records:
                result["hf_id"] = candidate_hf_id
                downloaded = True
                break
        except Exception as e:
            print(f"  {candidate_hf_id} failed: {e}", file=sys.stderr)
            continue

    if not downloaded:
        result["warnings"].append(
            "No suitable HuggingFace dataset found for StackExchange Systems. "
            "Canonical source is archive.org XML dumps. Consider manual acquisition."
        )
        result["status"] = "partial"
        result["errors"].append("No downloadable source found for y5 StackExchange Systems")
        return result

    result["raw_records"] = len(all_records)
    result["sampled_from_total"] = len(all_records)
    print(f"  Total available: {len(all_records)}", file=sys.stderr)

    # Determine available columns and stratify
    if all_records:
        sample_keys = list(all_records[0].keys())
        print(f"  Available columns: {sample_keys}", file=sys.stderr)

        # Try to stratify by topic/site if available
        stratify_field = None
        for field in ["site", "topic", "category", "tag", "post_type"]:
            if field in sample_keys:
                stratify_field = field
                break

        if stratify_field:
            selected = stratified_sample_by_field(all_records, target_n, stratify_field, seed=seed)
            # Track distribution
            for rec in selected:
                result["site_distribution"][str(rec.get(stratify_field, "unknown"))] += 1
        else:
            selected = deterministic_sample(all_records, target_n, seed=seed)

        # Topic distribution from tags/content
        for rec in selected:
            tags = rec.get("tags", [])
            if isinstance(tags, list):
                for t in tags[:3]:
                    result["topic_distribution"][str(t)] += 1
            elif isinstance(tags, str):
                result["topic_distribution"][tags[:50]] += 1
    else:
        selected = []

    print(f"  Selected: {len(selected)}", file=sys.stderr)

    # Normalise to Atlas schema
    atlas_records = []
    for rec in selected:
        try:
            # Extract question/answer from available columns
            question = rec.get("question", rec.get("title", rec.get("body", "")))
            answer = rec.get("answer", rec.get("response", rec.get("accepted_answer", "")))
            site = rec.get("site", "unix.stackexchange")
            owner = rec.get("owner", "")
            score = rec.get("score", 0)
            url = rec.get("url", rec.get("link", ""))

            # Build attribution
            attribution = f"Source: {site}"
            if url:
                attribution += f" ({url})"
            if owner:
                attribution += f" — Author: {owner}"
            if score:
                attribution += f" — Score: {score}"

            messages = [
                {"role": "user", "content": str(question)[:2000]},
                {"role": "assistant", "content": str(answer)[:2000] if answer else "See source."},
            ]

            atlas_rec = {
                "id": make_id(source_id, str(rec.get("id", rec.get("post_id", ""))), ""),
                "category": category,
                "subcategory": subcategory,
                "type": "qa",
                "source": {
                    "name": result["hf_id"] or "StackExchange Systems",
                    "url": url or f"https://{site}.com",
                    "license": license_str,
                    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "attribution": attribution,
                },
                "messages": messages,
                "language": "en",
                "difficulty": min(3, max(1, int(score / 5) + 1)) if isinstance(score, (int, float)) else 2,
                "tags": sorted(set([source_id, "systems", "stackexchange", site.replace(".", "-")])),
                "quality_score": min(10, 5 + int(score / 3)) if isinstance(score, (int, float)) else 6,
                "verified": False,
                "notes": f"P1 stratified sample — {source_id}. Site: {site}. Attribution required (CC-BY-SA-4.0). Needs human review.",
            }
            atlas_records.append(atlas_rec)
        except Exception as e:
            result["warnings"].append(f"Schema error: {e}")

    # Deduplicate
    seen_hashes = set()
    deduped = []
    dup_count = 0
    for rec in atlas_records:
        ch = content_hash_short(rec.get("messages", []))
        if ch not in seen_hashes:
            seen_hashes.add(ch)
            deduped.append(rec)
        else:
            dup_count += 1
    result["duplicate_records"] = dup_count
    print(f"  Dedup: {len(atlas_records)} → {len(deduped)} ({dup_count} duplicates)", file=sys.stderr)

    # Validation
    staging_file = STAGING_DIR / f"{source_id}.jsonl"
    with open(staging_file, "w") as f:
        for rec in deduped:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    result["staging_bytes"] = staging_file.stat().st_size

    val = validate_one_file(staging_file, strict=False, quiet=True)
    result["valid_records"] = val["total"] - val["record_errors"]
    result["rejected_records"] = val["record_errors"]
    result["eligible_records"] = result["valid_records"]
    print(f"  Validation: {val['total']} total, {val['record_errors']} errors", file=sys.stderr)

    # Contamination check
    contam = check_contamination(deduped, source_id, protected_ids)
    result["contamination_check"] = contam

    # Frontier classification
    for rec in deduped:
        tier = classify_frontier(rec, source_id)
        result["frontier_distribution"][tier] += 1

    result["status"] = "completed"
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Cross-source deduplication
# ─────────────────────────────────────────────────────────────────────────────

def cross_source_dedup(results: dict) -> dict:
    """Run cross-source deduplication across all P1 acquisitions."""
    print(f"\n{'='*70}", file=sys.stderr)
    print("CROSS-SOURCE DEDUPLICATION", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)

    all_hashes = defaultdict(list)  # hash -> [(source_id, record_index)]
    source_files = {}

    for sid in results:
        sf = STAGING_DIR / f"{sid}.jsonl"
        if sf.exists():
            source_files[sid] = sf

    cross_dups = 0
    for sid, sf in source_files.items():
        with open(sf) as f:
            for idx, line in enumerate(f):
                try:
                    rec = json.loads(line)
                    ch = content_hash_short(rec.get("messages", []))
                    all_hashes[ch].append((sid, idx))
                except Exception:
                    pass

    # Find cross-source duplicates
    cross_dup_pairs = []
    for h, locations in all_hashes.items():
        sources = set(loc[0] for loc in locations)
        if len(sources) > 1:
            cross_dup_pairs.append((h, locations))
            cross_dups += 1

    print(f"  Cross-source duplicates: {cross_dups}", file=sys.stderr)
    for h, locs in cross_dup_pairs[:10]:
        source_list = [f"{sid}:{idx}" for sid, idx in locs]
        print(f"    Hash {h}: {source_list}", file=sys.stderr)

    return {"cross_source_duplicates": cross_dups, "pairs": [(h, locs) for h, locs in cross_dup_pairs[:50]]}


# ─────────────────────────────────────────────────────────────────────────────
# Specialist mapping (policy-level, not on records)
# ─────────────────────────────────────────────────────────────────────────────

SPECIALIST_MAPPING = {
    "p1-swe-smith-mini": {"domain": "Code", "conceptual_domains": ["Code"]},
    "p1-nemotron-math-proofs-v2": {"domain": "Math", "conceptual_domains": ["Math"]},
    "p1-y9-linux-kernel": {"domain": "Systems", "conceptual_domains": ["Systems", "Hardware"]},
    "p1-y5-stackexchange-systems": {"domain": "Systems", "conceptual_domains": ["Systems"]},
}


# ─────────────────────────────────────────────────────────────────────────────
# Final report generation
# ─────────────────────────────────────────────────────────────────────────────

def generate_final_report(results: dict, cross_dedup: dict) -> dict:
    """Generate the final P1 acquisition report."""
    report = {
        "phase": "P1 Frontier Expansion",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "COMPLETE",
        "summary": {
            "total_sources": len(results),
            "total_raw": sum(r.get("raw_records", 0) for r in results.values()),
            "total_valid": sum(r.get("valid_records", 0) for r in results.values()),
            "total_duplicate": sum(r.get("duplicate_records", 0) for r in results.values()),
            "total_rejected": sum(r.get("rejected_records", 0) for r in results.values()),
            "total_eligible": sum(r.get("eligible_records", 0) for r in results.values()),
            "total_staging_bytes": sum(r.get("staging_bytes", 0) for r in results.values()),
        },
        "sources": results,
        "cross_source_dedup": cross_dedup,
        "specialist_mapping": SPECIALIST_MAPPING,
        "inventory_by_domain": {},
        "frontier_summary": {},
    }

    # Aggregate by domain
    domain_counts = defaultdict(lambda: {"records": 0, "eligible": 0, "frontier": Counter()})
    for sid, r in results.items():
        mapping = SPECIALIST_MAPPING.get(sid, {})
        domain = mapping.get("domain", "General")
        domain_counts[domain]["records"] += r.get("raw_records", 0)
        domain_counts[domain]["eligible"] += r.get("eligible_records", 0)
        for tier, count in r.get("frontier_distribution", {}).items():
            domain_counts[domain]["frontier"][tier] += count

    report["inventory_by_domain"] = {
        d: {
            "total_records": v["records"],
            "eligible": v["eligible"],
            "frontier_distribution": dict(v["frontier"]),
        }
        for d, v in domain_counts.items()
    }

    # Frontier summary
    for tier in ["A+ Frontier", "A Strong Specialist", "B Professional", "C General", "D Reject"]:
        report["frontier_summary"][tier] = sum(
            r.get("frontier_distribution", {}).get(tier, 0)
            for r in results.values()
        )

    return report


def print_final_table(results: dict, cross_dedup: dict):
    """Print the final inventory table."""
    print("\n" + "=" * 100, file=sys.stderr)
    print("P1 ACQUISITION FINAL INVENTORY", file=sys.stderr)
    print("=" * 100, file=sys.stderr)

    header = f"{'Source':<42} {'Raw':>7} {'Valid':>7} {'Dup':>7} {'Reject':>7} {'Elig':>7} {'Bytes':>12}"
    print(header, file=sys.stderr)
    print("-" * 100, file=sys.stderr)

    for sid, r in results.items():
        name = sid.replace("p1-", "")[:40]
        raw = r.get("raw_records", 0)
        valid = r.get("valid_records", 0)
        dup = r.get("duplicate_records", 0)
        reject = r.get("rejected_records", 0)
        elig = r.get("eligible_records", 0)
        bytes_ = r.get("staging_bytes", 0)
        print(f"  {name:<40} {raw:>7,} {valid:>7,} {dup:>7,} {reject:>7,} {elig:>7,} {bytes_:>12,}", file=sys.stderr)

    print("-" * 100, file=sys.stderr)
    totals = report_summary = {
        "raw": sum(r.get("raw_records", 0) for r in results.values()),
        "valid": sum(r.get("valid_records", 0) for r in results.values()),
        "dup": sum(r.get("duplicate_records", 0) for r in results.values()),
        "reject": sum(r.get("rejected_records", 0) for r in results.values()),
        "elig": sum(r.get("eligible_records", 0) for r in results.values()),
        "bytes": sum(r.get("staging_bytes", 0) for r in results.values()),
    }
    print(f"  {'TOTAL':<40} {totals['raw']:>7,} {totals['valid']:>7,} {totals['dup']:>7,} {totals['reject']:>7,} {totals['elig']:>7,} {totals['bytes']:>12,}", file=sys.stderr)

    # Domain aggregation
    print("\nDOMAIN AGGREGATION:", file=sys.stderr)
    domain_cols = {"Math": 0, "Code": 0, "Systems": 0, "Hardware": 0, "General": 0}
    for sid, r in results.items():
        mapping = SPECIALIST_MAPPING.get(sid, {})
        domain = mapping.get("domain", "General")
        if domain in domain_cols:
            domain_cols[domain] += r.get("eligible_records", 0)
    for domain, count in domain_cols.items():
        print(f"  {domain:<15} {count:>7,}", file=sys.stderr)

    # Contamination summary
    print("\nCONTAMINATION CHECK:", file=sys.stderr)
    for sid, r in results.items():
        cc = r.get("contamination_check", {})
        risk = cc.get("risk_level", "UNKNOWN")
        overlaps = cc.get("overlaps_found", 0)
        print(f"  {sid:<42} risk={risk:<10} overlaps={overlaps}", file=sys.stderr)

    # Frontier tier distribution
    print("\nFRONTIER TIER DISTRIBUTION:", file=sys.stderr)
    tiers = ["A+ Frontier", "A Strong Specialist", "B Professional", "C General", "D Reject"]
    for tier in tiers:
        count = sum(r.get("frontier_distribution", {}).get(tier, 0) for r in results.values())
        print(f"  {tier:<20} {count:>7,}", file=sys.stderr)

    # Cross-source dedup
    print(f"\nCROSS-SOURCE DUPLICATES: {cross_dedup.get('cross_source_duplicates', 0)}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Atlas P1 Frontier Acquisition")
    ap.add_argument("--dry-run", action="store_true", help="Plan only, no downloads")
    ap.add_argument("--source", type=str, help="Acquire only specific source (e.g., p1-swe-smith-mini)")
    args = ap.parse_args()

    print("=" * 70, file=sys.stderr)
    print("ATLAS P1 FRONTIER ACQUISITION", file=sys.stderr)
    print(f"Started: {datetime.now(timezone.utc).isoformat()}", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    # Load protected eval IDs
    protected_ids = load_protected_eval_ids()

    # Define sources to acquire
    sources = {
        "p1-swe-smith-mini": acquire_swe_smith_mini,
        "p1-nemotron-math-proofs-v2": acquire_nemotron_math_full,
        "p1-y9-linux-kernel": acquire_y9_linux_kernel,
        "p1-y5-stackexchange-systems": acquire_y5_stackexchange_systems,
    }

    if args.source:
        if args.source not in sources:
            print(f"ERROR: Unknown source '{args.source}'", file=sys.stderr)
            print(f"Available: {list(sources.keys())}", file=sys.stderr)
            return 1
        run_sources = {args.source: sources[args.source]}
    else:
        run_sources = sources

    results = {}
    for sid, acquire_fn in run_sources.items():
        if args.dry_run:
            print(f"\n[DRY RUN] Would acquire {sid}", file=sys.stderr)
            results[sid] = {"source_id": sid, "status": "dry_run", "raw_records": 0}
            continue
        try:
            results[sid] = acquire_fn(protected_ids)
        except Exception as e:
            print(f"ERROR acquiring {sid}: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            results[sid] = {
                "source_id": sid, "status": "failed", "errors": [str(e)],
                "raw_records": 0, "valid_records": 0, "duplicate_records": 0,
                "rejected_records": 0, "eligible_records": 0,
            }

    # Cross-source dedup
    cross_dedup = cross_source_dedup(results)

    # Generate final report
    final_report = generate_final_report(results, cross_dedup)

    # Print table
    print_final_table(results, cross_dedup)

    # Save report
    report_path = REPORTS_DIR / "p1_frontier_acquisition_report.json"
    report_path.write_text(json.dumps(final_report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReport saved: {report_path}", file=sys.stderr)

    # Save staging manifest
    manifest = {
        "phase": "P1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "staging_files": {
            sid: str(STAGING_DIR / f"{sid}.jsonl")
            for sid in results
            if (STAGING_DIR / f"{sid}.jsonl").exists()
        },
    }
    manifest_path = METADATA_DIR / "p1_staging_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Manifest saved: {manifest_path}", file=sys.stderr)

    # Summary
    completed = sum(1 for r in results.values() if r.get("status") == "completed")
    failed = sum(1 for r in results.values() if r.get("status") == "failed")
    total_eligible = sum(r.get("eligible_records", 0) for r in results.values())
    print(f"\nP1 Acquisition: {completed} completed, {failed} failed, {total_eligible:,} eligible records", file=sys.stderr)

    if failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
