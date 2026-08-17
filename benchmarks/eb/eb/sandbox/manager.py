#!/usr/bin/env python3
"""
manager.py — Sandbox lifecycle manager for the EffNine Benchmark (EB).

Manages the pool of active sandbox instances, enforces cleanup guarantees,
and provides a high-level API for EXEC task execution.

Supports multiple sandbox backends via EB_SANDBOX_BACKEND env var:
  - "docker" (default)
  - "opensandbox"
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import ExecResult, Sandbox, SandboxMetadata
from .docker import DockerSandbox
from .opensandbox import OpenSandboxBackend
from .security import (
    SecurityPolicy,
    DEFAULT_NETWORK_ENABLED,
    DEFAULT_CPU_LIMIT,
    DEFAULT_MEMORY_LIMIT,
)


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

SUPPORTED_BACKENDS = ("docker", "opensandbox")
DEFAULT_BACKEND = "docker"


def resolve_sandbox_backend() -> str:
    """
    Resolve the sandbox backend from environment or config.

    Priority:
      1. EB_SANDBOX_BACKEND env var
      2. sandbox.backend in config/ (if present)
      3. Default: "docker"
    """
    backend = os.environ.get("EB_SANDBOX_BACKEND", "").strip().lower()
    if backend and backend in SUPPORTED_BACKENDS:
        return backend
    return DEFAULT_BACKEND


def create_sandbox(backend: str | None = None, **kwargs: Any) -> Sandbox:
    """
    Factory function to create a Sandbox instance for the selected backend.

    Args:
        backend: "docker" or "opensandbox". Defaults to resolved backend.
        **kwargs: Backend-specific constructor arguments.

    Returns:
        A Sandbox instance.

    Raises:
        ValueError: If backend is not supported.
    """
    backend = backend or resolve_sandbox_backend()
    if backend == "docker":
        return DockerSandbox(**kwargs)
    elif backend == "opensandbox":
        return OpenSandboxBackend(**kwargs)
    else:
        raise ValueError(
            f"Unknown sandbox backend: {backend}. "
            f"Supported: {', '.join(SUPPORTED_BACKENDS)}"
        )


# ---------------------------------------------------------------------------
# Sandbox manager
# ---------------------------------------------------------------------------


@dataclass
class ActiveSandbox:
    """Track an active sandbox instance."""

    sandbox_id: str
    implementation: str
    image: str
    policy: SecurityPolicy
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    started_at: str | None = None
    stopped_at: str | None = None
    status: str = "created"
    task_count: int = 0


class SandboxManager:
    """
    Manages sandbox lifecycle for the EB benchmark.

    Provides:
      - Creation and startup of sandbox instances
      - Command execution with timeout enforcement
      - Resource cleanup on exceptions
      - Orphan detection and recovery
    """

    def __init__(self, sandbox: Sandbox | None = None, backend: str | None = None) -> None:
        self._backend = backend or resolve_sandbox_backend()
        self._sandbox = sandbox or create_sandbox(self._backend)
        self._active: dict[str, ActiveSandbox] = {}
        self._lock = asyncio.Lock()

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def implementation(self) -> str:
        return self._sandbox.implementation

    async def create(
        self,
        image: str,
        policy: SecurityPolicy | None = None,
    ) -> str:
        """
        Create and start a new sandbox.

        Returns the sandbox_id for subsequent operations.
        """
        policy = policy or self._default_policy()
        sandbox_id = await self._sandbox.create(image, policy)
        await self._sandbox.start(sandbox_id)

        async with self._lock:
            self._active[sandbox_id] = ActiveSandbox(
                sandbox_id=sandbox_id,
                implementation=self.implementation,
                image=image,
                policy=policy,
                started_at=datetime.now(timezone.utc).isoformat(),
                status="running",
            )
        return sandbox_id

    async def exec(
        self,
        sandbox_id: str,
        command: list[str],
        timeout_s: float | None = None,
        workdir: str | None = None,
    ) -> ExecResult:
        """Execute a command inside the specified sandbox."""
        result = await self._sandbox.exec(sandbox_id, command, timeout_s, workdir)

        async with self._lock:
            if sandbox_id in self._active:
                self._active[sandbox_id].task_count += 1
        return result

    async def copy_in(self, sandbox_id: str, source: Path, dest_path: str) -> None:
        """Copy files from host into the sandbox workspace."""
        await self._sandbox.copy_in(sandbox_id, source, dest_path)

    async def copy_out(self, sandbox_id: str, src_path: str, dest: Path) -> Path:
        """Copy files from the sandbox workspace to the host."""
        return await self._sandbox.copy_out(sandbox_id, src_path, dest)

    async def collect(self, sandbox_id: str) -> dict[str, Any]:
        """Collect execution evidence from the sandbox."""
        return await self._sandbox.collect(sandbox_id)

    async def stop(self, sandbox_id: str) -> None:
        """Stop a sandbox instance."""
        await self._sandbox.stop(sandbox_id)
        async with self._lock:
            if sandbox_id in self._active:
                self._active[sandbox_id].status = "stopped"
                self._active[sandbox_id].stopped_at = datetime.now(timezone.utc).isoformat()

    async def destroy(self, sandbox_id: str) -> None:
        """Destroy a sandbox instance and clean up resources."""
        await self._sandbox.destroy(sandbox_id)
        async with self._lock:
            self._active.pop(sandbox_id, None)

    async def get_metadata(self, sandbox_id: str) -> SandboxMetadata:
        """Get metadata for a sandbox instance."""
        return await self._sandbox.get_metadata(sandbox_id)

    async def list_active(self) -> list[dict[str, Any]]:
        """List all active sandbox instances."""
        async with self._lock:
            return [
                {
                    "sandbox_id": s.sandbox_id,
                    "image": s.image,
                    "status": s.status,
                    "task_count": s.task_count,
                    "created_at": s.created_at,
                    "started_at": s.started_at,
                    "implementation": s.implementation,
                }
                for s in self._active.values()
            ]

    async def cleanup_orphans(self) -> int:
        """Find and remove orphaned sandbox containers."""
        return await self._sandbox.cleanup_orphans()

    async def cleanup_all(self) -> int:
        """Stop and destroy all active sandboxes."""
        sandbox_ids = list(self._active.keys())
        count = 0
        for sid in sandbox_ids:
            try:
                await self.destroy(sid)
                count += 1
            except Exception:
                pass
        return count

    async def __aenter__(self) -> "SandboxManager":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.cleanup_all()

    @staticmethod
    def _default_policy() -> SecurityPolicy:
        return SecurityPolicy(
            network_enabled=DEFAULT_NETWORK_ENABLED,
            cpu_limit=DEFAULT_CPU_LIMIT,
            memory_limit=DEFAULT_MEMORY_LIMIT,
        )


# ---------------------------------------------------------------------------
# Benchmark-safe sandbox executor
# ---------------------------------------------------------------------------


@dataclass
class SandboxExecution:
    """Record of a complete sandbox execution session."""

    sandbox_id: str
    image: str
    policy: SecurityPolicy
    commands_executed: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: str | None = None
    status: str = "running"

    def add_command_result(self, command: list[str], result: ExecResult) -> None:
        self.commands_executed.append({
            "command": command,
            "exit_code": result.exit_code,
            "stdout": result.stdout[:500] if result.stdout else "",
            "stderr": result.stderr[:200] if result.stderr else "",
            "duration_s": result.duration_s,
            "truncated": result.truncated,
            "timed_out": result.timed_out,
        })

    def mark_completed(self) -> None:
        self.completed_at = datetime.now(timezone.utc).isoformat()
        self.status = "completed"

    def mark_error(self, error: str) -> None:
        self.errors.append(error)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sandbox_id": self.sandbox_id,
            "image": self.image,
            "policy": self.policy.to_dict(),
            "commands_executed": self.commands_executed,
            "evidence": self.evidence,
            "tool_calls": self.tool_calls,
            "errors": self.errors,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status,
        }
