"""
engine.py — Evaluation orchestration.

Provides the top-level EvaluationOrchestrator that coordinates
benchmark listing, metric description, and dry-run evaluation.
"""

from __future__ import annotations

import hashlib
import json
import socket
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .metrics import MetricRegistry
from .registry import BenchmarkRegistry
from .report import EvaluationReport


class NetworkBlocked(RuntimeError):
    """Raised when evaluation code attempts network access."""
    pass


def install_network_block() -> None:
    """Monkey-patch socket and urllib to block network access."""
    sock_init = socket.socket.__init__

    def _blocked_init(self, *a: Any, **k: Any) -> None:
        raise NetworkBlocked("network access is forbidden during evaluation")

    socket.socket.__init__ = _blocked_init  # type: ignore[assignment]

    def _blocked_urlopen(*a: Any, **k: Any) -> None:
        raise NetworkBlocked("network access is forbidden during evaluation")

    urllib.request.urlopen = _blocked_urlopen  # type: ignore[assignment]


class EvaluationOrchestrator:
    """Top-level evaluation orchestrator.

    Coordinates benchmark registry loading, metric execution,
    and report generation. All operations are read-only and
    deterministic.
    """

    def __init__(self, root: str | Path, network_block: bool = True) -> None:
        self._root = Path(root).resolve()
        self._benchmark_registry = BenchmarkRegistry(self._root)
        self._metric_registry = MetricRegistry()
        self._report = EvaluationReport(self._root)
        if network_block:
            install_network_block()

    # ------------------------------------------------------------------
    # Benchmark operations (read-only)
    # ------------------------------------------------------------------

    def list_benchmarks(self) -> list[dict[str, Any]]:
        """List all registered benchmarks.

        Returns:
            A list of benchmark metadata dicts.
        """
        return self._benchmark_registry.list_benchmarks()

    def describe_benchmark(self, benchmark_id: str) -> str:
        """Return a human-readable description of a benchmark.

        Args:
            benchmark_id: The unique benchmark identifier.

        Returns:
            A formatted markdown description.
        """
        return self._benchmark_registry.describe_benchmark(benchmark_id)

    def get_benchmark(self, benchmark_id: str) -> dict[str, Any] | None:
        """Look up a benchmark by ID.

        Args:
            benchmark_id: The unique benchmark identifier.

        Returns:
            Benchmark metadata dict, or None.
        """
        return self._benchmark_registry.get_benchmark(benchmark_id)

    # ------------------------------------------------------------------
    # Metric operations (read-only)
    # ------------------------------------------------------------------

    def list_metrics(self) -> list[dict[str, str]]:
        """List all registered metrics.

        Returns:
            A list of metric metadata dicts.
        """
        return self._metric_registry.list_metrics()

    def get_metric(self, metric_id: str) -> Any | None:
        """Retrieve a metric by ID.

        Args:
            metric_id: The metric identifier.

        Returns:
            The metric instance, or None.
        """
        return self._metric_registry.get(metric_id)

    # ------------------------------------------------------------------
    # Dry-run — evaluate without executing against real data
    # ------------------------------------------------------------------

    def dry_run(self) -> dict[str, Any]:
        """Run a dry-run evaluation: list benchmarks and metrics,
        produce a placeholder report, but do NOT execute against
        any curated data.

        Returns:
            A dict describing the dry-run outcome.
        """
        benchmarks = self.list_benchmarks()
        metrics = self.list_metrics()

        # Compute a reproducibility hash for the dry-run configuration
        config = {
            "benchmarks": [b["benchmark_id"] for b in benchmarks],
            "metrics": [m["metric_id"] for m in metrics],
            "mode": "dry-run",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        config_json = json.dumps(config, sort_keys=True, ensure_ascii=False)
        reproducibility_hash = hashlib.sha256(
            config_json.encode("utf-8")
        ).hexdigest()

        # Build a placeholder report
        dry_metrics = [
            {
                "metric_id": m["metric_id"],
                "name": m["name"],
                "value": None,
                "status": "dry-run",
                "message": "Dry-run mode — no actual evaluation executed.",
            }
            for m in metrics
        ]

        result = {
            "status": "dry-run",
            "mode": "dry-run",
            "benchmarks_available": len(benchmarks),
            "benchmarks": benchmarks,
            "metrics_available": len(metrics),
            "metrics": dry_metrics,
            "reproducibility_hash": reproducibility_hash,
            "message": (
                "Dry-run completed. No actual evaluation executed. "
                "Use --dry-run during development to verify infrastructure."
            ),
        }
        return result

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_registry(self) -> list[str]:
        """Validate the benchmark registry structure.

        Returns:
            A list of validation errors (empty if valid).
        """
        return self._benchmark_registry.validate()

    def validate_metrics(self) -> list[str]:
        """Validate that all metrics have required implementations.

        Returns:
            A list of validation errors (empty if valid).
        """
        errors: list[str] = []
        for m in self._metric_registry.list_metrics():
            mid = m["metric_id"]
            instance = self._metric_registry.get(mid)
            if instance is None:
                errors.append(f"Metric '{mid}' registered but not instantiated")
        return errors
