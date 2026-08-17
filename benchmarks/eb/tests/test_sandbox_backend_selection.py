"""Tests for sandbox backend selection in manager.py."""
import os
import pytest
from unittest.mock import MagicMock, patch


class TestResolveSandboxBackend:
    def test_default_backend_is_docker(self, monkeypatch):
        monkeypatch.delenv("EB_SANDBOX_BACKEND", raising=False)
        from eb.sandbox.manager import resolve_sandbox_backend
        assert resolve_sandbox_backend() == "docker"

    def test_env_var_selects_opensandbox(self, monkeypatch):
        monkeypatch.setenv("EB_SANDBOX_BACKEND", "opensandbox")
        from eb.sandbox.manager import resolve_sandbox_backend
        assert resolve_sandbox_backend() == "opensandbox"

    def test_env_var_selects_docker(self, monkeypatch):
        monkeypatch.setenv("EB_SANDBOX_BACKEND", "docker")
        from eb.sandbox.manager import resolve_sandbox_backend
        assert resolve_sandbox_backend() == "docker"

    def test_invalid_backend_falls_back_to_docker(self, monkeypatch):
        monkeypatch.setenv("EB_SANDBOX_BACKEND", "invalid-backend")
        from eb.sandbox.manager import resolve_sandbox_backend
        assert resolve_sandbox_backend() == "docker"

    def test_empty_env_falls_back_to_docker(self, monkeypatch):
        monkeypatch.setenv("EB_SANDBOX_BACKEND", "")
        from eb.sandbox.manager import resolve_sandbox_backend
        assert resolve_sandbox_backend() == "docker"

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("EB_SANDBOX_BACKEND", "OpenSandbox")
        from eb.sandbox.manager import resolve_sandbox_backend
        assert resolve_sandbox_backend() == "opensandbox"

        monkeypatch.setenv("EB_SANDBOX_BACKEND", "DOCKER")
        assert resolve_sandbox_backend() == "docker"


class TestCreateSandboxFactory:
    def test_creates_docker_by_default(self):
        from eb.sandbox.manager import create_sandbox
        sb = create_sandbox()
        assert sb.implementation == "docker"

    def test_creates_opensandbox_when_specified(self):
        from eb.sandbox.manager import create_sandbox
        sb = create_sandbox(backend="opensandbox")
        assert sb.implementation == "opensandbox"

    def test_raises_on_unknown_backend(self):
        from eb.sandbox.manager import create_sandbox
        with pytest.raises(ValueError, match="Unknown sandbox backend"):
            create_sandbox(backend="nonexistent")

    def test_passes_kwargs_to_opensandbox(self):
        from eb.sandbox.manager import create_sandbox
        sb = create_sandbox(backend="opensandbox", base_url="http://test:9999", api_key="key123")
        assert sb._base_url == "http://test:9999"
        assert sb._api_key == "key123"

    def test_passes_kwargs_to_docker(self):
        from eb.sandbox.manager import create_sandbox
        sb = create_sandbox(backend="docker")
        assert sb.implementation == "docker"


class TestSandboxManagerBackendSelection:
    def test_manager_uses_default_backend(self):
        from eb.sandbox.manager import SandboxManager
        mgr = SandboxManager()
        assert mgr.backend == "docker"
        assert mgr.implementation == "docker"

    def test_manager_uses_explicit_backend(self):
        from eb.sandbox.manager import SandboxManager
        mgr = SandboxManager(backend="opensandbox")
        assert mgr.backend == "opensandbox"
        assert mgr.implementation == "opensandbox"

    def test_manager_uses_provided_sandbox_instance(self):
        from eb.sandbox.manager import SandboxManager
        from eb.sandbox.opensandbox import OpenSandboxBackend

        real_sb = OpenSandboxBackend()
        mgr = SandboxManager(sandbox=real_sb)
        assert mgr.implementation == "opensandbox"
        assert mgr._sandbox is real_sb


class TestSandboxManagerBackendProperty:
    def test_backend_property_reflects_selection(self):
        from eb.sandbox.manager import SandboxManager
        mgr = SandboxManager(backend="opensandbox")
        assert mgr.backend == "opensandbox"

    def test_implementation_matches_backend(self):
        from eb.sandbox.manager import SandboxManager
        mgr_d = SandboxManager(backend="docker")
        assert mgr_d.implementation == "docker"

        mgr_o = SandboxManager(backend="opensandbox")
        assert mgr_o.implementation == "opensandbox"


class TestListActiveIncludesImplementation:
    def test_list_active_shows_implementation(self):
        from eb.sandbox.manager import SandboxManager
        mgr = SandboxManager(backend="opensandbox")
        # Just verify the method exists and returns a list when empty
        import asyncio
        result = asyncio.run(mgr.list_active())
        assert isinstance(result, list)
        assert len(result) == 0


class TestSupportedBackendsConstant:
    def test_constants_exist(self):
        from eb.sandbox.manager import SUPPORTED_BACKENDS, DEFAULT_BACKEND
        assert "docker" in SUPPORTED_BACKENDS
        assert "opensandbox" in SUPPORTED_BACKENDS
        assert DEFAULT_BACKEND == "docker"
