#!/usr/bin/env python3
"""
exact.py — Deterministic exact-match evaluator for the EffNine Benchmark (EB).

Supports:
  - exact string match
  - acceptable answers list
  - explicit normalization rules (exact, trim, lowercase, whitespace)

Normalization is NEVER applied silently. It must be explicitly configured.
If no expected answer exists, returns NOT_APPLICABLE.
"""

from __future__ import annotations

import re
from typing import Any

from ..core.schema import EvaluatorResult, Task, TaskResult
from ..core.types import EvaluatorStatus, JudgeMode
from .base import Evaluator


class ExactEvaluator(Evaluator):
    """
    Deterministic exact-match evaluator.

    Parameters (from task.context or evaluation parameters):
      - expected: str — the expected answer
      - acceptable_answers: list[str] — alternative accepted answers
      - normalization: str — one of 'exact', 'trim', 'lowercase', 'whitespace'
                         default: 'trim' (only when expected is present)
    """

    @property
    def name(self) -> str:
        return "exact"

    @property
    def authority_level(self) -> int:
        return 1  # Highest authority — deterministic evidence

    @property
    def supported_modes(self) -> list[JudgeMode]:
        return [JudgeMode.DETERMINISTIC]

    def is_applicable(self, task: Task) -> bool:
        """Applicable when an expected or acceptable answer is configured."""
        ctx = task.context
        params = None
        # Check task-level evaluation params first
        for ev_spec in task.evaluation.evaluators:
            if ev_spec.get("type") == "exact":
                params = ev_spec.get("parameters", {})
                break
        if params is None:
            params = {}

        has_expected = bool(params.get("expected") or ctx.get("expected") or ctx.get("answer"))
        has_acceptable = bool(params.get("acceptable_answers") or ctx.get("acceptable_answers"))
        return has_expected or has_acceptable

    def evaluate(self, task: Task, result: TaskResult) -> EvaluatorResult:
        response = (result.raw_response or "").strip()

        # Resolve parameters: spec params > context
        params = self._resolve_params(task)

        expected = params.get("expected") or task.context.get("expected") or task.context.get("answer")
        acceptable = params.get("acceptable_answers") or task.context.get("acceptable_answers")
        normalization = params.get("normalization", "trim")

        if expected is None and not acceptable:
            return EvaluatorResult(
                evaluator="exact",
                mode=JudgeMode.DETERMINISTIC,
                status=EvaluatorStatus.NOT_APPLICABLE,
                rationale="No expected answer or acceptable answers configured for this task",
                flags=["no_expected_answer"],
            )

        normalized_response = self._normalize(response, normalization)
        normalized_expected = self._normalize(str(expected), normalization) if expected else None

        # Check acceptable answers first
        if acceptable:
            norm_acceptable = [self._normalize(a, normalization) for a in acceptable]
            if normalized_response in norm_acceptable:
                return EvaluatorResult(
                    evaluator="exact",
                    mode=JudgeMode.DETERMINISTIC,
                    status=EvaluatorStatus.PASS,
                    score=1.0,
                    max_score=1.0,
                    normalized_score=1.0,
                    rationale="Response matches an acceptable answer",
                    evidence=[f"acceptable_match: {normalized_response[:200]}"],
                )
            # Not in acceptable list — fail if no expected to check against
            if normalized_expected is None:
                return EvaluatorResult(
                    evaluator="exact",
                    mode=JudgeMode.DETERMINISTIC,
                    status=EvaluatorStatus.FAIL,
                    score=0.0,
                    max_score=1.0,
                    normalized_score=0.0,
                    rationale="Response does not match any acceptable answer",
                    evidence=[f"response: {normalized_response[:200]}"],
                    flags=["not_in_acceptable_list"],
                )
            # Have both acceptable and expected — continue to expected check

        # Check against expected
        if normalized_expected is not None:
            if normalized_response == normalized_expected:
                return EvaluatorResult(
                    evaluator="exact",
                    mode=JudgeMode.DETERMINISTIC,
                    status=EvaluatorStatus.PASS,
                    score=1.0,
                    max_score=1.0,
                    normalized_score=1.0,
                    rationale="Response matches expected answer exactly",
                    evidence=[f"exact_match: {normalized_response[:200]}"],
                )
            else:
                return EvaluatorResult(
                    evaluator="exact",
                    mode=JudgeMode.DETERMINISTIC,
                    status=EvaluatorStatus.FAIL,
                    score=0.0,
                    max_score=1.0,
                    normalized_score=0.0,
                    rationale=f"Response does not match expected answer",
                    evidence=[
                        f"expected: {normalized_expected[:200]}",
                        f"got: {normalized_response[:200]}",
                    ],
                    flags=["expected_mismatch"],
                )

        return EvaluatorResult(
            evaluator="exact",
            mode=JudgeMode.DETERMINISTIC,
            status=EvaluatorStatus.NOT_APPLICABLE,
            rationale="No resolvable expected answer found",
            flags=["no_expected_answer"],
        )

    def _normalize(self, text: str, method: str) -> str:
        """
        Apply explicit normalization. Only normalizes when method is specified.
        Supported: 'exact', 'trim', 'lowercase', 'whitespace'.
        """
        if method == "exact":
            return text
        elif method == "trim":
            return text.strip()
        elif method == "lowercase":
            return text.strip().lower()
        elif method == "whitespace":
            return re.sub(r"\s+", " ", text.strip())
        else:
            # Unknown normalization method — fall back to trim
            return text.strip()

    def _resolve_params(self, task: Task) -> dict[str, Any]:
        """Extract exact evaluator parameters from task evaluation config or context."""
        # Check explicit evaluator specs first
        for ev_spec in task.evaluation.evaluators:
            if ev_spec.get("type") == "exact":
                return ev_spec.get("parameters", {})
        # Fall back to context
        return {}
