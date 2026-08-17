#!/usr/bin/env python3
"""
base.py — Abstract Sandbox interface for the EffNine Benchmark (EB).

Defines the contract that all sandbox implementations must fulfill.
Sandbox isolation is the primary security boundary for EXEC tasks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class ExecResult:
    """Result of executing a command inside a sandbox."""

    command: list[str]
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_s: float = 0.0
    truncated: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    oom_killed: bool = False
    timed_out: bool = False
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and self.error is None


@dataclass
class FileChange:
    """Record of a file change inside the sandbox workspace."""

    path: str
    operation: str  # "added", "modified", "deleted"
    diff: str = ""
    content_hash: str = ""


@dataclass
class SandboxMetadata:
    """Metadata about a sandbox instance."""

    sandbox_id: str
    image: str
    image_tag: str
    image_digest: str | None = None
    docker_version: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    stopped_at: str | None = None
    workspace_path: str = ""
    user: str = ""
    resource_limits: dict[str, Any] = field(default_factory=dict)


class Sandbox(ABC):
    """
    Abstract base class for sandbox implementations.

    Lifecycle:
        create() → start() → exec/copy_in/copy_out → collect() → stop() → destroy()

    All operations must preserve host isolation.
    """

    @abstractmethod
    async def create(self, image: str, policy: Any) -> str:
        """
        Create a new sandbox instance.

        Returns the sandbox_id for subsequent operations.
        Must not start the container — use start() for that.
        """
        ...

    @abstractmethod
    async def start(self, sandbox_id: str) -> None:
        """Start the sandbox container. Must be called after create()."""
        ...

    @abstractmethod
    async def exec(
        self,
        sandbox_id: str,
        command: list[str],
        timeout_s: float | None = None,
        workdir: str | None = None,
    ) -> ExecResult:
        """
        Execute a command inside the sandbox.

        The command runs as the sandbox-restricted user, not root on the host.
        Output limits are enforced by the security policy.
        """
        ...

    @abstractmethod
    async def copy_in(self, sandbox_id: str, source: Path, dest_path: str) -> None:
        """
        Copy files from the host into the sandbox workspace.

        source: path on the host
        dest_path: path inside the sandbox workspace (relative to workspace root)
        """
        ...

    @abstractmethod
    async def copy_out(self, sandbox_id: str, src_path: str, dest: Path) -> Path:
        """
        Copy files from the sandbox workspace to the host.

        Returns the destination path on the host.
        """
        ...

    @abstractmethod
    async def collect(self, sandbox_id: str) -> dict[str, Any]:
        """
        Collect execution evidence from the sandbox.

        Returns a dict with:
          - git_diff: str | None
          - changed_files: list[str]
          - workspace_snapshot: dict[str, str]  (path → hash)
          - resource_usage: dict  (cpu, memory, pids)
        """
        ...

    @abstractmethod
    async def stop(self, sandbox_id: str) -> None:
        """Stop the sandbox container gracefully."""
        ...

    @abstractmethod
    async def destroy(self, sandbox_id: str) -> None:
        """
        Destroy the sandbox container and all associated resources.

        Must be idempotent — safe to call multiple times.
        Must be called after stop() or in cleanup paths.
        """
        ...

    @abstractmethod
    async def get_metadata(self, sandbox_id: str) -> SandboxMetadata:
        """Return metadata about the sandbox instance."""
        ...

    @abstractmethod
    async def list_containers(self) -> list[dict[str, Any]]:
        """List all sandbox containers managed by this implementation."""
        ...

    @abstractmethod
    async def cleanup_orphans(self) -> int:
        """
        Find and remove any orphaned sandbox containers.

        Returns the number of containers cleaned up.
        """
        ...

    @property
    @abstractmethod
    def implementation(self) -> str:
        """Return the implementation name (e.g. 'docker')."""
        ...
