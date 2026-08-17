"""Tests for eb/judges/discovery.py — Judge model discovery."""
import pytest
from unittest.mock import MagicMock, patch

from eb.judges.client import JudgeClient, JudgeClientError
from eb.core.schema import JudgeModelInfo


class TestModelDiscovery:
    def test_standard_openai_format(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "object": "list",
            "data": [
                {"id": "gpt-4", "owned_by": "openai", "context_length": 8192},
                {"id": "gpt-3.5-turbo", "owned_by": "openai"},
            ],
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response

        with patch("eb.judges.client.httpx.Client", return_value=mock_client):
            client = JudgeClient(base_url="http://test.com/v1", api_key="sk-test")
            models = client.discover_models()

        assert len(models) == 2
        assert models[0].id == "gpt-4"
        assert models[0].owned_by == "openai"
        assert models[0].context_length == 8192
        assert models[1].id == "gpt-3.5-turbo"
        assert models[1].context_length is None

    def test_missing_id_skipped(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "object": "list",
            "data": [
                {"owned_by": "test"},  # no id
                {"id": "valid-model", "owned_by": "test"},
            ],
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response

        with patch("eb.judges.client.httpx.Client", return_value=mock_client):
            client = JudgeClient(base_url="http://test.com/v1", api_key="sk-test")
            models = client.discover_models()

        assert len(models) == 1
        assert models[0].id == "valid-model"

    def test_empty_data_list(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"object": "list", "data": []}
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response

        with patch("eb.judges.client.httpx.Client", return_value=mock_client):
            client = JudgeClient(base_url="http://test.com/v1", api_key="sk-test")
            models = client.discover_models()

        assert models == []

    def test_alternative_format_list(self):
        """Some gateways return models as a bare list."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"id": "model-a", "owned_by": "p"},
        ]
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response

        with patch("eb.judges.client.httpx.Client", return_value=mock_client):
            client = JudgeClient(base_url="http://test.com/v1", api_key="sk-test")
            models = client.discover_models()

        assert len(models) == 1
        assert models[0].id == "model-a"

    def test_unsupported_endpoint(self):
        import httpx
        mock_response = MagicMock()
        mock_response.status_code = 404
        exc = httpx.HTTPStatusError("not found", request=MagicMock(), response=mock_response)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = exc

        with patch("eb.judges.client.httpx.Client", return_value=mock_client):
            client = JudgeClient(base_url="http://test.com/v1", api_key="sk-test")
            with pytest.raises(JudgeClientError):
                client.discover_models()

    def test_malformed_json(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("bad json")
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response

        with patch("eb.judges.client.httpx.Client", return_value=mock_client):
            client = JudgeClient(base_url="http://test.com/v1", api_key="sk-test")
            with pytest.raises(JudgeClientError):
                client.discover_models()

    def test_context_length_from_id_pattern(self):
        """Context length inferred from model ID patterns like '128k'."""
        model = JudgeClient._normalize_model(JudgeClient, {"id": "model-128k"})  # type: ignore
        assert model is not None
        assert model.context_length == 131072

    def test_context_length_from_id_pattern_32k(self):
        model = JudgeClient._normalize_model(JudgeClient, {"id": "model-32k"})  # type: ignore
        assert model is not None
        assert model.context_length == 32768


class TestNormalizeModel:
    def test_basic_normalization(self):
        raw = {"id": "test-model", "owned_by": "provider-x", "context_length": 8192}
        info = JudgeClient._normalize_model(JudgeClient, raw)  # type: ignore
        assert info is not None
        assert info.id == "test-model"
        assert info.owned_by == "provider-x"
        assert info.context_length == 8192
        assert info.modality is None

    def test_vision_inference(self):
        raw = {"id": "gpt-4-vision", "owned_by": "openai"}
        info = JudgeClient._normalize_model(JudgeClient, raw)  # type: ignore
        assert info is not None
        assert info.modality == "vision"

    def test_text_inference(self):
        raw = {"id": "gpt-4-turbo", "owned_by": "openai"}
        info = JudgeClient._normalize_model(JudgeClient, raw)  # type: ignore
        assert info is not None
        assert info.modality == "text"

    def test_no_id_returns_none(self):
        info = JudgeClient._normalize_model(JudgeClient, {"owned_by": "test"})  # type: ignore
        assert info is None
