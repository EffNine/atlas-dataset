#!/usr/bin/env python3
"""
release_decision_simulator.py — Atlas Release Decision Simulation (Phase 5D).

Simulates the release decision process without performing any actual release action.
Evaluates:

  current state → release gates → training readiness → decision

No actual release is created. No training dataset is generated.
This is a pure simulation for governance visibility.

Usage:
  python scripts/release_decision_simulator.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = ROOT / "docs" / "training" / "release_decision_simulation.md"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl_records(path: Path) -> list[dict[str, Any]]:
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


def simulate_document_links() -> dict[str, Any]:
    """Collect documentation links relevant to the simulation context."""
    links: dict[str, list[dict[str, Any]]] = {
        "metadata": [],
        "docs": [],
        "specs": [],
    }

    md_dir = ROOT / "metadata"
    if md_dir.exists():
        for fp in sorted(md_dir.glob("*.json")):
            links["metadata"].append({
                "path": str(fp.relative_to(ROOT)),
                "exists": fp.exists(),
            })

    docs_dir = ROOT / "docs"
    if docs_dir.exists():
        for fp in sorted(docs_dir.rglob("*.md")):
            links["docs"].append({
                "path": str(fp.relative_to(ROOT)),
                "exists": fp.exists(),
            })

    specs_dir = ROOT / "docs" / "specs"
    if specs_dir.exists():
        for fp in sorted(specs_dir.glob("*.md")):
            links["specs"].append({
                "path": str(fp.relative_to(ROOT)),
                "exists": fp.exists(),
            })

    return links


def simulate_release_gates(root: Path) -> list[dict[str, Any]]:
    """Simulate the release gate evaluation."""
    gates: list[dict[str, Any]] = []

    # Load review manifest for gate evaluation
    manifest = _load_json(root / "metadata" / "v0.2_review_manifest.json")
    counts = manifest.get("counts", {})
    total = manifest.get("total_records", 0)
    pending = counts.get("pending", 0)
    approved = counts.get("approved", 0)
    rejected = counts.get("rejected", 0)
    needs_revision = counts.get("needs_revision", 0)

    # Gate 1: Review Gate
    if pending > 0 or needs_revision > 0:
        gates.append({
            "gate": "review_gate",
            "status": "BLOCKED",
            "passed": False,
            "message": (
                f"Review incomplete: {pending} pending, "
                f"{needs_revision} needs_revision, "
                f"{approved} approved"
            ),
            "detail": "All records must be reviewed before training",
        })
    else:
        gates.append({
            "gate": "review_gate",
            "status": "PASS",
            "passed": True,
            "message": f"All {total} records reviewed ({approved} approved)",
            "detail": "",
        })

    # Gate 2: License Gate
    denied_count = 0
    unknown_count = 0
    records = manifest.get("records", [])
    for rec in records:
        lic = rec.get("license", rec.get("source_attribution", {}).get("license", "unknown"))
        if lic in ("unknown", "proprietary", "all-rights-reserved") or \
           "nc" in str(lic).lower() or "nd" in str(lic).lower():
            denied_count += 1

    if denied_count > 0:
        gates.append({
            "gate": "license_gate",
            "status": "BLOCKED",
            "passed": False,
            "message": f"{denied_count} record(s) have denied or unknown licenses",
            "detail": "Denied licenses must be removed before training",
        })
    else:
        gates.append({
            "gate": "license_gate",
            "status": "PASS",
            "passed": True,
            "message": "All records have valid licenses",
            "detail": "",
        })

    # Gate 3: Quality Gate
    curated = _load_jsonl_records(root / "curated")
    quality_scores = [r.get("quality_score", 0) for r in curated if r.get("quality_score") is not None]
    avg_q = round(sum(quality_scores) / len(quality_scores), 2) if quality_scores else 0
    below_threshold = sum(1 for q in quality_scores if q < 7)
    quality_variance = len(set(quality_scores))

    if below_threshold > 0:
        gates.append({
            "gate": "quality_gate",
            "status": "BLOCKED",
            "passed": False,
            "message": f"{below_threshold} record(s) below quality threshold (7)",
            "detail": f"Quality range: {min(quality_scores)}–{max(quality_scores)}, avg={avg_q}",
        })
    elif quality_variance < 2:
        gates.append({
            "gate": "quality_gate",
            "status": "CONDITIONAL",
            "passed": False,
            "message": f"Low quality variance: {quality_variance} distinct score(s)",
            "detail": f"All scores at {quality_scores[0] if quality_scores else '?'} — "
                      "threshold-based filtering not meaningful",
        })
    else:
        gates.append({
            "gate": "quality_gate",
            "status": "PASS",
            "passed": True,
            "message": f"Quality scores OK: {quality_variance} distinct, avg={avg_q}",
            "detail": "",
        })

    # Gate 4: Lineage Gate
    missing_lineage = sum(
        1 for r in curated
        if not r.get("lineage") or not isinstance(r.get("lineage"), dict)
    )

    if missing_lineage > 0:
        gates.append({
            "gate": "lineage_gate",
            "status": "BLOCKED",
            "passed": False,
            "message": f"{missing_lineage} record(s) missing lineage information",
            "detail": "Complete lineage is required for reproducibility",
        })
    else:
        gates.append({
            "gate": "lineage_gate",
            "status": "PASS",
            "passed": True,
            "message": "All records have complete lineage",
            "detail": "",
        })

    # Gate 5: Provenance Gate
    missing_provenance = sum(
        1 for r in curated
        if not r.get("source_attribution") or
           not isinstance(r.get("source_attribution"), dict) or
           not r["source_attribution"].get("source_id")
    )
    if missing_provenance > 0:
        gates.append({
            "gate": "provenance_gate",
            "status": "BLOCKED",
            "passed": False,
            "message": f"{missing_provenance} record(s) missing provenance",
            "detail": "Provenance chain must be complete",
        })
    else:
        gates.append({
            "gate": "provenance_gate",
            "status": "PASS",
            "passed": True,
            "message": "All records have provenance information",
            "detail": "",
        })

    # Gate 6: Evaluation Gate
    benchmark_reg = _load_json(root / "metadata" / "benchmark_registry.json")
    bench_count = len(benchmark_reg.get("registry", {}).get("internal", {})) + \
                  len(benchmark_reg.get("registry", {}).get("external", {}))

    if bench_count == 0:
        gates.append({
            "gate": "evaluation_gate",
            "status": "BLOCKED",
            "passed": False,
            "message": "No benchmarks registered for evaluation",
            "detail": "At least one benchmark required",
        })
    else:
        gates.append({
            "gate": "evaluation_gate",
            "status": "PASS" if bench_count >= 2 else "CONDITIONAL",
            "passed": bench_count >= 2,
            "message": f"{bench_count} benchmark(s) registered",
            "detail": "",
        })

    return gates


def simulate_training_readiness(root: Path) -> dict[str, Any]:
    """Read the training readiness report if available, else evaluate inline."""
    report_path = root / "metadata" / "training_readiness_report.json"
    if report_path.exists():
        report = _load_json(report_path)
        return {
            "verdict": report.get("verdict", "UNKNOWN"),
            "generated_at": report.get("generated_at", "?"),
            "total_records": report.get("summary", {}).get("total_records", 0),
            "approved_records": report.get("summary", {}).get("approved_records", 0),
            "pending_records": report.get("summary", {}).get("pending_records", 0),
            "quality_mean": report.get("summary", {}).get("quality_mean", 0),
            "missing_lineage": report.get("summary", {}).get("missing_lineage", 0),
            "missing_provenance": report.get("summary", {}).get("missing_provenance", 0),
            "denied_licenses": report.get("summary", {}).get("denied_licenses", 0),
            "benchmark_count": report.get("summary", {}).get("benchmark_count", 0),
        }

    # Fallback inline assessment
    manifest = _load_json(root / "metadata" / "v0.2_review_manifest.json")
    total = manifest.get("total_records", 0)
    pending = manifest.get("counts", {}).get("pending", 0)
    return {
        "verdict": "BLOCKED" if pending > 0 else "UNKNOWN",
        "generated_at": "inline-assessment",
        "total_records": total,
        "pending_records": pending,
        "note": "No readiness report found; inline assessment used",
    }


def simulate_state_summary(root: Path) -> dict[str, Any]:
    """Simulate a comprehensive current state summary."""
    manifest = _load_json(root / "metadata" / "v0.2_review_manifest.json")
    gate_status = _load_json(root / "metadata" / "v0.2_review_gate_status.json")
    curated = _load_jsonl_records(root / "curated")

    curated_total = len(curated)
    licenses_found: dict[str, int] = {}
    for r in curated:
        lic = r.get("license", "unknown")
        licenses_found[lic] = licenses_found.get(lic, 0) + 1

    return {
        "dataset_version": "v0.2",
        "total_curated_records": curated_total,
        "review_manifest_records": manifest.get("total_records", 0),
        "review_pending": manifest.get("counts", {}).get("pending", 0),
        "review_gate_status": gate_status.get("release_gate", {}).get("review_gate", {}).get("status", "UNKNOWN"),
        "licenses": licenses_found,
        "curated_sources": sorted(set(
            r.get("source_attribution", {}).get("source_id", "?")
            for r in curated if r.get("source_attribution")
        )),
    }


def simulate_decision(state: dict[str, Any],
                      gates: list[dict[str, Any]],
                      readiness: dict[str, Any]) -> dict[str, Any]:
    """Simulate the final release/training decision."""
    blocked_gates = [g for g in gates if g["status"] == "BLOCKED"]
    conditional_gates = [g for g in gates if g["status"] == "CONDITIONAL"]
    total_passed = sum(1 for g in gates if g["passed"])
    total_gates = len(gates)

    readiness_verdict = readiness.get("verdict", "UNKNOWN")

    # Determine decision
    if blocked_gates or readiness_verdict == "BLOCKED":
        decision = "BLOCKED"
        decision_rationale = [
            "Governance requirements not satisfied. The following must be resolved:",
        ]
        for g in blocked_gates:
            decision_rationale.append(f"  - {g['gate']}: {g['message']}")
        if readiness_verdict == "BLOCKED":
            decision_rationale.append("  - Training readiness assessment: BLOCKED")
        decision_summary = "Training and release are BLOCKED by governance."
    elif readiness_verdict == "CONDITIONAL" or conditional_gates:
        decision = "CONDITIONAL"
        decision_rationale = [
            "Technical checks passed but governance conditions remain:",
        ]
        for g in conditional_gates:
            decision_rationale.append(f"  - ⚠️ {g['gate']}: {g['message']}")
        decision_summary = "Proceed with caution under conditional status."
    else:
        decision = "PASS"
        decision_rationale = [
            "All technical checks passed. Training may begin.",
            f"  Gates passed: {total_passed}/{total_gates}",
            f"  Readiness verdict: {readiness_verdict}",
        ]
        decision_summary = "All checks pass. Ready for training."

    return {
        "decision": decision,
        "summary": decision_summary,
        "rationale": decision_rationale,
        "gates_passed": total_passed,
        "gates_total": total_gates,
        "gates_blocked": len(blocked_gates),
        "gates_conditional": len(conditional_gates),
        "readiness_verdict": readiness_verdict,
    }


def render_markdown(state: dict[str, Any],
                    gates: list[dict[str, Any]],
                    readiness: dict[str, Any],
                    decision: dict[str, Any],
                    links: dict[str, Any]) -> str:
    """Render the simulation report as markdown."""
    lines: list[str] = []
    lines.append("# Atlas Release Decision Simulation")
    lines.append("")
    lines.append(f"> **Phase 5D — Training Readiness Gate & Release Decision**")
    lines.append(f"> Generated: {datetime.now(timezone.utc).isoformat()[:19]}")
    lines.append("")
    lines.append("This document simulates the release decision process.")
    lines.append("**No actual release action has been performed.**")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 1. Current State
    lines.append("## 1. Current State Assessment")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|---|---|")
    lines.append(f"| Dataset Version | {state.get('dataset_version', '?')} |")
    lines.append(f"| Total Curated Records | {state.get('total_curated_records', 0)} |")
    lines.append(f"| Review Manifest Records | {state.get('review_manifest_records', 0)} |")
    lines.append(f"| Review Pending | {state.get('review_pending', 0)} |")
    lines.append(f"| Review Gate Status | {state.get('review_gate_status', '?')} |")
    lines.append("")
    lines.append("**License Distribution (curated records):**")
    lines.append("")
    lines.append(f"| License | Count |")
    lines.append(f"|---|---|")
    for lic, cnt in sorted(state.get("licenses", {}).items()):
        lines.append(f"| {lic} | {cnt} |")
    lines.append("")
    lines.append("**Curated Sources:**")
    for src in state.get("curated_sources", []):
        lines.append(f"- `{src}`")
    lines.append("")

    # 2. Release Gates
    lines.append("## 2. Release Gates")
    lines.append("")
    lines.append(f"| Gate | Status | Passed | Message |")
    lines.append(f"|---|---|---|---|")
    for g in gates:
        icon = "✅" if g["passed"] else "❌"
        lines.append(f"| {g['gate']} | {g['status']} | {icon} | {g.get('message', '')} |")
    lines.append("")
    passed = sum(1 for g in gates if g["passed"])
    total = len(gates)
    lines.append(f"**Gates passed: {passed}/{total}**")
    lines.append("")

    # 3. Training Readiness
    lines.append("## 3. Training Readiness Assessment")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|---|---|")
    lines.append(f"| Readiness Verdict | {readiness.get('verdict', '?')} |")
    lines.append(f"| Generated At | {readiness.get('generated_at', '?')[:19]} |")
    lines.append(f"| Total Records | {readiness.get('total_records', 0)} |")
    lines.append(f"| Approved Records | {readiness.get('approved_records', 0)} |")
    lines.append(f"| Pending Records | {readiness.get('pending_records', 0)} |")
    lines.append(f"| Quality Mean | {readiness.get('quality_mean', 0)} |")
    lines.append(f"| Missing Lineage | {readiness.get('missing_lineage', 0)} |")
    lines.append(f"| Missing Provenance | {readiness.get('missing_provenance', 0)} |")
    lines.append(f"| Denied Licenses | {readiness.get('denied_licenses', 0)} |")
    lines.append(f"| Benchmarks | {readiness.get('benchmark_count', 0)} |")
    lines.append("")

    # 4. Decision
    lines.append("## 4. Decision")
    lines.append("")
    dec_icon = "✅" if decision["decision"] == "PASS" else "❌"
    lines.append(f"### Decision: {dec_icon} **{decision['decision']}**")
    lines.append("")
    lines.append(f"**{decision['summary']}**")
    lines.append("")
    lines.append("**Rationale:**")
    lines.append("")
    for r in decision["rationale"]:
        lines.append(f"- {r}")
    lines.append("")
    lines.append("**Statistics:**")
    lines.append(f"- Gates passed: {decision['gates_passed']}/{decision['gates_total']}")
    lines.append(f"- Gates blocked: {decision['gates_blocked']}")
    lines.append(f"- Gates conditional: {decision['gates_conditional']}")
    lines.append(f"- Readiness verdict: {decision['readiness_verdict']}")
    lines.append("")

    # 5. Required Actions (if blocked or conditional)
    if decision["decision"] != "PASS":
        lines.append("## 5. Required Actions")
        lines.append("")
        if decision["decision"] == "BLOCKED":
            lines.append("### Blocking issues requiring resolution:")
            lines.append("")
            for g in gates:
                if g["status"] == "BLOCKED":
                    lines.append(f"1. **{g['gate']}**: {g['detail'] or g['message']}")
            lines.append("")
        if decision["decision"] == "CONDITIONAL":
            lines.append("### Conditional warnings to review:")
            lines.append("")
            for g in gates:
                if g["status"] == "CONDITIONAL":
                    lines.append(f"1. **{g['gate']}**: {g['detail'] or g['message']}")
            lines.append("")

    # 6. Governance Reminder
    lines.append("## 6. Governance Reminder")
    lines.append("")
    lines.append("- **No model training** has been started")
    lines.append("- **No fine-tuning** has been performed")
    lines.append("- **No checkpoint** has been created")
    lines.append("- **No v0.2 release** has been made")
    lines.append("- **No training dataset** has been generated")
    lines.append("- This simulation is for **evaluation and visibility only**")
    lines.append("")

    # 7. Document References
    lines.append("## 7. Document References")
    lines.append("")
    lines.append("### Metadata Files")
    lines.append("")
    for m in links.get("metadata", []):
        lines.append(f"- `{m['path']}` {'✅' if m['exists'] else '❌'}")
    lines.append("")
    lines.append("### Documentation")
    lines.append("")
    for d in links.get("docs", []):
        lines.append(f"- `{d['path']}` {'✅' if d['exists'] else '❌'}")
    lines.append("")
    lines.append("### Specifications")
    lines.append("")
    for s in links.get("specs", []):
        lines.append(f"- `{s['path']}` {'✅' if s['exists'] else '❌'}")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*This simulation was generated by `scripts/release_decision_simulator.py`.*")
    lines.append("*No actual release, training dataset, model training, or fine-tuning has occurred.*")
    lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    root = ROOT

    # 1. Collect state
    state = simulate_state_summary(root)

    # 2. Evaluate gates
    gates = simulate_release_gates(root)

    # 3. Read training readiness
    readiness = simulate_training_readiness(root)

    # 4. Simulate decision
    decision = simulate_decision(state, gates, readiness)

    # 5. Collect document links
    links = simulate_document_links()

    # 6. Render
    md = render_markdown(state, gates, readiness, decision, links)

    # 7. Write
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(md, encoding="utf-8")

    print("=" * 64)
    print("ATLAS RELEASE DECISION SIMULATION")
    print("=" * 64)
    print(f"  Decision: {decision['decision']}")
    print(f"  Gates passed: {decision['gates_passed']}/{decision['gates_total']}")
    print(f"  Readiness: {decision['readiness_verdict']}")
    print(f"  Output -> {OUTPUT_PATH.relative_to(root)}")
    print()
    print(f"  {decision['summary']}")
    print("=" * 64)

    return 0


if __name__ == "__main__":
    sys.exit(main())
