"""Tests for eb/adapters/local.py — Local adapter with backend abstraction."""
import pytest

from eb.adapters.local import LocalModelAdapter
from eb.adapters.base import ModelRequest


class TestLocalAdapter:
    def test_unsupported_backend_rejected(self):
        with pytest.raises(ValueError, match="Unsupported local backend"):
            LocalModelAdapter("m", backend="nonexistent")

    def test_missing_model_path_rejected(self):
        with pytest.raises(ValueError, match="model_path is required"):
            LocalModelAdapter("m", backend="transformers")

    def test_metadata(self):
        adapter = LocalModelAdapter(
            "atan-v1",
            backend="transformers",
            model_path="/fake/model/path",
        )
        meta = adapter.metadata()
        assert meta.adapter_type == "local"
        assert meta.backend == "transformers"
        assert meta.model_name == "atan-v1"
        assert "model_path" in meta.extra

    def test_close(self):
        adapter = LocalModelAdapter(
            "m",
            backend="transformers",
            model_path="/fake/path",
        )
        adapter.close()
        resp = adapter.generate(ModelRequest(model="m", prompt="hi"))
        assert resp.error == "Adapter has been closed"


class TestLocalAdapterBackendFailure:
    def test_backend_unavailable_raises_on_generate(self):
        """When the transformers backend can't load, generate should fail gracefully."""
        adapter = LocalModelAdapter(
            "m",
            backend="transformers",
            model_path="/nonexistent/model",
        )
        resp = adapter.generate(ModelRequest(model="m", prompt="hi"))
        # Should return an error response, not raise
        assert resp.failed is True
        assert resp.error is not None


class TestLocalAdapterModelNotFound:
    def test_invalid_model_path(self):
        """When the model path doesn't exist, should return actionable error."""
        adapter = LocalModelAdapter(
            "m",
            backend="transformers",
            model_path="/definitely/does/not/exist/model",
        )
        resp = adapter.generate(ModelRequest(model="m", prompt="hi"))
        assert resp.failed is True
        assert "model" in resp.error.lower() or "load" in resp.error.lower() or "path" in resp.error.lower()
