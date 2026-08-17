"""Tests for eb/adapters/openai_compatible.py — OpenAI-compatible adapter."""
import pytest
from unittest.mock import MagicMock, patch

from eb.adapters.openai_compatible import OpenAICompatibleAdapter
from eb.adapters.base import ModelRequest, ModelResponse


class TestOpenAICompatibleAdapter:
    def test_missing_api_key_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("EB_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        adapter = OpenAICompatibleAdapter(
            "test-model",
            base_url="http://localhost:8000/v1",
            api_key_env="FAKE_KEY_VAR",
        )
        with pytest.raises(ValueError, match="API key not found"):
            adapter.generate(ModelRequest(model="test-model", prompt="hi"))

    def test_generates_via_http(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EB_API_KEY", "sk-test-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello world"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response

        with patch("eb.adapters.openai_compatible.httpx.Client", return_value=mock_client):
            adapter = OpenAICompatibleAdapter(
                "test-model",
                base_url="http://localhost:8000/v1",
                api_key_env="EB_API_KEY",
            )
            resp = adapter.generate(ModelRequest(model="test-model", prompt="hi"))

        assert resp.success is True
        assert resp.text == "Hello world"
        assert resp.model == "test-model"
        assert resp.backend == "openai_compatible"
        assert resp.usage.total_tokens == 8
        assert resp.finish_reason == "stop"

        # Verify the HTTP call
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "http://localhost:8000/v1/chat/completions"
        assert call_args[1]["headers"]["Authorization"] == "Bearer sk-test-key"

    def test_system_prompt_included(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EB_API_KEY", "sk-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response

        with patch("eb.adapters.openai_compatible.httpx.Client", return_value=mock_client):
            adapter = OpenAICompatibleAdapter(
                "m",
                base_url="http://localhost:8000/v1",
                api_key_env="EB_API_KEY",
            )
            resp = adapter.generate(ModelRequest(
                model="m",
                prompt="hello",
                system_prompt="you are helpful",
            ))

        call_args = mock_client.post.call_args
        payload = call_args[1]["json"]
        roles = [m["role"] for m in payload["messages"]]
        assert "system" in roles
        assert "user" in roles

    def test_custom_messages_used(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EB_API_KEY", "sk-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "reply"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response

        with patch("eb.adapters.openai_compatible.httpx.Client", return_value=mock_client):
            adapter = OpenAICompatibleAdapter("m", base_url="http://localhost:8000/v1", api_key_env="EB_API_KEY")
            resp = adapter.generate(ModelRequest(
                model="m",
                messages=[{"role": "user", "content": "custom msg"}],
            ))

        assert resp.text == "reply"

    def test_http_error_handled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EB_API_KEY", "sk-key")

        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limited"
        exc = httpx.HTTPStatusError("rate limited", request=MagicMock(), response=mock_response)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = exc

        with patch("eb.adapters.openai_compatible.httpx.Client", return_value=mock_client):
            adapter = OpenAICompatibleAdapter("m", base_url="http://localhost:8000/v1", api_key_env="EB_API_KEY")
            resp = adapter.generate(ModelRequest(model="m", prompt="hi"))

        assert resp.failed is True
        assert "429" in resp.error

    def test_timeout_handled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EB_API_KEY", "sk-key")

        import httpx
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.TimeoutException("timed out")

        with patch("eb.adapters.openai_compatible.httpx.Client", return_value=mock_client):
            adapter = OpenAICompatibleAdapter("m", base_url="http://localhost:8000/v1", api_key_env="EB_API_KEY")
            resp = adapter.generate(ModelRequest(model="m", prompt="hi"))

        assert resp.failed is True
        assert "timed out" in resp.error

    def test_closed_adapter(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EB_API_KEY", "sk-key")
        adapter = OpenAICompatibleAdapter("m", base_url="http://localhost:8000/v1", api_key_env="EB_API_KEY")
        adapter.close()
        resp = adapter.generate(ModelRequest(model="m", prompt="hi"))
        assert resp.error == "Adapter has been closed"

    def test_metadata(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EB_API_KEY", "sk-key")
        adapter = OpenAICompatibleAdapter("m", base_url="http://localhost:8000/v1", api_key_env="EB_API_KEY")
        meta = adapter.metadata()
        assert meta.adapter_type == "local"
        assert meta.backend == "openai_compatible"
        assert meta.model_name == "m"

    def test_api_key_redacted_in_metadata(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EB_API_KEY", "sk-secret-123")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response

        with patch("eb.adapters.openai_compatible.httpx.Client", return_value=mock_client):
            adapter = OpenAICompatibleAdapter("m", base_url="http://localhost:8000/v1", api_key_env="EB_API_KEY")
            resp = adapter.generate(ModelRequest(model="m", prompt="hi"))

        pm = resp.provider_metadata
        assert pm.get("api_key_env") == "EB_API_KEY"
        assert "sk-secret" not in str(pm)
