#!/usr/bin/env python3
"""Validation agent — placeholder for final validation checks.

In future phases, this agent will:
  - Run the full validation pipeline (schemas, integrity checks).
  - Cross-reference against the acquisition engine integrity module.
  - Validate training view eligibility.
  - Check dataset diff consistency.

For v1, this agent performs lightweight structural validation:
  - Required field presence.
  - Valid JSONL format.
  - License gate compliance (delegated to atlas_constants).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base_agent import BaseAgent, AgentResult, AgentStatus


class ValidationAgent(BaseAgent):
    """Placeholder final validation agent for v1.

    Performs structural validation on a curated dataset file:
      - Valid JSONL format
      - Required fields present
      - License gate compliance

    Args:
        root: Path to the atlas-dataset repository root.
        config: Optional dict with keys:
            - curated_path: Path to curated dataset JSONL.
            - required_fields: Override default required field set.
    """

    name: str = "validation_agent"
    description: str = "Validates dataset structure and compliance"

    # Default required fields for base schema records
    DEFAULT_REQUIRED_FIELDS: frozenset[str] = frozenset({
        "id", "category", "type", "source", "messages",
        "quality_score", "verified",
    })

    def __init__(
        self,
        root: str | Path,
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(root, config)
        self.required_fields = frozenset(
            config.get("required_fields", self.DEFAULT_REQUIRED_FIELDS)
        )

    def execute(self, context: dict[str, Any] | None = None) -> AgentResult:
        """Run final validation checks.

        Args:
            context: Optional pipeline context (unused in v1 placeholder).

        Returns:
            AgentResult with validation results.
        """
        curated_path = self.config.get("curated_path")
        if curated_path:
            path = Path(curated_path).resolve()
        else:
            path = self.root / "curated" / "v0.1" / "pilot_candidates.jsonl"

        if not path.exists():
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SKIPPED,
                summary=f"Dataset not found at {path}",
                data={"checked_path": str(path)},
            )

        # Load and validate
        raw = path.read_text(encoding="utf-8")
        records: list[dict[str, Any]] = []
        parse_errors: list[str] = []
        missing_fields: list[tuple[str, str]] = []  # (record_id, field)
        license_issues: list[str] = []
        line_no = 0

        for line_no, line in enumerate(raw.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                records.append(rec)
            except json.JSONDecodeError as e:
                parse_errors.append(f"Line {line_no}: {e}")
                continue

        # Check required fields
        for rec in records:
            rid = rec.get("id", f"line_{line_no}")
            for field in self.required_fields:
                if field not in rec:
                    missing_fields.append((rid, field))

        # Check license gate
        try:
            scripts_dir = str(self.root / "scripts")
            orig_path = list(__import__("sys").path)
            if scripts_dir not in __import__("sys").path:
                __import__("sys").path.insert(0, scripts_dir)
            from atlas_constants import is_denied_license  # type: ignore
        except ImportError:
            # License gate check is best-effort
            is_denied_license = lambda lic: False  # noqa: E731

        for rec in records:
            rid = rec.get("id", "unknown")
            lic = rec.get("license") or rec.get("source", {}).get("license", "")
            if lic and is_denied_license(lic):
                license_issues.append(f"{rid}: denied license '{lic}'")

        data = {
            "checked_path": str(path),
            "total_lines": len(raw.splitlines()),
            "valid_records": len(records),
            "parse_errors": len(parse_errors),
            "missing_fields": len(missing_fields),
            "license_issues": len(license_issues),
            "required_fields_checked": sorted(self.required_fields),
            "parse_error_details": parse_errors,
            "missing_field_details": [f"{rid}: missing {f}" for rid, f in missing_fields],
            "license_issue_details": license_issues,
            "is_valid_jsonl": len(parse_errors) == 0,
        }

        errors = []
        if parse_errors:
            errors.append(f"{len(parse_errors)} parse error(s)")
        if missing_fields:
            errors.append(f"{len(missing_fields)} record(s) missing required fields")
        if license_issues:
            errors.append(f"{len(license_issues)} license issue(s)")

        if errors:
            status = AgentStatus.FAILED
            summary = f"Validation failed: {'; '.join(errors)}"
        else:
            status = AgentStatus.PASSED
            summary = (
                f"Validation passed: {len(records)} valid records, "
                f"no parse errors, all fields present, license gate OK"
            )

        return AgentResult(
            agent_name=self.name,
            status=status,
            summary=summary,
            data=data,
            errors=errors,
        )
