"""Tests for eb/judges/router.py — Judge model routing."""
import os
import pytest
from unittest.mock import MagicMock, patch

from eb.core.schema import JudgeModelInfo, JudgeCapabilityProfile
from eb.core.types import Capability, JudgeDiversityPolicy
from eb.judges.router import JudgeRouter
from eb.judges.profiler import JudgeProfiler


def _make_model(mid: str, owned_by: str = "test", context_length: int | None = None) -> JudgeModelInfo:
    return JudgeModelInfo(
        id=mid,
        owned_by=owned_by,
        context_length=context_length,
        capabilities={"reasoning": 0.8, "coding": 0.7} if "code" in mid.lower() else {},
    )


def _make_profile(model_id: str, reasoning: float = 0.7, coding: float = 0.5) -> JudgeCapabilityProfile:
    return JudgeCapabilityProfile(
        model_id=model_id,
        reasoning=reasoning,
        coding=coding,
        source="test",
    )


class TestJudgeRouter:
    def test_architecture_routing(self):
        router = JudgeRouter()
        models = [
            _make_model("arch-specialist", context_length=128000),
            _make_model("general-model"),
        ]
        selection = router.route(models, [Capability.ARCH])
        assert selection.primary is not None
        assert len(selection.selected_models) >= 1

    def test_coding_routing(self):
        router = JudgeRouter()
        models = [
            _make_model("code-wizard", owned_by="provider-a"),
            _make_model("general-model", owned_by="provider-b"),
        ]
        selection = router.route(models, [Capability.CODE])
        assert selection.primary is not None
        # Code-specialist should score higher for CODE tasks
        assert selection.selection_scores.get("code-wizard", 0) >= 0.5

    def test_planning_routing(self):
        router = JudgeRouter()
        models = [
            _make_model("planner-pro", context_length=128000),
            _make_model("short-context"),
        ]
        selection = router.route(models, [Capability.PLAN])
        assert selection.primary is not None

    def test_long_horizon_routing(self):
        router = JudgeRouter()
        models = [
            _make_model("long-context-model", context_length=128000),
            _make_model("short-model", context_length=4096),
        ]
        selection = router.route(models, [Capability.LONG])
        assert selection.primary is not None
        # Long-context model should be preferred
        if selection.primary:
            assert "long" in selection.primary.lower() or selection.selection_scores.get("long-context-model", 0) >= selection.selection_scores.get("short-model", 0)

    def test_evidence_routing(self):
        router = JudgeRouter()
        models = [
            _make_model("fact-checker"),
            _make_model("creative-writer"),
        ]
        selection = router.route(models, [Capability.EVIDENCE])
        assert selection.primary is not None

    def test_multiple_judge_selection(self):
        router = JudgeRouter(
            profiler=JudgeProfiler(),
            min_judges=2,
            preferred_judges=3,
        )
        models = [
            _make_model("model-a", owned_by="prov-a"),
            _make_model("model-b", owned_by="prov-b"),
            _make_model("model-c", owned_by="prov-c"),
            _make_model("model-d", owned_by="prov-a"),  # same provider as a
        ]
        selection = router.route(models, [Capability.ARCH])
        assert len(selection.selected_models) >= 2
        assert selection.primary is not None

    def test_provider_diversity(self):
        router = JudgeRouter(
            profiler=JudgeProfiler(),
            diversity_policy="preferred",
            min_judges=3,
            preferred_judges=3,
        )
        models = [
            _make_model("a-gpt", owned_by="openai"),
            _make_model("b-gpt", owned_by="openai"),  # same provider
            _make_model("c-claude", owned_by="anthropic"),
            _make_model("d-gemini", owned_by="google"),
        ]
        selection = router.route(models, [Capability.ARCH])
        # Should prefer diversity across providers
        providers = set()
        for mid in selection.selected_models:
            for m in models:
                if m.id == mid:
                    providers.add((m.owned_by or "").lower())
                    break
        # At least 2 different providers should be selected
        assert len(providers) >= 2

    def test_single_judge_fallback(self):
        router = JudgeRouter(min_judges=2, preferred_judges=3)
        models = [_make_model("only-model")]
        selection = router.route(models, [Capability.ARCH])
        assert len(selection.selected_models) == 1
        assert selection.fallback_behavior == "single_judge_mode"

    def test_explicit_model_override(self, monkeypatch):
        monkeypatch.setenv("EB_JUDGE_MODEL", "forced-model-x")
        router = JudgeRouter()
        models = [
            _make_model("forced-model-x", owned_by="prov-a"),
            _make_model("other-model", owned_by="prov-b"),
        ]
        selection = router.route(models, [Capability.ARCH])
        assert selection.primary == "forced-model-x"
        assert selection.selection_reason == "explicit_model_override"
        del os.environ["EB_JUDGE_MODEL"]

    def test_no_models(self):
        router = JudgeRouter()
        selection = router.route([], [Capability.ARCH])
        assert selection.primary is None
        assert "No models" in selection.selection_reason

    def test_empty_capabilities_defaults_to_reasoning(self):
        router = JudgeRouter()
        models = [
            _make_model("model-a"),
            _make_model("model-b"),
        ]
        selection = router.route(models, [])
        assert selection.primary is not None

    def test_considered_all_models_for_scoring(self):
        router = JudgeRouter()
        # Model with high reasoning should score well for ARCH
        models = [
            _make_model("high-reason", context_length=128000),
            _make_model("low-reason", context_length=4096),
        ]
        selection = router.route(models, [Capability.ARCH])
        # Both should be scored
        assert "high-reason" in selection.selection_scores
        assert "low-reason" in selection.selection_scores


class TestRouterDiversityPolicy:
    def test_diversity_off(self):
        """With diversity off, top-scoring models are selected regardless of provider."""
        router = JudgeRouter(diversity_policy="off")
        models = [
            _make_model("best-a", owned_by="same-prov"),
            _make_model("best-b", owned_by="same-prov"),
            _make_model("good-c", owned_by="diff-prov"),
        ]
        selection = router.route(models, [Capability.ARCH])
        assert len(selection.selected_models) >= 2

    def test_diversity_required(self):
        """With diversity required, models from same provider+family are skipped."""
        router = JudgeRouter(
            diversity_policy="required",
            min_judges=2,
            preferred_judges=3,
        )
        models = [
            _make_model("same-family-1", owned_by="prov-a"),
            _make_model("same-family-2", owned_by="prov-a"),
            _make_model("different-1", owned_by="prov-b"),
        ]
        selection = router.route(models, [Capability.ARCH])
        # Should not have two models from same provider
        providers = []
        for mid in selection.selected_models:
            for m in models:
                if m.id == mid:
                    providers.append(m.owned_by)
                    break
        # At most one from each provider
        assert len(providers) == len(set(providers)) or len(selection.selected_models) < 2
