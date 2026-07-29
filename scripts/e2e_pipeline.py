#!/usr/bin/env python3
"""Atlas v2.0 — Single end-to-end pipeline command.

Chains: acquire → download → etl → transform → views → release bundle
with parallel workers (v1.9) and incremental state (skip already-done sources).

Usage::

    python -m scripts.automation_runner e2e --version v0.3 --max-workers 4

    # Dry-run (plan only, no network/disk writes)
    python -m scripts.automation_runner e2e --version v0.3 --dry-run

    # Limit sources and records for smoke tests
    python -m scripts.automation_runner e2e --version v0.3 \\
        --source-id c1 --source-id s4 --limit 200

    # Force re-run all stages even if incremental says done
    python -m scripts.automation_runner e2e --version v0.3 --force

Human approval gate::

    After e2e completes the bundle is staged. To promote to RELEASED:
        python -m scripts.automation_runner run --pipeline-id <version>
        python -m scripts.automation_runner approve --pipeline-id <version> --by reviewer
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from automation.base_agent import AgentResult, AgentStatus, BaseAgent
from downloader.download_agent import DownloadAgent
from etl.extract_agent import ExtractAgent
from incremental import IncrementalState
from parallel import ParallelRunner
from transform import run_transform
from view_builder import build_views
from release_builder import build_release
from etl.types import utc_now


@dataclass
class E2EResult:
    version: str
    status: str
    summary: str
    dry_run: bool = False
    stages_run: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    stage_results: dict[str, Any] = field(default_factory=dict)
    bundle_dir: str = ""
    record_count: int = 0
    elapsed_s: float = 0.0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class E2EPipeline(BaseAgent):
    """Atlas end-to-end pipeline agent (v2.0).

    Chains all stages with parallel workers and incremental state.
    """

    name = "e2e_pipeline"
    description = "End-to-end pipeline: download → etl → transform → views → release"

    def __init__(self, root: str | Path, config: dict[str, Any] | None = None) -> None:
        super().__init__(root, config)
        self.version = self.config.get("version") or "v0.3-e2e"
        self.source_ids: list[str] = list(self.config.get("source_ids") or [])
        self.max_workers: int = int(self.config.get("max_workers") or 4)
        self.dry_run: bool = bool(self.config.get("dry_run", False))
        self.force: bool = bool(self.config.get("force", False))
        self.limit: int | None = (
            int(self.config["limit"]) if self.config.get("limit") is not None else None
        )
        self.models: list[str] = list(
            self.config.get("models") or ["qwen", "llama", "deepseek"]
        )
        self.allow_staging: bool = bool(self.config.get("allow_staging", True))
        self.skip_download: bool = bool(self.config.get("skip_download", False))
        self.skip_etl: bool = bool(self.config.get("skip_etl", False))
        self.skip_transform: bool = bool(self.config.get("skip_transform", False))
        self.skip_views: bool = bool(self.config.get("skip_views", False))
        self.use_registry: bool = bool(self.config.get("use_registry", True))
        self._state = IncrementalState(self.root)
        self._runner = ParallelRunner(
            max_workers=self.max_workers,
            on_progress=self._on_progress,
        )
        self._progress_log: list[str] = []

    def execute(self, context: dict[str, Any] | None = None) -> AgentResult:
        t0 = time.monotonic()
        context = context or {}

        source_ids = list(context.get("source_ids") or self.source_ids)
        if not source_ids:
            source_ids = self._discover_sources()
        if not source_ids:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILED,
                summary="No source ids found — pass --source-id or ensure acquisition logs exist",
                errors=["no sources"],
            )

        result = E2EResult(
            version=self.version,
            status="passed",
            summary="",
            dry_run=self.dry_run,
            source_ids=source_ids,
            generated_at=utc_now(),
        )
        errors: list[str] = []
        warnings: list[str] = []

        # ── Stage 1: Download ────────────────────────────────────────
        if not self.skip_download:
            dl_result = self._run_download(source_ids, warnings)
            result.stage_results["download"] = dl_result
            result.stages_run.append("download")
            if dl_result.get("status") == "failed" and not self.dry_run:
                errors.append("download stage failed")

        # ── Stage 2: ETL (parallel per source) ───────────────────────
        if not self.skip_etl:
            pending_etl = self._pending(source_ids, "etl")
            if self.dry_run:
                result.stage_results["etl"] = {
                    "planned": pending_etl,
                    "skipped_incremental": len(source_ids) - len(pending_etl),
                }
            else:
                etl_pr = self._runner.run(self._etl_job, pending_etl)
                result.stage_results["etl"] = etl_pr.to_dict()
                errors.extend(
                    f"etl:{jr.source_id}: {jr.error}"
                    for jr in etl_pr.results if jr.status == "failed"
                )
            result.stages_run.append("etl")

        # ── Stage 3: Transform (parallel per source) ─────────────────
        if not self.skip_transform:
            pending_tr = self._pending(source_ids, "transform")
            if self.dry_run:
                result.stage_results["transform"] = {"planned": pending_tr}
            else:
                tr_pr = self._runner.run(self._transform_job, pending_tr)
                result.stage_results["transform"] = tr_pr.to_dict()
                errors.extend(
                    f"transform:{jr.source_id}: {jr.error}"
                    for jr in tr_pr.results if jr.status == "failed"
                )
            result.stages_run.append("transform")

        # ── Stage 4: Views ───────────────────────────────────────────
        if not self.skip_views:
            if self.dry_run:
                result.stage_results["views"] = {
                    "planned": True,
                    "version": self.version,
                    "models": self.models,
                }
            else:
                vr = build_views(
                    self.root,
                    version=self.version,
                    models=self.models,
                    source_ids=source_ids,
                    allow_staging=self.allow_staging,
                    limit=self.limit,
                )
                result.stage_results["views"] = vr.to_dict()
                errors.extend(vr.errors)
                warnings.extend(vr.warnings)
                if vr.status == "passed":
                    for sid in source_ids:
                        self._state.mark_done(sid, "views", metadata={"version": self.version})
            result.stages_run.append("views")

        # ── Stage 5: Release bundle ──────────────────────────────────
        if self.dry_run:
            result.stage_results["release"] = {
                "planned": True,
                "bundle_dir": str(self.root / "metadata" / "release_bundles" / self.version),
            }
        else:
            rr = build_release(
                self.root,
                version=self.version,
                source_ids=source_ids,
                view_version=self.version,
                allow_staging=self.allow_staging,
            )
            result.stage_results["release"] = rr.to_dict()
            result.bundle_dir = rr.bundle_dir
            result.record_count = rr.record_count
            errors.extend(rr.errors)
            warnings.extend(rr.warnings)
            if rr.status in {"passed"}:
                for sid in source_ids:
                    self._state.mark_done(sid, "release", metadata={"version": self.version})
        result.stages_run.append("release")

        result.elapsed_s = round(time.monotonic() - t0, 2)
        result.errors = errors
        result.warnings = warnings

        if errors and any(
            "failed" in e or "error" in e.lower()
            for e in errors
        ):
            result.status = "failed" if not result.bundle_dir else "partial"
        else:
            result.status = "passed"

        mode = "dry-run" if self.dry_run else "live"
        result.summary = (
            f"E2E [{mode}] {self.version}: "
            f"{len(source_ids)} sources, stages={'+'.join(result.stages_run)}, "
            f"records={result.record_count}, elapsed={result.elapsed_s}s"
        )
        if result.bundle_dir:
            result.summary += f", bundle={result.bundle_dir}"

        self._write_report(result)

        return AgentResult(
            agent_name=self.name,
            status=AgentStatus.PASSED if result.status in {"passed", "partial"} else AgentStatus.FAILED,
            summary=result.summary,
            data=result.to_dict(),
            errors=errors,
            warnings=warnings,
        )

    # ── stage helpers ─────────────────────────────────────────────────

    def _run_download(self, source_ids: list[str], warnings: list[str]) -> dict[str, Any]:
        pending = self._pending(source_ids, "download")
        if not pending:
            return {"status": "skipped", "message": "all sources already downloaded"}

        config: dict[str, Any] = {
            "mode": "dry-run" if self.dry_run else "download",
            "source_ids": pending,
            "use_registry": self.use_registry,
            "max_retries": 3,
            "timeout": 60,
        }
        if self.limit is not None:
            config["max_files"] = max(2, min(10, int(self.limit // 100) + 2))

        agent = DownloadAgent(self.root, config=config)
        result = agent.execute()
        payload = result.to_dict()
        payload["skipped_incremental"] = len(source_ids) - len(pending)

        if result.status == AgentStatus.PASSED and not self.dry_run:
            for sid in pending:
                chk = IncrementalState.checksum_for_download(self.root, sid)
                self._state.mark_done(sid, "download", checksum=chk)

        return payload

    def _etl_job(self, source_id: str) -> dict[str, Any]:
        config = {"source_ids": [source_id], "promote_atlas": True}
        if self.limit is not None:
            config["limit"] = self.limit
        agent = ExtractAgent(self.root, config=config)
        result = agent.execute()
        if result.status == AgentStatus.PASSED:
            chk = IncrementalState.checksum_for_etl(self.root, source_id)
            self._state.mark_done(source_id, "etl", checksum=chk)
        return result.to_dict()

    def _transform_job(self, source_id: str) -> dict[str, Any]:
        report = run_transform(self.root, source_id, limit=self.limit)
        if report.get("status") == "passed":
            self._state.mark_done(source_id, "transform")
        return report

    def _pending(self, source_ids: list[str], stage: str) -> list[str]:
        if self.force:
            return list(source_ids)
        return self._state.pending_sources(stage, source_ids)

    def _discover_sources(self) -> list[str]:
        """Discover source ids from acquisition logs, then registry."""
        log_dir = self.root / "metadata" / "acquisition_logs"
        if log_dir.exists():
            ids = sorted(
                p.name.removesuffix(".acquisition.json")
                for p in log_dir.glob("*.acquisition.json")
            )
            if ids:
                return ids
        if self.use_registry:
            reg_path = self.root / "metadata" / "source_registry.json"
            if reg_path.exists():
                reg = json.loads(reg_path.read_text(encoding="utf-8"))
                return sorted(
                    s["id"]
                    for s in reg.get("sources", [])
                    if s.get("status") in {"accepted", "review"} and s.get("id")
                )
        return []

    def _on_progress(self, source_id: str, event: str, payload: Any) -> None:
        msg = f"[{event}] {source_id}"
        self._progress_log.append(msg)

    def _write_report(self, result: E2EResult) -> None:
        out_dir = self.root / "metadata" / "e2e_reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{self.version}.json"
        path.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
