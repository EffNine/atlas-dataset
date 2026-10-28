"""Deterministic SHA-256 helpers for Source Discovery v1.0.

Single rule: SHA-256 on UTF-8 bytes, canonical JSON is sorted keys with
compact separators. No SHA-1 anywhere.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_canonical(obj: object) -> str:
    canonical = json.dumps(obj, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"))
    return sha256_text(canonical)


def sha256_file(path: str | Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def content_hash(source: str, target: str, source_lang: str,
                 target_lang: str) -> str:
    """Normalized content hash binding both sides + direction."""
    payload = "\x00".join([source, target, source_lang, target_lang])
    return sha256_text(payload)
