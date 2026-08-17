#!/usr/bin/env python3
"""
raw.py — Raw score collection and aggregation for the EffNine Benchmark (EB).

Stage 3: collects per-task raw scores, aggregates repeated runs,
aggregates by capability/category.

Does NOT normalize to 1000. Does NOT compute EB Score.
Uses terminology: raw_mean, raw_median, raw_stddev, raw_min, raw_max, raw_error_percent.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from ..core.schema import EvaluatorResult, TaskResult
from ..core.types import Capability, EvaluatorStatus


# ---------------------------------------------------------------------------
# Task-level aggregation
# ---------------------------------------------------------------------------


@dataclass
class TaskRawScore:
    """Aggregated raw score for a single task across repeats."""

    task_id: str
    repeat_scores: list[float] = field(default_factory=list)
    repeat_statuses: list[str] = field(default_factory=list)
    evaluator_results: list[EvaluatorResult] = field(default_factory=list)

    # Aggregated stats
    raw_mean: float | None = None
    raw_median: float | None = None
    raw_stddev: float | None = None
    raw_min: float | None = None
    raw_max: float | None = None
    raw_error_percent: float | None = None
    task_count: int = 0
    error_count: int = 0
    applicable_count: int = 0

    def add_repeat(self, score: float | None, status: str, eval_results: list[EvaluatorResult]) -> None:
        """Add a single repeat result."""
        if score is not None:
            self.repeat_scores.append(score)
        self.repeat_statuses.append(status)
        self.evaluator_results.extend(eval_results)
        self.task_count += 1
        if status in (EvaluatorStatus.ERROR.value, "ERROR"):
            self.error_count += 1
        if status not in (EvaluatorStatus.NOT_APPLICABLE.value, EvaluatorStatus.UNSUPPORTED.value, "NOT_APPLICABLE", "UNSUPPORTED"):
            self.applicable_count += 1

    def compute(self) -> None:
        """Compute aggregate statistics from repeat scores."""
        if not self.repeat_scores:
            return

        n = len(self.repeat_scores)
        self.raw_mean = sum(self.repeat_scores) / n
        sorted_scores = sorted(self.repeat_scores)
        if n % 2 == 0:
            self.raw_median = (sorted_scores[n // 2 - 1] + sorted_scores[n // 2]) / 2
        else:
            self.raw_median = sorted_scores[n // 2]

        if n > 1:
            variance = sum((s - self.raw_mean) ** 2 for s in self.repeat_scores) / (n - 1)
            self.raw_stddev = variance ** 0.5
        else:
            self.raw_stddev = 0.0

        self.raw_min = min(self.repeat_scores)
        self.raw_max = max(self.repeat_scores)

        if self.raw_mean is not None and self.raw_mean != 0:
            self.raw_error_percent = (self.raw_stddev / self.raw_mean) * 100

    @property
    def has_data(self) -> bool:
        return len(self.repeat_scores) > 0


# ---------------------------------------------------------------------------
# Capability-level aggregation
# ---------------------------------------------------------------------------


@dataclass
class CapabilityRawScore:
    """Raw aggregated score for a single capability."""

    capability: Capability
    task_scores: list[TaskRawScore] = field(default_factory=list)

    # Aggregated stats
    raw_mean: float | None = None
    raw_median: float | None = None
    raw_stddev: float | None = None
    raw_min: float | None = None
    raw_max: float | None = None
    raw_error_percent: float | None = None
    task_count: int = 0
    error_count: int = 0

    def compute(self) -> None:
        """Compute aggregate statistics from task scores."""
        scores = [t.raw_mean for t in self.task_scores if t.raw_mean is not None]
        if not scores:
            return

        n = len(scores)
        self.raw_mean = sum(scores) / n
        sorted_scores = sorted(scores)
        if n % 2 == 0:
            self.raw_median = (sorted_scores[n // 2 - 1] + sorted_scores[n // 2]) / 2
        else:
            self.raw_median = sorted_scores[n // 2]

        if n > 1:
            variance = sum((s - self.raw_mean) ** 2 for s in scores) / (n - 1)
            self.raw_stddev = variance ** 0.5
        else:
            self.raw_stddev = 0.0

        self.raw_min = min(scores)
        self.raw_max = max(scores)

        if self.raw_mean is not None and self.raw_mean != 0:
            self.raw_error_percent = (self.raw_stddev / self.raw_mean) * 100

        self.task_count = n
        self.error_count = sum(t.error_count for t in self.task_scores)

    @property
    def has_data(self) -> bool:
        return len([t for t in self.task_scores if t.has_data]) > 0


# ---------------------------------------------------------------------------
# Run-level aggregation
# ---------------------------------------------------------------------------


@dataclass
class RunRawScores:
    """
    Complete raw score aggregation for a benchmark run.

    Collects per-task raw scores, aggregates by capability,
    and preserves repeat-level data.
    """

    run_id: str
    task_scores: dict[str, TaskRawScore] = field(default_factory=dict)
    capability_scores: dict[str, CapabilityRawScore] = field(default_factory=dict)
    all_evaluator_results: list[EvaluatorResult] = field(default_factory=list)

    # Overall stats
    overall_raw_mean: float | None = None
    overall_task_count: int = 0
    overall_error_count: int = 0
    overall_applicable_count: int = 0

    def add_task_result(self, task_result: TaskResult, task_capabilities: list[Capability]) -> None:
        """Add a single task result to the aggregation."""
        task_id = task_result.task_id

        if task_id not in self.task_scores:
            self.task_scores[task_id] = TaskRawScore(task_id=task_id)

        task_score = self.task_scores[task_id]

        # Collect the best applicable evaluator score
        best_score = self._best_evaluator_score(task_result.evaluator_results)
        best_status = self._best_evaluator_status(task_result.evaluator_results)

        task_score.add_repeat(
            score=best_score,
            status=best_status,
            eval_results=task_result.evaluator_results,
        )

        # Track evaluator results globally
        self.all_evaluator_results.extend(task_result.evaluator_results)

        # Aggregate by capability (primary_capability policy: use first capability)
        if task_capabilities:
            primary_cap = task_capabilities[0]
            cap_key = primary_cap.value
            if cap_key not in self.capability_scores:
                self.capability_scores[cap_key] = CapabilityRawScore(capability=primary_cap)
            self.capability_scores[cap_key].task_scores.append(task_score)

        self.overall_task_count += 1
        if best_status == "ERROR":
            self.overall_error_count += 1
        if best_status not in ("NOT_APPLICABLE", "UNSUPPORTED"):
            self.overall_applicable_count += 1

    def compute(self) -> None:
        """Compute all aggregations."""
        for task_score in self.task_scores.values():
            task_score.compute()

        for cap_score in self.capability_scores.values():
            cap_score.compute()

        # Overall: mean of task means
        task_means = [t.raw_mean for t in self.task_scores.values() if t.raw_mean is not None]
        if task_means:
            self.overall_raw_mean = sum(task_means) / len(task_means)

    def get_task_raw_score(self, task_id: str) -> float | None:
        """Get the aggregated raw score for a specific task."""
        ts = self.task_scores.get(task_id)
        return ts.raw_mean if ts else None

    @staticmethod
    def _best_evaluator_score(results: list[EvaluatorResult]) -> float | None:
        """
        Select the best applicable evaluator score respecting authority.
        Higher authority_level wins. Among same authority, higher score wins.
        """
        applicable = [r for r in results if r.is_applicable and r.score is not None]
        if not applicable:
            return None
        # Sort by authority_level desc, then score desc
        applicable.sort(key=lambda r: (r.authoritative_level, r.score or 0), reverse=True)
        return applicable[0].score

    @staticmethod
    def _best_evaluator_status(results: list[EvaluatorResult]) -> str:
        """Get the status from the best applicable evaluator."""
        applicable = [r for r in results if r.is_applicable and r.status not in (
            EvaluatorStatus.NOT_APPLICABLE.value, EvaluatorStatus.UNSUPPORTED.value
        )]
        if not applicable:
            # Return the status of the most authoritative evaluator
            if results:
                results_sorted = sorted(results, key=lambda r: r.authoritative_level, reverse=True)
                return results_sorted[0].status
            return "UNKNOWN"
        applicable.sort(key=lambda r: r.authoritative_level, reverse=True)
        return applicable[0].status


# ---------------------------------------------------------------------------
# Aggregation strategy helpers
# ---------------------------------------------------------------------------


def aggregate_task_evaluator_results(
    results: list[EvaluatorResult],
    strategy: str = "single_authoritative",
) -> float | None:
    """
    Apply an aggregation strategy to combine multiple evaluator results
    into a single task raw score.

    Strategies:
      - single_authoritative: use the highest-authority applicable result
      - weighted: weighted average based on authority_level (higher = more weight)
      - all_required: require ALL evaluators to pass; score is min of all
      - any_required: any single pass is sufficient; score is max of all
    """
    applicable = [r for r in results if r.is_applicable and r.score is not None]

    if not applicable:
        return None

    if strategy == "single_authoritative":
        applicable.sort(key=lambda r: r.authoritative_level, reverse=True)
        return applicable[0].score

    if strategy == "weighted":
        total_weight = 0.0
        weighted_sum = 0.0
        for r in applicable:
            w = r.authoritative_level
            total_weight += w
            weighted_sum += (r.score or 0) * w
        if total_weight == 0:
            return None
        return weighted_sum / total_weight

    if strategy == "all_required":
        # All must pass (score >= 0.5)
        min_score = min(r.score or 0 for r in applicable)
        return min_score

    if strategy == "any_required":
        max_score = max(r.score or 0 for r in applicable)
        return max_score

    # Unknown strategy: fall back to single_authoritative
    applicable.sort(key=lambda r: r.authoritative_level, reverse=True)
    return applicable[0].score
