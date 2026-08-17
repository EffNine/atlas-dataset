"""Tests for eb/sandbox/security.py — Security policy and command validation."""
import pytest

from eb.sandbox.security import (
    DEFAULT_ALLOW_PRIVILEGED,
    DEFAULT_CPU_LIMIT,
    DEFAULT_MEMORY_LIMIT,
    DEFAULT_MAX_COMMAND_TIME_S,
    DEFAULT_MAX_STDOUT_BYTES,
    DEFAULT_MAX_TOOL_CALLS,
    DEFAULT_MAX_TOTAL_TIME_S,
    DEFAULT_NETWORK_ENABLED,
    DEFAULT_PIDS_LIMIT,
    DEFAULT_READ_ONLY_ROOT,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_USER,
    DEFAULT_WORKSPACE_PATH,
    DANGEROUS_COMMANDS,
    DANGEROUS_PATHS,
    SecurityPolicy,
    is_command_dangerous,
    is_path_safe,
    validate_command_for_sandbox,
)


class TestSecurityPolicyDefaults:
    def test_network_disabled_by_default(self):
        p = SecurityPolicy()
        assert p.network_enabled is False
        assert p.allow_privileged is False
        assert p.read_only_root is True
        assert p.user == DEFAULT_USER
        assert p.workspace_path == DEFAULT_WORKSPACE_PATH
        assert p.cpu_limit == DEFAULT_CPU_LIMIT
        assert p.memory_limit == DEFAULT_MEMORY_LIMIT
        assert p.pids_limit == DEFAULT_PIDS_LIMIT
        assert p.timeout_seconds == DEFAULT_TIMEOUT_SECONDS

    def test_to_dict_roundtrip(self):
        p = SecurityPolicy(network_enabled=True, cpu_limit=4, memory_limit=4294967296)
        d = p.to_dict()
        assert d["network_enabled"] is True
        assert d["cpu_limit"] == 4
        assert d["memory_limit"] == 4294967296

        p2 = SecurityPolicy.from_dict(d)
        assert p2.network_enabled is True
        assert p2.cpu_limit == 4
        assert p2.memory_limit == 4294967296

    def test_custom_policy(self):
        p = SecurityPolicy(
            network_enabled=True,
            cpu_limit=8,
            memory_limit=8589934592,
            pids_limit=512,
            timeout_seconds=600.0,
            allow_privileged=False,
            max_tool_calls=100,
            max_total_time_s=900.0,
            max_command_time_s=120.0,
        )
        assert p.network_enabled is True
        assert p.max_tool_calls == 100
        assert p.max_total_time_s == 900.0


class TestIsCommandDangerous:
    def test_dangerous_commands(self):
        assert is_command_dangerous(["docker", "ps"]) is True
        assert is_command_dangerous(["nsenter", "--target", "1"]) is True
        assert is_command_dangerous(["mount", "/dev/sda1", "/mnt"]) is True
        assert is_command_dangerous(["rm", "-rf", "/"]) is False  # rm is not in the list

    def test_safe_commands(self):
        assert is_command_dangerous(["python", "script.py"]) is False
        assert is_command_dangerous(["pytest", "-q"]) is False
        assert is_command_dangerous(["git", "diff"]) is False
        assert is_command_dangerous([]) is False

    def test_command_in_string(self):
        assert is_command_dangerous(["sh", "-c", "docker ps"]) is False  # sh is the command name
        assert is_command_dangerous(["echo", "docker is bad"]) is False  # echo is safe
        assert is_command_dangerous(["docker", "ps"]) is True


class TestIsPathSafe:
    def test_relative_path_within_workspace(self):
        assert is_path_safe("src/parser.py", "/workspace") is True
        assert is_path_safe("tests/test_parser.py", "/workspace") is True

    def test_path_traversal_rejected(self):
        assert is_path_safe("../etc/passwd", "/workspace") is False
        assert is_path_safe("../../../../etc/shadow", "/workspace") is False
        assert is_path_safe("src/../../../etc/passwd", "/workspace") is False

    def test_absolute_host_path_rejected(self):
        assert is_path_safe("/etc/passwd", "/workspace") is False
        assert is_path_safe("/var/run/docker.sock", "/workspace") is False


class TestValidateCommandForSandbox:
    def test_safe_command_passes(self):
        policy = SecurityPolicy()
        safe, reason = validate_command_for_sandbox(["pytest", "-q"], policy, "/workspace")
        assert safe is True
        assert reason == ""

    def test_docker_command_rejected(self):
        policy = SecurityPolicy()
        safe, reason = validate_command_for_sandbox(["docker", "ps"], policy, "/workspace")
        assert safe is False
        assert "dangerous_command" in reason

    def test_docker_socket_reference_rejected(self):
        policy = SecurityPolicy()
        safe, reason = validate_command_for_sandbox(["cat", "/var/run/docker.sock"], policy, "/workspace")
        assert safe is False
        assert "dangerous_path" in reason

    def test_network_operation_blocked_when_disabled(self):
        policy = SecurityPolicy(network_enabled=False)
        safe, reason = validate_command_for_sandbox(["curl", "https://example.com"], policy, "/workspace")
        assert safe is False
        assert "network" in reason

    def test_network_allowed_when_enabled(self):
        policy = SecurityPolicy(network_enabled=True)
        safe, reason = validate_command_for_sandbox(["curl", "https://example.com"], policy, "/workspace")
        assert safe is True

    def test_privileged_flag_rejected(self):
        policy = SecurityPolicy(allow_privileged=False)
        safe, reason = validate_command_for_sandbox(["ls", "-la", "--privileged"], policy, "/workspace")
        assert safe is False
        assert "privileged" in reason

    def test_localhost_network_allowed_even_when_disabled(self):
        policy = SecurityPolicy(network_enabled=False)
        safe, reason = validate_command_for_sandbox(["curl", "http://127.0.0.1:8080"], policy, "/workspace")
        assert safe is True


class TestDockerSocketProtection:
    def test_docker_sock_in_dangerous_paths(self):
        assert "/var/run/docker.sock" in DANGEROUS_PATHS

    def test_no_host_root_mount_by_policy(self):
        policy = SecurityPolicy()
        assert policy.read_only_root is True
        assert "/host" not in policy.writable_paths
