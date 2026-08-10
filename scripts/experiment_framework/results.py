#!/usr/bin/env python3
"""
results.py — Result registry for experiment outcomes.

Provides the ResultRegistry for storing and querying experiment results,
including aggregate metrics and per-example results.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .metadata import compute_sha256


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class AggregateMetrics:
    """
    Aggregate metrics for an experiment run.

    Mirrors the standard four-metric output used across all experiments:
    correctness, reasoning_quality, hallucination_rate, answer_format_consistency.
    """
    correctness: float | None = None
    reasoning_quality: float | None = None
    hallucination_rate: float | None = None
    answer_format_consistency: float | None = None
    latency_s_mean: float | None = None
    tokens_per_sec_mean: float | None = None
    evaluated_examples: int = 0
    total_examples: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AggregateMetrics":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def compute_from_results(cls, results: list[dict[str, Any]]) -> "AggregateMetrics":
        """Compute aggregate metrics from a list of per-example result dicts."""
        valid = [r for r in results if r.get("correctness") is not None]
        n = len(valid) if valid else 1
        return cls(
            correctness=round(sum(r["correctness"] for r in valid) / n, 4),
            reasoning_quality=round(sum(r["reasoning_quality"] for r in valid) / n, 4),
            hallucination_rate=round(sum(r["hallucination_rate"] for r in valid) / n, 4),
            answer_format_consistency=round(
                sum(r["answer_format_consistency"] for r in valid) / n, 4),
            latency_s_mean=round(sum(r["latency_s"] for r in valid) / n, 4) if valid else None,
            tokens_per_sec_mean=round(sum(r["tokens_per_sec"] for r in valid) / n, 2) if valid else None,
            evaluated_examples=len(valid),
            total_examples=len(results),
        )


@dataclass
class ResultEntry:
    """
    A single result entry combining aggregate metrics and metadata.
    """
    experiment_id: str
    evaluation_id: str
    status: str  # "COMPLETE", "BLOCKED", "HOLD"
    model: str  # "BASE_MODEL" or "LORA_ADAPTER"
    model_id: str
    adapter_path: str | None = None
    hardware: dict[str, Any] | None = None
    aggregate: AggregateMetrics | None = None
    per_example_path: str | None = None
    error: str | None = None
    generated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.aggregate:
            d["aggregate"] = self.aggregate.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResultEntry":
        agg_data = data.get("aggregate")
        if agg_data:
            data["aggregate"] = AggregateMetrics.from_dict(agg_data)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# ResultRegistry
# ---------------------------------------------------------------------------

class ResultRegistry:
    """
    Central registry for experiment results.

    Stores aggregate and per-example results for all experiments,
    enabling comparison across runs and families.
    """

    SCHEMA_VERSION = "1.0"
    REGISTRY_KEY = "experiment_results.json"

    def __init__(self, registry_path: str | Path | None = None):
        self._path = Path(registry_path) if registry_path else None
        self._entries: dict[str, list[ResultEntry]] = {}
        self._loaded = False

    @property
    def path(self) -> Path:
        if self._path is None:
            from ..atlas_paths import metadata_dir
            self._path = metadata_dir() / self.REGISTRY_KEY
        return self._path

    def load(self) -> None:
        """Load the result registry from disk."""
        if not self.path.exists():
            self._entries = {}
            self._loaded = True
            return
        with self.path.open(encoding="utf-8") as f:
            data = json.load(f)
        if data.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError(
                f"Result registry schema version mismatch: expected {self.SCHEMA_VERSION}, "
                f"got {data.get('schema_version')}"
            )
        self._entries = {}
        for exp_id, entries in data.get("results", {}).items():
            self._entries[exp_id] = [
                ResultEntry.from_dict(e) for e in entries
            ]
        self._loaded = True

    def save(self) -> None:
        """Save the result registry to disk."""
        if not self._loaded:
            self.load()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": self.SCHEMA_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "result_count": sum(len(entries) for entries in self._entries.values()),
            "results": {
                exp_id: [e.to_dict() for e in entries]
                for exp_id, entries in self._entries.items()
            },
        }
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")

    def add(self, entry: ResultEntry) -> None:
        """Add a result entry to the registry."""
        if not self._loaded:
            self.load()
        exp_id = entry.experiment_id
        if exp_id not in self._entries:
            self._entries[exp_id] = []
        self._entries[exp_id].append(entry)
        self.save()

    def get(self, experiment_id: str) -> list[ResultEntry]:
        """Get all result entries for an experiment."""
        if not self._loaded:
            self.load()
        return self._entries.get(experiment_id, [])

    def get_latest(self, experiment_id: str) -> ResultEntry | None:
        """Get the most recent result entry for an experiment."""
        entries = self.get(experiment_id)
        return entries[-1] if entries else None

    def list_by_status(self, status: str) -> list[tuple[str, ResultEntry]]:
        """List all result entries with the given status."""
        if not self._loaded:
            self.load()
        result = []
        for exp_id, entries in self._entries.items():
            for entry in entries:
                if entry.status == status:
                    result.append((exp_id, entry))
        return result

    def list_complete(self) -> list[tuple[str, ResultEntry]]:
        """List all completed result entries."""
        return self.list_by_status("COMPLETE")

    def list_holds(self) -> list[tuple[str, ResultEntry]]:
        """List all HOLD result entries."""
        return self.list_by_status("HOLD")

    def list_blocked(self) -> list[tuple[str, ResultEntry]]:
        """List all BLOCKED result entries."""
        return self.list_by_status("BLOCKED")

    def compare(
        self,
        baseline_exp_id: str,
        experimental_exp_id: str,
        metric: str = "correctness",
    ) -> dict[str, Any] | None:
        """
        Compare baseline and experimental results for a given metric.

        Args:
            baseline_exp_id: ID of the baseline experiment.
            experimental_exp_id: ID of the experimental run.
            metric: Metric to compare (default: "correctness").

        Returns:
            Comparison dict with baseline, experimental, and delta values,
            or None if either experiment has no results.
        """
        baseline_entries = self.get(baseline_exp_id)
        experimental_entries = self.get(experimental_exp_id)
        if not baseline_entries or not experimental_entries:
            return None

        baseline = baseline_entries[-1]
        experimental = experimental_entries[-1]

        if not baseline.aggregate or not experimental.aggregate:
            return None

        b_val = getattr(baseline.aggregate, metric)
        e_val = getattr(experimental.aggregate, metric)

        if b_val is None or e_val is None:
            return None

        return {
            "baseline_experiment": baseline_exp_id,
            "experimental_experiment": experimental_exp_id,
            "metric": metric,
            "baseline_value": b_val,
            "experimental_value": e_val,
            "delta": round(e_val - b_val, 4),
        }

    def __len__(self) -> int:
        if not self._loaded:
            self.load()
        return sum(len(entries) for entries in self._entries.values())

    def summary(self) -> dict[str, Any]:
        """Return a summary of the result registry."""
        if not self._loaded:
            self.load()
        status_counts: dict[str, int] = {}
        for entries in self._entries.values():
            for entry in entries:
                status_counts[entry.status] = status_counts.get(entry.status, 0) + 1
        return {
            "schema_version": self.SCHEMA_VERSION,
            "total_entries": len(self),
            "experiments": len(self._entries),
            "by_status": status_counts,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
