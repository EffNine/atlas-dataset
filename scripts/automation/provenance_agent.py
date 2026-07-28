#!/usr/bin/env python3
"""Provenance agent — adapter for the existing ProvenanceResolver.

This agent adapts :class:`provenance_resolver.ProvenanceResolver` into the
``BaseAgent`` interface without modifying the original tool. It:

  1. Creates a resolver instance for the project root.
  2. Runs the resolver against the pending expansion queue.
  3. Classifies records by resolution status.
  4. Reports unresolved records that still need human attention.

No immutable dataset files are read or written by this agent — only metadata
and report files.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .base_agent import BaseAgent, AgentResult, AgentStatus


class ProvenanceAgent(BaseAgent):
    """Adapter that wraps ProvenanceResolver as a pipeline agent.

    Runs the existing provenance resolution logic and reports which records
    have complete provenance metadata and which still require human input.

    Args:
        root: Path to the atlas-dataset repository root.
        config: Optional dict with keys:
            - input_path: Override default JSONL input path.
            - output_path: Override default report output path.
            - fail_on_unresolved: If True, agent FAILS when any records
              remain unresolved (default: False).

    Typical usage::

        agent = ProvenanceAgent(ROOT)
        result = agent.execute()
        if result.passed:
            print(f"Provenance OK: {result.summary}")
    """

    name: str = "provenance_agent"
    description: str = "Resolves provenance metadata for StackExchange records"

    def __init__(
        self,
        root: str | Path,
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(root, config)
        self._resolver = None
        # Lazy import to avoid circulars and keep the import optional
        self._resolver_module = None

    def _get_resolver(self):
        """Lazy-load and return the ProvenanceResolver."""
        if self._resolver is not None:
            return self._resolver

        # Import the provenance resolver from the scripts directory
        scripts_dir = str(self.root / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)

        from provenance_resolver import ProvenanceResolver  # type: ignore

        self._resolver = ProvenanceResolver(str(self.root))
        return self._resolver

    def execute(self, context: dict[str, Any] | None = None) -> AgentResult:
        """Run provenance resolution across the pending queue.

        Args:
            context: Optional pipeline context (unused by this agent).

        Returns:
            AgentResult with:
              - ``data.pending_queue_path`` — input file used
              - ``data.total_checked`` — total records examined
              - ``data.resolved_count`` — records with complete provenance
              - ``data.unresolved_count`` — records needing human attention
              - ``data.unresolved_ids`` — list of unresolved record IDs
              - ``data.report_path`` — path to the written report
              - ``errors`` — list of any errors encountered
        """
        try:
            resolver = self._get_resolver()
        except Exception as e:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILED,
                summary=f"Failed to load ProvenanceResolver: {e}",
                errors=[f"Import error: {e}"],
            )

        # Determine input path
        input_path = self.config.get("input_path")
        if input_path is not None:
            input_path = str(Path(input_path).resolve())

        # Run the resolver
        try:
            report = resolver.run(input_path=input_path)
        except Exception as e:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILED,
                summary=f"ProvenanceResolver.run() failed: {e}",
                errors=[str(e)],
            )

        # Write report
        output_path = self.config.get("output_path")
        try:
            report_path = resolver.write_report(report, output_path=output_path)
        except Exception as e:
            report_path = self.root / "tmp" / "provenance_resolution_report.md"
            # Non-fatal — report writing is advisory

        # Classify results
        resolved_ids = [s.record_id for s in report.suggestions if s.resolved]
        unresolved_ids = [s.record_id for s in report.suggestions if not s.resolved]

        data = {
            "pending_queue_path": str(report.source_file),
            "total_checked": report.total_records_checked,
            "resolved_count": len(resolved_ids),
            "unresolved_count": len(unresolved_ids),
            "resolved_ids": sorted(resolved_ids),
            "unresolved_ids": sorted(unresolved_ids),
            "report_path": str(report_path) if report_path else "",
            "errors_count": len(report.errors),
        }

        # Determine status
        fail_on_unresolved = self.config.get("fail_on_unresolved", False)
        if report.errors:
            status = AgentStatus.FAILED
            summary = f"Provenance resolution completed with {len(report.errors)} error(s)"
        elif fail_on_unresolved and unresolved_ids:
            status = AgentStatus.FAILED
            summary = (
                f"{len(unresolved_ids)} record(s) unresolved "
                f"(fail_on_unresolved=True)"
            )
        else:
            status = AgentStatus.PASSED
            summary = (
                f"Provenance check: {data['resolved_count']} resolved, "
                f"{data['unresolved_count']} unresolved, "
                f"{data['total_checked']} total checked"
            )

        return AgentResult(
            agent_name=self.name,
            status=status,
            summary=summary,
            data=data,
            errors=report.errors if report.errors else [],
        )
