#!/usr/bin/env python3
"""
checkpoint.py — Checkpoint schema for LONG task persistence.

Defines CheckpointV1, the Pydantic model for checkpoint files used by
LongHorizonRunner to persist execution state between stages and support
manual resume after process interruption.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Schema versioning
# ---------------------------------------------------------------------------

SUPPORTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({"1.0"})
CURRENT_SCHEMA_VERSION: str = "1.0"
CURRENT_EB_VERSION: str = "0.1.0"


# ---------------------------------------------------------------------------
# Checkpoint exception hierarchy
# ---------------------------------------------------------------------------


class CheckpointError(Exception):
    """Base exception for checkpoint errors."""


class CheckpointLoadError(CheckpointError):
    """Failed to load a checkpoint (corrupt, missing, wrong schema)."""


class CheckpointSaveError(CheckpointError):
    """Failed to save a checkpoint."""


class CheckpointValidationError(CheckpointError):
    """Checkpoint failed validation (hash mismatch, archive missing, etc.)."""


# ---------------------------------------------------------------------------
# CheckpointV1 schema
# ---------------------------------------------------------------------------


class CheckpointV1(BaseModel):
    """
    Checkpoint for a LONG task execution.

    Captures everything needed to resume from a stage boundary after
    process interruption. Does NOT contain secrets, API keys, or
    environment variable values.
    """

    # Schema identity
    schema_version: str = CURRENT_SCHEMA_VERSION
    eb_version: str = CURRENT_EB_VERSION

    # Task identity
    task_id: str
    run_id: str
    repeat_id: str

    # Fixture state (for integrity verification)
    fixture_id: str | None = None
    fixture_hash: str | None = None

    # Image
    docker_image: str

    # Execution state
    completed_stages: list[dict[str, Any]] = Field(default_factory=list)
    next_stage_index: int = 0
    prev_response: str = ""

    # Sandbox traceability (may be stale after process restart)
    sandbox_id: str = ""
    sandbox_image: str = ""

    # Workspace archive
    workspace_archive_path: str = ""
    workspace_snapshot: dict[str, str] = Field(default_factory=dict)
    archive_sha256: str = ""

    # Security policy (serialized, no secrets)
    security_policy: dict[str, Any] = Field(default_factory=dict)

    # Runner configuration
    configuration: dict[str, Any] = Field(default_factory=dict)

    # Backend identity
    backend: str = "docker"

    # Timestamps
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resumed_from: str | None = None

    # Integrity
    checksum: str | None = None

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, v: str) -> str:
        if v not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"Unsupported schema version {v!r}. "
                f"Supported: {', '.join(sorted(SUPPORTED_SCHEMA_VERSIONS))}"
            )
        return v

    def compute_checksum(self) -> str:
        """
        Compute SHA-256 of the serialized checkpoint payload.

        The checksum is computed over the model dump excluding the checksum
        field itself, producing a canonical deterministic hash.
        """
        payload = self.model_dump(exclude={"checksum"})
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def verify_checksum(self) -> bool:
        """Verify the stored checksum matches the computed one."""
        computed = self.compute_checksum()
        return computed == self.checksum

    def mark_checkpointed(self) -> None:
        """Set the checksum field to the current computed value."""
        self.checksum = self.compute_checksum()

    @classmethod
    def load(cls, path: Path) -> "CheckpointV1":
        """
        Load a checkpoint from disk.

        Raises CheckpointLoadError if the file is missing, malformed JSON,
        has a checksum mismatch, or an unsupported schema version.
        """
        if not path.exists():
            raise CheckpointLoadError(f"Checkpoint not found: {path}")

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise CheckpointLoadError(f"Invalid JSON in checkpoint: {e}") from e

        schema_version = data.get("schema_version", "0.0")
        if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise CheckpointLoadError(
                f"Unsupported schema version {schema_version!r}. "
                f"Supported: {', '.join(sorted(SUPPORTED_SCHEMA_VERSIONS))}"
            )

        try:
            checkpoint = cls.model_validate(data)
        except Exception as e:
            raise CheckpointLoadError(f"Failed to parse checkpoint: {e}") from e

        if not checkpoint.verify_checksum():
            raise CheckpointLoadError(
                f"Checkpoint checksum mismatch: {path}"
            )

        return checkpoint

    @classmethod
    def load_raw(cls, path: Path) -> "CheckpointV1":
        """
        Load a checkpoint without verifying the checksum.

        Used during validation before deciding whether to trust the file.
        """
        if not path.exists():
            raise CheckpointLoadError(f"Checkpoint not found: {path}")

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise CheckpointLoadError(f"Invalid JSON in checkpoint: {e}") from e

        schema_version = data.get("schema_version", "0.0")
        if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise CheckpointLoadError(
                f"Unsupported schema version {schema_version!r}. "
                f"Supported: {', '.join(sorted(SUPPORTED_SCHEMA_VERSIONS))}"
            )

        try:
            return cls.model_validate(data)
        except Exception as e:
            raise CheckpointLoadError(f"Failed to parse checkpoint: {e}") from e

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for writing."""
        return self.model_dump()
