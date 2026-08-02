"""Deterministic utilities shared across the expert pipeline."""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from typing import Any


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()


def normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def content_hash(*parts: str) -> str:
    """Deterministic 16-hex content hash for original_id fallback."""
    return sha256_hex("|".join(parts))[:16]


def utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def valid_iso_date(s: Any, full: bool = False) -> bool:
    try:
        if full:
            datetime.datetime.fromisoformat(s)
        else:
            datetime.date.fromisoformat(s)
        return True
    except (ValueError, TypeError):
        return False


def parse_list_field(v: Any) -> list:
    """FAIL_TO_PASS/PASS_TO_PASS are JSON-encoded strings in SWE-bench_Verified."""
    if isinstance(v, list):
        return v
    if isinstance(v, str) and v.strip():
        try:
            parsed = json.loads(v)
            return parsed if isinstance(parsed, list) else []
        except (ValueError, TypeError):
            return []
    return []


def extract_files(patch: str) -> list[str]:
    files = []
    for line in (patch or "").splitlines():
        m = re.match(r"diff --git a/(\S+) b/\S+", line)
        if m:
            files.append(m.group(1))
    return files
