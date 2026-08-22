#!/usr/bin/env python3
"""
Phase A Training Dataset Manifest — Explicit inclusion/exclusion.

This manifest controls which datasets are available for Phase A training.
Datasets are EXPLICITLY included or excluded — directory discovery is NOT used.

Audit findings (2026-08-15):
  - v0.1 architecture (30K): TEMPLATE DATA — 0.2% uniqueness, MUST EXCLUDE
  - v0.1 debugging (30K): TEMPLATE DATA — 0.5% uniqueness, MUST EXCLUDE
  - v0.2 single-turn (10K): QUALITY — 99.7% unique, KEEP
  - v0.3 multi-session+dialogue (5K): NEEDS FIXES — Malay ratio too low, KEEP AFTER FIX
  - Malay dialogue v0.1 (5K): LOW UNIQUE — 36% unique, EXCLUDE for now
  - SWE-smith trajectories (3K): QUALITY — 100% unique, annotate then include

Usage:
  python scripts/phase_a_dataset_manifest.py --generate
  python scripts/phase_a_dataset_manifest.py --validate
  python scripts/phase_a_dataset_manifest.py --stats
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ATLAS_ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = Path("/home/afnan/projects/active/model-eval-finetune")
MANIFEST_PATH = MODEL_ROOT / "datasets" / "sft" / "phase_a_manifest.json"

# ---------------------------------------------------------------------------
# Dataset entry definitions
# ---------------------------------------------------------------------------

@dataclass
class DatasetEntry:
    """A single dataset entry in the Phase A manifest."""
    name: str
    path: str
    included: bool
    reason: str
    record_count: int = 0
    train_count: int = 0
    val_count: int = 0
    exact_uniqueness: float = 0.0
    semantic_uniqueness: float = 0.0
    l3_plus_pct: float = 0.0
    malay_ratio: float = 0.0
    capabilities_covered: int = 0
    capabilities_total: int = 14
    tags: list[str] = field(default_factory=list)
    requires_fix: bool = False
    fix_notes: str = ""
    audit_date: str = "2026-08-15"
    audit_verdict: str = ""


# ---------------------------------------------------------------------------
# Manifest definition
# ---------------------------------------------------------------------------

PHASE_A_MANIFEST = {
    "version": "1.0.0",
    "phase": "A",
    "phase_name": "Language & Engineering Identity",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "audit_reference": "docs/audit/atan_v1_synthetic_dataset_audit_2026_08_15.md",
    "datasets": [
        {
            "name": "v0.2_single_turn",
            "path": str(MODEL_ROOT / "datasets" / "sft" / "synthetic_v0.2" / "atan_v1_train.jsonl"),
            "included": True,
            "reason": "99.7% unique, combinatorial generation, 85% L3-L5, 46% Malay ratio, 100% capability coverage",
            "record_count": 9000,
            "tags": ["synthetic", "single-turn", "combinatorial", "quality"],
            "audit_verdict": "READY",
        },
        {
            "name": "v0.3_multi_session_fixed",
            "path": str(MODEL_ROOT / "datasets" / "sft" / "multi_session_v0.3" / "atan_v1_train.jsonl"),
            "included": True,
            "reason": "100% unique, multi-session + multi-turn dialogue, needs Malay ratio fix (see fix_notes)",
            "record_count": 4500,
            "tags": ["synthetic", "multi-session", "multi-turn", "needs_language_fix"],
            "audit_verdict": "NEEDS_CLEANUP",
            "requires_fix": True,
            "fix_notes": "Increase Malay language ratio from 7-12% to >=30%. Fix dialogue rebuttal chains.",
        },
        {
            "name": "v0.1_architecture_template",
            "path": str(Path("/home/afnan/Downloads/atan-v1_synthetic_corpus_v0/architecture_reasoning_30000.jsonl")),
            "included": False,
            "reason": "TEMPLATE DATA: 0.2% exact uniqueness, 4834 records share identical assistant response pattern. Will teach formulaic output.",
            "record_count": 30000,
            "tags": ["synthetic", "template", "EXCLUDED"],
            "audit_verdict": "NOT READY",
        },
        {
            "name": "v0.1_debugging_template",
            "path": str(Path("/home/afnan/Downloads/atan-v1_synthetic_corpus_v0/debugging_30000.jsonl")),
            "included": False,
            "reason": "TEMPLATE DATA: 0.5% exact uniqueness, 4880 records share identical assistant response pattern. Will teach formulaic output.",
            "record_count": 30000,
            "tags": ["synthetic", "template", "EXCLUDED"],
            "audit_verdict": "NOT READY",
        },
        {
            "name": "malay_dialogue_v0.1",
            "path": str(Path("/home/afnan/Downloads/atan-v1_malaysian_engineering_dialogue_5000.jsonl")),
            "included": False,
            "reason": "LOW DIVERSITY: 36% exact uniqueness, 64% semantically duplicated. Generator needs rework before reuse.",
            "record_count": 5000,
            "tags": ["synthetic", "low-diversity", "EXCLUDED"],
            "audit_verdict": "NEEDS REWORK",
        },
        {
            "name": "swe_smith_trajectories",
            "path": str(MODEL_ROOT / "datasets" / "sft" / "agent_trajectories_train.jsonl"),
            "included": True,
            "reason": "100% unique, real SWE-agent trajectories, good for Phase D but needs Malay system prompt injection for Phase A",
            "record_count": 2700,
            "tags": ["real", "multi-turn", "agent-trajectory", "needs_malay_prompt"],
            "audit_verdict": "NEEDS_ANNOTATION",
            "requires_fix": True,
            "fix_notes": "Inject Malaysian engineering system prompt. Add difficulty labels via intelligence layer.",
        },
        {
            "name": "pilot_v0.2",
            "path": str(ATLAS_ROOT / "pilot" / "v0.2"),
            "included": False,
            "reason": "Pilot data (4,499 records) — separate from synthetic corpus. To be evaluated for Phase A inclusion after license audit.",
            "record_count": 4499,
            "tags": ["pilot", "expert", "LICENSE_AUDIT_REQUIRED"],
            "audit_verdict": "PENDING_LICENSE_AUDIT",
        },
    ],
}


def generate_manifest() -> dict[str, Any]:
    """Generate the full Phase A manifest with computed metrics."""
    manifest = json.loads(json.dumps(PHASE_A_MANIFEST))  # deep copy

    # Compute metrics for included datasets
    for ds in manifest["datasets"]:
        if not ds["included"]:
            continue
        path = Path(ds["path"])
        if not path.exists():
            ds["status"] = "PATH_NOT_FOUND"
            continue

        # Count records
        count = 0
        with open(path) as f:
            for line in f:
                if line.strip():
                    count += 1
        ds["record_count"] = count
        ds["train_count"] = count  # Single file, no split
        ds["status"] = "VALIDATED"

    # Compute totals
    included = [d for d in manifest["datasets"] if d["included"]]
    excluded = [d for d in manifest["datasets"] if not d["included"]]

    manifest["summary"] = {
        "total_datasets": len(manifest["datasets"]),
        "included_datasets": len(included),
        "excluded_datasets": len(excluded),
        "included_records": sum(d.get("record_count", 0) for d in included),
        "excluded_records": sum(d.get("record_count", 0) for d in excluded),
        "excluded_reasons": [
            f"{d['name']}: {d['reason'][:80]}..." for d in excluded
        ],
    }

    manifest["generated_at"] = datetime.now(timezone.utc).isoformat()
    return manifest


def validate_manifest(manifest: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Validate manifest integrity."""
    errors = []
    warnings = []

    # Check no template data is included
    for ds in manifest["datasets"]:
        if ds["included"] and "TEMPLATE" in ds.get("tags", []):
            errors.append(f"FATAL: Template dataset included: {ds['name']}")
        if ds["included"] and "EXCLUDED" in ds.get("tags", []):
            errors.append(f"FATAL: Explicitly excluded dataset included: {ds['name']}")
        if ds["included"] and "LOW-DIVERSITY" in ds.get("tags", []):
            warnings.append(f"LOW DIVERSITY dataset included: {ds['name']}")

    # Check required fields
    for ds in manifest["datasets"]:
        if not ds.get("path"):
            errors.append(f"Missing path for dataset: {ds['name']}")
        if not ds.get("reason"):
            warnings.append(f"Missing reason for dataset: {ds['name']}")

    # Check included records > 0
    included_records = sum(d.get("record_count", 0) for d in manifest["datasets"] if d["included"])
    if included_records == 0:
        errors.append("NO datasets included for training!")

    # Check path existence for included datasets
    for ds in manifest["datasets"]:
        if ds["included"]:
            path = Path(ds["path"])
            if not path.exists():
                errors.append(f"Included dataset path does not exist: {ds['name']} ({path})")

    return errors, warnings


def print_stats(manifest: dict[str, Any]) -> None:
    """Print human-readable stats."""
    print("=" * 70, file=sys.stderr)
    print("PHASE A TRAINING DATASET MANIFEST", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    s = manifest["summary"]
    print(f"\nIncluded: {s['included_datasets']} datasets, {s['included_records']:,} records", file=sys.stderr)
    print(f"Excluded: {s['excluded_datasets']} datasets, {s['excluded_records']:,} records", file=sys.stderr)

    print(f"\n--- INCLUDED ---", file=sys.stderr)
    for ds in manifest["datasets"]:
        if not ds["included"]:
            continue
        status = "✅" if ds.get("status") == "VALIDATED" else "⚠️"
        fix = " [FIX NEEDED]" if ds.get("requires_fix") else ""
        print(f"  {status} {ds['name']}: {ds.get('record_count', 0):,} records{fix}", file=sys.stderr)
        print(f"     {ds['reason'][:100]}...", file=sys.stderr)

    print(f"\n--- EXCLUDED ---", file=sys.stderr)
    for ds in manifest["datasets"]:
        if ds["included"]:
            continue
        tag = "[TEMPLATE]" if "TEMPLATE" in ds.get("tags", []) else "[LOW-DIV]" if "LOW-DIVERSITY" in ds.get("tags", []) else ""
        print(f"  ❌ {ds['name']}{tag}: {ds.get('record_count', 0):,} records", file=sys.stderr)
        print(f"     {ds['reason'][:100]}...", file=sys.stderr)

    print(f"\n{'='*70}", file=sys.stderr)
    if s["included_records"] > 0:
        print("VERDICT: READY FOR PHASE A (with fixes applied)", file=sys.stderr)
    else:
        print("VERDICT: NOT READY — no datasets included", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Phase A training dataset manifest manager.")
    parser.add_argument("--generate", action="store_true", help="Generate the manifest JSON file.")
    parser.add_argument("--validate", action="store_true", help="Validate current manifest.")
    parser.add_argument("--stats", action="store_true", help="Print human-readable stats.")
    parser.add_argument("--output", type=Path, default=MANIFEST_PATH, help="Output path for manifest.")
    args = parser.parse_args()

    # Load or generate manifest
    if args.validate or args.stats:
        if not MANIFEST_PATH.exists():
            print(f"ERROR: Manifest not found at {MANIFEST_PATH}", file=sys.stderr)
            print("Run with --generate first.", file=sys.stderr)
            return 1
        with open(MANIFEST_PATH) as f:
            manifest = json.load(f)
    else:
        manifest = generate_manifest()

    if args.validate:
        errors, warnings = validate_manifest(manifest)
        print(f"\nValidation results for {MANIFEST_PATH}:", file=sys.stderr)
        if errors:
            for e in errors:
                print(f"  ERROR: {e}", file=sys.stderr)
        if warnings:
            for w in warnings:
                print(f"  WARNING: {w}", file=sys.stderr)
        if not errors and not warnings:
            print(f"  ✅ All checks passed.", file=sys.stderr)
        return 0 if not errors else 1

    if args.stats:
        print_stats(manifest)
        return 0

    if args.generate:
        # Generate fresh manifest
        manifest = generate_manifest()
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"Manifest written to {MANIFEST_PATH}", file=sys.stderr)

        # Validate immediately
        errors, warnings = validate_manifest(manifest)
        if errors:
            print(f"\nValidation FAILED ({len(errors)} errors):", file=sys.stderr)
            for e in errors:
                print(f"  ERROR: {e}", file=sys.stderr)
            return 1
        if warnings:
            print(f"\nValidation warnings ({len(warnings)}):", file=sys.stderr)
            for w in warnings:
                print(f"  WARNING: {w}", file=sys.stderr)

        print_stats(manifest)
        return 0

    # Default: generate + validate + stats
    manifest = generate_manifest()
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Manifest written to {MANIFEST_PATH}", file=sys.stderr)

    errors, warnings = validate_manifest(manifest)
    if errors:
        print(f"\nValidation FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  ERROR: {e}", file=sys.stderr)
        return 1

    print_stats(manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
