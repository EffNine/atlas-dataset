#!/usr/bin/env python3
"""Atlas Release Integrity Checker.

Verifies that release manifests are consistent with actual filesystem state.
This is a READ-ONLY audit tool — it does not modify any data.

Usage:
    python scripts/release/integrity_check.py [--root /path/to/repo]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def check_dataset_exists(root: Path, manifest: dict) -> dict[str, Any]:
    """Check if dataset files exist in release bundle."""
    result = {
        "dataset_exists": False,
        "has_data_files": False,
        "has_only_gitkeep": False,
        "category_dirs": [],
        "error": None,
    }

    try:
        version = manifest.get("release_version", "")
        # Try common paths
        candidates = [
            root / "releases" / version / "dataset",
            root / "releases" / version.replace("-", "/") / "dataset",
            root / "releases" / version,
        ]
        dataset_dir = None
        for candidate in candidates:
            if candidate.exists() and candidate.is_dir():
                dataset_dir = candidate
                break

        if not dataset_dir:
            result["error"] = f"Dataset directory not found for {version}"
            return result

        categories = list(dataset_dir.iterdir())
        result["category_dirs"] = [c.name for c in categories]

        # Check if any category has actual data files
        has_data = False
        has_gitkeep = False
        for cat_dir in categories:
            if cat_dir.is_dir():
                files = list(cat_dir.iterdir())
                has_gitkeep_files = [f for f in files if f.name == ".gitkeep"]
                data_files = [f for f in files if f.name != ".gitkeep"]
                if data_files:
                    has_data = True
                if has_gitkeep_files:
                    has_gitkeep = True

        result["has_data_files"] = has_data
        result["has_only_gitkeep"] = has_gitkeep and not has_data
        result["dataset_exists"] = True
        result["is_valid"] = has_data
    except Exception as e:
        result["error"] = str(e)

    return result


def check_manifest_integrity(manifest_path: Path) -> dict[str, Any]:
    """Verify manifest file integrity (hash consistency)."""
    result = {
        "exists": manifest_path.exists(),
        "valid_json": False,
        "has_signature": False,
        "hash_consistent": False,
        "error": None,
    }

    if not manifest_path.exists():
        return result

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        result["valid_json"] = True

        sig = manifest.get("release_signature", {})
        result["has_signature"] = bool(sig)

        if sig:
            # Verify content hash
            import hashlib
            exclude = {"release_signature", "release_id"}
            data = {k: v for k, v in manifest.items() if k not in exclude}
            raw = json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
            computed_hash = hashlib.sha256(raw).hexdigest()
            stored_hash = sig.get("content_hash", "")
            result["hash_consistent"] = computed_hash == stored_hash
            if computed_hash != stored_hash:
                result["error"] = "Content hash mismatch — manifest was modified after signing"
    except json.JSONDecodeError as e:
        result["error"] = f"Invalid JSON: {e}"
    except Exception as e:
        result["error"] = str(e)

    return result


def check_human_review_evidence(root: Path) -> dict[str, Any]:
    """Check if human review evidence exists."""
    approved_path = root / "review_queue" / "approved.jsonl"
    result = {
        "evidence_exists": approved_path.exists(),
        "approved_count": 0,
        "error": None,
    }

    if not approved_path.exists():
        result["error"] = "approved.jsonl does not exist — human review gate cannot pass"
        return result

    count = 0
    with open(approved_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    json.loads(line)
                    count += 1
                except json.JSONDecodeError:
                    pass

    result["approved_count"] = count
    result["has_evidence"] = count > 0
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Check release integrity")
    ap.add_argument("--root", default=None, help="Repository root")
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else Path(__file__).resolve().parent.parent.parent
    manifests_dir = root / "metadata" / "releases"

    print("=" * 60)
    print("ATLAS RELEASE INTEGRITY CHECK")
    print("=" * 60)

    all_ok = True
    issues = []

    # Check each manifest
    for manifest_file in sorted(manifests_dir.glob("*_release.json")):
        version = manifest_file.stem.replace("_release", "")
        print(f"\n--- {version} ---")

        # Manifest integrity
        manifest_integrity = check_manifest_integrity(manifest_file)
        print(f"  Manifest valid JSON: {'YES' if manifest_integrity['valid_json'] else 'NO'}")
        print(f"  Has signature: {'YES' if manifest_integrity['has_signature'] else 'NO'}")
        print(f"  Hash consistent: {'YES' if manifest_integrity['hash_consistent'] else 'NO'}")

        if not manifest_integrity["hash_consistent"]:
            all_ok = False
            issues.append(f"{version}: Manifest hash mismatch")

        # Load manifest
        if manifest_integrity["valid_json"]:
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            # Dataset existence
            dataset_check = check_dataset_exists(root, manifest)
            print(f"  Dataset exists: {'YES' if dataset_check['dataset_exists'] else 'NO'}")
            print(f"  Has data files: {'YES' if dataset_check['has_data_files'] else 'NO'}")
            print(f"  Has only .gitkeep: {'YES' if dataset_check['has_only_gitkeep'] else 'NO'}")

            if dataset_check.get("has_only_gitkeep"):
                all_ok = False
                issues.append(f"{version}: Dataset directory contains only .gitkeep files")

            # Human review evidence
            review_evidence = check_human_review_evidence(root)
            gates = manifest.get("gates", {})
            human_gate = gates.get("human_review_gate", {})
            print(f"  Human review gate claims passed: {'YES' if human_gate.get('passed') else 'NO'}")
            print(f"  Approved.jsonl exists: {'YES' if review_evidence['evidence_exists'] else 'NO'}")

            if human_gate.get("passed") and not review_evidence["evidence_exists"]:
                all_ok = False
                issues.append(f"{version}: Human review gate claims passed but no approved.jsonl exists")

    print("\n" + "=" * 60)
    if all_ok:
        print("RESULT: PASS — All integrity checks passed")
        return 0
    else:
        print("RESULT: FAIL — Integrity issues found:")
        for issue in issues:
            print(f"  - {issue}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
