#!/usr/bin/env python3
"""
router.py — Judge model routing for the EffNine Benchmark (EB).

Selects primary, secondary, and tertiary judge models based on:
  - Task capability requirements
  - Judge capability profiles
  - Provider diversity preferences
  - Explicit model override (EB_JUDGE_MODEL)

Never hardcodes specific model names. Routing works from whatever
models the gateway exposes.
"""

from __future__ import annotations

import os
from typing import Any

from ..core.schema import (
    JudgeCapabilityProfile,
    JudgeModelInfo,
    JudgeSelectionResult,
)
from ..core.types import Capability, JudgeDiversityPolicy
from .profiler import JudgeProfiler


# ---------------------------------------------------------------------------
# Task capability -> required judge dimensions
# ---------------------------------------------------------------------------

CAPABILITY_REQUIREMENTS: dict[Capability, dict[str, float]] = {
    Capability.ARCH: {"reasoning": 1.0, "planning": 0.8, "instruction_following": 0.6},
    Capability.DEBUG: {"reasoning": 0.9, "coding": 0.8, "factual_analysis": 0.6},
    Capability.CODE: {"coding": 1.0, "reasoning": 0.7},
    Capability.PLAN: {"planning": 1.0, "reasoning": 0.8, "instruction_following": 0.6},
    Capability.ADVISORY: {"reasoning": 1.0, "instruction_following": 0.8, "factual_analysis": 0.6},
    Capability.JUDGMENT: {"reasoning": 1.0, "factual_analysis": 0.9, "instruction_following": 0.6},
    Capability.EVIDENCE: {"factual_analysis": 1.0, "reasoning": 0.8, "instruction_following": 0.6},
    Capability.LONG: {"reasoning": 0.9, "long_context": 1.0, "instruction_following": 0.7},
    Capability.UNDERSTAND: {"reasoning": 0.9, "instruction_following": 0.7},
    Capability.TEST: {"coding": 0.8, "reasoning": 0.6},
    Capability.MYENG: {"reasoning": 0.8, "coding": 0.7, "instruction_following": 0.6},
    Capability.AGENT: {"reasoning": 1.0, "planning": 0.9, "coding": 0.7, "instruction_following": 0.8},
}


class JudgeRouter:
    """
    Routes tasks to appropriate judge models.

    Selection strategy:
      1. If EB_JUDGE_MODEL is set, force that exact model
      2. Score all discovered models against task requirements
      3. Select top-k by score with diversity preference
      4. Fall back to single judge if insufficient qualified models
    """

    def __init__(
        self,
        profiler: JudgeProfiler | None = None,
        diversity_policy: str = "preferred",
        min_judges: int = 2,
        preferred_judges: int = 3,
    ) -> None:
        self._profiler = profiler or JudgeProfiler()
        self._diversity_policy = JudgeDiversityPolicy(diversity_policy)
        self._min_judges = min_judges
        self._preferred_judges = preferred_judges

    def route(
        self,
        models: list[JudgeModelInfo],
        task_capabilities: list[Capability],
        *,
        min_judges: int | None = None,
        preferred_judges: int | None = None,
    ) -> JudgeSelectionResult:
        """
        Select judge models for a task.

        Args:
            models: Discovered judge models from the gateway.
            task_capabilities: Capabilities the task exercises.
            min_judges: Override minimum judge count.
            preferred_judges: Override preferred judge count.

        Returns:
            JudgeSelectionResult with selected models and reasoning.
        """
        # Check for explicit model override (not "auto")
        explicit_model = os.environ.get("EB_JUDGE_MODEL", "").strip()
        if explicit_model and explicit_model != "auto":
            return self._route_with_override(models, explicit_model)

        if not models:
            return JudgeSelectionResult(
                selection_reason="No models available from gateway",
                fallback_behavior="benchmark_requires_judge_model",
            )

        # Get requirement scores for this task
        requirements: dict[str, float] = {}
        for cap in task_capabilities:
            reqs = CAPABILITY_REQUIREMENTS.get(cap, {})
            for dim, weight in reqs.items():
                requirements[dim] = max(requirements.get(dim, 0.0), weight)

        if not requirements:
            requirements = {"reasoning": 0.5}

        # Score each model
        scored: list[tuple[JudgeModelInfo, JudgeCapabilityProfile, float]] = []
        for model in models:
            profile = self._profiler.get_profile(model)
            score = self._compute_selection_score(profile, requirements)
            scored.append((model, profile, score))

        # Sort by score descending
        scored.sort(key=lambda x: x[2], reverse=True)

        # Select judges with diversity
        selected: list[tuple[JudgeModelInfo, JudgeCapabilityProfile]] = []
        scores_dict: dict[str, float] = {}

        target_count = min(
            preferred_judges or self._preferred_judges,
            len(scored),
        )
        actual_min = min(min_judges or self._min_judges, len(scored))

        seen_providers: set[str] = set()
        seen_families: set[str] = set()

        for model, profile, score in scored:
            if len(selected) >= target_count:
                break

            provider = (model.owned_by or "unknown").lower()
            family = self._infer_family(model.id)

            # Diversity check
            if self._diversity_policy == JudgeDiversityPolicy.REQUIRED:
                if provider in seen_providers and family in seen_families:
                    continue
            elif self._diversity_policy == JudgeDiversityPolicy.PREFERRED:
                if provider in seen_providers and family in seen_families:
                    # Skip only if we already have diversity
                    if len(selected) >= actual_min:
                        continue

            selected.append((model, profile))
            scores_dict[model.id] = score
            seen_providers.add(provider)
            seen_families.add(family)

        # Ensure we have at least min_judges
        if len(selected) < actual_min and len(scored) > len(selected):
            for model, profile, score in scored:
                if model.id not in {s.id for s, _ in selected}:
                    selected.append((model, profile))
                    scores_dict[model.id] = score
                    if len(selected) >= actual_min:
                        break

        # Build result
        result = JudgeSelectionResult(
            primary=selected[0][0].id if len(selected) > 0 else None,
            secondary=selected[1][0].id if len(selected) > 1 else None,
            tertiary=selected[2][0].id if len(selected) > 2 else None,
            selected_models=[m.id for m, _ in selected],
            selection_scores=scores_dict,
            capability_requirements=requirements,
            diversity_policy=self._diversity_policy.value,
        )

        if len(selected) == 1:
            result.selection_reason = "only_one_valid_model_available"
            result.fallback_behavior = "single_judge_mode"
        elif len(selected) < actual_min:
            result.selection_reason = f"only_{len(selected)}_models_available_below_minimum_{actual_min}"
            result.fallback_behavior = "proceed_with_available_judges"
        else:
            result.selection_reason = "highest_capability_scores_with_diversity"
            result.fallback_behavior = "none"

        return result

    def _route_with_override(
        self,
        models: list[JudgeModelInfo],
        override_model: str,
    ) -> JudgeSelectionResult:
        """Route using an explicit model override."""
        # Find the model in discovered list
        matched = next((m for m in models if m.id == override_model), None)

        result = JudgeSelectionResult(
            primary=override_model,
            selected_models=[override_model],
            selection_scores={override_model: 1.0},
            selection_reason="explicit_model_override",
            fallback_behavior="none",
        )

        if matched:
            profile = self._profiler.get_profile(matched)
            result.selection_scores[override_model] = self._compute_selection_score(
                profile, {"reasoning": 0.5}
            )
        else:
            # Model not in discovery list — still use it but mark as unknown profile
            result.selection_scores[override_model] = 0.5
            result.fallback_behavior = "model_not_in_discovery_list"

        return result

    def _compute_selection_score(
        self,
        profile: JudgeCapabilityProfile,
        requirements: dict[str, float],
    ) -> float:
        """
        Compute a composite selection score for a profile against requirements.

        Score = sum(required_dim_score * requirement_weight) / sum(requirement_weights)
        """
        if not requirements:
            return 0.5

        total_weight = sum(requirements.values())
        weighted_sum = 0.0

        for dim, weight in requirements.items():
            dim_value = getattr(profile, dim, 0.0)
            weighted_sum += dim_value * weight

        return weighted_sum / total_weight if total_weight > 0 else 0.0

    @staticmethod
    def _infer_family(model_id: str) -> str:
        """Infer model family from ID for diversity tracking."""
        mid = model_id.lower()
        if any(kw in mid for kw in ("gpt", "o1", "o3", "claude", "gemini", "glm", "deepseek", "nemotron", "qwen", "llama", "mistral", "grok", "step", "yi", "internlm")):
            # Extract the provider prefix
            for kw in ("gpt", "o1", "o3", "claude", "gemini", "glm", "deepseek", "nemotron", "qwen", "llama", "mistral", "grok", "step", "yi", "internlm"):
                if kw in mid:
                    return kw
        return model_id.split("/")[-1].split(":")[0] if "/" in model_id else model_id.split("-")[0]
