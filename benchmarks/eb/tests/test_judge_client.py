"""Tests for eb/judges/client.py — Conductor judge client."""
import pytest
from unittest.mock import MagicMock, patch

from eb.judges.client import (
    JudgeAuthenticationError,
    JudgeClient,
    JudgeClientError,
    JudgeRateLimitError,
    JudgeTimeoutError,
)


class TestJudgeClient:
    def test_from_env_success(self, monkeypatch):
        monkeypatch.setenv("EB_JUDGE_BASE_URL", "https://judge.example.com/v1")
        monkeypatch.setenv("EB_JUDGE_API_KEY", "sk-test-key-1234")
        client = JudgeClient.from_env()
        assert client.base_url == "https://judge.example.com/v1"
        assert client._api_key == "sk-test-key-1234"
        del os.environ["EB_JUDGE_BASE_URL"]
        del os.environ["EB_JUDGE_API_KEY"]

    def test_from_env_missing_url(self, monkeypatch):
        monkeypatch.delenv("EB_JUDGE_BASE_URL", raising=False)
        monkeypatch.delenv("EB_JUDGE_API_KEY", raising=False)
        with pytest.raises(ValueError, match="EB_JUDGE_BASE_URL"):
            JudgeClient.from_env()

    def test_from_env_missing_key(self, monkeypatch):
        monkeypatch.setenv("EB_JUDGE_BASE_URL", "https://example.com/v1")
        monkeypatch.delenv("EB_JUDGE_API_KEY", raising=False)
        with pytest.raises(ValueError, match="EB_JUDGE_API_KEY"):
            JudgeClient.from_env()
        del os.environ["EB_JUDGE_BASE_URL"]

    def test_models_standard_response(self, monkeypatch):
        monkeypatch.setenv("EB_JUDGE_BASE_URL", "https://judge.example.com/v1")
        monkeypatch.setenv("EB_JUDGE_API_KEY", "sk-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "object": "list",
            "data": [
                {"id": "model-a", "owned_by": "provider-a", "context_length": 128000},
                {"id": "model-b", "owned_by": "provider-b"},
            ],
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response

        with patch("eb.judges.client.httpx.Client", return_value=mock_client):
            client = JudgeClient.from_env()
            models = client.discover_models()

        assert len(models) == 2
        assert models[0].id == "model-a"
        assert models[0].context_length == 128000
        assert models[1].id == "model-b"
        assert models[1].context_length is None

    def test_models_empty_list(self, monkeypatch):
        monkeypatch.setenv("EB_JUDGE_BASE_URL", "https://judge.example.com/v1")
        monkeypatch.setenv("EB_JUDGE_API_KEY", "sk-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"object": "list", "data": []}
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response

        with patch("eb.judges.client.httpx.Client", return_value=mock_client):
            client = JudgeClient.from_env()
            models = client.discover_models()

        assert models == []

    def test_authentication_failure(self, monkeypatch):
        monkeypatch.setenv("EB_JUDGE_BASE_URL", "https://judge.example.com/v1")
        monkeypatch.setenv("EB_JUDGE_API_KEY", "sk-bad-key")

        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        # Return a response object; the client will check status_code before raise_for_status
        mock_client.get.return_value = mock_response

        with patch("eb.judges.client.httpx.Client", return_value=mock_client):
            client = JudgeClient.from_env()
            with pytest.raises(JudgeAuthenticationError):
                client.discover_models()

    def test_rate_limit_triggers_retry_on_discovery(self, monkeypatch):
        """Rate limit on /models raises JudgeRateLimitError after retries exhausted."""
        monkeypatch.setenv("EB_JUDGE_BASE_URL", "https://judge.example.com/v1")
        monkeypatch.setenv("EB_JUDGE_API_KEY", "sk-key")

        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limited"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response

        with patch("eb.judges.client.httpx.Client", return_value=mock_client):
            client = JudgeClient.from_env()
            with pytest.raises(JudgeRateLimitError):
                client.discover_models()

    def test_timeout_on_discovery(self, monkeypatch):
        monkeypatch.setenv("EB_JUDGE_BASE_URL", "https://judge.example.com/v1")
        monkeypatch.setenv("EB_JUDGE_API_KEY", "sk-key")

        import httpx
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.TimeoutException("timed out")

        with patch("eb.judges.client.httpx.Client", return_value=mock_client):
            client = JudgeClient.from_env()
            with pytest.raises(JudgeTimeoutError):
                client.discover_models()

    def test_malformed_response(self, monkeypatch):
        monkeypatch.setenv("EB_JUDGE_BASE_URL", "https://judge.example.com/v1")
        monkeypatch.setenv("EB_JUDGE_API_KEY", "sk-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("invalid json")
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response

        with patch("eb.judges.client.httpx.Client", return_value=mock_client):
            client = JudgeClient.from_env()
            with pytest.raises(JudgeClientError):
                client.discover_models()

    def test_chat_completion_success(self, monkeypatch):
        monkeypatch.setenv("EB_JUDGE_BASE_URL", "https://judge.example.com/v1")
        monkeypatch.setenv("EB_JUDGE_API_KEY", "sk-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"score": 0.8}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response

        with patch("eb.judges.client.httpx.Client", return_value=mock_client):
            client = JudgeClient.from_env()
            text, latency, pt, ct = client.evaluate(
                "model-a", [{"role": "user", "content": "evaluate this"}]
            )

        assert text == '{"score": 0.8}'
        assert pt == 10
        assert ct == 5

    def test_chat_completion_auth_failure(self, monkeypatch):
        monkeypatch.setenv("EB_JUDGE_BASE_URL", "https://judge.example.com/v1")
        monkeypatch.setenv("EB_JUDGE_API_KEY", "sk-bad")

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response

        with patch("eb.judges.client.httpx.Client", return_value=mock_client):
            client = JudgeClient.from_env()
            with pytest.raises(JudgeAuthenticationError):
                client.evaluate("model-a", [{"role": "user", "content": "eval"}])

    def test_chat_completion_timeout(self, monkeypatch):
        monkeypatch.setenv("EB_JUDGE_BASE_URL", "https://judge.example.com/v1")
        monkeypatch.setenv("EB_JUDGE_API_KEY", "sk-key")

        import httpx
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.TimeoutException("timeout")

        with patch("eb.judges.client.httpx.Client", return_value=mock_client):
            client = JudgeClient.from_env()
            with pytest.raises(JudgeTimeoutError):
                client.evaluate("model-a", [{"role": "user", "content": "eval"}])

    def test_chat_completion_rate_limit_retries(self, monkeypatch):
        monkeypatch.setenv("EB_JUDGE_BASE_URL", "https://judge.example.com/v1")
        monkeypatch.setenv("EB_JUDGE_API_KEY", "sk-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"score": 0.9}'}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

        # First call rate limits, second succeeds
        rate_response = MagicMock()
        rate_response.status_code = 429
        rate_response.text = "Rate limited"

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = [rate_response, mock_response]

        with patch("eb.judges.client.httpx.Client", return_value=mock_client):
            client = JudgeClient.from_env()
            text, _, pt, ct = client.evaluate("model-a", [{"role": "user", "content": "eval"}])

        assert text == '{"score": 0.9}'
        assert mock_client.post.call_count == 2

    def test_max_retries_exhausted(self, monkeypatch):
        monkeypatch.setenv("EB_JUDGE_BASE_URL", "https://judge.example.com/v1")
        monkeypatch.setenv("EB_JUDGE_API_KEY", "sk-key")

        import httpx
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.TimeoutException("timeout")

        with patch("eb.judges.client.httpx.Client", return_value=mock_client):
            client = JudgeClient.from_env()
            # retry_count=3 exceeds max_retries=2, so should raise immediately
            with pytest.raises(JudgeClientError, match="Max retries"):
                client.evaluate("model-a", [{"role": "user", "content": "eval"}], retry_count=3)

    def test_redacted_url_no_credentials(self, monkeypatch):
        monkeypatch.setenv("EB_JUDGE_BASE_URL", "https://user:pass@example.com/v1")
        monkeypatch.setenv("EB_JUDGE_API_KEY", "sk-key")

        client = JudgeClient.from_env()
        url = client._redacted_url()
        assert "user" not in url
        assert "pass" not in url
        assert "example.com" in url

    def test_get_models_redacted(self, monkeypatch):
        monkeypatch.setenv("EB_JUDGE_BASE_URL", "https://judge.example.com/v1")
        monkeypatch.setenv("EB_JUDGE_API_KEY", "sk-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "object": "list",
            "data": [{"id": "model-a", "owned_by": "prov-a"}],
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response

        with patch("eb.judges.client.httpx.Client", return_value=mock_client):
            client = JudgeClient.from_env()
            models = client.get_models_redacted()

        assert len(models) == 1
        assert models[0]["id"] == "model-a"
        assert "api_key" not in str(models)

    def test_cache_reuse(self, monkeypatch):
        monkeypatch.setenv("EB_JUDGE_BASE_URL", "https://judge.example.com/v1")
        monkeypatch.setenv("EB_JUDGE_API_KEY", "sk-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "object": "list",
            "data": [{"id": "model-x", "owned_by": "p"}],
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response

        with patch("eb.judges.client.httpx.Client", return_value=mock_client):
            client = JudgeClient.from_env()
            m1 = client.discover_models()
            m2 = client.discover_models()  # should use cache
            assert mock_client.get.call_count == 1  # only one HTTP call
            assert m1[0].id == m2[0].id

    def test_force_refresh_bypasses_cache(self, monkeypatch):
        monkeypatch.setenv("EB_JUDGE_BASE_URL", "https://judge.example.com/v1")
        monkeypatch.setenv("EB_JUDGE_API_KEY", "sk-key")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "object": "list",
            "data": [{"id": "model-y", "owned_by": "p"}],
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response

        with patch("eb.judges.client.httpx.Client", return_value=mock_client):
            client = JudgeClient.from_env()
            client.discover_models()
            client.discover_models(force_refresh=True)
            assert mock_client.get.call_count == 2


# Need to import os for the test
import os
