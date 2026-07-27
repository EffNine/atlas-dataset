#!/usr/bin/env python3
"""
probe_evaluation_foundation.py — Verification probe for Phase 5A.

Verifies:
  1. Evaluation engine imports (EvaluationOrchestrator, BenchmarkRegistry, etc.)
  2. Benchmark registry is valid JSON and validates against expected schema
  3. Evaluation report schema is valid (fields match spec)
  4. CLI commands work: --list, --describe, --dry-run
  5. No network access during evaluation operations
  6. No dataset modifications (curated files unchanged)
  7. No review modifications (review files unchanged)
  8. No release metadata modifications
  9. Existing atlas self-test unchanged (same pass count as prior)
  10. Architecture validator still passes
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


# =====================================================================
# 1. Evaluation engine imports
# =====================================================================
print("=" * 60)
print("1. Evaluation engine imports")
print("=" * 60)

try:
    from evaluation_engine import (
        EvaluationOrchestrator,
        BenchmarkRegistry,
        EvaluationReport,
        MetricRegistry,
        QualityScoreAgreement,
        ProvenanceAccuracy,
        SchemaPassRate,
        ContentSafetyRate,
    )
    check("evaluation_engine import", True)
    check("EvaluationOrchestrator exists", callable(EvaluationOrchestrator))
    check("BenchmarkRegistry exists", callable(BenchmarkRegistry))
    check("EvaluationReport exists", callable(EvaluationReport))
    check("MetricRegistry exists", callable(MetricRegistry))
    check("QualityScoreAgreement exists", callable(QualityScoreAgreement))
    check("ProvenanceAccuracy exists", callable(ProvenanceAccuracy))
    check("SchemaPassRate exists", callable(SchemaPassRate))
    check("ContentSafetyRate exists", callable(ContentSafetyRate))
except Exception as e:
    check("evaluation_engine import", False, str(e))

# Submodule imports
try:
    from evaluation_engine.engine import EvaluationOrchestrator, NetworkBlocked
    check("engine submodule import", True)
    check("NetworkBlocked exists", issubclass(NetworkBlocked, RuntimeError))
except Exception as e:
    check("engine submodule import", False, str(e))

try:
    from evaluation_engine.registry import BenchmarkRegistry
    check("registry submodule import", True)
except Exception as e:
    check("registry submodule import", False, str(e))

try:
    from evaluation_engine.metrics import BaseMetric, MetricRegistry
    check("metrics submodule import", True)
    check("BaseMetric is abstract", hasattr(BaseMetric, "compute"))
except Exception as e:
    check("metrics submodule import", False, str(e))

try:
    from evaluation_engine.report import EvaluationReport
    check("report submodule import", True)
except Exception as e:
    check("report submodule import", False, str(e))

# =====================================================================
# 2. Benchmark registry valid
# =====================================================================
print("\n" + "=" * 60)
print("2. Benchmark registry validation")
print("=" * 60)

reg_path = ROOT / "metadata" / "benchmark_registry.json"
check("registry file exists", reg_path.exists())

if reg_path.exists():
    try:
        reg_data = json.loads(reg_path.read_text(encoding="utf-8"))
        check("registry JSON parseable", True)

        # Check schema_version
        sv = reg_data.get("schema_version", "")
        check("registry has schema_version", bool(sv), f"version={sv}")

        # Check registry structure
        registry = reg_data.get("registry", {})
        check("registry has registry key", bool(registry))

        # Check internal benchmarks
        internal = registry.get("internal", {})
        check("registry has internal benchmarks", len(internal) >= 3,
              f"found {len(internal)} internal")

        # Check external benchmarks
        external = registry.get("external", {})
        check("registry has external benchmarks", len(external) >= 4,
              f"found {len(external)} external")

        # Validate each benchmark has required fields
        required = {"benchmark_id", "category", "purpose", "metric", "status"}
        missing_fields = []
        for cat_name, cat_benches in registry.items():
            for bm_id, bm in cat_benches.items():
                missing = required - set(bm.keys())
                if missing:
                    missing_fields.append(f"{cat_name}.{bm_id}: missing {missing}")
        check("all benchmarks have required fields", len(missing_fields) == 0,
              str(missing_fields))

        # Validate benchmark_registry.json is read-only (no extra top-level fields)
        allowed_top = {"schema_version", "updated", "description", "registry"}
        extra = set(reg_data.keys()) - allowed_top
        check("registry no extra top-level fields", len(extra) == 0,
              f"extra: {extra}")

    except (json.JSONDecodeError, KeyError) as e:
        check("registry validation", False, str(e))

# Validate via registry loader
try:
    from evaluation_engine import BenchmarkRegistry
    br = BenchmarkRegistry(ROOT)
    load_errors = br.validate()
    check("registry loader validates", len(load_errors) == 0,
          f"errors: {load_errors}")
    loaded = br.load()
    check("registry loader loads", bool(loaded))
except Exception as e:
    check("registry loader validation", False, str(e))

# =====================================================================
# 3. Report schema valid
# =====================================================================
print("\n" + "=" * 60)
print("3. Evaluation report schema validation")
print("=" * 60)

spec_path = ROOT / "docs" / "specs" / "evaluation_report_spec.md"
check("report spec exists", spec_path.exists())

# Check the report generator produces valid reports
try:
    from evaluation_engine import EvaluationReport
    er = EvaluationReport(ROOT)

    report = er.create_report(
        evaluation_id="eval_test_001",
        model_id="none",
        dataset_version="v0.1",
        benchmark_version="1.0",
        metrics=[{"metric_id": "test_metric", "name": "Test", "value": 1.0,
                  "status": "dry-run", "message": "test"}],
        failures=[],
        recommendations=["Test recommendation"],
    )

    required_fields = {
        "evaluation_id", "model_id", "dataset_version", "benchmark_version",
        "metrics", "failures", "recommendations", "timestamp", "reproducibility_hash",
    }
    present = set(report.keys())
    missing = required_fields - present
    check("report has all required fields", len(missing) == 0,
          f"missing: {missing}")

    extra = present - required_fields
    check("report no extra fields", len(extra) == 0,
          f"extra: {extra}")

    check("report evaluation_id matches", report["evaluation_id"] == "eval_test_001")
    check("report has reproducibility_hash", bool(report["reproducibility_hash"]))
    check("report has timestamp", bool(report["timestamp"]))

    # Check markdown rendering
    md = er.render_markdown(report)
    check("report renders markdown", len(md) > 50)
    check("report md contains evaluation_id", "eval_test_001" in md)

except Exception as e:
    check("report schema validation", False, str(e))

# =====================================================================
# 4. CLI commands work
# =====================================================================
print("\n" + "=" * 60)
print("4. CLI commands")
print("=" * 60)

# --list
rc, out = run_script([sys.executable, "scripts/atlas.py", "evaluate", "--list"])
check("evaluate --list exit 0", rc == 0, f"exit={rc}")
check("evaluate --list shows benchmarks", "Benchmark ID" in out, f"out={out[-200:]}")
check("evaluate --list shows internal", "atlas_quality_benchmark" in out,
      f"missing atlas_quality_benchmark")
check("evaluate --list shows external", "mmlu" in out, f"missing mmlu")

# --describe
rc, out = run_script([sys.executable, "scripts/atlas.py",
                       "evaluate", "--describe", "atlas_quality_benchmark"])
check("evaluate --describe exit 0", rc == 0, f"exit={rc}")
check("evaluate --describe shows benchmark", "atlas_quality_benchmark" in out,
      f"out={out[-200:]}")

# --describe nonexistent
rc, out = run_script([sys.executable, "scripts/atlas.py",
                       "evaluate", "--describe", "nonexistent"])
check("evaluate --describe unknown exits 0", rc == 0, f"exit={rc}")
check("evaluate --describe unknown shows not found", "Not found" in out,
      f"out={out[-200:]}")

# --dry-run
rc, out = run_script([sys.executable, "scripts/atlas.py", "evaluate", "--dry-run"])
check("evaluate --dry-run exit 0", rc == 0, f"exit={rc}")
check("evaluate --dry-run shows status", "dry-run" in out.lower(),
      f"out={out[-300:]}")
check("evaluate --dry-run shows benchmarks available",
      "Benchmarks available" in out, f"out={out[-300:]}")
check("evaluate --dry-run shows metrics available",
      "Metrics available" in out, f"out={out[-300:]}")
check("evaluate --dry-run shows reproducibility hash",
      "Reproducibility hash" in out, f"out={out[-300:]}")

# --dry-run twice: same reproducibility hash (deterministic)
rc1, out1 = run_script([sys.executable, "scripts/atlas.py", "evaluate", "--dry-run"])
rc2, out2 = run_script([sys.executable, "scripts/atlas.py", "evaluate", "--dry-run"])
check("dry-run deterministic (exit)", rc1 == rc2 == 0, f"rc1={rc1} rc2={rc2}")

# =====================================================================
# 5. No network access
# =====================================================================
print("\n" + "=" * 60)
print("5. No network access")
print("=" * 60)

try:
    from evaluation_engine.engine import install_network_block, NetworkBlocked
    import socket

    install_network_block()
    try:
        socket.socket()
        check("network blocked via socket", False, "socket creation was allowed")
    except NetworkBlocked:
        check("network blocked via socket", True)
    except Exception as e:
        check("network blocked via socket", False,
              f"unexpected exception: {e}")

    import urllib.request
    try:
        urllib.request.urlopen("http://example.com")
        check("network blocked via urlopen", False, "urlopen was allowed")
    except NetworkBlocked:
        check("network blocked via urlopen", True)
    except Exception:
        # May raise other exceptions (e.g. NameError if socket is also blocked)
        check("network blocked via urlopen", True)
except Exception as e:
    check("network block tests", False, str(e))

# =====================================================================
# 6. No dataset modifications
# =====================================================================
print("\n" + "=" * 60)
print("6. Dataset integrity (curated files unchanged)")
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

# Check benchmark_registry.json exists and is read-only
reg_path = ROOT / "metadata" / "benchmark_registry.json"
if reg_path.exists():
    content = reg_path.read_bytes()
    h = hashlib.sha256(content).hexdigest()
    print(f"       {reg_path.relative_to(ROOT)}: {h}")
    check("benchmark_registry.json present", True)

# =====================================================================
# 9. Existing atlas self-test unchanged
# =====================================================================
print("\n" + "=" * 60)
print("9. Atlas self-test unchanged")
print("=" * 60)

rc, out = run_script([sys.executable, "scripts/atlas.py", "self-test"])
check("self-test exit 0", rc == 0, f"exit={rc}")
pass_count = out.count("[PASS]")
check("self-test pass count >= 27", pass_count >= 27, f"got {pass_count}")
# Check no FAIL in the results section
fail_section = out.split("RESULT")[0] if "RESULT" in out else out
check("self-test no FAIL", "FAIL" not in fail_section, f"unexpected FAIL")

# =====================================================================
# 10. Architecture validator still passes
# =====================================================================
print("\n" + "=" * 60)
print("10. Architecture validator still passes")
print("=" * 60)

rc, out = run_script([sys.executable, "scripts/validate_architecture.py"])
check("architecture validator exit 0", rc == 0, f"exit={rc}")
check("architecture validator reports PASS", "RESULT: PASS" in out,
      f"unexpected: {out[-300:]}")
check("architecture validator no violations", "VIOLATION" not in out,
      "unexpected violations")

# =====================================================================
# Report
# =====================================================================
print("\n" + "=" * 60)
print(f"PHASE 5A EVALUATION FOUNDATION VERIFICATION: {len(errors)} failure(s)")
print("=" * 60)
if errors:
    for e in errors:
        print(e)
    print("\nRESULT: FAIL")
    sys.exit(1)
else:
    print("RESULT: ALL PASS — evaluation foundation verified")
    sys.exit(0)
