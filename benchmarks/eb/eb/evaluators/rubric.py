#!/usr/bin/env python3
"""
rubric.py — Structured rubric evaluation for the EffNine Benchmark (EB).

Stage 3 does NOT use a cloud model. The rubric evaluator represents a
structured rubric and provides deterministic aggregation hooks.

Supports:
  - criterion definitions with weights
  - manually/reference-supplied criterion scores
  - deterministic criterion checks (presence/absence of expected strings)

For rubrics that require a judge model, produces explicit
evaluator_status = PENDING_JUDGE so Stage 4 cloud judge integration
can consume the scaffold.

Never invents criterion scores from natural language.
"""

from __future__ import annotations

from typing import Any

from ..core.schema import EvaluatorResult, Task, TaskResult
from ..core.types import EvaluatorStatus, JudgeMode
from .base import Evaluator


class RubricEvaluator(Evaluator):
    """
    Structured rubric evaluator (deterministic scaffold only).

    If criteria have explicit reference scores, they are used.
    If criteria require judgment, status is PENDING_JUDGE.
    """

    @property
    def name(self) -> str:
        return "rubric"

    @property
    def authority_level(self) -> int:
        return 2  # Below deterministic evidence, above cloud judge

    @property
    def supported_modes(self) -> list[JudgeMode]:
        return [JudgeMode.RUBRIC, JudgeMode.DETERMINISTIC]

    def is_applicable(self, task: Task) -> bool:
        params = self._resolve_params(task)
        has_criteria = bool(params.get("criteria"))
        has_pending = bool(params.get("_pending_judge"))
        # Always applicable — may produce PENDING_JUDGE or deterministic result
        return True

    def evaluate(self, task: Task, result: TaskResult) -> EvaluatorResult:
        params = self._resolve_params(task)
        criteria = params.get("criteria") or []
        weights = params.get("weights", {})
        pending_judge = bool(params.get("_pending_judge"))

        if pending_judge and not criteria:
            return EvaluatorResult(
                evaluator="rubric",
                mode=JudgeMode.RUBRIC,
                status=EvaluatorStatus.PENDING_JUDGE,
                rationale="Rubric requires cloud judge model (Stage 4+). No deterministic criteria defined.",
                flags=["pending_judge"],
                details={"criteria_count": 0, "requires_judge": True},
            )

        if not criteria:
            return EvaluatorResult(
                evaluator="rubric",
                mode=JudgeMode.RUBRIC,
                status=EvaluatorStatus.NOT_APPLICABLE,
                rationale="No criteria defined for rubric evaluation",
                flags=["no_criteria"],
            )

        # Process each criterion
        criterion_results: list[dict[str, Any]] = []
        total_weight = 0.0
        weighted_score = 0.0
        pending_criteria: list[str] = []

        for criterion in criteria:
            crit_name = criterion.get("id", criterion.get("name", "unknown"))
            crit_weight = float(criterion.get("weight", weights.get(crit_name, 1.0)))
            crit_score = criterion.get("score")  # Reference/manual score
            crit_check = criterion.get("check")   # Deterministic check spec
            crit_requires_judge = bool(criterion.get("requires_judge", False))

            total_weight += crit_weight

            if crit_score is not None:
                # Manual/reference score provided
                weighted_score += crit_score * crit_weight
                criterion_results.append({
                    "criterion": crit_name,
                    "score": crit_score,
                    "weight": crit_weight,
                    "weighted": crit_score * crit_weight,
                    "source": "reference_score",
                })
            elif crit_requires_judge:
                pending_criteria.append(crit_name)
                criterion_results.append({
                    "criterion": crit_name,
                    "score": None,
                    "weight": crit_weight,
                    "source": "pending_judge",
                })
            elif crit_check:
                # Deterministic check
                score, passed, evidence = self._check_criterion(response=result.raw_response or "", check=crit_check)
                weighted_score += score * crit_weight
                criterion_results.append({
                    "criterion": crit_name,
                    "score": score,
                    "weight": crit_weight,
                    "weighted": score * crit_weight,
                    "source": "deterministic_check",
                    "evidence": evidence,
                })
            else:
                # No score, no check, not pending — treat as missing
                pending_criteria.append(crit_name)
                criterion_results.append({
                    "criterion": crit_name,
                    "score": None,
                    "weight": crit_weight,
                    "source": "missing",
                })

        if pending_criteria:
            return EvaluatorResult(
                evaluator="rubric",
                mode=JudgeMode.RUBRIC,
                status=EvaluatorStatus.PENDING_JUDGE,
                rationale=f"Rubric has {len(pending_criteria)}/{len(criteria)} criteria requiring judge: {pending_criteria}",
                flags=["pending_judge", f"{len(pending_criteria)}_criteria_pending"],
                details={
                    "criterion_results": criterion_results,
                    "total_weight": total_weight,
                    "partial_score": weighted_score,
                    "pending_criteria": pending_criteria,
                    "completed_criteria": len(criteria) - len(pending_criteria),
                },
            )

        if total_weight == 0:
            return EvaluatorResult(
                evaluator="rubric",
                mode=JudgeMode.RUBRIC,
                status=EvaluatorStatus.NOT_APPLICABLE,
                rationale="Total criterion weight is zero",
                flags=["zero_weight"],
            )

        normalized_score = weighted_score / total_weight
        all_scores_valid = all(
            cr.get("score") is not None for cr in criterion_results
        )

        if not all_scores_valid:
            status = EvaluatorStatus.PENDING
            rationale = "Some criteria lack scores"
        elif normalized_score >= 0.5:
            status = EvaluatorStatus.PASS
            rationale = f"Rubric score {normalized_score:.3f} >= 0.5 threshold"
        else:
            status = EvaluatorStatus.FAIL
            rationale = f"Rubric score {normalized_score:.3f} < 0.5 threshold"

        return EvaluatorResult(
            evaluator="rubric",
            mode=JudgeMode.RUBRIC,
            status=status,
            score=normalized_score,
            max_score=1.0,
            normalized_score=normalized_score,
            rationale=rationale,
            evidence=[f"criterion_{cr['criterion']}={cr['score']}" for cr in criterion_results if cr.get("score") is not None],
            details={
                "criterion_results": criterion_results,
                "total_weight": total_weight,
                "raw_weighted_score": weighted_score,
            },
        )

    def _check_criterion(self, response: str, check: dict[str, Any]) -> tuple[float, bool, list[str]]:
        """
        Execute a deterministic criterion check.
        Supported check types:
          - {"type": "contains", "value": "expected string"}
          - {"type": "not_contains", "value": "forbidden string"}
          - {"type": "regex", "pattern": "regex"}
          - {"type": "min_length", "value": N}
          - {"type": "max_length", "value": N}
        """
        check_type = check.get("type", "")
        case_insensitive = check.get("case_insensitive", True)

        text = response.lower() if case_insensitive else response

        if check_type == "contains":
            value = check.get("value", "")
            if case_insensitive:
                value = value.lower()
            if value in text:
                return 1.0, True, [f"contains '{value[:50]}'"]
            return 0.0, False, [f"missing required content: '{value[:50]}'"]

        if check_type == "not_contains":
            value = check.get("value", "")
            if case_insensitive:
                value = value.lower()
            if value not in text:
                return 1.0, True, [f"does not contain forbidden '{value[:50]}'"]
            return 0.0, False, [f"contains forbidden content: '{value[:50]}'"]

        if check_type == "regex":
            import re as _re
            pattern = check.get("pattern", "")
            if _re.search(pattern, text):
                return 1.0, True, [f"matches regex '{pattern}'"]
            return 0.0, False, [f"does not match regex '{pattern}'"]

        if check_type == "min_length":
            min_len = check.get("value", 0)
            if len(response) >= min_len:
                return 1.0, True, [f"length {len(response)} >= {min_len}"]
            return 0.0, False, [f"length {len(response)} < {min_len}"]

        if check_type == "max_length":
            max_len = check.get("value", 0)
            if len(response) <= max_len:
                return 1.0, True, [f"length {len(response)} <= {max_len}"]
            return 0.0, False, [f"length {len(response)} > {max_len}"]

        return 0.0, False, [f"unknown check type: {check_type}"]

    def _resolve_params(self, task: Task) -> dict[str, Any]:
        for ev_spec in task.evaluation.evaluators:
            if ev_spec.get("type") == "rubric":
                return ev_spec.get("parameters", {})
        return {}
