#!/usr/bin/env python3
"""dashboard.actions — whitelisted registry of Atlas operations.

Layer 4 (CLI & Tooling). Every dashboard-triggerable operation is declared
here as a fixed argv template over the REAL Atlas CLIs. The browser supplies
only validated parameters; it can never express arbitrary commands, flags, or
paths.

Action record fields:
  id           stable identifier used by POST /api/actions/{id}/run
  title        human label
  description  what the underlying Atlas operation actually does
  danger       read | safe_write | network | destructive | gpu
  confirm      exact confirmation phrase required when danger == destructive
  group        UI grouping (pipeline | acquisition | etl | views | release |
               review | evaluation | integrity | maintenance)
  params       parameter schema [{name,type,required,default,min,max,choices}]
  build        callable(params) -> full argv list
  timeout_s    job kill timeout
  requires_env env vars that must be present for the action to be enabled

Credentials never travel through argv: they are inherited from the server
environment only, and their presence (never value) is reported via the catalog.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable

from atlas_paths import get_root
from .safety import (
    SafetyError,
    require_confirmation,
    validate_bool,
    validate_choice,
    safe_id,
    validate_int,
    validate_text,
    validate_version,
)

def _v_int(value: object, minimum: int | None = None, maximum: int | None = None,
           name: str = "int") -> int:
    return validate_int(value, name, 0 if minimum is None else minimum,
                        10**9 if maximum is None else maximum)


def _v_choice(value: object, choices: list[str] | None = None,
              name: str = "choice") -> str:
    return validate_choice(value, name, choices or [])


def _v_path_str(value: object, name: str = "path") -> str:
    if not isinstance(value, str) or not value.strip():
        raise SafetyError(f"invalid {name}: must be a non-empty string")
    return value


VALIDATORS: dict[str, Callable[..., Any]] = {
    "id": lambda v, name="id": safe_id(v, name),
    "version": lambda v, name="version": validate_version(v, name),
    "text": lambda v, name="text": validate_text(v, name),
    "int": _v_int,
    "bool": lambda v, name="flag": validate_bool(v, name),
    "choice": _v_choice,
    # path-typed params are validated at argv-build time against whitelists
    "path_in": _v_path_str,
    "path_out": _v_path_str,
}


def _py() -> str:
    return sys.executable


def _runner_argv(*args: str) -> list[str]:
    """automation_runner invocation: python -m scripts.automation_runner <args>

    --output-json keeps job logs machine-readable so the dashboard can echo
    the CLI's own decision messages (e.g. approval-gate rejections) verbatim.
    """
    return [_py(), "-m", "scripts.automation_runner", "--json", *args]


def _atlas_argv(*args: str) -> list[str]:
    """atlas CLI invocation: python scripts/atlas.py <args>"""
    return [_py(), str(Path("scripts") / "atlas.py"), *args]


def _script_argv(rel: str, *args: str) -> list[str]:
    return [_py(), rel, *args]


# ---------------------------------------------------------------------------
# Param builders (concise declarations)
# ---------------------------------------------------------------------------


def P(
    name: str,
    type_: str = "text",
    *,
    required: bool = False,
    default: Any = None,
    choices: list[str] | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
    help: str = "",
) -> dict[str, Any]:
    spec: dict[str, Any] = {"name": name, "type": type_, "required": required,
                            "default": default, "help": help}
    if choices is not None:
        spec["choices"] = choices
    if minimum is not None:
        spec["minimum"] = minimum
    if maximum is not None:
        spec["maximum"] = maximum
    return spec


def _require(params: dict[str, Any], spec: dict[str, Any]) -> Any:
    val = params.get(spec["name"], spec.get("default"))
    if val is None:
        if spec.get("required"):
            raise SafetyError(f"missing required parameter: {spec['name']}")
        return None
    kwargs: dict[str, Any] = {"name": spec["name"]}
    if "choices" in spec:
        kwargs["choices"] = spec["choices"]
    if "minimum" in spec:
        kwargs.update(minimum=spec["minimum"], maximum=spec.get("maximum", 10**9))
    return VALIDATORS[spec["type"]](val, **kwargs)


def _flag(params: dict[str, Any], name: str) -> list[str]:
    return [f"--{name.replace('_', '-')}"] if params.get(name) else []


def _opt(params: dict[str, Any], flag: str, key: str | None = None,
         cast: Callable[[Any], str] = str) -> list[str]:
    key = key or flag.lstrip("-").replace("-", "_")
    val = params.get(key)
    if val is None or val == "":
        return []
    return [flag, cast(val)]


def _repeatable(params: dict[str, Any], flag: str, key: str | None = None) -> list[str]:
    key = key or flag.lstrip("-").replace("-", "_")
    val = params.get(key) or []
    out: list[str] = []
    for item in val:
        out += [flag, safe_id(str(item), key)]
    return out


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ACTIONS: dict[str, dict[str, Any]] = {}


def action(
    id: str,
    title: str,
    description: str,
    *,
    group: str,
    danger: str = "safe_write",
    confirm: str | None = None,
    params: list[dict[str, Any]] | None = None,
    timeout_s: int = 1800,
    requires_env: list[str] | None = None,
) -> Callable[[Callable[[dict[str, Any]], list[str]]], Callable[[dict[str, Any]], list[str]]]:
    def deco(build: Callable[[dict[str, Any]], list[str]]) -> Callable[[dict[str, Any]], list[str]]:
        ACTIONS[id] = {
            "id": id,
            "title": title,
            "description": description,
            "group": group,
            "danger": danger,
            "confirm": confirm,
            "params": params or [],
            "timeout_s": timeout_s,
            "requires_env": requires_env or [],
            "build": build,
        }
        return build
    return deco


# ── Pipeline lifecycle (scripts/automation_runner.py) ──────────────────────


action(
    "pipeline.run", "Run pipeline",
    "Execute the full automation pipeline end-to-end (agents run per FSM state).",
    group="pipeline", danger="safe_write",
    params=[P("pipeline_id", "id", required=True),
            P("dry_run", "bool", default=False),
            P("config_json", "text")],
)(lambda p: _runner_argv("run", "--pipeline-id", p["pipeline_id"],
                         *(_flag(p, "dry_run")), *_opt(p, "--config", "config_json")))


action(
    "pipeline.retry", "Retry pipeline",
    "Retry a failed agent in a pipeline from its failure point.",
    group="pipeline", danger="safe_write",
    params=[P("pipeline_id", "id", required=True), P("config_json", "text")],
)(lambda p: _runner_argv("retry", "--pipeline-id", p["pipeline_id"],
                         *_opt(p, "--config", "config_json")))


action(
    "pipeline.resume", "Resume pipeline",
    "Clear the recorded failure and continue a failed pipeline.",
    group="pipeline", danger="safe_write",
    params=[P("pipeline_id", "id", required=True), P("config_json", "text")],
)(lambda p: _runner_argv("resume", "--pipeline-id", p["pipeline_id"],
                         *_opt(p, "--config", "config_json")))


action(
    "pipeline.cancel", "Cancel pipeline",
    "Cancel a pipeline (terminal CANCELLED transition). Cannot be undone.",
    group="pipeline", danger="destructive", confirm="CANCEL PIPELINE",
    params=[P("pipeline_id", "id", required=True), P("reason", "text")],
)(lambda p: _runner_argv("cancel", "--pipeline-id", p["pipeline_id"],
                         *_opt(p, "--reason", "reason")))


action(
    "pipeline.request_approval", "Request approval",
    "Create a human approval request (WAITING_HUMAN_APPROVAL gate).",
    group="pipeline", danger="safe_write",
    params=[P("pipeline_id", "id", required=True),
            P("role", "choice", default="reviewer",
              choices=["reviewer", "maintainer", "architect", "automated"]),
            P("requested_by", "id", default="dashboard"),
            P("artifacts", "text")],
)(lambda p: _runner_argv("request-approval", "--pipeline-id", p["pipeline_id"],
                         "--role", p["role"], "--requested-by", p["requested_by"],
                         *_opt(p, "--artifacts", "artifacts")))


action(
    "pipeline.approve", "Approve release",
    "Record a human approval decision for a waiting pipeline.",
    group="pipeline", danger="destructive", confirm="APPROVE RELEASE",
    params=[P("pipeline_id", "id", required=True),
            P("by", "id", required=True),
            P("role", "choice", default="reviewer",
              choices=["reviewer", "maintainer", "architect", "automated"]),
            P("comment", "text")],
)(lambda p: _runner_argv("approve", "--pipeline-id", p["pipeline_id"],
                         "--by", p["by"], "--role", p["role"],
                         *_opt(p, "--comment", "comment")))


action(
    "pipeline.deny", "Deny release",
    "Deny a pending release request (transition to RELEASE_REJECTED).",
    group="pipeline", danger="destructive", confirm="DENY RELEASE",
    params=[P("pipeline_id", "id", required=True),
            P("by", "id", required=True),
            P("role", "choice", default="reviewer",
              choices=["reviewer", "maintainer", "architect", "automated"]),
            P("reason", "text")],
)(lambda p: _runner_argv("deny", "--pipeline-id", p["pipeline_id"],
                         "--by", p["by"], "--role", p["role"],
                         *_opt(p, "--reason", "reason")))


action(
    "pipeline.rescind", "Rescind approval",
    "Rescind/clear a previous approval decision.",
    group="pipeline", danger="destructive", confirm="RESCIND APPROVAL",
    params=[P("pipeline_id", "id", required=True)],
)(lambda p: _runner_argv("rescind", "--pipeline-id", p["pipeline_id"]))


action(
    "pipeline.release", "Execute release",
    "Execute release on an APPROVED pipeline (gates enforced by the FSM).",
    group="release", danger="destructive", confirm="EXECUTE RELEASE",
    params=[P("pipeline_id", "id", required=True)],
)(lambda p: _runner_argv("release", "--pipeline-id", p["pipeline_id"]))


# ── Acquisition & download ─────────────────────────────────────────────────


action(
    "acquire.dry_run", "Acquisition dry-run",
    "Simulate the Acquisition Engine plan without side effects (offline).",
    group="acquisition", danger="read",
)(lambda p: _runner_argv("acquire", "--mode", "dry-run"))


action(
    "acquire.execute", "Acquisition execute",
    "Run AcquisitionAgent in acquire mode (writes engine state/artifacts).",
    group="acquisition", danger="safe_write",
)(lambda p: _runner_argv("acquire", "--mode", "acquire"))


action(
    "download.dry_run", "Download dry-run",
    "Plan source downloads into raw/.cache/ without network I/O.",
    group="acquisition", danger="read",
    params=[P("source_ids", type_="multi"), P("use_registry", "bool", default=False)],
)(lambda p: _runner_argv("download", "--mode", "dry-run",
                         *_repeatable(p, "--source-id"),
                         *(_flag(p, "use_registry"))))


action(
    "download.execute", "Download sources",
    "Download acquired sources into raw/.cache/ (real network I/O).",
    group="acquisition", danger="network",
    params=[P("source_ids", type_="multi"), P("use_registry", "bool", default=False),
            P("max_files", "int", minimum=1, maximum=1000),
            P("force", "bool", default=False)],
    timeout_s=7200,
)(lambda p: _runner_argv("download", "--mode", "download",
                         *_repeatable(p, "--source-id"), *(_flag(p, "use_registry")),
                         *_opt(p, "--max-files", "max_files"),
                         *(_flag(p, "force"))))


action(
    "cache.stats", "Cache statistics",
    "Report raw/.cache/ statistics (optionally listing entries). Read-only.",
    group="acquisition", danger="read",
    params=[P("list_entries", "bool", default=False)],
)(lambda p: _runner_argv("cache-stats", *(_flag(p, "list_entries"))))


# ── ETL & transform ────────────────────────────────────────────────────────


action(
    "etl.run", "Run ETL",
    "Extract → normalize → clean cached downloads into metadata/etl/<source>/.",
    group="etl", danger="safe_write",
    params=[P("source_ids", type_="multi"),
            P("limit", "int", minimum=1, maximum=10_000_000),
            P("no_promote", "bool", default=False)],
    timeout_s=7200,
)(lambda p: _runner_argv("etl", *_repeatable(p, "--source-id"),
                         *_opt(p, "--limit", "limit"), *(_flag(p, "no_promote"))))


action(
    "transform.run", "Transform records",
    "Transform cleaned ETL records into the 5 training types.",
    group="etl", danger="safe_write",
    params=[P("source_ids", type_="multi"),
            P("limit", "int", minimum=1, maximum=10_000_000),
            P("prefer", "choice", default="cleaned",
              choices=["cleaned", "atlas_staging", "normalized"])],
)(lambda p: _runner_argv("transform", *_repeatable(p, "--source-id"),
                         *_opt(p, "--limit", "limit"), "--prefer", p["prefer"]))


# ── Views & bundles ────────────────────────────────────────────────────────


action(
    "views.build", "Build training views",
    "Build model-family training views under metadata/views/<version>/ "
    "(view_builder v1.8). Production mode requires approved curated records.",
    group="views", danger="safe_write",
    params=[P("version", "version", required=True),
            P("models", "text", default="qwen,llama,deepseek"),
            P("curated_version", "version"),
            P("production", "bool", default=False),
            P("quality_threshold", "int", minimum=0, maximum=10, default=7),
            P("eval_ratio", "int", minimum=0, maximum=90, default=10),
            P("limit", "int", minimum=1, maximum=10_000_000)],
    timeout_s=7200,
)(lambda p: _runner_argv(
    "views", "--version", p["version"],
    *_opt(p, "--models", "models"),
    *_opt(p, "--curated-version", "curated_version"),
    *(_flag(p, "production")),
    "--quality-threshold", str(p["quality_threshold"]),
    "--eval-ratio", f"0.{p['eval_ratio']:02d}" if p["eval_ratio"] < 10 else str(p["eval_ratio"] / 100),
    *_opt(p, "--limit", "limit")))


action(
    "release.build_bundle", "Build release bundle",
    "Package canonical snapshot + views + eval holdout + checksum manifest "
    "under metadata/release_bundles/<version>/ (Release Builder v1.8).",
    group="release", danger="safe_write",
    params=[P("version", "version", required=True),
            P("source_ids", type_="multi"),
            P("view_version", "version"),
            P("production", "bool", default=False)],
)(lambda p: _runner_argv("release-build", "--version", p["version"],
                         *_repeatable(p, "--source-id"),
                         *_opt(p, "--view-version", "view_version"),
                         *(_flag(p, "production"))))


# ── End-to-end ─────────────────────────────────────────────────────────────


action(
    "e2e.run", "End-to-end pipeline",
    "Full e2e: download → ETL → transform → views → release bundle (v2.0).",
    group="pipeline", danger="network",
    params=[P("version", "version", required=True),
            P("source_ids", type_="multi"),
            P("models", "text", default="qwen,llama,deepseek"),
            P("limit", "int", minimum=1, maximum=10_000_000),
            P("dry_run", "bool", default=False),
            P("production", "bool", default=False),
            P("skip_download", "bool", default=False),
            P("skip_etl", "bool", default=False),
            P("skip_transform", "bool", default=False),
            P("skip_views", "bool", default=False)],
    timeout_s=14400,
)(lambda p: _runner_argv(
    "e2e", "--version", p["version"], *_repeatable(p, "--source-id"),
    *_opt(p, "--models", "models"), *_opt(p, "--limit", "limit"),
    *(_flag(p, "dry_run")), *(_flag(p, "production")),
    *(_flag(p, "skip_download")), *(_flag(p, "skip_etl")),
    *(_flag(p, "skip_transform")), *(_flag(p, "skip_views"))))


# ── Release engineering (scripts/release/*) ────────────────────────────────


action(
    "release.verify_chain", "Verify release chain",
    "Verify the hash-linked release chain and latest release summary "
    "(atlas release --chain-verify --summary). Read-only.",
    group="release", danger="read",
)(lambda p: _atlas_argv("release", "--chain-verify", "--summary"))


action(
    "release.verify_bundle", "Verify release bundle",
    "Verify checksums/counts/structure of releases/<release>/ on disk.",
    group="release", danger="read",
    params=[P("release", "version", required=True)],
)(lambda p: _script_argv("scripts/release/verify_release.py",
                         "--release", p["release"]))


action(
    "release.checksums", "Generate checksums",
    "Compute per-file SHA-256 into releases/<release>/metadata/checksums.sha256. "
    "Refuses to touch released manifests.",
    group="release", danger="safe_write",
    params=[P("release", "version", required=True)],
)(lambda p: _script_argv("scripts/release/generate_checksums.py",
                         "--release", p["release"]))


action(
    "release.audit_duplicates", "Audit duplicates",
    "Audit review_queue/approved.jsonl for duplicate records (report only).",
    group="release", danger="read",
)(lambda p: _script_argv("scripts/release/audit_duplicates.py"))


action(
    "release.promote", "Promote RC to final",
    "Promote a release candidate to final: writes a NEW manifest (RC is never "
    "modified; dataset bytes identical) per ADR-011 immutability.",
    group="release", danger="destructive", confirm="PROMOTE RELEASE",
    params=[P("from_version", "version", required=True),
            P("to_version", "version", required=True),
            P("changelog", "text"),
            P("dry_run", "bool", default=False)],
    timeout_s=7200,
)(lambda p: _script_argv("scripts/release/promote_release.py",
                         "--from", p["from_version"], "--to", p["to_version"],
                         *_opt(p, "--changelog", "changelog"),
                         *(_flag(p, "dry_run"))))


action(
    "release.upload_hf", "Publish bundle to Hugging Face",
    "Upload releases/<release>/ to the Hugging Face Hub (requires HF_TOKEN).",
    group="release", danger="network", requires_env=["HF_TOKEN"],
    params=[P("repo_id", "id", required=True),
            P("release", "version", required=True),
            P("dry_run", "bool", default=False)],
    timeout_s=14400,
)(lambda p: _script_argv("scripts/release/upload_huggingface.py",
                         "--repo-id", p["repo_id"], "--release", p["release"],
                         *(_flag(p, "dry_run"))))


action(
    "release.download_hf", "Restore bundle from Hugging Face",
    "Restore releases/<release>/ from the HF Hub into releases/restored/ and "
    "verify SHA-256 (requires HF_TOKEN). Network operation.",
    group="release", danger="network", requires_env=["HF_TOKEN"],
    params=[P("repo_id", "id", required=True),
            P("release", "version", required=True),
            P("verify", "bool", default=True)],
    timeout_s=14400,
)(lambda p: _script_argv("scripts/release/download_release.py",
                         "--repo-id", p["repo_id"], "--release", p["release"],
                         *(["--verify"] if p.get("verify", True) else [])))


action(
    "release.update_index", "Update release index",
    "Record Hub publication facts (commit URL/hash, file count) in "
    "metadata/release_index.json after a successful upload.",
    group="release", danger="safe_write",
    params=[P("release", "version", required=True),
            P("repo_id", "id", required=True),
            P("commit_url", "text"), P("commit_hash", "id"),
            P("files", "int", minimum=0, maximum=100000, default=0),
            P("total_records", "int", minimum=0, maximum=10_000_000_000, default=0)],
)(lambda p: _script_argv("scripts/release/update_release_index.py",
                         "--release", p["release"], "--repo-id", p["repo_id"],
                         *_opt(p, "--commit-url", "commit_url"),
                         *_opt(p, "--commit-hash", "commit_hash"),
                         "--files", str(p.get("files") or 0),
                         "--total-records", str(p.get("total_records") or 0)))


# ── Review / SFT ───────────────────────────────────────────────────────────


def _existing_view_files() -> list[str]:
    try:
        root = get_root()
        base = root / "metadata" / "views"
        if not base.is_dir():
            return []
        out = []
        for manifest in sorted(base.glob("*")):
            if not manifest.is_dir():
                continue
            for sub in ("train.jsonl",):
                cand = manifest / sub
                if cand.is_file():
                    out.append(str(cand.relative_to(root)))
        return out
    except Exception:
        return []


_RECORDS_PARAM = [P("records", "path_list", required=True,
                    help="SFT train.jsonl inputs (whitelisted repo paths)")]


def _build_records_args(p: dict[str, Any]) -> list[str]:
    from .safety import resolve_readable_path
    args: list[str] = []
    for raw in p.get("records") or []:
        if not isinstance(raw, str) or not raw.strip():
            raise SafetyError("records entries must be non-empty strings")
        args += ["--records", str(resolve_readable_path(raw))]
    if not args:
        raise SafetyError("at least one records path is required")
    return args


action(
    "review.sample", "Generate review sample",
    "Generate a stratified human calibration sample from SFT records "
    "(expert_pipeline.review_sample). Never-overwrite writer.",
    group="review", danger="safe_write",
    params=_RECORDS_PARAM + [
        P("output", "path_out", required=True),
        P("rate_pct", "int", minimum=1, maximum=100, default=5),
        P("seed", "int", minimum=0, maximum=2**31 - 1, default=20260802)],
)(lambda p: _atlas_argv("sft-review", "sample",
                        *_build_records_args(p), "--output",
                        str(_output_path(p["output"])),
                        "--rate", f"{p['rate_pct'] / 100:.4f}".rstrip("0").rstrip(".") or "0",
                        "--seed", str(p["seed"])))


action(
    "review.ai_run", "AI semantic review",
    "Run the dual-mode AI reviewer over records (deterministic gates first; "
    "failures are routed to review, NEVER acceptance). Requires reviewer API "
    "credentials via ATLAS_REVIEW_API_KEY/OPENAI_API_KEY and base URL env.",
    group="review", danger="network",
    requires_env=["ATLAS_REVIEW_BASE_URL"],
    params=_RECORDS_PARAM + [
        P("tag", "id", required=True),
        P("min_quality", "int", minimum=0, maximum=10, default=7),
        P("limit", "int", minimum=1, maximum=100000),
        P("temperature", "int", minimum=0, maximum=200, default=0)],
    timeout_s=14400,
)(lambda p: _atlas_argv("sft-review", "run", "--review-mode", "ai",
                        *_build_records_args(p), "--tag", p["tag"],
                        "--min-quality", str(p["min_quality"]),
                        "--temperature", f"{p['temperature'] / 100:.2f}",
                        *_opt(p, "--limit", "limit")))


action(
    "review.calibrate", "Calibrate human vs AI",
    "Compare human decisions vs AI reviews (verdict agreement, false "
    "accept/reject rates, score delta). Read-only computation + report write.",
    group="review", danger="safe_write",
    params=[P("human_path", "path_in", required=True),
            P("ai_path", "path_in", required=True),
            P("report_out", "path_out")],
)(lambda p: _atlas_argv("sft-review", "calibrate",
                        "--human", str(_input_path(p["human_path"])),
                        "--ai", str(_input_path(p["ai_path"])),
                        *(["--report-out", str(_output_path(p["report_out"]))]
                          if p.get("report_out") else [])))


# ── Evaluation ─────────────────────────────────────────────────────────────


action(
    "evaluation.list_benchmarks", "List benchmarks",
    "List registered evaluation benchmarks (read-only inventory).",
    group="evaluation", danger="read",
)(lambda p: _atlas_argv("evaluate", "--list"))


action(
    "evaluation.describe", "Describe benchmark",
    "Describe one registered benchmark in detail. Read-only.",
    group="evaluation", danger="read",
    params=[P("benchmark_id", "id", required=True)],
)(lambda p: _atlas_argv("evaluate", "--describe", p["benchmark_id"]))


action(
    "evaluation.dry_run", "Evaluation dry-run",
    "Simulate an evaluation run (no data mutation, no network).",
    group="evaluation", danger="read",
    params=[P("benchmark_id", "id", required=True)],
)(lambda p: _atlas_argv("evaluate", "--dry-run", "--run", p["benchmark_id"]))


action(
    "evaluation.run", "Execute evaluation",
    "Execute deterministic evaluation against a benchmark (QEE; network-free; "
    "reports written under metadata/evaluation/reports/).",
    group="evaluation", danger="safe_write",
    params=[P("benchmark_id", "id", required=True)],
    timeout_s=7200,
)(lambda p: _atlas_argv("evaluate", "--no-dry-run", "--run", p["benchmark_id"]))


action(
    "benchmark.discover", "Discover benchmarks",
    "Discover candidate external benchmarks (network research tooling).",
    group="evaluation", danger="network",
    params=[P("query", "text")],
    timeout_s=3600,
)(lambda p: _atlas_argv("benchmark", "discover", *_opt(p, "--query", "query")))


# ── Integrity & maintenance ────────────────────────────────────────────────


action(
    "integrity.self_test", "CLI self-test",
    "Run atlas CLI invariant checks (license gate, AQL, release manager, "
    "release chain). Read-only diagnostics.",
    group="integrity", danger="read",
    timeout_s=900,
)(lambda p: _atlas_argv("self-test"))


action(
    "integrity.architecture", "Architecture validation",
    "Run scripts/validate_architecture.py governance checks. Read-only.",
    group="integrity", danger="read",
    timeout_s=900,
)(lambda p: [_py(), "scripts/validate_architecture.py"])


action(
    "integrity.readiness", "Training readiness check",
    "Recompute the 6-gate training readiness verdict (READ-ONLY evaluation; "
    "prints report JSON).",
    group="integrity", danger="read",
    timeout_s=1800,
)(lambda p: _atlas_argv("training-readiness"))


action(
    "maintenance.metadata_sync", "Metadata sync",
    "Run the fixed metadata synchronization workflow (baseline verify → sync).",
    group="maintenance", danger="safe_write",
    timeout_s=1800,
)(lambda p: _script_argv("scripts/metadata_sync.py"))


action(
    "dataset.validate", "Validate dataset file",
    "Validate a dataset JSONL against the Atlas schema with statistics. "
    "Read-only. Input restricted to whitelisted subtrees.",
    group="integrity", danger="read",
    params=[P("input_path", "path_in", required=True),
            P("strict", "bool", default=False)],
    timeout_s=3600,
)(lambda p: _script_argv("scripts/validate_dataset.py",
                         "--input", str(_input_path(p["input_path"])),
                         "--stats", *(_flag(p, "strict"))))


action(
    "quality.calibrate", "Quality calibration",
    "Compare auto quality scores vs human reviews and emit "
    "metadata/calibration_report.json (calibrate_quality.py).",
    group="review", danger="safe_write",
    params=[P("reviews_path", "path_in", required=True),
            P("candidates_path", "path_in", required=True)],
    timeout_s=3600,
)(lambda p: _script_argv("scripts/calibrate_quality.py",
                         "--reviews", str(_input_path(p["reviews_path"])),
                         "--candidates", str(_input_path(p["candidates_path"]))))


action(
    "aql.validate", "Validate AQL query",
    "Validate an Atlas Query Language statement without executing. Read-only.",
    group="evaluation", danger="read",
    params=[P("query", "text", required=True),
            P("source", "id", default="v0.1")],
)(lambda p: _atlas_argv("query", "--validate", p["query"],
                        "--source", p["source"]))


action(
    "aql.execute", "Execute AQL query",
    "Execute an AQL query against curated/<version> (network blocked inside "
    "the CLI; read-only query surface).",
    group="evaluation", danger="read",
    params=[P("query", "text", required=True),
            P("source", "id", default="v0.1")],
    timeout_s=3600,
)(lambda p: _atlas_argv("query", "--execute", p["query"], "--source", p["source"]))


# ---------------------------------------------------------------------------
# Path helpers for path-typed params
# ---------------------------------------------------------------------------


def _validated_repo_file(rel: str, kind: str) -> Path:
    del kind
    from .safety import resolve_readable_path
    return resolve_readable_path(rel)


def _input_path(rel: str) -> Path:
    return _validated_repo_file(rel, "in")


def _output_path(rel: str) -> Path:
    """Output paths must be repo-relative, inside approved write roots."""
    from .safety import SafetyError
    from atlas_paths import is_write_safe
    if not isinstance(rel, str) or rel.startswith(("/", "~")) or "\\" in rel:
        raise SafetyError("output must be a repo-relative path using forward slashes")
    root = get_root().resolve()
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SafetyError("output path escapes repository root") from exc
    if not is_write_safe(candidate):
        raise SafetyError(
            "output path is outside approved write roots "
            "(see atlas_paths.APPROVED_WRITE_ROOTS)")
    return candidate


# ---------------------------------------------------------------------------
# Catalog / validation entry points
# ---------------------------------------------------------------------------

_MULTI_TYPES = {"multi", "path_list"}


def get_action(action_id: str) -> dict[str, Any]:
    act = ACTIONS.get(action_id)
    if act is None:
        raise KeyError(action_id)
    return act


def catalog() -> list[dict[str, Any]]:
    """Serializable action catalog for the frontend (includes enabled state)."""
    items = []
    for act in sorted(ACTIONS.values(), key=lambda a: (a["group"], a["id"])):
        missing = [env for env in act["requires_env"] if not os.environ.get(env)]
        items.append({
            "id": act["id"],
            "title": act["title"],
            "description": act["description"],
            "group": act["group"],
            "danger": act["danger"],
            "confirm_phrase": act["confirm"],
            "params": act["params"],
            "timeout_s": act["timeout_s"],
            "enabled": not missing,
            "disabled_reason": (
                "missing required environment: " + ", ".join(missing)
                if missing else None),
            # Presence booleans only — never values.
            "credentials_present": {
                env: bool(os.environ.get(env)) for env in ("HF_TOKEN",
                                                           "ATLAS_REVIEW_BASE_URL",
                                                           "ATLAS_REVIEW_API_KEY",
                                                           "OPENAI_API_KEY")
            },
        })
    return items


def build_argv(action_id: str, params: dict[str, Any] | None) -> list[str]:
    """Validate params against the schema and build the subprocess argv."""
    act = get_action(action_id)
    params = params or {}
    # Reject unknown parameters outright.
    known = {spec["name"] for spec in act["params"]}
    unknown = set(params) - known - {"confirm"}
    if unknown:
        raise SafetyError(f"unknown parameter(s): {sorted(unknown)}")

    normalized: dict[str, Any] = {}
    for spec in act["params"]:
        t = spec["type"]
        if t in _MULTI_TYPES:
            raw = params.get(spec["name"], [])
            if not isinstance(raw, list):
                raise SafetyError(f"parameter {spec['name']} must be a list")
            cleaned = []
            for item in raw[:1000]:
                if not isinstance(item, str):
                    raise SafetyError(f"parameter {spec['name']} entries must be strings")
                if t == "multi":
                    cleaned.append(safe_id(item, spec["name"]))
                else:  # path_list — validated at build time against whitelist
                    cleaned.append(item)
            if spec.get("required") and not cleaned:
                raise SafetyError(f"missing required parameter: {spec['name']}")
            normalized[spec["name"]] = cleaned
        elif spec.get("required") and spec["name"] not in params \
                and spec.get("default") is None:
            raise SafetyError(f"missing required parameter: {spec['name']}")
        elif spec["name"] in params or spec.get("default") is not None:
            val = params.get(spec["name"], spec.get("default"))
            kwargs: dict[str, Any] = {"name": spec["name"]}
            if "choices" in spec:
                kwargs["choices"] = spec["choices"]
            if "minimum" in spec:
                kwargs.update(minimum=spec["minimum"],
                              maximum=spec.get("maximum", 10**9))
            normalized[spec["name"]] = VALIDATORS[t](val, **kwargs)

    if act["danger"] == "destructive":
        require_confirmation(params.get("confirm"), act["confirm"])

    argv = act["build"](normalized)
    if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
        raise RuntimeError(f"action {action_id} produced invalid argv")
    return argv
