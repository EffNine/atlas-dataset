"""Tests for eb/judges/profiler.py — Judge capability profiling."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from eb.core.schema import JudgeModelInfo, JudgeCapabilityProfile
from eb.judges.profiler import JudgeProfiler


class TestJudgeProfiler:
    def setup_method(self):
        self.tmp_dir = Path("/tmp/eb-judge-profiler-test")
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.profiler = JudgeProfiler(cache_dir=self.tmp_dir)
        self.profiler.clear_cache()

    def teardown_method(self):
        import shutil
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_metadata_based_profile(self):
        model = JudgeModelInfo(
            id="test-model-32k",
            owned_by="test-provider",
            context_length=32768,
        )
        profile = self.profiler.get_profile(model)
        assert profile.model_id == "test-model-32k"
        assert profile.source == "gateway_metadata"
        assert profile.long_context >= 0.5  # 32k context

    def test_long_context_inference(self):
        model = JudgeModelInfo(id="big-model", context_length=128000)
        profile = self.profiler.get_profile(model)
        assert profile.long_context >= 0.9

    def test_short_context(self):
        model = JudgeModelInfo(id="small-model", context_length=4096)
        profile = self.profiler.get_profile(model)
        assert profile.long_context < 0.5

    def test_vision_model(self):
        model = JudgeModelInfo(id="model-vision-ft", modality="vision")
        profile = self.profiler.get_profile(model)
        assert profile.vision > 0

    def test_configured_profile(self):
        profiler = JudgeProfiler(
            configured_profiles={
                "configured-model": {
                    "reasoning": 0.95,
                    "coding": 0.90,
                }
            },
            cache_dir=self.tmp_dir,
        )
        model = JudgeModelInfo(id="configured-model")
        profile = profiler.get_profile(model)
        assert profile.source == "configured"
        assert profile.reasoning == 0.95
        assert profile.coding == 0.90

    def test_unknown_capability_defaults(self):
        model = JudgeModelInfo(id="unknown-model")
        profile = self.profiler.get_profile(model)
        assert profile.reasoning > 0
        assert profile.availability == 1.0

    def test_probe_fallback(self):
        """When no metadata available, returns gateway_metadata profile (not probe)."""
        model = JudgeModelInfo(id="bare-model")
        profile = self.profiler.get_profile(model)
        # Bare models still get gateway_metadata profile with heuristic scoring
        assert profile.source == "gateway_metadata"
        assert profile.reasoning > 0

    def test_cache_persistence(self):
        model = JudgeModelInfo(id="cached-model", context_length=64000)
        profile1 = self.profiler.get_profile(model)

        # New profiler instance should load from cache
        profiler2 = JudgeProfiler(cache_dir=self.tmp_dir)
        profile2 = profiler2.get_profile(model)

        assert profile1.model_id == profile2.model_id
        assert profile1.source == profile2.source

    def test_clear_cache(self):
        model = JudgeModelInfo(id="clear-test")
        self.profiler.get_profile(model)
        self.profiler.clear_cache()
        assert model.id not in self.profiler._cache

    def test_invalidate_cache(self):
        model = JudgeModelInfo(id="invalidate-test")
        self.profiler.get_profile(model)
        self.profiler.invalidate_cache()
        assert model.id not in self.profiler._cache
        # Disk cache also cleared
        cache_file = self.tmp_dir / "judge_capability_cache.json"
        assert not cache_file.exists()

    def test_task_dimension_scores(self):
        scores = self.profiler.get_task_dimension_scores(["ARCH", "CODE"])
        assert "reasoning" in scores
        assert scores["reasoning"] == 1.0
        assert scores["planning"] >= 0.8
        assert scores["coding"] == 1.0

    def test_task_dimension_scores_empty(self):
        scores = self.profiler.get_task_dimension_scores([])
        assert scores == {}

    def test_normalized_model_no_id_skipped(self):
        """Models without an 'id' field are skipped."""
        raw = {"owned_by": "test"}  # no id
        result = JudgeClient._normalize_model(JudgeClient, raw)  # type: ignore
        assert result is None

    def test_context_length_from_id(self):
        model = JudgeClient._normalize_model(JudgeClient, {"id": "gpt-4-128k"})  # type: ignore
        assert model is not None
        assert model.context_length == 131072  # 128 * 1024


# Import helper needed by tests
from eb.judges.client import JudgeClient
