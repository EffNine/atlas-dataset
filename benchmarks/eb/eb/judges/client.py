#!/usr/bin/env python3
"""
client.py — Conductor OpenAI-compatible judge client for EB.

Targets a single OpenAI-compatible gateway (Conductor) for cloud judge
evaluations. Supports model discovery (GET /models) and chat completions
(POST /chat/completions).

Never hardcodes model names, base URLs, or API keys.
Never prints or persists API keys.
"""

from __future__ import annotations

import json
import time
import urllib.parse
from typing import Any

import httpx

from ..core.schema import JudgeModelInfo
from ..env_config import JUDGE_API_KEY_VAR, JUDGE_BASE_URL_VAR, redact


class JudgeClientError(Exception):
    """Base exception for judge client errors."""


class JudgeAuthenticationError(JudgeClientError):
    """Raised when authentication fails."""


class JudgeTimeoutError(JudgeClientError):
    """Raised when a request times out."""


class JudgeRateLimitError(JudgeClientError):
    """Raised when the gateway rate-limits the request."""


class JudgeClient:
    """
    OpenAI-compatible client for the Conductor judge gateway.

    All requests use the configured base URL and API key from environment.
    The client performs model discovery via GET /models and evaluates
    via POST /chat/completions.
    """

    DEFAULT_TIMEOUT_S = 120.0
    DEFAULT_MAX_RETRIES = 2
    MODELS_CACHE_TTL_S = 300.0  # 5 minutes

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._models_cache: dict[str, Any] = {}
        self._models_cache_time: float = 0.0
        self._provider_name: str | None = None

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def provider_name(self) -> str | None:
        return self._provider_name

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

    def _redacted_url(self) -> str:
        """Return a redacted URL for logging (credentials stripped)."""
        try:
            parsed = urllib.parse.urlparse(self._base_url)
            netloc = parsed.hostname or ""
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            return f"{parsed.scheme}://{netloc}{parsed.path}"
        except Exception:
            return "[redacted]"

    # ------------------------------------------------------------------
    # Model discovery
    # ------------------------------------------------------------------

    def discover_models(self, force_refresh: bool = False) -> list[JudgeModelInfo]:
        """
        Discover available judge models from the gateway.

        Results are cached for MODELS_CACHE_TTL_S seconds unless
        force_refresh is True.

        Returns:
            List of normalized JudgeModelInfo objects.

        Raises:
            JudgeAuthenticationError: If the API key is invalid.
            JudgeClientError: If /models is unavailable or malformed.
        """
        if not force_refresh:
            cached = self._models_cache.get("models")
            cache_time = self._models_cache.get("time", 0.0)
            if cached is not None and (time.time() - cache_time) < self.MODELS_CACHE_TTL_S:
                return cached

        url = f"{self._base_url}/models"
        start = time.time()
        try:
            with httpx.Client(timeout=self._timeout_s) as client:
                response = client.get(url, headers=self._headers())

            if response.status_code == 401 or response.status_code == 403:
                raise JudgeAuthenticationError(
                    f"Authentication failed against {self._redacted_url()}"
                )

            if response.status_code == 429:
                raise JudgeRateLimitError(
                    f"Rate limited by {self._redacted_url()}"
                )

            response.raise_for_status()
            data = response.json()

            # Handle both dict and list response formats
            if isinstance(data, list):
                raw_models = data
                self._provider_name = "unknown"
            elif isinstance(data, dict):
                self._provider_name = data.get("object") or data.get("data", [{}])[0].get("owned_by", "unknown")
                raw_models = data.get("data", [])
                if not raw_models and "models" in data:
                    raw_models = data["models"]
            else:
                raw_models = []

            results = []
            for m in raw_models:
                info = self._normalize_model(m)
                if info:
                    results.append(info)

            # Cache the result
            self._models_cache = {"models": results, "time": time.time()}
            return results

        except JudgeAuthenticationError:
            raise
        except JudgeRateLimitError:
            raise
        except httpx.TimeoutException:
            elapsed = time.time() - start
            raise JudgeTimeoutError(
                f"Model discovery timed out after {elapsed:.1f}s against {self._redacted_url()}"
            )
        except httpx.HTTPStatusError as e:
            elapsed = time.time() - start
            raise JudgeClientError(
                f"Model discovery HTTP {e.response.status_code} after {elapsed:.1f}s: "
                f"{e.response.text[:300]}"
            )
        except httpx.HTTPError as e:
            raise JudgeClientError(f"Model discovery failed: {e}")
        except Exception as e:
            raise JudgeClientError(f"Model discovery error: {type(e).__name__}: {e}")

    def _normalize_model(self, raw: dict[str, Any]) -> JudgeModelInfo | None:
        """Normalize a raw model entry from the /models response."""
        model_id = raw.get("id")
        if not model_id:
            return None

        info = JudgeModelInfo(
            id=model_id,
            owned_by=raw.get("owned_by"),
            context_length=self._extract_context_length(raw),
            created=raw.get("created"),
            capabilities=self._extract_capabilities(raw),
            modality=raw.get("modality") or self._infer_modality(raw),
            provider_metadata={
                k: v for k, v in raw.items()
                if k not in ("id", "owned_by", "context_length", "created", "modality")
            },
            raw_metadata=raw,
        )
        return info

    @staticmethod
    def _extract_context_length(raw: dict[str, Any]) -> int | None:
        """Extract context length from various gateway response formats."""
        for key in ("context_length", "max_context_tokens", "max_tokens", "contextWindowSize"):
            val = raw.get(key)
            if val is not None:
                try:
                    return int(val)
                except (TypeError, ValueError):
                    continue
        # Try to parse from id (e.g. "model-32k")
        model_id = raw.get("id", "")
        import re
        match = re.search(r"(\d+)k", model_id, re.IGNORECASE)
        if match:
            return int(match.group(1)) * 1024
        match = re.search(r"(\d+)m", model_id, re.IGNORECASE)
        if match:
            return int(match.group(1)) * 1000000
        return None

    @staticmethod
    def _extract_capabilities(raw: dict[str, Any]) -> dict[str, float]:
        """Extract capability scores from gateway metadata if available."""
        caps: dict[str, float] = {}
        for key in ("capabilities", "tags", "metadata"):
            val = raw.get(key)
            if isinstance(val, dict):
                for k, v in val.items():
                    if isinstance(v, (int, float)):
                        caps[k] = float(v)
        return caps

    @staticmethod
    def _infer_modality(raw: dict[str, Any]) -> str | None:
        """Infer modality from model ID or metadata heuristics."""
        model_id = raw.get("id", "").lower()
        if any(kw in model_id for kw in ("vision", "vl", "img", "image")):
            return "vision"
        # Default to text for known text-only models
        if any(kw in model_id for kw in ("text", "instruct", "base", "turbo", "pro", "mini")):
            return "text"
        return None

    # ------------------------------------------------------------------
    # Chat completions (judge evaluation)
    # ------------------------------------------------------------------

    def evaluate(
        self,
        model_id: str,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 2048,
        temperature: float = 0.0,
        timeout_s: float | None = None,
        retry_count: int = 0,
    ) -> tuple[str, float, int, int]:
        """
        Send a judge evaluation request and return the response text.

        Args:
            model_id: Model to use for judging.
            messages: Chat messages list.
            max_tokens: Maximum completion tokens.
            temperature: Sampling temperature.
            timeout_s: Override default timeout.
            retry_count: Current retry attempt (for internal use).

        Returns:
            (response_text, latency_s, prompt_tokens, completion_tokens)

        Raises:
            JudgeAuthenticationError: On auth failure (not retried).
            JudgeTimeoutError: On timeout.
            JudgeRateLimitError: On rate limit (may be retried).
            JudgeClientError: On other failures.
        """
        if retry_count > self._max_retries:
            raise JudgeClientError(f"Max retries ({self._max_retries}) exhausted")

        url = f"{self._base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }

        timeout = timeout_s or self._timeout_s
        start = time.time()

        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(url, json=payload, headers=self._headers())

            if response.status_code == 401 or response.status_code == 403:
                raise JudgeAuthenticationError(
                    f"Authentication failed against {self._redacted_url()}"
                )

            if response.status_code == 429:
                if retry_count < self._max_retries:
                    wait = min(2 ** retry_count, 30)
                    time.sleep(wait)
                    return self.evaluate(
                        model_id, messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        timeout_s=timeout_s,
                        retry_count=retry_count + 1,
                    )
                raise JudgeRateLimitError(
                    f"Rate limited after {retry_count + 1} attempts against {self._redacted_url()}"
                )

            response.raise_for_status()
            data = response.json()
            latency = time.time() - start

            choice = data.get("choices", [{}])[0]
            text = choice.get("message", {}).get("content", "")

            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)

            return text, latency, prompt_tokens, completion_tokens

        except JudgeAuthenticationError:
            raise
        except JudgeRateLimitError:
            raise
        except httpx.TimeoutException:
            latency = time.time() - start
            if retry_count < self._max_retries:
                time.sleep(min(2 ** retry_count, 30))
                return self.evaluate(
                    model_id, messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout_s=timeout_s,
                    retry_count=retry_count + 1,
                )
            raise JudgeTimeoutError(
                f"Judge request timed out after {latency:.1f}s (retry {retry_count + 1})"
            )
        except httpx.HTTPStatusError as e:
            latency = time.time() - start
            raise JudgeClientError(
                f"HTTP {e.response.status_code} after {latency:.1f}s: "
                f"{e.response.text[:300]}"
            )
        except httpx.HTTPError as e:
            raise JudgeClientError(f"Judge request failed: {e}")
        except Exception as e:
            raise JudgeClientError(f"Unexpected error: {type(e).__name__}: {e}")

    def get_models_redacted(self) -> list[dict[str, Any]]:
        """
        Return model list with sensitive data stripped.
        Safe for logging.
        """
        models = self.discover_models()
        result = []
        for m in models:
            result.append({
                "id": m.id,
                "owned_by": m.owned_by,
                "context_length": m.context_length,
                "modality": m.modality,
            })
        return result

    @classmethod
    def from_env(
        cls,
        *,
        base_url_env: str = JUDGE_BASE_URL_VAR,
        api_key_env: str = JUDGE_API_KEY_VAR,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> JudgeClient:
        """
        Create a JudgeClient from environment variables.

        Raises:
            ValueError: If required environment variables are not set.
        """
        import os
        base_url = os.environ.get(base_url_env, "")
        api_key = os.environ.get(api_key_env, "")

        if not base_url:
            raise ValueError(f"{base_url_env} is not set")
        if not api_key:
            raise ValueError(f"{api_key_env} is not set")

        return cls(
            base_url=base_url,
            api_key=api_key,
            timeout_s=timeout_s,
            max_retries=max_retries,
        )
