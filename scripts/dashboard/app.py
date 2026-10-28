#!/usr/bin/env python3
"""dashboard.app — Atlas Engineering Dashboard HTTP application.

Layer 4 (CLI & Tooling). Assembles the aiohttp application:

- JSON API under /api/* (read-only state aggregation + action submission)
- Static SPA served from scripts/dashboard/static/
- Security middleware: optional bearer token (ATLAS_DASHBOARD_TOKEN),
  strict headers, no-store on API responses
- Structured JSON errors; SafetyError → 400; missing state → explicit payloads

The application never executes browser-supplied shell input: all actions go
through dashboard.actions.build_argv(), and job execution happens on the
JobManager worker pool (never inside an event-loop handler).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from aiohttp import web

from . import safety as safety_mod
from .actions import build_argv, catalog, get_action
from atlas_paths import get_root
from .jobs import JobManager
from parallel.config import resolve_worker_count
from .safety import (
    MAX_PREVIEW_LINES,
    SafetyError as SafeErr,
    resolve_readable_path,
    tokens_equal,
)
from . import state as atlas_state

log = logging.getLogger("atlas.dashboard.app")

STATIC_DIR = Path(__file__).resolve().parent / "static"
DATA_SUBDIR = "dashboard"  # under metadata/ (approved write root)

JOB_MANAGER_KEY = web.AppKey("jobs", JobManager)


@web.middleware
async def security_headers(request: web.Request,
                           handler: Any) -> web.StreamResponse:
    response = await handler(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Content-Security-Policy",
                                "default-src 'self'; script-src 'self'; "
                                "style-src 'self'; connect-src 'self'; "
                                "img-src 'self' data:")
    if request.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    elif request.path == "/" or request.path.startswith("/static/"):
        # always revalidate SPA assets so code/HTML versions stay in sync
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


@web.middleware
async def auth_middleware(request: web.Request,
                          handler: Any) -> web.StreamResponse:
    token = os.environ.get("ATLAS_DASHBOARD_TOKEN")
    if token and request.path.startswith("/api/") \
            and not request.path.startswith("/api/health"):
        provided = None
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            provided = header[len("Bearer "):].strip()
        # allow query param for log downloads via browser? No — keep header-only.
        if not tokens_equal(provided, token):
            raise web.HTTPUnauthorized(
                text=json.dumps({"error": "unauthorized"}),
                content_type="application/json")
    return await handler(request)


@web.middleware
async def error_middleware(request: web.Request,
                           handler: Any) -> web.StreamResponse:
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except SafeErr as exc:
        return json_response({"error": "validation_failed",
                              "detail": str(exc)}, status=400)
    except FileNotFoundError as exc:
        return json_response({"error": "not_found",
                              "detail": str(exc)}, status=404)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # pragma: no cover — last-resort handler
        log.exception("unhandled error on %s %s",
                      request.method, request.path_qs)
        return json_response({"error": "internal_error",
                              "detail": f"{type(exc).__name__}: {exc}"},
                             status=500)


def json_response(data: Any, *, status: int = 200) -> web.Response:
    return web.json_response(data, status=status,
                             dumps=lambda d: json.dumps(d, indent=1,
                                                        default=str))


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def h_index(_request: web.Request) -> web.StreamResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


async def h_health(_request: web.Request) -> web.Response:
    mgr: JobManager = _request.app[JOB_MANAGER_KEY]
    return json_response({
        "status": "ok",
        "service": "atlas-engineering-dashboard",
        "active_jobs": mgr.active_count(),
        "repo_root": str(get_root()),
    })


async def h_overview(_request: web.Request) -> web.Response:
    return json_response(atlas_state.overview())


async def h_catalog(_request: web.Request) -> web.Response:
    return json_response({"actions": catalog()})


async def h_releases(_request: web.Request) -> web.Response:
    return json_response(atlas_state.releases_index())


async def h_release_detail(request: web.Request) -> web.Response:
    version = safety_mod.validate_version(request.match_info["version"])
    return json_response(atlas_state.release_detail(version))


async def h_pipelines(_request: web.Request) -> web.Response:
    return json_response(atlas_state.pipelines_index())


async def h_pipeline_detail(request: web.Request) -> web.Response:
    pid = safety_mod.safe_id(request.match_info["pipeline_id"])
    return json_response(atlas_state.pipeline_detail(pid))


async def h_approvals(_request: web.Request) -> web.Response:
    return json_response(atlas_state.approvals_summary())


async def h_review_progress(_request: web.Request) -> web.Response:
    return json_response(atlas_state.review_progress())


async def h_review_queue(_request: web.Request) -> web.Response:
    return json_response(atlas_state.review_queue_snapshot())


async def h_review_artifacts(_request: web.Request) -> web.Response:
    return json_response({"artifacts": atlas_state.review_artifacts()})


async def h_sft_batches(_request: web.Request) -> web.Response:
    return json_response({"batches": atlas_state.sft_review_batches()})


async def h_sources(_request: web.Request) -> web.Response:
    return json_response(atlas_state.sources_registry())


async def h_etl(_request: web.Request) -> web.Response:
    return json_response({"outputs": atlas_state.etl_outputs()})


async def h_downloads(_request: web.Request) -> web.Response:
    return json_response(atlas_state.download_logs())


async def h_cache(_request: web.Request) -> web.Response:
    return json_response(atlas_state.cache_stats_summary())


async def h_views(_request: web.Request) -> web.Response:
    return json_response(atlas_state.views_inventory())


async def h_benchmarks(_request: web.Request) -> web.Response:
    return json_response(atlas_state.benchmark_registry())


async def h_eval_reports(_request: web.Request) -> web.Response:
    return json_response({"reports": atlas_state.evaluation_reports()})


async def h_intelligence(_request: web.Request) -> web.Response:
    return json_response(atlas_state.intelligence_summary())


async def h_calibration(_request: web.Request) -> web.Response:
    return json_response(atlas_state.calibration_status())


async def h_readiness(_request: web.Request) -> web.Response:
    return json_response(atlas_state.training_readiness())


async def h_jobs(request: web.Request) -> web.Response:
    mgr: JobManager = request.app[JOB_MANAGER_KEY]
    limit = int(request.query.get("limit", "100"))
    limit = max(1, min(limit, 300))
    status = request.query.get("status") or None
    return json_response({"jobs": mgr.list_jobs(limit=limit, status=status)})


def _extract_cli_result(log_text: str) -> dict[str, Any] | None:
    """Extract the first top-level JSON document from a job log.

    automation_runner jobs run with --json, so their decision payloads
    (approval-gate rejections etc.) are recoverable verbatim from the log.
    """
    lines = log_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "{":
            start = i
            break
        if stripped.startswith("{") and stripped.endswith("}") \
                and len(stripped) > 2:
            try:
                doc = json.loads(stripped)
                return doc if isinstance(doc, dict) else None
            except ValueError:
                continue
    if start is None:
        return None
    depth = 0
    buf: list[str] = []
    for line in lines[start:]:
        buf.append(line)
        depth += line.count("{") - line.count("}")
        if depth <= 0:
            break
    try:
        doc = json.loads("\n".join(buf))
        return doc if isinstance(doc, dict) else None
    except ValueError:
        return None


async def h_job_detail(request: web.Request) -> web.Response:
    mgr: JobManager = request.app[JOB_MANAGER_KEY]
    job = mgr.get(request.match_info["job_id"])
    if not job:
        raise FileNotFoundError("no such job")
    payload = dict(job)
    if job["status"] in ("succeeded", "failed", "needs_attention",
                         "timeout", "cancelled", "interrupted"):
        log_text = mgr.log_tail(request.match_info["job_id"], max_bytes=256_000)
        cli_doc = _extract_cli_result(log_text)
        if cli_doc is not None:
            payload["cli_result"] = {
                "command": cli_doc.get("command"),
                "error": cli_doc.get("error"),
                "message": cli_doc.get("message"),
                "keys": sorted(k for k in cli_doc.keys()
                               if k not in ("command", "error", "message")),
            }
    return json_response(payload)


async def h_job_log(request: web.Request) -> web.Response:
    mgr: JobManager = request.app[JOB_MANAGER_KEY]
    tail = int(request.query.get("bytes", "64000"))
    tail = max(500, min(tail, 512_000))
    text = mgr.log_tail(request.match_info["job_id"], max_bytes=tail)
    return web.Response(text=text, content_type="text/plain")


async def h_job_cancel(request: web.Request) -> web.Response:
    mgr: JobManager = request.app[JOB_MANAGER_KEY]
    ok, message = mgr.cancel(request.match_info["job_id"])
    return json_response({"cancelled": ok, "detail": message},
                         status=200 if ok else 409)


async def h_action_run(request: web.Request) -> web.Response:
    action_id = request.match_info["action_id"]
    try:
        get_action(action_id)
    except KeyError:
        raise web.HTTPNotFound(
            text=json.dumps({"error": "unknown action", "action": action_id}),
            content_type="application/json")

    disabled = next((a for a in catalog() if a["id"] == action_id), {})
    if disabled and not disabled.get("enabled", True):
        return json_response(
            {"error": "action_disabled",
             "detail": disabled.get("disabled_reason")},
            status=409)

    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise SafeErr("request body must be a JSON object")

    argv = build_argv(action_id, payload)
    act = get_action(action_id)
    timeout_s = act["timeout_s"]
    requested_timeout = payload.get("timeout_s")
    if requested_timeout is not None:
        from .safety import validate_int
        timeout_s = validate_int(requested_timeout, "timeout_s", 5, 86400)
    mgr: JobManager = request.app[JOB_MANAGER_KEY]
    job = mgr.submit(action_id=action_id, title=act["title"], argv=argv,
                     danger=act["danger"], timeout_s=timeout_s,
                     params=payload)
    return json_response({"job": job}, status=202)


async def h_preview(request: web.Request) -> web.Response:
    rel = request.query.get("path", "")
    try:
        limit = int(request.query.get("limit", "50"))
        offset = max(0, int(request.query.get("offset", "0")))
    except ValueError:
        raise SafeErr("limit/offset must be integers")
    limit = max(1, min(limit, MAX_PREVIEW_LINES))
    path = resolve_readable_path(rel)
    lines: list[str] = []
    total_lines = 0
    truncated_file = False
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            total_lines += 1
            if offset <= i < offset + limit:
                lines.append(line.rstrip("\n"))
            if len(lines) >= limit and total_lines > offset + limit:
                break
    parsed: list[Any] = []
    is_jsonl = path.suffix == ".jsonl"
    if is_jsonl:
        for line in lines:
            try:
                parsed.append(json.loads(line))
            except ValueError:
                parsed.append(line)
    stat = path.stat()
    return json_response({
        "path": rel,
        "size_bytes": stat.st_size,
        "returned": len(lines),
        "offset": offset,
        "is_jsonl": is_jsonl,
        "records": parsed if is_jsonl else lines,
    })


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(*, data_dir: Path | None = None,
               worker_count: int | None = None) -> web.Application:
    root = get_root()
    if data_dir is None:
        data_dir = atlas_state._md().joinpath(DATA_SUBDIR)
    if worker_count is None:
        resolved = resolve_worker_count("dashboard")
        worker_count = int(resolved) if isinstance(resolved, (int, float)) \
            else 2
        worker_count = max(1, min(worker_count, 4))

    app = web.Application(middlewares=[security_headers, auth_middleware,
                                       error_middleware])

    mgr = JobManager(data_dir=data_dir, root=root, max_workers=worker_count)

    async def _on_cleanup(a: web.Application) -> None:
        mgr.shutdown()

    app.on_cleanup.append(_on_cleanup)
    app[JOB_MANAGER_KEY] = mgr

    r = app.router
    r.add_get("/", h_index)
    r.add_get("/index.html", h_index)
    r.add_static("/static/", path=STATIC_DIR, name="static")

    api = "/api"
    r.add_get(api + "/health", h_health)
    r.add_get(api + "/overview", h_overview)
    r.add_get(api + "/catalog", h_catalog)
    r.add_get(api + "/releases", h_releases)
    r.add_get(api + "/releases/{version}", h_release_detail)
    r.add_get(api + "/pipelines", h_pipelines)
    r.add_get(api + "/pipelines/{pipeline_id}", h_pipeline_detail)
    r.add_get(api + "/approvals", h_approvals)
    r.add_get(api + "/review/progress", h_review_progress)
    r.add_get(api + "/review/queue", h_review_queue)
    r.add_get(api + "/review/artifacts", h_review_artifacts)
    r.add_get(api + "/review/sft", h_sft_batches)
    r.add_get(api + "/sources", h_sources)
    r.add_get(api + "/sources/etl", h_etl)
    r.add_get(api + "/sources/downloads", h_downloads)
    r.add_get(api + "/sources/cache", h_cache)
    r.add_get(api + "/views", h_views)
    r.add_get(api + "/evaluation/benchmarks", h_benchmarks)
    r.add_get(api + "/evaluation/reports", h_eval_reports)
    r.add_get(api + "/intelligence", h_intelligence)
    r.add_get(api + "/calibration", h_calibration)
    r.add_get(api + "/readiness", h_readiness)
    r.add_get(api + "/jobs", h_jobs)
    r.add_get(api + "/jobs/{job_id}", h_job_detail)
    r.add_get(api + "/jobs/{job_id}/log", h_job_log)
    r.add_post(api + "/jobs/{job_id}/cancel", h_job_cancel)
    r.add_post(api + "/actions/{action_id}/run", h_action_run)
    r.add_get(api + "/preview", h_preview)
    return app
