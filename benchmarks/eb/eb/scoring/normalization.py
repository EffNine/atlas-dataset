#!/usr/bin/env python3
"""
normalization.py — Baseline compatibility validation and normalization.

Stage 5: Validates that a trained-model run and a baseline run are
compatible for normalization. Refuses to compare incompatible runs.

Compatibility fields checked:
    benchmark_version
    task_set_version
    suite
    partitions
    task_set_hash
    scoring_version
    evaluator_config_version
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.schema import BaselineRecord, BenchmarkRun
from .eb_score import SCORING_VERSION


# ---------------------------------------------------------------------------
# Compatibility validation
# ---------------------------------------------------------------------------


@dataclass
class CompatibilityCheck:
    """Result of a baseline compatibility check."""

    compatible: bool
    mismatches: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def errors(self) -> list[str]:
        return [
            f"{field_name}: {actual} != {expected}"
            for field_name, actual, expected in self.mismatches
        ]


def validate_compatibility(
    run: BenchmarkRun,
    baseline: BaselineRecord,
    *,
    strict: bool = True,
) -> CompatibilityCheck:
    """
    Validate that a benchmark run is compatible with a baseline for normalization.

    Checks performed:
        1. benchmark_version must match exactly
        2. task_set_version must match exactly
        3. suite must match exactly
        4. partitions must be compatible
        5. task_set_hash must match (from manifest)
        6. scoring_version must match

    Parameters
    ----------
    run : BenchmarkRun
        The trained model's benchmark run.
    baseline : BaselineRecord
        The base model baseline record.
    strict : bool
        If True, all checks must pass. If False, warnings are issued instead of failures.

    Returns
    -------
    CompatibilityCheck with compatible flag and list of mismatches.
    """
    mismatches: list[tuple[str, str, str]] = []

    # 1. Benchmark version
    if run.benchmark_version != baseline.benchmark_version:
        mismatches.append((
            "benchmark_version",
            run.benchmark_version,
            baseline.benchmark_version,
        ))

    # 2. Task set version
    if run.task_set_version != baseline.task_set_version:
        mismatches.append((
            "task_set_version",
            run.task_set_version,
            baseline.task_set_version,
        ))

    # 3. Suite
    if run.suite != getattr(baseline, "suite", run.suite):
        mismatches.append((
            "suite",
            run.suite,
            getattr(baseline, "suite", "unknown"),
        ))

    # 4. Partitions
    run_partitions = sorted(p.value for p in run.partitions)
    baseline_part = getattr(baseline, "partitions", None)
    if baseline_part is not None and len(baseline_part) > 0:
        baseline_partitions = sorted(baseline_part)
        if run_partitions != baseline_partitions:
            mismatches.append((
                "partitions",
                ",".join(run_partitions),
                ",".join(baseline_partitions),
            ))

    # 5. Task set hash
    run_task_hash = getattr(run, "task_set_hash", None)
    baseline_task_hash = getattr(baseline, "task_set_hash", None)
    if run_task_hash is not None and baseline_task_hash is not None:
        if run_task_hash != baseline_task_hash:
            mismatches.append((
                "task_set_hash",
                run_task_hash,
                baseline_task_hash,
            ))

    # 6. Scoring version
    baseline_scoring = getattr(baseline, "scoring_version", None) or SCORING_VERSION
    if baseline_scoring != SCORING_VERSION:
        mismatches.append((
            "scoring_version",
            SCORING_VERSION,
            baseline_scoring,
        ))

    # 7. Evaluator config version
    run_eval_version = getattr(run, "evaluator_config_version", None)
    baseline_eval_version = getattr(baseline, "evaluator_config_version", None)
    if run_eval_version is not None and baseline_eval_version is not None:
        if run_eval_version != baseline_eval_version:
            mismatches.append((
                "evaluator_config_version",
                run_eval_version,
                baseline_eval_version,
            ))

    compatible = len(mismatches) == 0
    return CompatibilityCheck(compatible=compatible, mismatches=mismatches)


def resolve_baseline(
    run: BenchmarkRun,
    baselines: list[BaselineRecord],
) -> BaselineRecord | None:
    """
    Resolve the best matching baseline for a run.

    Priority:
        1. Baseline with matching base_model_name AND benchmark_version
        2. Among those, the one with highest compatibility score

    Parameters
    ----------
    run : BenchmarkRun
        The run to find a baseline for.
    baselines : list[BaselineRecord]
        Available baselines.

    Returns
    -------
    The best matching BaselineRecord, or None if no compatible baseline exists.
    """
    candidates: list[tuple[BaselineRecord, int]] = []

    for bl in baselines:
        # Quick filter: must match base model name
        if bl.base_model_name != run.base_model.name:
            continue
        # Quick filter: must match benchmark version
        if bl.benchmark_version != run.benchmark_version:
            continue

        check = validate_compatibility(run, bl)
        if check.compatible:
            candidates.append((bl, 0))  # Perfect match
        else:
            candidates.append((bl, len(check.mismatches)))

    if not candidates:
        return None

    # Sort by compatibility score (fewer mismatches first)
    candidates.sort(key=lambda x: x[1])
    best = candidates[0]
    if best[1] > 0 and strict_mode():
        return None
    return best[0]


def strict_mode() -> bool:
    """Check if strict compatibility mode is enabled."""
    import os
    return os.environ.get("EB_STRICT_COMPATIBILITY", "true").lower() in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def normalize_run_against_baseline(
    run: BenchmarkRun,
    baseline: BaselineRecord,
) -> tuple[BenchmarkRun, CompatibilityCheck]:
    """
    Validate compatibility between a run and baseline.

    This checks compatibility but does not modify the run in place.
    Call compute_eb_score separately for the actual computation.

    Parameters
    ----------
    run : BenchmarkRun
        The trained model's run.
    baseline : BaselineRecord
        The baseline record.

    Returns
    -------
    Tuple of (run, compatibility_check).
    Raises ValueError if incompatible.
    """
    check = validate_compatibility(run, baseline)
    if not check.compatible:
        raise ValueError(
            f"Incompatible baseline for normalization.\n"
            f"Mismatches: {check.errors}"
        )
    return run, check
