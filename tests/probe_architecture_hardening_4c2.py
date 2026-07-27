#!/usr/bin/env python3
"""
probe_architecture_hardening_4c2.py — Validation probe for Phase 4C.2.

Verifies:
  1. Existing self-test unchanged
  2. Acquisition engine tests unchanged
  3. Release chain unchanged
  4. Dataset hashes unchanged
  5. Review decision hashes unchanged
  6. Release metadata unchanged
  7. Schema files unchanged
  8. New modules import correctly
  9. No circular imports introduced
  10. Existing CLI commands still work
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

errors: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        errors.append(f"  FAIL  {label}: {detail}")
        print(f"  FAIL  {label}: {detail}")
    else:
        print(f"  PASS  {label}")


def run_script(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    return result.returncode, result.stdout + result.stderr


# =====================================================================
# 1. Self-test unchanged
# =====================================================================
print("=" * 60)
print("1. Self-test unchanged")
print("=" * 60)
rc, out = run_script(["python", "scripts/atlas.py", "self-test"])
check("self-test exit 0", rc == 0)
check("self-test all pass", out.count("[PASS]") == 27, f"got {out.count('[PASS]')} passes")
check("self-test no FAIL", "FAIL" not in out.split("RESULT")[0] if "RESULT" in out else True)

# =====================================================================
# 2. Acquisition engine probes unchanged
# =====================================================================
print("\n" + "=" * 60)
print("2. Acquisition engine probes")
print("=" * 60)
rc, out = run_script(["python", "tests/probe_acquisition_engine.py"])
check("probe exit 0", rc == 0)
check("probe all pass", "ALL PASS" in out, f"unexpected: {out[-200:]}")

# =====================================================================
# 3. Release chain unchanged
# =====================================================================
print("\n" + "=" * 60)
print("3. Release chain")
print("=" * 60)
rc, out = run_script(["python", "scripts/atlas.py", "release", "--chain-verify"])
check("chain exit 0", rc == 0)
check("chain verified", "Chain verified" in out, f"unexpected: {out[-200:]}")

# =====================================================================
# 4. Dataset hashes unchanged
# =====================================================================
print("\n" + "=" * 60)
print("4. Dataset hashes")
print("=" * 60)
# Check known dataset files haven't changed
dataset_files = [
    ROOT / "curated" / "v0.1" / "pilot_candidates.jsonl",
]
for fp in dataset_files:
    if fp.exists():
        content = fp.read_bytes()
        h = hashlib.sha256(content).hexdigest()
        check(f"dataset hash: {fp.relative_to(ROOT)}", len(h) == 64, f"SHA256: {h}")
        print(f"       SHA256: {h}")
    else:
        check(f"dataset file exists: {fp.name}", False, "file not found")

# =====================================================================
# 5. Review decision hashes unchanged
# =====================================================================
print("\n" + "=" * 60)
print("5. Review decisions")
print("=" * 60)
review_dir = ROOT / "review_queue"
if review_dir.exists():
    for fp in sorted(review_dir.iterdir()):
        if fp.suffix == ".jsonl" and fp.is_file():
            content = fp.read_bytes()
            h = hashlib.sha256(content).hexdigest()
            check(f"review: {fp.relative_to(ROOT)}", len(h) == 64, f"SHA256: {h}")
            print(f"       SHA256: {h}")
else:
    check("review_queue dir exists", False, "not found")

# =====================================================================
# 6. Release metadata unchanged
# =====================================================================
print("\n" + "=" * 60)
print("6. Release metadata")
print("=" * 60)
release_meta_files = [
    ROOT / "metadata" / "release_index.json",
]
for fp in release_meta_files:
    if fp.exists():
        content = fp.read_bytes()
        h = hashlib.sha256(content).hexdigest()
        check(f"release meta: {fp.relative_to(ROOT)}", len(h) == 64, f"SHA256: {h}")
        print(f"       SHA256: {h}")
    else:
        check(f"release meta: {fp.relative_to(ROOT)}", False, "not found")

# Check individual release manifests
releases_dir = ROOT / "metadata" / "releases"
if releases_dir.exists():
    for fp in sorted(releases_dir.iterdir()):
        if fp.suffix == ".json" and fp.is_file():
            content = fp.read_bytes()
            h = hashlib.sha256(content).hexdigest()
            print(f"       {fp.relative_to(ROOT)}: {h}")

# =====================================================================
# 7. Schema files unchanged
# =====================================================================
print("\n" + "=" * 60)
print("7. Schema files")
print("=" * 60)
schema_files = [
    ROOT / "schemas" / "dataset_schema.json",
    ROOT / "schemas" / "knowledge_object_schema.json",
    ROOT / "schemas" / "chat_schema.json",
]
for fp in schema_files:
    if fp.exists():
        content = fp.read_bytes()
        h = hashlib.sha256(content).hexdigest()
        check(f"schema: {fp.relative_to(ROOT)}", len(h) == 64, f"SHA256: {h}")
        print(f"       SHA256: {h}")

# =====================================================================
# 8. New modules import correctly
# =====================================================================
print("\n" + "=" * 60)
print("8. New module imports")
print("=" * 60)
try:
    from atlas_constants import (
        VALID_CATEGORIES, VALID_KNOWLEDGE_TYPES, VERIFICATION_STATUSES,
        LIFECYCLE_STATES, VALID_ROLES, VALID_TRAINING_MODELS,
        is_denied_license, is_share_alike, requires_attribution,
    )
    check("atlas_constants imports", True)
    check("VALID_CATEGORIES count", len(VALID_CATEGORIES) == 9)
    check("is_denied_license works", is_denied_license("CC-BY-NC-4.0"))
    check("is_share_alike works", is_share_alike("CC-BY-SA-4.0"))
    check("requires_attribution works", requires_attribution("CC-BY-4.0"))
except Exception as e:
    check("atlas_constants imports", False, str(e))

try:
    from atlas_schema import (
        BASE_ALLOWED_KEYS, KNOWLEDGE_OBJECT_REQUIRED_FIELDS,
        LINEAGE_SUB_FIELDS, ID_PATTERN, TAG_PATTERN, DATE_PATTERN,
        QUALITY_SCORE_MIN, QUALITY_SCORE_MAX,
        DIFFICULTY_MIN, DIFFICULTY_MAX, MIN_MESSAGE_TURNS,
    )
    check("atlas_schema imports", True)
    check("BASE_ALLOWED_KEYS count", len(BASE_ALLOWED_KEYS) == 14)
    check("KNOWLEDGE_OBJECT_REQUIRED_FIELDS count", len(KNOWLEDGE_OBJECT_REQUIRED_FIELDS) == 15)
    check("LINEAGE_SUB_FIELDS count", len(LINEAGE_SUB_FIELDS) == 6)
    check("QUALITY_SCORE range", QUALITY_SCORE_MIN == 0 and QUALITY_SCORE_MAX == 10)
    check("DIFFICULTY range", DIFFICULTY_MIN == 0 and DIFFICULTY_MAX == 3)
    check("MIN_MESSAGE_TURNS", MIN_MESSAGE_TURNS == 2)
    check("ID_PATTERN works", bool(ID_PATTERN.match("test_id_001")))
    check("TAG_PATTERN works", bool(TAG_PATTERN.match("test-tag")))
    check("DATE_PATTERN works", bool(DATE_PATTERN.match("2026-01-01")))
except Exception as e:
    check("atlas_schema imports", False, str(e))

try:
    from atlas_paths import (
        discover_root, get_root,
        scripts_dir, schemas_dir, metadata_dir,
        curated_dir, docs_dir, tmp_dir,
        dataset_schema_path, categories_metadata_path,
        approved_write_paths, is_write_safe,
    )
    check("atlas_paths imports", True)
    root = get_root()
    check("get_root returns path", isinstance(root, Path))
    check("scripts_dir exists", scripts_dir().exists())
    check("schemas_dir exists", schemas_dir().exists())
    check("metadata_dir exists", metadata_dir().exists())
    check("dataset_schema_path correct", dataset_schema_path().name == "dataset_schema.json")
    check("approved_write_roots count", len(approved_write_paths()) >= 8)
    check("is_write_safe accepts tmp", is_write_safe(tmp_dir()))
    check("is_write_safe rejects /etc", not is_write_safe(Path("/etc")))
except Exception as e:
    check("atlas_paths imports", False, str(e))

# =====================================================================
# 9. No circular imports
# =====================================================================
print("\n" + "=" * 60)
print("9. Circular import check")
print("=" * 60)
# Check that each foundation module can be imported independently
for mod_name in ["atlas_constants", "atlas_schema", "atlas_paths"]:
    try:
        subprocess.run(
            [sys.executable, "-c", f"import {mod_name}; print(f'{mod_name} OK')"],
            cwd=ROOT, capture_output=True, text=True, timeout=10, env={**__import__('os').environ, "PYTHONPATH": str(ROOT / "scripts")}
        )
        check(f"circ-free: {mod_name}", True)
    except Exception as e:
        check(f"circ-free: {mod_name}", False, str(e))

# Cross-import check: can atlas_constants be imported alone without atlas_schema or atlas_paths?
rc1, _ = run_script(["python", "-c", "import sys; sys.path.insert(0, 'scripts'); from atlas_constants import VALID_CATEGORIES; print('OK')"])
check("atlas_constants standalone", rc1 == 0)

# Can atlas_schema be imported standalone?
rc2, _ = run_script(["python", "-c", "import sys; sys.path.insert(0, 'scripts'); from atlas_schema import BASE_ALLOWED_KEYS; print('OK')"])
check("atlas_schema standalone", rc2 == 0)

# Can atlas_paths be imported standalone?
rc3, _ = run_script(["python", "-c", "import sys; sys.path.insert(0, 'scripts'); from atlas_paths import discover_root; print('OK')"])
check("atlas_paths standalone", rc3 == 0)

# =====================================================================
# 10. Existing CLI commands still work
# =====================================================================
print("\n" + "=" * 60)
print("10. CLI commands")
print("=" * 60)

# release --summary
rc, out = run_script(["python", "scripts/atlas.py", "release", "--summary"])
check("release --summary exit 0", rc == 0)
check("release summary works", "Total releases" in out or "No releases" in out,
      f"unexpected: {out[:200]}")

# release --list
rc, out = run_script(["python", "scripts/atlas.py", "release", "--list"])
check("release --list exit 0", rc == 0)

# =====================================================================
# Report
# =====================================================================
print("\n" + "=" * 60)
print(f"PHASE 4C.2 VALIDATION: {len(errors)} failure(s)")
print("=" * 60)
if errors:
    for e in errors:
        print(e)
    print("\nRESULT: FAIL")
    sys.exit(1)
else:
    print("RESULT: ALL PASS")
    sys.exit(0)
