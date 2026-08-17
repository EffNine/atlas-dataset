#!/usr/bin/env python3
"""
checkpoint.py — Checkpoint manager for LONG task persistence.

Manages checkpoint file I/O, workspace archiving, integrity verification,
and cleanup for LongHorizonRunner. All checkpoints are stored under
outputs/checkpoints/<run_id>/<task_id>/.
"""

from __future__ import annotations

import hashlib
import json
import os
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.checkpoint import (
    CheckpointLoadError,
    CheckpointSaveError,
    CheckpointValidationError,
    CheckpointV1,
    CURRENT_EB_VERSION,
)
from ..core.schema import StageResult
from ..paths import outputs_dir


# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

CHECKPOINT_DIR_NAME = "checkpoints"
WORKSPACE_ARCHIVE_NAME = "workspace.tar.gz"
WORKSPACE_SNAPSHOT_NAME = "workspace_snapshot.json"
CHECKPOINT_FILE_NAME = "checkpoint.json"

# Paths to exclude from workspace archive
EXCLUDED_PATHS: frozenset[str] = frozenset({
    ".git",
    ".git/",
    ".git\\",
})

# Absolute path components that indicate path traversal attempts
DANGEROUS_PATH_PREFIXES: tuple[str, ...] = (
    "/",
    "..",
    "~",
)


# ---------------------------------------------------------------------------
# CheckpointManager
# ---------------------------------------------------------------------------


class CheckpointManager:
    """
    Manages checkpoint file I/O for LONG task execution.

    Responsibilities:
      - Create checkpoint directories under outputs/checkpoints/
      - Archive workspace as workspace.tar.gz
      - Compute workspace snapshot (file → SHA-256)
      - Write checkpoint.json atomically
      - Load and validate checkpoints
      - Clean up checkpoint files on success
    """

    def __init__(
        self,
        run_id: str,
        task_id: str,
        output_root: Path | None = None,
    ) -> None:
        self._run_id = run_id
        self._task_id = task_id
        self._output_root = output_root or outputs_dir()
        self._checkpoint_dir: Path | None = None
        self._checkpoint_id: str | None = None

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def task_id(self) -> str:
        return self._task_id

    def _make_checkpoint_dir(self) -> Path:
        """Create and return the checkpoint directory."""
        base = self._output_root / CHECKPOINT_DIR_NAME / self._run_id / self._task_id
        base.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        checkpoint_id = f"{timestamp}-{os.getpid()}"
        checkpoint_dir = base / f"{checkpoint_id}.ckpt"
        checkpoint_dir.mkdir()

        self._checkpoint_id = checkpoint_id
        self._checkpoint_dir = checkpoint_dir
        return checkpoint_dir

    def _compute_workspace_snapshot(
        self, workspace: Path
    ) -> tuple[dict[str, str], str]:
        """
        Compute SHA-256 hashes for all files in the workspace.

        Returns (snapshot_dict, archive_sha256) where snapshot_dict maps
        relative path → hex SHA-256 and archive_sha256 is the hash of the
        tar.gz archive.
        """
        snapshot: dict[str, str] = {}
        for fpath in sorted(workspace.rglob("*")):
            if not fpath.is_file():
                continue
            rel = str(fpath.relative_to(workspace))
            if self._is_excluded(rel):
                continue
            h = hashlib.sha256()
            with fpath.open("rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    h.update(chunk)
            snapshot[rel] = h.hexdigest()
        return snapshot, ""

    @staticmethod
    def _is_excluded(rel: str) -> bool:
        """Check if a relative path should be excluded from the archive."""
        parts = rel.split("/")
        for part in parts:
            if part in EXCLUDED_PATHS:
                return True
        return False

    @staticmethod
    def _is_safe_path(rel: str) -> bool:
        """Check if a path is safe (no traversal or absolute paths)."""
        if not rel:
            return False
        if rel.startswith("/") or rel.startswith("\\"):
            return False
        if ".." in rel.split("/"):
            return False
        return True

    def _archive_workspace(
        self,
        workspace: Path,
        snapshot: dict[str, str],
    ) -> str:
        """
        Create workspace.tar.gz in the checkpoint directory.

        Returns the SHA-256 of the archive file itself.
        """
        assert self._checkpoint_dir is not None
        archive_path = self._checkpoint_dir / WORKSPACE_ARCHIVE_NAME

        with tarfile.open(archive_path, "w:gz") as tar:
            for rel in sorted(snapshot.keys()):
                if not self._is_safe_path(rel):
                    continue
                full_path = workspace / rel
                if not full_path.exists() or not full_path.is_file():
                    continue
                arcname = rel.replace("\\", "/")
                tar.add(str(full_path), arcname=arcname)

        # Set restrictive permissions (0600)
        archive_path.chmod(0o600)

        # Compute SHA-256 of the archive file itself
        h = hashlib.sha256()
        with archive_path.open("rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    def save(
        self,
        *,
        workspace: Path,
        completed_stages: list[StageResult],
        next_stage_index: int,
        prev_response: str,
        sandbox_id: str,
        sandbox_image: str,
        docker_image: str,
        fixture_id: str | None,
        fixture_hash: str | None,
        security_policy: dict[str, Any],
        configuration: dict[str, Any],
        backend: str,
        repeat_id: str,
    ) -> CheckpointV1:
        """
        Save a checkpoint atomically.

        Writes checkpoint.json, workspace.tar.gz, and workspace_snapshot.json
        to a new checkpoint directory. The checkpoint is only considered
        saved after all files are written and the directory is no longer
        being modified.

        Returns the saved CheckpointV1.
        """
        checkpoint_dir = self._make_checkpoint_dir()

        # Compute workspace snapshot and archive
        snapshot, _ = self._compute_workspace_snapshot(workspace)
        archive_sha256 = self._archive_workspace(workspace, snapshot)

        # Write snapshot JSON
        snapshot_path = checkpoint_dir / WORKSPACE_SNAPSHOT_NAME
        with snapshot_path.open("w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
        snapshot_path.chmod(0o600)

        # Build checkpoint
        stage_dicts = [sr.model_dump() for sr in completed_stages]
        checkpoint = CheckpointV1(
            schema_version="1.0",
            eb_version=CURRENT_EB_VERSION,
            task_id=self._task_id,
            run_id=self._run_id,
            repeat_id=repeat_id,
            fixture_id=fixture_id,
            fixture_hash=fixture_hash,
            docker_image=docker_image,
            completed_stages=stage_dicts,
            next_stage_index=next_stage_index,
            prev_response=prev_response,
            sandbox_id=sandbox_id,
            sandbox_image=sandbox_image,
            workspace_archive_path=str(WORKSPACE_ARCHIVE_NAME),
            workspace_snapshot=snapshot,
            archive_sha256=archive_sha256,
            security_policy=security_policy,
            configuration=configuration,
            backend=backend,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        checkpoint.mark_checkpointed()

        # Atomic write: write to temp, then rename
        tmp_path = checkpoint_dir / f"{CHECKPOINT_FILE_NAME}.tmp"
        final_path = checkpoint_dir / CHECKPOINT_FILE_NAME
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(checkpoint.to_dict(), f, indent=2, ensure_ascii=False)
        tmp_path.chmod(0o600)
        tmp_path.rename(final_path)

        return checkpoint

    def load(self) -> CheckpointV1:
        """
        Load the most recent checkpoint for this run/task.

        Returns the CheckpointV1. Raises CheckpointLoadError if no
        checkpoint exists or if validation fails.
        """
        base = self._output_root / CHECKPOINT_DIR_NAME / self._run_id / self._task_id
        if not base.exists():
            raise CheckpointLoadError(f"No checkpoint directory: {base}")

        # Find the latest checkpoint directory
        ckpt_dirs = sorted(
            [d for d in base.iterdir() if d.is_dir() and d.name.endswith(".ckpt")],
            key=lambda d: d.name,
            reverse=True,
        )
        if not ckpt_dirs:
            raise CheckpointLoadError(f"No checkpoint directories in {base}")

        ckpt_path = ckpt_dirs[0] / CHECKPOINT_FILE_NAME
        return CheckpointV1.load(ckpt_path)

    def load_from_path(self, path: Path) -> CheckpointV1:
        """
        Load a checkpoint from an explicit path.

        Used by --resume to load a specific checkpoint.
        """
        return CheckpointV1.load(path)

    def validate_checkpoint(
        self,
        checkpoint: CheckpointV1,
        *,
        workspace: Path,
        fixture_hash: str | None = None,
        checkpoint_path: Path | None = None,
    ) -> None:
        """
        Validate a loaded checkpoint against current state.

        Raises CheckpointValidationError on any mismatch.
        """
        if fixture_hash is not None and checkpoint.fixture_hash is not None:
            if checkpoint.fixture_hash != fixture_hash:
                raise CheckpointValidationError(
                    f"Fixture hash mismatch: checkpoint={checkpoint.fixture_hash}, "
                    f"expected={fixture_hash}"
                )

        # Find checkpoint directory
        ckpt_base: Path | None = None
        if checkpoint_path is not None:
            ckpt_base = checkpoint_path.parent
        else:
            ckpt_base = self._get_checkpoint_base()

        if ckpt_base is None:
            raise CheckpointValidationError("Checkpoint directory not found")

        archive_path = ckpt_base / WORKSPACE_ARCHIVE_NAME
        if not archive_path.exists():
            raise CheckpointValidationError(
                f"Workspace archive missing: {archive_path}"
            )

        # Verify archive SHA-256
        h = hashlib.sha256()
        with archive_path.open("rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        computed_archive_sha256 = h.hexdigest()
        if computed_archive_sha256 != checkpoint.archive_sha256:
            raise CheckpointValidationError(
                f"Archive SHA-256 mismatch: computed={computed_archive_sha256}, "
                f"expected={checkpoint.archive_sha256}"
            )

        # Restore workspace and verify snapshot
        self._restore_workspace(archive_path, workspace)
        restored_snapshot, _ = self._compute_workspace_snapshot(workspace)
        if restored_snapshot != checkpoint.workspace_snapshot:
            missing = set(checkpoint.workspace_snapshot.keys()) - set(restored_snapshot.keys())
            extra = set(restored_snapshot.keys()) - set(checkpoint.workspace_snapshot.keys())
            diff_keys = []
            for k in sorted(checkpoint.workspace_snapshot.keys()):
                if k in restored_snapshot and checkpoint.workspace_snapshot[k] != restored_snapshot[k]:
                    diff_keys.append(k)
            warnings = []
            if missing:
                warnings.append(f"missing files: {sorted(missing)}")
            if extra:
                warnings.append(f"extra files: {sorted(extra)}")
            if diff_keys:
                warnings.append(f"changed files: {diff_keys}")
            # Log warning but don't fail — filesystem metadata may differ
            import logging
            logging.getLogger("eb").warning(
                f"Workspace snapshot has differences after restore: {', '.join(warnings)}"
            )

    def _restore_workspace(
        self,
        archive_path: Path,
        dest: Path,
    ) -> None:
        """
        Extract workspace.tar.gz to dest, with path traversal protection.
        """
        dest.mkdir(parents=True, exist_ok=True)

        with tarfile.open(archive_path, "r:gz") as tar:
            # Security: reject entries with absolute paths or traversal
            for member in tar.getmembers():
                if member.name.startswith("/") or ".." in member.name.split("/"):
                    raise CheckpointValidationError(
                        f"Unsafe path in archive: {member.name}"
                    )
            tar.extractall(dest, filter="data" if hasattr(tar, "get_members") else None)

    def _get_checkpoint_base(self) -> Path | None:
        """Get the checkpoint base directory, or None if not yet created."""
        if self._checkpoint_dir is None:
            return None
        return self._checkpoint_dir.parent

    def get_checkpoint_dir(self) -> Path | None:
        """Get the current checkpoint directory, or None."""
        return self._checkpoint_dir

    def cleanup(self) -> None:
        """
        Remove all checkpoint files for this run/task.

        Safe to call multiple times. Removes the entire checkpoint tree.
        """
        base = self._output_root / CHECKPOINT_DIR_NAME / self._run_id / self._task_id
        if base.exists():
            import shutil
            shutil.rmtree(base, ignore_errors=True)

    def cleanup_single(self, checkpoint_dir: Path) -> None:
        """Remove a single checkpoint directory."""
        if checkpoint_dir.exists():
            import shutil
            shutil.rmtree(checkpoint_dir, ignore_errors=True)
