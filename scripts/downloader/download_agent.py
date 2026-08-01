#!/usr/bin/env python3
"""DownloadAgent v1.6 — orchestrate source adapters + cache for acquired packets.

Reads acquisition logs (or the source registry directly), routes each source to
the correct SourceAdapter, and stores artifacts under ``raw/.cache/``.

Modes:
  - dry-run: plan downloads without writing cache objects (Hub metadata may be fetched)
  - download: perform downloads through CacheManager (resume + checksum + retry)

Safety:
  - Never writes to curated/, review_queue/, training_views/
  - Never mutates immutable raw trees (external/generated/…)
  - Only writes under raw/.cache/ and metadata/download_logs/
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from automation.base_agent import AgentResult, AgentStatus, BaseAgent

from .adapters import build_adapters, select_adapter
from .adapters.base import DownloadResult, DownloadStatus
from .cache import CacheManager


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


class DownloadAgent(BaseAgent):
    name = "download_agent"
    description = "Download acquired sources into the content-addressable cache"

    def __init__(self, root: str | Path, config: dict[str, Any] | None = None) -> None:
        super().__init__(root, config)
        self.mode = (self.config.get("mode") or "dry-run").strip().lower()
        if self.mode not in {"dry-run", "download"}:
            raise ValueError("mode must be 'dry-run' or 'download'")

        cache_dir = self.config.get("cache_dir")
        self.cache = CacheManager(
            self.root,
            cache_dir=cache_dir,
            max_retries=int(self.config.get("max_retries", 3)),
            timeout=float(self.config.get("timeout", 60)),
            backoff_base=float(self.config.get("backoff_base", 0.5)),
        )
        self.adapters = build_adapters(self.cache, config=self.config)
        self._log_dir = self.root / "metadata" / "download_logs"
        self._registry_path = self._resolve_path(
            "registry_path", self.root / "metadata" / "source_registry.json"
        )
        self._acquisition_log_dir = self._resolve_path(
            "acquisition_log_dir", self.root / "metadata" / "acquisition_logs"
        )

    def execute(self, context: dict[str, Any] | None = None) -> AgentResult:
        sources, source_errors = self._load_sources(context)
        if source_errors and not sources:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILED,
                summary="No downloadable sources found",
                errors=source_errors,
            )

        planned: list[dict[str, Any]] = []
        downloaded: list[dict[str, Any]] = []
        cached: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        dry_run = self.mode == "dry-run"
        source_filter = set(self.config.get("source_ids") or [])

        # Universal Scheduler path (Phase 5B): deterministic per-source tasks
        # (download:<sid>:<url_hash>) with I/O-aware worker limits, TaskRegistry
        # resume/retry, and sequential fallback (identical behavior).
        # Cache handling, HTTP Range resume, checksum verification, and adapter
        # logic are unchanged (downloader/scheduler_tasks.py is orchestration
        # only).
        try:
            from .scheduler_tasks import run_download_scheduler

            planned_sources = []
            for source in sources:
                sid = str(source.get("id") or source.get("source_id") or "")
                if source_filter and sid not in source_filter:
                    skipped.append({"source_id": sid, "reason": "filtered by source_ids"})
                    continue
                adapter = select_adapter(source, self.adapters)
                if adapter is None:
                    skipped.append({
                        "source_id": sid,
                        "reason": "no adapter supports this source",
                        "url": source.get("url"),
                    })
                    continue
                planned_sources.append(source)
                planned.append({
                    "source_id": sid,
                    "adapter": adapter.name,
                    "url": source.get("url"),
                    "name": source.get("name"),
                })

            payloads = run_download_scheduler(
                self.root,
                planned_sources,
                self.adapters,
                self.cache,
                self._write_download_log,
                dry_run=dry_run,
            )
            for payload in payloads:
                status = payload.get("status", "")
                if status == "failed":
                    failed.append(payload)
                elif status == "cached":
                    cached.append(payload)
                elif status in ("downloaded", "planned"):
                    downloaded.append(payload)
                else:
                    skipped.append(payload)
        except Exception as sched_exc:
            # Sequential fallback (original behavior) on any scheduler error.
            print(f"[downloader] scheduler unavailable ({sched_exc}); falling back to sequential", file=sys.stderr)
            for source in sources:
                sid = str(source.get("id") or source.get("source_id") or "")
                if source_filter and sid not in source_filter:
                    skipped.append({"source_id": sid, "reason": "filtered by source_ids"})
                    continue

                adapter = select_adapter(source, self.adapters)
                if adapter is None:
                    skipped.append(
                        {
                            "source_id": sid,
                            "reason": "no adapter supports this source",
                            "url": source.get("url"),
                        }
                    )
                    continue

                planned.append(
                    {
                        "source_id": sid,
                        "adapter": adapter.name,
                        "url": source.get("url"),
                        "name": source.get("name"),
                    }
                )

                try:
                    result = adapter.download(source, dry_run=dry_run)
                except Exception as exc:
                    failed.append(
                        {
                            "source_id": sid,
                            "adapter": adapter.name,
                            "error": str(exc),
                        }
                    )
                    continue

                payload = {
                    "source_id": sid,
                    "adapter": adapter.name,
                    "status": result.status.value,
                    "summary": result.summary,
                    "url": result.url,
                    "files": result.files,
                    "errors": result.errors,
                    "warnings": result.warnings,
                    "entries": [e.to_dict() for e in result.entries],
                }

                if result.status == DownloadStatus.FAILED:
                    failed.append(payload)
                elif result.status == DownloadStatus.CACHED:
                    cached.append(payload)
                elif result.status in {DownloadStatus.DOWNLOADED, DownloadStatus.PLANNED}:
                    downloaded.append(payload)
                else:
                    skipped.append(payload)

                if self.mode == "download" and result.status != DownloadStatus.FAILED:
                    self._write_download_log(sid, result)

        stats = {
            "planned": len(planned),
            "downloaded": len(downloaded),
            "cached": len(cached),
            "skipped": len(skipped),
            "failed": len(failed),
            "cache": self.cache.stats(),
        }

        if failed and not downloaded and not cached and self.mode == "download":
            status = AgentStatus.FAILED
            summary = f"All downloads failed ({len(failed)} failure(s))"
        elif failed:
            status = AgentStatus.PASSED
            summary = (
                f"Completed with {len(failed)} failure(s); "
                f"{len(downloaded) + len(cached)} ok, {len(skipped)} skipped"
            )
        elif self.mode == "dry-run":
            status = AgentStatus.PASSED
            summary = f"Dry-run complete: {len(planned)} planned, {len(skipped)} skipped"
        else:
            status = AgentStatus.PASSED
            summary = (
                f"Downloaded/cached {len(downloaded) + len(cached)} source(s); "
                f"skipped {len(skipped)}"
            )

        return AgentResult(
            agent_name=self.name,
            status=status,
            summary=summary,
            data={
                "mode": self.mode,
                "planned": planned,
                "downloaded": downloaded,
                "cached": cached,
                "skipped": skipped,
                "failed": failed,
                "stats": stats,
            },
            errors=[f"{f.get('source_id')}: {f.get('error') or f.get('summary')}" for f in failed],
            warnings=source_errors,
        )

    # ── source loading ────────────────────────────────────────────────

    def _load_sources(
        self, context: dict[str, Any] | None
    ) -> tuple[list[dict[str, Any]], list[str]]:
        errors: list[str] = []
        if context and context.get("sources"):
            return list(context["sources"]), errors

        registry = self._load_registry()
        # Prefer acquired packets when logs exist
        acquired_ids = self._load_acquired_source_ids()
        if acquired_ids:
            sources = [registry[sid] for sid in acquired_ids if sid in registry]
            missing = [sid for sid in acquired_ids if sid not in registry]
            for sid in missing:
                errors.append(f"acquisition log source_id '{sid}' not in registry")
            return sources, errors

        # Fallback: all accepted/review registry sources (explicit opt-in)
        if self.config.get("use_registry", False):
            sources = [
                s
                for s in registry.values()
                if (s.get("status") or "").lower() in {"accepted", "review"}
            ]
            return sources, errors

        errors.append(
            "no acquisition logs found; pass context.sources or set use_registry=true"
        )
        return [], errors

    def _load_registry(self) -> dict[str, dict[str, Any]]:
        if not self._registry_path.exists():
            return {}
        doc = json.loads(self._registry_path.read_text(encoding="utf-8"))
        return {str(s.get("id")): s for s in doc.get("sources", []) if s.get("id")}

    def _load_acquired_source_ids(self) -> list[str]:
        log_dir = self._acquisition_log_dir
        if not log_dir.exists():
            return []
        ids: list[str] = []
        for path in sorted(log_dir.glob("*.acquisition.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            sid = doc.get("source_id") or doc.get("packet_id")
            if sid:
                ids.append(str(sid))
        return ids

    def _write_download_log(self, source_id: str, result: DownloadResult) -> None:
        self._log_dir.mkdir(parents=True, exist_ok=True)
        path = self._log_dir / f"{source_id}.download.json"
        doc = {
            "source_id": source_id,
            "adapter": result.adapter,
            "status": result.status.value,
            "url": result.url,
            "timestamp": _ts(),
            "summary": result.summary,
            "files": result.files,
            "entries": [e.to_dict() for e in result.entries],
            "errors": result.errors,
            "warnings": result.warnings,
        }
        path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _resolve_path(self, config_key: str, default: Path) -> Path:
        value = self.config.get(config_key)
        if value is None:
            return default
        path = Path(value)
        return path if path.is_absolute() else self.root / path
