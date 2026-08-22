"""cli.py — CLI command dispatch for evaluation_research package.

Extends the existing atlas.py CLI with benchmark and eval subcommands.
All commands follow the existing pattern: deterministic, read-only where
possible, with explicit approval gates.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))


def cmd_benchmark_discover(argv: list[str] | None = None) -> int:
    """Discover benchmarks and check license/provenance."""
    from evaluation_research.benchmark_discover import discover_all, discover_benchmark

    ap = argparse.ArgumentParser(description="Discover benchmarks")
    ap.add_argument("--id", default=None, help="Specific benchmark ID to discover")
    ap.add_argument("--register", action="store_true", help="Register discovered benchmarks")
    args = ap.parse_args(argv)

    if args.id:
        results = [discover_benchmark(args.id, REPO)]
    else:
        results = discover_all(REPO)

    print("=" * 64)
    print("BENCHMARK DISCOVERY")
    print("=" * 64)
    for r in results:
        status_icon = "OK" if r.license_compatible else "BLOCKED"
        print(f"  [{status_icon}] {r.benchmark_id}: {r.name}")
        print(f"         license={r.license} family={r.family} N~={r.estimated_n_records}")
        print(f"         risk={r.contamination_risk} url={r.source_url}")
    print("=" * 64)

    if args.register:
        from evaluation_research.benchmark_discover import register_benchmark
        for r in results:
            if r.license_compatible:
                register_benchmark(REPO, r)
                print(f"[register] {r.benchmark_id} registered")
    return 0


def cmd_benchmark_acquire(argv: list[str] | None = None) -> int:
    """Acquire a benchmark from HuggingFace."""
    from evaluation_research.benchmark_discover import discover_benchmark
    from evaluation_research.benchmark_acquire import acquire_benchmark

    ap = argparse.ArgumentParser(description="Acquire a benchmark")
    ap.add_argument("--id", required=True, help="Benchmark ID")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    discovery = discover_benchmark(args.id, REPO)
    if not discovery.license_compatible:
        print(f"[acquire] BLOCKED: license {discovery.license} not compatible")
        return 1

    result = acquire_benchmark(args.id, REPO, dry_run=args.dry_run)
    print(f"[acquire] {result.benchmark_id}: {result.status}")
    print(f"         records={result.n_records} schema_valid={result.schema_valid}")
    if result.files_downloaded:
        print(f"         files={result.files_downloaded}")
    if result.error:
        print(f"         error: {result.error}")
    return 0 if result.status in ("acquired", "partial") else 1


def cmd_benchmark_audit(argv: list[str] | None = None) -> int:
    """Run contamination audit on an eval set."""
    from evaluation_research.contamination import run_contamination_audit

    ap = argparse.ArgumentParser(description="Contamination audit")
    ap.add_argument("--eval-file", required=True, help="Eval set JSONL path")
    ap.add_argument("--output", default=None, help="Output path for audit report")
    args = ap.parse_args(argv)

    result = run_contamination_audit(Path(args.eval_file), REPO, output_path=Path(args.output) if args.output else None)
    print("=" * 64)
    print(f"CONTAMINATION AUDIT — {result.get('eval_set', '?')}")
    print("=" * 64)
    print(f"  total: {result.get('n_total', 0)}")
    print(f"  exact_id:    {result.get('n_exact_id', 0)}")
    print(f"  exact_text:  {result.get('n_exact_text', 0)}")
    print(f"  normalized:  {result.get('n_normalized', 0)}")
    print(f"  near_dup:    {result.get('n_near_duplicate', 0)}")
    print(f"  removed:     {result.get('n_removed', 0)}")
    print(f"  clean:       {result.get('n_clean', 0)}")
    print(f"  verdict:     {result.get('verdict', '?')}")
    print(f"  audit_id:    {result.get('audit_id', '?')}")
    print("=" * 64)
    return 0 if result.get("verdict") in ("PASS", "HOLD") else 1


def cmd_eval_calibrate(argv: list[str] | None = None) -> int:
    """Run generation-policy calibration."""
    from evaluation_research.calibration import main as cal_main
    return cal_main(argv)


def cmd_eval_status(argv: list[str] | None = None) -> int:
    """Show status of research experiments."""
    ap = argparse.ArgumentParser(description="Research experiment status")
    ap.add_argument("--experiment", default=None, help="Specific experiment ID")
    args = ap.parse_args(argv)

    state_dir = REPO / "metadata" / "research_state"
    cal_dir = REPO / "metadata" / "evaluation" / "calibration"
    prod_dir = REPO / "evaluation" / "eval_sets" / "production"

    print("=" * 64)
    print("RESEARCH EXPERIMENT STATUS")
    print("=" * 64)

    # Calibration reports
    cal_files = sorted(cal_dir.glob("*.json")) if cal_dir.exists() else []
    print(f"\nCalibration reports: {len(cal_files)}")
    for f in cal_files[-5:]:
        data = json.loads(f.read_text())
        print(f"  {f.name}: {data.get('verdict', '?')} alpha={data.get('recommended_alpha')} "
              f"N={data.get('n_records_evaluated')}")

    # Frozen eval sets
    mf_files = sorted(prod_dir.glob("*_manifest.json")) if prod_dir.exists() else []
    print(f"\nFrozen eval sets: {len(mf_files)}")
    for mf in mf_files[-5:]:
        data = json.loads(mf.read_text())
        print(f"  {mf.stem}: N={data.get('n_clean')} verdict={data.get('contamination_verdict')} "
              f"sha={data.get('clean_sha256', '')[:12]}")

    # Research state machines
    state_files = sorted(state_dir.glob("*.json")) if state_dir.exists() else []
    print(f"\nResearch state machines: {len(state_files)}")
    for sf in state_files[-5:]:
        data = json.loads(sf.read_text())
        print(f"  {sf.stem}: state={data.get('current_state', '?')} "
              f"transitions={data.get('n_transitions', 0)}")

    print("=" * 64)
    return 0


def register_evaluation_research_commands(parser: argparse.ArgumentParser) -> None:
    """Register evaluation_research subcommands with the Atlas CLI."""
    sub = parser.add_subparsers(dest="command")

    bench = sub.add_parser("benchmark", help="Benchmark management")
    bench_sub = bench.add_subparsers(dest="benchmark_command")

    bench_sub.add_parser("discover", help="Discover benchmarks").set_defaults(
        func=lambda args: cmd_benchmark_discover())
    da = bench_sub.add_parser("acquire", help="Acquire a benchmark")
    da.add_argument("--id", required=True)
    da.add_argument("--dry-run", action="store_true")
    da.set_defaults(func=lambda args: cmd_benchmark_acquire(args))
    aa = bench_sub.add_parser("audit", help="Contamination audit")
    aa.add_argument("--eval-file", required=True)
    aa.add_argument("--output", default=None)
    aa.set_defaults(func=lambda args: cmd_benchmark_audit(args))

    ev = sub.add_parser("eval", help="Evaluation research commands")
    ev_sub = ev.add_subparsers(dest="eval_command")

    ca = ev_sub.add_parser("calibrate-policy", help="Generation-policy calibration")
    ca.add_argument("--eval-file", required=True)
    ca.add_argument("--family", required=True, choices=["math", "code", "semantic"])
    ca.add_argument("--alphas", nargs="+", type=float, required=True)
    ca.add_argument("--seed", type=int, default=42)
    ca.add_argument("--max-records", type=int, default=None)
    ca.add_argument("--smoke", action="store_true")
    ca.add_argument("--resume", action="store_true")
    ca.add_argument("--inference", action="store_true")
    ca.add_argument("--output", default=None)
    ca.set_defaults(func=lambda args: cmd_eval_calibrate([
        "--eval-file", args.eval_file, "--family", args.family,
        "--alphas"
    ] + [str(a) for a in args.alphas] +
        ([] if args.seed == 42 else ["--seed", str(args.seed)]) +
        ([] if args.max_records is None else ["--max-records", str(args.max_records)]) +
        (["--smoke"] if args.smoke else []) +
        (["--resume"] if args.resume else []) +
        (["--inference"] if args.inference else []) +
        ([] if args.output is None else ["--output", args.output])
    ))

    ev_sub.add_parser("status", help="Research experiment status").set_defaults(
        func=lambda args: cmd_eval_status())
