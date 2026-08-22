#!/usr/bin/env python3
"""
Atlas P0 Frontier Dataset Acquisition Pipeline
VERIFICATION → CLASSIFICATION → DOWNLOAD → ETL → VALIDATION → INVENTORY
"""
import json
import sys
import time
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from huggingface_hub import HfApi
from downloader.adapters.huggingface import HuggingFaceAdapter
from downloader.cache import CacheManager
from etl.pipeline import run_etl_for_source
from atlas_constants import is_denied_license, VALID_CATEGORIES

ROOT = Path(__file__).resolve().parents[1]

# ============================================================
# P0 SOURCE DEFINITIONS
# ============================================================
P0_SOURCES = [
    {
        "source_id": "p0-nemotron-math-proofs-v2",
        "hf_id": "nvidia/Nemotron-Math-Proofs-v2",
        "domain": "math",
        "role": "TRAINING",
        "category": "06_science_engineering",
        "subcategory": "mathematics",
        "extraction_method": "cot_pair",
        "description": "NVIDIA Nemotron formally verified math proofs (v2)",
        "expected_data_type": "synthetic_distilled",
        "teacher_model": "Llama-3.1-405B-Instruct",
    },
    {
        "source_id": "p0-swe-smith-trajectories",
        "hf_id": "SWE-bench/SWE-smith-trajectories",
        "domain": "code",
        "role": "TRAINING",
        "category": "02_software_engineering",
        "subcategory": "debugging",
        "extraction_method": "instruction_pair",
        "description": "SWE-smith 66K verified agent trajectories",
        "expected_data_type": "distilled",
        "teacher_model": "SWE-agent",
    },
    {
        "source_id": "p0-cpp-compiler-curriculum",
        "hf_id": "gonzalolinares/cpp-compiler-curriculum",
        "domain": "systems",
        "role": "TRAINING",
        "category": "03_system_engineering",
        "subcategory": "linux",
        "extraction_method": "instruction_pair",
        "description": "C++ compiler curriculum (LLM-generated from textbooks)",
        "expected_data_type": "synthetic",
        "teacher_model": "UNKNOWN",
    },
    {
        "source_id": "p0-swe-smith-mini",
        "hf_id": "Kwai-Klear/SWE-smith-mini_swe_agent_plus-trajectories-66k",
        "domain": "code",
        "role": "TRAINING",
        "category": "02_software_engineering",
        "subcategory": "debugging",
        "extraction_method": "instruction_pair",
        "description": "SWE-smith mini agent trajectories 66K",
        "expected_data_type": "synthetic",
        "teacher_model": "SWE-agent",
    },
    {
        "source_id": "p0-ifeval",
        "hf_id": "google/IFEval",
        "domain": "evaluation",
        "role": "EVALUATION",
        "category": "06_science_engineering",
        "subcategory": "general",
        "extraction_method": "instruction_pair",
        "description": "Google IFEval — instruction following evaluation benchmark",
        "expected_data_type": "human",
        "teacher_model": None,
    },
    {
        "source_id": "p0-swe-bench-verified",
        "hf_id": "princeton-nlp/SWE-bench_Verified",
        "domain": "code",
        "role": "BOTH_WITH_STRICT_SPLIT",
        "category": "02_software_engineering",
        "subcategory": "debugging",
        "extraction_method": "issue_to_patch",
        "description": "SWE-bench Verified — gold patches with verification predicates",
        "expected_data_type": "human",
        "teacher_model": None,
    },
    {
        "source_id": "p0-multi-domain-reasoning",
        "hf_id": "khazarai/Multi-Domain-Reasoning-Benchmark",
        "domain": "reasoning",
        "role": "TRAINING",
        "category": "06_science_engineering",
        "subcategory": "general",
        "extraction_method": "qa_pair",
        "description": "Multi-domain reasoning benchmark with verification",
        "expected_data_type": "human",
        "teacher_model": None,
    },
    {
        "source_id": "p0-quantum-hardware-physics",
        "hf_id": "Neura-parse/quantum-hardware-device-physics",
        "domain": "science",
        "role": "TRAINING",
        "category": "05_hardware_engineering",
        "subcategory": "cpu",
        "extraction_method": "instruction_pair",
        "description": "Quantum hardware device physics dataset",
        "expected_data_type": "synthetic",
        "teacher_model": "UNKNOWN",
    },
]

# ============================================================
# VERIFICATION PHASE
# ============================================================
print("=" * 70, file=sys.stderr)
print("PHASE 1: VERIFICATION — Fetching HF metadata for P0 sources", file=sys.stderr)
print("=" * 70, file=sys.stderr)

api = HfApi()
verification_results = []

for src in P0_SOURCES:
    print(f"\n  Verifying: {src['hf_id']}", file=sys.stderr)
    try:
        info = api.dataset_info(src["hf_id"], timeout=60)
        card = getattr(info, "card_data", None)

        lic_raw = "UNKNOWN"
        if card and hasattr(card, "license"):
            vals = card.license
            lic_raw = vals[0] if isinstance(vals, list) and vals else str(vals)
        elif card and hasattr(card, "__dict__"):
            lic_raw = card.__dict__.get("license", "UNKNOWN")

        lic_class = "UNKNOWN"
        if lic_raw != "UNKNOWN":
            if any(l in lic_raw.lower() for l in ["apache-2.0", "mit", "cc0-1.0", "cc-by-4.0",
                                                     "odc-by", "public-domain", "isc", "bsd"]):
                lic_class = "VERIFIED COMPATIBLE"
            elif "nc" in lic_raw.lower() or "non-commercial" in lic_raw.lower():
                lic_class = "INCOMPATIBLE"
            elif "rail" in lic_raw.lower() or "rai" in lic_raw.lower():
                lic_class = "NEEDS REVIEW"
            elif "cc-by-sa" in lic_raw.lower():
                lic_class = "NEEDS REVIEW"
            else:
                lic_class = "NEEDS REVIEW"

        denied = is_denied_license(lic_raw)

        siblings = info.siblings or []
        files = [s.rfilename for s in siblings if hasattr(s, "rfilename")]

        desc = (info.description or "")[:500]

        result = {
            "source_id": src["source_id"],
            "hf_id": src["hf_id"],
            "domain": src["domain"],
            "role": src["role"],
            "license_raw": lic_raw,
            "license_class": lic_class,
            "license_denied": denied,
            "downloads": info.downloads or 0,
            "likes": info.likes or 0,
            "gated": getattr(info, "gated", False),
            "file_count": len(files),
            "available_files": files[:20],
            "description_snippet": desc[:300],
            "created_at": str(info.created_at) if info.created_at else "UNKNOWN",
            "last_modified": str(info.lastModified) if info.lastModified else "UNKNOWN",
            "tags": info.tags or [],
            "verification": "PASS",
            "discrepancies": [],
        }

        # Check discrepancies vs discovery report
        # (We already know licenses from enrichment; flag if different)
        if src["role"] == "EVALUATION" and lic_class == "VERIFIED COMPATIBLE":
            pass  # Good
        elif denied:
            result["verification"] = "BLOCKED"
            result["discrepancies"].append(f"License DENIED: {lic_raw}")

        verification_results.append(result)
        print(f"  ✓ {src['hf_id']}: license={lic_raw} ({lic_class}), {len(files)} files, {info.downloads} dl", file=sys.stderr)

    except Exception as e:
        print(f"  ✗ {src['hf_id']}: ERROR {e}", file=sys.stderr)
        verification_results.append({
            "source_id": src["source_id"],
            "hf_id": src["hf_id"],
            "domain": src["domain"],
            "role": src["role"],
            "license_raw": "UNKNOWN",
            "license_class": "UNKNOWN",
            "license_denied": True,
            "downloads": 0,
            "likes": 0,
            "gated": False,
            "file_count": 0,
            "available_files": [],
            "description_snippet": "",
            "created_at": "UNKNOWN",
            "last_modified": "UNKNOWN",
            "tags": [],
            "verification": "ERROR",
            "discrepancies": [str(e)],
        })
    time.sleep(0.3)

# Save verification
ver_path = ROOT / "metadata" / "p0_verification.json"
ver_path.parent.mkdir(parents=True, exist_ok=True)
ver_path.write_text(json.dumps(verification_results, indent=2), encoding="utf-8")
print(f"\n  Verification saved to {ver_path}", file=sys.stderr)

# ============================================================
# PHASE 2: CLASSIFY DATASET ROLE
# ============================================================
print("\n" + "=" * 70, file=sys.stderr)
print("PHASE 2: ROLE CLASSIFICATION", file=sys.stderr)
print("=" * 70, file=sys.stderr)

classifications = []
for vr, src in zip(verification_results, P0_SOURCES):
    cls = {
        "source_id": src["source_id"],
        "hf_id": src["hf_id"],
        "role": src["role"],
        "domain": src["domain"],
        "category": src["category"],
        "subcategory": src["subcategory"],
        "license": vr["license_raw"],
        "license_class": vr["license_class"],
        "train_eligible": src["role"] in ("TRAINING", "BOTH_WITH_STRICT_SPLIT"),
        "eval_eligible": src["role"] in ("EVALUATION", "BOTH_WITH_STRICT_SPLIT"),
        "strict_split_required": src["role"] == "BOTH_WITH_STRICT_SPLIT",
        "specialist_pools": [],
        "contamination_risk": "LOW",
    }

    # Map to specialist pools
    pool_map = {
        "math": ["Math"],
        "code": ["Code", "Software Engineering"],
        "systems": ["Systems", "Hardware"],
        "reasoning": ["General Reasoning"],
        "science": ["Science", "Hardware"],
        "evaluation": ["Evaluation (protected)"],
    }
    cls["specialist_pools"] = pool_map.get(src["domain"], ["General"])

    # Contamination risk
    if src["role"] == "EVALUATION":
        cls["contamination_risk"] = "HIGH — EVAL ONLY, must not mix with training"
    elif src["role"] == "BOTH_WITH_STRICT_SPLIT":
        cls["contamination_risk"] = "MEDIUM — strict train/eval split required"
    elif src["domain"] in ("math", "code"):
        cls["contamination_risk"] = "MEDIUM — widely-used benchmarks"
    else:
        cls["contamination_risk"] = "LOW"

    classifications.append(cls)
    status = "✓" if vr["verification"] != "BLOCKED" else "✗"
    print(f"  {status} {src['source_id']}: role={src['role']}, license={vr['license_class']}", file=sys.stderr)

cls_path = ROOT / "metadata" / "p0_classifications.json"
cls_path.write_text(json.dumps(classifications, indent=2), encoding="utf-8")

# ============================================================
# PHASE 3: UPDATE SOURCE REGISTRY
# ============================================================
print("\n" + "=" * 70, file=sys.stderr)
print("PHASE 3: SOURCE REGISTRY UPDATE", file=sys.stderr)
print("=" * 70, file=sys.stderr)

registry_path = ROOT / "metadata" / "source_registry.json"
with open(registry_path) as f:
    registry = json.load(f)

existing_ids = {s["id"] for s in registry["sources"]}
new_sources = []
for cls in classifications:
    sid = cls["source_id"]
    if sid in existing_ids:
        print(f"  SKIP (already exists): {sid}", file=sys.stderr)
        continue

    # Find matching verification result
    vr = next(v for v in verification_results if v["source_id"] == sid)
    src_def = next(s for s in P0_SOURCES if s["source_id"] == sid)

    reg_entry = {
        "id": sid,
        "name": vr["hf_id"],
        "source": f"HuggingFace/{vr['hf_id'].split('/')[0]}",
        "url": f"https://huggingface.co/datasets/{vr['hf_id']}",
        "category": cls["category"],
        "subcategory_hint": cls["subcategory"],
        "tier": "Tier 2 (frontier-discovered)",
        "license": vr["license_raw"],
        "license_class": cls["license_class"],
        "format": "JSONL/Parquet (HF default)",
        "size": f"{vr['file_count']} files available",
        "status": "accepted" if cls["train_eligible"] else "review",
        "quality_score": 0,
        "scores": {
            "accuracy": 0,
            "technical": 0,
            "diversity": 0,
            "cleanliness": 0,
            "license_clarity": 10 if cls["license_class"] == "VERIFIED COMPATIBLE" else 5,
        },
        "recommendation": "accept" if cls["train_eligible"] and cls["license_class"] != "INCOMPATIBLE" else "review",
        "notes": (
            f"P0 frontier discovery 2026-08-14. "
            f"Role: {cls['role']}. "
            f"Domain: {src_def['domain']}. "
            f"Data type: {src_def['expected_data_type']}. "
            f"Teacher: {src_def.get('teacher_model') or 'N/A'}. "
            f"Downloads: {vr['downloads']}. "
            f"Files: {vr['available_files'][:5]}"
        ),
        "acquisition_phase": "p0",
        "acquisition_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "role_classification": cls["role"],
        "contamination_risk": cls["contamination_risk"],
    }
    new_sources.append(reg_entry)
    print(f"  ADD: {sid} → {vr['hf_id']} ({cls['role']}, {vr['license_class']})", file=sys.stderr)

if new_sources:
    registry["sources"].extend(new_sources)
    registry["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(registry_path, "w") as f:
        json.dump(registry, f, indent=2)
    print(f"\n  Registry updated: {len(new_sources)} new sources added", file=sys.stderr)
else:
    print("\n  No new sources to add", file=sys.stderr)

# ============================================================
# PHASE 4: DOWNLOAD
# ============================================================
print("\n" + "=" * 70, file=sys.stderr)
print("PHASE 4: ACTUAL DOWNLOAD", file=sys.stderr)
print("=" * 70, file=sys.stderr)

cache = CacheManager(ROOT)
adapter = HuggingFaceAdapter(cache)

download_results = {}
train_sources = [c for c in classifications if c["train_eligible"]]
eval_sources = [c for c in classifications if c["eval_eligible"]]

for cls in classifications:
    sid = cls["source_id"]
    hf_id = cls["hf_id"]
    url = f"https://huggingface.co/datasets/{hf_id}"

    source_def = {
        "id": sid,
        "name": hf_id,
        "url": url,
        "source_type": "huggingface",
    }

    print(f"\n  Downloading: {hf_id}", file=sys.stderr)
    try:
        result = adapter.download(source_def, dry_run=False)
        download_results[sid] = {
            "hf_id": hf_id,
            "status": result.status.value,
            "summary": result.summary,
            "files": result.files,
            "errors": result.errors,
            "warnings": result.warnings,
            "entries": [e.to_dict() for e in result.entries],
            "size_bytes": sum(e.size_bytes for e in result.entries) if result.entries else 0,
        }
        print(f"  {'✓' if result.ok else '✗'} {result.status.value}: {result.summary}", file=sys.stderr)
    except Exception as e:
        download_results[sid] = {
            "hf_id": hf_id,
            "status": "failed",
            "summary": str(e),
            "files": [],
            "errors": [str(e)],
            "warnings": [],
            "entries": [],
            "size_bytes": 0,
        }
        print(f"  ✗ ERROR: {e}", file=sys.stderr)
    time.sleep(0.5)

dl_path = ROOT / "metadata" / "p0_downloads.json"
dl_path.write_text(json.dumps(download_results, indent=2), encoding="utf-8")
print(f"\n  Download results saved to {dl_path}", file=sys.stderr)

# ============================================================
# PHASE 5: ETL PIPELINE
# ============================================================
print("\n" + "=" * 70, file=sys.stderr)
print("PHASE 5: ETL PIPELINE", file=sys.stderr)
print("=" * 70, file=sys.stderr)

etl_results = {}
for cls in classifications:
    sid = cls["source_id"]
    dl = download_results.get(sid, {})
    if dl.get("status") in ("failed", "") or not dl.get("entries"):
        # No files downloaded — skip ETL
        etl_results[sid] = {
            "source_id": sid,
            "status": "skipped",
            "summary": "No files downloaded",
            "extracted": 0,
            "normalized": 0,
            "cleaned": 0,
            "atlas_records": 0,
            "dropped": 0,
            "errors": ["No cached files — download failed or blocked"],
        }
        continue

    print(f"\n  ETL: {sid} ({cls['role']})", file=sys.stderr)
    try:
        # Limit to reasonable sample for pilot
        etl_result = run_etl_for_source(ROOT, sid, limit=500, promote_atlas=True)
        etl_results[sid] = {
            "source_id": sid,
            "status": etl_result.status,
            "summary": etl_result.summary,
            "extracted": etl_result.extracted,
            "normalized": etl_result.normalized,
            "cleaned": etl_result.cleaned,
            "atlas_records": etl_result.atlas_records,
            "dropped": etl_result.dropped,
            "files_processed": etl_result.files_processed,
            "errors": etl_result.errors,
            "warnings": etl_result.warnings,
            "stats": etl_result.stats,
        }
        print(f"  {'✓' if etl_result.status == 'passed' else '✗'} {etl_result.summary}", file=sys.stderr)
    except Exception as e:
        print(f"  ✗ ETL ERROR: {e}", file=sys.stderr)
        etl_results[sid] = {
            "source_id": sid,
            "status": "failed",
            "summary": str(e),
            "extracted": 0,
            "normalized": 0,
            "cleaned": 0,
            "atlas_records": 0,
            "dropped": 0,
            "errors": [str(e)],
        }
    time.sleep(0.3)

etl_path = ROOT / "metadata" / "p0_etl_results.json"
etl_path.write_text(json.dumps(etl_results, indent=2), encoding="utf-8")
print(f"\n  ETL results saved to {etl_path}", file=sys.stderr)

# ============================================================
# PHASE 6: VALIDATE
# ============================================================
print("\n" + "=" * 70, file=sys.stderr)
print("PHASE 6: VALIDATION", file=sys.stderr)
print("=" * 70, file=sys.stderr)

validation_results = {}
for sid, etl in etl_results.items():
    if etl.get("status") not in ("passed",):
        validation_results[sid] = {
            "source_id": sid,
            "status": "skipped",
            "records_validated": 0,
            "records_with_errors": 0,
            "schema_errors": 0,
            "license_errors": 0,
            "duplicate_errors": 0,
            "quality_errors": 0,
            "details": "ETL did not complete",
        }
        continue

    staging_path = ROOT / "metadata" / "etl" / sid / "atlas_staging.jsonl"
    if not staging_path.exists():
        validation_results[sid] = {
            "source_id": sid,
            "status": "skipped",
            "records_validated": 0,
            "records_with_errors": 0,
            "details": "No staging file found",
        }
        continue

    # Run structural validation
    from validate_dataset import validate_one_file
    val_result = validate_one_file(staging_path, strict=False, quiet=True)
    validation_results[sid] = {
        "source_id": sid,
        "status": "passed" if val_result["record_errors"] == 0 else "partial",
        "records_validated": val_result["total"],
        "records_with_errors": val_result["record_errors"],
        "bad_json": val_result["bad_json"],
        "details": f"{val_result['total']} total, {val_result['record_errors']} with errors",
    }
    print(f"  {'✓' if val_result['record_errors'] == 0 else '⚠'} {sid}: {val_result['total']} records, {val_result['record_errors']} errors", file=sys.stderr)
    time.sleep(0.2)

val_path = ROOT / "metadata" / "p0_validation.json"
val_path.write_text(json.dumps(validation_results, indent=2), encoding="utf-8")

# ============================================================
# PHASE 7: SIZE INVENTORY
# ============================================================
print("\n" + "=" * 70, file=sys.stderr)
print("PHASE 7: SIZE INVENTORY", file=sys.stderr)
print("=" * 70, file=sys.stderr)

inventory = {}
for sid, etl in etl_results.items():
    if etl.get("status") not in ("passed",):
        continue
    staging = ROOT / "metadata" / "etl" / sid / "atlas_staging.jsonl"
    cleaned = ROOT / "metadata" / "etl" / sid / "cleaned.jsonl"
    normalized = ROOT / "metadata" / "etl" / sid / "normalized.jsonl"

    inv = {"source_id": sid, "staging_records": 0, "cleaned_records": 0,
           "normalized_records": 0, "staging_bytes": 0, "cleaned_bytes": 0}
    for fname, key in [("atlas_staging.jsonl", "staging"),
                        ("cleaned.jsonl", "cleaned"),
                        ("normalized.jsonl", "normalized")]:
        p = ROOT / "metadata" / "etl" / sid / fname
        if p.exists():
            inv[f"{key}_records"] = sum(1 for line in p.read_text(encoding="utf-8").splitlines() if line.strip())
            inv[f"{key}_bytes"] = p.stat().st_size
    inventory[sid] = inv
    total_recs = inv.get("staging_records", 0)
    total_bytes = inv.get("staging_bytes", 0)
    print(f"  {sid}: {total_recs} records, {total_bytes:,} bytes", file=sys.stderr)

inv_path = ROOT / "metadata" / "p0_inventory.json"
inv_path.write_text(json.dumps(inventory, indent=2), encoding="utf-8")

# ============================================================
# FINAL SUMMARY
# ============================================================
print("\n" + "=" * 70, file=sys.stderr)
print("P0 ACQUISITION SUMMARY", file=sys.stderr)
print("=" * 70, file=sys.stderr)

print(f"\n  Total P0 sources: {len(P0_SOURCES)}", file=sys.stderr)
print(f"  Downloaded: {sum(1 for d in download_results.values() if d.get('status') == 'downloaded')}", file=sys.stderr)
print(f"  ETL passed: {sum(1 for e in etl_results.values() if e.get('status') == 'passed')}", file=sys.stderr)
print(f"  Validated clean: {sum(1 for v in validation_results.values() if v.get('status') == 'passed')}", file=sys.stderr)

total_records = sum(inv.get("staging_records", 0) for inv in inventory.values())
total_bytes = sum(inv.get("staging_bytes", 0) for inv in inventory.values())
print(f"\n  Total records acquired: {total_records}", file=sys.stderr)
print(f"  Total bytes: {total_bytes:,}", file=sys.stderr)

print("\nP0 Acquisition pipeline complete.", file=sys.stderr)
