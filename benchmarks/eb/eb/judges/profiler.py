#!/usr/bin/env python3
"""
profiler.py — Judge capability profiling for the EffNine Benchmark (EB).

Builds normalized capability profiles for discovered judge models using:
  1. Gateway-provided metadata
  2. Explicit configured metadata (from config/judges.yaml)
  3. Lightweight capability probes (fallback)

Profiles are cached by model ID to avoid repeated probing.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from ..core.schema import JudgeCapabilityProfile, JudgeModelInfo
from ..paths import metadata_dir
from ..core.types import Capability


# ---------------------------------------------------------------------------
# Capability mapping from Capability enum dimensions
# ---------------------------------------------------------------------------

CAPABILITY_DIMENSIONS = {
    "reasoning",
    "coding",
    "planning",
    "instruction_following",
    "long_context",
    "factual_analysis",
    "vision",
    "latency",
    "availability",
}

# Default weights per task capability -> judge capability dimension
TASK_TO_JUDGE_DIM_MAP: dict[str, list[str]] = {
    "ARCH": ["reasoning", "planning", "instruction_following"],
    "DEBUG": ["reasoning", "coding", "factual_analysis"],
    "CODE": ["coding", "reasoning"],
    "PLAN": ["planning", "reasoning", "instruction_following"],
    "ADVISORY": ["reasoning", "instruction_following", "factual_analysis"],
    "JUDGMENT": ["reasoning", "factual_analysis", "instruction_following"],
    "EVIDENCE": ["factual_analysis", "reasoning", "instruction_following"],
    "LONG": ["reasoning", "long_context", "instruction_following"],
    "UNDERSTAND": ["reasoning", "instruction_following"],
    "TEST": ["coding", "reasoning"],
    "MYENG": ["reasoning", "coding", "instruction_following"],
    "AGENT": ["reasoning", "planning", "coding", "instruction_following"],
}


class JudgeProfiler:
    """
    Builds and caches capability profiles for judge models.

    Profile sources (in priority order):
      1. Gateway-provided metadata (from /models response)
      2. Explicit configured metadata (from config file)
      3. Lightweight capability probe
    """

    PROBE_VERSION = "1.0"
    CACHE_FILENAME = "judge_capability_cache.json"

    def __init__(
        self,
        configured_profiles: dict[str, dict[str, float]] | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self._configured: dict[str, dict[str, float]] = configured_profiles or {}
        self._cache_dir = cache_dir or metadata_dir()
        self._cache: dict[str, JudgeCapabilityProfile] = {}
        self._load_cache()

    def _cache_key(self, model_id: str) -> str:
        """Generate a cache key from model ID and probe version."""
        raw = f"{model_id}:{self.PROBE_VERSION}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _load_cache(self) -> None:
        """Load capability cache from disk."""
        cache_path = self._cache_dir / self.CACHE_FILENAME
        if not cache_path.exists():
            return
        try:
            with cache_path.open(encoding="utf-8") as f:
                data = json.load(f)
            for model_id, profile_data in data.items():
                try:
                    self._cache[model_id] = JudgeCapabilityProfile.model_validate(profile_data)
                except Exception:
                    pass
        except Exception:
            pass

    def _save_cache(self) -> None:
        """Persist capability cache to disk."""
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            data = {k: v.model_dump() for k, v in self._cache.items()}
            with (self._cache_dir / self.CACHE_FILENAME).open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def get_profile(self, model: JudgeModelInfo) -> JudgeCapabilityProfile:
        """
        Get or build a capability profile for a model.

        Checks in order:
          1. In-memory cache
          2. Disk cache
          3. Configured profiles
          4. Gateway metadata
          5. Probe fallback
        """
        # Check in-memory cache
        if model.id in self._cache:
            return self._cache[model.id]

        # Check disk cache
        cache_key = self._cache_key(model.id)
        cache_path = self._cache_dir / self.CACHE_FILENAME
        if cache_path.exists():
            try:
                with cache_path.open(encoding="utf-8") as f:
                    disk_cache = json.load(f)
                if cache_key in disk_cache:
                    profile = JudgeCapabilityProfile.model_validate(disk_cache[cache_key])
                    self._cache[model.id] = profile
                    return profile
            except Exception:
                pass

        # Check configured profiles
        if model.id in self._configured:
            profile = self._build_from_config(model.id, self._configured[model.id])
            self._cache[model.id] = profile
            self._save_cache()
            return profile

        # Build from gateway metadata
        profile = self._build_from_metadata(model)
        if profile.source != "unknown":
            self._cache[model.id] = profile
            self._save_cache()
            return profile

        # Fallback: probe
        profile = self._probe(model)
        self._cache[model.id] = profile
        self._save_cache()
        return profile

    def _build_from_config(self, model_id: str, caps: dict[str, float]) -> JudgeCapabilityProfile:
        """Build a profile from explicitly configured capability scores."""
        profile = JudgeCapabilityProfile(model_id=model_id, source="configured")
        for dim, value in caps.items():
            if dim in CAPABILITY_DIMENSIONS:
                setattr(profile, dim, float(value))
        return profile

    def _build_from_metadata(self, model: JudgeModelInfo) -> JudgeCapabilityProfile:
        """Build a profile from gateway-provided metadata."""
        profile = JudgeCapabilityProfile(model_id=model.id, source="gateway_metadata")

        # Check raw metadata for capability hints
        raw = model.raw_metadata
        owned_by = (model.owned_by or "").lower()

        # Heuristic scoring based on available metadata
        if model.context_length:
            if model.context_length >= 128000:
                profile.long_context = 0.9
            elif model.context_length >= 32000:
                profile.long_context = 0.7
            elif model.context_length >= 8000:
                profile.long_context = 0.5
            else:
                profile.long_context = 0.3

        # Base reasoning score from owned_by / known providers
        reasoning_base = 0.5
        if any(kw in owned_by for kw in ("anthropic", "openai", "google", "deepseek")):
            reasoning_base = 0.7
        if any(kw in owned_by for kw in ("x-ai", "grok")):
            reasoning_base = 0.75
        profile.reasoning = reasoning_base

        # Coding heuristics from model ID
        model_id_lower = model.id.lower()
        if any(kw in model_id_lower for kw in ("code", "codex", "swe", "github")):
            profile.coding = 0.9
        elif any(kw in model_id_lower for kw in ("o1", "o3", "claude", "sonnet", "opus")):
            profile.coding = 0.8
        elif any(kw in model_id_lower for kw in ("gpt", "turbo", "pro")):
            profile.coding = 0.7
        else:
            profile.coding = 0.5

        # Vision
        if model.modality == "vision" or any(kw in model_id_lower for kw in ("vision", "vl", "img")):
            profile.vision = 0.9

        # Instruction following from capabilities dict
        for dim, val in model.capabilities.items():
            if dim in CAPABILITY_DIMENSIONS:
                setattr(profile, dim, float(val))

        return profile

    def _probe(self, model: JudgeModelInfo) -> JudgeCapabilityProfile:
        """
        Return a default profile with source=probe.
        Actual probing requires a live client and is deferred to the router.
        This provides a safe baseline.
        """
        return JudgeCapabilityProfile(
            model_id=model.id,
            source="probe",
            probe_version=self.PROBE_VERSION,
            reasoning=0.6,
            coding=0.5,
            planning=0.5,
            instruction_following=0.6,
            long_context=0.5 if model.context_length and model.context_length >= 32000 else 0.3,
            factual_analysis=0.5,
            vision=0.0,
        )

    def get_task_dimension_scores(self, task_capabilities: list[Any]) -> dict[str, float]:
        """
        Compute required judge dimensions for a set of task capabilities.

        Returns a dict of dimension -> required_weight.
        """
        scores: dict[str, float] = {}
        for cap in task_capabilities:
            if hasattr(cap, "value"):
                cap_str = cap.value
            else:
                cap_str = str(cap)
            dims = TASK_TO_JUDGE_DIM_MAP.get(cap_str, [])
            for dim in dims:
                scores[dim] = max(scores.get(dim, 0.0), 1.0)
        return scores

    def clear_cache(self) -> None:
        """Clear in-memory cache."""
        self._cache.clear()

    def invalidate_cache(self) -> None:
        """Clear both in-memory and disk cache."""
        self._cache.clear()
        cache_path = self._cache_dir / self.CACHE_FILENAME
        if cache_path.exists():
            try:
                cache_path.unlink()
            except Exception:
                pass
