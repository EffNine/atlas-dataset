#!/usr/bin/env python3
"""dashboard.safety — security primitives for the Atlas Engineering Dashboard.

Layer 4 (CLI & Tooling). Provides:

- Repo-relative path resolution with traversal protection.
- Read-whitelist enforcement for file preview endpoints.
- Typed-confirmation enforcement for destructive actions.
- Constant-time token comparison helper.

This module never performs I/O on behalf of the browser beyond validating
paths; it contains no business logic.
"""

from __future__ import annotations

import hmac
import re
from pathlib import Path
from typing import Iterable

from atlas_paths import get_root

# Subtrees the dashboard may READ raw record files from (relative to root).
# Everything else is rejected for preview endpoints. These are read-only
# surfaces; no dashboard endpoint may write here.
READABLE_SUBTREES: tuple[str, ...] = (
    "review",
    "review_queue",
    "pilot",
    "curated",
    "metadata/views",
    "metadata/sft_review",
    "metadata/releases",
    "metadata/etl",
    "metadata/evaluation",
    "reports",
    "evaluation",
)

# Hard identifier pattern: pipeline ids, source ids, benchmark ids.
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
# Release/view version pattern, e.g. v1.0, v1.0-RC2, v0.3-gsm8k, atlas-sft-v0.2
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
# Free-text fields (comments, reasons): printable, no control chars, bounded.
_TEXT_RE = re.compile(r"^[\x20-\x7e\n\r\t]{0,2000}$")

MAX_PREVIEW_LINES = 500
MAX_PREVIEW_BYTES = 2_000_000


class SafetyError(ValueError):
    """Raised when a browser-supplied input fails validation."""


def safe_id(value: str, field: str = "id") -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise SafetyError(f"invalid {field}: must match ^[A-Za-z0-9][A-Za-z0-9._-]{{0,127}}$")
    return value


def validate_version(value: str, field: str = "version") -> str:
    if not isinstance(value, str) or not _VERSION_RE.match(value):
        raise SafetyError(f"invalid {field}: must match ^[A-Za-z0-9][A-Za-z0-9._-]{{0,63}}$")
    return value


def validate_text(value: str, field: str = "text") -> str:
    if not isinstance(value, str) or not _TEXT_RE.match(value):
        raise SafetyError(f"invalid {field}: too long or contains control characters")
    return value


def validate_bool(value: object, field: str = "flag") -> bool:
    if not isinstance(value, bool):
        raise SafetyError(f"invalid {field}: must be a boolean")
    return value


def validate_int(value: object, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SafetyError(f"invalid {field}: must be an integer")
    if value < minimum or value > maximum:
        raise SafetyError(f"invalid {field}: must be between {minimum} and {maximum}")
    return value


def validate_choice(value: object, field: str, choices: Iterable[str]) -> str:
    if not isinstance(value, str) or value not in set(choices):
        raise SafetyError(f"invalid {field}: must be one of {sorted(set(choices))}")
    return value


def resolve_readable_path(rel_path: str) -> Path:
    """Resolve a repo-relative path for READ-ONLY preview.

    The path must:
      - be relative (no absolute paths),
      - resolve inside the repository root (no traversal),
      - fall under one of READABLE_SUBTREES.
    """
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise SafetyError("path must be a non-empty repo-relative string")
    if rel_path.startswith(("/", "~")) or "\\" in rel_path:
        raise SafetyError("path must be repo-relative and use forward slashes")
    root = get_root().resolve()
    candidate = (root / rel_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SafetyError("path escapes repository root") from exc
    allowed = False
    for sub in READABLE_SUBTREES:
        sub_abs = (root / sub).resolve()
        try:
            candidate.relative_to(sub_abs)
            allowed = True
            break
        except ValueError:
            continue
    if not allowed:
        raise SafetyError(
            f"path is outside readable subtrees: allowed roots are {list(READABLE_SUBTREES)}"
        )
    if not candidate.is_file():
        raise SafetyError("path does not point to an existing file")
    return candidate


def require_confirmation(provided: object, expected: str) -> None:
    """Destructive actions must echo the exact confirmation phrase."""
    if not isinstance(provided, str) or not hmac.compare_digest(provided, expected):
        raise SafetyError(
            f"destructive action requires confirm == {expected!r} (typed exactly)"
        )


def tokens_equal(provided: str | None, expected: str | None) -> bool:
    """Constant-time bearer-token comparison."""
    if not expected:
        return True
    if not provided:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))
