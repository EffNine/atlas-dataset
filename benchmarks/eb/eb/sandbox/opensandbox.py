#!/usr/bin/env python3
"""
opensandbox.py — OpenSandbox backend implementation of the EB Sandbox interface.

Provides an alternative sandbox backend using the OpenSandbox platform
(https://github.com/opensandbox-group/OpenSandbox) instead of direct Docker.

OpenSandbox is a control-plane API that manages Docker/Kubernetes sandboxes.
This adapter translates EB's Sandbox interface into OpenSandbox SDK calls.

Requirements:
  - OpenSandbox server running (endpoint via EB_OPENSANDBOX_BASE_URL)
  - API key (via EB_OPENSANDBOX_API_KEY)
  - Python package: pip install opensandbox

Environment variables:
  EB_SANDBOX_BACKEND      — "docker" (default) or "opensandbox"
  EB_OPENSANDBOX_BASE_URL — OpenSandbox server endpoint (e.g. http://localhost:8080)
  EB_OPENSANDBOX_API_KEY  — API key for OpenSandbox server
"""

from __future__ import annotations

import hashlib
import os
import shlex
import tarfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import io as _io_module

from .base import ExecResult, Sandbox, SandboxMetadata
from .security import SecurityPolicy, validate_command_for_sandbox


# ---------------------------------------------------------------------------
# OpenSandbox-specific error types
# ---------------------------------------------------------------------------


class OpenSandboxError(RuntimeError):
    """Base exception for OpenSandbox adapter errors."""


class OpenSandboxAuthError(OpenSandboxError):
    """Authentication failed with OpenSandbox server."""


class OpenSandboxNotFoundError(OpenSandboxError):
    """Requested sandbox not found."""


class OpenSandboxTimeoutError(OpenSandboxError):
    """Command or sandbox operation timed out."""


class OpenSandboxUnavailableError(OpenSandboxError):
    """OpenSandbox server is not reachable."""


# ---------------------------------------------------------------------------
# Capability reporting
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OpenSandboxCapabilities:
    """Features supported by the OpenSandbox backend."""

    has_network_policy: bool = True
    has_cpu_limit: bool = True
    has_memory_limit: bool = True
    has_pid_limit: bool = False
    has_read_only_root: bool = False
    has_timeout: bool = True
    has_streaming: bool = True
    has_snapshot: bool = True
    has_isolated_execution: bool = True
    has_file_upload: bool = True
    has_file_download: bool = True
    has_list_files: bool = True
    has_cleanup_api: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


# ---------------------------------------------------------------------------
# OpenSandbox backend
# ---------------------------------------------------------------------------


class OpenSandboxBackend(Sandbox):
    """
    OpenSandbox-based sandbox backend for EB EXEC tasks.

    Lifecycle:
        sandbox = OpenSandboxBackend()
        sid = await sandbox.create(image, policy)
        await sandbox.start(sid)
        await sandbox.copy_in(sid, source, dest)
        result = await sandbox.exec(sid, ["pytest", "-q"])
        evidence = await sandbox.collect(sid)
        await sandbox.stop(sid)
        await sandbox.destroy(sid)

    The OpenSandbox server manages the underlying Docker containers.
    This adapter only holds the sandbox_id and forwards operations.
    """

    def __init__(self, base_url: str | None = None, api_key: str | None = None) -> None:
        self._base_url = base_url or os.environ.get("EB_OPENSANDBOX_BASE_URL", "http://localhost:8080")
        self._api_key = api_key or os.environ.get("EB_OPENSANDBOX_API_KEY", "")
        self._containers: dict[str, dict[str, Any]] = {}
        self._policy_map: dict[str, SecurityPolicy] = {}
        self._sdk_available = False
        self._imported = False

    @property
    def implementation(self) -> str:
        return "opensandbox"

    @property
    def capabilities(self) -> OpenSandboxCapabilities:
        return OpenSandboxCapabilities()

    def _ensure_sdk(self) -> None:
        """Import and cache the OpenSandbox SDK on first use."""
        if self._imported:
            return
        try:
            from opensandbox.sandbox import Sandbox as _OSSandbox
            from opensandbox.config import ConnectionConfig as _OSConfig
            from opensandbox.exceptions import SandboxException as _OSExc
            from opensandbox.models.sandboxes import NetworkPolicy as _NetPol
            from opensandbox.models.filesystem import WriteEntry as _WriteEntry
            from opensandbox.manager import SandboxManager as _OSMgr
            from opensandbox.models.sandboxes import SandboxFilter as _OSFilter
            from opensandbox.models.execd import RunCommandOpts as _RunCommandOpts

            self._OSSandbox = _OSSandbox
            self._OSConfig = _OSConfig
            self._OSExc = _OSExc
            self._NetPol = _NetPol
            self._WriteEntry = _WriteEntry
            self._OSMgr = _OSMgr
            self._OSFilter = _OSFilter
            self._RunCommandOpts = _RunCommandOpts
            self._sdk_available = True
            self._imported = True
        except ImportError as e:
            raise RuntimeError(
                f"OpenSandbox SDK not available: {e}. "
                "Install with: pip install opensandbox"
            ) from e

    async def create(self, image: str, policy: SecurityPolicy) -> str:
        self._ensure_sdk()

        sandbox_id = f"eb-osb-{hashlib.md5(f'{image}-{datetime.now(timezone.utc).isoformat()}'.encode()).hexdigest()[:12]}"

        self._containers[sandbox_id] = {
            "image": image,
            "policy": policy,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "state": "created",
            "os_id": None,
        }
        self._policy_map[sandbox_id] = policy
        return sandbox_id

    async def start(self, sandbox_id: str) -> None:
        if sandbox_id not in self._containers:
            raise ValueError(f"Unknown sandbox: {sandbox_id}")

        container = self._containers[sandbox_id]
        policy = container["policy"]
        image = container["image"]

        try:
            config = self._OSConfig(
                domain=self._base_url,
                api_key=self._api_key,
                request_timeout=timedelta(seconds=120),
            )

            resource: dict[str, str] = {}
            if policy.cpu_limit:
                resource["cpu"] = str(policy.cpu_limit)
            if policy.memory_limit:
                resource["memory"] = f"{policy.memory_limit // (1024 * 1024 * 1024)}Gi"

            network_policy = None
            if not policy.network_enabled:
                network_policy = self._NetPol(defaultAction="deny")
            else:
                network_policy = self._NetPol(defaultAction="allow")

            env: dict[str, str] = {}
            for k in policy.allowed_env:
                v = os.environ.get(k, "")
                if v:
                    env[k] = v

            # Only pass timeout if it's reasonable (>= 60s per server validation)
            timeout_td = timedelta(seconds=max(policy.timeout_seconds, 60))

            os_sandbox = await self._OSSandbox.create(
                image,
                connection_config=config,
                timeout=timeout_td,
                resource=resource if resource else None,
                env=env if env else None,
                network_policy=network_policy,
                metadata={"eb_sandbox": "true", "eb_id": sandbox_id},
            )

            container["os_id"] = os_sandbox.id
            container["state"] = "running"
            container["started_at"] = datetime.now(timezone.utc).isoformat()
            container["_os_sandbox_ref"] = os_sandbox
        except self._OSExc as e:
            container["state"] = "failed"
            container["error"] = str(e)
            raise OpenSandboxError(f"OpenSandbox create failed: {e}") from e
        except Exception as e:
            container["state"] = "failed"
            container["error"] = str(e)
            if "ApiKey" in type(e).__name__ or "auth" in str(e).lower():
                raise OpenSandboxAuthError(f"OpenSandbox authentication failed: {e}") from e
            elif "not found" in str(e).lower() or "404" in str(e):
                raise OpenSandboxNotFoundError(f"OpenSandbox sandbox not found: {e}") from e
            elif "timeout" in str(e).lower() or "timed out" in str(e).lower():
                raise OpenSandboxTimeoutError(f"OpenSandbox timeout: {e}") from e
            elif "unreachable" in str(e).lower() or "connection" in str(e).lower():
                raise OpenSandboxUnavailableError(f"OpenSandbox service unavailable: {e}") from e
            else:
                raise OpenSandboxError(f"OpenSandbox error: {e}") from e

    async def exec(
        self,
        sandbox_id: str,
        command: list[str],
        timeout_s: float | None = None,
        workdir: str | None = None,
    ) -> ExecResult:
        if sandbox_id not in self._containers:
            return ExecResult(
                command=command,
                exit_code=-1,
                error=f"Unknown sandbox: {sandbox_id}",
            )

        container = self._containers[sandbox_id]
        policy = container["policy"]
        timeout = timeout_s or policy.timeout_seconds
        workspace_root = policy.workspace_path

        safe, reason = validate_command_for_sandbox(command, policy, workspace_root)
        if not safe:
            return ExecResult(
                command=command,
                exit_code=-1,
                error=f"Command rejected by security policy: {reason}",
            )

        os_sandbox = container.get("_os_sandbox_ref")
        if os_sandbox is None:
            return ExecResult(
                command=command,
                exit_code=-1,
                error=f"Sandbox {sandbox_id} not started (no OpenSandbox ref)",
            )

        cmd_str = shlex.join(command)
        start_time = time.time()

        try:
            opts = self._RunCommandOpts(timeout=timedelta(seconds=timeout))
            execution = await os_sandbox.commands.run(cmd_str, opts=opts)

            stdout_parts = [line.text for line in execution.logs.stdout]
            stderr_parts = [line.text for line in execution.logs.stderr]
            stdout_raw = "\n".join(stdout_parts)
            stderr_raw = "\n".join(stderr_parts)

            stdout_truncated = len(stdout_raw.encode()) > policy.max_stdout_bytes
            stderr_truncated = len(stderr_raw.encode()) > policy.max_stderr_bytes

            if stdout_truncated:
                stdout_raw = stdout_raw[:policy.max_stdout_bytes] + "\n... [truncated]"
            if stderr_truncated:
                stderr_raw = stderr_raw[:policy.max_stderr_bytes] + "\n... [truncated]"

            duration = time.time() - start_time
            exit_code = execution.exit_code if execution.exit_code is not None else (0 if not execution.error else -1)

            return ExecResult(
                command=command,
                exit_code=exit_code,
                stdout=stdout_raw,
                stderr=stderr_raw,
                duration_s=round(duration, 3),
                truncated=stdout_truncated or stderr_truncated,
                stdout_truncated=stdout_truncated,
                stderr_truncated=stderr_truncated,
                timed_out=duration >= timeout,
            )
        except self._OSExc as e:
            duration = time.time() - start_time
            return ExecResult(
                command=command,
                exit_code=-1,
                error=f"OpenSandbox exec error: {e}",
                duration_s=round(duration, 3),
                timed_out=duration >= timeout,
            )
        except Exception as e:
            duration = time.time() - start_time
            return ExecResult(
                command=command,
                exit_code=-1,
                error=str(e),
                duration_s=round(duration, 3),
                timed_out=duration >= timeout,
            )

    async def copy_in(self, sandbox_id: str, source: Path, dest_path: str) -> None:
        if sandbox_id not in self._containers:
            raise ValueError(f"Unknown sandbox: {sandbox_id}")

        container = self._containers[sandbox_id]
        os_sandbox = container.get("_os_sandbox_ref")
        if os_sandbox is None:
            raise RuntimeError(f"Sandbox {sandbox_id} not started")

        if not source.exists():
            raise FileNotFoundError(f"Source not found: {source}")

        try:
            if source.is_dir():
                buf = _io_module.BytesIO()
                with tarfile.open(fileobj=buf, mode="w") as tar:
                    for fpath in sorted(source.rglob("*")):
                        arcname = fpath.relative_to(source)
                        tar.add(fpath, arcname=str(arcname))
                buf.seek(0)
                tar_data = buf.read()
            else:
                tar_data = source.read_bytes()
                buf = _io_module.BytesIO()
                with tarfile.open(fileobj=buf, mode="w") as tar:
                    info = tarfile.TarInfo(name=dest_path.split("/")[-1])
                    info.size = len(tar_data)
                    tar.addfile(info, _io_module.BytesIO(tar_data))
                buf.seek(0)
                tar_data = buf.read()

            dest_filename = dest_path.split("/")[-1]
            dest_dir = dest_path.rstrip("/").rsplit("/", 1)[0] if "/" in dest_path else "."

            await os_sandbox.files.write_files([
                self._WriteEntry(path=f"{dest_dir}/{dest_filename}", data=tar_data, mode=0o644)
            ])
        except Exception as e:
            raise RuntimeError(f"Failed to copy into OpenSandbox {sandbox_id}: {e}") from e

    async def copy_out(self, sandbox_id: str, src_path: str, dest: Path) -> Path:
        if sandbox_id not in self._containers:
            raise ValueError(f"Unknown sandbox: {sandbox_id}")

        container = self._containers[sandbox_id]
        os_sandbox = container.get("_os_sandbox_ref")
        if os_sandbox is None:
            raise RuntimeError(f"Sandbox {sandbox_id} not started")

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            content = await os_sandbox.files.read_file(src_path)
            if isinstance(content, bytes):
                dest.write_bytes(content)
            else:
                dest.write_text(str(content))
            return dest
        except Exception as e:
            raise RuntimeError(f"Failed to copy from OpenSandbox {sandbox_id}: {e}") from e

    async def collect(self, sandbox_id: str) -> dict[str, Any]:
        if sandbox_id not in self._containers:
            raise ValueError(f"Unknown sandbox: {sandbox_id}")

        container = self._containers[sandbox_id]
        policy = container["policy"]
        workspace_root = policy.workspace_path

        evidence: dict[str, Any] = {
            "git_diff": None,
            "changed_files": [],
            "workspace_snapshot": {},
            "resource_usage": {},
        }

        os_sandbox = container.get("_os_sandbox_ref")
        if os_sandbox is None:
            return evidence

        try:
            diff_result = await self.exec(sandbox_id, ["git", "diff"])
            if diff_result.success and diff_result.stdout.strip():
                evidence["git_diff"] = diff_result.stdout.strip()

            files_result = await self.exec(
                sandbox_id,
                ["git", "status", "--porcelain"],
            )
            if files_result.success:
                for line in files_result.stdout.strip().splitlines():
                    if line.strip():
                        fname = line[3:].strip()
                        if fname:
                            evidence["changed_files"].append(fname)

            snapshot_result = await self.exec(
                sandbox_id,
                ["find", workspace_root, "-type", "f", "-not", "-path", "*/.git/*"],
            )
            if snapshot_result.success:
                for fpath in snapshot_result.stdout.strip().splitlines():
                    fpath = fpath.strip()
                    if fpath:
                        hash_result = await self.exec(sandbox_id, ["sha256sum", fpath])
                        if hash_result.success:
                            parts = hash_result.stdout.strip().split()
                            if len(parts) >= 2:
                                evidence["workspace_snapshot"][fpath] = parts[0]

        except Exception as e:
            evidence["collect_error"] = str(e)

        return evidence

    async def stop(self, sandbox_id: str) -> None:
        if sandbox_id not in self._containers:
            raise ValueError(f"Unknown sandbox: {sandbox_id}")

        container = self._containers[sandbox_id]
        os_sandbox = container.get("_os_sandbox_ref")
        if os_sandbox is not None:
            try:
                await os_sandbox.close()
            except Exception:
                pass
        container["state"] = "stopped"
        container["stopped_at"] = datetime.now(timezone.utc).isoformat()

    async def destroy(self, sandbox_id: str) -> None:
        container = self._containers.pop(sandbox_id, None)
        if container is None:
            return

        os_sandbox = container.get("_os_sandbox_ref")
        if os_sandbox is not None:
            try:
                await os_sandbox.destroy()
            except Exception:
                pass

        container["state"] = "destroyed"

    async def get_metadata(self, sandbox_id: str) -> "SandboxMetadata":
        if sandbox_id not in self._containers:
            raise ValueError(f"Unknown sandbox: {sandbox_id}")

        container = self._containers[sandbox_id]
        policy = container["policy"]
        image_ref = container["image"]
        os_sandbox = container.get("_os_sandbox_ref")

        os_version = None
        try:
            if os_sandbox is not None:
                info = await os_sandbox.get_info()
                os_version = getattr(info, "runtime", None)
        except Exception:
            pass

        return SandboxMetadata(
            sandbox_id=sandbox_id,
            image=image_ref,
            image_tag=image_ref.split(":")[-1] if ":" in image_ref else "latest",
            image_digest=None,
            docker_version=os_version,
            created_at=container.get("created_at", datetime.now(timezone.utc).isoformat()),
            stopped_at=container.get("stopped_at"),
            workspace_path=policy.workspace_path,
            user=policy.user,
            resource_limits={
                "cpu_limit": policy.cpu_limit,
                "memory_limit": policy.memory_limit,
                "pids_limit": policy.pids_limit,
                "timeout_seconds": policy.timeout_seconds,
                "network_enabled": policy.network_enabled,
                "backend": "opensandbox",
            },
        )

    async def list_containers(self) -> list[dict[str, Any]]:
        results = []
        try:
            self._ensure_sdk()
            config = self._OSConfig(domain=self._base_url, api_key=self._api_key)
            async with await self._OSMgr.create(connection_config=config) as manager:
                sandboxes = await manager.list_sandbox_infos(
                    self._OSFilter(states=["RUNNING"], page_size=100)
                )
                for info in sandboxes.sandbox_infos:
                    results.append({
                        "id": info.id,
                        "image": info.image,
                        "state": info.status.state if info.status else "unknown",
                        "created": info.created_at or "",
                        "eb_id": info.metadata.get("eb_id") if info.metadata else "",
                    })
        except Exception:
            pass
        return results

    async def cleanup_orphans(self) -> int:
        count = 0
        try:
            self._ensure_sdk()
            config = self._OSConfig(domain=self._base_url, api_key=self._api_key)
            async with await self._OSMgr.create(connection_config=config) as manager:
                sandboxes = await manager.list_sandbox_infos(
                    self._OSFilter(states=["RUNNING", "TERMINATED", "FAILED"], page_size=100)
                )
                for info in sandboxes.sandbox_infos:
                    eb_id = info.metadata.get("eb_id") if info.metadata else ""
                    if eb_id and eb_id.startswith("eb-osb-"):
                        try:
                            await manager.kill_sandbox(info.id)
                            count += 1
                        except Exception:
                            pass
        except Exception:
            pass
        return count


# ---------------------------------------------------------------------------
# Context manager for safe sandbox usage
# ---------------------------------------------------------------------------


class OpenSandboxContext:
    """
    Context-manager-style wrapper ensuring cleanup on success/failure/exception.
    """

    def __init__(self, sandbox: OpenSandboxBackend, sandbox_id: str, policy: SecurityPolicy) -> None:
        self._sandbox = sandbox
        self._sandbox_id = sandbox_id
        self._policy = policy

    async def __aenter__(self) -> "OpenSandboxContext":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self._sandbox.stop(self._sandbox_id)
        await self._sandbox.destroy(self._sandbox_id)

    async def exec(
        self,
        command: list[str],
        timeout_s: float | None = None,
        workdir: str | None = None,
    ) -> ExecResult:
        return await self._sandbox.exec(self._sandbox_id, command, timeout_s, workdir)

    async def copy_in(self, source: Path, dest_path: str) -> None:
        await self._sandbox.copy_in(self._sandbox_id, source, dest_path)

    async def copy_out(self, src_path: str, dest: Path) -> Path:
        return await self._sandbox.copy_out(self._sandbox_id, src_path, dest)

    async def collect(self) -> dict[str, Any]:
        return await self._sandbox.collect(self._sandbox_id)

    async def get_metadata(self) -> SandboxMetadata:
        return await self._sandbox.get_metadata(self._sandbox_id)
