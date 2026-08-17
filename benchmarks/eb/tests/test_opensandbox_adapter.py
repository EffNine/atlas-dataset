"""Tests for eb/sandbox/opensandbox.py — OpenSandbox backend adapter."""
import asyncio
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestOpenSandboxCapabilities:
    def test_default_capabilities(self):
        from eb.sandbox.opensandbox import OpenSandboxCapabilities
        caps = OpenSandboxCapabilities()
        assert caps.has_network_policy is True
        assert caps.has_cpu_limit is True
        assert caps.has_memory_limit is True
        assert caps.has_pid_limit is False
        assert caps.has_read_only_root is False
        assert caps.has_timeout is True
        assert caps.has_streaming is True
        assert caps.to_dict()["has_network_policy"] is True

    def test_dict_serialization(self):
        from eb.sandbox.opensandbox import OpenSandboxCapabilities
        caps = OpenSandboxCapabilities()
        d = caps.to_dict()
        assert isinstance(d, dict)
        assert "has_network_policy" in d
        assert "has_pid_limit" in d


class TestOpenSandboxErrorHierarchy:
    def test_base_error(self):
        from eb.sandbox.opensandbox import OpenSandboxError
        assert issubclass(OpenSandboxError, RuntimeError)

    def test_auth_error(self):
        from eb.sandbox.opensandbox import OpenSandboxError, OpenSandboxAuthError
        assert issubclass(OpenSandboxAuthError, OpenSandboxError)

    def test_not_found_error(self):
        from eb.sandbox.opensandbox import OpenSandboxError, OpenSandboxNotFoundError
        assert issubclass(OpenSandboxNotFoundError, OpenSandboxError)

    def test_timeout_error(self):
        from eb.sandbox.opensandbox import OpenSandboxError, OpenSandboxTimeoutError
        assert issubclass(OpenSandboxTimeoutError, OpenSandboxError)

    def test_unavailable_error(self):
        from eb.sandbox.opensandbox import OpenSandboxError, OpenSandboxUnavailableError
        assert issubclass(OpenSandboxUnavailableError, OpenSandboxError)


class TestOpenSandboxBackendInit:
    def test_default_urls(self, monkeypatch):
        monkeypatch.delenv("EB_OPENSANDBOX_BASE_URL", raising=False)
        monkeypatch.delenv("EB_OPENSANDBOX_API_KEY", raising=False)
        from eb.sandbox.opensandbox import OpenSandboxBackend
        sb = OpenSandboxBackend()
        assert sb._base_url == "http://localhost:8080"
        assert sb._api_key == ""
        assert sb.implementation == "opensandbox"

    def test_explicit_constructor(self):
        from eb.sandbox.opensandbox import OpenSandboxBackend
        sb = OpenSandboxBackend(base_url="http://test:9090", api_key="test-key")
        assert sb._base_url == "http://test:9090"
        assert sb._api_key == "test-key"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("EB_OPENSANDBOX_BASE_URL", "http://env-host:1234")
        monkeypatch.setenv("EB_OPENSANDBOX_API_KEY", "env-key")
        from eb.sandbox.opensandbox import OpenSandboxBackend
        sb = OpenSandboxBackend()
        assert sb._base_url == "http://env-host:1234"
        assert sb._api_key == "env-key"


class TestOpenSandboxBackendCreate:
    def test_create_returns_sandbox_id(self):
        from eb.sandbox.opensandbox import OpenSandboxBackend
        from eb.sandbox.security import SecurityPolicy

        sb = OpenSandboxBackend()
        policy = SecurityPolicy()

        with patch.object(sb, '_ensure_sdk'):
            sid = asyncio.run(sb.create("python:3.11-slim", policy))
            assert sid.startswith("eb-osb-")
            assert len(sid) == 19  # "eb-osb-" + 12 hex chars

    def test_create_registers_container(self):
        from eb.sandbox.opensandbox import OpenSandboxBackend
        from eb.sandbox.security import SecurityPolicy

        sb = OpenSandboxBackend()
        policy = SecurityPolicy(cpu_limit=4, memory_limit=4294967296)

        with patch.object(sb, '_ensure_sdk'):
            sid = asyncio.run(sb.create("python:3.11-slim", policy))
            assert sid in sb._containers
            assert sb._containers[sid]["image"] == "python:3.11-slim"
            assert sb._containers[sid]["state"] == "created"
            assert sb._containers[sid]["policy"] == policy


class TestOpenSandboxBackendExec:
    def test_unknown_sandbox(self):
        from eb.sandbox.opensandbox import OpenSandboxBackend
        sb = OpenSandboxBackend()
        result = asyncio.run(sb.exec("nonexistent", ["echo", "hi"]))
        assert result.exit_code == -1
        assert "Unknown sandbox" in result.error

    def test_command_rejected_by_policy(self):
        from eb.sandbox.opensandbox import OpenSandboxBackend
        from eb.sandbox.security import SecurityPolicy

        sb = OpenSandboxBackend()
        policy = SecurityPolicy()

        with patch.object(sb, '_ensure_sdk'):
            sid = asyncio.run(sb.create("python:3.11-slim", policy))

        result = asyncio.run(sb.exec(sid, ["docker", "ps"]))
        assert result.exit_code == -1
        assert "security policy" in result.error.lower()

    def test_unstarted_sandbox(self):
        from eb.sandbox.opensandbox import OpenSandboxBackend
        from eb.sandbox.security import SecurityPolicy

        sb = OpenSandboxBackend()
        policy = SecurityPolicy()

        with patch.object(sb, '_ensure_sdk'):
            sid = asyncio.run(sb.create("python:3.11-slim", policy))

        result = asyncio.run(sb.exec(sid, ["echo", "hi"]))
        assert result.exit_code == -1
        assert "not started" in result.error.lower()


class TestOpenSandboxBackendLifecycle:
    def test_stop_unknown_raises(self):
        from eb.sandbox.opensandbox import OpenSandboxBackend
        sb = OpenSandboxBackend()
        with pytest.raises(ValueError, match="Unknown sandbox"):
            asyncio.run(sb.stop("missing"))

    def test_destroy_unknown_is_noop(self):
        from eb.sandbox.opensandbox import OpenSandboxBackend
        sb = OpenSandboxBackend()
        asyncio.run(sb.destroy("missing"))  # Should not raise

    def test_get_metadata_unknown_raises(self):
        from eb.sandbox.opensandbox import OpenSandboxBackend
        sb = OpenSandboxBackend()
        with pytest.raises(ValueError, match="Unknown sandbox"):
            asyncio.run(sb.get_metadata("missing"))


class TestOpenSandboxContext:
    def test_context_manager_calls_stop_and_destroy(self):
        from eb.sandbox.opensandbox import OpenSandboxBackend, OpenSandboxContext
        from eb.sandbox.security import SecurityPolicy

        sb = OpenSandboxBackend()
        policy = SecurityPolicy()

        with patch.object(sb, '_ensure_sdk'):
            sid = asyncio.run(sb.create("python:3.11-slim", policy))

        ctx = OpenSandboxContext(sb, sid, policy)
        assert ctx._sandbox_id == sid
        assert ctx._policy == policy

    def test_context_manager_exit_calls_cleanup(self):
        from eb.sandbox.opensandbox import OpenSandboxBackend, OpenSandboxContext
        from eb.sandbox.security import SecurityPolicy

        sb = OpenSandboxBackend()
        policy = SecurityPolicy()

        with patch.object(sb, '_ensure_sdk'):
            sid = asyncio.run(sb.create("python:3.11-slim", policy))

        ctx = OpenSandboxContext(sb, sid, policy)
        asyncio.run(ctx.__aexit__(None, None, None))
        # destroy() pops the container, so it should no longer be in _containers
        assert sid not in sb._containers


class TestOpenSandboxSDKImport:
    def test_missing_sdk_raises_runtime_error(self):
        from eb.sandbox.opensandbox import OpenSandboxBackend
        sb = OpenSandboxBackend()
        sb._imported = False  # Force re-import attempt
        with patch.dict('sys.modules', {'opensandbox': None, 'opensandbox.sandbox': None}):
            with pytest.raises(RuntimeError, match="OpenSandbox SDK not available"):
                sb._ensure_sdk()


class TestErrorMapping:
    def test_auth_error_mapping(self):
        from eb.sandbox.opensandbox import OpenSandboxAuthError
        assert issubclass(OpenSandboxAuthError, Exception)

    def test_not_found_error_mapping(self):
        from eb.sandbox.opensandbox import OpenSandboxNotFoundError
        assert issubclass(OpenSandboxNotFoundError, Exception)

    def test_timeout_error_mapping(self):
        from eb.sandbox.opensandbox import OpenSandboxTimeoutError
        assert issubclass(OpenSandboxTimeoutError, Exception)

    def test_unavailable_error_mapping(self):
        from eb.sandbox.opensandbox import OpenSandboxUnavailableError
        assert issubclass(OpenSandboxUnavailableError, Exception)


class TestSecretRedaction:
    def test_api_key_not_in_sandbox_id(self):
        """Sandbox IDs must never contain API keys."""
        from eb.sandbox.opensandbox import OpenSandboxBackend
        from eb.sandbox.security import SecurityPolicy

        sb = OpenSandboxBackend(api_key="sk-secret-key-12345")
        policy = SecurityPolicy()

        with patch.object(sb, '_ensure_sdk'):
            sid = asyncio.run(sb.create("python:3.11-slim", policy))

        assert "sk-secret" not in sid
        assert "12345" not in sid
        assert sid.startswith("eb-osb-")

    def test_base_url_not_in_sandbox_id(self):
        from eb.sandbox.opensandbox import OpenSandboxBackend
        from eb.sandbox.security import SecurityPolicy

        sb = OpenSandboxBackend(base_url="http://secret-host:8080")
        policy = SecurityPolicy()

        with patch.object(sb, '_ensure_sdk'):
            sid = asyncio.run(sb.create("python:3.11-slim", policy))

        assert "secret-host" not in sid
        assert "8080" not in sid
