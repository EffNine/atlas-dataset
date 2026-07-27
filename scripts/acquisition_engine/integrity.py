#!/usr/bin/env python3
"""
integrity.py — Atlas Acquisition Engine integrity verification.

Provides checksum computation, verification, tamper-evident logging,
and per-stage integrity checks. Every pipeline stage computes and records
checksums so tampering or corruption is detectable on subsequent runs.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Checksum utilities
# ---------------------------------------------------------------------------

def file_sha256(path: str | Path) -> str:
    """Compute sha256 of a file's content."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def dict_sha256(data: dict) -> str:
    """Compute sha256 of a dict (sorted keys, JSON-encoded)."""
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def text_sha256(text: str) -> str:
    """Compute sha256 of a string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_file_checksums(
    directory: str | Path,
    pattern: str = "*.jsonl",
    recursive: bool = False,
) -> dict[str, str]:
    """Compute sha256 for every matching file in a directory."""
    directory = Path(directory)
    if not directory.exists():
        return {}
    checksums: dict[str, str] = {}
    glob_fn = directory.rglob if recursive else directory.glob
    for p in sorted(glob_fn(pattern)):
        if p.is_file():
            rel = p.relative_to(directory)
            checksums[str(rel)] = file_sha256(p)
    return checksums


# ---------------------------------------------------------------------------
# Tamper-evident verification log
# ---------------------------------------------------------------------------

class VerificationLog:
    """
    An append-only, tamper-evident log of verification events.

    Each entry is cryptographically chained to the previous entry via the
    `previous_hash` field, forming a hash chain. Any modification of a past
    entry breaks the chain and is detectable.
    """

    def __init__(self, log_path: str | Path):
        self.path = Path(log_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: list[dict[str, Any]] = []
        self._last_hash: str = ""
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._entries = []
            self._last_hash = ""
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._entries = raw.get("entries", [])
            if self._entries:
                self._last_hash = self._entries[-1].get("hash", "")
            else:
                self._last_hash = raw.get("genesis_hash", "")
        except (json.JSONDecodeError, KeyError):
            self._entries = []
            self._last_hash = ""

    def verify_chain(self) -> bool:
        """Verify the entire hash chain is intact."""
        if not self._entries:
            return True
        prev_hash = ""
        for entry in self._entries:
            expected = entry.get("previous_hash", "")
            if expected != prev_hash:
                return False
            # Recompute this entry's hash
            entry_copy = dict(entry)
            entry_copy.pop("hash", None)
            computed = text_sha256(
                json.dumps(entry_copy, sort_keys=True, ensure_ascii=False)
            )
            if entry.get("hash") != computed:
                return False
            prev_hash = computed
        return True

    def append(
        self,
        event: str,
        stage: str,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append a new verification event to the log."""
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "stage": stage,
            "status": status,
            "previous_hash": self._last_hash,
        }
        if details:
            entry["details"] = details

        entry["hash"] = text_sha256(
            json.dumps(entry, sort_keys=True, ensure_ascii=False)
        )
        self._entries.append(entry)
        self._last_hash = entry["hash"]
        self._flush()
        return entry

    def _flush(self) -> None:
        data = {
            "genesis_hash": self._entries[0]["hash"] if self._entries else "",
            "log_version": "1.0",
            "entries": self._entries,
        }
        self.path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @property
    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries)

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def last_entry(self) -> dict[str, Any] | None:
        return self._entries[-1] if self._entries else None


# ---------------------------------------------------------------------------
# Checksum registry (for dataset versions)
# ---------------------------------------------------------------------------

class ChecksumRegistry:
    """
    Manages a registry of file checksums for a dataset version.

    Format:
    {
      "version": "v0.1",
      "generated": "2026-07-27T...",
      "algorithm": "sha256",
      "files": {
        "curated/v0.1/atlas_v0.1.jsonl": "<sha256>",
        "curated/v0.1/pilot_candidates.jsonl": "<sha256>",
        ...
      },
      "summary": { "total_files": N, "total_checksums": N },
      "checksum": "<sha256-of-above-fields>"
    }
    """

    def __init__(self, registry_path: str | Path):
        self.path = Path(registry_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        version: str,
        file_checksums: dict[str, str],
    ) -> dict[str, Any]:
        """Create a new checksum registry."""
        summary = {
            "total_files": len(file_checksums),
            "total_checksums": len(file_checksums),
        }
        data: dict[str, Any] = {
            "version": version,
            "generated": datetime.now(timezone.utc).isoformat(),
            "algorithm": "sha256",
            "files": dict(sorted(file_checksums.items())),
            "summary": summary,
        }
        data["checksum"] = dict_sha256(
            {k: v for k, v in data.items() if k != "checksum"}
        )
        self.path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return data

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def verify(self) -> dict[str, Any]:
        """
        Verify every file in the registry matches its stored checksum.
        Returns { "verified": bool, "mismatches": list[str], "missing": list[str] }.

        Handles both dict format (`{"file": "sha256", ...}`) and list format
        (`[{"path": "...", "sha256": "..."}, ...]`) for the files field.
        """
        data = self.load()
        if data is None:
            return {"verified": False, "mismatches": [], "missing": [], "error": "No registry"}

        stored_raw = data.get("files", {})
        # Normalize to dict format
        if isinstance(stored_raw, list):
            stored = {entry["path"]: entry["sha256"] for entry in stored_raw
                      if "path" in entry and "sha256" in entry}
        elif isinstance(stored_raw, dict):
            stored = stored_raw
        else:
            return {"verified": False, "mismatches": [], "missing": [],
                    "error": f"Unexpected files format: {type(stored_raw).__name__}"}
        mismatches: list[str] = []
        missing: list[str] = []

        root_dir = self.path.parent.parent  # metadata/ -> repo root
        for rel_path, expected_checksum in stored.items():
            abs_path = root_dir / rel_path
            # Engine format stores paths relative to the collected directory
            # (e.g., "pilot_candidates.jsonl" relative to curated/v0.1/)
            if not abs_path.exists():
                alt_path = root_dir / "curated" / data.get("version", "") / rel_path
                if alt_path.exists():
                    abs_path = alt_path
                else:
                    missing.append(rel_path)
                    continue
            actual = file_sha256(abs_path)
            if actual != expected_checksum:
                mismatches.append(rel_path)

        return {
            "verified": len(mismatches) == 0 and len(missing) == 0,
            "mismatches": mismatches,
            "missing": missing,
            "total_checked": len(stored),
        }

    @staticmethod
    def diff_registries(
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Diff two checksum registries to find changed files."""

        def _normalize_files(data: dict | None) -> dict[str, str]:
            """Convert registry files field to dict format regardless of input shape."""
            if data is None:
                return {}
            raw = data.get("files", {})
            if isinstance(raw, list):
                return {entry["path"]: entry["sha256"] for entry in raw
                        if "path" in entry and "sha256" in entry}
            if isinstance(raw, dict):
                return raw
            return {}

        before_files = _normalize_files(before)
        after_files = _normalize_files(after)

        before_set = set(before_files.keys())
        after_set = set(after_files.keys())

        added = sorted(after_set - before_set)
        removed = sorted(before_set - after_set)
        common = before_set & after_set

        changed: list[str] = []
        unchanged = 0
        for f in sorted(common):
            if before_files[f] != after_files[f]:
                changed.append(f)
            else:
                unchanged += 1

        return {
            "changed": changed,
            "added": added,
            "removed": removed,
            "unchanged": unchanged,
        }


# ---------------------------------------------------------------------------
# Stage verification helpers
# ---------------------------------------------------------------------------

def verify_stage_integrity(
    stage: str,
    input_paths: list[Path],
    output_paths: list[Path],
    ver_log: VerificationLog,
) -> dict[str, Any]:
    """
    Verify that stage outputs are consistent with inputs.
    Checks: output files exist, input files unchanged, record counts sane.
    Returns { "passed": bool, "checks": dict }.
    """
    checks: dict[str, Any] = {}
    all_pass = True

    # Input files exist check
    for p in input_paths:
        exists = p.exists()
        checks[f"input_exists:{p.name}"] = exists
        if not exists:
            all_pass = False

    # Output files exist and non-empty
    for p in output_paths:
        exists = p.exists() and p.stat().st_size > 0
        checks[f"output_valid:{p.name}"] = exists
        if not exists:
            all_pass = False

    # Compute input checksums for tracing
    input_checksums = {}
    for p in input_paths:
        if p.exists():
            input_checksums[p.name] = file_sha256(p)

    event = ver_log.append(
        event="stage_verification",
        stage=stage,
        status="passed" if all_pass else "failed",
        details={
            "checks": checks,
            "input_checksums": input_checksums,
            "input_count": len(input_paths),
            "output_count": len(output_paths),
        },
    )

    return {"passed": all_pass, "checks": checks, "event": event}
