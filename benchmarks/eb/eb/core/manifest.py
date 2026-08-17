#!/usr/bin/env python3
"""
manifest.py — Benchmark run manifest for the EffNine Benchmark (EB).

Produces a reproducible manifest record for each benchmark run, capturing
the benchmark version, task-set hash, selected partitions, inference
configuration, and environment metadata.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .schema import InferenceSettings, ModelMetadata


def compute_sha256(path: Path | str) -> str:
    """Compute SHA-256 hash of a file."""
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_records_sha256(jsonl_path: Path | str) -> str:
    """Compute SHA-256 of sorted, serialized JSON records (canonical checksum)."""
    import hashlib as _hl
    p = Path(jsonl_path)
    records = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    records.sort(key=lambda r: str(r.get("id") or r.get("task_id", "")))
    canonical = "\n".join(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in records)
    h = _hl.sha256()
    h.update(canonical.encode("utf-8"))
    return h.hexdigest()


def git_info(repo_path: Path | str | None = None) -> dict[str, str | None]:
    """Collect git repository information."""
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
    status_output = _run(["git", "status", "--porcelain"])
    is_clean = status_output is None or status_output == ""

    return {
        "git_commit": commit,
        "git_short": short,
        "git_branch": branch,
        "git_status_clean": "true" if is_clean else "false",
    }


def hardware_info() -> dict[str, Any]:
    """Collect hardware and software version information."""
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
        info["python_version"] = sys.version.split()[0]
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
# Manifest schema
# ---------------------------------------------------------------------------


class TaskSetManifest(BaseModel):
    """Manifest for a task set (collection of tasks)."""

    task_set_version: str
    task_dir: str
    n_tasks: int = 0
    raw_sha256: str | None = None
    records_sha256: str | None = None
    partitions: dict[str, int] = Field(default_factory=dict)
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def compute_from_dir(self, task_dir: Path) -> None:
        """Compute checksums by scanning task JSON files in the directory."""
        tasks = list(task_dir.rglob("task.json"))
        self.n_tasks = len(tasks)
        if not tasks:
            return

        all_records = []
        partition_counts: dict[str, int] = {}
        for task_file in sorted(tasks):
            with task_file.open(encoding="utf-8") as f:
                data = json.load(f)
            all_records.append(data)
            part = data.get("partition", "development")
            partition_counts[part] = partition_counts.get(part, 0) + 1

        self.partitions = partition_counts
        # Compute raw hash of concatenated sorted task files
        raw_parts = []
        for task_file in sorted(tasks):
            raw_parts.append(task_file.read_bytes())
        combined = b"".join(raw_parts)
        self.raw_sha256 = hashlib.sha256(combined).hexdigest()

        # Compute canonical records hash
        records_sorted = sorted(all_records, key=lambda r: r.get("id", ""))
        canonical = "\n".join(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in records_sorted)
        self.records_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class BenchmarkRunManifest(BaseModel):
    """
    Complete manifest for a benchmark run.

    Records all parameters needed to reproduce or audit a benchmark execution.
    """

    run_id: str
    benchmark_version: str
    task_set_manifest: TaskSetManifest
    model: ModelMetadata
    base_model: ModelMetadata
    baseline_run_id: str | None = None
    suite: str
    partitions: list[str] = Field(default_factory=list)
    inference: InferenceSettings
    environment: dict[str, Any] = Field(default_factory=dict)
    judge: dict[str, Any] | None = None
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    git_commit: str | None = None
    manifest_sha256: str | None = None

    # Reproducibility metadata (Stage 8F)
    evaluator_config_version: str | None = None
    sandbox_backend: str | None = None
    sandbox_image: str | None = None
    rubric_version: str | None = None
    long_max_concurrent: int | None = None

    def compute_sha256(self) -> str:
        """Compute SHA-256 of the manifest content (excluding the sha256 field itself)."""
        payload = self.model_dump(exclude={"manifest_sha256"})
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        self.manifest_sha256 = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return self.manifest_sha256

    def to_dict(self) -> dict[str, Any]:
        d = self.model_dump()
        d["task_set_manifest"] = self.task_set_manifest.model_dump()
        return d

    @classmethod
    def create(
        cls,
        run_id: str,
        benchmark_version: str,
        task_set_version: str,
        task_dir: Path,
        model: ModelMetadata,
        base_model: ModelMetadata,
        suite: str,
        partitions: list[str],
        inference: InferenceSettings,
        git_commit: str | None = None,
        judge: dict[str, Any] | None = None,
        evaluator_config_version: str | None = None,
        sandbox_backend: str | None = None,
        sandbox_image: str | None = None,
        rubric_version: str | None = None,
        long_max_concurrent: int | None = None,
    ) -> BenchmarkRunManifest:
        """Create a manifest from run parameters, computing task-set checksums."""
        task_manifest = TaskSetManifest(task_set_version=task_set_version, task_dir=str(task_dir))
        task_manifest.compute_from_dir(task_dir)

        env = hardware_info()
        git = git_info() if git_commit is None else {"git_commit": git_commit, "git_short": git_commit[:8], "git_status_clean": "true", "git_branch": "unknown"}

        manifest = cls(
            run_id=run_id,
            benchmark_version=benchmark_version,
            task_set_manifest=task_manifest,
            model=model,
            base_model=base_model,
            baseline_run_id=None,
            suite=suite,
            partitions=partitions,
            inference=inference,
            environment=env,
            judge=judge,
            git_commit=git.get("git_commit"),
            evaluator_config_version=evaluator_config_version,
            sandbox_backend=sandbox_backend,
            sandbox_image=sandbox_image,
            rubric_version=rubric_version,
            long_max_concurrent=long_max_concurrent,
        )
        manifest.compute_sha256()
        return manifest