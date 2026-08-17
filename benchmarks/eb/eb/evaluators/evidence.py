#!/usr/bin/env python3
"""
evidence.py — Structured evidence verification for the EffNine Benchmark (EB).

Verifies explicitly structured evidence requirements using deterministic
matching/extraction only. Does NOT perform semantic LLM judging.

Supports:
  - required_claims: list[str] — claims that must appear in response
  - forbidden_claims: list[str] — claims that must NOT appear
  - expected_facts: list[str] — facts that must be present

When deterministic evidence verification is insufficient, returns
NOT_APPLICABLE or UNSUPPORTED rather than inventing a score.
"""

from __future__ import annotations

import re
from typing import Any

from ..core.schema import EvaluatorResult, Task, TaskResult
from ..core.types import EvaluatorStatus, JudgeMode
from .base import Evaluator


class EvidenceEvaluator(Evaluator):
    """
    Deterministic evidence evaluator.

    Operates on machine-checkable/reference evidence only.
    Returns NOT_APPLICABLE when deterministic verification is insufficient.
    """

    @property
    def name(self) -> str:
        return "evidence"

    @property
    def authority_level(self) -> int:
        return 1  # Deterministic evidence

    @property
    def supported_modes(self) -> list[JudgeMode]:
        return [JudgeMode.DETERMINISTIC]

    def is_applicable(self, task: Task) -> bool:
        ctx = task.context
        params = self._resolve_params(task)

        has_required = bool(params.get("required_claims") or ctx.get("required_claims"))
        has_forbidden = bool(params.get("forbidden_claims") or ctx.get("forbidden_claims"))
        has_facts = bool(params.get("expected_facts") or ctx.get("expected_facts"))

        return has_required or has_forbidden or has_facts

    def evaluate(self, task: Task, result: TaskResult) -> EvaluatorResult:
        response = result.raw_response or ""
        params = self._resolve_params(task)
        ctx = task.context

        required_claims = params.get("required_claims") or ctx.get("required_claims") or []
        forbidden_claims = params.get("forbidden_claims") or ctx.get("forbidden_claims") or []
        expected_facts = params.get("expected_facts") or ctx.get("expected_facts") or []

        if not required_claims and not forbidden_claims and not expected_facts:
            return EvaluatorResult(
                evaluator="evidence",
                mode=JudgeMode.DETERMINISTIC,
                status=EvaluatorStatus.NOT_APPLICABLE,
                rationale="No evidence requirements configured",
                flags=["no_evidence_requirements"],
            )

        checks_passed: list[str] = []
        checks_failed: list[str] = []
        scores: list[float] = []

        if required_claims:
            score, passed, evidence = self._check_required_claims(response, required_claims)
            scores.append(score)
            if passed:
                checks_passed.append(f"required_claims ({len(required_claims)}/{len(required_claims)})")
            else:
                checks_failed.extend(evidence)

        if forbidden_claims:
            score, passed, evidence = self._check_forbidden_claims(response, forbidden_claims)
            scores.append(score)
            if passed:
                checks_passed.append(f"forbidden_claims ({len(forbidden_claims)} checked)")
            else:
                checks_failed.extend(evidence)

        if expected_facts:
            score, passed, evidence = self._check_expected_facts(response, expected_facts)
            scores.append(score)
            if passed:
                checks_passed.append(f"expected_facts ({len(expected_facts)}/{len(expected_facts)})")
            else:
                checks_failed.extend(evidence)

        if not checks_passed and not checks_failed:
            return EvaluatorResult(
                evaluator="evidence",
                mode=JudgeMode.DETERMINISTIC,
                status=EvaluatorStatus.NOT_APPLICABLE,
                rationale="No resolvable evidence requirements",
                flags=["no_evidence_to_check"],
            )

        all_passed = len(checks_failed) == 0
        avg_score = sum(scores) / len(scores) if scores else (1.0 if all_passed else 0.0)

        status = EvaluatorStatus.PASS if all_passed else EvaluatorStatus.FAIL

        return EvaluatorResult(
            evaluator="evidence",
            mode=JudgeMode.DETERMINISTIC,
            status=status,
            score=avg_score,
            max_score=1.0,
            normalized_score=avg_score,
            rationale=f"Evidence: {'all checks passed' if all_passed else f'{len(checks_failed)} check(s) failed'}",
            evidence=checks_passed + checks_failed,
            flags=checks_failed if checks_failed else [],
            details={
                "required_claims_checked": required_claims,
                "forbidden_claims_checked": forbidden_claims,
                "expected_facts_checked": expected_facts,
                "checks_passed": checks_passed,
                "checks_failed": checks_failed,
            },
        )

    def _check_required_claims(self, response: str, claims: list[str]) -> tuple[float, bool, list[str]]:
        """Check that all required claims appear in the response."""
        response_lower = response.lower()
        missing = []
        for claim in claims:
            claim_lower = claim.lower()
            if claim_lower not in response_lower:
                missing.append(claim)

        if not missing:
            return 1.0, True, [f"all {len(claims)} required claims present"]

        ratio = (len(claims) - len(missing)) / len(claims)
        return ratio, False, [
            f"missing required claims ({len(missing)}/{len(claims)}): {missing[:5]}"
        ]

    def _check_forbidden_claims(self, response: str, claims: list[str]) -> tuple[float, bool, list[str]]:
        """Check that no forbidden claims appear in the response."""
        response_lower = response.lower()
        violations = []
        for claim in claims:
            claim_lower = claim.lower()
            if claim_lower in response_lower:
                violations.append(claim)

        if not violations:
            return 1.0, True, [f"no forbidden claims found ({len(claims)} checked)"]

        return 0.0, False, [
            f"forbidden claims found ({len(violations)}/{len(claims)}): {violations[:5]}"
        ]

    def _check_expected_facts(self, response: str, facts: list[str]) -> tuple[float, bool, list[str]]:
        """Check that expected facts are present in the response."""
        response_lower = response.lower()
        present = 0
        for fact in facts:
            fact_lower = fact.lower()
            if fact_lower in response_lower:
                present += 1

        ratio = present / len(facts) if facts else 1.0
        passed = ratio >= 0.5
        return ratio, passed, [f"{present}/{len(facts)} expected facts present"]

    def _resolve_params(self, task: Task) -> dict[str, Any]:
        for ev_spec in task.evaluation.evaluators:
            if ev_spec.get("type") == "evidence":
                return ev_spec.get("parameters", {})
        return {}
