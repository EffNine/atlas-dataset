#!/usr/bin/env python3
"""
release.py — Atlas Release Management.

Provides:
  * ReleaseManager: create, list, verify, sign releases
  * Release manifest with full integrity metadata
  * Hash-chained release signatures (each release linked to prior)
  * Release gates: quality, license, schema, verification, category balance
  * Semantic diff with breaking-change detection and impact analysis
  * Deterministic, auditable, independently verifiable release process

Every Atlas release becomes a frozen, signed, and independently verifiable
snapshot. The release chain forms an audit trail: given the genesis release,
any subsequent release can be verified against the chain.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys
# Ensure scripts/ is on sys.path so atlas_constants and validate_dataset are importable
_THIS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _THIS_DIR.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from atlas_constants import (
    VALID_CATEGORIES,
    VERIFICATION_STATUSES,
    VERIFICATION_STATUS_RANK,
    is_denied_license,
    is_share_alike,
    requires_attribution,
)


# ---------------------------------------------------------------------------
# Release gate checks
# ---------------------------------------------------------------------------


def _load_records(file_paths: list[Path]) -> list[dict[str, Any]]:
    """Load records from multiple JSONL files."""
    records: list[dict[str, Any]] = []
    for fp in file_paths:
        if not fp.exists():
            continue
        with open(fp, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return records


GATE_RESULTS = {
    "PASS": "pass",
    "FAIL": "fail",
    "WARN": "warn",
}


class ReleaseGateResult:
    """Result of a single release gate check."""

    def __init__(self, name: str, status: str, message: str = "",
                 details: dict[str, Any] | None = None):
        self.name = name
        self.status = status  # "pass", "fail", "warn"
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
        }

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def __repr__(self) -> str:
        return f"[{self.status.upper()}] {self.name}: {self.message}"


class ReleaseGates:
    """
    Collection of release gate checks that must pass before a release.

    Gates:
      - quality_gate:    100% records have quality_score >= 7
      - license_gate:    No denied licenses in the release
      - schema_gate:     All records pass structural/knowledge-object validation
      - verification_gate: Checksums match for all files
      - category_balance_gate: Each category within ±5% of target
      - no_unknown_gate: No records with license="unknown"
      - no_rejected_sources_gate: No records from rejected sources
    """

    REQUIRED_GATES = [
        "quality_gate",
        "license_gate",
        "schema_gate",
        "verification_gate",
        "category_balance_gate",
        "no_unknown_license_gate",
        "no_rejected_source_gate",
    ]

    def __init__(self, records: list[dict[str, Any]],
                 manifest_data: dict[str, Any] | None = None):
        self.records = records
        self.manifest_data = manifest_data or {}

    def check_quality_gate(self, min_score: int = 7) -> ReleaseGateResult:
        """Check that 100% of records have quality_score >= min_score."""
        if not self.records:
            return ReleaseGateResult("quality_gate", "fail", "No records to check")
        below = [r.get("id", "?") for r in self.records
                 if not isinstance(r.get("quality_score"), (int, float))
                 or r["quality_score"] < min_score]
        total = len(self.records)
        pct_ok = round(100 * (total - len(below)) / total, 1)
        if below:
            return ReleaseGateResult(
                "quality_gate", "fail",
                f"{len(below)}/{total} records below quality_score {min_score} ({pct_ok}% pass)",
                {"below_threshold": below[:20], "total_below": len(below), "total": total,
                 "min_score": min_score, "pass_pct": pct_ok},
            )
        return ReleaseGateResult(
            "quality_gate", "pass",
            f"All {total} records have quality_score >= {min_score}",
            {"total": total, "min_score": min_score, "pass_pct": 100.0},
        )

    def check_license_gate(self) -> ReleaseGateResult:
        """Check that no records have denied licenses."""
        if not self.records:
            return ReleaseGateResult("license_gate", "fail", "No records to check")
        denied = [r for r in self.records
                  if is_denied_license(r.get("license", "unknown"))]
        if denied:
            lic_counts: dict[str, int] = {}
            for r in denied:
                l = r.get("license", "unknown")
                lic_counts[l] = lic_counts.get(l, 0) + 1
            return ReleaseGateResult(
                "license_gate", "fail",
                f"{len(denied)} records with denied licenses: {dict(sorted(lic_counts.items()))}",
                {"denied_count": len(denied), "total": len(self.records),
                 "by_license": lic_counts,
                 "denied_ids": [r.get("id", "?") for r in denied[:20]]},
            )
        return ReleaseGateResult(
            "license_gate", "pass",
            f"All {len(self.records)} records pass license gate",
            {"total": len(self.records)},
        )

    def check_schema_gate(self) -> ReleaseGateResult:
        """Check all records pass knowledge-object structural validation.

        Delegates to validate_dataset.structural_errors() as the canonical
        implementation, which runs the full structural check (fields, types,
        enums, source structure, messages, tags, quality_score, etc.).
        """
        # Import the canonical validator from validate_dataset.py
        import importlib.util as _ilu
        _ROOT = Path(__file__).resolve().parents[2]
        _v_spec = _ilu.spec_from_file_location(
            "validate_mod", _ROOT / "scripts" / "validate_dataset.py"
        )
        _v_mod = _ilu.module_from_spec(_v_spec)
        _v_spec.loader.exec_module(_v_mod)
        _structural_errors = _v_mod.structural_errors

        # Remove the "DENIED by commercial-safety policy" errors from the
        # structural check because the license_gate already covers that, and
        # they produce confusing duplicate failures. Filter only errors that
        # do NOT mention "DENIED".
        errors: list[dict[str, Any]] = []
        for r in self.records:
            rid = r.get("id", "?")
            all_errs = _structural_errors(r)
            structural_errs = [e for e in all_errs if "DENIED" not in e]
            if structural_errs:
                errors.append({
                    "id": rid,
                    "issue": "; ".join(structural_errs[:5]),
                    "total": len(structural_errs),
                })
        if errors:
            return ReleaseGateResult(
                "schema_gate", "fail",
                f"{len(errors)}/{len(self.records)} records have schema errors",
                {"errors": errors[:30], "total_errors": len(errors),
                 "total": len(self.records)},
            )
        return ReleaseGateResult(
            "schema_gate", "pass",
            f"All {len(self.records)} records pass schema validation",
            {"total": len(self.records)},
        )

    def check_verification_gate(self, checksums_registry: dict[str, Any] | None = None,
                                 actual_checksums: dict[str, str] | None = None) -> ReleaseGateResult:
        """Check that file checksums match stored registry."""
        if checksums_registry is None:
            return ReleaseGateResult("verification_gate", "warn",
                                     "No checksum registry available — skipping verification gate",
                                     {"available": False})
        stored_files = checksums_registry.get("files", {})
        if isinstance(stored_files, list):
            stored = {e["path"]: e["sha256"] for e in stored_files
                      if "path" in e and "sha256" in e}
        else:
            stored = stored_files
        mismatches: list[str] = []
        missing: list[str] = []
        if actual_checksums:
            for path_str, actual in actual_checksums.items():
                expected = stored.get(path_str)
                if expected is None:
                    missing.append(path_str)
                elif actual != expected:
                    mismatches.append(path_str)
        if mismatches or missing:
            return ReleaseGateResult(
                "verification_gate", "fail",
                f"{len(mismatches)} mismatches, {len(missing)} missing files",
                {"mismatches": mismatches[:20], "missing": missing[:20],
                 "total_checked": len(actual_checksums or {})},
            )
        return ReleaseGateResult(
            "verification_gate", "pass",
            f"All {len(actual_checksums or {})} checksums verified",
            {"total_verified": len(actual_checksums or {})},
        )

    def check_category_balance_gate(self, tolerance: float = 0.05) -> ReleaseGateResult:
        """Check category distribution within tolerance of target."""
        targets: dict[str, int] = {}
        cat_targets = self.manifest_data.get("category_targets", {})
        if cat_targets:
            targets = {k: int(v) for k, v in cat_targets.items()}
        if not targets:
            return ReleaseGateResult("category_balance_gate", "warn",
                                     "No category targets in manifest — skipping balance gate",
                                     {"available": False})
        actual_counts: dict[str, int] = {}
        for r in self.records:
            c = r.get("category", "unknown")
            actual_counts[c] = actual_counts.get(c, 0) + 1
        imbalances: list[str] = []
        for cat, target in sorted(targets.items()):
            actual = actual_counts.get(cat, 0)
            if target > 0:
                deviation = abs(actual - target) / target
                if deviation > tolerance:
                    imbalances.append(f"{cat}: target={target} actual={actual} "
                                      f"dev={deviation*100:.1f}% (>±{tolerance*100:.0f}%)")
        extra_cats = set(actual_counts.keys()) - set(targets.keys())
        if extra_cats:
            for ec in extra_cats:
                imbalances.append(f"{ec}: unexpected category (not in targets, count={actual_counts[ec]})")
        if imbalances:
            return ReleaseGateResult(
                "category_balance_gate", "fail",
                f"{len(imbalances)} category imbalance(s)", {"imbalances": imbalances[:20]},
            )
        return ReleaseGateResult(
            "category_balance_gate", "pass",
            f"All {len(targets)} categories within ±{tolerance*100:.0f}% of target",
            {"tolerance": tolerance, "targets": targets, "actual": actual_counts},
        )

    def check_no_unknown_license_gate(self) -> ReleaseGateResult:
        """Check that no records have license='unknown'."""
        unknown = [r for r in self.records
                   if r.get("license", "").lower().strip() == "unknown"]
        if unknown:
            return ReleaseGateResult(
                "no_unknown_license_gate", "fail",
                f"{len(unknown)} records with 'unknown' license",
                {"total_unknown": len(unknown), "total": len(self.records),
                 "ids": [r.get("id", "?") for r in unknown[:20]]},
            )
        return ReleaseGateResult(
            "no_unknown_license_gate", "pass",
            f"Zero records with 'unknown' license (out of {len(self.records)})",
            {"total": len(self.records)},
        )

    def check_no_rejected_source_gate(self) -> ReleaseGateResult:
        """Check that no records come from rejected sources."""
        rejected_sources: set[str] = set()
        reg = self.manifest_data.get("source_registry", [])
        for s in reg:
            if isinstance(s, dict) and s.get("status") == "rejected":
                rejected_sources.add(s.get("id", ""))
        from_rejected = [r for r in self.records
                         if r.get("source_attribution", {}).get("source_id", "") in rejected_sources]
        if from_rejected:
            return ReleaseGateResult(
                "no_rejected_source_gate", "fail",
                f"{len(from_rejected)} records from rejected sources",
                {"ids": [r.get("id", "?") for r in from_rejected[:20]],
                 "sources": list(rejected_sources)},
            )
        return ReleaseGateResult(
            "no_rejected_source_gate", "pass",
            f"No records from rejected sources (out of {len(self.records)})",
            {"total": len(self.records)},
        )

    def run_all(self, checksums_registry: dict[str, Any] | None = None,
                actual_checksums: dict[str, str] | None = None) -> list[ReleaseGateResult]:
        """Run all gates and return results."""
        results = [
            self.check_quality_gate(),
            self.check_license_gate(),
            self.check_schema_gate(),
            self.check_verification_gate(checksums_registry, actual_checksums),
            self.check_category_balance_gate(),
            self.check_no_unknown_license_gate(),
            self.check_no_rejected_source_gate(),
        ]
        return results

    @staticmethod
    def all_passed(results: list[ReleaseGateResult]) -> bool:
        """Return True if all gates passed."""
        return all(r.passed for r in results)

    @staticmethod
    def format_results(results: list[ReleaseGateResult]) -> str:
        """Format gate results as a readable string."""
        lines: list[str] = []
        lines.append("Release Gate Results:")
        lines.append("-" * 60)
        for r in results:
            icon = "✅" if r.passed else ("⚠️" if r.status == "warn" else "❌")
            lines.append(f"  {icon} [{r.status.upper()}] {r.name}")
            lines.append(f"      {r.message}")
        lines.append("-" * 60)
        passed = sum(1 for r in results if r.passed)
        total = len(results)
        lines.append(f"  Gates: {passed}/{total} passed")
        if ReleaseGates.all_passed(results):
            lines.append("  ✅ All gates PASSED — ready for release")
        else:
            lines.append("  ❌ Some gates FAILED — release blocked")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Semantic diff engine
# ---------------------------------------------------------------------------

class SemanticDiff:
    """
    Enhanced semantic diff with breaking-change detection and impact analysis.

    Extends the basic ID-level diff from dataset_diff.py with:
      - Breaking change detection (schema changes, category removal, etc.)
      - Impact analysis (which downstream consumers are affected)
      - Summary metrics (churn, stability score)
    """

    BREAKING_CHANGE_TYPES = [
        "schema_field_removed",
        "category_removed",
        "license_policy_change",
        "verification_status_regression",
        "quality_score_degradation",
        "knowledge_type_removed",
    ]

    def __init__(self, from_records: dict[str, dict[str, Any]],
                 to_records: dict[str, dict[str, Any]]):
        self.from_records = from_records
        self.to_records = to_records

    def compute(self) -> dict[str, Any]:
        """Compute a semantic diff between two record sets."""
        from_ids = set(self.from_records.keys())
        to_ids = set(self.to_records.keys())

        added_ids = sorted(to_ids - from_ids)
        removed_ids = sorted(from_ids - to_ids)
        common_ids = sorted(from_ids & to_ids)

        # Detect schema-level breaking changes
        breaking_changes: list[dict[str, Any]] = []

        # Collect all field keys from both sides
        from_keys: set[str] = set()
        to_keys: set[str] = set()
        for rid in common_ids:
            from_keys.update(self.from_records[rid].keys())
            to_keys.update(self.to_records[rid].keys())

        removed_fields = from_keys - to_keys
        for f in sorted(removed_fields):
            breaking_changes.append({
                "type": "schema_field_removed",
                "field": f,
                "severity": "breaking",
                "impact": f"Field '{f}' removed from all records",
            })

        # Detect category removal
        from_cats = set()
        for r in self.from_records.values():
            c = r.get("category")
            if c:
                from_cats.add(c)
        to_cats = set()
        for r in self.to_records.values():
            c = r.get("category")
            if c:
                to_cats.add(c)
        removed_cats = from_cats - to_cats
        for c in sorted(removed_cats):
            breaking_changes.append({
                "type": "category_removed",
                "category": c,
                "severity": "breaking",
                "impact": f"Entire category '{c}' removed (was {sum(1 for r in self.from_records.values() if r.get('category') == c)} records)",
            })

        # Detect quality score degradation
        degraded: list[dict[str, Any]] = []
        for rid in common_ids:
            fq = self.from_records[rid].get("quality_score", 0)
            tq = self.to_records[rid].get("quality_score", 0)
            if isinstance(fq, (int, float)) and isinstance(tq, (int, float)):
                if tq < fq - 1:  # meaningful drop
                    degraded.append({
                        "id": rid,
                        "from_score": fq,
                        "to_score": tq,
                        "delta": tq - fq,
                    })
        if len(degraded) > len(common_ids) * 0.1:  # >10% degraded
            breaking_changes.append({
                "type": "quality_score_degradation",
                "severity": "warning",
                "impact": f"{len(degraded)}/{len(common_ids)} records had quality_score drop > 1.0",
                "affected_ids": [d["id"] for d in degraded[:20]],
            })

        # Detect verification status regression
        regressed: list[dict[str, Any]] = []
        for rid in common_ids:
            fv = self.from_records[rid].get("verification_status", "")
            tv = self.to_records[rid].get("verification_status", "")
            f_rank = VERIFICATION_STATUS_RANK.get(fv, 0)
            t_rank = VERIFICATION_STATUS_RANK.get(tv, 0)
            if t_rank < f_rank:
                regressed.append({"id": rid, "from": fv, "to": tv})
        if regressed:
            breaking_changes.append({
                "type": "verification_status_regression",
                "severity": "warning",
                "impact": f"{len(regressed)} records had verification status regress",
                "affected": regressed[:20],
            })

        # Compute field-level diff for changed records
        changed_records: list[dict[str, Any]] = []
        tracking_fields = {"quality_score", "verification_status", "verified",
                           "difficulty", "license", "category", "subcategory"}
        field_change_counts: dict[str, int] = {}
        for rid in common_ids:
            fr = self.from_records[rid]
            tr = self.to_records[rid]
            changes: dict[str, dict[str, Any]] = {}
            for field in tracking_fields:
                fv = fr.get(field)
                tv = tr.get(field)
                if fv != tv:
                    changes[field] = {"from": fv, "to": tv}
                    field_change_counts[field] = field_change_counts.get(field, 0) + 1
            if changes:
                changed_records.append({"id": rid, "category": fr.get("category", ""), "changes": changes})

        # Churn metrics
        total_from = len(from_ids)
        total_to = len(to_ids)
        churn = total_from + total_to - 2 * len(common_ids)

        stability = 1.0
        if total_from > 0 and total_to > 0:
            stability = (len(common_ids) - len(changed_records)) / max(total_from, total_to)

        return {
            "summary": {
                "from_total": total_from,
                "to_total": total_to,
                "added": len(added_ids),
                "removed": len(removed_ids),
                "changed": len(changed_records),
                "unchanged": len(common_ids) - len(changed_records),
                "net_change": total_to - total_from,
                "churn": churn,
                "stability_score": round(stability, 4),
            },
            "breaking_changes": breaking_changes,
            "has_breaking_changes": len([b for b in breaking_changes if b.get("severity") == "breaking"]) > 0,
            "changed_records": changed_records[:50],
            "field_change_counts": dict(sorted(field_change_counts.items(), key=lambda x: -x[1])),
            "added_ids": added_ids[:20],
            "removed_ids": removed_ids[:20],
            "generated": datetime.now(timezone.utc).isoformat(),
        }

    def render_markdown(self, diff: dict[str, Any]) -> str:
        """Render semantic diff as a readable markdown report."""
        lines: list[str] = []
        summary = diff.get("summary", {})

        lines.append("# Atlas Semantic Dataset Diff Report")
        lines.append("")
        lines.append(f"**Generated:** {diff.get('generated', 'unknown')}")
        lines.append("")
        lines.append("## Summary")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|---|---|")
        lines.append(f"| From version total | {summary.get('from_total', '?')} |")
        lines.append(f"| To version total | {summary.get('to_total', '?')} |")
        lines.append(f"| Added | {summary.get('added', 0)} |")
        lines.append(f"| Removed | {summary.get('removed', 0)} |")
        lines.append(f"| Changed | {summary.get('changed', 0)} |")
        lines.append(f"| Unchanged | {summary.get('unchanged', 0)} |")
        lines.append(f"| Net change | {summary.get('net_change', 0):+d} |")
        lines.append(f"| Churn | {summary.get('churn', 0)} |")
        lines.append(f"| Stability score | {summary.get('stability_score', 1.0)} |")
        lines.append("")

        breaking = diff.get("breaking_changes", [])
        if breaking:
            lines.append("## ⚠ Breaking Changes & Warnings")
            lines.append("")
            for bc in breaking:
                sev = "🔴 BREAKING" if bc.get("severity") == "breaking" else "🟡 WARNING"
                lines.append(f"### {sev}: {bc.get('type', 'unknown')}")
                lines.append("")
                lines.append(f"{bc.get('impact', '')}")
                lines.append("")
            lines.append("")

        changed_recs = diff.get("changed_records", [])
        if changed_recs:
            lines.append("## Changed Records (first 50)")
            lines.append("")
            for cr in changed_recs:
                lines.append(f"- **{cr['id']}** ({cr.get('category', '')}):")
                for field, change in cr.get("changes", {}).items():
                    lines.append(f"  - {field}: `{change.get('from')}` → `{change.get('to')}`")
            lines.append("")

        field_counts = diff.get("field_change_counts", {})
        if field_counts:
            lines.append("## Most-Changed Fields")
            lines.append("")
            lines.append("| Field | Change Count |")
            lines.append("|---|---|")
            for field, count in field_counts.items():
                lines.append(f"| {field} | {count} |")
            lines.append("")

        added = diff.get("added_ids", [])
        if added:
            lines.append(f"## Added IDs (first 20)")
            lines.append("")
            lines.append(", ".join(added))
            lines.append("")

        removed = diff.get("removed_ids", [])
        if removed:
            lines.append(f"## Removed IDs (first 20)")
            lines.append("")
            lines.append(", ".join(removed))
            lines.append("")

        lines.append("---")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Release manager
# ---------------------------------------------------------------------------

class ReleaseManager:
    """
    Manages the full release lifecycle.

    Each release is a frozen, signed snapshot containing:
      - Release manifest (version, metadata, statistics, checksums)
      - Quality gate results
      - Semantic diff from the previous release
      - Signed metadata (hash-chained to prior release)
      - Full audit trail

    The release chain is stored in metadata/release_index.json and each
    release's manifest is stored at metadata/releases/<version>_release.json.
    """

    RELEASE_VERSION_RE = re.compile(r"^v(\d+)\.(\d+)(?:\.(\d+))?$")

    def __init__(self, dataset_root: str | Path):
        self.root = Path(dataset_root)
        self.metadata_dir = self.root / "metadata"
        self.releases_dir = self.metadata_dir / "releases"
        self.releases_dir.mkdir(parents=True, exist_ok=True)
        self.release_index_path = self.metadata_dir / "release_index.json"

    # -----------------------------------------------------------------------
    # Release index management
    # -----------------------------------------------------------------------

    def _load_release_index(self) -> dict[str, Any]:
        """Load the release index."""
        if not self.release_index_path.exists():
            return {"releases": [], "genesis_hash": ""}
        try:
            return json.loads(self.release_index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError):
            return {"releases": [], "genesis_hash": ""}

    def _save_release_index(self, index: dict[str, Any]) -> None:
        """Save the release index."""
        self.release_index_path.write_text(
            json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def list_releases(self) -> list[dict[str, Any]]:
        """List all releases with metadata."""
        index = self._load_release_index()
        return index.get("releases", [])

    def get_latest_release(self) -> dict[str, Any] | None:
        """Get the most recent release."""
        releases = self.list_releases()
        if not releases:
            return None
        return releases[-1]

    def get_release(self, version: str) -> dict[str, Any] | None:
        """Get a specific release by version string."""
        releases = self.list_releases()
        for r in releases:
            if r.get("version") == version:
                return r
        return None

    def release_exists(self, version: str) -> bool:
        """Check if a release version already exists."""
        return self.get_release(version) is not None

    def load_release_manifest(self, version: str) -> dict[str, Any] | None:
        """Load the full release manifest for a version."""
        manifest_path = self.releases_dir / f"{version}_release.json"
        if not manifest_path.exists():
            return None
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError):
            return None

    # -----------------------------------------------------------------------
    # Release signing (hash chain)
    # -----------------------------------------------------------------------

    def _compute_release_hash(self, release_data: dict[str, Any]) -> str:
        """Compute the signed hash of a release (excluding signature and derived fields)."""
        exclude = {"release_signature", "release_id"}
        data = {k: v for k, v in release_data.items() if k not in exclude}
        raw = json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
        return hashlib.sha256(raw).hexdigest()

    def _build_release_signature(self, release_data: dict[str, Any],
                                  previous_hash: str) -> dict[str, str]:
        """Build a hash-chain signature linking this release to the previous."""
        content_hash = self._compute_release_hash(release_data)
        chain_input = (previous_hash + content_hash).encode()
        chain_hash = hashlib.sha256(chain_input).hexdigest()
        return {
            "content_hash": content_hash,
            "previous_release_hash": previous_hash,
            "chain_hash": chain_hash,
            "signature_algorithm": "sha256-chain-v1",
        }

    def verify_release_signature(self, version: str) -> dict[str, Any]:
        """Verify a release's signature and position in the chain."""
        manifest = self.load_release_manifest(version)
        if manifest is None:
            return {"verified": False, "error": f"Release {version} not found"}

        signature = manifest.get("release_signature", {})
        if not signature:
            return {"verified": False, "error": "No signature found on release"}

        # Recompute content hash (same exclusion as _compute_release_hash)
        import hashlib as _hl
        exclude = {"release_signature", "release_id"}
        data = {k: v for k, v in manifest.items() if k not in exclude}
        raw = json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
        content_hash = _hl.sha256(raw).hexdigest()

        if content_hash != signature.get("content_hash"):
            return {"verified": False, "error": "Content hash mismatch — data has been modified"}

        # Verify chain hash
        prev_hash = signature.get("previous_release_hash", "")
        chain_input = (prev_hash + content_hash).encode()
        expected_chain = hashlib.sha256(chain_input).hexdigest()
        if expected_chain != signature.get("chain_hash"):
            return {"verified": False, "error": "Chain hash mismatch — chain is broken"}

        return {
            "verified": True,
            "version": version,
            "content_hash": content_hash,
            "chain_hash": signature.get("chain_hash", ""),
            "previous_hash": prev_hash,
        }

    def verify_release_chain(self) -> dict[str, Any]:
        """Verify the full hash chain from genesis to latest release."""
        releases = self.list_releases()
        if not releases:
            return {"verified": True, "chain_length": 0, "message": "No releases to verify"}

        chain_ok = True
        breakdown: list[dict[str, Any]] = []
        prev_hash = ""

        for i, r in enumerate(releases):
            ver = r.get("version", "?")
            result = self.verify_release_signature(ver)
            if i == 0:
                # Genesis: previous_hash should be empty
                manifest = self.load_release_manifest(ver)
                sig = manifest.get("release_signature", {}) if manifest else {}
                if sig.get("previous_release_hash", "") != "":
                    result["verified"] = False
                    result["error"] = "Genesis release has non-empty previous hash"
            else:
                # Check chain continuity
                if result.get("previous_hash") != prev_hash:
                    chain_ok = False
                    result["error"] = f"Chain discontinuity at {ver}: expected prev_hash {prev_hash}"

            if not result.get("verified", False):
                chain_ok = False
            breakdown.append({
                "version": ver,
                "verified": result.get("verified", False),
                "content_hash": result.get("content_hash", ""),
                "chain_hash": result.get("chain_hash", ""),
                "previous_hash": result.get("previous_hash", ""),
                "error": result.get("error"),
            })
            # Get content hash from verified result for next iteration
            if result.get("verified"):
                prev_hash = result.get("chain_hash", "")

        return {
            "verified": chain_ok,
            "chain_length": len(releases),
            "breakdown": breakdown,
        }

    # -----------------------------------------------------------------------
    # Release creation
    # -----------------------------------------------------------------------

    def create_release(
        self,
        version: str,
        source_paths: list[Path] | None = None,
        changelog: str = "",
        records: list[dict[str, Any]] | None = None,
        manifest_data: dict[str, Any] | None = None,
        checksums_registry: dict[str, Any] | None = None,
        actual_checksums: dict[str, str] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Create a new signed release.

        Runs all release gates. If any gate fails and force is False,
        the release is blocked.

        Args:
            version: Version string (e.g. "v0.2", "v1.0.0")
            source_paths: Paths to JSONL files to include
            changelog: Human-readable changelog
            records: Pre-loaded records (loaded from source_paths if None)
            manifest_data: Manifest data for gate checks (category_targets, etc.)
            checksums_registry: Checksum registry for verification gate
            actual_checksums: Actual file checksums for verification gate
            force: If True, skip gate failures and force the release

        Returns:
            Release manifest dict with status
        """
        version = version.lower().strip()
        if not self.RELEASE_VERSION_RE.match(version):
            return {"status": "error", "error": f"Invalid version format: {version}. Use vN.N or vN.N.N"}

        # Load records
        if records is None and source_paths:
            records = _load_records(source_paths)
        if records is None:
            records = []

        if not records and source_paths:
            return {"status": "error", "error": "No records loaded — nothing to release"}

        # Run release gates
        gates = ReleaseGates(records, manifest_data or {})
        gate_results = gates.run_all(checksums_registry, actual_checksums)
        gates_pass = ReleaseGates.all_passed(gate_results)

        if not gates_pass and not force:
            return {
                "status": "blocked",
                "error": "Release gates failed — use --force to override",
                "gate_results": [g.to_dict() for g in gate_results],
            }

        # Load previous release for diff and chain
        previous = self.get_latest_release()
        previous_hash = previous.get("chain_hash", "") if previous else ""
        from_version = previous.get("version", "") if previous else ""

        # Compute stats
        total = len(records)
        cat_counts: dict[str, int] = {}
        lic_counts: dict[str, int] = {}
        scores: list[int] = []
        status_counts: dict[str, int] = {}
        for rec in records:
            c = rec.get("category", "unknown")
            cat_counts[c] = cat_counts.get(c, 0) + 1
            l = rec.get("license", "unknown")
            lic_counts[l] = lic_counts.get(l, 0) + 1
            q = rec.get("quality_score", 0)
            if isinstance(q, (int, float)):
                scores.append(int(q))
            vs = rec.get("verification_status", "unknown")
            status_counts[vs] = status_counts.get(vs, 0) + 1

        avg_q = round(sum(scores) / len(scores), 2) if scores else 0

        # Compute diff from previous release if available
        semantic_diff: dict[str, Any] | None = None
        if from_version and previous:
            prev_records = self._load_release_records(from_version)
            if prev_records:
                from_index = {r["id"]: r for r in prev_records}
                to_index = {r["id"]: r for r in records}
                sd = SemanticDiff(from_index, to_index)
                semantic_diff = sd.compute()

        # Build release data
        now = datetime.now(timezone.utc).isoformat()

        release_type = "major" if ".0.0" in version else ("minor" if version.count(".") <= 1 else "patch")

        release_data: dict[str, Any] = {
            "release_version": version,
            "release_type": release_type,
            "created_at": now,
            "changelog": changelog,
            "from_version": from_version if from_version else None,
            "total_records": total,
            "statistics": {
                "by_category": dict(sorted(cat_counts.items())),
                "by_license": dict(sorted(lic_counts.items())),
                "by_verification_status": dict(sorted(status_counts.items())),
                "quality": {
                    "avg": avg_q,
                    "min": min(scores) if scores else 0,
                    "max": max(scores) if scores else 0,
                },
            },
            "gate_results": [g.to_dict() for g in gate_results],
            "gates_passed": gates_pass,
        }

        if semantic_diff:
            release_data["diff_from_previous"] = semantic_diff.get("summary", {})
            release_data["breaking_changes"] = semantic_diff.get("breaking_changes", [])
            release_data["has_breaking_changes"] = semantic_diff.get("has_breaking_changes", False)

        if checksums_registry:
            release_data["checksum_registry"] = {
                "version": checksums_registry.get("version", ""),
                "algorithm": checksums_registry.get("algorithm", "sha256"),
                "total_files": len(checksums_registry.get("files", {})),
                "registry_path": str(self.root / "metadata" / "engine_checksums.json"),
            }

        # Add release metadata before signing (so hash covers everything except signature)
        release_data["status"] = "created"

        # Sign the release
        signature = self._build_release_signature(release_data, previous_hash)
        release_data["release_signature"] = signature
        release_data["release_id"] = signature["chain_hash"][:16]

        # Save release manifest
        manifest_path = self.releases_dir / f"{version}_release.json"
        manifest_path.write_text(
            json.dumps(release_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Update release index
        index = self._load_release_index()
        if not index.get("genesis_hash") and not previous:
            index["genesis_hash"] = signature["chain_hash"]
        # Remove existing entry for this version if present
        index["releases"] = [r for r in index.get("releases", [])
                             if r.get("version") != version]
        index["releases"].append({
            "version": version,
            "release_type": release_type,
            "created_at": now,
            "total_records": total,
            "chain_hash": signature["chain_hash"],
            "content_hash": signature["content_hash"],
            "previous_hash": previous_hash,
            "gates_passed": gates_pass,
            "release_id": release_data["release_id"],
        })
        self._save_release_index(index)

        # Compute the gates passed count
        gates_passed_count = sum(1 for g in gate_results if g.passed)
        gates_total = len(gate_results)

        print(f"[release] Created release '{version}' — {total} records, "
              f"{gates_passed_count}/{gates_total} gates passed")
        if signature:
            print(f"[release] Release signature: {signature['chain_hash'][:16]}...")

        return release_data

    def _load_release_records(self, version: str) -> list[dict[str, Any]]:
        """Load records from a previous release's curated files."""
        curated_dir = self.root / "curated" / version
        if not curated_dir.exists():
            return []
        files = sorted(curated_dir.rglob("*.jsonl"))
        return _load_records(files)

    # -----------------------------------------------------------------------
    # Release verification
    # -----------------------------------------------------------------------

    def verify_release(self, version: str) -> dict[str, Any]:
        """Full verification of a release: signature, gates, data integrity."""
        manifest = self.load_release_manifest(version)
        if manifest is None:
            return {"verified": False, "error": f"Release {version} not found"}

        # 1. Signature verification
        sig_result = self.verify_release_signature(version)
        if not sig_result.get("verified"):
            return {"verified": False, "error": f"Signature verification failed: {sig_result.get('error')}"}

        # 2. Check release index consistency
        index = self._load_release_index()
        index_entry = None
        for r in index.get("releases", []):
            if r.get("version") == version:
                index_entry = r
                break
        if index_entry is None:
            return {"verified": False, "error": "Release not in index"}
        if index_entry.get("chain_hash") != sig_result.get("chain_hash"):
            return {"verified": False, "error": "Chain hash mismatch between manifest and index"}

        # 3. Verify gates are consistent (if stored in release)
        stored_gates = manifest.get("gate_results", [])
        stored_all_pass = all(g.get("status") == "pass" for g in stored_gates)

        return {
            "verified": True,
            "version": version,
            "release_id": manifest.get("release_id", ""),
            "total_records": manifest.get("total_records", 0),
            "signature_ok": True,
            "index_consistent": True,
            "gates_stored_pass": stored_all_pass,
            "gates_total": len(stored_gates),
            "generated": manifest.get("created_at", ""),
        }

    # -----------------------------------------------------------------------
    # Release summary
    # -----------------------------------------------------------------------

    def release_summary(self) -> dict[str, Any]:
        """Generate a summary of all releases and chain health."""
        index = self._load_release_index()
        releases = index.get("releases", [])
        if not releases:
            return {"status": "no_releases", "total": 0}

        chain_health = self.verify_release_chain()
        latest = releases[-1]

        return {
            "status": "ok",
            "total_releases": len(releases),
            "latest_version": latest.get("version", ""),
            "latest_release_id": latest.get("release_id", ""),
            "latest_records": latest.get("total_records", 0),
            "latest_gates_passed": latest.get("gates_passed", False),
            "chain_verified": chain_health.get("verified", False),
            "chain_length": chain_health.get("chain_length", 0),
            "genesis_hash": index.get("genesis_hash", ""),
            "releases": [
                {
                    "version": r.get("version"),
                    "type": r.get("release_type"),
                    "records": r.get("total_records"),
                    "created": r.get("created_at", "")[:19],
                    "gates_passed": r.get("gates_passed"),
                    "release_id": r.get("release_id"),
                }
                for r in releases
            ],
        }

    def render_summary_markdown(self, summary: dict[str, Any]) -> str:
        """Render the release summary as markdown."""
        lines: list[str] = []
        lines.append("# Atlas Release Summary")
        lines.append("")
        if summary.get("status") == "no_releases":
            lines.append("No releases have been created yet.")
            return "\n".join(lines) + "\n"

        lines.append(f"**Total releases:** {summary.get('total_releases', 0)}")
        lines.append(f"**Latest version:** {summary.get('latest_version', '?')}")
        lines.append(f"**Latest release ID:** `{summary.get('latest_release_id', '?')}`")
        lines.append(f"**Latest records:** {summary.get('latest_records', 0)}")
        lines.append(f"**Chain verified:** {'✅' if summary.get('chain_verified') else '❌'}")
        lines.append(f"**Chain length:** {summary.get('chain_length', 0)}")
        lines.append("")

        lines.append("## Releases")
        lines.append("")
        lines.append("| Version | Type | Records | Created | Gates | Release ID |")
        lines.append("|---|---|---|---|---|---|")
        for r in summary.get("releases", []):
            gates_icon = "✅" if r.get("gates_passed") else "❌"
            lines.append(
                f"| {r.get('version', '?')} | {r.get('type', '?')} | "
                f"{r.get('records', 0)} | {r.get('created', '?')} | "
                f"{gates_icon} | `{r.get('release_id', '?')[:12]}...` |"
            )
        lines.append("")
        return "\n".join(lines) + "\n"
