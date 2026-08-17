#!/usr/bin/env python3
"""
security.py — Typed security policy for the EffNine Benchmark (EB) sandbox.

Enforces least-privilege defaults:
  - No network by default
  - No privileged containers
  - No host filesystem mounts
  - No Docker socket exposure
  - Non-root user
  - Finite CPU, memory, PID, and timeout limits
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Safe defaults
# ---------------------------------------------------------------------------

DEFAULT_NETWORK_ENABLED = False
DEFAULT_ALLOW_PRIVILEGED = False
DEFAULT_READ_ONLY_ROOT = True
DEFAULT_USER = "ebuser"
DEFAULT_WORKSPACE_PATH = "/workspace"
DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_STDOUT_BYTES = 65536
DEFAULT_MAX_STDERR_BYTES = 32768
DEFAULT_MAX_TOOL_CALLS = 50
DEFAULT_MAX_TOTAL_TIME_S = 600.0
DEFAULT_MAX_COMMAND_TIME_S = 60.0
DEFAULT_CPU_LIMIT = 2
DEFAULT_MEMORY_LIMIT = 2147483648  # 2 GiB
DEFAULT_PIDS_LIMIT = 256


# ---------------------------------------------------------------------------
# Security policy dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SecurityPolicy:
    """
    Immutable, typed security policy for sandbox operations.

    All fields have safe-by-default values. To relax a restriction,
    set the corresponding field explicitly.
    """

    network_enabled: bool = DEFAULT_NETWORK_ENABLED
    cpu_limit: int | None = DEFAULT_CPU_LIMIT
    memory_limit: int | None = DEFAULT_MEMORY_LIMIT
    pids_limit: int | None = DEFAULT_PIDS_LIMIT
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    read_only_root: bool = DEFAULT_READ_ONLY_ROOT
    workspace_path: str = DEFAULT_WORKSPACE_PATH
    user: str = DEFAULT_USER
    allow_privileged: bool = DEFAULT_ALLOW_PRIVILEGED
    allowed_env: list[str] = field(default_factory=lambda: ["PATH", "HOME", "LANG", "PYTHONPATH"])
    writable_paths: list[str] = field(
        default_factory=lambda: ["/workspace", "/tmp"]
    )
    max_stdout_bytes: int = DEFAULT_MAX_STDOUT_BYTES
    max_stderr_bytes: int = DEFAULT_MAX_STDERR_BYTES
    max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS
    max_total_time_s: float = DEFAULT_MAX_TOTAL_TIME_S
    max_command_time_s: float = DEFAULT_MAX_COMMAND_TIME_S
    policy_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        """Serialize policy to a dict for artifact recording."""
        return {
            "network_enabled": self.network_enabled,
            "cpu_limit": self.cpu_limit,
            "memory_limit": self.memory_limit,
            "pids_limit": self.pids_limit,
            "timeout_seconds": self.timeout_seconds,
            "read_only_root": self.read_only_root,
            "workspace_path": self.workspace_path,
            "user": self.user,
            "allow_privileged": self.allow_privileged,
            "allowed_env": self.allowed_env,
            "writable_paths": self.writable_paths,
            "max_stdout_bytes": self.max_stdout_bytes,
            "max_stderr_bytes": self.max_stderr_bytes,
            "max_tool_calls": self.max_tool_calls,
            "max_total_time_s": self.max_total_time_s,
            "max_command_time_s": self.max_command_time_s,
            "policy_version": self.policy_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SecurityPolicy":
        """Create a SecurityPolicy from a dict (e.g. loaded from artifact)."""
        return cls(
            network_enabled=data.get("network_enabled", DEFAULT_NETWORK_ENABLED),
            cpu_limit=data.get("cpu_limit", DEFAULT_CPU_LIMIT),
            memory_limit=data.get("memory_limit", DEFAULT_MEMORY_LIMIT),
            pids_limit=data.get("pids_limit", DEFAULT_PIDS_LIMIT),
            timeout_seconds=data.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
            read_only_root=data.get("read_only_root", DEFAULT_READ_ONLY_ROOT),
            workspace_path=data.get("workspace_path", DEFAULT_WORKSPACE_PATH),
            user=data.get("user", DEFAULT_USER),
            allow_privileged=data.get("allow_privileged", DEFAULT_ALLOW_PRIVILEGED),
            allowed_env=data.get("allowed_env", DEFAULT_ALLOWED_ENV),
            writable_paths=data.get("writable_paths", DEFAULT_WRITABLE_PATHS),
            max_stdout_bytes=data.get("max_stdout_bytes", DEFAULT_MAX_STDOUT_BYTES),
            max_stderr_bytes=data.get("max_stderr_bytes", DEFAULT_MAX_STDERR_BYTES),
            max_tool_calls=data.get("max_tool_calls", DEFAULT_MAX_TOOL_CALLS),
            max_total_time_s=data.get("max_total_time_s", DEFAULT_MAX_TOTAL_TIME_S),
            max_command_time_s=data.get("max_command_time_s", DEFAULT_MAX_COMMAND_TIME_S),
            policy_version=data.get("policy_version", "1.0"),
        )

    # Backwards compat aliases for from_dict
    _env_compat = {
        "allowed_env": "allowed_env",
        "writable_paths": "writable_paths",
    }


DEFAULT_ALLOWED_ENV = ["PATH", "HOME", "LANG", "PYTHONPATH"]
DEFAULT_WRITABLE_PATHS = ["/workspace", "/tmp"]


# ---------------------------------------------------------------------------
# Command validation policy
# ---------------------------------------------------------------------------

DANGEROUS_COMMANDS: frozenset[str] = frozenset([
    "docker",
    "nsenter",
    "mount",
    "umount",
    "mknod",
    "insmod",
    "rmmod",
    "modprobe",
    "chroot",
    "pivot_root",
    "dd",
    " FORMAT=",
    "mkfs",
    "fdisk",
])

DANGEROUS_PATHS: frozenset[str] = frozenset([
    "/var/run/docker.sock",
    "/etc/shadow",
    "/etc/passwd",
    "/proc/",
    "/sys/",
    "/dev/",
])


def is_command_dangerous(command: list[str]) -> bool:
    """
    Check if a command is dangerous based on command-name heuristics.

    This is a SECONDARY defense-in-depth layer. Primary security comes from
    container isolation. Do NOT rely on this as the sole safety mechanism.

    Only checks the command name (first element), not arguments.
    """
    if not command:
        return False
    cmd_name = command[0].split("/")[-1] if command[0] else ""
    if cmd_name in DANGEROUS_COMMANDS:
        return True
    return False


def is_path_safe(path: str, workspace_root: str) -> bool:
    """
    Validate that a path stays within the workspace root.

    Rejects path traversal attempts (../) and absolute host paths.
    """
    import os

    if not workspace_root:
        return True

    resolved = os.path.realpath(os.path.join(workspace_root, path))
    return resolved.startswith(os.path.realpath(workspace_root))


def validate_command_for_sandbox(
    command: list[str],
    policy: SecurityPolicy,
    workspace_root: str,
) -> tuple[bool, str]:
    """
    Validate a command against the security policy.

    Returns (is_safe, reason).
    """
    if is_command_dangerous(command):
        return False, f"dangerous_command: {command[0]}"

    cmd_str = " ".join(command)
    for dangerous_path in DANGEROUS_PATHS:
        if dangerous_path in cmd_str:
            return False, f"dangerous_path_reference: {dangerous_path}"

    if not policy.allow_privileged and "--privileged" in cmd_str:
        return False, "privileged_flag_rejected"

    if not policy.network_enabled and any(
        flag in cmd_str for flag in ("--network", "-n", "curl ", "wget ", "pip install", "apt ", "npm install")
    ):
        if "localhost" not in cmd_str and "127.0.0.1" not in cmd_str:
            return False, "network_operation_blocked"

    return True, ""
