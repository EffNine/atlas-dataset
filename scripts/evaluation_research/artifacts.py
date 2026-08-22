"""artifacts.py — Artifact integrity and provenance tracking.

Provides deterministic checksum verification for all research artifacts:
eval sets, calibration reports, contamination manifests, and per-example
outputs. Fail-closed on checksum mismatch.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    """Compute SHA-256 hex digest of a UTF-8 string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(obj: Any) -> str:
    """Deterministic JSON serialization (sorted keys, no extra whitespace)."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class ArtifactManifest:
    """Checksummed manifest for a single artifact file."""

    path: str
    sha256: str
    size_bytes: int
    artifact_type: str  # "eval_set", "calibration_report", "contamination_manifest", ...
    created_at: str
    version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "artifact_type": self.artifact_type,
            "created_at": self.created_at,
            "version": self.version,
        }


@dataclass(frozen=True)
class ArtifactIntegrity:
    """Integrity report for a set of artifacts."""

    artifacts: tuple[ArtifactManifest, ...] = field(default_factory=tuple)
    all_verified: bool = True
    mismatches: list[dict[str, str]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    computed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "all_verified": self.all_verified,
            "n_artifacts": len(self.artifacts),
            "mismatches": self.mismatches,
            "missing": self.missing,
            "computed_at": self.computed_at,
            "artifacts": [a.to_dict() for a in self.artifacts],
        }


class ArtifactVerifier:
    """Verify integrity of research artifacts by re-computing checksums."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def verify_file(self, rel_path: str, expected_sha256: str) -> tuple[bool, str]:
        """Verify a single file's SHA-256 against an expected value.

        Returns (verified, actual_sha256).
        """
        full_path = self.root / rel_path
        if not full_path.exists():
            return False, ""
        actual = sha256_file(full_path)
        return actual == expected_sha256, actual

    def verify_eval_set(self, eval_set_path: Path, expected_sha256: str | None = None) -> dict:
        """Verify an eval set file and return its manifest."""
        if not eval_set_path.exists():
            return {"verified": False, "error": f"missing: {eval_set_path}"}
        actual_sha = sha256_file(eval_set_path)
        size = eval_set_path.stat().st_size
        manifest = ArtifactManifest(
            path=str(eval_set_path.relative_to(self.root)),
            sha256=actual_sha,
            size_bytes=size,
            artifact_type="eval_set",
            created_at="",
        )
        verified = expected_sha256 is None or actual_sha == expected_sha256
        return {
            "verified": verified,
            "expected_sha256": expected_sha256,
            "actual_sha256": actual_sha,
            "size_bytes": size,
            "manifest": manifest.to_dict(),
        }

    def verify_jsonl(self, path: Path) -> dict:
        """Parse and checksum a JSONL file; count records."""
        records = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        sha = sha256_text(canonical_json(records))
        return {
            "path": str(path),
            "record_count": len(records),
            "records_sha256": sha,
            "file_sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }

    def verify_experiment_dir(self, exp_dir: Path) -> dict:
        """Verify all expected artifacts in an experiment directory."""
        expected = {
            "run_metadata.json": None,
            "config.json": None,
        }
        results: dict[str, dict] = {}
        for name, expected_sha in expected.items():
            p = exp_dir / name
            if p.exists():
                results[name] = {
                    "exists": True,
                    "sha256": sha256_file(p),
                    "size_bytes": p.stat().st_size,
                }
            else:
                results[name] = {"exists": False, "sha256": None}
        return results
