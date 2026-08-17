"""Tests for eb/adapters/base.py — ModelAdapter contract."""
import pytest

from eb.adapters.base import (
    AdapterMetadata,
    ModelAdapter,
    ModelRequest,
    ModelResponse,
    TokenUsage,
)
from eb.core.schema import InferenceSettings


class _TestAdapter(ModelAdapter):
    """Concrete test adapter that always returns a fixed response."""

    def __init__(self, model_name: str = "test-model", **kwargs) -> None:
        super().__init__(model_name, **kwargs)
        self._call_count = 0
        self._raise_on_generate = False
        self._gen_error: str | None = None

    def generate(self, request: ModelRequest) -> ModelResponse:
        if self._closed:
            return ModelResponse(
                text="",
                model=self._model_name,
                error="Adapter has been closed",
                backend="test",
            )
        if self._raise_on_generate:
            raise RuntimeError(self._gen_error or "test error")
        self._call_count += 1
        return ModelResponse(
            text="test response",
            model=self._model_name,
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            latency_s=0.123,
            backend="test",
        )

    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            adapter_type="test",
            backend="test-backend",
            model_name=self._model_name,
            supported_settings=["seed", "temperature", "top_p", "top_k", "max_tokens"],
        )


class TestModelRequest:
    def test_valid_prompt(self):
        req = ModelRequest(model="m", prompt="hello")
        assert req.prompt == "hello"
        assert req.messages is None

    def test_valid_messages(self):
        req = ModelRequest(model="m", messages=[{"role": "user", "content": "hi"}])
        assert req.messages is not None
        assert req.prompt == ""

    def test_both_prompt_and_messages_rejected(self):
        with pytest.raises(ValueError, match="both"):
            ModelRequest(model="m", prompt="x", messages=[{"role": "user", "content": "y"}])

    def test_neither_prompt_nor_messages_rejected(self):
        with pytest.raises(ValueError, match="either"):
            ModelRequest(model="m", prompt="", messages=None)

    def test_system_prompt(self):
        req = ModelRequest(model="m", prompt="hi", system_prompt="you are helpful")
        assert req.system_prompt == "you are helpful"

    def test_context(self):
        req = ModelRequest(model="m", prompt="hi", context={"domain": "code"})
        assert req.context == {"domain": "code"}


class TestModelResponse:
    def test_success(self):
        r = ModelResponse(text="hello", model="m")
        assert r.success is True
        assert r.failed is False

    def test_empty_text_not_success(self):
        r = ModelResponse(text="", model="m")
        assert r.success is False

    def test_error(self):
        r = ModelResponse(text="", model="m", error="boom")
        assert r.failed is True
        assert r.success is False

    def test_to_dict_redacts_secrets(self):
        r = ModelResponse(
            text="hello",
            model="m",
            backend="test",
            provider_metadata={
                "api_key": "secret123",
                "base_url": "http://example.com",
                "token": "abc",
            },
        )
        d = r.to_dict()
        assert d["provider_metadata"]["api_key"] == "[REDACTED]"
        assert d["provider_metadata"]["token"] == "[REDACTED]"
        assert d["provider_metadata"]["base_url"] == "http://example.com"

    def test_usage_fields(self):
        r = ModelResponse(
            text="hello",
            model="m",
            usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
        )
        d = r.to_dict()
        assert d["usage"]["total_tokens"] == 150


class TestAdapterContract:
    def test_abstract_methods(self):
        with pytest.raises(TypeError):
            ModelAdapter()  # type: ignore[abstract]

    def test_generate_returns_model_response(self):
        adapter = _TestAdapter()
        req = ModelRequest(model="test-model", prompt="hello")
        resp = adapter.generate(req)
        assert isinstance(resp, ModelResponse)
        assert resp.text == "test response"
        assert resp.model == "test-model"

    def test_metadata_returns_adapter_metadata(self):
        adapter = _TestAdapter()
        meta = adapter.metadata()
        assert isinstance(meta, AdapterMetadata)
        assert meta.adapter_type == "test"
        assert meta.model_name == "test-model"

    def test_close_lifecycle(self):
        adapter = _TestAdapter()
        adapter.close()
        assert adapter._closed is True
        # After close, generate should return error response
        resp = adapter.generate(ModelRequest(model="m", prompt="hi"))
        assert resp.error == "Adapter has been closed"

    def test_context_manager(self):
        with _TestAdapter() as adapter:
            assert adapter._closed is False
        assert adapter._closed is True

    def test_validation_raises_on_unsupported_setting(self):
        adapter = _TestAdapter()
        # adapter supports all standard settings, so this should not raise
        req = ModelRequest(
            model="m",
            prompt="hi",
            inference_settings=InferenceSettings(seed=1, temperature=0.5, max_tokens=100),
        )
        resp = adapter.generate(req)
        assert resp.success is True

    def test_inference_settings_passed_through(self):
        settings = InferenceSettings(seed=99, temperature=0.7, max_tokens=2048)
        adapter = _TestAdapter(inference_settings=settings)
        assert adapter.inference_settings.seed == 99
        assert adapter.inference_settings.temperature == 0.7


class TestTokenUsage:
    def test_defaults(self):
        u = TokenUsage()
        assert u.prompt_tokens == 0
        assert u.has_usage is False

    def test_with_values(self):
        u = TokenUsage(prompt_tokens=10, completion_tokens=5)
        assert u.total_tokens == 15
        assert u.has_usage is True
