#!/usr/bin/env python3
"""
registry.py — Benchmark run registry for the EffNine Benchmark (EB).

Persists benchmark run history and baseline records to disk using atomic
writes to prevent corruption. Each EB instance maintains its own registry
separate from Atlas's experiment registry.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema import BaselineRecord, BenchmarkRun


class BenchmarkRegistry:
    """
    Central registry for EB benchmark runs and baselines.

    Persists to metadata/benchmark_registry.json within the EB root directory.
    Uses atomic writes (write to temp file, then rename) to prevent corruption.
    """

    SCHEMA_VERSION = "1.0"
    REGISTRY_KEY = "benchmark_registry.json"

    def __init__(self, registry_path: Path | str | None = None) -> None:
        self._path: Path | None = Path(registry_path) if registry_path else None
        self._runs: dict[str, dict[str, Any]] = {}
        self._baselines: dict[str, BaselineRecord] = {}
        self._registered_baselines: dict[str, str] = {}
        self._loaded = False

    @property
    def path(self) -> Path:
        if self._path is None:
            from ..paths import metadata_dir
            self._path = metadata_dir() / self.REGISTRY_KEY
        return self._path

    def load(self) -> None:
        """Load the registry from disk."""
        if not self.path.exists():
            self._runs = {}
            self._baselines = {}
            self._loaded = True
            return
        with self.path.open(encoding="utf-8") as f:
            data = json.load(f)
        if data.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError(
                f"Registry schema version mismatch: expected {self.SCHEMA_VERSION}, "
                f"got {data.get('schema_version')}"
            )
        self._runs = {r["run_id"]: r for r in data.get("runs", [])}
        self._baselines = {
            key: BaselineRecord(**val) for key, val in data.get("baselines", {}).items()
        }
        self._loaded = True

    def save(self) -> None:
        """Save the registry to disk using an atomic write."""
        if not self._loaded:
            self.load()
        self.path.parent.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {
            "schema_version": self.SCHEMA_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "run_count": len(self._runs),
            "baseline_count": len(self._baselines),
            "runs": list(self._runs.values()),
            "baselines": {
                key: val.model_dump() if isinstance(val, BaselineRecord) else val
                for key, val in self._baselines.items()
            },
        }

        content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"

        # Atomic write: write to temp file in same directory, then rename
        dir_path = self.path.parent
        fd, tmp_path = tempfile.mkstemp(suffix=".tmp", dir=str(dir_path))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, str(self.path))
        except Exception:
            # Clean up temp file on failure
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def create_run(self, run: BenchmarkRun) -> None:
        """Persist a benchmark run record."""
        if not self._loaded:
            self.load()
        self._runs[run.run_id] = run.to_dict()
        self.save()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Retrieve a benchmark run by ID."""
        if not self._loaded:
            self.load()
        return self._runs.get(run_id)

    def list_runs(self, *, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        """List all benchmark runs, optionally paginated."""
        if not self._loaded:
            self.load()
        runs = list(self._runs.values())
        runs.sort(key=lambda r: r.get("generated_at", ""), reverse=True)
        if limit is not None:
            return runs[offset : offset + limit]
        return runs[offset:]

    def set_baseline(
        self,
        record: BaselineRecord,
        *,
        as_registered: bool = False,
    ) -> None:
        """Set or update a baseline record.

        Parameters
        ----------
        record : BaselineRecord
            The baseline to register.
        as_registered : bool
            If True, also store the run_id → baseline mapping for resolution.
        """
        if not self._loaded:
            self.load()
        key = self._baseline_key(record.base_model_name, record.benchmark_version)
        self._baselines[key] = record
        if as_registered:
            self._registered_baselines[record.baseline_run_id] = key
        self.save()

    def get_baseline(
        self,
        base_model_name: str | None = None,
        benchmark_version: str | None = None,
        run_id: str | None = None,
    ) -> BaselineRecord | None:
        """Retrieve a baseline record.

        Parameters
        ----------
        base_model_name : str, optional
            Name of the base model.
        benchmark_version : str, optional
            Benchmark version.
        run_id : str, optional
            Baseline run ID to look up directly.

        Returns
        -------
        BaselineRecord or None.
        """
        if not self._loaded:
            self.load()

        # Direct run_id lookup
        if run_id is not None:
            mapped_key = self._registered_baselines.get(run_id)
            if mapped_key:
                return self._baselines.get(mapped_key)
            # Also try direct match on baseline_run_id field
            for key, bl in self._baselines.items():
                if bl.baseline_run_id == run_id:
                    return bl

        # Key-based lookup
        if base_model_name and benchmark_version:
            key = self._baseline_key(base_model_name, benchmark_version)
            return self._baselines.get(key)

        return None

    def resolve_baseline_for_run(
        self,
        run: "BenchmarkRun",  # type: ignore[name-defined]
    ) -> BaselineRecord | None:
        """Resolve the best baseline for a given BenchmarkRun.

        Priority:
            1. Explicit --baseline-run matching run.baseline_run_id
            2. Registered baseline matching exact lineage
            3. None (fail clearly)
        """
        if not self._loaded:
            self.load()

        from ..scoring.normalization import resolve_baseline as _resolve

        # 1. Check for explicit baseline_run_id
        if run.baseline_run_id:
            explicit = self.get_baseline(run_id=run.baseline_run_id)
            if explicit is not None:
                return explicit

        # 2. Search by model lineage
        all_baselines = list(self._baselines.values())
        return _resolve(run, all_baselines)

    def list_baselines(self) -> list[tuple[str, BaselineRecord]]:
        """List all baseline records."""
        if not self._loaded:
            self.load()
        return list(self._baselines.items())

    @staticmethod
    def _baseline_key(base_model_name: str, benchmark_version: str) -> str:
        return f"{base_model_name}::{benchmark_version}"

    def summary(self) -> dict[str, Any]:
        """Return a summary of the registry state."""
        if not self._loaded:
            self.load()
        return {
            "schema_version": self.SCHEMA_VERSION,
            "total_runs": len(self._runs),
            "total_baselines": len(self._baselines),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }