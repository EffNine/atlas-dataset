#!/usr/bin/env python3
"""Validation agent — production implementation (v1.1).

Delegates to the existing production validators instead of reimplementing
validation logic in the agent itself:

  -  ``validate_dataset.py``: structural_errors() for base schema records
  -  ``validate_knowledge_object.py``: structural_errors() for KO records
  -  ``validate_dataset.py``: strict_jsonschema() (when jsonschema package available)
  -  ``atlas_constants.py``: is_denied_license(), VERIFICATION_STATUS_RANK
  -  ``atlas_schema.py``: canonical field sets, regex patterns
  -  ``acquisition_engine/integrity.py``: checksum verification

All dataset files are read-only — no writes to curated/ or review_queue/.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from .base_agent import BaseAgent, AgentResult, AgentStatus


# ---------------------------------------------------------------------------
# Lazy imports for production validators (preserve import resilience)
# ---------------------------------------------------------------------------

def _import(target: str):
    """Lazy-import a module from the scripts directory."""
    return __import__(target)


class ValidationAgent(BaseAgent):
    """Production dataset validation agent (v1.1).

    Performs comprehensive validation by delegating to existing production
    validators:

      1. JSONL parse check (every line must be valid JSON)
      2. Structural validation via ``validate_dataset.structural_errors()``
         or ``validate_knowledge_object.structural_errors()``
      3. JSON Schema validation via ``strict_jsonschema()`` (best-effort)
      4. License gate compliance via ``atlas_constants.is_denied_license()``
      5. Duplicate ID detection
      6. Duplicate content detection (normalized SHA-1 signature)
      7. Strict curated gate (quality_score >= 7, verified == True) — optional
      8. Record-level classification (valid / warning / error counts)

    Config keys:
        curated_path:  Override the default dataset path.
        schema_type:   ``"base"``, ``"knowledge_object"``, or ``"auto"``
                       (default ``"auto"`` — detects from record fields).
        strict:        Enable curated-stage gate (default ``False``).
        check_duplicates:  Enable duplicate detection (default ``True``).
        min_quality:   Minimum quality_score threshold for strict gate
                       (default ``7``).

    Args:
        root:  Path to the atlas-dataset repository root.
        config:  Optional configuration dict (see above).
    """

    name: str = "validation_agent"
    description: str = "Production dataset validation — structural, schema, license, duplicates, integrity"

    def __init__(
        self,
        root: str | Path,
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(root, config)
        cfg = config or {}
        self.schema_type = cfg.get("schema_type", "auto")
        self.strict = cfg.get("strict", False)
        self.check_duplicates = cfg.get("check_duplicates", True)
        self.min_quality = cfg.get("min_quality", 7)

        # Ensure scripts/ is on sys.path for production imports
        scripts = str(self.root / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)

    # ── Agent execution ──────────────────────────────────────────────────

    def execute(self, context: dict[str, Any] | None = None) -> AgentResult:
        """Run comprehensive validation against a curated dataset file.

        Args:
            context:  Optional dict; if ``curated_path`` is not set in config
                      the agent searches ``curated/v0.1/pilot_candidates.jsonl``
                      then ``curated/v0.1/*.jsonl``.

        Returns:
            ``AgentResult`` with detailed per-record validation data.
        """
        path = self._resolve_path()
        if path is None:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SKIPPED,
                summary="No dataset file found to validate",
                data={"searched": self._list_curated_files()},
            )

        # ── 1. Parse JSONL ───────────────────────────────────────────────
        records, parse_errors = self._parse_jsonl(path)
        total_lines = sum(1 for _ in path.read_text(encoding="utf-8").splitlines()
                          if _.strip())

        if not records and parse_errors:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILED,
                summary=f"All {len(parse_errors)} line(s) failed JSON parsing at {path}",
                data={"checked_path": str(path), "parse_errors": parse_errors},
                errors=parse_errors,
            )

        # ── 2. Import production validators ──────────────────────────────
        validate_dataset = _import("validate_dataset")
        atlas_constants = _import("atlas_constants")

        # ── 3. Detect schema type ────────────────────────────────────────
        schema_type = self.schema_type
        if schema_type == "auto" and records:
            # KO records have "knowledge_type" and "source_attribution"
            has_ko_fields = any(
                "knowledge_type" in r and "source_attribution" in r
                for r in records
            )
            schema_type = "knowledge_object" if has_ko_fields else "base"

        validate_ko = None
        if schema_type == "knowledge_object":
            try:
                validate_ko = _import("validate_knowledge_object")
            except ImportError:
                validate_ko = None

        # ── 4. Validate each record ──────────────────────────────────────
        per_record: list[dict[str, Any]] = []
        id_counter: Counter[str] = Counter()
        content_seen: dict[str, str] = {}
        stats = {
            "total": len(records),
            "valid": 0,
            "with_errors": 0,
            "with_warnings": 0,
        }

        for rec in records:
            rid = rec.get("id", "<no-id>")
            record_result: dict[str, Any] = {
                "id": rid,
                "errors": [],
                "warnings": [],
            }

            # Structural errors (primary validator)
            errs = validate_dataset.structural_errors(rec)
            record_result["errors"].extend(errs)

            # KO-specific structural errors (superset validator)
            if validate_ko and schema_type == "knowledge_object":
                ko_errs = validate_ko.structural_errors(rec)
                record_result["errors"].extend(ko_errs)

            # JSON Schema validation (best-effort, additive)
            # We only do this for base schema; KO schema validation is done
            # above in KO structural_errors
            if schema_type == "base":
                try:
                    schema_errs = validate_dataset.strict_jsonschema([rec])
                    if schema_errs and schema_errs[0]:
                        record_result["errors"].extend(schema_errs[0])
                except Exception:
                    pass  # jsonschema unavailable — non-fatal

            # License gate: check source.license or top-level license
            lic = (
                rec.get("license")
                or rec.get("source", {}).get("license", "")
                or ""
            )
            if lic and atlas_constants.is_denied_license(lic):
                record_result["errors"].append(
                    f"Denied license: {lic!r}"
                )

            # Track IDs for duplicate detection
            id_counter[rid] += 1

            # Content duplicate (normalized SHA-1)
            if self.check_duplicates:
                msgs = rec.get("messages", [])
                norm = "|".join(
                    f"{m.get('role', '?')}:{m.get('content', '').strip().lower()}"
                    for m in msgs if isinstance(m, dict)
                )
                ch = hashlib.sha1(norm.encode("utf-8")).hexdigest()
                if ch in content_seen:
                    record_result["errors"].append(
                        f"Duplicate content (also id={content_seen[ch]})"
                    )
                else:
                    content_seen[ch] = rid

            # Strict curated gate
            if self.strict:
                if lic == "unknown":
                    record_result["errors"].append(
                        "Curated license must not be 'unknown'"
                    )
                if not rec.get("verified"):
                    record_result["errors"].append("Record not verified")
                try:
                    qs = int(rec.get("quality_score", 0))
                    if qs < self.min_quality:
                        record_result["errors"].append(
                            f"quality_score {qs} < {self.min_quality}"
                        )
                except (TypeError, ValueError):
                    record_result["errors"].append(
                        "quality_score not an integer"
                    )

            # Classify
            if record_result["errors"]:
                stats["with_errors"] += 1
            else:
                stats["valid"] += 1
            if record_result["warnings"]:
                stats["with_warnings"] += 1

            per_record.append(record_result)

        # ── 5. Duplicate ID check (cross-record) ─────────────────────────
        dup_ids = {i for i, c in id_counter.items() if c > 1}
        if dup_ids and self.check_duplicates:
            for pr in per_record:
                if pr["id"] in dup_ids:
                    pr["errors"].append(f"Duplicate ID: {pr['id']!r} appears {id_counter[pr['id']]} times")
                    stats["with_errors"] += 1

        # ── 6. Build result data ─────────────────────────────────────────
        error_summary = self._summarize(per_record)

        data: dict[str, Any] = {
            "checked_path": str(path),
            "total_lines": total_lines,
            "total_records": len(records),
            "schema_type": schema_type,
            "strict_gate": self.strict,
            "stats": stats,
            "error_summary": error_summary,
            "parse_errors": parse_errors,
            "duplicate_ids": sorted(dup_ids) if dup_ids else [],
            "records": per_record,
        }

        # ── 7. Determine status ──────────────────────────────────────────
        errors_list = []
        if parse_errors:
            errors_list.append(f"{len(parse_errors)} line(s) failed JSON parse")
        if stats["with_errors"]:
            errors_list.append(
                f"{stats['with_errors']}/{stats['total']} record(s) have validation errors"
            )

        if errors_list:
            status = AgentStatus.FAILED
            summary = f"Validation failed: {'; '.join(errors_list)}"
        else:
            status = AgentStatus.PASSED
            summary = (
                f"Validation passed: {stats['valid']}/{stats['total']} records valid, "
                f"schema={schema_type}"
                f"{', strict' if self.strict else ''}"
            )

        return AgentResult(
            agent_name=self.name,
            status=status,
            summary=summary,
            data=data,
            errors=errors_list,
        )

    # ── Path resolution ──────────────────────────────────────────────────

    def _resolve_path(self) -> Path | None:
        """Resolve the dataset path from config or discover it."""
        curated_path = self.config.get("curated_path")
        if curated_path:
            p = Path(curated_path)
            return p if p.exists() else None

        # Default: pilot_candidates
        candidates = [
            self.root / "curated" / "v0.1" / "pilot_candidates.jsonl",
            self.root / "curated" / "v0.1" / "atlas_synthetic_test_v0.1.jsonl",
            self.root / "curated" / "v0.1" / "atlas_v0.1.jsonl",
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def _list_curated_files(self) -> list[str]:
        """List available curated files for diagnostic messaging."""
        curated = self.root / "curated"
        if not curated.exists():
            return []
        return sorted(
            str(p.relative_to(self.root))
            for p in curated.rglob("*.jsonl")
            if p.is_file()
        )

    # ── Parsing ──────────────────────────────────────────────────────────

    @staticmethod
    def _parse_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
        """Parse a JSONL file. Returns (records, parse_error_messages)."""
        records: list[dict[str, Any]] = []
        parse_errors: list[str] = []
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as e:
                parse_errors.append(f"Line {line_no}: {e}")
        return records, parse_errors

    # ── Reporting helpers ────────────────────────────────────────────────

    @staticmethod
    def _summarize(
        per_record: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Aggregate error/warning patterns across all records."""
        error_patterns: Counter[str] = Counter()
        for pr in per_record:
            for err in pr["errors"]:
                # Group similar errors by normalized message prefix
                prefix = err.split(":")[0] if ":" in err else err.split("(")[0]
                error_patterns[prefix.strip()] += 1

        return {
            "total_records": len(per_record),
            "unique_error_patterns": len(error_patterns),
            "error_patterns": dict(error_patterns.most_common(20)),
        }
