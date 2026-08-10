#!/usr/bin/env python3
"""
metadata.py — Run metadata and checksum utilities.

Provides functions for collecting run metadata (git info, hardware info,
checksums) and dataclasses for storing run and checkpoint metadata.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def compute_sha256(path: Path | str) -> str:
    """
    Compute the SHA-256 hash of a file.

    Args:
        path: Path to the file.

    Returns:
        Hexdigest of the SHA-256 hash.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_records_sha256(jsonl_path: Path | str) -> str:
    """
    Compute the SHA-256 hash of sorted, serialized JSON records.

    This provides a canonical checksum that is stable regardless of file
    ordering (by record_id) and serialization format.

    Args:
        jsonl_path: Path to the JSONL file.

    Returns:
        Hexdigest of the SHA-256 hash of canonical sorted records.
    """
    p = Path(jsonl_path)
    records = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    # Sort by record_id for determinism
    records.sort(key=lambda r: str(r.get("record_id") or r.get("id", "")))

    # Serialize to canonical JSON (sorted keys, no trailing whitespace)
    canonical = "\n".join(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in records)
    h = hashlib.sha256()
    h.update(canonical.encode("utf-8"))
    return h.hexdigest()


def git_info(repo_path: Path | str | None = None) -> dict[str, str | None]:
    """
    Collect git repository information.

    Args:
        repo_path: Path to the git repository. Defaults to current directory.

    Returns:
        Dictionary with git_commit, git_short, git_status_clean, git_branch.
    """
    def _run(cmd: list[str]) -> str | None:
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10,
                cwd=str(repo_path) if repo_path else None,
            )
            return result.stdout.strip() or None
        except Exception:
            return None

    commit = _run(["git", "rev-parse", "HEAD"])
    short = _run(["git", "rev-parse", "--short", "HEAD"])
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])

    # Check if working tree is clean
    status_output = _run(["git", "status", "--porcelain"])
    is_clean = status_output is None or status_output == ""

    return {
        "git_commit": commit,
        "git_short": short,
        "git_branch": branch,
        "git_status_clean": "true" if is_clean else "false",
    }


def hardware_info() -> dict[str, Any]:
    """
    Collect hardware and software version information.

    Returns:
        Dictionary with GPU info, torch version, CUDA version, etc.
    """
    info: dict[str, Any] = {
        "platform": "unknown",
        "python_version": "unknown",
        "torch_version": "unknown",
        "cuda_available": False,
        "cuda_version": None,
        "gpu_name": None,
        "vram_total_mib": None,
    }

    try:
        import platform
        info["platform"] = platform.system()
    except Exception:
        pass

    try:
        import sys
        info["python_version"] = sys.version
    except Exception:
        pass

    try:
        import torch
        info["torch_version"] = torch.__version__
        info["cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            info["cuda_version"] = torch.version.cuda
            p = torch.cuda.get_device_properties(0)
            info["gpu_name"] = p.name
            info["vram_total_mib"] = round(p.total_memory / 1024**2, 2)
    except ImportError:
        pass
    except Exception:
        pass

    return info


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RunMetadata:
    """
    Pre-run metadata collected before training begins.

    This captures all the inputs that must be pinned for reproducibility.
    """
    experiment_id: str
    phase: str
    git_commit: str | None = None
    git_short: str | None = None
    git_status_clean: str | None = None
    train_jsonl_sha256: str | None = None
    approved_train_sha256: str | None = None
    checksum_match: bool | None = None
    model_revision: str | None = None
    cuda_available: bool | None = None
    hardware: dict[str, Any] | None = None
    generated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunMetadata":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def collect(
        cls,
        experiment_id: str,
        phase: str,
        train_jsonl_path: Path | str | None = None,
        approved_train_sha256: str | None = None,
    ) -> "RunMetadata":
        """
        Collect run metadata before training begins.

        Args:
            experiment_id: Experiment identifier.
            phase: Phase identifier (e.g., "5B.1", "8").
            train_jsonl_path: Path to the training JSONL file (optional).
            approved_train_sha256: Expected SHA-256 of the training file (optional).

        Returns:
            RunMetadata with all collected fields.
        """
        now = datetime.now(timezone.utc).isoformat()

        # Collect git info
        from ..atlas_paths import get_root
        git = git_info(get_root())

        # Compute train checksum if path provided
        train_sha = None
        checksum_match = None
        if train_jsonl_path is not None:
            train_sha = compute_sha256(train_jsonl_path)
            if approved_train_sha256 is not None:
                checksum_match = (train_sha == approved_train_sha256)

        # Collect hardware info
        hw = hardware_info()

        return cls(
            experiment_id=experiment_id,
            phase=phase,
            git_commit=git.get("git_commit"),
            git_short=git.get("git_short"),
            git_status_clean=git.get("git_status_clean"),
            train_jsonl_sha256=train_sha,
            approved_train_sha256=approved_train_sha256,
            checksum_match=checksum_match,
            model_revision=None,  # Collected after model load
            cuda_available=hw.get("cuda_available"),
            hardware=hw,
            generated_at=now,
        )

    def validate(self) -> list[str]:
        """
        Validate the collected metadata for reproducibility.

        Returns a list of validation errors (empty if valid).
        """
        errors = []
        if not self.git_commit:
            errors.append("git_commit is required for reproducibility")
        if not self.train_jsonl_sha256:
            errors.append("train_jsonl_sha256 is required for reproducibility")
        if self.approved_train_sha256 is not None and self.checksum_match is False:
            errors.append("train JSONL checksum mismatch — fail-closed")
        if self.generated_at is None:
            errors.append("generated_at timestamp is required")
        return errors


@dataclass
class CheckpointMetadata:
    """
    Metadata for a training checkpoint (LoRA adapter).

    Tracks the adapter configuration, SHA-256 hashes, and training state
    at the time of the checkpoint.
    """
    adapter_path: str
    base_model: str
    adapter_config_sha256: str | None = None
    adapter_model_sha256: str | None = None
    trainable_parameters: int | None = None
    total_parameters: int | None = None
    trainable_percent: float | None = None
    training_steps: int | None = None
    final_loss: float | None = None
    min_loss: float | None = None
    peak_mem_allocated_mib: float | None = None
    generated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CheckpointMetadata":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_adapter_dir(
        cls,
        adapter_dir: Path | str,
        base_model: str,
        training_steps: int | None = None,
        final_loss: float | None = None,
        min_loss: float | None = None,
        peak_mem_mib: float | None = None,
    ) -> "CheckpointMetadata":
        """
        Create checkpoint metadata from an adapter directory.

        Args:
            adapter_dir: Path to the adapter directory.
            base_model: Base model identifier.
            training_steps: Number of training steps completed.
            final_loss: Final training loss.
            min_loss: Minimum training loss observed.
            peak_mem_mib: Peak VRAM allocated in MiB.

        Returns:
            CheckpointMetadata with computed hashes.
        """
        ad = Path(adapter_dir)
        now = datetime.now(timezone.utc).isoformat()

        adapter_config_path = ad / "adapter_config.json"
        adapter_model_path = ad / "adapter_model.safetensors"

        config_sha = compute_sha256(adapter_config_path) if adapter_config_path.exists() else None
        model_sha = compute_sha256(adapter_model_path) if adapter_model_path.exists() else None

        # Try to load trainable parameters from adapter_config
        trainable_params = None
        total_params = None
        trainable_percent = None
        if adapter_config_path.exists():
            try:
                with adapter_config_path.open(encoding="utf-8") as f:
                    config = json.load(f)
                # PeftModel stores this in the safetensors index or we can compute from config
                # For now, these are set by the training runner
            except Exception:
                pass

        return cls(
            adapter_path=str(ad),
            base_model=base_model,
            adapter_config_sha256=config_sha,
            adapter_model_sha256=model_sha,
            trainable_parameters=trainable_params,
            total_parameters=total_params,
            trainable_percent=trainable_percent,
            training_steps=training_steps,
            final_loss=final_loss,
            min_loss=min_loss,
            peak_mem_allocated_mib=peak_mem_mib,
            generated_at=now,
        )

    def save(self, path: Path | str) -> None:
        """Save checkpoint metadata to a JSON file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
            f.write("\n")

    @classmethod
    def load(cls, path: Path | str) -> "CheckpointMetadata":
        """Load checkpoint metadata from a JSON file."""
        p = Path(path)
        with p.open(encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)
