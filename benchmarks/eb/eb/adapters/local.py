#!/usr/bin/env python3
"""
local.py — Local model inference adapter for the EffNine Benchmark (EB).

Provides a backend abstraction for local inference. Initially supports one
concrete backend (transformers-based) while keeping the interface open for
future backends (vLLM, llama.cpp, etc.).

Usage:
    adapter = LocalModelAdapter(
        model_name="atan-v1",
        backend="transformers",
        model_path="/path/to/model",
    )
    response = adapter.generate(request)
"""

from __future__ import annotations

import os
from typing import Any

from .base import AdapterMetadata, ModelAdapter, ModelRequest, ModelResponse, TokenUsage


# ---------------------------------------------------------------------------
# Backend protocols (interfaces, not implementations)
# ---------------------------------------------------------------------------


class _Backend(staticmethod):
    """Marker: concrete backends must implement this interface."""

    def generate(self, prompt: str, settings: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Return (text, metadata) from the backend."""
        raise NotImplementedError

    def is_available(self) -> bool:
        """Check whether the backend can load the requested model."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Transformers backend (initial concrete implementation)
# ---------------------------------------------------------------------------


class _TransformersBackend:
    """
    Backend using HuggingFace transformers pipeline.

    Loads models with AutoModelForCausalLM + AutoTokenizer. Supports CUDA
    acceleration when available. Falls back to CPU otherwise.
    """

    def __init__(self, model_path: str, device_map: str | None = None) -> None:
        self._model_path = model_path
        self._device_map = device_map
        self._tokenizer = None
        self._model = None
        self._loaded = False

    def is_available(self) -> bool:
        try:
            import torch  # noqa: F811
            from transformers import AutoModelForCausalLM, AutoTokenizer  # noqa: F811
            return True
        except ImportError:
            return False

    def load(self) -> None:
        if self._loaded:
            return
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._tokenizer = AutoTokenizer.from_pretrained(self._model_path, trust_remote_code=True)
            self._model = AutoModelForCausalLM.from_pretrained(
                self._model_path,
                torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
                device_map=self._device_map or ("auto" if torch.cuda.is_available() else "cpu"),
                trust_remote_code=True,
            )
            if not hasattr(self._tokenizer, "pad_token") or self._tokenizer.pad_token is None:
                self._tokenizer.pad_token = self._tokenizer.eos_token
            self._model.eval()
            self._loaded = True
        except ImportError as e:
            raise RuntimeError(
                f"Local transformers backend requires 'transformers' and 'torch'. "
                f"Install with: pip install transformers torch\nCause: {e}"
            ) from e
        except OSError as e:
            raise RuntimeError(
                f"Failed to load model from {self._model_path}. "
                f"Ensure the path exists and contains valid model weights.\nCause: {e}"
            ) from e

    def generate(self, prompt: str, settings: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if not self._loaded:
            self.load()

        max_tokens = settings.get("max_tokens", 4096)
        temperature = settings.get("temperature", 0.0)
        top_p = settings.get("top_p", 1.0)
        top_k = settings.get("top_k", 0)
        seed = settings.get("seed", 42)

        inputs = self._tokenizer(prompt, return_tensors="pt")
        input_ids = inputs["input_ids"]
        attention_mask = inputs.get("attention_mask", input_ids)

        import torch

        # Move inputs to the same device as the model
        model_device = next(self._model.parameters()).device
        if model_device.type == "cuda":
            input_ids = input_ids.to("cuda")
            attention_mask = attention_mask.to("cuda")

        gen_kwargs: dict[str, Any] = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "max_new_tokens": max_tokens,
            "do_sample": temperature > 0,
            "pad_token_id": self._tokenizer.pad_token_id,
        }
        if temperature > 0:
            gen_kwargs["temperature"] = temperature
            gen_kwargs["top_p"] = top_p
        if top_k > 0:
            gen_kwargs["top_k"] = top_k

        if seed is not None:
            torch.manual_seed(seed)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(seed)

        with torch.no_grad():
            outputs = self._model.generate(**gen_kwargs)

        # Handle empty generation gracefully — some models (especially with
        # LoRA wrappers or NF4 quantization) may return zero new tokens and
        # trigger internal reshape operations that fail on empty tensors.
        try:
            generated_ids = outputs[0][input_ids.shape[-1]:]
        except (IndexError, RuntimeError) as e:
            # Model returned fewer tokens than input; treat as empty response
            generated_ids = torch.empty(0, dtype=input_ids.dtype, device=input_ids.device)

        if generated_ids.numel() == 0:
            return "", {
                "prompt_tokens": len(input_ids[0]),
                "completion_tokens": 0,
            }

        try:
            text = self._tokenizer.decode(generated_ids, skip_special_tokens=True)
        except Exception:
            text = ""

        return text, {
            "prompt_tokens": len(input_ids[0]),
            "completion_tokens": len(generated_ids),
        }


# ---------------------------------------------------------------------------
# LocalModelAdapter
# ---------------------------------------------------------------------------


_SUPPORTED_BACKENDS = {
    "transformers": _TransformersBackend,
}


class LocalModelAdapter(ModelAdapter):
    """
    Local model inference adapter with pluggable backends.

    Configuration precedence (highest to lowest):
      1. CLI override (passed via inference_settings)
      2. Config file (models.yaml)
      3. Schema defaults (InferenceSettings)
    """

    def __init__(
        self,
        model_name: str,
        *,
        backend: str = "transformers",
        model_path: str | None = None,
        inference_settings: InferenceSettings | None = None,
        env_var_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        if backend not in _SUPPORTED_BACKENDS:
            supported = list(_SUPPORTED_BACKENDS.keys())
            raise ValueError(
                f"Unsupported local backend {backend!r}. "
                f"Supported: {supported}"
            )

        super().__init__(model_name, inference_settings)

        self._backend_name = backend
        self._kwargs = kwargs
        self._backend_instance: Any = None
        self._model_path = model_path or os.environ.get("EB_LOCAL_MODEL_PATH")

        if self._model_path is None:
            raise ValueError(
                f"model_path is required for local adapter '{backend}'. "
                f"Set it in config/models.yaml or via EB_LOCAL_MODEL_PATH."
            )

    def _ensure_backend(self) -> None:
        if self._backend_instance is None:
            cls = _SUPPORTED_BACKENDS[self._backend_name]
            self._backend_instance = cls(self._model_path, **self._kwargs)
            if not self._backend_instance.is_available():
                raise RuntimeError(
                    f"Backend '{self._backend_name}' is not available. "
                    f"Check that required dependencies are installed."
                )

    def generate(self, request: ModelRequest) -> ModelResponse:
        if self._closed:
            return ModelResponse(
                text="",
                model=self._model_name,
                error="Adapter has been closed",
                backend=self._backend_name,
            )

        self._validate_request(request)
        self._ensure_backend()

        settings = request.inference_settings or self._inference_settings

        # Convert messages to prompt if messages are provided (for multi-turn
        # EXEC/MULTI tasks). Otherwise use the prompt directly (SINGLE/LONG).
        if request.messages:
            try:
                # Ensure backend is loaded so tokenizer is available
                self._backend_instance.load()
                prompt_text = self._backend_instance._tokenizer.apply_chat_template(
                    request.messages,
                    tokenize=False,
                    add_generation_prompt=True,
                )
            except Exception as e:
                raise RuntimeError(
                    f"Failed to apply chat template for {len(request.messages)} message(s): {e}"
                ) from e
        else:
            prompt_text = request.prompt

        start = __import__("time").time()
        try:
            text, backend_meta = self._backend_instance.generate(prompt_text, {
                "max_tokens": settings.max_tokens,
                "temperature": settings.temperature,
                "top_p": settings.top_p,
                "top_k": settings.top_k,
                "seed": settings.seed,
            })
            latency = __import__("time").time() - start

            usage = TokenUsage(
                prompt_tokens=backend_meta.get("prompt_tokens", 0),
                completion_tokens=backend_meta.get("completion_tokens", 0),
            )

            return ModelResponse(
                text=text,
                model=self._model_name,
                finish_reason="stop",
                usage=usage,
                latency_s=latency,
                backend=self._backend_name,
                provider_metadata={"model_path": self._model_path},
            )
        except Exception as e:
            latency = __import__("time").time() - start
            return ModelResponse(
                text="",
                model=self._model_name,
                error=str(e),
                backend=self._backend_name,
                latency_s=latency,
                provider_metadata={"model_path": self._model_path},
            )

    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            adapter_type="local",
            backend=self._backend_name,
            model_name=self._model_name,
            supported_settings=["seed", "temperature", "top_p", "top_k", "max_tokens", "context_length"],
            version="0.1.0",
            extra={"model_path": self._model_path},
        )

    def close(self) -> None:
        super().close()
        self._backend_instance = None
