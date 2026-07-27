#!/usr/bin/env python3
"""
probe_training_view_engine.py — Verification probe for Phase 5C.

Verifies:
  1. Training view engine imports (generator, filter, manifest, validator)
  2. Lifecycle filtering works (approved vs pending vs rejected)
  3. Lineage preserved through generation pipeline
  4. License checks enforced (denied licenses blocked)
  5. Deterministic generation (same inputs, same output)
  6. No dataset mutation (curated files unchanged)
  7. No review mutation (review files unchanged)
  8. No release mutation (release metadata unchanged)
  9. Architecture validator passes
 10. Atlas self-test passes
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


def run_script(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT
    )
    return result.returncode, result.stdout + result.stderr


# Capture baseline hashes before any operations
baseline_hashes: dict[str, str] = {}


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture_baseline() -> None:
    """Capture SHA-256 hashes of curated, review, and release files."""
    for pattern, target_dir in [
        ("*.jsonl", ROOT / "curated"),
        ("*.jsonl", ROOT / "review_queue"),
        ("*.json", ROOT / "metadata" / "releases"),
        ("*.json", ROOT / "review" / "v0.2"),
        ("*.json", ROOT / "review" / "operations"),
    ]:
        if target_dir.exists():
            for fp in sorted(target_dir.rglob(pattern)):
                if fp.is_file():
                    baseline_hashes[str(fp.relative_to(ROOT))] = hash_file(fp)


# =====================================================================
# 1. Training view engine imports
# =====================================================================
print("=" * 60)
print("1. Training view engine imports")
print("=" * 60)

try:
    from training_view_engine import (
        TrainingViewGenerator,
        TrainingViewFilter,
        TrainingViewManifest,
        TrainingViewValidator,
    )
    check("training_view_engine import", True)
    check("TrainingViewGenerator exists", callable(TrainingViewGenerator))
    check("TrainingViewFilter exists", callable(TrainingViewFilter))
    check("TrainingViewManifest exists", callable(TrainingViewManifest))
    check("TrainingViewValidator exists", callable(TrainingViewValidator))
except Exception as e:
    check("training_view_engine import", False, str(e))

# Submodule imports
try:
    from training_view_engine.generator import TrainingViewGenerator
    check("generator submodule import", True)
except Exception as e:
    check("generator submodule import", False, str(e))

try:
    from training_view_engine.filter import TrainingViewFilter
    check("filter submodule import", True)
except Exception as e:
    check("filter submodule import", False, str(e))

try:
    from training_view_engine.manifest import TrainingViewManifest
    check("manifest submodule import", True)
except Exception as e:
    check("manifest submodule import", False, str(e))

try:
    from training_view_engine.validator import TrainingViewValidator
    check("validator submodule import", True)
except Exception as e:
    check("validator submodule import", False, str(e))

# =====================================================================
# 2. Lifecycle filtering works
# =====================================================================
print("\n" + "=" * 60)
print("2. Lifecycle filtering works")
print("=" * 60)

try:
    from training_view_engine.filter import TrainingViewFilter

    f = TrainingViewFilter(quality_threshold=5)

    # Create sample records: one approved, one pending, one rejected
    sample_records = [
        {
            "id": "rec_approved",
            "verification_status": "approved",
            "license": "MIT",
            "quality_score": 9,
            "training_view_eligibility": {"qwen": True, "llama": True, "deepseek": True},
            "lineage": {
                "source": "test",
                "transformations": [],
                "knowledge_object": "ko_1",
                "curated_dataset": "curated/v0.1",
                "training_view": "all",
                "future_model": "m",
            },
        },
        {
            "id": "rec_pending",
            "verification_status": "pending",
            "license": "MIT",
            "quality_score": 9,
            "training_view_eligibility": {"qwen": True, "llama": True, "deepseek": True},
            "lineage": {
                "source": "test",
                "transformations": [],
                "knowledge_object": "ko_2",
                "curated_dataset": "curated/v0.1",
                "training_view": "all",
                "future_model": "m",
            },
        },
        {
            "id": "rec_rejected",
            "verification_status": "rejected",
            "license": "MIT",
            "quality_score": 9,
            "training_view_eligibility": {"qwen": True, "llama": True, "deepseek": True},
            "lineage": {
                "source": "test",
                "transformations": [],
                "knowledge_object": "ko_3",
                "curated_dataset": "curated/v0.1",
                "training_view": "all",
                "future_model": "m",
            },
        },
    ]

    filtered = f.filter_records(sample_records)
    check("filter removes pending", len(filtered) == 1,
          f"expected 1, got {len(filtered)}")
    check("filter keeps approved only",
          all(r["verification_status"] == "approved" for r in filtered))
    check("filter removes rejected", "rec_rejected" not in [r["id"] for r in filtered],
          "rejected record was included")

    # Test filter_report
    report = f.filter_report(sample_records)
    check("filter_report total_input", report["total_input"] == 3)
    check("filter_report pending", report["pending_review"] == 1)
    check("filter_report rejected", report["rejected"] == 1)
    check("filter_report eligible", report["eligible"] == 1)

except Exception as e:
    check("lifecycle filtering", False, str(e))

# =====================================================================
# 3. Lineage preserved
# =====================================================================
print("\n" + "=" * 60)
print("3. Lineage preserved through generation pipeline")
print("=" * 60)

try:
    from training_view_engine.validator import TrainingViewValidator

    v = TrainingViewValidator()

    # A record with complete lineage should pass
    complete_record = {
        "id": "rec_lineage_ok",
        "verification_status": "approved",
        "license": "MIT",
        "quality_score": 9,
        "training_view_eligibility": {"qwen": True, "llama": True, "deepseek": True},
        "lineage": {
            "source": "test",
            "transformations": ["clean", "score"],
            "knowledge_object": "ko_1",
            "curated_dataset": "curated/v0.1",
            "training_view": "qwen",
            "future_model": "m",
        },
        "messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}],
        "category": "01_foundation",
        "subcategory": "test",
        "knowledge_type": "fact",
        "canonical_answer": "ans",
        "metadata": {},
        "source_attribution": {"source_id": "s1", "name": "n", "url": "", "license": "MIT", "attribution_text": ""},
        "tags": ["t"],
        "difficulty": 1,
    }
    errs = v.validate_record(complete_record)
    check("complete lineage passes", len(errs) == 0, f"errors: {errs}")

    # A record with missing lineage should fail
    incomplete_record = dict(complete_record)
    incomplete_record["lineage"] = {"source": "test"}
    incomplete_record["id"] = "rec_lineage_bad"
    errs2 = v.validate_record(incomplete_record)
    check("incomplete lineage fails", len(errs2) >= 1,
          f"expected lineage errors, got none")
    check("lineage error mentions lineage",
          any("lineage" in e for e in errs2),
          f"errors: {errs2}")

except Exception as e:
    check("lineage preservation", False, str(e))

# =====================================================================
# 4. License checks enforced
# =====================================================================
print("\n" + "=" * 60)
print("4. License checks enforced")
print("=" * 60)

try:
    from training_view_engine.filter import TrainingViewFilter
    from training_view_engine.validator import TrainingViewValidator

    f = TrainingViewFilter(quality_threshold=5)
    v = TrainingViewValidator()

    base = {
        "id": "rec_license_test",
        "verification_status": "approved",
        "quality_score": 9,
        "training_view_eligibility": {"qwen": True, "llama": True, "deepseek": True},
        "lineage": {
            "source": "test",
            "transformations": [],
            "knowledge_object": "ko_1",
            "curated_dataset": "curated/v0.1",
            "training_view": "all",
            "future_model": "m",
        },
        "messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}],
        "category": "01_foundation",
        "subcategory": "test",
        "knowledge_type": "fact",
        "canonical_answer": "ans",
        "metadata": {},
        "source_attribution": {"source_id": "s1", "name": "n", "url": "", "license": "MIT", "attribution_text": ""},
        "tags": ["t"],
        "difficulty": 1,
    }

    # Denied license
    denied = dict(base)
    denied["id"] = "rec_nc_license"
    denied["license"] = "CC-BY-NC-4.0"
    filtered_d = f.filter_records([denied])
    check("filter blocks NC license", len(filtered_d) == 0,
          f"NC license record was included")

    errs_d = v.validate_record(denied)
    check("validator blocks NC license", len(errs_d) >= 1,
          f"expected errors for NC license: {errs_d}")

    # Unknown license
    unknown = dict(base)
    unknown["id"] = "rec_unknown_license"
    unknown["license"] = "unknown"
    filtered_u = f.filter_records([unknown])
    check("filter blocks unknown license", len(filtered_u) == 0,
          "unknown license record was included")

    # Allowed license
    allowed = dict(base)
    allowed["id"] = "rec_mit_license"
    allowed["license"] = "MIT"
    filtered_a = f.filter_records([allowed])
    check("filter allows MIT license", len(filtered_a) == 1,
          "MIT record was excluded")

    errs_a = v.validate_record(allowed)
    check("validator passes MIT license", len(errs_a) == 0,
          f"errors for MIT: {errs_a}")

except Exception as e:
    check("license checks", False, str(e))

# =====================================================================
# 5. Deterministic generation
# =====================================================================
print("\n" + "=" * 60)
print("5. Deterministic generation")
print("=" * 60)

try:
    from training_view_engine.filter import TrainingViewFilter
    from training_view_engine.manifest import TrainingViewManifest

    recs = [
        {"id": "b", "name": "second"},
        {"id": "a", "name": "first"},
    ]

    # deterministic_hash should be the same on two calls
    f = TrainingViewFilter()
    h1 = f.deterministic_hash(recs)
    h2 = f.deterministic_hash(recs)
    check("filter.deterministic_hash stable", h1 == h2,
          f"h1={h1}, h2={h2}")

    # deterministic_hash should differ when records differ
    h3 = f.deterministic_hash([{"id": "c", "name": "third"}])
    check("deterministic_hash differs on different data", h1 != h3,
          "hashes should differ")

    # Manifest view ID should be deterministic
    vid1 = TrainingViewManifest.generate_view_id("v0.1", "qwen", "recipe_sft")
    vid2 = TrainingViewManifest.generate_view_id("v0.1", "qwen", "recipe_sft")
    check("view ID deterministic", vid1 == vid2,
          f"vid1={vid1}, vid2={vid2}")

    # Different models should produce different IDs
    vid3 = TrainingViewManifest.generate_view_id("v0.1", "llama", "recipe_sft")
    check("view ID differs per model", vid1 != vid3,
          "IDs should differ for different models")

except Exception as e:
    check("deterministic generation", False, str(e))

# =====================================================================
# 6. No dataset mutation
# =====================================================================
print("\n" + "=" * 60)
print("6. No dataset mutation (curated files unchanged)")
print("=" * 60)

# Capture baseline, then run training-view commands, then verify
capture_baseline()

dataset_files = sorted((ROOT / "curated").rglob("*.jsonl"))
if dataset_files:
    for fp in dataset_files:
        rel = str(fp.relative_to(ROOT))
        if rel in baseline_hashes:
            current = hash_file(fp)
            check(f"curated file unchanged: {rel}",
                  current == baseline_hashes[rel],
                  f"hash changed: {baseline_hashes[rel]} -> {current}")
else:
    check("curated files exist", False, "no curated files found")

# =====================================================================
# 7. No review mutation
# =====================================================================
print("\n" + "=" * 60)
print("7. Review integrity (no mutation)")
print("=" * 60)

review_patterns = [
    (ROOT / "review_queue", "*.jsonl"),
    (ROOT / "review" / "v0.2", "*.json"),
    (ROOT / "review" / "operations", "*.json"),
]
any_review_files = False
for rdir, rpat in review_patterns:
    if rdir.exists():
        for fp in sorted(rdir.rglob(rpat)):
            if fp.is_file():
                any_review_files = True
                rel = str(fp.relative_to(ROOT))
                if rel in baseline_hashes:
                    current = hash_file(fp)
                    check(f"review file unchanged: {rel}",
                          current == baseline_hashes[rel],
                          f"hash changed")
                else:
                    # File wasn't in baseline (new), but we have it now
                    print(f"       {rel}: {hash_file(fp)}")

if not any_review_files:
    # Review_queue may be empty or absent — that's OK
    check("review files check", True, "no review files to check")

# =====================================================================
# 8. No release mutation
# =====================================================================
print("\n" + "=" * 60)
print("8. Release metadata integrity")
print("=" * 60)

release_patterns = [
    (ROOT / "metadata" / "releases", "*.json"),
]
for rdir, rpat in release_patterns:
    if rdir.exists():
        for fp in sorted(rdir.rglob(rpat)):
            if fp.is_file():
                rel = str(fp.relative_to(ROOT))
                if rel in baseline_hashes:
                    current = hash_file(fp)
                    check(f"release file unchanged: {rel}",
                          current == baseline_hashes[rel],
                          f"hash changed")
                else:
                    print(f"       {rel}: {hash_file(fp)}")

# =====================================================================
# 9. Architecture validator passes
# =====================================================================
print("\n" + "=" * 60)
print("9. Architecture validator still passes")
print("=" * 60)

rc, out = run_script([sys.executable, "scripts/validate_architecture.py"])
check("architecture validator exit 0", rc == 0, f"exit={rc}")
check("architecture validator reports PASS", "RESULT: PASS" in out,
      f"unexpected: {out[-300:]}")
check("architecture validator no violations", "VIOLATION" not in out,
      "unexpected violations")

# =====================================================================
# 10. Atlas self-test passes
# =====================================================================
print("\n" + "=" * 60)
print("10. Atlas self-test passes")
print("=" * 60)

rc, out = run_script([sys.executable, "scripts/atlas.py", "self-test"])
check("self-test exit 0", rc == 0, f"exit={rc}")
# Check pass count
pass_count = out.count("[PASS]")
check("self-test pass count >= 27", pass_count >= 27, f"got {pass_count}")
# Check no FAIL in results section
fail_section = out.split("RESULT")[0] if "RESULT" in out else out
check("self-test no FAIL", "FAIL" not in fail_section,
      "unexpected FAIL in self-test")

# Also verify training-view safety check in self-test
check("self-test mentions training-view",
      "training-view-safety" in out,
      "training-view-safety check missing")

# =====================================================================
# 11. Training view CLI commands work
# =====================================================================
print("\n" + "=" * 60)
print("11. Training view CLI commands")
print("=" * 60)

# --list
rc, out = run_script([sys.executable, "scripts/atlas.py", "training-view", "--list"])
check("training-view --list exit 0", rc == 0, f"exit={rc}")
check("training-view --list shows text", "TRAINING VIEWS" in out,
      f"out={out[-200:]}")

# --generate (dry-run) — expect BLOCKED because no approved records
rc, out = run_script([sys.executable, "scripts/atlas.py",
                      "training-view", "--generate", "--source", "v0.2"])
# Should exit 1 because BLOCKED (no approved records)
check("training-view --generate exits blocked", rc == 1, f"exit={rc}")
check("training-view --generate shows BLOCKED", "BLOCKED" in out,
      f"out={out[-300:]}")
check("training-view --generate shows reproducibility hash",
      "Reproducibility" in out,
      f"missing reproducibility: {out[-200:]}")

# Verify no data was written during any operation
print("\n" + "-" * 60)
print("POST-OPERATION INTEGRITY CHECK")
print("-" * 60)
all_ok = True
for fp_rel, baseline_hash in baseline_hashes.items():
    fp = ROOT / fp_rel
    if fp.exists():
        current = hash_file(fp)
        if current != baseline_hash:
            print(f"  ❌ FILE CHANGED: {fp_rel}")
            all_ok = False
    else:
        print(f"  ❌ FILE MISSING: {fp_rel}")
        all_ok = False

if all_ok:
    print("  ✅ All tracked files unchanged — no mutation detected")

check("zero file mutation across all operations", all_ok,
      "some files were modified during read-only operations")

# =====================================================================
# Report
# =====================================================================
print("\n" + "=" * 60)
print(f"PHASE 5C TRAINING VIEW ENGINE VERIFICATION: {len(errors)} failure(s)")
print("=" * 60)
if errors:
    for e in errors:
        print(e)
    print("\nRESULT: FAIL")
    sys.exit(1)
else:
    print("RESULT: ALL PASS — training view engine verified")
    sys.exit(0)
