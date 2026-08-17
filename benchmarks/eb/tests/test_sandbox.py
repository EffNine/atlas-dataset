"""Tests for eb/sandbox/base.py — Sandbox interface and data types."""
import pytest

from eb.sandbox.base import ExecResult, FileChange, SandboxMetadata


class TestExecResult:
    def test_success_when_exit_code_zero_and_no_error(self):
        r = ExecResult(command=["echo", "hi"], exit_code=0)
        assert r.success is True

    def test_failure_when_exit_code_nonzero(self):
        r = ExecResult(command=["false"], exit_code=1)
        assert r.success is False

    def test_failure_when_error_set(self):
        r = ExecResult(command=["echo", "hi"], exit_code=0, error="boom")
        assert r.success is False

    def test_truncation_flags(self):
        r = ExecResult(
            command=["long-cmd"],
            exit_code=0,
            stdout="x" * 1000,
            stderr="y" * 500,
            stdout_truncated=True,
            stderr_truncated=True,
        )
        assert r.stdout_truncated is True
        assert r.stderr_truncated is True


class TestFileChange:
    def test_defaults(self):
        fc = FileChange(path="src/main.py", operation="modified")
        assert fc.path == "src/main.py"
        assert fc.operation == "modified"
        assert fc.diff == ""
        assert fc.content_hash == ""

    def test_with_diff(self):
        fc = FileChange(
            path="src/main.py",
            operation="modified",
            diff="--- a/src/main.py\n+++ b/src/main.py\n",
            content_hash="abc123",
        )
        assert fc.diff.startswith("---")
        assert fc.content_hash == "abc123"


class TestSandboxMetadata:
    def test_defaults(self):
        m = SandboxMetadata(sandbox_id="s1", image="python:3.11-slim", image_tag="3.11-slim")
        assert m.sandbox_id == "s1"
        assert m.image == "python:3.11-slim"
        assert m.image_digest is None
        assert m.docker_version is None
        assert "T" in m.created_at  # ISO format

    def test_with_full_fields(self):
        m = SandboxMetadata(
            sandbox_id="s2",
            image="python:3.11-slim",
            image_tag="3.11-slim",
            image_digest="sha256:abc123",
            docker_version="24.0.7",
            workspace_path="/workspace",
            user="ebuser",
            resource_limits={"cpu_limit": 2, "memory_limit": 2147483648},
        )
        assert m.image_digest == "sha256:abc123"
        assert m.docker_version == "24.0.7"
        assert m.resource_limits["cpu_limit"] == 2
