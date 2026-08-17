#!/usr/bin/env python3
"""
openai_compatible.py — OpenAI-compatible API adapter for the EffNine Benchmark (EB).

Connects to any OpenAI-compatible endpoint (vLLM serving, LM Studio,
OpenRouter, local OpenAI server, etc.) via HTTP. API keys are read from
environment variables, never hardcoded or written to artifacts.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from ..core.schema import InferenceSettings
from .base import AdapterMetadata, ModelAdapter, ModelRequest, ModelResponse, TokenUsage


class OpenAICompatibleAdapter(ModelAdapter):
    """
    Adapter for OpenAI-compatible chat completions API.

    Supports any server that implements the OpenAI chat completions interface,
    including vLLM, Ollama (with openai prefix), LM Studio, and cloud providers.

    Configuration precedence (highest to lowest):
      1. CLI override (passed via inference_settings)
      2. Config file (models.yaml)
      3. Environment variables
      4. Schema defaults (InferenceSettings)
    """

    DEFAULT_TIMEOUT_S = 120.0
    DEFAULT_MAX_RETRIES = 3

    def __init__(
        self,
        model_name: str,
        *,
        base_url: str,
        api_key_env: str = "EB_API_KEY",
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
        inference_settings: InferenceSettings | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(model_name, inference_settings)

        self._base_url = base_url.rstrip("/")
        self._api_key_env = api_key_env
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._extra = kwargs

        # Resolve API key from environment (never store plaintext)
        self._api_key = os.environ.get(api_key_env) or os.environ.get("OPENAI_API_KEY")

    def _get_api_key(self) -> str:
        if not self._api_key:
            raise ValueError(
                f"API key not found. Set environment variable {self._api_key_env} "
                f"or OPENAI_API_KEY."
            )
        return self._api_key

    def generate(self, request: ModelRequest) -> ModelResponse:
        if self._closed:
            return ModelResponse(
                text="",
                model=self._model_name,
                error="Adapter has been closed",
                backend="openai_compatible",
            )

        self._validate_request(request)

        settings = request.inference_settings or self._inference_settings
        api_key = self._get_api_key()

        # Build messages list
        if request.messages:
            messages = list(request.messages)
        else:
            messages = []
            if request.system_prompt:
                messages.append({"role": "system", "content": request.system_prompt})
            messages.append({"role": "user", "content": request.prompt})

        payload: dict[str, Any] = {
            "model": self._model_name,
            "messages": messages,
            "max_tokens": settings.max_tokens,
            "temperature": settings.temperature,
            "top_p": settings.top_p,
            "seed": settings.seed if settings.seed is not None else None,
        }
        # Only include top_k if > 0 (many providers treat 0 as "not set")
        if settings.top_k > 0:
            payload["top_k"] = settings.top_k

        # Filter out None values
        payload = {k: v for k, v in payload.items() if v is not None}
        payload.update(self._extra)

        url = f"{self._base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        start = __import__("time").time()
        try:
            with httpx.Client(timeout=self._timeout_s) as client:
                response = client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()

            latency = __import__("time").time() - start

            choice = data.get("choices", [{}])[0]
            text = choice.get("message", {}).get("content", "")
            finish_reason = choice.get("finish_reason")

            usage_data = data.get("usage", {})
            usage = TokenUsage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
            )

            return ModelResponse(
                text=text,
                model=self._model_name,
                finish_reason=finish_reason,
                usage=usage,
                latency_s=latency,
                backend="openai_compatible",
                provider_metadata={
                    "base_url": self._base_url,
                    "api_key_env": self._api_key_env,
                },
            )
        except httpx.HTTPStatusError as e:
            latency = __import__("time").time() - start
            return ModelResponse(
                text="",
                model=self._model_name,
                error=f"HTTP {e.response.status_code}: {e.response.text[:500]}",
                backend="openai_compatible",
                latency_s=latency,
                provider_metadata={"base_url": self._base_url},
            )
        except httpx.TimeoutException as e:
            latency = __import__("time").time() - start
            return ModelResponse(
                text="",
                model=self._model_name,
                error=f"Request timed out after {self._timeout_s}s: {e}",
                backend="openai_compatible",
                latency_s=latency,
                provider_metadata={"base_url": self._base_url},
            )
        except httpx.HTTPError as e:
            latency = __import__("time").time() - start
            return ModelResponse(
                text="",
                model=self._model_name,
                error=f"HTTP error: {e}",
                backend="openai_compatible",
                latency_s=latency,
                provider_metadata={"base_url": self._base_url},
            )
        except Exception as e:
            latency = __import__("time").time() - start
            return ModelResponse(
                text="",
                model=self._model_name,
                error=f"Unexpected error: {type(e).__name__}: {e}",
                backend="openai_compatible",
                latency_s=latency,
                provider_metadata={"base_url": self._base_url},
            )

    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            adapter_type="local",
            backend="openai_compatible",
            model_name=self._model_name,
            supported_settings=["seed", "temperature", "top_p", "top_k", "max_tokens", "context_length"],
            version="0.1.0",
            extra={"base_url": self._base_url, "api_key_env": self._api_key_env},
        )

    def close(self) -> None:
        super().close()
