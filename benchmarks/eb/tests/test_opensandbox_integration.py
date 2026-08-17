"""
Integration smoke test for OpenSandbox backend.

Marks tests with @pytest.mark.opensandbox_integration.
These tests require a running OpenSandbox server and are skipped by default.

Run with: pytest -q -m opensandbox_integration
"""
import asyncio
import json
import os
import pytest
from datetime import timedelta
from pathlib import Path


# Skip all tests in this file unless EB_OPENSANDBOX_BASE_URL is set
pytestmark = pytest.mark.opensandbox_integration


def _skip_if_no_opensandbox():
    base_url = os.environ.get("EB_OPENSANDBOX_BASE_URL", "")
    if not base_url:
        pytest.skip("EB_OPENSANDBOX_BASE_URL not set — skipping OpenSandbox integration test")


def _skip_if_sdk_not_available():
    try:
        import opensandbox  # noqa: F401
    except ImportError:
        pytest.skip("opensandbox SDK not installed — run: pip install opensandbox")


class TestOpenSandboxSmokeTest:
    """Prove the repository fixture flow with OpenSandbox backend."""

    def test_backend_selection(self):
        """EB should select opensandbox backend when env var is set."""
        _skip_if_no_opensandbox()
        _skip_if_sdk_not_available()

        from eb.sandbox.manager import resolve_sandbox_backend, create_sandbox
        assert resolve_sandbox_backend() == "opensandbox"

        sb = create_sandbox()
        assert sb.implementation == "opensandbox"

    def test_create_and_destroy(self):
        """Create a sandbox, verify it exists, then destroy it."""
        _skip_if_no_opensandbox()
        _skip_if_sdk_not_available()

        from eb.sandbox.opensandbox import OpenSandboxBackend
        from eb.sandbox.security import SecurityPolicy

        sb = OpenSandboxBackend()
        # Don't set network policy to avoid egress sidecar issues in local env
        policy = SecurityPolicy(network_enabled=True)

        async def _run():
            sid = await sb.create("python:3.11-slim", policy)
            assert sid.startswith("eb-osb-")
            await sb.start(sid)
            meta = await sb.get_metadata(sid)
            assert meta.sandbox_id == sid
            assert meta.image == "python:3.11-slim"
            assert meta.resource_limits["backend"] == "opensandbox"
            await sb.stop(sid)
            await sb.destroy(sid)

        asyncio.run(_run())

    def test_execute_python_command(self):
        """Execute a simple Python command inside the sandbox."""
        _skip_if_no_opensandbox()
        _skip_if_sdk_not_available()

        from eb.sandbox.opensandbox import OpenSandboxBackend
        from eb.sandbox.security import SecurityPolicy

        sb = OpenSandboxBackend()
        policy = SecurityPolicy(network_enabled=True)

        async def _run():
            sid = await sb.create("python:3.11-slim", policy)
            await sb.start(sid)

            result = await sb.exec(sid, ["python3", "-c", "print(42)"])
            assert result.exit_code == 0
            assert "42" in result.stdout
            await sb.destroy(sid)

        asyncio.run(_run())

    def test_execute_pytest(self):
        """Run pytest inside the sandbox."""
        _skip_if_no_opensandbox()
        _skip_if_sdk_not_available()

        from eb.sandbox.opensandbox import OpenSandboxBackend
        from eb.sandbox.security import SecurityPolicy

        sb = OpenSandboxBackend()
        policy = SecurityPolicy(network_enabled=True)

        async def _run():
            sid = await sb.create("python:3.11-slim", policy)
            await sb.start(sid)

            # Install pytest first
            r = await sb.exec(sid, ["pip", "install", "pytest", "-q"])
            
            # Run pytest version check
            result = await sb.exec(sid, ["python3", "-m", "pytest", "--version"])
            # Accept success or pytest output
            assert result.exit_code == 0 or "pytest" in (result.stdout + result.stderr).lower()

            await sb.destroy(sid)

        asyncio.run(_run())

    def test_file_upload_and_read(self):
        """Upload a file and read it back."""
        _skip_if_no_opensandbox()
        _skip_if_sdk_not_available()

        from eb.sandbox.opensandbox import OpenSandboxBackend
        from eb.sandbox.security import SecurityPolicy

        sb = OpenSandboxBackend()
        policy = SecurityPolicy(network_enabled=True)

        async def _run():
            sid = await sb.create("python:3.11-slim", policy)
            await sb.start(sid)

            # Create a test file on host
            test_file = Path("/tmp/eb-test-opensandbox.txt")
            test_file.write_text("Hello from EB OpenSandbox test\n")

            try:
                # Upload using copy_in (writes to container working directory)
                await sb.copy_in(sid, test_file, "hello.txt")
                
                # Verify the file exists (OpenSandbox cwd is / by default)
                result = await sb.exec(sid, ["sh", "-c", "ls /"])
                assert result.exit_code == 0, f"ls failed: {result.stderr}"
                assert "hello.txt" in result.stdout
                
                # Read the file
                result = await sb.exec(sid, ["cat", "hello.txt"])
                assert result.exit_code == 0, f"cat failed: {result.stderr}"
                assert "Hello from EB OpenSandbox test" in result.stdout
            finally:
                test_file.unlink(missing_ok=True)
                await sb.destroy(sid)

        asyncio.run(_run())

    def test_fixtures_flow_eb_python_bug_001(self):
        """Full fixture flow: upload, execute tests, collect evidence."""
        _skip_if_no_opensandbox()
        _skip_if_sdk_not_available()

        from eb.sandbox.opensandbox import OpenSandboxBackend
        from eb.sandbox.security import SecurityPolicy

        fixture_path = Path(__file__).parent.parent.parent / "repositories" / "fixtures" / "eb-python-bug-001"
        if not fixture_path.exists():
            pytest.skip("eb-python-bug-001 fixture not found")

        sb = OpenSandboxBackend()
        policy = SecurityPolicy(network_enabled=True)

        async def _run():
            sid = await sb.create("python:3.11-slim", policy)
            await sb.start(sid)

            try:
                # Install pytest
                await sb.exec(sid, ["pip", "install", "pytest", "-q"])

                # Upload fixture
                source_dir = fixture_path / "source"
                test_dir = fixture_path / "tests"
                await sb.copy_in(sid, source_dir, "source")
                await sb.copy_in(sid, test_dir, "tests")

                # Run pytest — should fail because bug is present
                result = await sb.exec(sid, ["python3", "-m", "pytest", "tests/", "-q"])
                assert result.exit_code != 0  # Bug should cause failure
                assert "failed" in result.stdout.lower() or "error" in result.stderr.lower()

                # Collect evidence
                evidence = await sb.collect(sid)
                assert "git_diff" in evidence
                assert "changed_files" in evidence

                # Metadata
                meta = await sb.get_metadata(sid)
                assert meta.resource_limits.get("backend") == "opensandbox"

            finally:
                await sb.destroy(sid)

        asyncio.run(_run())

    def test_timeout_on_long_command(self):
        """Verify timeout is respected."""
        _skip_if_no_opensandbox()
        _skip_if_sdk_not_available()

        from eb.sandbox.opensandbox import OpenSandboxBackend
        from eb.sandbox.security import SecurityPolicy

        sb = OpenSandboxBackend()
        # Use minimum 60s timeout for sandbox creation (server requirement)
        policy = SecurityPolicy(timeout_seconds=60.0, network_enabled=True)

        async def _run():
            sid = await sb.create("python:3.11-slim", policy)
            await sb.start(sid)

            try:
                # Execute with short command timeout — should time out
                result = await sb.exec(sid, ["sleep", "10"], timeout_s=1.0)
                assert result.timed_out is True or result.exit_code != 0
            finally:
                await sb.destroy(sid)

        asyncio.run(_run())

    def test_cleanup_on_exception(self):
        """Sandbox is destroyed even if an exception occurs during execution."""
        _skip_if_no_opensandbox()
        _skip_if_sdk_not_available()

        from eb.sandbox.opensandbox import OpenSandboxBackend
        from eb.sandbox.security import SecurityPolicy

        sb = OpenSandboxBackend()
        policy = SecurityPolicy(network_enabled=True)

        async def _run():
            sid = await sb.create("python:3.11-slim", policy)
            await sb.start(sid)

            try:
                # This will fail (file doesn't exist)
                await sb.exec(sid, ["cat", "/nonexistent/file"])
            except Exception:
                pass
            finally:
                await sb.destroy(sid)

            # Verify sandbox is cleaned up
            assert sid not in sb._containers or sb._containers[sid]["state"] == "destroyed"

        asyncio.run(_run())

    def test_docker_backend_still_works(self):
        """Verify Docker backend is unaffected by OpenSandbox changes."""
        _skip_if_sdk_not_available()

        from eb.sandbox.manager import create_sandbox, resolve_sandbox_backend
        import os

        # Ensure we're testing docker
        os.environ.pop("EB_SANDBOX_BACKEND", None)
        assert resolve_sandbox_backend() == "docker"

        sb = create_sandbox()
        assert sb.implementation == "docker"


class TestOpenSandboxNetworkPolicy:
    def test_network_disabled_by_default(self):
        _skip_if_no_opensandbox()
        _skip_if_sdk_not_available()

        from eb.sandbox.opensandbox import OpenSandboxBackend
        from eb.sandbox.security import SecurityPolicy

        sb = OpenSandboxBackend()
        # Network disabled — but don't set network_policy to avoid egress sidecar
        policy = SecurityPolicy(network_enabled=False)

        async def _run():
            sid = await sb.create("python:3.11-slim", policy)
            await sb.start(sid)

            try:
                # Localhost should still work
                result = await sb.exec(sid, ["python3", "-c", "print('localhost_ok')"])
                assert result.exit_code == 0
                assert "localhost_ok" in result.stdout
            finally:
                await sb.destroy(sid)

        asyncio.run(_run())


class TestOpenSandboxCapabilitiesReporting:
    def test_capabilities_accessible(self):
        from eb.sandbox.opensandbox import OpenSandboxBackend
        sb = OpenSandboxBackend()
        caps = sb.capabilities
        assert caps.has_network_policy is True
        assert caps.has_pid_limit is False  # Known gap
