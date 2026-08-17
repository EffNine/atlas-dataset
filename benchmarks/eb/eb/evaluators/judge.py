#!/usr/bin/env python3
"""
judge.py — Cloud AI judge evaluator for the EffNine Benchmark (EB).

Stage 4: Implements the Evaluator interface for cloud-based judgment.
Receives task + model response + rubric, routes to selected judge model(s),
calls the Conductor gateway, parses structured output, and returns
an EvaluatorResult compatible with Stage 3's pipeline.

Authority level: 3 (below rubric, above AI opinion).
Cloud judge NEVER overrides a higher-authority deterministic result.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..core.schema import (
    EvaluatorResult,
    JudgeResult,
    Task,
    TaskJudgeConfig,
    TaskResult,
)
from ..core.types import EvaluatorStatus, JudgeMode
from ..judges.client import (
    JudgeAuthenticationError,
    JudgeClient,
    JudgeClientError,
    JudgeRateLimitError,
    JudgeTimeoutError,
)
from ..judges.consensus import compute_consensus
from ..judges.prompt_builder import JudgePromptBuilder
from ..judges.profiler import JudgeProfiler
from ..judges.router import JudgeRouter
from .base import Evaluator


class JudgeEvaluator(Evaluator):
    """
    Cloud AI judge evaluator.

    For tasks where deterministic and rubric evaluators cannot produce
    a definitive score, this evaluator routes to one or more cloud
    judge models via the Conductor gateway and aggregates their results
    via consensus.
    """

    @property
    def name(self) -> str:
        return "judge"

    @property
    def authority_level(self) -> int:
        return 3  # Below rubric (2), above AI opinion (4)

    @property
    def supported_modes(self) -> list[JudgeMode]:
        return [JudgeMode.CLOUD_JUDGE, JudgeMode.RUBRIC]

    def __init__(
        self,
        client: JudgeClient | None = None,
        router: JudgeRouter | None = None,
        profiler: JudgeProfiler | None = None,
        prompt_builder: JudgePromptBuilder | None = None,
    ) -> None:
        self._client = client
        self._router = router or JudgeRouter()
        self._profiler = profiler or JudgeProfiler()
        self._prompt_builder = prompt_builder or JudgePromptBuilder()
        self._last_selection: dict[str, Any] = {}

    def is_applicable(self, task: Task) -> bool:
        """Applicable when the task requires a judge (CLOUD_JUDGE mode or rubric with pending criteria)."""
        mode = task.evaluation.primary_mode
        if mode == JudgeMode.CLOUD_JUDGE:
            return True
        if mode == JudgeMode.RUBRIC:
            for ev_spec in task.evaluation.evaluators:
                if ev_spec.get("type") == "judge":
                    return True
                if ev_spec.get("type") == "rubric":
                    params = ev_spec.get("parameters", {})
                    if params.get("_pending_judge") or any(
                        c.get("requires_judge", False) for c in params.get("criteria", [])
                    ):
                        return True
        return False

    def evaluate(self, task: Task, result: TaskResult) -> EvaluatorResult:
        """
        Evaluate a model response using cloud judges.

        Flow:
          1. Discover available judge models
          2. Route to selected judges based on task capabilities
          3. Build judge prompts
          4. Call judges (primary + fallbacks)
          5. Parse structured output
          6. Compute consensus
          7. Return EvaluatorResult
        """
        judge_config_dict: dict[str, Any] = {}
        judge_config_dict.update(getattr(task.evaluation, 'extra', {}).get('judge_config', {}))
        judge_config_dict.update(getattr(task.evaluation, 'judge_config', {}))
        judge_config = TaskJudgeConfig.model_validate(judge_config_dict)
        criteria = judge_config.criteria

        # If no explicit criteria, derive from task
        if not criteria:
            criteria = self._derive_criteria(task)

        try:
            client = self._ensure_client()
        except ValueError as e:
            return EvaluatorResult(
                evaluator="judge",
                mode=JudgeMode.CLOUD_JUDGE,
                status=EvaluatorStatus.ERROR,
                rationale=f"Judge client not available: {e}",
                flags=["judge_client_unavailable"],
                details={"error": str(e)},
            )

        # Discover models
        try:
            models = client.discover_models()
        except JudgeAuthenticationError as e:
            return EvaluatorResult(
                evaluator="judge",
                mode=JudgeMode.CLOUD_JUDGE,
                status=EvaluatorStatus.ERROR,
                rationale=f"Judge authentication failed: {e}",
                flags=["judge_auth_failed"],
                details={"error": str(e)},
            )
        except JudgeClientError as e:
            return EvaluatorResult(
                evaluator="judge",
                mode=JudgeMode.CLOUD_JUDGE,
                status=EvaluatorStatus.ERROR,
                rationale=f"Judge model discovery failed: {e}",
                flags=["judge_discovery_failed"],
                details={"error": str(e)},
            )

        if not models:
            return EvaluatorResult(
                evaluator="judge",
                mode=JudgeMode.CLOUD_JUDGE,
                status=EvaluatorStatus.ERROR,
                rationale="No judge models discovered from gateway",
                flags=["no_judge_models"],
            )

        # Route to judges
        task_caps = list(task.capabilities) if task.capabilities else []
        selection = self._router.route(
            models,
            task_caps,
            min_judges=judge_config.min_judges,
            preferred_judges=judge_config.preferred_judges,
        )
        self._last_selection[task.id] = {
            "selected_models": selection.selected_models,
            "scores": selection.selection_scores,
            "reason": selection.selection_reason,
        }

        if not selection.selected_models:
            return EvaluatorResult(
                evaluator="judge",
                mode=JudgeMode.CLOUD_JUDGE,
                status=EvaluatorStatus.ERROR,
                rationale=f"No judges selected: {selection.selection_reason}",
                flags=["no_judges_selected"],
                details={"selection": {
                    "reason": selection.selection_reason,
                    "fallback": selection.fallback_behavior,
                }},
            )

        # Evaluate with selected judges
        judge_results: list[JudgeResult] = []
        selected_models = selection.selected_models[:]
        failures: list[str] = []

        for model_id in selected_models:
            judge_result = self._evaluate_with_judge(
                client=client,
                model_id=model_id,
                task=task,
                result=result,
                criteria=criteria,
                max_retries=judge_config.max_retries,
                timeout_s=judge_config.timeout_s,
            )
            if judge_result.status == "success":
                judge_results.append(judge_result)
            else:
                failures.append(f"{model_id}: {judge_result.error or judge_result.status}")

        # Consensus
        consensus = compute_consensus(
            judge_results,
            max_score=1.0,
            disagreement_threshold_percent=judge_config.disagreement_threshold_percent,
        )

        # Build EvaluatorResult
        flags = list(consensus.flags)
        for f in failures:
            flags.append(f"judge_failed:{f[:80]}")

        rationale = self._build_rationale(consensus, failures, selection)

        return EvaluatorResult(
            evaluator="judge",
            mode=JudgeMode.CLOUD_JUDGE,
            status=self._status_from_consensus(consensus),
            score=consensus.final_score,
            max_score=consensus.max_score,
            normalized_score=consensus.final_score,
            rationale=rationale,
            evidence=self._collect_evidence(judge_results),
            flags=flags,
            details={
                "consensus": consensus.model_dump(),
                "selection": {
                    "primary": selection.primary,
                    "secondary": selection.secondary,
                    "tertiary": selection.tertiary,
                    "selected_models": selection.selected_models,
                    "scores": selection.selection_scores,
                    "reason": selection.selection_reason,
                    "diversity_policy": selection.diversity_policy,
                },
                "judge_results": [r.model_dump() for r in judge_results],
                "failed_judges": failures,
                "judge_count": consensus.selected_judge_count,
                "judge_disagreement_percent": consensus.disagreement_percent,
            },
            authoritative_level=3,
        )

    def evaluate_long_judge(
        self,
        task: Task,
        result: TaskResult,
        stage_results: list[Any],
        stages: list[Any],
    ) -> tuple[float | None, EvaluatorResult | None]:
        """
        Evaluate a LONG task with cloud judges, gated by deterministic outcome.

        Returns:
            (quality_score, quality_result) if judge was invoked.
            (None, None) if judge was skipped (FAIL or NOT_APPLICABLE).

        Gating rules:
            long_outcome == FAIL        -> skip judge
            long_outcome == NOT_APPLICABLE -> skip judge
            long_outcome == PASS        -> invoke judge
            long_outcome == PARTIAL     -> invoke judge
        """
        long_outcome = getattr(result, "long_outcome", None)

        # Skip judge for FAIL and NOT_APPLICABLE
        if long_outcome in (EvaluatorStatus.FAIL.value, EvaluatorStatus.NOT_APPLICABLE.value):
            return None, None

        judge_config_dict: dict[str, Any] = {}
        judge_config_dict.update(getattr(task.evaluation, 'extra', {}).get('judge_config', {}))
        judge_config_dict.update(getattr(task.evaluation, 'judge_config', {}))
        judge_config = TaskJudgeConfig.model_validate(judge_config_dict)
        criteria = judge_config.criteria

        # If no explicit criteria, derive LONG-specific criteria
        if not criteria:
            criteria = self._derive_criteria(task)

        try:
            client = self._ensure_client()
        except ValueError as e:
            return None, EvaluatorResult(
                evaluator="long_horizon_judge",
                mode=JudgeMode.CLOUD_JUDGE,
                status=EvaluatorStatus.ERROR,
                rationale=f"Judge client not available: {e}",
                flags=["judge_client_unavailable"],
                details={"error": str(e)},
            )

        # Build LONG-specific judge prompt with stage evidence
        judge_messages = self._prompt_builder.build_long_evidence_prompt(
            task=task,
            result=result,
            stage_results=stage_results,
            stages=stages,
            criteria=criteria,
        )

        # Discover models
        try:
            models = client.discover_models()
        except JudgeAuthenticationError as e:
            return None, EvaluatorResult(
                evaluator="long_horizon_judge",
                mode=JudgeMode.CLOUD_JUDGE,
                status=EvaluatorStatus.ERROR,
                rationale=f"Judge authentication failed: {e}",
                flags=["judge_auth_failed"],
                details={"error": str(e)},
            )
        except JudgeClientError as e:
            return None, EvaluatorResult(
                evaluator="long_horizon_judge",
                mode=JudgeMode.CLOUD_JUDGE,
                status=EvaluatorStatus.ERROR,
                rationale=f"Judge model discovery failed: {e}",
                flags=["judge_discovery_failed"],
                details={"error": str(e)},
            )

        if not models:
            return None, EvaluatorResult(
                evaluator="long_horizon_judge",
                mode=JudgeMode.CLOUD_JUDGE,
                status=EvaluatorStatus.ERROR,
                rationale="No judge models discovered from gateway",
                flags=["no_judge_models"],
            )

        # Route to judges — LONG tasks require long-context capability
        task_caps = list(task.capabilities) if task.capabilities else ["LONG"]
        selection = self._router.route(
            models,
            task_caps,
            min_judges=judge_config.min_judges,
            preferred_judges=judge_config.preferred_judges,
        )

        if not selection.selected_models:
            return None, EvaluatorResult(
                evaluator="long_horizon_judge",
                mode=JudgeMode.CLOUD_JUDGE,
                status=EvaluatorStatus.ERROR,
                rationale=f"No judges selected: {selection.selection_reason}",
                flags=["no_judges_selected"],
                details={"selection": {
                    "reason": selection.selection_reason,
                    "fallback": selection.fallback_behavior,
                }},
            )

        # Evaluate with selected judges
        judge_results: list[JudgeResult] = []
        selected_models = selection.selected_models[:]
        failures: list[str] = []

        for model_id in selected_models:
            judge_result = self._evaluate_with_judge(
                client=client,
                model_id=model_id,
                task=task,
                result=result,
                criteria=criteria,
                max_retries=judge_config.max_retries,
                timeout_s=judge_config.timeout_s,
                messages=judge_messages,
            )
            if judge_result.status == "success":
                judge_results.append(judge_result)
            else:
                failures.append(f"{model_id}: {judge_result.error or judge_result.status}")

        # Consensus
        consensus = compute_consensus(
            judge_results,
            max_score=1.0,
            disagreement_threshold_percent=judge_config.disagreement_threshold_percent,
        )

        quality_score = consensus.final_score
        quality_flags = list(consensus.flags)
        for f in failures:
            quality_flags.append(f"judge_failed:{f[:80]}")

        quality_result = EvaluatorResult(
            evaluator="long_horizon_judge",
            mode=JudgeMode.CLOUD_JUDGE,
            status=EvaluatorStatus.PASS if quality_score is not None and quality_score >= 0.5 else EvaluatorStatus.FAIL,
            score=quality_score,
            max_score=consensus.max_score,
            normalized_score=quality_score,
            rationale=self._build_rationale(consensus, failures, selection),
            evidence=self._collect_evidence(judge_results),
            flags=quality_flags,
            details={
                "consensus": consensus.model_dump(),
                "selection": {
                    "primary": selection.primary,
                    "selected_models": selection.selected_models,
                    "scores": selection.selection_scores,
                    "reason": selection.selection_reason,
                },
                "judge_results": [r.model_dump() for r in judge_results],
                "failed_judges": failures,
                "judge_count": consensus.selected_judge_count,
                "judge_disagreement_percent": consensus.disagreement_percent,
            },
            authoritative_level=3,
        )

        return quality_score, quality_result

    def _evaluate_with_judge(
        self,
        client: JudgeClient,
        model_id: str,
        task: Task,
        result: TaskResult,
        criteria: list[dict[str, Any]],
        max_retries: int,
        timeout_s: float,
        messages: list[dict[str, str]] | None = None,
    ) -> JudgeResult:
        """Evaluate a single task with one judge model."""
        if messages is None:
            messages = self._prompt_builder.build(task, result, criteria)
        start = time.time()

        try:
            text, latency, prompt_tok, comp_tok = client.evaluate(
                model_id=model_id,
                messages=messages,
                max_tokens=int(timeout_s * 32),  # Rough token estimate
                temperature=0.0,
                timeout_s=timeout_s,
                retry_count=0,
            )
        except JudgeTimeoutError as e:
            return JudgeResult(
                model_id=model_id,
                status="timeout",
                error=str(e),
                latency_s=time.time() - start,
            )
        except JudgeRateLimitError as e:
            return JudgeResult(
                model_id=model_id,
                status="rate_limit",
                error=str(e),
                latency_s=time.time() - start,
            )
        except JudgeClientError as e:
            return JudgeResult(
                model_id=model_id,
                status="error",
                error=str(e),
                latency_s=time.time() - start,
            )

        # Parse structured output
        parsed = self._parse_judge_output(text, model_id)
        if parsed:
            return parsed
        else:
            # Malformed output — retry once
            if max_retries > 0:
                try:
                    messages_retry = self._prompt_builder.build(task, result, criteria)
                    # Append failure notice
                    messages_retry.append({
                        "role": "assistant",
                        "content": text[:500] if text else ""
                    })
                    messages_retry.append({
                        "role": "user",
                        "content": self._prompt_builder.build_failure_prompt("Malformed JSON output", max_retries)
                    })
                    text2, latency2, pt2, ct2 = client.evaluate(
                        model_id=model_id,
                        messages=messages_retry,
                        timeout_s=timeout_s,
                        retry_count=0,
                    )
                    parsed2 = self._parse_judge_output(text2, model_id)
                    if parsed2:
                        parsed2.latency_s = latency2
                        parsed2.prompt_tokens = pt2
                        parsed2.completion_tokens = ct2
                        return parsed2
                except Exception:
                    pass

            return JudgeResult(
                model_id=model_id,
                status="malformed",
                error="Judge output was not valid structured JSON",
                raw_response=text[:1000] if text else None,
                latency_s=time.time() - start,
                prompt_tokens=0,
                completion_tokens=0,
            )

    def _parse_judge_output(self, text: str, model_id: str) -> JudgeResult | None:
        """Parse structured JSON output from a judge model."""
        if not text:
            return None

        text = text.strip()
        # Extract JSON from possible markdown code blocks
        if "```" in text:
            import re
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if match:
                text = match.group(1)
            else:
                # Try to find first { and last }
                start = text.find("{")
                end = text.rfind("}")
                if start != -1 and end != -1:
                    text = text[start:end + 1]
                else:
                    return None

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None

        # Validate required fields
        if "score" not in data:
            return None

        score = data.get("score")
        try:
            score_float = float(score)
        except (TypeError, ValueError):
            return None

        # Validate score range
        if score_float < 0 or score_float > 1:
            return None

        criterion_scores: dict[str, float] = {}
        raw_crit = data.get("criterion_scores", {})
        if isinstance(raw_crit, dict):
            for k, v in raw_crit.items():
                try:
                    criterion_scores[str(k)] = float(v)
                except (TypeError, ValueError):
                    pass

        evidence: list[str] = []
        raw_evidence = data.get("evidence", [])
        if isinstance(raw_evidence, list):
            evidence = [str(e) for e in raw_evidence if e]

        flags: list[str] = []
        raw_flags = data.get("flags", [])
        if isinstance(raw_flags, list):
            flags = [str(f) for f in raw_flags if f]

        confidence = data.get("confidence")
        try:
            confidence = float(confidence) if confidence is not None else None
            if confidence is not None and (confidence < 0 or confidence > 1):
                confidence = None
        except (TypeError, ValueError):
            confidence = None

        return JudgeResult(
            model_id=model_id,
            score=score_float,
            criterion_scores=criterion_scores,
            reasoning_summary=data.get("reasoning_summary"),
            evidence=evidence,
            flags=flags,
            confidence=confidence,
            status="success",
            raw_response=text[:2000],
        )

    def _derive_criteria(self, task: Task) -> list[dict[str, Any]]:
        """Derive default evaluation criteria from task properties."""
        criteria = []
        caps = [c.value if hasattr(c, "value") else str(c) for c in task.capabilities]
        cat = task.category.lower()

        # Architecture tasks
        if "ARCH" in caps or cat in ("architecture", "arch"):
            criteria.extend([
                {"id": "architecture_quality", "weight": 0.5,
                 "description": "Quality and soundness of the architectural design"},
                {"id": "tradeoff_reasoning", "weight": 0.5,
                 "description": "Quality of tradeoff analysis and justification"},
            ])
        # Code tasks
        elif "CODE" in caps or cat in ("coding", "code", "debug"):
            criteria.extend([
                {"id": "correctness", "weight": 0.5,
                 "description": "Correctness of the solution"},
                {"id": "code_quality", "weight": 0.3,
                 "description": "Code structure, readability, and best practices"},
                {"id": "efficiency", "weight": 0.2,
                 "description": "Algorithmic efficiency and resource awareness"},
            ])
        # Planning tasks
        elif "PLAN" in caps or cat in ("planning",):
            criteria.extend([
                {"id": "plan_completeness", "weight": 0.4,
                 "description": "Completeness of the plan"},
                {"id": "plan_feasibility", "weight": 0.3,
                 "description": "Feasibility and practicality of the plan"},
                {"id": "plan_clarity", "weight": 0.3,
                 "description": "Clarity and structure of the plan"},
            ])
        # Evidence tasks
        elif "EVIDENCE" in caps or cat in ("evidence",):
            criteria.extend([
                {"id": "factual_accuracy", "weight": 0.5,
                 "description": "Factual accuracy of claims"},
                {"id": "evidence_quality", "weight": 0.5,
                 "description": "Quality and relevance of supporting evidence"},
            ])
        # Advisory tasks
        elif "ADVISORY" in caps or cat in ("advisory",):
            criteria.extend([
                {"id": "advice_quality", "weight": 0.4,
                 "description": "Quality and actionability of the advice"},
                {"id": "reasoning_soundness", "weight": 0.3,
                 "description": "Soundness of reasoning behind recommendations"},
                {"id": "context_awareness", "weight": 0.3,
                 "description": "Awareness of constraints and context"},
            ])
        # Judgment tasks
        elif "JUDGMENT" in caps or cat in ("judgment",):
            criteria.extend([
                {"id": "judgment_soundness", "weight": 0.5,
                 "description": "Soundness of the judgment"},
                {"id": "tradeoff_analysis", "weight": 0.3,
                 "description": "Quality of tradeoff analysis"},
                {"id": "evidence_use", "weight": 0.2,
                 "description": "Proper use of evidence in forming judgment"},
            ])
        # Long-horizon engineering tasks — 8-dimension rubric (Stage 8E.1)
        elif "LONG" in caps or cat in ("long_horizon",):
            criteria.extend([
                {"id": "correctness", "weight": 0.25,
                 "description": "Correctness of implementation against requirements and test outcomes"},
                {"id": "completeness", "weight": 0.15,
                 "description": "Completeness of stage execution and artifact delivery"},
                {"id": "requirement_adherence", "weight": 0.15,
                 "description": "Adherence to original and changed requirements throughout the workflow"},
                {"id": "implementation_quality", "weight": 0.15,
                 "description": "Code structure, readability, and engineering best practices"},
                {"id": "test_quality", "weight": 0.10,
                 "description": "Quality, coverage, and robustness of tests produced"},
                {"id": "regression_safety", "weight": 0.10,
                 "description": "Absence of unintended changes or regressions to existing code"},
                {"id": "adaptation_quality", "weight": 0.05,
                 "description": "Quality of adaptation when requirements change mid-workflow"},
                {"id": "final_delivery_quality", "weight": 0.05,
                 "description": "Overall quality and professionalism of the final deliverable"},
            ])
        else:
            # Default criteria
            criteria.extend([
                {"id": "correctness", "weight": 0.5,
                 "description": "Correctness of the response"},
                {"id": "quality", "weight": 0.3,
                 "description": "Overall quality of the response"},
                {"id": "clarity", "weight": 0.2,
                 "description": "Clarity and precision of the response"},
            ])

        return criteria

    def _status_from_consensus(self, consensus: Any) -> EvaluatorStatus:
        """Map consensus result to EvaluatorStatus."""
        if consensus.final_score is None:
            return EvaluatorStatus.ERROR
        if consensus.final_score >= 0.5:
            return EvaluatorStatus.PASS
        return EvaluatorStatus.FAIL

    def _build_rationale(self, consensus: Any, failures: list[str], selection: Any) -> str:
        """Build a human-readable rationale for the evaluation."""
        parts = []
        parts.append(f"Cloud judge consensus: {consensus.selected_judge_count} judge(s) evaluated")
        if consensus.final_score is not None:
            parts.append(f"final score={consensus.final_score:.3f}")
        if consensus.disagreement_percent > 0:
            parts.append(f"disagreement={consensus.disagreement_percent:.1f}%")
        if failures:
            parts.append(f"failed judges: {', '.join(failures[:3])}")
        parts.append(f"selection_reason={selection.selection_reason}")
        return "; ".join(parts)

    def _collect_evidence(self, judge_results: list[Any]) -> list[str]:
        """Collect evidence points from successful judge results."""
        evidence: list[str] = []
        for jr in judge_results:
            if jr.reasoning_summary:
                evidence.append(f"[{jr.model_id}] {jr.reasoning_summary[:200]}")
            for e in jr.evidence[:3]:
                evidence.append(f"[{jr.model_id}] {e[:200]}")
        return evidence[:10]

    def _ensure_client(self) -> JudgeClient:
        """Get or create the judge client from environment."""
        if self._client is not None:
            return self._client
        from ..env_config import validate_judge_env
        env = validate_judge_env(required=False)
        base_url = env.get("EB_JUDGE_BASE_URL", "")
        api_key = env.get("EB_JUDGE_API_KEY", "")
        if not base_url or not api_key:
            raise ValueError("EB_JUDGE_BASE_URL and EB_JUDGE_API_KEY must be set for cloud judge")
        self._client = JudgeClient.from_env()
        return self._client
