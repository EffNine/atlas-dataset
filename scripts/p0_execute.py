#!/usr/bin/env python3
"""
Atlas P0 Acquisition — Execute ETL, Validate, and Produce Final Report.
Copies HF cache files into Atlas raw cache, runs ETL pipeline, validates.
"""
import json
import hashlib
import shutil
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

ROOT = Path(__file__).resolve().parents[1]
HF_CACHE = Path("/home/afnan/projects/models/huggingface/hub")

P0_SOURCES = {
    "p0-nemotron-math-proofs-v2": {
        "hf_id": "nvidia/Nemotron-Math-Proofs-v2",
        "domain": "math",
        "role": "TRAINING",
        "category": "06_science_engineering",
        "subcategory": "mathematics",
        "data_files": ["data/train.jsonl"],
        "schema": "jsonl(messages, problem, source, license, uuid)",
        "size_bytes": 17_131_378_160,
        "sample_size": 500,
        "size_issue": "17GB full dataset; sampling required for pilot acquisition",
    },
    "p0-swe-smith-trajectories": {
        "hf_id": "SWE-bench/SWE-smith-trajectories",
        "domain": "code",
        "role": "TRAINING",
        "category": "02_software_engineering",
        "subcategory": "debugging",
        "data_files": ["data/ticks-00000-of-00008.parquet", "data/ticks-00001-of-00008.parquet"],
        "schema": "parquet(messages, instance_id, resolved, model, traj_id, patch)",
        "size_bytes": 208_466_718,
        "sample_size": 500,
        "size_issue": None,
    },
    "p0-cpp-compiler-curriculum": {
        "hf_id": "gonzalolinares/cpp-compiler-curriculum",
        "domain": "systems",
        "role": "TRAINING",
        "category": "03_system_engineering",
        "subcategory": "linux",
        "data_files": ["eval.jsonl"],
        "schema": "jsonl(messages, level)",
        "size_bytes": 62_649,
        "sample_size": None,
        "size_issue": None,
    },
    "p0-swe-smith-mini": {
        "hf_id": "Kwai-Klear/SWE-smith-mini_swe_agent_plus-trajectories-66k",
        "domain": "code",
        "role": "TRAINING",
        "category": "02_software_engineering",
        "subcategory": "debugging",
        "data_files": ["data/train-00000-of-00047.parquet", "data/train-00001-of-00047.parquet"],
        "schema": "parquet(instance_id, messages)",
        "size_bytes": 54_294_239,
        "sample_size": 500,
        "size_issue": None,
    },
    "p0-ifeval": {
        "hf_id": "google/IFEval",
        "domain": "evaluation",
        "role": "EVALUATION",
        "category": "06_science_engineering",
        "subcategory": "general",
        "data_files": ["ifeval_input_data.jsonl"],
        "schema": "jsonl(key, prompt, instruction_id_list, kwargs)",
        "size_bytes": 207_111,
        "sample_size": None,
        "size_issue": None,
    },
    "p0-swe-bench-verified": {
        "hf_id": "princeton-nlp/SWE-bench_Verified",
        "domain": "code",
        "role": "BOTH_WITH_STRICT_SPLIT",
        "category": "02_software_engineering",
        "subcategory": "debugging",
        "data_files": ["data/test-00000-of-00001.parquet"],
        "schema": "parquet(repo, instance_id, base_commit, patch, test_patch, problem_statement, hints_text, FAIL_TO_PASS, ...)",
        "size_bytes": 2_096_679,
        "sample_size": None,
        "size_issue": None,
    },
    "p0-multi-domain-reasoning": {
        "hf_id": "khazarai/Multi-Domain-Reasoning-Benchmark",
        "domain": "reasoning",
        "role": "TRAINING",
        "category": "06_science_engineering",
        "subcategory": "general",
        "data_files": ["multi_bench_data.parquet"],
        "schema": "parquet(question_category, difficulty_level, question, guide_text, answer, success_criteria)",
        "size_bytes": 91_920,
        "sample_size": None,
        "size_issue": None,
    },
    "p0-quantum-hardware-physics": {
        "hf_id": "Neura-parse/quantum-hardware-device-physics",
        "domain": "science",
        "role": "TRAINING",
        "category": "05_hardware_engineering",
        "subcategory": "cpu",
        "data_files": ["data/train-00000-of-00001.parquet"],
        "schema": "parquet(95K rows, 39 cols including id, domain, record_type, category, topic, difficulty)",
        "size_bytes": 18_844_614,
        "sample_size": 500,
        "size_issue": None,
    },
}


def hf_snapshot_path(hf_id: str, rel_path: str) -> Path:
    """Resolve HF cache snapshot path."""
    # The HF cache uses double-dashes for each path segment
    # e.g., nvidia/Nemotron-Math-Proofs-v2 -> datasets--nvidia--Nemotron-Math-Proofs-v2
    parts = hf_id.replace("/", "--")
    snapshot_dir = HF_CACHE / f"datasets--{parts}" / "snapshots"
    if not snapshot_dir.exists():
        return Path()
    snaps = sorted(snapshot_dir.iterdir())
    if not snaps:
        return Path()
    return snaps[-1] / rel_path


def copy_to_raw(source_id: str, src_path: Path, dest_dir: Path):
    """Copy a file from HF cache to Atlas raw cache."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    if not src_path.exists():
        return None, None, None, None
    h = hashlib.sha256()
    with open(src_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192 * 1024), b""):
            h.update(chunk)
    checksum = h.hexdigest()
    dest_path = dest_dir / checksum / src_path.name
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if dest_path.exists():
        return str(dest_path), checksum, src_path.stat().st_size, "cached"
    shutil.copy2(src_path, dest_path)
    return str(dest_path), checksum, src_path.stat().st_size, "downloaded"


def convert_parquet_to_jsonl(parquet_path: Path, output_path: Path, limit=None) -> int:
    """Convert parquet to JSONL."""
    import pyarrow.parquet as pq
    table = pq.read_table(parquet_path)
    if limit:
        table = table.slice(0, limit)
    records = table.to_pydict()
    row_count = table.num_rows
    with open(output_path, "w") as f:
        for i in range(row_count):
            row = {k: v[i] for k, v in records.items()}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row_count


def main():
    raw_dir = ROOT / "raw" / "p0"
    raw_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70, file=sys.stderr)
    print("P0 ACQUISITION — Copy, ETL, Validate, Report", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    results = {}

    for sid, info in P0_SOURCES.items():
        print(f"\n--- {sid} ({info['hf_id']}) ---", file=sys.stderr)
        result = {
            "source_id": sid,
            "hf_id": info["hf_id"],
            "domain": info["domain"],
            "role": info["role"],
            "category": info["category"],
            "subcategory": info["subcategory"],
            "schema": info["schema"],
            "status": "pending",
            "files_copied": 0,
            "records_extracted": 0,
            "records_cleaned": 0,
            "records_valid": 0,
            "size_bytes": info["size_bytes"],
            "checksums": {},
            "etl_status": None,
            "validation_status": None,
            "errors": [],
            "warnings": [],
            "contamination_risk": "LOW",
            "specialist_pools": [],
            "inventory": {},
        }

        # Specialist pools
        pool_map = {
            "math": ["Math"],
            "code": ["Code", "Software Engineering"],
            "systems": ["Systems", "Hardware"],
            "reasoning": ["General Reasoning"],
            "science": ["Science", "Hardware"],
            "evaluation": ["Evaluation (protected)"],
        }
        result["specialist_pools"] = pool_map.get(info["domain"], ["General"])

        if info["role"] == "EVALUATION":
            result["contamination_risk"] = "HIGH — EVAL ONLY"
        elif info["role"] == "BOTH_WITH_STRICT_SPLIT":
            result["contamination_risk"] = "MEDIUM — strict split required"
        elif info["domain"] in ("math", "code"):
            result["contamination_risk"] = "MEDIUM — benchmark overlap possible"
        else:
            result["contamination_risk"] = "LOW"

        # Copy files
        src_dir = raw_dir / sid / "src"
        for rel_file in info["data_files"]:
            hf_path = hf_snapshot_path(info["hf_id"], rel_file)
            if not hf_path.exists():
                result["errors"].append(f"File not in HF cache: {rel_file}")
                continue
            dest_path, checksum, size, status = copy_to_raw(sid, hf_path, src_dir)
            if dest_path:
                result["files_copied"] += 1
                result["checksums"][rel_file] = {"path": dest_path, "checksum": checksum, "size": size, "status": status}
                print(f"  Copied: {rel_file} ({size:,}B, {status})", file=sys.stderr)
            else:
                result["errors"].append(f"Failed to copy: {rel_file}")

        if result["files_copied"] == 0:
            result["status"] = "failed"
            results[sid] = result
            continue

        # Convert parquet → JSONL
        convert_dir = raw_dir / sid / "converted"
        convert_dir.mkdir(parents=True, exist_ok=True)
        jsonl_files = []
        for rel_file, chk in result["checksums"].items():
            src_path = Path(chk["path"])
            if src_path.suffix == ".parquet":
                out_jsonl = convert_dir / f"{Path(rel_file).stem}.jsonl"
                try:
                    n = convert_parquet_to_jsonl(src_path, out_jsonl, limit=info.get("sample_size"))
                    jsonl_files.append(str(out_jsonl))
                    result["records_extracted"] += n
                    print(f"  Converted: {rel_file} → {n} rows", file=sys.stderr)
                except Exception as e:
                    result["errors"].append(f"Parquet conversion: {e}")
            elif src_path.suffix in (".jsonl", ".json"):
                jsonl_files.append(str(src_path))

        # ETL
        from etl.pipeline import run_etl_for_source
        etl_result = run_etl_for_source(ROOT, sid, limit=info.get("sample_size"), promote_atlas=True)
        result["etl_status"] = etl_result.status
        result["records_cleaned"] = etl_result.cleaned
        result["records_valid"] = etl_result.atlas_records
        result["warnings"].extend(etl_result.warnings)
        result["errors"].extend(etl_result.errors)
        print(f"  ETL: {etl_result.status} — {etl_result.summary}", file=sys.stderr)

        # Validate
        from validate_dataset import validate_one_file
        staging_path = ROOT / "metadata" / "etl" / sid / "atlas_staging.jsonl"
        if staging_path.exists():
            val = validate_one_file(staging_path, strict=False, quiet=True)
            result["validation_status"] = "passed" if val["record_errors"] == 0 else "partial"
            result["validation_errors"] = val["record_errors"]
            print(f"  Validate: {result['validation_status']} — {val['total']} records, {val['record_errors']} errors", file=sys.stderr)
        else:
            result["validation_status"] = "skipped"
            result["errors"].append("No staging file")

        # Inventory
        if staging_path.exists():
            result["inventory"] = {
                "records": sum(1 for l in staging_path.read_text(encoding="utf-8").splitlines() if l.strip()),
                "bytes": staging_path.stat().st_size,
            }

        result["status"] = "completed" if etl_result.status == "passed" else "failed"
        results[sid] = result

    # ============================================================
    # FINAL REPORT
    # ============================================================
    print("\n" + "=" * 70, file=sys.stderr)
    print("P0 ACQUISITION FINAL REPORT", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    # Save report
    report_path = ROOT / "metadata" / "p0_acquisition_report.json"
    report_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    # Summary table
    print(f"\n{'Source':<42} {'Role':<22} {'Status':<10} {'Records':>8} {'Bytes':>12}", file=sys.stderr)
    print("-" * 100, file=sys.stderr)
    for sid, r in results.items():
        short = sid.replace("p0-", "")[:40]
        role = r["role"][:20]
        status = r["status"][:9]
        inv = r.get("inventory", {})
        recs = inv.get("records", r.get("records_cleaned", 0))
        bts = inv.get("bytes", 0)
        print(f"  {short:<40} {role:<20} {status:<9} {recs:>8} {bts:>12,}", file=sys.stderr)

    total_recs = sum(r.get("inventory", {}).get("records", r.get("records_cleaned", 0)) for r in results.values())
    total_bytes = sum(r.get("inventory", {}).get("bytes", 0) for r in results.values())
    completed = sum(1 for r in results.values() if r["status"] == "completed")
    failed = sum(1 for r in results.values() if r["status"] == "failed")
    print(f"\n  Total: {len(results)} sources, {completed} completed, {failed} failed", file=sys.stderr)
    print(f"  Records acquired: {total_recs}, Size: {total_bytes:,} bytes", file=sys.stderr)

    # P1 gaps
    print("\n" + "=" * 70, file=sys.stderr)
    print("P1 DATA GAPS", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    gaps = {
        "Systems/Hardware": [
            "CPU/GPU microarchitecture",
            "Linux kernel internals",
            "Memory/cache systems",
            "Networking protocols (RFCs)",
            "Distributed systems",
            "Embedded/firmware",
            "CUDA/GPU programming",
            "Performance engineering",
        ],
        "Math": [
            "Competition math (AIME/AMC/Putnam) — dedup needed",
            "Proof theory / formal verification",
            "University-level math",
        ],
        "Code": [
            "Repository-level coding (full PRs)",
            "Code review pairs",
            "Test generation",
            "Multi-language systems (Rust, Go, C)",
        ],
    }
    for domain, items in gaps.items():
        print(f"\n  {domain}:", file=sys.stderr)
        for item in items:
            print(f"    - {item}", file=sys.stderr)
        if domain == "Systems/Hardware":
            print(f"    → Recommended: Use existing registry y1-y8 (kernel docs, man-pages, RFCs, LLVM docs)", file=sys.stderr)

    print("\nP0 Acquisition complete.", file=sys.stderr)


if __name__ == "__main__":
    main()
