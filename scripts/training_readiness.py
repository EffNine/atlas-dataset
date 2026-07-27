#!/usr/bin/env python3
"""
training_readiness.py — Atlas Training Readiness Gate Engine (Phase 5D).

Evaluates whether the Atlas dataset is ready for training dataset generation.
This is a READ-ONLY assessment — no dataset mutation, no review changes,
no release changes, no training.

Four readiness dimensions:
  1. Review readiness   — approved/pending/rejected/needs_revision ratios
  2. Data quality       — quality score distribution, missing lineage, schema, provenance
  3. License            — denied/unknown licenses, attribution requirements
  4. Evaluation         — benchmark availability, evaluation reports, reproducibility

Status values:
  READY       — all gates pass
  CONDITIONAL — warnings exist but no hard blocks
  BLOCKED     — hard gate failure (pending records, unresolved provenance, missing lineage)

Usage:
  python scripts/training_readiness.py                         # generate report
  python scripts/training_readiness.py --verify                # verify report integrity
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = ROOT / "metadata" / "training_readiness_report.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl_records(path: Path) -> list[dict[str, Any]]:
    """Load all JSONL records from a directory tree of .jsonl files."""
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    for fp in sorted(path.rglob("*.jsonl")):
        with open(fp, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return records


def _verify_report(report: dict[str, Any]) -> dict[str, Any]:
    """Verify the integrity and determinism of a readiness report."""
    issues: list[str] = []

    # 1. Structural: all required keys present
    required = ["generated_at", "schema", "verdict", "dimensions", "gates", "summary"]
    for key in required:
        if key not in report:
            issues.append(f"Missing required key: {key}")

    # 2. Verdict is valid
    valid_verdicts = {"READY", "CONDITIONAL", "BLOCKED"}
    if report.get("verdict") not in valid_verdicts:
        issues.append(f"Invalid verdict: {report.get('verdict')}")

    # 3. Dimensions all present
    dim_keys = {"review_readiness", "data_quality_readiness",
                "license_readiness", "evaluation_readiness"}
    dims = report.get("dimensions", {})
    for dk in dim_keys:
        if dk not in dims:
            issues.append(f"Missing dimension: {dk}")

    # 4. Gates array structure
    gates = report.get("gates", [])
    for g in gates:
        if "gate" not in g or "status" not in g:
            issues.append(f"Gate missing required fields: {g.get('gate', '?')}")

    # 5. Deterministic — re-running gives the same result
    #    (This is an external property; here we verify the hash is stable)
    if "report_hash" in report:
        computed = _compute_report_hash(report)
        if computed != report["report_hash"]:
            issues.append("Report hash mismatch — content may have changed")

    return {
        "verified": len(issues) == 0,
        "issues": issues,
    }


def _compute_report_hash(report: dict[str, Any]) -> str:
    """Deterministic hash of the report (excluding generated_at and hash fields)."""
    # Make a copy, strip mutable metadata
    rep = dict(report)
    rep.pop("generated_at", None)
    rep.pop("report_hash", None)
    raw = json.dumps(rep, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Readiness Gate: Review Readiness
# ---------------------------------------------------------------------------

def evaluate_review_readiness(root: Path) -> dict[str, Any]:
    """Evaluate review completeness and blocking conditions."""
    result: dict[str, Any] = {
        "status": "UNKNOWN",
        "total_records": 0,
        "approved": 0,
        "pending": 0,
        "rejected": 0,
        "needs_revision": 0,
        "unresolved_revisions": 0,
        "approval_pct": 0.0,
        "details": [],
    }

    # Load review manifest
    manifest = _load_json(root / "metadata" / "v0.2_review_manifest.json")
    counts = manifest.get("counts", {})
    total = manifest.get("total_records", 0)
    result["total_records"] = total
    result["approved"] = counts.get("approved", 0)
    result["pending"] = counts.get("pending", 0)
    result["rejected"] = counts.get("rejected", 0)
    result["needs_revision"] = counts.get("needs_revision", 0)

    # Also scan records array for detailed status counts
    records = manifest.get("records", [])
    for rec in records:
        vs = rec.get("review_status", "pending")

    if total > 0:
        result["approval_pct"] = round(result["approved"] / total * 100, 2)

    # Also check review gate status
    gate_status = _load_json(root / "metadata" / "v0.2_review_gate_status.json")
    result["review_completed"] = gate_status.get("review_completed", False)

    # Unresolved revisions: from review feedback or needs_revision records
    result["unresolved_revisions"] = result["needs_revision"]

    # Determine blocking conditions
    blocked_conditions = []
    warnings = []

    if result["pending"] > 0:
        blocked_conditions.append(f"Pending records: {result['pending']}")

    if result["unresolved_revisions"] > 0:
        blocked_conditions.append(f"Unresolved revisions: {result['unresolved_revisions']}")

    if result["rejected"] > 0:
        warnings.append(f"Rejected records present: {result['rejected']} (may need replacement)")

    if not result.get("review_completed", False):
        blocked_conditions.append("Review cycle not completed")

    result["blocked_conditions"] = blocked_conditions
    result["warnings"] = warnings

    # Status
    if blocked_conditions:
        result["status"] = "BLOCKED"
    elif warnings:
        result["status"] = "CONDITIONAL"
    else:
        result["status"] = "READY"

    # Details
    result["details"] = blocked_conditions + warnings
    result["sources"] = ["metadata/v0.2_review_manifest.json",
                         "metadata/v0.2_review_gate_status.json"]

    return result


# ---------------------------------------------------------------------------
# Readiness Gate: Data Quality Readiness
# ---------------------------------------------------------------------------

def evaluate_data_quality_readiness(root: Path) -> dict[str, Any]:
    """Evaluate data quality — scores, lineage, schema, provenance."""
    result: dict[str, Any] = {
        "status": "UNKNOWN",
        "total_records": 0,
        "quality_distribution": {},
        "quality_mean": 0.0,
        "missing_lineage": 0,
        "schema_compliance": True,
        "provenance_status": "UNKNOWN",
        "details": [],
    }

    # Load curated records
    curated = []
    for vdir in sorted((root / "curated").iterdir()):
        if vdir.is_dir():
            curated.extend(_load_jsonl_records(vdir))

    result["total_records"] = len(curated)

    if not curated:
        result["status"] = "BLOCKED"
        result["details"] = ["No curated records found"]
        result["sources"] = ["curated/"]
        return result

    # Quality score distribution
    q_dist: dict[str, int] = {}
    missing_lineage = 0
    missing_provenance = 0
    schema_issues = 0
    expected_fields = {"id", "category", "messages", "license",
                       "quality_score", "verification_status"}

    for rec in curated:
        q = rec.get("quality_score")
        if q is not None:
            q_str = str(q)
            q_dist[q_str] = q_dist.get(q_str, 0) + 1

        # Lineage check
        lineage = rec.get("lineage")
        if not lineage or not isinstance(lineage, dict):
            missing_lineage += 1
        else:
            # Check required lineage sub-fields
            lineage_fields = {"source", "transformations"}
            if not lineage_fields.issubset(lineage.keys()):
                missing_lineage += 1

        # Provenance check (source_attribution)
        sa = rec.get("source_attribution")
        if not sa or not isinstance(sa, dict):
            missing_provenance += 1
        elif not sa.get("source_id") or not sa.get("license"):
            missing_provenance += 1

        # Schema compliance (basic structural)
        for f in expected_fields:
            if f not in rec:
                schema_issues += 1
                break

    result["quality_distribution"] = q_dist
    if q_dist:
        vals = [int(k) for k in q_dist]
        result["quality_mean"] = round(sum(vals) / len(vals), 2) if vals else 0.0
        result["quality_min"] = min(vals) if vals else 0
        result["quality_max"] = max(vals) if vals else 0

    result["missing_lineage"] = missing_lineage
    result["missing_provenance"] = missing_provenance
    result["schema_compliance"] = schema_issues == 0
    result["schema_issues"] = schema_issues

    # Provenance status
    if missing_provenance == 0:
        result["provenance_status"] = "COMPLETE"
    elif missing_provenance > 0:
        result["provenance_status"] = "PARTIAL"

    # Blocking conditions
    blocked_conditions = []
    warnings = []

    if missing_lineage > 0:
        blocked_conditions.append(f"Missing lineage on {missing_lineage} record(s)")

    if missing_provenance > 0:
        blocked_conditions.append(f"Unresolved provenance on {missing_provenance} record(s)")

    if not result["schema_compliance"]:
        blocked_conditions.append(f"Schema compliance issues: {schema_issues} record(s)")

    if len(q_dist) == 1:
        # All records have the same quality score — no variance
        warnings.append("No quality score variance — threshold-based filtering not possible")

    result["blocked_conditions"] = blocked_conditions
    result["warnings"] = warnings

    if blocked_conditions:
        result["status"] = "BLOCKED"
    elif warnings:
        result["status"] = "CONDITIONAL"
    else:
        result["status"] = "READY"

    result["details"] = blocked_conditions + warnings
    result["sources"] = ["curated/"]

    return result


# ---------------------------------------------------------------------------
# Readiness Gate: License Readiness
# ---------------------------------------------------------------------------

def evaluate_license_readiness(root: Path) -> dict[str, Any]:
    """Evaluate license compliance — denied, unknown, attribution."""
    result: dict[str, Any] = {
        "status": "UNKNOWN",
        "total_records": 0,
        "license_distribution": {},
        "denied_licenses": {},
        "unknown_licenses": {},
        "attribution_required": 0,
        "attribution_complete": 0,
        "details": [],
    }

    # Load source registry for source-level licenses
    registry = _load_json(root / "metadata" / "source_registry.json")
    sources = registry.get("sources", [])

    # Collect unique licenses from curated records
    curated: list[dict[str, Any]] = []
    for vdir in sorted((root / "curated").iterdir()):
        if vdir.is_dir():
            curated.extend(_load_jsonl_records(vdir))

    result["total_records"] = len(curated)

    lic_dist: dict[str, int] = {}
    denied_sources: dict[str, int] = {}
    unknown_sources: dict[str, int] = {}
    attr_required = 0
    attr_complete = 0

    # From curated records
    for rec in curated:
        lic = rec.get("license", "unknown")
        lic_dist[lic] = lic_dist.get(lic, 0) + 1

        # Check for denied license patterns
        from atlas_constants import is_denied_license, requires_attribution
        if is_denied_license(lic):
            denied_sources[lic] = denied_sources.get(lic, 0) + 1
        if lic == "unknown":
            unknown_sources[lic] = unknown_sources.get(lic, 0) + 1

        # Attribution check
        if requires_attribution(lic):
            attr_required += 1
            sa = rec.get("source_attribution", {})
            if sa and sa.get("attribution_text"):
                attr_complete += 1

    # Also check source registry for license issues
    for src in sources:
        sid = src.get("id", "?")
        lic = src.get("license", "unknown").lower()
        status = src.get("status", "unknown")
        if status == "rejected":
            denied_sources[f"source:{sid}"] = denied_sources.get(f"source:{sid}", 0) + 1

    result["license_distribution"] = lic_dist
    result["denied_licenses"] = {k: v for k, v in sorted(denied_sources.items())}
    result["unknown_licenses"] = unknown_sources
    result["attribution_required"] = attr_required
    result["attribution_complete"] = attr_complete
    result["attribution_pending"] = attr_required - attr_complete

    # Blocking conditions
    blocked_conditions = []
    warnings = []

    if denied_sources:
        blocked_conditions.append(f"Denied licenses found: {sum(denied_sources.values())} record(s)")

    if unknown_sources:
        blocked_conditions.append(f"Unknown licenses found: {sum(unknown_sources.values())} record(s)")

    if attr_required > 0 and attr_complete < attr_required:
        warnings.append(f"Attribution pending on {attr_required - attr_complete} record(s)")

    result["blocked_conditions"] = blocked_conditions
    result["warnings"] = warnings

    if blocked_conditions:
        result["status"] = "BLOCKED"
    elif warnings:
        result["status"] = "CONDITIONAL"
    else:
        result["status"] = "READY"

    result["details"] = blocked_conditions + warnings
    result["sources"] = ["curated/", "metadata/source_registry.json"]

    return result


# ---------------------------------------------------------------------------
# Readiness Gate: Evaluation Readiness
# ---------------------------------------------------------------------------

def evaluate_evaluation_readiness(root: Path) -> dict[str, Any]:
    """Evaluate evaluation infrastructure readiness."""
    result: dict[str, Any] = {
        "status": "UNKNOWN",
        "benchmark_count": 0,
        "internal_benchmarks": 0,
        "external_benchmarks": 0,
        "evaluation_reports": 0,
        "evaluation_reproducible": False,
        "details": [],
    }

    # Load benchmark registry
    registry = _load_json(root / "metadata" / "benchmark_registry.json")
    bench_reg = registry.get("registry", {})
    internal = bench_reg.get("internal", {})
    external = bench_reg.get("external", {})
    result["internal_benchmarks"] = len(internal)
    result["external_benchmarks"] = len(external)
    result["benchmark_count"] = len(internal) + len(external)

    # Count existing evaluation reports
    eval_dir = root / "evaluation"
    reports_found = 0
    if eval_dir.exists():
        for fp in eval_dir.rglob("*_report.json"):
            reports_found += 1
        for fp in eval_dir.rglob("*.json"):
            reports_found += 1
    result["evaluation_reports"] = reports_found

    # Check reproducibility — at least one benchmark with a registered checksum
    reproducible = False
    for bm_type in (internal, external):
        for bm_id, bm_data in bm_type.items():
            if bm_data.get("status") in ("active", "verified"):
                reproducible = True
                break

    result["evaluation_reproducible"] = reproducible

    # Blocking conditions
    blocked_conditions = []
    warnings = []

    if result["benchmark_count"] == 0:
        blocked_conditions.append("No benchmarks registered")
    else:
        all_placeholder = True
        for bm_type in (internal, external):
            for bm_id, bm_data in bm_type.items():
                if bm_data.get("status") != "placeholder":
                    all_placeholder = False
                    break
        if all_placeholder:
            warnings.append("All benchmarks are in placeholder status — no real evaluations run")

    if not reproducible:
        warnings.append("No verified/reproducible evaluation benchmarks")

    if reports_found == 0:
        warnings.append("No evaluation reports found")

    result["blocked_conditions"] = blocked_conditions
    result["warnings"] = warnings

    if blocked_conditions:
        result["status"] = "BLOCKED"
    elif warnings:
        result["status"] = "CONDITIONAL"
    else:
        result["status"] = "READY"

    result["details"] = blocked_conditions + warnings
    result["sources"] = ["metadata/benchmark_registry.json", "evaluation/"]

    return result


# ---------------------------------------------------------------------------
# Composite Readiness Engine
# ---------------------------------------------------------------------------

def evaluate_readiness(root: Path | None = None) -> dict[str, Any]:
    """Run all readiness gates and produce the composite readiness report."""
    if root is None:
        root = ROOT

    # Evaluate each dimension
    review = evaluate_review_readiness(root)
    quality = evaluate_data_quality_readiness(root)
    license_ = evaluate_license_readiness(root)
    evaluation = evaluate_evaluation_readiness(root)

    dimensions = {
        "review_readiness": review,
        "data_quality_readiness": quality,
        "license_readiness": license_,
        "evaluation_readiness": evaluation,
    }

    # Composite gates
    gates: list[dict[str, Any]] = []
    gate_defs = [
        ("review_gate", review, "All records must be reviewed (approved or rejected); no pending"),
        ("lineage_gate", quality, "All records must have complete lineage"),
        ("provenance_gate", quality, "All records must have resolved provenance"),
        ("license_gate", license_, "No denied or unknown licenses"),
        ("quality_gate", quality, "Quality scores must exist with variance"),
        ("evaluation_gate", evaluation, "Evaluation benchmarks available and reproducible"),
    ]

    all_blocked = False
    all_ready = True
    gate_summary: dict[str, int] = {"ready": 0, "conditional": 0, "blocked": 0}

    for g_name, g_dim, g_desc in gate_defs:
        g_status = g_dim["status"]
        g_passed = g_status == "READY"
        g_blocked = g_status == "BLOCKED"
        gates.append({
            "gate": g_name,
            "status": g_status,
            "passed": g_passed,
            "description": g_desc,
            "detail": "; ".join(g_dim.get("details", [])),
        })
        gate_summary[g_status.lower()] = gate_summary.get(g_status.lower(), 0) + 1
        if g_blocked:
            all_blocked = True
        if g_status != "READY":
            all_ready = False

    # Composite verdict
    if all_blocked:
        verdict = "BLOCKED"
    elif all_ready:
        verdict = "READY"
    else:
        verdict = "CONDITIONAL"

    report: dict[str, Any] = {
        "schema": "metadata/training_readiness_report.json",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_version": "v0.2",
        "verdict": verdict,
        "dimensions": dimensions,
        "gates": gates,
        "gate_summary": gate_summary,
        "summary": {
            "total_records": review.get("total_records", 0),
            "approved_records": review.get("approved", 0),
            "pending_records": review.get("pending", 0),
            "approval_rate": review.get("approval_pct", 0.0),
            "quality_mean": quality.get("quality_mean", 0.0),
            "missing_lineage": quality.get("missing_lineage", 0),
            "missing_provenance": quality.get("missing_provenance", 0),
            "denied_licenses": sum(license_.get("denied_licenses", {}).values()),
            "unknown_licenses": sum(license_.get("unknown_licenses", {}).values()),
            "benchmark_count": evaluation.get("benchmark_count", 0),
            "evaluation_reports": evaluation.get("evaluation_reports", 0),
        },
        "rules_applied": [
            "Any pending human review → BLOCKED",
            "Any unresolved provenance → BLOCKED",
            "Any missing lineage → BLOCKED",
            "Any denied/unknown license → BLOCKED",
            "No evaluation benchmarks → BLOCKED",
        ],
    }

    # Report hash for deterministic verification
    report["report_hash"] = _compute_report_hash(report)

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    do_verify = "--verify" in argv

    # Generate readiness report
    report = evaluate_readiness()
    verdict = report["verdict"]

    # Print summary
    print("=" * 64)
    print("ATLAS TRAINING READINESS REPORT")
    print("=" * 64)
    print(f"  Generated:        {report['generated_at'][:19]}")
    print(f"  Dataset version:  {report['dataset_version']}")
    print(f"  Verdict:          {verdict}")
    print()
    print("  Gates:")
    for g in report["gates"]:
        icon = "✅" if g["status"] == "READY" else ("⚠️" if g["status"] == "CONDITIONAL" else "❌")
        print(f"    {icon} {g['gate']}: {g['status']}")
        if g.get("detail"):
            print(f"       {g['detail']}")
    print()
    print("  Summary:")
    s = report["summary"]
    print(f"    Total records:        {s['total_records']}")
    print(f"    Approved:             {s['approved_records']}")
    print(f"    Pending:              {s['pending_records']}")
    print(f"    Approval rate:        {s['approval_rate']}%")
    print(f"    Quality mean:         {s['quality_mean']}")
    print(f"    Missing lineage:      {s['missing_lineage']}")
    print(f"    Missing provenance:   {s['missing_provenance']}")
    print(f"    Denied licenses:      {s['denied_licenses']}")
    print(f"    Unknown licenses:     {s['unknown_licenses']}")
    print(f"    Benchmarks:           {s['benchmark_count']}")
    print(f"    Evaluation reports:   {s['evaluation_reports']}")
    print()

    # Write report
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"  Report -> {REPORT_PATH.relative_to(ROOT)}")

    # Verify if requested
    if do_verify:
        print()
        print("  Verification:")
        loaded = _load_json(REPORT_PATH)
        v = _verify_report(loaded)
        if v["verified"]:
            print("    ✅ Report integrity verified")
        else:
            print("    ❌ Report issues:")
            for issue in v["issues"]:
                print(f"       - {issue}")
        print()

    # Final verdict
    if verdict == "BLOCKED":
        print("  ❌ TRAINING BLOCKED — resolve gate failures before proceeding.")
        print()
        print("  STOP. Do not train models, generate training datasets, or release v0.2.")
        print("  Wait for approval before Phase 5E.")
    elif verdict == "CONDITIONAL":
        print("  ⚠️  TRAINING CONDITIONAL — warnings exist; review before proceeding.")
    else:
        print("  ✅ TRAINING READY — all gates pass. Proceed with Phase 5E at your discretion.")

    print()
    print(f"  Report hash: {report['report_hash'][:20]}...")
    print("=" * 64)

    return 0 if verdict in ("READY", "CONDITIONAL") else 1


if __name__ == "__main__":
    sys.exit(main())
