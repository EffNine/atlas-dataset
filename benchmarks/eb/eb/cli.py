#!/usr/bin/env python3
"""
cli.py — EffNine Benchmark CLI entry point.

Provides command parsing and dispatch for:
   eb run     — Run a benchmark suite against a model
   eb compare — Compare benchmark runs between models
   eb report  — Generate or display a benchmark report
   eb baseline — Register a base-model run as baseline
   eb status  — Show run status from registry
   eb calibrate — Run calibration agreement analysis

Usage:
   eb run --model atan-v1 --suite single
   eb run --model atan-v1 --suite single --repeats 3
   eb run --model qwen-base --suite single --as-baseline
   eb compare run-a run-b
   eb report --run-id <run-id>
   eb status <run-id>
   eb calibrate [--live-judge] [--judge-model <model>] [--output <path>]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import NoReturn

from .adapters.factory import AdapterFactory
from .calibration.agreement import AgreementAnalyzer
from .calibration.report import generate_report as calibration_generate_report
from .env_config import ensure_env_loaded, redact_dict, validate_run_env
from .core.registry import BenchmarkRegistry
from .core.schema import BaselineRecord, BenchmarkRun, InferenceSettings, ModelMetadata
from .core.types import BenchmarkPartition
from .reports.generator import generate_human_report, generate_machine_report
from .runners.orchestration import RunOrchestrator
from .sandbox.manager import SUPPORTED_BACKENDS, resolve_sandbox_backend
from .scoring.eb_score import SCORING_VERSION
from .scoring.regression import compare_runs


VERSION = "0.5.0"


def _error(msg: str) -> NoReturn:
    print(f"EB ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="eb",
        description=f"EffNine Benchmark v{VERSION} — Capability benchmark for software engineering",
    )
    parser.add_argument("--version", action="version", version=f"eb {VERSION}")

    sub = parser.add_subparsers(dest="command", required=True)

    # ---- eb run ----
    run = sub.add_parser("run", help="Run a benchmark suite against a model")
    run.add_argument("--model", required=True, help="Model identifier (e.g. atan-v1)")
    run.add_argument("--suite", default="full", help="Suite name (default: full)")
    run.add_argument(
        "--benchmark-version", default=None,
        help="Benchmark version (default: eb-v0.1)",
    )
    run.add_argument(
        "--task-set-version", default=None,
        help="Task set version (default: tasks-v0.1)",
    )
    run.add_argument(
        "--partitions", default="development",
        help="Comma-separated partitions to include (default: development)",
    )
    run.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    run.add_argument("--temperature", type=float, default=0.0, help="Sampling temperature (default: 0.0)")
    run.add_argument("--top-p", type=float, default=1.0, help="Top-p sampling (default: 1.0)")
    run.add_argument("--top-k", type=int, default=0, help="Top-k sampling (default: 0)")
    run.add_argument("--max-tokens", type=int, default=4096, help="Max tokens per response (default: 4096)")
    run.add_argument("--context-length", type=int, default=8192, help="Context length (default: 8192)")
    run.add_argument("--repeats", type=int, default=1, help="Number of repeated runs (default: 1)")
    run.add_argument(
        "--baseline-run", default=None,
        help="Explicit baseline run ID to normalize against",
    )
    run.add_argument(
        "--as-baseline", action="store_true",
        help="Register this run as a baseline for its base model",
    )
    # EXEC-specific flags (Stage 6)
    run.add_argument(
        "--max-tool-calls", type=int, default=50,
        help="Maximum tool calls per EXEC task (default: 50)",
    )
    run.add_argument(
        "--sandbox-timeout", type=float, default=300.0,
        help="Sandbox command timeout in seconds (default: 300)",
    )
    run.add_argument(
        "--docker-image", type=str, default="python:3.11-slim",
        help="Docker image for EXEC sandbox (default: python:3.11-slim)",
    )
    run.add_argument(
        "--long-max-concurrent", type=int, default=1,
        help="Maximum concurrent LONG tasks (default: 1)",
    )
    # Stage 8F additions
    run.add_argument(
        "--resume", default=None,
        help="Path to checkpoint file or directory to resume from",
    )
    run.add_argument(
        "--sandbox-backend", default=None,
        choices=SUPPORTED_BACKENDS,
        help=f"Sandbox backend (default: docker, or EB_SANDBOX_BACKEND env)",
    )
    run.add_argument(
        "--output-dir", default=None,
        help="Output directory for run artifacts (default: outputs/runs/)",
    )
    run.set_defaults(handler=_cmd_run)

    # ---- eb compare ----
    compare = sub.add_parser("compare", help="Compare benchmark runs between models")
    compare.add_argument("runs", nargs="+", help="Run IDs to compare")
    compare.add_argument(
        "--benchmark-version", default=None,
        help="Benchmark version to compare (default: latest)",
    )
    compare.set_defaults(handler=_cmd_compare)

    # ---- eb report ----
    report = sub.add_parser("report", help="Generate or display a benchmark report")
    report.add_argument("--run-id", required=True, help="Run ID to report on")
    report.add_argument("--format", choices=["text", "json"], default="text", help="Output format")
    report.set_defaults(handler=_cmd_report)

    # ---- eb baseline ----
    baseline = sub.add_parser("baseline", help="Register or inspect baselines")
    baseline.add_argument("action", choices=["list", "register", "resolve"], help="Action to perform")
    baseline.add_argument("--run-id", default=None, help="Run ID to register as baseline")
    baseline.add_argument("--model", default=None, help="Base model name (for register)")
    baseline.add_argument("--benchmark-version", default=None, help="Benchmark version")
    baseline.set_defaults(handler=_cmd_baseline)

    # ---- eb status ----
    status = sub.add_parser("status", help="Show benchmark run status")
    status.add_argument("run_id", help="Run ID to query")
    status.set_defaults(handler=_cmd_status)

    # ---- eb calibrate ----
    calibrate = sub.add_parser("calibrate", help="Run calibration agreement analysis")
    calibrate.add_argument(
        "--live-judge", action="store_true",
        help="Request live judge evaluation (requires EB_JUDGE_API_KEY)",
    )
    calibrate.add_argument(
        "--judge-model", default=None,
        help="Judge model identifier (default: auto)",
    )
    calibrate.add_argument(
        "--output", default=None,
        help="Output path for calibration report (default: metadata/calibration/)",
    )
    calibrate.set_defaults(handler=_cmd_calibrate)

    return parser


# ---------------------------------------------------------------------------
# Preflight model identity check
# ---------------------------------------------------------------------------


def _preflight_model_identity(model_name: str) -> None:
    """Verify that the requested model resolves to a valid, loadable model.

    Reads the model config, inspects config.json on disk, attempts a light
    load via AutoConfig, and prints the verified identity.  Exits on failure
    so that a benchmark never runs against the wrong model.
    """
    from .adapters.factory import get_factory
    from .paths import config_dir
    import json as _json
    import os as _os

    factory = get_factory()
    config = factory.get_model_config(model_name)
    if config is None:
        _error(f"Model {model_name!r} not found in {config_dir() / 'models.yaml'}")

    model_path = config.get("model_path")
    if not model_path:
        model_path = _os.environ.get("EB_LOCAL_MODEL_PATH")
    if not model_path:
        _error(f"No model_path for {model_name!r} and EB_LOCAL_MODEL_PATH is unset")

    config_json = _os.path.join(model_path, "config.json")
    if not _os.path.isfile(config_json):
        _error(f"config.json not found at {config_json}")

    with open(config_json, encoding="utf-8") as f:
        model_cfg = _json.load(f)

    arch = model_cfg.get("architectures", ["unknown"])
    mtype = model_cfg.get("model_type", "unknown")
    dtype = model_cfg.get("dtype", "unknown")
    quant = model_cfg.get("quantization_config")
    quant_str = f" quant={quant.get('quant_method')}" if quant else ""

    print(f"EB PREFLIGHT: model={model_name}")
    print(f"  path         = {model_path}")
    print(f"  architecture = {arch}")
    print(f"  model_type   = {mtype}")
    print(f"  dtype        = {dtype}{quant_str}")

    try:
        from transformers import AutoConfig
        AutoConfig.from_pretrained(model_path, trust_remote_code=True)
        print("  config_load  = OK")
    except Exception as e:
        print(f"  config_load  = FAILED: {e}", file=sys.stderr)
        _error(f"Model config validation failed for {model_name!r}: {e}")

    print()


# ---- Command handlers ----


def _cmd_run(args: argparse.Namespace) -> None:
    """Run a benchmark suite against a model."""
    partitions = [p.strip() for p in getattr(args, "partitions", "development").split(",")]

    try:
        env = validate_run_env()
        redacted = redact_dict(env)
        print(f"EB v{VERSION}: run")
        print(f"  model            = {args.model}")
        print(f"  suite            = {args.suite}")
        print(f"  benchmark_version = {getattr(args, 'benchmark_version', None) or 'eb-v0.1'}")
        print(f"  task_set_version  = {getattr(args, 'task_set_version', None) or 'tasks-v0.1'}")
        print(f"  partitions       = {partitions}")
        print(f"  seed             = {args.seed}")
        print(f"  temperature      = {args.temperature}")
        print(f"  repeats          = {args.repeats}")
        print(f"  baseline_run     = {args.baseline_run}")
        print(f"  as_baseline      = {args.as_baseline}")
        print()
    except Exception as e:
        print(f"EB WARNING: env validation issue: {e}", file=sys.stderr)

    # Preflight: verify model identity before launching the run.
    _preflight_model_identity(args.model)

    orchestrator = RunOrchestrator(
        model_name=args.model,
        suite=args.suite,
        partitions=partitions,
        repeats=args.repeats,
        seed=args.seed,
        temperature=args.temperature,
        top_p=args.top_p,
        top_k=args.top_k,
        max_tokens=args.max_tokens,
        context_length=args.context_length,
        benchmark_version=getattr(args, "benchmark_version", None),
        task_set_version=getattr(args, "task_set_version", None),
        baseline_run_id=getattr(args, "baseline_run", None),
        as_baseline=getattr(args, "as_baseline", False),
        max_tool_calls=getattr(args, "max_tool_calls", 50),
        sandbox_timeout=getattr(args, "sandbox_timeout", 300.0),
        docker_image=getattr(args, "docker_image", "python:3.11-slim"),
        long_max_concurrent=getattr(args, "long_max_concurrent", 1),
        resume_from=getattr(args, "resume", None),
        sandbox_backend=getattr(args, "sandbox_backend", None),
        output_dir=getattr(args, "output_dir", None),
    )
    summary = orchestrator.run()
    print(f"\nRun ID: {summary.run_id}")
    print(f"Artifact dir: {summary.artifact_dir}")


def _cmd_compare(args: argparse.Namespace) -> None:
    """Compare benchmark runs."""
    registry = BenchmarkRegistry()
    runs_data = []
    for run_id in args.runs:
        run = registry.get_run(run_id)
        if run is None:
            _error(f"Run not found: {run_id}")
        runs_data.append(run)

    if len(runs_data) < 2:
        _error("Compare requires at least 2 run IDs")

    from .scoring.regression import compare_runs
    result = compare_runs(runs_data[0], runs_data[1])

    print(f"EB v{VERSION}: compare")
    print(f"  {result.model_a}  →  EB Score: {result.eb_score_a}")
    print(f"  {result.model_b}  →  EB Score: {result.eb_score_b}")
    print(f"  Delta: {result.score_delta:+d} ({result.percent_delta:+.1f}%)")
    print()

    if result.capability_deltas:
        print("Capability deltas:")
        for cd in result.capability_deltas:
            sign = "+" if cd.delta > 0 else ""
            print(f"  {cd.capability:<15} {cd.score_a:>5} → {cd.score_b:>5}  ({sign}{cd.delta:+d}, {sign}{cd.percent_delta:.1f}%)")
        print()

    if result.notes:
        for note in result.notes:
            print(f"  {note}")


def _cmd_report(args: argparse.Namespace) -> None:
    """Generate a report for a run."""
    registry = BenchmarkRegistry()
    run_data = registry.get_run(args.run_id)
    if run_data is None:
        _error(f"Run not found: {args.run_id}")

    if args.format == "json":
        report = generate_machine_report(run_data)
        print(json.dumps(report, indent=2))
    else:
        text = generate_human_report(run_data)
        print(text)


def _cmd_baseline(args: argparse.Namespace) -> None:
    """Baseline management commands."""
    registry = BenchmarkRegistry()

    if args.action == "list":
        baselines = registry.list_baselines()
        if not baselines:
            print("No baselines registered.")
            return
        for key, bl in baselines:
            print(f"  {key}")
            print(f"    model     = {bl.base_model_name} ({bl.base_model_revision})")
            print(f"    bench     = {bl.benchmark_version} / {bl.task_set_version}")
            print(f"    run_id    = {bl.baseline_run_id}")
            print(f"    scores    = {bl.run_scores}")
            print(f"    mean      = {bl.mean}")
            print(f"    eb_score  = {bl.eb_score}")
            print()

    elif args.action == "register":
        if not args.run_id:
            _error("--run-id is required for register")
        run_data = registry.get_run(args.run_id)
        if run_data is None:
            _error(f"Run not found: {args.run_id}")
        model_name = args.model or run_data.get("model", {}).get("name", "unknown")
        bench_ver = args.benchmark_version or run_data.get("benchmark_version", "eb-v0.1")
        bl = BaselineRecord(
            base_model_name=model_name,
            base_model_revision=run_data.get("model", {}).get("revision", "local"),
            benchmark_version=bench_ver,
            task_set_version=run_data.get("task_set_version", "tasks-v0.1"),
            baseline_run_id=args.run_id,
            suite=run_data.get("suite", ""),
            scoring_version=SCORING_VERSION,
        )
        bl.compute_stats()
        registry.set_baseline(bl, as_registered=True)
        print(f"Registered baseline: {bl.baseline_run_id} for {model_name}")
        print(f"  EB Score (normalized): {bl.eb_score}")
        print(f"  Mean run score: {bl.mean}")

    elif args.action == "resolve":
        run_id = args.run_id
        if not run_id:
            _error("--run-id is required for resolve")
        bl = registry.get_baseline(run_id=run_id)
        if bl:
            print(f"Baseline found: {bl.base_model_name} @ {bl.benchmark_version}")
            print(f"  run_id    = {bl.baseline_run_id}")
            print(f"  mean      = {bl.mean}")
            print(f"  eb_score  = {bl.eb_score}")
        else:
            print("No baseline found for this run.")


def _cmd_status(args: argparse.Namespace) -> None:
    """Show status of a benchmark run."""
    registry = BenchmarkRegistry()
    run_data = registry.get_run(args.run_id)
    if run_data is None:
        print(f"Run not found: {args.run_id}", file=sys.stderr)
        sys.exit(1)

    print(f"Run ID:          {run_data.get('run_id', 'unknown')}")
    print(f"Model:           {run_data.get('model', {}).get('name', 'unknown')}")
    print(f"Suite:           {run_data.get('suite', 'unknown')}")
    print(f"Run Status:      {run_data.get('run_status', 'unknown')}")

    generated_at = run_data.get('generated_at')
    if generated_at:
        print(f"Generated At:    {generated_at}")

    task_results = run_data.get('task_results', [])
    if task_results:
        total = len(task_results)
        with_scores = sum(1 for r in task_results if r.get('raw_task_score') is not None)
        with_outcome = sum(1 for r in task_results if r.get('long_outcome') is not None)
        print(f"Task Count:      {total}")
        if with_scores:
            print(f"  With scores:   {with_scores}")
        if with_outcome:
            print(f"  With outcome:  {with_outcome}")

    sys.exit(0)


def _cmd_calibrate(args: argparse.Namespace) -> None:
    """Run calibration agreement analysis."""
    live_judge = getattr(args, "live_judge", False)
    judge_model = getattr(args, "judge_model", None)
    output_path = getattr(args, "output", None)

    if live_judge:
        from .env_config import validate_judge_env, EnvValidationError
        try:
            validate_judge_env(required=True)
        except EnvValidationError as e:
            _error(f"Live judge requires environment configuration: {e}")

    live_judge_status = "AVAILABLE" if live_judge else "NOT_AVAILABLE"
    judge_model_value = judge_model or "auto"

    try:
        report = calibration_generate_report(
            judge_model=judge_model_value,
            live_judge=live_judge_status,
            output_path=Path(output_path) if output_path else None,
        )
        print(f"Calibration report generated.")
        print(f"  Reference samples: {report.reference_samples}")
        print(f"  Judge samples:     {report.judge_samples}")
        print(f"  Comparable:        {report.comparable_samples}")
        print(f"  Overall MAE:       {report.overall_mae}")
        print(f"  Agreement rate:    {report.overall_agreement_rate}")
        print(f"  Low agreement:     {report.low_agreement_count}")
        print(f"  Live judge:        {report.live_judge}")
        if output_path:
            print(f"  Output:            {output_path}")
    except Exception as e:
        _error(f"Calibration failed: {e}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()

