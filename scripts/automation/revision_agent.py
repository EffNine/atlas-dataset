#!/usr/bin/env python3
"""Revision agent — placeholder for content revision workflow integration.

In future phases, this agent will:
  - Integrate with the existing revision review system.
  - Track records that need content revision.
  - Apply automated fixes for common issues (formatting, missing fields).
  - Route complex revisions to human reviewers.

For v1, this is a readiness check that reports any records flagged for revision.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base_agent import BaseAgent, AgentResult, AgentStatus


class RevisionAgent(BaseAgent):
    """Placeholder content revision agent for v1.

    Scans curated records for ``needs_revision`` verification status and
    reports which records require content revision before proceeding.

    Args:
        root: Path to the atlas-dataset repository root.
        config: Optional dict with keys:
            - curated_path: Path to curated dataset JSONL.
            - auto_fix: If True, attempt automated fixes (default: False,
              reserved for future phases).
    """

    name: str = "revision_agent"
    description: str = "Identifies records needing content revision"

    def __init__(
        self,
        root: str | Path,
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(root, config)
        self.auto_fix = (config or {}).get("auto_fix", False)

    def execute(self, context: dict[str, Any] | None = None) -> AgentResult:
        """Scan for records needing content revision.

        Args:
            context: Optional pipeline context (unused in v1 placeholder).

        Returns:
            AgentResult with revision status summary.
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
                summary=f"Curated dataset not found at {path}",
                data={"checked_path": str(path)},
            )

        records = self._load_jsonl(path)
        if not records:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SKIPPED,
                summary="No records to check",
                data={"checked_path": str(path), "total_records": 0},
            )

        needs_revision = []
        pending = []
        approved = []
        other = []

        for rec in records:
            vs = rec.get("verification_status", "unknown")
            rid = rec.get("id", "unknown")
            if vs == "needs_revision":
                needs_revision.append(rid)
            elif vs == "pending":
                pending.append(rid)
            elif vs == "approved":
                approved.append(rid)
            else:
                other.append(rid)

        data = {
            "checked_path": str(path),
            "total_records": len(records),
            "needs_revision_count": len(needs_revision),
            "pending_count": len(pending),
            "approved_count": len(approved),
            "other_count": len(other),
            "needs_revision_ids": sorted(needs_revision),
            "verification_statuses": {
                "needs_revision": len(needs_revision),
                "pending": len(pending),
                "approved": len(approved),
                "other": len(other),
            },
        }

        if needs_revision:
            status = AgentStatus.FAILED
            summary = (
                f"Revision check: {len(needs_revision)} record(s) need revision "
                f"({len(pending)} pending, {len(approved)} approved)"
            )
        else:
            status = AgentStatus.PASSED
            summary = (
                f"Revision check passed: {len(pending)} pending, "
                f"{len(approved)} approved, 0 needs revision"
            )

        return AgentResult(
            agent_name=self.name,
            status=status,
            summary=summary,
            data=data,
            errors=(
                [f"{len(needs_revision)} records need revision"]
                if needs_revision else []
            ),
        )

    @staticmethod
    def _load_jsonl(path: Path) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if not path.exists():
            return records
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return records
