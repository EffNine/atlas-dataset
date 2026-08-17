#!/usr/bin/env python3
"""
generator.py — Human-readable and machine-readable EB report generator.

Stage 5: Produces final benchmark reports in two formats:
    1. Human-readable text report (simple, clean)
    2. Machine-readable JSON report (full detail)

Usage:
    generator.generate_human_report(run_data) -> str
    generator.generate_machine_report(run_data) -> dict
"""

from __future__ import annotations

from typing import Any

from ..scoring.regression import classify_stability


# ---------------------------------------------------------------------------
# Human-readable report
# ---------------------------------------------------------------------------


def generate_human_report(run_data: dict[str, Any]) -> str:
    """
    Generate a human-readable EB benchmark report.

    Parameters
    ----------
    run_data : dict
        Run data containing:
            - model, base_model, benchmark_version, task_set_version
            - repeats (int)
            - overall_eb_score (int)
            - error_percent (float, optional)
            - capability_scores (dict of cap_key → {eb_score, error_percent})
            - baseline_eb_score (int, optional)
            - improvement_percent (float, optional)
            - stability_status (str, optional)

    Returns
    -------
    str — Formatted report text.
    """
    lines: list[str] = []

    # Header
    lines.append("EFFNINE BENCHMARK")
    lines.append("")

    # Model info
    model = run_data.get("model", "unknown")
    base = run_data.get("base_model", "unknown")
    benchmark = run_data.get("benchmark_version", "unknown")
    task_set = run_data.get("task_set_version", "unknown")
    repeats = run_data.get("repeats", 1)

    lines.append(f"Model       {model}")
    lines.append(f"Base        {base}")
    lines.append(f"Benchmark   {benchmark}")
    lines.append(f"Task Set    {task_set}")
    lines.append(f"Runs        {repeats}")
    lines.append("")

    # EB Score
    eb_score = run_data.get("overall_eb_score")
    error_pct = run_data.get("error_percent")
    if eb_score is not None:
        if error_pct is not None:
            lines.append(f"EB SCORE")
            lines.append(f"{eb_score} \u00b1 {error_pct:.1f}%")
        else:
            lines.append(f"EB SCORE")
            lines.append(f"{eb_score}")
    lines.append("")

    # Capability scores
    cap_scores = run_data.get("capability_scores", {})
    if cap_scores:
        lines.append("CAPABILITY")
        # Find max width for alignment
        max_len = max(len(cap) for cap in _capability_labels()) if cap_scores else 0
        for cap_key in _capability_order():
            cs = cap_scores.get(cap_key)
            if cs is None:
                continue
            label = _capability_label(cap_key)
            score = cs.get("eb_score", "?")
            err = cs.get("error_percent")
            err_str = f"  \u00b1{err:.1f}%" if err is not None else ""
            lines.append(f"  {label:<{max_len+2}} {score}{err_str}")
        lines.append("")

    # Stability
    stability_status = run_data.get("stability_status")
    if stability_status or error_pct is not None:
        lines.append("STABILITY")
        if error_pct is not None:
            lines.append(f"  Error    {error_pct:.1f}%")
        if stability_status:
            lines.append(f"  Status   {stability_status}")
        lines.append("")

    # EXEC-specific output
    exec_meta = run_data.get("execution_metadata", {})
    if exec_meta:
        lines.append("EXECUTION")
        repo_id = exec_meta.get("repository_id")
        if repo_id:
            lines.append(f"  Repository   {repo_id}")
        test_summary = exec_meta.get("test_summary", {})
        if test_summary:
            tc = test_summary.get("test_count", "?")
            passed = test_summary.get("passed", False)
            lines.append(f"  Tests        {tc} {'passed' if passed else 'failed'}")
        changed = exec_meta.get("changed_files", [])
        if changed:
            lines.append(f"  Changed      {len(changed)} file(s)")
        exec_time = exec_meta.get("execution_time")
        if exec_time is not None:
            lines.append(f"  Execution    {exec_time:.1f}s")
        lines.append("")

    # Baseline comparison
    baseline_score = run_data.get("baseline_eb_score", 1000)
    improvement = run_data.get("improvement_percent")
    if eb_score is not None:
        lines.append("BASELINE")
        lines.append(f"  Base Model       {baseline_score}")
        lines.append(f"  {model}               {eb_score}")
        if improvement is not None:
            sign = "+" if improvement > 0 else ""
            lines.append(f"  Improvement      {sign}{improvement}%")
        lines.append("")

    # Reproducibility metadata
    repro = run_data.get("reproducibility", {})
    if repro:
        lines.append("REPRODUCIBILITY")
        sb = repro.get("sandbox_backend")
        if sb:
            lines.append(f"  Sandbox Backend  {sb}")
        eval_ver = repro.get("evaluator_config_version")
        if eval_ver:
            lines.append(f"  Evaluator Config {eval_ver}")
        rubric_ver = repro.get("rubric_version")
        if rubric_ver:
            lines.append(f"  Rubric Version   {rubric_ver}")
        lm = repro.get("long_max_concurrent")
        if lm is not None:
            lines.append(f"  Long Concurrent  {lm}")
        lines.append("")

    # Judge / quality availability
    judge_enabled = run_data.get("judge") is not None
    if judge_enabled or run_data.get("quality"):
        lines.append("JUDGE & QUALITY")
        lines.append(f"  Judge Enabled    {'yes' if judge_enabled else 'no'}")
        qs = run_data.get("quality", {})
        if qs:
            avg_qs = qs.get("avg_quality_score")
            if avg_qs is not None:
                lines.append(f"  Avg Quality      {avg_qs:.4f}")
            qc = qs.get("quality_count", 0)
            if qc > 0:
                lines.append(f"  Quality Samples  {qc}")
        lines.append("")

    # Outcome distribution
    outcome_dist = run_data.get("outcome_distribution")
    if outcome_dist:
        lines.append("OUTCOME DISTRIBUTION")
        for outcome, count in sorted(outcome_dist.items()):
            lines.append(f"  {outcome:<12} {count}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Machine-readable report
# ---------------------------------------------------------------------------


def generate_machine_report(run_data: dict[str, Any]) -> dict[str, Any]:
    """
    Generate a machine-readable report with full detail.

    Parameters
    ----------
    run_data : dict
        Run data (same structure as human report, plus optional extras).

    Returns
    -------
    dict — Full structured report.
    """
    task_results = run_data.get("task_results", [])
    scores = [r.get("raw_task_score") for r in task_results if r.get("raw_task_score") is not None]
    outcomes = [r.get("long_outcome") for r in task_results if r.get("long_outcome") is not None]
    quality_scores = []
    for r in task_results:
        for ev in r.get("evaluator_results", []):
            details = ev.get("details", {})
            qs = details.get("quality_score")
            if qs is not None:
                quality_scores.append(qs)

    return {
        "report_type": "effnine_benchmark",
        "schema_version": "8F.1",
        "scoring_version": run_data.get("scoring_version", "eb-score-v1"),
        "model": run_data.get("model"),
        "base_model": run_data.get("base_model"),
        "benchmark_version": run_data.get("benchmark_version"),
        "task_set_version": run_data.get("task_set_version"),
        "repeats": run_data.get("repeats", 1),
        "overall_eb_score": run_data.get("overall_eb_score"),
        "base_raw_mean": run_data.get("base_raw_mean"),
        "model_raw_mean": run_data.get("model_raw_mean"),
        "improvement_percent": run_data.get("improvement_percent"),
        "error_percent": run_data.get("error_percent"),
        "stability_status": run_data.get("stability_status") or classify_stability(run_data.get("error_percent")),
        "capability_scores": run_data.get("capability_scores", {}),
        "score": sum(scores) / len(scores) if scores else None,
        "outcome_distribution": {o: outcomes.count(o) for o in set(outcomes)} if outcomes else None,
        "quality": {
            "avg_quality_score": sum(quality_scores) / len(quality_scores) if quality_scores else None,
            "quality_count": len(quality_scores),
        },
        "judge_enabled": run_data.get("judge") is not None,
        "sandbox_backend": run_data.get("reproducibility", {}).get("sandbox_backend"),
        "baseline": {
            "baseline_run_id": run_data.get("baseline_run_id"),
            "eb_score": run_data.get("baseline_eb_score", 1000),
            "base_model_name": run_data.get("base_model"),
        },
        "benchmark_compatibility": {
            "benchmark_version": run_data.get("benchmark_version"),
            "task_set_version": run_data.get("task_set_version"),
            "scoring_version": run_data.get("scoring_version", "eb-score-v1"),
            "task_set_hash": run_data.get("task_set_hash"),
            "evaluator_config_version": run_data.get("evaluator_config_version"),
        },
        "reproducibility": run_data.get("reproducibility", {}),
        "generated_at": run_data.get("generated_at"),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _capability_order() -> list[str]:
    """Return capabilities in the canonical display order."""
    return [
        "ARCH", "DEBUG", "CODE", "UNDERSTAND", "PLAN",
        "TEST", "ADVISORY", "JUDGMENT", "EVIDENCE",
        "MYENG", "AGENT", "LONG",
    ]


def _capability_labels() -> list[str]:
    """Return human-readable capability labels."""
    return [
        "Architecture", "Debugging", "Coding", "Understanding", "Planning",
        "Testing", "Advisory", "Judgment", "Evidence",
        "MY Engineering", "Agentic", "Long Horizon",
    ]


def _capability_label(cap_key: str) -> str:
    """Map capability key to human-readable label."""
    labels = {
        "ARCH": "Architecture",
        "DEBUG": "Debugging",
        "CODE": "Coding",
        "UNDERSTAND": "Understanding",
        "PLAN": "Planning",
        "TEST": "Testing",
        "ADVISORY": "Advisory",
        "JUDGMENT": "Judgment",
        "EVIDENCE": "Evidence",
        "MYENG": "MY Engineering",
        "AGENT": "Agentic",
        "LONG": "Long Horizon",
    }
    return labels.get(cap_key, cap_key)


def write_report_files(
    artifact_dir: str,
    run_id: str,
    human_text: str,
    machine_data: dict[str, Any],
) -> dict[str, str]:
    """
    Write report files to the artifact directory.

    Parameters
    ----------
    artifact_dir : str
        Path to the run's artifact directory.
    run_id : str
        Run identifier.
    human_text : str
        Human-readable report text.
    machine_data : dict
        Machine-readable report data.

    Returns
    -------
    dict mapping filename → written path.
    """
    import os
    paths = {}

    # Human-readable report
    report_path = os.path.join(artifact_dir, "report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(human_text)
    paths["report.txt"] = report_path

    # Machine-readable report (JSON)
    machine_path = os.path.join(artifact_dir, "report.json")
    with open(machine_path, "w", encoding="utf-8") as f:
        import json
        json.dump(machine_data, f, indent=2, ensure_ascii=False)
    paths["report.json"] = machine_path

    return paths
