#!/usr/bin/env python3
"""ExtractAgent v1.7 — run Extract → Normalize → Clean on cached downloads."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from automation.base_agent import AgentResult, AgentStatus, BaseAgent

from .pipeline import run_etl_for_source


class ExtractAgent(BaseAgent):
    name = "extract_agent"
    description = "Extract → Normalize → Clean cached downloads into staging JSONL"

    def __init__(self, root: str | Path, config: dict[str, Any] | None = None) -> None:
        super().__init__(root, config)
        self.source_ids = list(self.config.get("source_ids") or [])
        self.limit = self.config.get("limit")
        if self.limit is not None:
            self.limit = int(self.limit)
        self.promote_atlas = bool(self.config.get("promote_atlas", True))

    def execute(self, context: dict[str, Any] | None = None) -> AgentResult:
        context = context or {}
        source_ids = list(context.get("source_ids") or self.source_ids)
        if not source_ids:
            # Default: sources that have download logs
            log_dir = self.root / "metadata" / "download_logs"
            if log_dir.exists():
                source_ids = sorted(p.stem.replace(".download", "") for p in log_dir.glob("*.download.json"))
                # stem is like "c1.download" → Path.stem gives "c1.download" only if suffix is .json
                source_ids = sorted(p.name.removesuffix(".download.json") for p in log_dir.glob("*.download.json"))

        if not source_ids:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILED,
                summary="No source_ids provided and no download logs found",
                errors=["pass source_ids or run download first"],
            )

        results = []
        errors: list[str] = []
        warnings: list[str] = []
        totals = {"extracted": 0, "cleaned": 0, "atlas_records": 0, "dropped": 0}

        for sid in source_ids:
            etl = run_etl_for_source(
                self.root,
                sid,
                limit=self.limit,
                promote_atlas=self.promote_atlas,
            )
            results.append(etl.to_dict())
            totals["extracted"] += etl.extracted
            totals["cleaned"] += etl.cleaned
            totals["atlas_records"] += etl.atlas_records
            totals["dropped"] += etl.dropped
            errors.extend(etl.errors)
            warnings.extend(etl.warnings)

        failed = [r for r in results if r.get("status") == "failed"]
        if failed and len(failed) == len(results):
            status = AgentStatus.FAILED
            summary = f"ETL failed for all {len(failed)} source(s)"
        elif failed:
            status = AgentStatus.PASSED
            summary = (
                f"ETL completed with {len(failed)} failure(s); "
                f"cleaned={totals['cleaned']} atlas_staging={totals['atlas_records']}"
            )
        else:
            status = AgentStatus.PASSED
            summary = (
                f"ETL complete for {len(results)} source(s): "
                f"extracted={totals['extracted']} cleaned={totals['cleaned']} "
                f"atlas_staging={totals['atlas_records']} dropped={totals['dropped']}"
            )

        return AgentResult(
            agent_name=self.name,
            status=status,
            summary=summary,
            data={
                "sources": results,
                "totals": totals,
            },
            errors=errors,
            warnings=warnings,
        )
