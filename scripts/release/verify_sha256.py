#!/usr/bin/env python3
"""Shared SHA-256 verification helpers for Atlas release tooling.

Provides:
  - sha256_file(path)                   streaming file hash
  - load_checksum_manifest(path)        parse checksums.sha256
  - verify_file_sha256(path, expected)  single-file verification
  - verify_manifest_files(root, manifest) verify all manifest entries on disk

Design:
  - deterministic
  - streaming hash calculation
  - no external network dependency
  - pure functions where possible
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Low-level hash
# ---------------------------------------------------------------------------

def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 hex digest of ``path``, streamed in ``chunk_size``
    blocks so memory usage is O(chunk_size) regardless of file size."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------

class ManifestError(Exception):
    """Raised when a checksums manifest cannot be parsed."""


def load_checksum_manifest(path: Path) -> Dict[str, str]:
    """Parse a ``checksums.sha256`` file.

    Returns an ordered mapping of ``relative_path -> sha256_hex``.

    Rules:
      - blank lines and lines starting with ``#`` are skipped
      - each data line must match ``<hex>  <path>`` exactly
      - returned hashes are lowercased for case-insensitive comparison

    Raises ``ManifestError`` on malformed input.
    """
    out: Dict[str, str] = {}
    text = path.read_text(encoding="utf-8")
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            hexd, rel = line.split("  ", 1)
        except ValueError:
            raise ManifestError(
                f"{path}:{lineno}: malformed checksum line (expected '<hex>  <path>'): {line!r}"
            )
        hexd = hexd.lower()
        if len(hexd) != 64 or any(c not in "0123456789abcdef" for c in hexd):
            raise ManifestError(
                f"{path}:{lineno}: invalid sha256 hex: {hexd!r}"
            )
        out[rel] = hexd
    return out


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

@dataclass
class VerifyResult:
    """Outcome of a manifest verification pass."""
    ok: bool
    verified: int = 0
    mismatches: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    extra_manifest: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def failed(self) -> int:
        return len(self.mismatches) + len(self.missing) + len(self.errors)


def verify_file_sha256(path: Path, expected_hash: str) -> Tuple[bool, Optional[str]]:
    """Verify ``path`` against ``expected_hash``.

    Returns ``(True, None)`` on match.
    Returns ``(False, actual_hash)`` on mismatch.
    Returns ``(False, None)`` if the file cannot be read.
    """
    try:
        actual = sha256_file(path).lower()
    except OSError as exc:
        return False, None
    if actual != expected_hash.lower():
        return False, actual
    return True, None


def verify_manifest_files(root: Path, manifest: Dict[str, str]) -> VerifyResult:
    """Verify every file listed in ``manifest`` exists under ``root`` and
    matches its recorded hash.

    ``root`` is the release root; manifest keys are paths relative to it.

    Returns a ``VerifyResult`` with ``ok=True`` only when all files are
    present, readable, and hash-match.
    """
    result = VerifyResult(ok=True)

    for rel, expected in manifest.items():
        fp = root / rel
        if not fp.exists():
            result.ok = False
            result.missing.append(rel)
            continue
        if not fp.is_file():
            result.ok = False
            result.errors.append(f"{rel}: not a regular file")
            continue
        ok, actual = verify_file_sha256(fp, expected)
        if not ok:
            result.ok = False
            if actual is None:
                result.errors.append(f"{rel}: unreadable")
            else:
                result.mismatches.append(
                    f"{rel}: expected {expected} got {actual}"
                )
        else:
            result.verified += 1

    return result
