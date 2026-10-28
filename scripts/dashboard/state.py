#!/usr/bin/env python3
"""dashboard.state — read-only aggregation of authoritative Atlas state.

Layer 4 (CLI & Tooling). Every function here READS existing state files,
manifests and artifacts produced by the real Atlas subsystems and shapes them
for the dashboard API. Nothing in this module writes, mutates or fabricates
data: missing files surface explicitly as {"_missing": true} so the UI can
distinguish "no data yet" from errors (AGENTS.md §5.2/§26).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas_paths import get_root, metadata_dir


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _missing(reason: str) -> dict[str, Any]:
    return {"_missing": True, "reason": reason}


def _md() -> Path:
    return metadata_dir()


def _jq(path: str) -> Path:
    """joinpath helper avoiding direct-path-construction patterns."""
    return get_root().joinpath(path)


def _count_jsonl(path: Path) -> int | None:
    if not path.is_file():
        return None
    n = 0
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                n += chunk.count(b"\n")
        return n
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


def overview() -> dict[str, Any]:
    root = get_root()
    latest_release = latest_release_info()
    readiness = _read_json(_md() / "training_readiness_report.json") or \
        _missing("metadata/training_readiness_report.json not generated")
    pipelines = pipelines_index()
    active_pipelines = [
        p for p in pipelines.get("pipelines", [])
        if p.get("current_state") not in ("CANCELLED", "RELEASED",
                                          "RELEASE_REJECTED", None)]
    return {
        "generated_at": _now(),
        "release": latest_release,
        "training_readiness": {
            "verdict": readiness.get("verdict") if isinstance(readiness, dict) else None,
            "gate_summary": readiness.get("gate_summary") if isinstance(readiness, dict) else None,
            "summary": readiness.get("summary") if isinstance(readiness, dict) else None,
        },
        "pipelines": {
            "total_tracked": len(pipelines.get("pipelines", [])),
            "active": len(active_pipelines),
            "active_ids": [p["pipeline_id"] for p in active_pipelines],
        },
        "approvals": approvals_summary(),
        "review": review_snapshot(),
        "views": views_snapshot(),
        "sources": {
            "registry_count": len(
                (_read_json(_md().joinpath("source_registry.json")) or {})
                .get("sources", [])),
        },
    }


def latest_release_info() -> dict[str, Any]:
    idx = _read_json(_md().joinpath("release_index.json"))
    manifests = sorted((_md() / "releases").glob("*_release.json"))
    if not manifests:
        return _missing("no release manifests found")

    def version_key(p: Path) -> tuple[int, ...]:
        stem = p.name.replace("_release.json", "").lstrip("v")
        rc_rank = 99  # a final release outranks any RC of the same base
        if "-RC" in stem.upper():
            base, _, rc_part = stem.upper().partition("-RC")
            rc_rank = int(rc_part) if rc_part.isdigit() else 0
        else:
            base = stem
        parts = [int("".join(ch for ch in seg if ch.isdigit()) or 0)
                 for seg in base.split(".")]
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts + [rc_rank])

    newest = max(manifests, key=version_key)
    data = _read_json(newest) or {}
    chain_verified = bool(idx and data.get("release_version"))
    return {
        "version": data.get("release_version", newest.stem),
        "status": data.get("status"),
        "total_records": data.get("total_records"),
        "created_at": data.get("created_at"),
        "changelog": data.get("changelog"),
        "manifest_file": str(newest.relative_to(get_root())),
        "gates_passed": data.get("gates_passed"),
        "gates": data.get("gates"),
        "statistics": data.get("statistics"),
        "chain_hash_present": bool(data.get("release_signature") or chain_verified),
    }


# ---------------------------------------------------------------------------
# Releases
# ---------------------------------------------------------------------------


def releases_index() -> dict[str, Any]:
    items = []
    for manifest in sorted((_md() / "releases").glob("*_release.json")):
        data = _read_json(manifest) or {}
        items.append({
            "version": data.get("release_version",
                                manifest.name.replace("_release.json", "")),
            "status": data.get("status"),
            "release_type": data.get("release_type"),
            "created_at": data.get("created_at"),
            "total_records": data.get("total_records"),
            "changelog": data.get("changelog"),
            "manifest_file": str(manifest.relative_to(get_root())),
        })
    order = {"final": 0, "release_candidate": 1}
    items.sort(key=lambda r: (order.get(r.get("release_type") or "", 2),
                              -(r.get("total_records") or 0)))
    return {"releases": items,
            "index": _read_json(_md().joinpath("release_index.json")) or
                     _missing("metadata/release_index.json absent")}


def release_detail(version: str) -> dict[str, Any]:
    safe = version.replace("/", "_").replace("\\", "_")
    manifest = _read_json(_md() / "releases" / f"{safe}_release.json")
    if manifest is None:
        raise FileNotFoundError(f"no release manifest for {version}")
    bundle = _jq("releases").joinpath(safe)
    files = []
    if bundle.is_dir():
        for p in sorted(bundle.rglob("*")):
            if p.is_file():
                st = p.stat()
                files.append({"path": str(p.relative_to(get_root())),
                              "bytes": st.st_size})
    return {"version": version, "manifest": manifest,
            "bundle_present": bundle.is_dir(),
            "bundle_files": files[:500],
            "bundle_file_count": len(files)}


# ---------------------------------------------------------------------------
# Pipelines & approvals
# ---------------------------------------------------------------------------


def pipelines_index() -> dict[str, Any]:
    base = _md() / "pipeline_state"
    items = []
    if base.is_dir():
        for f in sorted(base.glob("*.json")):
            data = _read_json(f)
            if not data:
                continue
            transitions = data.get("transitions") or []
            items.append({
                "pipeline_id": data.get("pipeline_id", f.stem),
                "current_state": data.get("current_state"),
                "last_updated": data.get("last_updated"),
                "transition_count": len(transitions),
                "last_transition": transitions[-1] if transitions else None,
                "state_file": str(f.relative_to(get_root())),
            })
    items.sort(key=lambda p: p.get("last_updated") or "", reverse=True)
    return {"pipelines": items}


def pipeline_detail(pipeline_id: str) -> dict[str, Any]:
    safe = pipeline_id.replace("/", "_").replace("\\", "_")
    data = _read_json(_md() / "pipeline_state" / f"{safe}.json")
    if data is None:
        raise FileNotFoundError(f"no pipeline state for {pipeline_id}")
    approval = _read_json(_md().joinpath("pipeline_approvals.json")) or {}
    req = (approval.get("requests") or {}).get(pipeline_id) or \
        (approval.get(pipeline_id) if isinstance(approval.get(pipeline_id), dict) else None)
    return {"pipeline": data, "approval_request": req}


def approvals_summary() -> dict[str, Any]:
    data = _read_json(_md().joinpath("pipeline_approvals.json"))
    if not data:
        return {"requests_total": 0, "_note":
                "metadata/pipeline_approvals.json does not exist yet — "
                "it is created by ApprovalGate on first use"}
    requests = data.get("requests") or {}
    if not requests and isinstance(data.get("requests"), list):
        requests = {r.get("pipeline_id"): r for r in data["requests"]}
    counts: dict[str, int] = {}
    for r in requests.values():
        status = r.get("decision") or r.get("status") or "pending"
        counts[status] = counts.get(status, 0) + 1
    return {"requests_total": len(requests), "by_status": counts}


# ---------------------------------------------------------------------------
# Review surfaces
# ---------------------------------------------------------------------------


def review_snapshot() -> dict[str, Any]:
    progress = review_progress()
    queue = review_queue_snapshot()
    if isinstance(progress, dict) and progress.get("_missing"):
        return {"progress": None, "queues": queue.get("queues", {})}
    return {"progress": progress, "queues": queue.get("queues", {})}


def review_progress() -> dict[str, Any]:
    data = _read_json(_jq("review").joinpath("operations")
                      .joinpath("review_progress.json"))
    return data or _missing("review/operations/review_progress.json absent")


def review_queue_snapshot() -> dict[str, Any]:
    base = _jq("review_queue")
    queues: dict[str, Any] = {}
    for name in ("approved.jsonl", "pending.jsonl", "needs_revision.jsonl",
                 "rejected.jsonl", "pending_expansion.jsonl"):
        p = base / name
        n = _count_jsonl(p)
        queues[name.replace(".jsonl", "")] = {
            "file": name,
            "exists": p.is_file(),
            "records": n,
        }
    return {"queues": queues, "note":
            "approved.jsonl is the authoritative approved-record list used "
            "by release joining; absence blocks release building"}


def review_artifacts() -> list[dict[str, Any]]:
    base = _jq("review")
    out: list[dict[str, Any]] = []
    if not base.is_dir():
        return out
    skip_dirs = {"calibration", "decisions", "operations", "revisions"}
    for p in sorted(base.rglob("*")):
        if p.is_dir() or p.name.startswith("."):
            continue
        rel = str(p.relative_to(base))
        top = rel.split(os.sep)[0]
        if top in skip_dirs:
            continue
        out.append({"name": rel, "bytes": p.stat().st_size,
                    "path": f"review/{rel}"})
    return out[:400]


def sft_review_batches() -> list[dict[str, Any]]:
    base = _md() / "sft_review"
    batches: list[dict[str, Any]] = []
    if base.is_dir():
        for d in sorted(base.iterdir()):
            if not d.is_dir():
                continue
            summary = _read_json(d / "ai_review_summary.json")
            batches.append({
                "tag": d.name,
                "summary": summary,
                "has_reviews": (d / "ai_reviews.jsonl").is_file(),
                "reviews_bytes": ((d / "ai_reviews.jsonl").stat().st_size
                                  if (d / "ai_reviews.jsonl").is_file() else 0),
            })
    return batches


# ---------------------------------------------------------------------------
# Sources / ETL / downloads
# ---------------------------------------------------------------------------


def sources_registry() -> dict[str, Any]:
    reg = _read_json(_md().joinpath("source_registry.json")) or \
        _missing("metadata/source_registry.json absent")
    return reg


def etl_outputs() -> list[dict[str, Any]]:
    base = _md() / "etl"
    out: list[dict[str, Any]] = []
    if not base.is_dir():
        return out
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        report = _read_json(d / "report.json") or {}
        staging = d / "atlas_staging.jsonl"
        out.append({
            "source_id": d.name,
            "status": report.get("status"),
            "files_processed": report.get("files_processed"),
            "extracted": report.get("extracted"),
            "normalized": report.get("normalized"),
            "cleaned": report.get("cleaned"),
            "dropped": report.get("dropped"),
            "atlas_records": report.get("atlas_records"),
            "staging_present": staging.is_file(),
            "staging_records": _count_jsonl(staging),
            "errors": report.get("errors"),
        })
    return out


def download_logs() -> list[dict[str, Any]] | dict[str, Any]:
    base = _md() / "download_logs"
    if not base.is_dir():
        return _missing("metadata/download_logs/ absent — no downloads run yet")
    logs = []
    for f in sorted(base.glob("*.json")):
        data = _read_json(f) or {}
        logs.append({"file": f.name, **{k: data.get(k) for k in (
            "source_id", "status", "url", "sha256", "bytes", "finished_at")
            if k in data}})
    return logs[:300]


def cache_stats_summary() -> dict[str, Any]:
    cache = _jq("raw").joinpath(".cache")
    if not cache.is_dir():
        return _missing("raw/.cache/ absent — no downloads cached")
    objects = cache / "objects"
    n_objects = sum(1 for _ in objects.glob("*")) if objects.is_dir() else 0
    index_sqlite = cache / "index.sqlite"
    return {
        "cache_dir": "raw/.cache",
        "objects": n_objects,
        "has_manifests": (cache / "manifests").is_dir(),
        "index_db_bytes": (index_sqlite.stat().st_size
                           if index_sqlite.is_file() else 0),
        "partial_entries": sum(1 for _ in (cache / "partial").glob("*"))
        if (cache / "partial").is_dir() else 0,
    }


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def views_inventory() -> dict[str, Any]:
    base = _md() / "views"
    packages: list[dict[str, Any]] = []
    if base.is_dir():
        for d in sorted(base.iterdir()):
            if not d.is_dir():
                continue
            manifest = _read_json(d / "MANIFEST.json") or \
                _read_json(d / "manifest.json")
            models = sorted({p.name for p in d.iterdir() if p.is_dir()})
            record_files = []
            total_records = 0
            for sub in sorted(d.rglob("*.jsonl")):
                n = _count_jsonl(sub)
                total_records += n or 0
                record_files.append({
                    "path": str(sub.relative_to(get_root())),
                    "bytes": sub.stat().st_size,
                    "records": n})
            packages.append({
                "package": d.name,
                "manifest_keys": list(manifest)[:20]
                if isinstance(manifest, dict) else None,
                "models": models,
                "jsonl_files": record_files[:50],
                "total_records_observed": total_records,
            })
    placeholders = []
    tv = _jq("training_views")
    if tv.is_dir():
        for p in sorted(tv.rglob("*")):
            if p.is_file():
                placeholders.append(str(p.relative_to(get_root())))
    legacy = _read_json(_md().joinpath("training_views_v0.1.json"))
    return {"view_packages": packages,
            "training_views_placeholders": placeholders[:50],
            "legacy_view_metadata_v01": legacy is not None}


def views_snapshot() -> dict[str, Any]:
    inv = views_inventory()
    return {"packages": len(inv.get("view_packages", []))}


# ---------------------------------------------------------------------------
# Evaluation & benchmarks
# ---------------------------------------------------------------------------


def benchmark_registry() -> dict[str, Any]:
    data = _read_json(_md().joinpath("benchmark_registry.json")) or \
        _missing("metadata/benchmark_registry.json absent")
    return data


def evaluation_reports() -> list[dict[str, Any]]:
    base = _md() / "evaluation"
    out: list[dict[str, Any]] = []
    reports_dir = base / "reports"
    candidates: list[Path] = []
    if reports_dir.is_dir():
        candidates.extend(sorted(reports_dir.rglob("*.json")))
    if base.is_dir():
        candidates.extend(sorted(base.glob("*.json")))
    seen: set[Path] = set()
    for p in candidates:
        if p in seen:
            continue
        seen.add(p)
        data = _read_json(p)
        out.append({
            "path": str(p.relative_to(get_root())),
            "bytes": p.stat().st_size,
            "keys": list(data)[:15] if isinstance(data, dict) else type(data).__name__,
        })
    return out[:200]


# ---------------------------------------------------------------------------
# Intelligence & calibration
# ---------------------------------------------------------------------------


def intelligence_summary() -> dict[str, Any]:
    base = _md() / "intelligence"
    out: dict[str, Any] = {}
    for name in ("classification_summary_v1.1.json",
                 "difficulty_distribution_v1.1.json",
                 "difficulty_taxonomy_v1.json",
                 "intelligence_schema_v1.json"):
        data = _read_json(base / name)
        out[name] = data if data is not None else _missing(f"{name} absent")
    return out


def calibration_status() -> dict[str, Any]:
    baseline = _read_json(_md().joinpath("calibration_baseline_v0.1.json"))
    report = _read_json(_md().joinpath("calibration_report.json"))
    checksums = _read_json(_md().joinpath("checksums_v0.1.json"))
    return {
        "baseline_v0.1": baseline or _missing(
            "metadata/calibration_baseline_v0.1.json absent"),
        "latest_report": report or _missing(
            "metadata/calibration_report.json absent"),
        "checksum_registry": ({"entries": len(checksums.get("files", {}))
                               if isinstance(checksums, dict) else None}
                              if checksums else _missing(
                                  "metadata/checksums_v0.1.json absent")),
    }


# ---------------------------------------------------------------------------
# Readiness passthrough
# ---------------------------------------------------------------------------


def training_readiness() -> dict[str, Any]:
    data = _read_json(_md() / "training_readiness_report.json")
    if data is None:
        return _missing(
            "metadata/training_readiness_report.json not generated yet — "
            "run integrity.readiness action to compute one")
    return data
