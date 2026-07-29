#!/usr/bin/env python3
"""PublishAgent v1.8 — orchestrate Transform → Views → Release Bundle."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from automation.base_agent import AgentResult, AgentStatus, BaseAgent
from transform import run_transform
from view_builder import build_views
from release_builder import build_release


class PublishAgent(BaseAgent):
    name = "publish_agent"
    description = "Transform → Training Views → Release Bundle (v1.8)"

    def __init__(self, root: str | Path, config: dict[str, Any] | None = None) -> None:
        super().__init__(root, config)
        self.source_ids = list(self.config.get("source_ids") or [])
        self.version = self.config.get("version") or "v0.3-staging"
        self.models = list(self.config.get("models") or ["qwen", "llama", "deepseek"])
        self.allow_staging = bool(self.config.get("allow_staging", True))
        self.limit = self.config.get("limit")
        if self.limit is not None:
            self.limit = int(self.limit)
        self.skip_transform = bool(self.config.get("skip_transform", False))
        self.skip_views = bool(self.config.get("skip_views", False))
        self.hub_publish = bool(self.config.get("hub_publish", False))

    def execute(self, context: dict[str, Any] | None = None) -> AgentResult:
        context = context or {}
        source_ids = list(context.get("source_ids") or self.source_ids)
        if not source_ids:
            etl_root = self.root / "metadata" / "etl"
            if etl_root.exists():
                source_ids = sorted(p.name for p in etl_root.iterdir() if p.is_dir())
        if not source_ids:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILED,
                summary="No source_ids and no ETL outputs found",
                errors=["run etl first or pass source_ids"],
            )

        errors: list[str] = []
        warnings: list[str] = []
        transform_reports = []
        view_report = None
        release_report = None

        if not self.skip_transform:
            for sid in source_ids:
                report = run_transform(self.root, sid, limit=self.limit)
                transform_reports.append(report)
                if report.get("status") == "failed":
                    errors.extend(report.get("errors") or [report.get("summary", "transform failed")])

        if not self.skip_views:
            view_result = build_views(
                self.root,
                version=self.version,
                models=self.models,
                source_ids=source_ids,
                allow_staging=self.allow_staging,
                limit=self.limit,
            )
            view_report = view_result.to_dict()
            errors.extend(view_result.errors)
            warnings.extend(view_result.warnings)

        release_result = build_release(
            self.root,
            version=self.version,
            source_ids=source_ids,
            view_version=self.version,
            allow_staging=self.allow_staging,
            hub_publish=self.hub_publish,
        )
        release_report = release_result.to_dict()
        errors.extend(release_result.errors)
        warnings.extend(release_result.warnings)

        failed = bool(errors) and (
            (view_report and view_report.get("status") in {"failed", "blocked"})
            or release_report.get("status") in {"failed", "blocked"}
            or any(r.get("status") == "failed" for r in transform_reports)
        )

        if failed and (
            (view_report and view_report.get("status") == "failed")
            or release_report.get("status") == "failed"
            or all(r.get("status") == "failed" for r in transform_reports)
        ):
            status = AgentStatus.FAILED
        elif failed:
            status = AgentStatus.BLOCKED if any(
                (view_report or {}).get("status") == "blocked"
                or release_report.get("status") == "blocked"
                for _ in [0]
            ) else AgentStatus.PASSED
        else:
            status = AgentStatus.PASSED

        summary = (
            f"Publish {self.version}: "
            f"transform_sources={len(transform_reports)} "
            f"views={ (view_report or {}).get('summary', 'skipped') }; "
            f"release={release_report.get('summary')}"
        )

        return AgentResult(
            agent_name=self.name,
            status=status,
            summary=summary,
            data={
                "version": self.version,
                "source_ids": source_ids,
                "transform": transform_reports,
                "views": view_report,
                "release": release_report,
            },
            errors=errors,
            warnings=warnings,
        )
