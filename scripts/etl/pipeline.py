#!/usr/bin/env python3
"""ETL pipeline — Extract → Normalize → Clean → (optional) Atlas promote.

Reads cached download artifacts for a source, writes staging outputs under
``metadata/etl/<source_id>/``. Never writes to curated/, review_queue/,
training_views/, or immutable raw trees.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from downloader.cache import CacheManager

from .extractors import build_extractors, select_extractor
from .normalizer import normalize_record, to_atlas_record
from .cleaners import run_cleaners
from .types import CanonicalRecord, RawRecord, utc_now, write_jsonl


@dataclass
class EtlResult:
    source_id: str
    status: str
    summary: str
    extracted: int = 0
    normalized: int = 0
    cleaned: int = 0
    atlas_records: int = 0
    dropped: int = 0
    output_dir: str = ""
    files_processed: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_registry(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "metadata" / "source_registry.json"
    if not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {str(s.get("id")): s for s in doc.get("sources", []) if s.get("id")}


def _download_log(root: Path, source_id: str) -> dict[str, Any] | None:
    path = root / "metadata" / "download_logs" / f"{source_id}.download.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_cache_files(
    cache: CacheManager,
    source_id: str,
    download_log: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Return list of {source_ref, path, filename, format_hint} for ETL."""
    files: list[dict[str, Any]] = []
    if download_log:
        for entry in download_log.get("entries") or []:
            ref = entry.get("source_ref")
            if not ref:
                continue
            cached = cache.get(ref)
            if cached is None:
                continue
            path = cache.object_path(cached.checksum)
            filename = (cached.metadata or {}).get("filename") or Path(path).name
            files.append(
                {
                    "source_ref": ref,
                    "path": path,
                    "filename": filename,
                    "format_hint": _hint_from_name(filename),
                    "checksum": cached.checksum,
                }
            )
        # Also use files[] metadata when entries lack filename
        if not files:
            for f in download_log.get("files") or []:
                ref = f.get("source_ref")
                if not ref:
                    continue
                cached = cache.get(ref)
                if cached is None:
                    continue
                path = cache.object_path(cached.checksum)
                filename = f.get("filename") or Path(path).name
                files.append(
                    {
                        "source_ref": ref,
                        "path": path,
                        "filename": filename,
                        "format_hint": _hint_from_name(filename),
                        "checksum": cached.checksum,
                    }
                )

    # Fallback: scan cache index for source_id prefix
    if not files:
        prefix = f":{source_id}"
        for entry in cache.list_entries():
            if source_id in entry.source_ref.split(":"):
                path = cache.object_path(entry.checksum)
                filename = (entry.metadata or {}).get("filename") or Path(path).name
                files.append(
                    {
                        "source_ref": entry.source_ref,
                        "path": path,
                        "filename": filename,
                        "format_hint": _hint_from_name(filename),
                        "checksum": entry.checksum,
                    }
                )
    return files


def _hint_from_name(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".parquet") or ".parquet" in lower:
        return "parquet"
    if lower.endswith(".jsonl"):
        return "jsonl"
    if lower.endswith(".json"):
        return "json"
    if lower.endswith(".md"):
        return "markdown"
    if lower.endswith((".html", ".htm")):
        return "html"
    return ""


def run_etl_for_source(
    root: str | Path,
    source_id: str,
    *,
    limit: int | None = None,
    promote_atlas: bool = True,
    skip_meta_files: bool = True,
) -> EtlResult:
    root = Path(root).resolve()
    cache = CacheManager(root)
    registry = _load_registry(root)
    source = registry.get(source_id, {"id": source_id, "name": source_id})
    download_log = _download_log(root, source_id)

    out_dir = root / "metadata" / "etl" / source_id
    out_dir.mkdir(parents=True, exist_ok=True)

    result = EtlResult(
        source_id=source_id,
        status="passed",
        summary="",
        output_dir=str(out_dir),
    )

    files = _resolve_cache_files(cache, source_id, download_log)
    if not files:
        result.status = "failed"
        result.errors.append(
            f"no cached files for source '{source_id}' — run download first"
        )
        result.summary = "No cached files to extract"
        return result

    extractors = build_extractors()
    raw_records: list[RawRecord] = []
    meta_skip = {".gitattributes", "readme.md", "eval.yaml", "license", "license.txt"}

    for info in files:
        filename = info["filename"]
        base = Path(filename).name.lower()
        if skip_meta_files and (base in meta_skip or base.startswith(".")):
            result.warnings.append(f"skipped meta file: {filename}")
            continue

        path = Path(info["path"])
        extractor = select_extractor(path, extractors, format_hint=info["format_hint"])
        if extractor is None:
            # Try HTML sniff for extensionless doc pages
            extractor = select_extractor(path, extractors, format_hint="html")
            if extractor is None or not extractor.supports(path, format_hint="html"):
                result.warnings.append(f"no extractor for {filename}")
                continue

        try:
            ctx: dict[str, Any] = {}
            if limit is not None:
                ctx["limit"] = limit
            extracted = extractor.extract(
                path,
                source_ref=info["source_ref"],
                context=ctx,
            )
        except Exception as exc:
            result.errors.append(f"{filename}: {exc}")
            continue

        # Apply global limit across files if set
        if limit is not None:
            remaining = limit - len(raw_records)
            if remaining <= 0:
                break
            extracted = extracted[:remaining]

        raw_records.extend(extracted)
        result.files_processed.append(
            {
                "filename": filename,
                "extractor": extractor.name,
                "records": len(extracted),
                "source_ref": info["source_ref"],
            }
        )

    result.extracted = len(raw_records)
    write_jsonl(out_dir / "extracted.jsonl", [r.to_dict() for r in raw_records])

    if not raw_records:
        result.status = "failed" if result.errors else "skipped"
        result.summary = "No records extracted"
        _write_report(out_dir, result)
        return result

    # Normalize
    canonical: list[CanonicalRecord] = []
    for raw in raw_records:
        canonical.append(
            normalize_record(
                raw,
                source_id=source_id,
                source_name=source.get("name") or source_id,
                license=source.get("license") or "unknown",
                category=source.get("category") or "",
                subcategory=source.get("subcategory_hint") or "general",
            )
        )
        # attach url into metadata for promotion
        canonical[-1].metadata["source_url"] = source.get("url") or ""

    result.normalized = len(canonical)
    write_jsonl(out_dir / "normalized.jsonl", [c.to_dict() for c in canonical])

    # Clean
    cleaned = run_cleaners(canonical)
    result.cleaned = len(cleaned.records)
    result.dropped = len(cleaned.dropped)
    result.stats["clean"] = cleaned.stats
    write_jsonl(out_dir / "cleaned.jsonl", [c.to_dict() for c in cleaned.records])
    (out_dir / "dropped.json").write_text(
        json.dumps(cleaned.dropped, indent=2) + "\n", encoding="utf-8"
    )

    # Promote toward Atlas staging records (still unverified)
    atlas_rows: list[dict[str, Any]] = []
    if promote_atlas:
        for idx, rec in enumerate(cleaned.records, start=1):
            atlas_rows.append(to_atlas_record(rec, seq=idx))
        result.atlas_records = len(atlas_rows)
        write_jsonl(out_dir / "atlas_staging.jsonl", atlas_rows)

    if result.errors and not cleaned.records:
        result.status = "failed"
        result.summary = f"ETL failed for {source_id}"
    else:
        result.status = "passed"
        result.summary = (
            f"ETL {source_id}: extracted={result.extracted} "
            f"cleaned={result.cleaned} atlas_staging={result.atlas_records} "
            f"dropped={result.dropped}"
        )

    result.stats.update(
        {
            "generated_at": utc_now(),
            "source": {
                "id": source_id,
                "name": source.get("name"),
                "license": source.get("license"),
                "category": source.get("category"),
            },
            "limit": limit,
        }
    )
    _write_report(out_dir, result)
    return result


def _write_report(out_dir: Path, result: EtlResult) -> None:
    (out_dir / "report.json").write_text(
        json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ----------------------------------------------------------------------
# Universal Scheduler integration (Phase 4)
# ----------------------------------------------------------------------


def etl_task(task) -> dict:
    """Universal Scheduler worker: run ETL for one source.

    Module-level so it can be pickled into process workers. Task carries
    source_id in task.input (or task.source), and options in task.extra.
    Raises on failure so the scheduler can retry and mark the registry entry.
    """
    source_id = task.input or task.source
    extra = getattr(task, "extra", {}) or {}
    root = Path(extra.get("root", "."))
    limit = extra.get("limit")
    promote = bool(extra.get("promote_atlas", True))
    result = run_etl_for_source(
        root,
        source_id,
        limit=limit,
        promote_atlas=promote,
    )
    if result.status == "failed":
        raise RuntimeError(f"ETL failed for {source_id}: {'; '.join(result.errors)}")
    return result.to_dict()


def plan_etl_tasks(
    source_ids: list[str],
    root: str | Path,
    *,
    limit: int | None = None,
    promote_atlas: bool = True,
) -> list:
    """Build ETL Tasks (one per source) for the Universal Scheduler."""
    from parallel.models import Task

    return [
        Task(
            task_id=f"etl:{sid}",
            source=sid,
            operation="run_etl_for_source",
            input=sid,
            extra={
                "root": str(Path(root).resolve()),
                "limit": limit,
                "promote_atlas": promote_atlas,
            },
        )
        for sid in sorted(source_ids)
    ]


def run_etl_scheduler(
    root: str | Path,
    source_ids: list[str],
    *,
    limit: int | None = None,
    promote_atlas: bool = True,
    registry_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Run ETL for many sources through the Universal Scheduler.

    Returns a list of EtlResult dicts, one per source, sorted by source_id
    (deterministic). Falls back to the sequential loop on scheduler error.
    """
    root_p = Path(root).resolve()
    tasks = plan_etl_tasks(source_ids, root_p, limit=limit, promote_atlas=promote_atlas)
    try:
        from parallel.scheduler import Scheduler

        reg_root = registry_root or (root_p / "metadata" / "pipeline_state")
        sched = Scheduler(
            "etl",
            registry_root=str(reg_root),
            workers=None,  # adaptive
            pool="process",
            max_retries=2,
        )
        print(f"[etl] scheduler: {len(tasks)} source tasks, {sched.workers} adaptive workers")
        results: list[dict[str, Any]] = []
        trs = sched.run(tasks, etl_task)
        for tr in trs:
            if tr.status == "completed" and isinstance(tr.result, dict):
                results.append(tr.result)
            elif tr.status == "failed":
                results.append({
                    "source_id": tr.task_id.split(":", 1)[1],
                    "status": "failed",
                    "summary": f"scheduler task failed: {tr.error}",
                    "errors": [tr.error],
                })
            # skipped: completed in a prior run — reload report.json from disk
            elif tr.status == "skipped":
                sid = tr.task_id.split(":", 1)[1]
                report_path = root_p / "metadata" / "etl" / sid / "report.json"
                try:
                    results.append(json.loads(report_path.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError):
                    results.append({
                        "source_id": sid,
                        "status": "skipped",
                        "summary": "completed in prior run (report.json missing)",
                        "errors": [],
                    })
        return results
    except Exception as sched_exc:
        print(f"[etl] scheduler unavailable ({sched_exc}); falling back to sequential", file=sys.stderr)
        results = []
        for sid in sorted(source_ids):
            etl = run_etl_for_source(root_p, sid, limit=limit, promote_atlas=promote_atlas)
            results.append(etl.to_dict())
        return results
