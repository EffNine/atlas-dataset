#!/usr/bin/env python3
"""
knowledge_pack.py — Atlas Knowledge Pack generation.

Knowledge Packs are compact, portable, independently-verifiable subsets
of the Atlas dataset. Each Pack contains:
  * A curated subset of records (filtered by category, quality, etc.)
  * A manifest with metadata, statistics, and checksums
  * An optional README describing the pack's purpose and contents

Use cases:
  * Sharing a focused subset with reviewers without exposing the full dataset
  * Providing a small, verifiable sample for external evaluation
  * Distribution of domain-specific subsets to downstream projects
"""

from __future__ import annotations

import gzip
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .integrity import file_sha256, compute_file_checksums


# ---------------------------------------------------------------------------
# Knowledge Pack generation
# ---------------------------------------------------------------------------

def generate_knowledge_pack(
    name: str,
    records: list[dict[str, Any]],
    output_dir: str | Path,
    category_filter: list[str] | None = None,
    min_quality: int = 0,
    compress: bool = True,
    description: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Generate a Knowledge Pack from a list of records.

    Args:
        name: Pack name (used for filename, e.g. "foundation-v0.1")
        records: List of record dicts
        output_dir: Output directory
        category_filter: Optional list of categories to include
        min_quality: Minimum quality_score threshold
        compress: Whether to gzip the record file
        description: Human-readable description
        metadata: Optional additional metadata

    Returns:
        Pack manifest dict
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Filter records
    filtered = list(records)
    if category_filter:
        filtered = [r for r in filtered if r.get("category") in category_filter]
    if min_quality > 0:
        filtered = [
            r for r in filtered
            if isinstance(r.get("quality_score"), (int, float))
            and r["quality_score"] >= min_quality
        ]

    if not filtered:
        print(f"[pack] WARNING: '{name}' has zero records after filtering")

    # Sort for deterministic output
    filtered.sort(key=lambda r: r.get("id", ""))

    # Write records
    records_filename = f"{name}.jsonl"
    records_path = output_dir / records_filename
    with records_path.open("w", encoding="utf-8") as f:
        for rec in filtered:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Optionally compress
    if compress and records_path.stat().st_size > 0:
        gz_path = output_dir / f"{name}.jsonl.gz"
        with records_path.open("rb") as f_in:
            with gzip.open(gz_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        records_path.unlink()  # remove uncompressed
        records_filename = f"{name}.jsonl.gz"

    # Compute checksums
    abs_path = output_dir / records_filename
    record_checksum = file_sha256(abs_path) if abs_path.exists() else ""

    # Aggregated stats
    total = len(filtered)
    cat_counts: dict[str, int] = {}
    lic_counts: dict[str, int] = {}
    qual_scores: list[int] = []
    for rec in filtered:
        c = rec.get("category", "unknown")
        cat_counts[c] = cat_counts.get(c, 0) + 1
        l = rec.get("license", "unknown")
        lic_counts[l] = lic_counts.get(l, 0) + 1
        q = rec.get("quality_score", 0)
        if isinstance(q, (int, float)):
            qual_scores.append(int(q))

    avg_q = round(sum(qual_scores) / len(qual_scores), 2) if qual_scores else 0

    manifest: dict[str, Any] = {
        "pack_name": name,
        "pack_version": "1.0",
        "generated": datetime.now(timezone.utc).isoformat(),
        "description": description,
        "total_records": total,
        "filter_criteria": {
            "categories": category_filter,
            "min_quality": min_quality,
        },
        "statistics": {
            "by_category": dict(sorted(cat_counts.items())),
            "by_license": dict(sorted(lic_counts.items())),
            "avg_quality": avg_q,
            "quality_min": min(qual_scores) if qual_scores else 0,
            "quality_max": max(qual_scores) if qual_scores else 0,
        },
        "files": {
            records_filename: record_checksum,
        },
    }
    if metadata:
        manifest["metadata"] = metadata

    manifest_path = output_dir / f"{name}_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Write checksum file
    checksums: dict[str, str] = {}
    for fname, csum in manifest["files"].items():
        checksums[fname] = csum
    checksums["manifest"] = file_sha256(manifest_path)
    checksums_path = output_dir / f"{name}_checksums.json"
    checksums_path.write_text(
        json.dumps({
            "pack_name": name,
            "algorithm": "sha256",
            "checksums": checksums,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    total_bytes = abs_path.stat().st_size if abs_path.exists() else 0
    print(f"[pack] Generated Knowledge Pack '{name}' — "
          f"{total} records, {_fmt_bytes(total_bytes)}")
    return manifest


def _fmt_bytes(n: int) -> str:
    if n <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB"]
    f = float(n)
    for u in units:
        if f < 1024 or u == units[-1]:
            return f"{f:.1f} {u}" if u != "B" else f"{int(f)} B"
        f /= 1024.0
    return f"{n} B"


def verify_knowledge_pack(pack_dir: str | Path) -> dict[str, Any]:
    """
    Verify the integrity of a Knowledge Pack.
    Checks: manifest exists, checksum file exists, all files present and matching.
    """
    pack_dir = Path(pack_dir)
    if not pack_dir.exists():
        return {"verified": False, "error": "Directory not found"}

    manifests = sorted(pack_dir.glob("*_manifest.json"))
    if not manifests:
        return {"verified": False, "error": "No manifest found"}

    results: list[dict[str, Any]] = []
    all_ok = True

    for man_path in manifests:
        try:
            manifest = json.loads(man_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError) as e:
            results.append({"manifest": man_path.name, "verified": False, "error": str(e)})
            all_ok = False
            continue

        pack_name = manifest.get("pack_name", "unknown")
        checksums_path = pack_dir / f"{pack_name}_checksums.json"
        if not checksums_path.exists():
            results.append({"manifest": man_path.name, "verified": False,
                            "error": "Checksum file missing"})
            all_ok = False
            continue

        try:
            checksum_data = json.loads(checksums_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            results.append({"manifest": man_path.name, "verified": False,
                            "error": "Checksum file corrupt"})
            all_ok = False
            continue

        stored_checksums = checksum_data.get("checksums", {})

        # Verify each file
        pack_errors: list[str] = []
        for fname, expected_csum in stored_checksums.items():
            if fname == "manifest":
                continue  # handled separately
            fpath = pack_dir / fname
            if not fpath.exists():
                pack_errors.append(f"Missing file: {fname}")
                all_ok = False
                continue
            actual = file_sha256(fpath)
            if actual != expected_csum:
                pack_errors.append(f"Checksum mismatch: {fname}")
                all_ok = False

        # Verify manifest checksum
        if "manifest" in stored_checksums:
            actual_man_csum = file_sha256(man_path)
            if actual_man_csum != stored_checksums["manifest"]:
                pack_errors.append("Manifest checksum mismatch")
                all_ok = False

        results.append({
            "manifest": man_path.name,
            "pack_name": pack_name,
            "verified": len(pack_errors) == 0,
            "record_count": manifest.get("total_records", 0),
            "errors": pack_errors,
        })

    return {"verified": all_ok, "packs": results}
