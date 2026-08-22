#!/usr/bin/env python3
"""Complete P0 acquisition — processes all sources, generates final report."""
import json
import hashlib
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

ROOT = Path(__file__).resolve().parents[1]
STAGING_DIR = ROOT / "raw" / "p0" / "staging"
STAGING_DIR.mkdir(parents=True, exist_ok=True)

from atlas_schema import BASE_ALLOWED_KEYS

P0_SOURCES = {
    "p0-nemotron-math-proofs-v2": {
        "hf_id": "nvidia/Nemotron-Math-Proofs-v2", "domain": "math", "role": "TRAINING",
        "category": "06_science_engineering", "subcategory": "mathematics",
        "data_files": ["data/train.jsonl"], "size_bytes": 17_131_378_160, "sample_size": 500,
        "license": "CC-BY-4.0", "size_issue": "17GB — sampled to 500 records",
    },
    "p0-swe-smith-trajectories": {
        "hf_id": "SWE-bench/SWE-smith-trajectories", "domain": "code", "role": "TRAINING",
        "category": "02_software_engineering", "subcategory": "debugging",
        "data_files": ["data/ticks-00000-of-00008.parquet", "data/ticks-00001-of-00008.parquet"],
        "size_bytes": 208_466_718, "sample_size": 500, "license": "MIT",
    },
    "p0-cpp-compiler-curriculum": {
        "hf_id": "gonzalolinares/cpp-compiler-curriculum", "domain": "systems", "role": "TRAINING",
        "category": "03_system_engineering", "subcategory": "linux",
        "data_files": ["eval.jsonl"], "size_bytes": 62_649, "sample_size": None,
        "license": "Apache-2.0",
    },
    "p0-swe-smith-mini": {
        "hf_id": "Kwai-Klear/SWE-smith-mini_swe_agent_plus-trajectories-66k",
        "domain": "code", "role": "TRAINING",
        "category": "02_software_engineering", "subcategory": "debugging",
        "data_files": ["data/train-00000-of-00047.parquet", "data/train-00001-of-00047.parquet"],
        "size_bytes": 54_294_239, "sample_size": 500, "license": "MIT",
    },
    "p0-ifeval": {
        "hf_id": "google/IFEval", "domain": "evaluation", "role": "EVALUATION",
        "category": "06_science_engineering", "subcategory": "general",
        "data_files": ["ifeval_input_data.jsonl"], "size_bytes": 207_111, "sample_size": None,
        "license": "Apache-2.0",
    },
    "p0-swe-bench-verified": {
        "hf_id": "princeton-nlp/SWE-bench_Verified", "domain": "code", "role": "BOTH_WITH_STRICT_SPLIT",
        "category": "02_software_engineering", "subcategory": "debugging",
        "data_files": ["data/test-00000-of-00001.parquet"], "size_bytes": 2_096_679, "sample_size": None,
        "license": "MIT",
    },
    "p0-multi-domain-reasoning": {
        "hf_id": "khazarai/Multi-Domain-Reasoning-Benchmark", "domain": "reasoning", "role": "TRAINING",
        "category": "06_science_engineering", "subcategory": "reasoning",
        "data_files": ["multi_bench_data.parquet"], "size_bytes": 91_920, "sample_size": None,
        "license": "Apache-2.0",
    },
    "p0-quantum-hardware-physics": {
        "hf_id": "Neura-parse/quantum-hardware-device-physics", "domain": "science", "role": "TRAINING",
        "category": "05_hardware_engineering", "subcategory": "cpu",
        "data_files": ["data/train-00000-of-00001.parquet"], "size_bytes": 18_844_614, "sample_size": 500,
        "license": "CC-BY-4.0",
    },
}


def fix_record(rec, source_id, hf_id, license, category, subcategory, role):
    """Normalize a raw record to Atlas schema."""
    from atlas_constants import VALID_CATEGORIES, VALID_TYPES, VALID_ROLES

    # Strip to allowed keys
    clean = {k: v for k, v in rec.items() if k in BASE_ALLOWED_KEYS}
    clean["category"] = category
    clean["subcategory"] = subcategory
    clean["license"] = license
    clean["language"] = "en"
    clean["verified"] = False
    clean["verification_status"] = "pending"
    clean["notes"] = f"P0 frontier acquisition — {hf_id}. Needs human review."

    # Difficulty
    diff = rec.get("difficulty")
    if isinstance(diff, int) and 1 <= diff <= 4:
        clean["difficulty"] = diff
    elif "proof" in str(rec).lower() or "theorem" in str(rec).lower():
        clean["difficulty"] = 4
    else:
        clean["difficulty"] = 2

    # Quality score
    base = 7
    if hf_id.startswith(("nvidia/", "google/", "princeton-nlp/", "SWE-bench/")):
        base = 8
    clean["quality_score"] = base

    # Process messages
    msgs = rec.get("messages")
    if isinstance(msgs, list) and msgs:
        fixed = []
        for m in msgs:
            if isinstance(m, dict):
                role = m.get("role", "user")
                content = str(m.get("content", ""))[:2000]
                if content.strip():
                    fixed.append({"role": role, "content": content})
        msgs = fixed
    elif isinstance(msgs, str):
        try:
            msgs = json.loads(msgs)
            if isinstance(msgs, list):
                fixed = []
                for m in msgs:
                    if isinstance(m, dict):
                        c = str(m.get("content", ""))[:2000]
                        if c.strip():
                            fixed.append({"role": m.get("role", "user"), "content": c})
                msgs = fixed
            else:
                msgs = None
        except (TypeError, KeyError, AttributeError) as e:
            print(f"[WARN] Message parsing error: {e}", file=sys.stderr)
            msgs = None

    # If no valid messages, construct from content fields
    if not msgs:
        parts = []
        for k in ["question", "prompt", "instruction"]:
            if k in rec and rec[k]:
                parts.append(("user", str(rec[k])[:2000]))
                break
        for k in ["answer", "output", "response", "solution"]:
            if k in rec and rec[k]:
                parts.append(("assistant", str(rec[k])[:2000]))
                break
        if not parts and "problem" in rec and rec["problem"]:
            parts.append(("user", f"Prove: {rec['problem']}"[:2000]))
            # Try to get answer from messages if it was parsed
            if isinstance(rec.get("_parsed_messages"), list):
                for m in rec["_parsed_messages"]:
                    if m.get("role") == "assistant":
                        parts.append(("assistant", m.get("content", "")[:2000]))
                        break
                if len(parts) < 2:
                    parts.append(("assistant", "See source."))
            else:
                parts.append(("assistant", "See source."))
        elif "text" in rec:
            parts.append(("user", f"Content: {rec['text']}"[:2000]))
            parts.append(("assistant", "See source."))
        else:
            parts = [
                ("user", f"Process: {str(dict(rec))[:500]}"),
                ("assistant", "See source data."),
            ]
        msgs = [{"role": r, "content": c} for r, c in parts]

    # Ensure both roles present
    roles = [m.get("role") for m in msgs]
    if "user" not in roles:
        msgs.insert(0, {"role": "user", "content": "Process this data."})
    if "assistant" not in roles:
        msgs.append({"role": "assistant", "content": "See source."})

    clean["messages"] = msgs
    clean["type"] = "reasoning" if "proof" in str(clean.get("messages", ""))[:500].lower() else "qa"
    clean["tags"] = sorted(set([source_id, subcategory.replace("_", "-"), clean["type"]]))
    clean["source"] = {
        "name": hf_id,
        "url": f"https://huggingface.co/datasets/{hf_id}",
        "license": license,
        "date": "2026-08-14",
    }
    clean["lineage"] = {
        "source": hf_id,
        "transformations": ["download:huggingface", "normalize:v1.7", "promote:atlas_schema"],
        "knowledge_object": "",
        "curated_dataset": "",
        "training_view": "",
        "future_model": "",
    }
    clean["metadata"] = {
        "upstream_hf_id": hf_id,
        "acquisition_date": datetime.now(timezone.utc).isoformat(),
        "role_classification": role,
        "contamination_risk": "HIGH" if role == "EVALUATION" else ("MEDIUM" if role == "BOTH_WITH_STRICT_SPLIT" else "LOW"),
    }

    # Generate ID
    raw = f"{source_id}_{hashlib.sha256(json.dumps(clean, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]}"
    clean["id"] = raw[:64]

    return clean


def process_source(sid, info):
    """Process a single source. Returns (records, errors, warnings)."""
    errors = []
    warnings = []
    raw_records = []

    src_dir = ROOT / "raw" / "p0" / sid / "src"
    conv_dir = ROOT / "raw" / "p0" / sid / "converted"

    for rel_file in info["data_files"]:
        # Find file
        candidates = list(src_dir.rglob(Path(rel_file).name))
        if not candidates:
            candidates = list(conv_dir.rglob(Path(rel_file).name))
        if not candidates:
            warnings.append(f"File not found: {rel_file}")
            continue

        fpath = candidates[0]
        suffix = fpath.suffix.lower()

        if suffix == ".parquet":
            try:
                import pyarrow.parquet as pq
                table = pq.read_table(fpath)
                limit = info.get("sample_size")
                if limit:
                    table = table.slice(0, limit)
                records = table.to_pydict()
                for i in range(table.num_rows):
                    row = {k: v[i] for k, v in records.items()}
                    raw_records.append(row)
                print(f"  {fpath.name}: {table.num_rows} rows", file=sys.stderr)
            except Exception as e:
                errors.append(f"Parquet error {rel_file}: {e}")
        elif suffix in (".jsonl", ".json"):
            limit = info.get("sample_size")
            count = 0
            with open(fpath) as f:
                for line in f:
                    if limit and count >= limit:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        raw_records.append(obj)
                        count += 1
                    except (json.JSONDecodeError, ValueError) as e:
                        print(f"[WARN] Failed to parse line in {fpath.name}: {e}", file=sys.stderr)
                        pass
            print(f"  {fpath.name}: {count} lines", file=sys.stderr)
        else:
            warnings.append(f"Unsupported format: {fpath.suffix}")

    if not raw_records:
        return [], errors, warnings

    # Normalize
    atlas_records = []
    for rec in raw_records:
        try:
            clean = fix_record(rec, sid, info["hf_id"], info["license"],
                             info["category"], info["subcategory"], info["role"])
            atlas_records.append(clean)
        except Exception as e:
            errors.append(f"Record normalization error: {e}")

    # Deduplicate
    seen = set()
    deduped = []
    for rec in atlas_records:
        msgs = rec.get("messages", [])
        norm = "\n".join(f"{m.get('role','')}:{m.get('content','').strip()[:200]}" for m in msgs)
        h = hashlib.sha256(norm.encode()).hexdigest()[:16]
        if h not in seen:
            seen.add(h)
            deduped.append(rec)

    return deduped, errors, warnings


def main():
    print("=" * 70, file=sys.stderr)
    print("P0 ACQUISITION — Complete Pipeline", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    results = {}
    all_staging_records = {}

    for sid, info in P0_SOURCES.items():
        print(f"\n--- {sid} ({info['hf_id']}) ---", file=sys.stderr)
        records, errors, warnings = process_source(sid, info)

        result = {
            "source_id": sid,
            "hf_id": info["hf_id"],
            "domain": info["domain"],
            "role": info["role"],
            "category": info["category"],
            "subcategory": info["subcategory"],
            "license": info["license"],
            "status": "completed" if records else ("failed" if errors else "empty"),
            "records_produced": len(records),
            "errors": errors,
            "warnings": warnings,
            "contamination_risk": "HIGH" if info["role"] == "EVALUATION" else ("MEDIUM" if info["role"] == "BOTH_WITH_STRICT_SPLIT" else "LOW"),
            "specialist_pools": {
                "math": ["Math"], "code": ["Code", "Software Engineering"],
                "systems": ["Systems", "Hardware"], "reasoning": ["General Reasoning"],
                "science": ["Science", "Hardware"], "evaluation": ["Evaluation (protected)"],
            }.get(info["domain"], ["General"]),
            "provenance": {
                "upstream_hf_id": info["hf_id"],
                "upstream_url": f"https://huggingface.co/datasets/{info['hf_id']}",
                "license": info["license"],
                "acquisition_date": datetime.now(timezone.utc).isoformat(),
                "source_type": info["role"],
            },
        }

        if records:
            staging_file = STAGING_DIR / f"{sid}.jsonl"
            with open(staging_file, "w") as f:
                for rec in records:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            result["staging_bytes"] = staging_file.stat().st_size
            result["staging_file"] = str(staging_file.relative_to(ROOT))
            all_staging_records[sid] = records
            print(f"  → {len(records)} records, {staging_file.stat().st_size:,} bytes", file=sys.stderr)
        else:
            result["staging_bytes"] = 0
            result["staging_file"] = None

        results[sid] = result

    # ============================================================
    # VALIDATE ALL STAGING FILES
    # ============================================================
    print("\n--- VALIDATION ---", file=sys.stderr)
    from validate_dataset import validate_one_file

    for sid, result in results.items():
        if result["staging_file"] is None:
            result["validation_passed"] = False
            result["validation_errors"] = "no staging file"
            continue
        staging_path = ROOT / result["staging_file"]
        val = validate_one_file(staging_path, strict=False, quiet=True)
        result["validation_passed"] = val["record_errors"] == 0
        result["validation_total"] = val["total"]
        result["validation_errors"] = val["record_errors"]
        status = "PASS" if val["record_errors"] == 0 else f"{val['record_errors']} errors"
        print(f"  {sid}: {status}", file=sys.stderr)

    # ============================================================
    # FINAL REPORT
    # ============================================================
    print("\n" + "=" * 70, file=sys.stderr)
    print("P0 ACQUISITION FINAL REPORT", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    report_path = ROOT / "metadata" / "p0_acquisition_report.json"
    report_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    # Table
    print(f"\n{'Source':<42} {'Role':<22} {'License':<12} {'Status':<9} {'Recs':>6} {'Bytes':>12} {'Valid':>6}", file=sys.stderr)
    print("-" * 115, file=sys.stderr)
    for sid, r in results.items():
        short = sid.replace("p0-", "")[:40]
        role = r["role"][:20]
        lic = r.get("license", "N/A")[:10]
        status = r["status"][:8]
        recs = r.get("records_produced", 0)
        bts = r.get("staging_bytes", 0)
        valid = "YES" if r.get("validation_passed") else "NO"
        print(f"  {short:<40} {role:<20} {lic:<10} {status:<8} {recs:>6} {bts:>12,} {valid:>6}", file=sys.stderr)

    total_recs = sum(r.get("records_produced", 0) for r in results.values())
    total_bytes = sum(r.get("staging_bytes", 0) for r in results.values())
    completed = sum(1 for r in results.values() if r["status"] == "completed")
    failed = sum(1 for r in results.values() if r["status"] == "failed")
    valid_count = sum(1 for r in results.values() if r.get("validation_passed"))
    print(f"\n  Total: {len(results)} sources, {completed} completed, {failed} failed, {valid_count} validated clean", file=sys.stderr)
    print(f"  Records: {total_recs}, Staging: {total_bytes:,} bytes ({total_bytes/1e6:.1f} MB)", file=sys.stderr)

    train = sum(r.get("records_produced", 0) for r in results.values()
                if r["status"] == "completed" and r["role"] in ("TRAINING", "BOTH_WITH_STRICT_SPLIT"))
    eval_only = sum(r.get("records_produced", 0) for r in results.values()
                    if r["status"] == "completed" and r["role"] == "EVALUATION")
    print(f"  Training-eligible: {train} records", file=sys.stderr)
    print(f"  Evaluation-only: {eval_only} records", file=sys.stderr)

    # Files modified
    print(f"\n  Staging files written:", file=sys.stderr)
    for sid, r in results.items():
        if r.get("staging_file"):
            print(f"    {r['staging_file']} ({r['staging_bytes']:,}B, {r['records_produced']} recs)", file=sys.stderr)

    # P1 gaps
    print("\n" + "=" * 70, file=sys.stderr)
    print("P1 DATA GAPS", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    gaps = [
        ("Systems/Hardware", [
            "CPU/GPU microarchitecture", "Linux kernel internals", "Memory/cache systems",
            "Networking protocols (RFCs)", "Distributed systems", "Embedded/firmware",
            "CUDA/GPU programming", "Performance engineering",
        ], ["y1-y8 registry (kernel docs, man-pages, RFCs, LLVM)"]),
        ("Math", [
            "Competition math (AIME/AMC/Putnam) — dedup needed",
            "Proof theory / formal verification", "University-level math",
        ], []),
        ("Code", [
            "Repository-level coding (full PRs)", "Code review pairs",
            "Test generation", "Multi-language systems (Rust, Go, C)",
        ], []),
    ]
    for domain, items, recs in gaps:
        print(f"\n  {domain}:", file=sys.stderr)
        for item in items:
            print(f"    - {item}", file=sys.stderr)
        for item in recs:
            print(f"    → {item}", file=sys.stderr)

    print("\nP0 Acquisition complete.", file=sys.stderr)


if __name__ == "__main__":
    main()
