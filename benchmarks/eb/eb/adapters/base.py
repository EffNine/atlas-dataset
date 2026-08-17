#!/usr/bin/env python3
"""
base.py — Abstract ModelAdapter contract for the EffNine Benchmark (EB).

Defines the framework-agnostic interface that all model inference backends
must implement. The runner layer depends only on this interface, never on
concrete backend implementations.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ModelRequest:
    """Canonical request sent to a model adapter."""

    model: str
    prompt: str = ""
    system_prompt: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, str]] | None = None
    inference_settings: InferenceSettings | None = None

    def __post_init__(self) -> None:
        has_prompt = bool(self.prompt)
        has_messages = self.messages is not None
        if has_prompt and has_messages:
            raise ValueError("Cannot set both 'messages' and 'prompt'")
        if not has_prompt and not has_messages:
            raise ValueError("Must set either 'prompt' or 'messages'")


@dataclass
class TokenUsage:
    """Token usage statistics from a model response."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        if self.total_tokens == 0:
            self.total_tokens = self.prompt_tokens + self.completion_tokens

    @property
    def has_usage(self) -> bool:
        return self.total_tokens > 0


@dataclass
class ModelResponse:
    """Canonical response from a model adapter."""

    text: str
    model: str
    finish_reason: str | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    latency_s: float = 0.0
    error: str | None = None
    backend: str = "unknown"
    provider_metadata: dict[str, Any] = field(default_factory=dict)
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def failed(self) -> bool:
        return self.error is not None

    @property
    def success(self) -> bool:
        return not self.failed and bool(self.text)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "text": self.text,
            "model": self.model,
            "finish_reason": self.finish_reason,
            "usage": {
                "prompt_tokens": self.usage.prompt_tokens,
                "completion_tokens": self.usage.completion_tokens,
                "total_tokens": self.usage.total_tokens,
            },
            "latency_s": round(self.latency_s, 4),
            "error": self.error,
            "backend": self.backend,
            "generated_at": self.generated_at,
        }
        # Redact secrets in provider metadata
        redacted = {}
        for k, v in self.provider_metadata.items():
            if any(secret in k.lower() for secret in ("key", "token", "secret", "password")):
                redacted[k] = "[REDACTED]"
            else:
                redacted[k] = v
        if redacted:
            d["provider_metadata"] = redacted
        return d


@dataclass
class AdapterMetadata:
    """Static metadata about an adapter instance."""

    adapter_type: str
    backend: str
    model_name: str
    supported_settings: list[str] = field(default_factory=list)
    version: str = "0.1.0"
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "adapter_type": self.adapter_type,
            "backend": self.backend,
            "model_name": self.model_name,
            "supported_settings": self.supported_settings,
            "version": self.version,
            "extra": self._redact_extra(self.extra),
        }
        return d

    @staticmethod
    def _redact_extra(extra: dict[str, Any]) -> dict[str, Any]:
        """Redact sensitive values in extra metadata."""
        redacted = {}
        for k, v in extra.items():
            if any(secret in k.lower() for secret in ("key", "token", "secret", "password")):
                redacted[k] = "[REDACTED]"
            else:
                redacted[k] = v
        return redacted


from ..core.schema import InferenceSettings  # noqa: E402


class ModelAdapter(ABC):
    """
    Abstract base class for model inference adapters.

    All concrete adapters must implement generate(), metadata(), and close().
    The adapter is responsible for:
      - Translating ModelRequest into backend-specific API calls
      - Normalizing responses into ModelResponse
      - Tracking latency and token usage
      - Managing connection lifecycle via close()
    """

    def __init__(self, model_name: str, inference_settings: InferenceSettings | None = None) -> None:
        self._model_name = model_name
        self._inference_settings = inference_settings or InferenceSettings()
        self._closed = False

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def inference_settings(self) -> InferenceSettings:
        return self._inference_settings

    @abstractmethod
    def generate(self, request: ModelRequest) -> ModelResponse:
        """
        Generate a response for the given request.

        Must be idempotent for the same seed+settings combination when the
        backend supports deterministic sampling.

        Returns:
            ModelResponse with normalized fields. On failure, populate
            `error` rather than raising (unless the error is fatal/config-level).
        """
        ...

    @abstractmethod
    def metadata(self) -> AdapterMetadata:
        """Return static metadata about this adapter instance."""
        ...

    def close(self) -> None:
        """Release any resources held by the adapter."""
        self._closed = True

    def __enter__(self) -> ModelAdapter:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def _record_latency(self, start: float) -> float:
        return time.time() - start

    def _validate_request(self, request: ModelRequest) -> None:
        """Validate request against adapter capabilities. Raises ValueError on issues."""
        settings = request.inference_settings or self._inference_settings
        meta = self.metadata()
        unsupported = [
            s for s in InferenceSettings.model_fields.keys()
            if s != "tool_configuration" and s not in meta.supported_settings and meta.supported_settings
        ]
        if unsupported:
            raise ValueError(
                f"Adapter {meta.backend} does not support settings: {unsupported}"
            )
