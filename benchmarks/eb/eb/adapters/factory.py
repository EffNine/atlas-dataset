#!/usr/bin/env python3
"""
factory.py — Adapter factory for the EffNine Benchmark (EB).

Resolves model identifiers and provider configuration from config/models.yaml
into concrete ModelAdapter instances. The CLI never instantiates adapter
classes directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..paths import config_dir
from .base import ModelAdapter
from .local import LocalModelAdapter
from .openai_compatible import OpenAICompatibleAdapter


# Canonical mapping from config 'type' to adapter class
_ADAPTER_REGISTRY: dict[str, type[ModelAdapter]] = {
    "local": LocalModelAdapter,
    "openai_compatible": OpenAICompatibleAdapter,
    "openai": OpenAICompatibleAdapter,
}


class AdapterFactory:
    """
    Factory that resolves model configs into ModelAdapter instances.

    Reads from config/models.yaml and creates adapters based on the
    model type field. The factory caches created adapters to avoid
    repeated instantiation.
    """

    def __init__(self, config_path: Path | str | None = None) -> None:
        self._config_path = Path(config_path) if config_path else config_dir() / "models.yaml"
        self._config: dict[str, Any] = {}
        self._adapters: dict[str, ModelAdapter] = {}
        self._load_config()

    def _load_config(self) -> None:
        if self._config_path.exists():
            with self._config_path.open(encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}
        else:
            self._config = {"models": []}

    def get_model_config(self, model_name: str) -> dict[str, Any] | None:
        """Retrieve raw config dict for a model by name."""
        for m in self._config.get("models", []):
            if m.get("name") == model_name:
                return m
        return None

    def list_models(self) -> list[str]:
        """Return available model names from config."""
        return [m["name"] for m in self._config.get("models", [])]

    def create_adapter(
        self,
        model_name: str,
        *,
        inference_settings: Any = None,
        overrides: dict[str, Any] | None = None,
    ) -> ModelAdapter:
        """
        Create a ModelAdapter for the named model.

        Args:
            model_name: Key from config/models.yaml
            inference_settings: Optional InferenceSettings override
            overrides: Additional keyword args passed to the adapter constructor

        Returns:
            A configured ModelAdapter instance

        Raises:
            ValueError: If model not found or config is invalid
            RuntimeError: If adapter type is unknown
        """
        if model_name in self._adapters:
            return self._adapters[model_name]

        config = self.get_model_config(model_name)
        if config is None:
            available = self.list_models()
            raise ValueError(
                f"Unknown model {model_name!r}. Available: {available}"
            )

        adapter_type = config.get("type", "").lower()
        cls = _ADAPTER_REGISTRY.get(adapter_type)
        if cls is None:
            supported = list(_ADAPTER_REGISTRY.keys())
            raise RuntimeError(
                f"Unknown adapter type {adapter_type!r} for model {model_name!r}. "
                f"Supported types: {supported}"
            )

        # Build constructor kwargs from config
        kwargs: dict[str, Any] = dict(overrides or {})
        kwargs["model_name"] = model_name
        if inference_settings is not None:
            kwargs["inference_settings"] = inference_settings

        # Type-specific config mapping
        if adapter_type == "local":
            kwargs["backend"] = config.get("backend", "transformers")
            kwargs["model_path"] = config.get("model_path")
            kwargs["env_var_key"] = config.get("env_var_key")
        elif adapter_type in ("openai_compatible", "openai"):
            kwargs["base_url"] = config.get("base_url", "")
            kwargs["api_key_env"] = config.get("api_key_env", "EB_API_KEY")
            kwargs["timeout_s"] = config.get("timeout_s", 120.0)

        adapter = cls(**kwargs)
        self._adapters[model_name] = adapter
        return adapter

    def close_all(self) -> None:
        """Close all cached adapters."""
        for adapter in self._adapters.values():
            adapter.close()
        self._adapters.clear()

    def __del__(self) -> None:
        try:
            self.close_all()
        except Exception:
            pass


# Module-level singleton (lazy)
_factory: AdapterFactory | None = None


def get_factory(config_path: Path | str | None = None) -> AdapterFactory:
    """Get or create the module-level adapter factory."""
    global _factory
    if _factory is None or config_path is not None:
        _factory = AdapterFactory(config_path)
    return _factory
