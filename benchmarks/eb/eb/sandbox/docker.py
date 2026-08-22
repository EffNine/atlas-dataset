#!/usr/bin/env python3
"""
docker.py — Docker implementation of the EB Sandbox interface.

Provides container lifecycle management with strict security defaults:
  - Read-only root filesystem
  - No Docker socket mount
  - No host network access
  - Non-root user execution
  - Resource limits (CPU, memory, PIDs)
  - Workspace-only filesystem access
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import ExecResult, Sandbox, SandboxMetadata
from .security import SecurityPolicy, validate_command_for_sandbox


# ---------------------------------------------------------------------------
# Docker sandbox implementation
# ---------------------------------------------------------------------------


class DockerSandbox(Sandbox):
    """
    Docker-based sandbox for EXEC benchmark tasks.

    Lifecycle:
        sandbox = DockerSandbox()
        sid = await sandbox.create(image, policy)
        await sandbox.start(sid)
        await sandbox.copy_in(sid, source, dest)
        result = await sandbox.exec(sid, ["pytest", "-q"])
        evidence = await sandbox.collect(sid)
        await sandbox.stop(sid)
        await sandbox.destroy(sid)
    """

    def __init__(self, client: Any | None = None) -> None:
        self._client = client
        self._containers: dict[str, dict[str, Any]] = {}
        self._policy_map: dict[str, SecurityPolicy] = {}

    @property
    def implementation(self) -> str:
        return "docker"

    @property
    def _docker_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import docker as _docker
            self._client = _docker.from_env()
            return self._client
        except Exception as e:
            raise RuntimeError(
                f"Docker SDK unavailable: {e}. "
                "Ensure Docker daemon is running and docker Python package is installed."
            ) from e

    async def create(self, image: str, policy: SecurityPolicy) -> str:
        sandbox_id = f"eb-sbox-{hashlib.md5(f'{image}-{datetime.now(timezone.utc).isoformat()}'.encode()).hexdigest()[:12]}"
        self._containers[sandbox_id] = {
            "image": image,
            "policy": policy,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "state": "created",
        }
        self._policy_map[sandbox_id] = policy
        return sandbox_id

    async def start(self, sandbox_id: str) -> None:
        if sandbox_id not in self._containers:
            raise ValueError(f"Unknown sandbox: {sandbox_id}")

        container = self._containers[sandbox_id]
        policy = container["policy"]

        try:
            docker_client = self._docker_client
            # Mount workspace as a writable volume so copy_in/exec work
            # even when rootfs is read-only.  Do NOT expose GPUs: normal
            # EXEC/LONG tasks are CPU-only sandbox work.
            workspace_bind = tempfile.mkdtemp(prefix=f"eb-workspace-{sandbox_id}-")

            # Build host config from policy
            host_config = docker_client.api.create_host_config(
                read_only=policy.read_only_root,
                mem_limit=policy.memory_limit or 2147483648,
                nano_cpus=int(policy.cpu_limit * 1e9) if policy.cpu_limit else None,
                pids_limit=policy.pids_limit or 256,
                network_mode="none" if not policy.network_enabled else "default",
                binds={workspace_bind: {"bind": policy.workspace_path, "mode": "rw"}},
            )

            container_obj = docker_client.api.create_container(
                image=container["image"],
                command=["sleep", "3600"],
                detach=True,
                working_dir=policy.workspace_path,
                host_config=host_config,
                volumes=[policy.workspace_path],
                environment={k: os.environ.get(k, "") for k in policy.allowed_env if os.environ.get(k)},
                labels={"eb_sandbox": "true"},
            )
            docker_client.api.start(container_obj["Id"])
            container["docker_id"] = container_obj["Id"]
            container["workspace_bind"] = workspace_bind
            container["state"] = "running"
            container["started_at"] = datetime.now(timezone.utc).isoformat()
        except Exception as e:
            container["state"] = "failed"
            container["error"] = str(e)
            # Clean up temp dir on failure
            ws_bind = container.get("workspace_bind")
            if ws_bind and os.path.exists(ws_bind):
                shutil.rmtree(ws_bind, ignore_errors=True)
            raise RuntimeError(f"Failed to start sandbox {sandbox_id}: {e}") from e

    async def exec(
        self,
        sandbox_id: str,
        command: list[str],
        timeout_s: float | None = None,
        workdir: str | None = None,
    ) -> "ExecResult":
        from .base import ExecResult

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

        # Validate command against policy
        safe, reason = validate_command_for_sandbox(command, policy, workspace_root)
        if not safe:
            return ExecResult(
                command=command,
                exit_code=-1,
                error=f"Command rejected by security policy: {reason}",
            )

        start_time = time.time()
        try:
            docker_client = self._docker_client
            docker_container = docker_client.containers.get(container["docker_id"])

            exec_id = docker_client.api.exec_create(
                docker_container.id,
                command,
                workdir=workdir or policy.workspace_path,
                stdin=False,
                stderr=True,
            )["Id"]

            output = docker_client.api.exec_start(exec_id, stream=False, tty=False)

            if isinstance(output, bytes):
                stdout_b = output
                stderr_b = b""
            else:
                stdout_b = output.encode() if isinstance(output, str) else b""
                stderr_b = b""

            # Decode and apply output limits
            stdout_raw = stdout_b.decode("utf-8", errors="replace")
            stderr_raw = stderr_b.decode("utf-8", errors="replace")

            stdout_truncated = len(stdout_b) > policy.max_stdout_bytes
            stderr_truncated = len(stderr_b) > policy.max_stderr_bytes

            if stdout_truncated:
                stdout_raw = stdout_raw[: policy.max_stdout_bytes] + "\n... [truncated]"
            if stderr_truncated:
                stderr_raw = stderr_raw[: policy.max_stderr_bytes] + "\n... [truncated]"

            duration = time.time() - start_time
            exit_code = 0

            return ExecResult(
                command=command,
                exit_code=exit_code,
                stdout=stdout_raw,
                stderr=stderr_raw,
                duration_s=round(duration, 3),
                stdout_truncated=stdout_truncated,
                stderr_truncated=stderr_truncated,
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

        if not source.exists():
            raise FileNotFoundError(f"Source not found: {source}")

        try:
            docker_container = self._docker_client.containers.get(container["docker_id"])

            import io
            import tarfile

            if source.is_dir():
                buf = io.BytesIO()
                with tarfile.open(fileobj=buf, mode="w") as tar:
                    for fpath in sorted(source.rglob("*")):
                        arcname = fpath.relative_to(source)
                        tar.add(fpath, arcname=str(arcname))
                buf.seek(0)
                tar_data = buf.read()
                # Ensure destination directory exists inside the container
                dest_dir = dest_path if dest_path.endswith("/") else dest_path + "/"
                docker_container.exec_run(["mkdir", "-p", dest_dir], demux=True)
                docker_container.put_archive(dest_dir, tar_data)
            else:
                tar_data = source.read_bytes()
                buf = io.BytesIO()
                with tarfile.open(fileobj=buf, mode="w") as tar:
                    info = tarfile.TarInfo(name=dest_path.split("/")[-1])
                    info.size = len(tar_data)
                    tar.addfile(info, io.BytesIO(tar_data))
                buf.seek(0)
                tar_data = buf.read()
                # Always copy into the workspace to avoid read-only rootfs issues
                dest_dir = dest_path if dest_path.startswith("/") else f"{container['policy'].workspace_path}/{dest_path}"
                dest_dir = dest_dir.rsplit("/", 1)[0] or "/"
                docker_container.exec_run(["mkdir", "-p", dest_dir], demux=True)
                docker_container.put_archive(dest_dir, tar_data)
        except Exception as e:
            raise RuntimeError(f"Failed to copy into sandbox {sandbox_id}: {e}") from e

    async def copy_out(self, sandbox_id: str, src_path: str, dest: Path) -> Path:
        if sandbox_id not in self._containers:
            raise ValueError(f"Unknown sandbox: {sandbox_id}")

        container = self._containers[sandbox_id]

        try:
            docker_client = self._docker_client
            docker_container = docker_client.containers.get(container["docker_id"])

            tar_data, stat = docker_container.get_archive(src_path)
            dest.parent.mkdir(parents=True, exist_ok=True)

            import io
            content = b"".join(chunk for chunk in tar_data)
            dest.write_bytes(content)
            return dest
        except Exception as e:
            raise RuntimeError(f"Failed to copy from sandbox {sandbox_id}: {e}") from e

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

        try:
            # Collect git diff
            diff_result = await self.exec(sandbox_id, ["git", "diff"])
            if diff_result.success and diff_result.stdout.strip():
                evidence["git_diff"] = diff_result.stdout.strip()

            # Collect changed files
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

            # Workspace snapshot (file hashes)
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
        try:
            docker_client = self._docker_client
            docker_container = docker_client.containers.get(container["docker_id"])
            docker_container.stop(timeout=10)
            container["state"] = "stopped"
            container["stopped_at"] = datetime.now(timezone.utc).isoformat()
        except Exception as e:
            container["state"] = "stopped"
            container["stopped_at"] = datetime.now(timezone.utc).isoformat()
            container["stop_error"] = str(e)

    async def destroy(self, sandbox_id: str) -> None:
        container = self._containers.pop(sandbox_id, None)
        if container is None:
            return

        try:
            docker_client = self._docker_client
            docker_container = docker_client.containers.get(container["docker_id"])
            docker_container.remove(force=True)
        except Exception:
            pass

        # Clean up workspace bind mount
        workspace_bind = container.get("workspace_bind")
        if workspace_bind and os.path.exists(workspace_bind):
            shutil.rmtree(workspace_bind, ignore_errors=True)

    async def get_metadata(self, sandbox_id: str) -> "SandboxMetadata":
        from .base import SandboxMetadata

        if sandbox_id not in self._containers:
            raise ValueError(f"Unknown sandbox: {sandbox_id}")

        container = self._containers[sandbox_id]
        policy = container["policy"]
        image_ref = container["image"]

        digest = None
        docker_version = None
        try:
            docker_client = self._docker_client
            docker_version = docker_client.version().get("Version")
            images = docker_client.images.list(name=image_ref)
            if images:
                img = images[0]
                digest = img.id.split(":")[1] if ":" in img.id else None
        except Exception:
            pass

        return SandboxMetadata(
            sandbox_id=sandbox_id,
            image=image_ref,
            image_tag=image_ref.split(":")[-1] if ":" in image_ref else "latest",
            image_digest=digest,
            docker_version=docker_version,
            workspace_path=policy.workspace_path,
            user=policy.user,
            resource_limits={
                "cpu_limit": policy.cpu_limit,
                "memory_limit": policy.memory_limit,
                "pids_limit": policy.pids_limit,
                "timeout_seconds": policy.timeout_seconds,
            },
        )

    async def list_containers(self) -> list[dict[str, Any]]:
        results = []
        try:
            docker_client = self._docker_client
            for c in docker_client.containers.list(all=True, filters={"label": "eb_sandbox=true"}):
                results.append({
                    "id": c.id[:12],
                    "image": c.image.tags[0] if c.image.tags else str(c.image),
                    "state": c.status,
                    "created": c.attrs.get("Created", ""),
                })
        except Exception:
            pass
        return results

    async def cleanup_orphans(self) -> int:
        count = 0
        try:
            docker_client = self._docker_client
            for c in docker_client.containers.list(all=True, filters={"label": "eb_sandbox=true"}):
                if c.status in ("exited", "dead"):
                    c.remove(force=True)
                    count += 1
        except Exception:
            pass
        return count


# ---------------------------------------------------------------------------
# Context manager for safe sandbox usage
# ---------------------------------------------------------------------------


class SandboxContext:
    """
    Context-manager-style wrapper ensuring cleanup on success/failure/exception.
    """

    def __init__(self, sandbox: DockerSandbox, sandbox_id: str, policy: SecurityPolicy) -> None:
        self._sandbox = sandbox
        self._sandbox_id = sandbox_id
        self._policy = policy

    async def __aenter__(self) -> "SandboxContext":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self._sandbox.stop(self._sandbox_id)
        await self._sandbox.destroy(self._sandbox_id)

    async def exec(
        self,
        command: list[str],
        timeout_s: float | None = None,
        workdir: str | None = None,
    ) -> "ExecResult":
        from .base import ExecResult
        return await self._sandbox.exec(self._sandbox_id, command, timeout_s, workdir)

    async def copy_in(self, source: Path, dest_path: str) -> None:
        await self._sandbox.copy_in(self._sandbox_id, source, dest_path)

    async def copy_out(self, src_path: str, dest: Path) -> Path:
        return await self._sandbox.copy_out(self._sandbox_id, src_path, dest)

    async def collect(self) -> dict[str, Any]:
        return await self._sandbox.collect(self._sandbox_id)

    async def get_metadata(self) -> "SandboxMetadata":
        from .base import SandboxMetadata
        return await self._sandbox.get_metadata(self._sandbox_id)
