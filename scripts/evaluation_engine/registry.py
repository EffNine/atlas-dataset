"""
registry.py — Benchmark registry loader.

Loads and validates the benchmark registry from metadata/benchmark_registry.json.
Provides lookup, listing, and description of registered benchmarks.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class BenchmarkRegistry:
    """Read-only registry of supported evaluation benchmarks.

    Loads benchmark definitions from metadata/benchmark_registry.json.
    Provides listing, lookup, and description accessors.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()
        self._path = self._root / "metadata" / "benchmark_registry.json"
        self._data: dict[str, Any] | None = None

    def load(self) -> dict[str, Any]:
        """Load the benchmark registry from disk.

        Returns:
            The full registry data structure.

        Raises:
            FileNotFoundError: If the registry file does not exist.
            json.JSONDecodeError: If the registry file is not valid JSON.
        """
        if self._data is not None:
            return self._data
        if not self._path.exists():
            raise FileNotFoundError(
                f"Benchmark registry not found: {self._path}"
            )
        raw = self._path.read_text(encoding="utf-8")
        loaded = json.loads(raw)
        if not isinstance(loaded, dict):
            raise ValueError("Benchmark registry root is not a JSON object")
        self._data = loaded
        return loaded

    def list_benchmarks(self) -> list[dict[str, Any]]:
        """List all registered benchmarks with their metadata.

        Returns:
            A list of benchmark metadata dicts.
        """
        data = self.load()
        registry = data.get("registry", {})
        results: list[dict[str, Any]] = []
        for category in ("internal", "external"):
            cat_benchmarks = registry.get(category, {})
            for bm_id, bm in cat_benchmarks.items():
                entry = dict(bm)
                entry["category_group"] = category
                results.append(entry)
        return results

    def get_benchmark(self, benchmark_id: str) -> dict[str, Any] | None:
        """Look up a specific benchmark by ID.

        Args:
            benchmark_id: The unique benchmark identifier.

        Returns:
            Benchmark metadata dict, or None if not found.
        """
        data = self.load()
        registry = data.get("registry", {})
        for category in ("internal", "external"):
            cat_benchmarks = registry.get(category, {})
            if benchmark_id in cat_benchmarks:
                entry = dict(cat_benchmarks[benchmark_id])
                entry["category_group"] = category
                return entry
        return None

    def describe_benchmark(self, benchmark_id: str) -> str:
        """Return a human-readable description of a benchmark.

        Args:
            benchmark_id: The unique benchmark identifier.

        Returns:
            A formatted markdown description string.
        """
        bm = self.get_benchmark(benchmark_id)
        if bm is None:
            return f"**Benchmark '{benchmark_id}'**: Not found."
        lines = [
            f"### {bm.get('benchmark_id', benchmark_id)}",
            f"",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| **Category** | {bm.get('category', '?')} |",
            f"| **Group** | {bm.get('category_group', '?')} |",
            f"| **Purpose** | {bm.get('purpose', '?')} |",
            f"| **Metric** | {bm.get('metric', '?')} |",
            f"| **Split** | {bm.get('split', '?')} |",
            f"| **License** | {bm.get('license', '?')} |",
            f"| **Status** | {bm.get('status', '?')} |",
        ]
        return "\n".join(lines)

    def validate(self) -> list[str]:
        """Validate the registry structure and return any errors.

        Returns:
            A list of validation error messages (empty if valid).
        """
        errors: list[str] = []
        try:
            data = self.load()
        except (FileNotFoundError, json.JSONDecodeError) as e:
            errors.append(str(e))
            return errors

        if not isinstance(data, dict):
            errors.append("Registry root is not a JSON object")
            return errors

        sv = data.get("schema_version")
        if not sv:
            errors.append("Missing schema_version")

        registry = data.get("registry", {})
        if not isinstance(registry, dict):
            errors.append("registry is not a JSON object")
            return errors

        for category in ("internal", "external"):
            cat_benchmarks = registry.get(category, {})
            if not isinstance(cat_benchmarks, dict):
                errors.append(f"registry.{category} is not a JSON object")
                continue
            for bm_id, bm in cat_benchmarks.items():
                if not isinstance(bm, dict):
                    errors.append(f"registry.{category}.{bm_id}: not an object")
                    continue
                required = {"benchmark_id", "category", "purpose", "metric", "status"}
                missing = required - set(bm.keys())
                if missing:
                    errors.append(
                        f"registry.{category}.{bm_id}: missing fields: {missing}"
                    )
        return errors
