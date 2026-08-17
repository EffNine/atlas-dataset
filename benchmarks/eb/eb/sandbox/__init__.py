"""EffNine Benchmark sandbox — Multi-backend container management."""

from .base import ExecResult, FileChange, Sandbox, SandboxMetadata
from .docker import DockerSandbox, SandboxContext
from .manager import ActiveSandbox, SandboxExecution, SandboxManager
from .security import (
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
from .opensandbox import (
    OpenSandboxBackend,
    OpenSandboxContext,
    OpenSandboxCapabilities,
    OpenSandboxError,
    OpenSandboxAuthError,
    OpenSandboxNotFoundError,
    OpenSandboxTimeoutError,
    OpenSandboxUnavailableError,
)

__all__ = [
    # Base types
    "ExecResult",
    "FileChange",
    "Sandbox",
    "SandboxMetadata",
    "SecurityPolicy",
    # Docker
    "DockerSandbox",
    "SandboxContext",
    # OpenSandbox
    "OpenSandboxBackend",
    "OpenSandboxContext",
    "OpenSandboxCapabilities",
    "OpenSandboxError",
    "OpenSandboxAuthError",
    "OpenSandboxNotFoundError",
    "OpenSandboxTimeoutError",
    "OpenSandboxUnavailableError",
    # Manager
    "ActiveSandbox",
    "SandboxExecution",
    "SandboxManager",
    # Security constants
    "DEFAULT_ALLOW_PRIVILEGED",
    "DEFAULT_CPU_LIMIT",
    "DEFAULT_MEMORY_LIMIT",
    "DEFAULT_MAX_COMMAND_TIME_S",
    "DEFAULT_MAX_STDOUT_BYTES",
    "DEFAULT_MAX_TOOL_CALLS",
    "DEFAULT_MAX_TOTAL_TIME_S",
    "DEFAULT_NETWORK_ENABLED",
    "DEFAULT_PIDS_LIMIT",
    "DEFAULT_READ_ONLY_ROOT",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_USER",
    "DEFAULT_WORKSPACE_PATH",
    "DANGEROUS_COMMANDS",
    "DANGEROUS_PATHS",
    "is_command_dangerous",
    "is_path_safe",
    "validate_command_for_sandbox",
]
