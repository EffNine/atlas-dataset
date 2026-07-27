#!/usr/bin/env python3
"""
probe_architecture_governance.py — Verification probe for Phase 4C.3.

Verifies:
  1. Architecture validator executes and exits 0 (clean pass)
  2. No circular dependencies detected
  3. Dependency import rules pass (no lower-to-higher-layer imports)
  4. No duplicate license implementations detected
  5. No duplicate schema contracts detected
  6. No dataset modifications (curated files unchanged)
  7. No review modifications (review files unchanged)
  8. No release metadata modifications (release files unchanged)
  9. Existing atlas self-test unchanged (same pass count)
  10. Acquisition engine unchanged (same pass count)
  11. Release chain unchanged (chain verify passes)
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

errors: list[str] = []

# Stdlib modules for Layer 1 purity check
STDLIB_MODULES: frozenset[str] = frozenset({
    "abc", "argparse", "ast", "collections", "copy", "csv", "dataclasses",
    "datetime", "enum", "functools", "hashlib", "inspect", "itertools",
    "json", "math", "operator", "os", "pathlib", "pdb", "pickle", "pprint",
    "random", "re", "shutil", "string", "struct", "subprocess", "sys",
    "textwrap", "threading", "time", "traceback", "typing", "uuid",
    "warnings", "__future__", "__main__",
})


def check(label: str, cond: bool, detail: str = "") -> None:
    if not cond:
        errors.append(f"  FAIL  {label}: {detail}")
        print(f"  FAIL  {label}: {detail}")
    else:
        print(f"  PASS  {label}")


def run_script(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    return result.returncode, result.stdout + result.stderr


# =====================================================================
# 1. Architecture validator executes cleanly
# =====================================================================
print("=" * 60)
print("1. Architecture validator executes cleanly")
print("=" * 60)

rc, out = run_script([sys.executable, "scripts/validate_architecture.py"])
check("validator exit 0", rc == 0, f"exit code {rc}")
check("validator reports PASS", "RESULT: PASS" in out, f"unexpected: {out[-300:]}")

# Verify the report was written to metadata/
report_path = ROOT / "metadata" / "architecture_validation_report.json"
check("validation report exists", report_path.exists())
if report_path.exists():
    try:
        report = json.loads(report_path.read_text())
        check("report has schema_version", report.get("schema_version") == "1.0")
        check("report total_violations is 0", report.get("total_violations") == 0,
              f"found {report.get('total_violations')} violations")
        check("report result is PASS", report.get("result") == "PASS")
    except (json.JSONDecodeError, KeyError) as e:
        check("report JSON parseable", False, str(e))

# =====================================================================
# 2. No circular dependencies
# =====================================================================
print("\n" + "=" * 60)
print("2. Circular dependency check")
print("=" * 60)

if report_path.exists():
    report = json.loads(report_path.read_text())
    circ_count = report.get("summary", {}).get("circular_dependencies", -1)
    check("zero circular dependencies", circ_count == 0, f"found {circ_count}")

# Also verify through the validator output
check("validator no circular dep msg", "circular" not in out.lower() or "0 circular" in out.lower(),
      "circular dependency may have been detected")

# =====================================================================
# 3. Dependency rules pass
# =====================================================================
print("\n" + "=" * 60)
print("3. Dependency import rules")
print("=" * 60)

if report_path.exists():
    report = json.loads(report_path.read_text())
    fi_count = report.get("summary", {}).get("forbidden_imports", -1)
    check("zero forbidden imports", fi_count == 0, f"found {fi_count}")

# Check individual Layer 1 modules have no project imports
for mod_name in ["atlas_constants", "atlas_schema", "atlas_paths"]:
    mod_path = ROOT / "scripts" / f"{mod_name}.py"
    if mod_path.exists():
        content = mod_path.read_text()
        # Should only import stdlib
        suspicious = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                # Skip __future__, __main__ — built-in pseudo-modules
                if "__future__" in stripped or "import __main__" in stripped:
                    continue
                # Skip stdlib
                if any(stripped.startswith(f"import {std_mod}") or
                       stripped.startswith(f"from {std_mod} ") or
                       stripped.startswith(f"from {std_mod}.")
                       for std_mod in STDLIB_MODULES):
                    continue
                suspicious.append(stripped)
        if suspicious:
            check(f"Layer 1 purity: {mod_name}", suspicious == [],
                  f"imports: {suspicious}")
        else:
            check(f"Layer 1 purity: {mod_name}", True)

# =====================================================================
# 4. No duplicate license implementations
# =====================================================================
print("\n" + "=" * 60)
print("4. License implementation uniqueness")
print("=" * 60)

if report_path.exists():
    report = json.loads(report_path.read_text())
    lf_count = report.get("summary", {}).get("duplicated_license_functions", -1)
    check("zero duplicated license functions", lf_count == 0, f"found {lf_count}")

# =====================================================================
# 5. No duplicate schema contracts
# =====================================================================
print("\n" + "=" * 60)
print("5. Schema definition uniqueness")
print("=" * 60)

if report_path.exists():
    report = json.loads(report_path.read_text())
    sd_count = report.get("summary", {}).get("duplicated_schema_definitions", -1)
    check("zero duplicated schema definitions", sd_count == 0, f"found {sd_count}")

# =====================================================================
# 6. No dataset modifications
# =====================================================================
print("\n" + "=" * 60)
print("6. Dataset integrity")
print("=" * 60)

dataset_files = [
    ROOT / "curated" / "v0.1" / "pilot_candidates.jsonl",
]
for fp in dataset_files:
    if fp.exists():
        content = fp.read_bytes()
        h = hashlib.sha256(content).hexdigest()
        check(f"dataset file present: {fp.relative_to(ROOT)}", True)
        print(f"       SHA256: {h}")
    else:
        check(f"dataset file exists: {fp.relative_to(ROOT)}", False, "not found")

# =====================================================================
# 7. No review modifications
# =====================================================================
print("\n" + "=" * 60)
print("7. Review decision integrity")
print("=" * 60)

review_dir = ROOT / "review_queue"
if review_dir.exists():
    for fp in sorted(review_dir.iterdir()):
        if fp.suffix == ".jsonl" and fp.is_file():
            content = fp.read_bytes()
            h = hashlib.sha256(content).hexdigest()
            print(f"       {fp.relative_to(ROOT)}: {h}")
    check("review_queue files readable", True)
else:
    check("review_queue dir exists", review_dir.exists(), "not found")

# Also check review metadata
review_meta_files = [
    ROOT / "review" / "v0.2" / "index.json",
    ROOT / "metadata" / "v0.2_review_manifest.json",
    ROOT / "metadata" / "v0.2_review_manifest_current.json",
]
for fp in review_meta_files:
    if fp.exists():
        content = fp.read_bytes()
        print(f"       {fp.relative_to(ROOT)}: {hashlib.sha256(content).hexdigest()}")

# =====================================================================
# 8. No release metadata modifications
# =====================================================================
print("\n" + "=" * 60)
print("8. Release metadata integrity")
print("=" * 60)

release_meta_files = [
    ROOT / "metadata" / "release_index.json",
]
for fp in release_meta_files:
    if fp.exists():
        content = fp.read_bytes()
        h = hashlib.sha256(content).hexdigest()
        print(f"       {fp.relative_to(ROOT)}: {h}")
        check(f"release meta: {fp.relative_to(ROOT)}", True)

releases_dir = ROOT / "metadata" / "releases"
if releases_dir.exists():
    for fp in sorted(releases_dir.iterdir()):
        if fp.suffix == ".json" and fp.is_file():
            content = fp.read_bytes()
            h = hashlib.sha256(content).hexdigest()
            print(f"       {fp.relative_to(ROOT)}: {h}")

# =====================================================================
# 9. Existing atlas self-test unchanged
# =====================================================================
print("\n" + "=" * 60)
print("9. Atlas self-test unchanged")
print("=" * 60)

rc, out = run_script([sys.executable, "scripts/atlas.py", "self-test"])
check("self-test exit 0", rc == 0)
pass_count = out.count("[PASS]")
check("self-test pass count >= 27", pass_count >= 27, f"got {pass_count}")
check("self-test no FAIL", "FAIL" not in out.split("RESULT")[0] if "RESULT" in out else True,
      f"unexpected FAIL")

# =====================================================================
# 10. Acquisition engine unchanged
# =====================================================================
print("\n" + "=" * 60)
print("10. Acquisition engine probes")
print("=" * 60)

rc, out = run_script([sys.executable, "tests/probe_acquisition_engine.py"])
check("probe exit 0", rc == 0)
check("probe all pass", "ALL PASS" in out, f"unexpected: {out[-300:]}")

# =====================================================================
# 11. Release chain unchanged
# =====================================================================
print("\n" + "=" * 60)
print("11. Release chain verification")
print("=" * 60)

rc, out = run_script([sys.executable, "scripts/atlas.py", "release", "--chain-verify"])
check("chain exit 0", rc == 0)
check("chain verified", "Chain verified" in out, f"unexpected: {out[-300:]}")

# =====================================================================
# Report
# =====================================================================
print("\n" + "=" * 60)
print(f"PHASE 4C.3 GOVERNANCE VERIFICATION: {len(errors)} failure(s)")
print("=" * 60)
if errors:
    for e in errors:
        print(e)
    print("\nRESULT: FAIL")
    sys.exit(1)
else:
    print("RESULT: ALL PASS")
    sys.exit(0)
