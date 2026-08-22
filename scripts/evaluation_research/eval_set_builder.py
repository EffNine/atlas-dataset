"""eval_set_builder.py — Build and manage versioned clean evaluation sets.

Takes acquired benchmark data + contamination audit results and produces
a versioned, immutable eval set under evaluation/eval_sets/production/.

The benchmark is immutable after freeze: no modification of benchmark
questions is permitted. Records removed by contamination are tracked in
a separate manifest.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifacts import sha256_file, sha256_text, canonical_json


@dataclass(frozen=True)
class FrozenEvalSet:
    """A frozen (immutable) evaluation set with full provenance."""

    eval_set_id: str
    path: str
    n_records: int
    sha256: str
    contamination_audit_id: str
    contamination_verdict: str
    n_removed: int
    n_clean: int
    created_at: str
    protocol_version: str = "v2"
    family: str = ""
    source_benchmarks: list[str] = field(default_factory=list)
    manifest_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "eval_set_id": self.eval_set_id,
            "path": self.path,
            "n_records": self.n_records,
            "sha256": self.sha256,
            "contamination_audit_id": self.contamination_audit_id,
            "contamination_verdict": self.contamination_verdict,
            "n_removed": self.n_removed,
            "n_clean": self.n_clean,
            "created_at": self.created_at,
            "protocol_version": self.protocol_version,
            "family": self.family,
            "source_benchmarks": self.source_benchmarks,
            "manifest_path": self.manifest_path,
        }


class EvalSetBuilder:
    """Build and manage versioned clean evaluation sets."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.production_dir = self.root / "evaluation" / "eval_sets" / "production"
        self.production_dir.mkdir(parents=True, exist_ok=True)

    def build_from_audit(
        self,
        eval_set_id: str,
        source_eval_file: Path,
        contamination_result: dict,
        family: str = "",
        source_benchmarks: list[str] | None = None,
    ) -> FrozenEvalSet:
        """Build a frozen eval set from a contamination audit result.

        Records with contamination are excluded from the clean set.
        The original file is NEVER modified; a new clean file is created.
        """
        # Load all records
        all_records = []
        with source_eval_file.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    all_records.append(json.loads(line))

        # Identify contaminated record IDs
        contaminated_ids: set[str] = set()
        per_record = contamination_result.get("per_record", [])
        for rec_result in per_record:
            if rec_result.get("removed"):
                bid = rec_result.get("benchmark_id", "")
                if bid:
                    contaminated_ids.add(bid)

        # Build clean set
        clean_records = [
            r for r in all_records
            if (r.get("record_id") or r.get("original_id", "")) not in contaminated_ids
        ]

        # Write clean eval set
        clean_path = self.production_dir / f"{eval_set_id}_clean.jsonl"
        clean_path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in clean_records) + "\n",
            encoding="utf-8",
        )

        # Write removed records manifest
        removed_path = self.production_dir / f"{eval_set_id}_removed.jsonl"
        removed_records = [
            r for r in all_records
            if (r.get("record_id") or r.get("original_id", "")) in contaminated_ids
        ]
        if removed_records:
            removed_path.write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in removed_records) + "\n",
                encoding="utf-8",
            )

        # Compute checksums
        clean_sha = sha256_file(clean_path)
        removed_sha = sha256_file(removed_path) if removed_path.exists() else ""

        # Write manifest
        manifest = {
            "eval_set_id": eval_set_id,
            "family": family,
            "protocol_version": "v2",
            "source_file": str(source_eval_file),
            "n_total": len(all_records),
            "n_clean": len(clean_records),
            "n_removed": len(removed_records),
            "contamination_audit_id": contamination_result.get("audit_id", ""),
            "contamination_verdict": contamination_result.get("verdict", ""),
            "clean_file": str(clean_path),
            "clean_sha256": clean_sha,
            "removed_file": str(removed_path) if removed_records else None,
            "removed_sha256": removed_sha,
            "source_benchmarks": source_benchmarks or [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        manifest_path = self.production_dir / f"{eval_set_id}_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        return FrozenEvalSet(
            eval_set_id=eval_set_id,
            path=str(clean_path),
            n_records=len(clean_records),
            sha256=clean_sha,
            contamination_audit_id=contamination_result.get("audit_id", ""),
            contamination_verdict=contamination_result.get("verdict", ""),
            n_removed=len(removed_records),
            n_clean=len(clean_records),
            created_at=manifest["created_at"],
            family=family,
            source_benchmarks=source_benchmarks or [],
            manifest_path=str(manifest_path),
        )

    def list_frozen_sets(self) -> list[dict[str, Any]]:
        """List all frozen eval sets in the production directory."""
        sets = []
        for mf in sorted(self.production_dir.glob("*_manifest.json")):
            data = json.loads(mf.read_text(encoding="utf-8"))
            sets.append(data)
        return sets

    def verify_frozen_set(self, eval_set_id: str) -> dict[str, Any]:
        """Verify a frozen eval set's integrity."""
        manifest_path = self.production_dir / f"{eval_set_id}_manifest.json"
        if not manifest_path.exists():
            return {"verified": False, "error": f"manifest not found: {manifest_path}"}

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        clean_path = Path(manifest["clean_file"])
        if not clean_path.exists():
            return {"verified": False, "error": f"clean file missing: {clean_path}"}

        actual_sha = sha256_file(clean_path)
        expected_sha = manifest.get("clean_sha256", "")
        return {
            "verified": actual_sha == expected_sha,
            "eval_set_id": eval_set_id,
            "n_records": manifest.get("n_clean", 0),
            "sha256_expected": expected_sha[:16],
            "sha256_actual": actual_sha[:16],
            "contamination_verdict": manifest.get("contamination_verdict"),
        }
