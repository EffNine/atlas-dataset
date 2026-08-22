"""benchmark_discover.py — Benchmark discovery and metadata collection.

Discovers external benchmarks (GSM8K, MATH, etc.) from known sources,
validates license compatibility, checks provenance, and estimates
evaluation dataset size.

Does NOT download data — only collects metadata.
Actual acquisition is handled by benchmark_acquire.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas_constants import is_denied_license


@dataclass(frozen=True)
class BenchmarkDiscovery:
    """Metadata collected about a discovered benchmark."""

    benchmark_id: str
    name: str
    source_url: str
    license: str
    license_compatible: bool
    family: str  # math, code, semantic, mixed
    estimated_n_records: int | None
    canonical_answer_available: bool
    split: str
    status: str  # discovered | validated | rejected
    provenance_notes: str = ""
    contamination_risk: str = "unknown"  # low | medium | high | unknown
    discovered_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "name": self.name,
            "source_url": self.source_url,
            "license": self.license,
            "license_compatible": self.license_compatible,
            "family": self.family,
            "estimated_n_records": self.estimated_n_records,
            "canonical_answer_available": self.canonical_answer_available,
            "split": self.split,
            "status": self.status,
            "provenance_notes": self.provenance_notes,
            "contamination_risk": self.contamination_risk,
            "discovered_at": self.discovered_at,
            "metadata": self.metadata,
        }


# Known benchmark specifications (discovery hints)
KNOWN_BENCHMARKS: dict[str, dict[str, Any]] = {
    "gsm8k": {
        "name": "GSM8K",
        "source_url": "https://huggingface.co/datasets/openai/gsm8k",
        "license": "MIT",
        "family": "math",
        "canonical_answer_available": True,
        "split": "test",
        "estimated_n_records": 1319,
        "contamination_risk": "medium",
        "notes": "Grade School Math 8K — arithmetic reasoning with chain-of-thought. "
                 "Well-known benchmark; moderate contamination risk with math training data.",
    },
    "math": {
        "name": "MATH",
        "source_url": "https://huggingface.co/datasets/ HuggingFaceH4/MATH",
        "license": "MIT",
        "family": "math",
        "canonical_answer_available": True,
        "split": "test",
        "estimated_n_records": 5000,
        "contamination_risk": "high",
        "notes": "MATH benchmark — competition-level math problems. "
                 "High contamination risk: widely used in LLM training.",
    },
}


def discover_benchmark(
    benchmark_id: str,
    root: Path | None = None,
) -> BenchmarkDiscovery:
    """Discover a benchmark by ID using known specifications.

    Returns a BenchmarkDiscovery with license check and metadata.
    Does NOT download any data.
    """
    if root is None:
        root = Path(__file__).resolve().parent.parent
    registry_path = root / "metadata" / "benchmark_registry.json"

    # Check registry first
    existing = None
    if registry_path.exists():
        reg = json.loads(registry_path.read_text(encoding="utf-8"))
        reg_data = reg.get("registry", {})
        for cat in ("internal", "external"):
            if benchmark_id in reg_data.get(cat, {}):
                existing = reg_data[cat][benchmark_id]
                break

    # Fall back to known benchmarks
    spec = KNOWN_BENCHMARKS.get(benchmark_id, {})
    if existing:
        spec = {**spec, **{k: v for k, v in existing.items() if k not in spec}}

    license_str = spec.get("license", "unknown")
    license_ok = is_denied_license(license_str) if license_str else True
    license_ok = not license_ok  # is_denied_license returns True for bad licenses

    return BenchmarkDiscovery(
        benchmark_id=benchmark_id,
        name=spec.get("name", benchmark_id),
        source_url=spec.get("source_url", ""),
        license=license_str,
        license_compatible=license_ok,
        family=spec.get("family", "mixed"),
        estimated_n_records=spec.get("estimated_n_records"),
        canonical_answer_available=spec.get("canonical_answer_available", False),
        split=spec.get("split", "test"),
        status="discovered" if license_ok else "rejected",
        provenance_notes=spec.get("notes", ""),
        contamination_risk=spec.get("contamination_risk", "unknown"),
        discovered_at=datetime.now(timezone.utc).isoformat(),
        metadata=spec,
    )


def discover_all(root: Path | None = None) -> list[BenchmarkDiscovery]:
    """Discover all known benchmarks."""
    results = []
    for bid in KNOWN_BENCHMARKS:
        results.append(discover_benchmark(bid, root))
    return results


def register_benchmark(root: Path, discovery: BenchmarkDiscovery) -> None:
    """Update the benchmark registry with a discovered benchmark."""
    registry_path = root / "metadata" / "benchmark_registry.json"
    if not registry_path.exists():
        raise FileNotFoundError(f"benchmark registry not found: {registry_path}")

    data = json.loads(registry_path.read_text(encoding="utf-8"))
    registry = data.get("registry", {})
    external = registry.get("external", {})

    external[discovery.benchmark_id] = {
        "benchmark_id": discovery.benchmark_id,
        "category": "external",
        "purpose": discovery.provenance_notes,
        "metric": "exact_match" if discovery.family == "math" else "accuracy",
        "split": discovery.split,
        "license": discovery.license,
        "status": discovery.status,
        "source_url": discovery.source_url,
        "family": discovery.family,
        "estimated_n_records": discovery.estimated_n_records,
        "canonical_answer_available": discovery.canonical_answer_available,
        "contamination_risk": discovery.contamination_risk,
        "registered_at": discovery.discovered_at,
    }

    data["registry"]["external"] = external
    data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    registry_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
