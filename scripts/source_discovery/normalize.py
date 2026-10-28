"""Normalization + provenance for Source Discovery v1.0.

Normalized record shape (translation-ai-v0.1 compatible, provenance-first):

  {id, source_lang, target_lang, source, target, source_id, source_revision,
   source_record_id, original_sha256, content_sha256, quality_status,
   acquisition: {method, acquired_utc, parser_format, direction}}

Rules: Unicode NFC, CRLF->LF, strip ends, collapse 3+ newlines to 2, collapse
horizontal whitespace runs. Deterministic: same input bytes -> same output.
IDs are deterministic: {source_id}:{revision8}:{record-or-hash16}.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from .hashing import content_hash, sha256_text

_WS_RUN = re.compile(r"[ \t\u00a0]+")
_NL_RUN = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    t = unicodedata.normalize("NFC", text)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = _NL_RUN.sub("\n\n", t)
    lines = [_WS_RUN.sub(" ", ln).strip() for ln in t.split("\n")]
    # Drop leading/trailing blank lines introduced by stripping.
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def normalize_pair(source: str, target: str, source_lang: str,
                   target_lang: str, source_id: str,
                   source_revision: str = "",
                   source_record_id: str = "",
                   method: str = "", parser_format: str = "",
                   extra: dict | None = None) -> dict[str, Any]:
    if not isinstance(source, str) or not isinstance(target, str):
        raise ValueError("source/target must be strings")
    original_sha = sha256_text(source + "\x00" + target)
    ns, nt = normalize_text(source), normalize_text(target)
    chash = content_hash(ns, nt, source_lang, target_lang)
    rev8 = (source_revision or "norev")[:8]
    tail = source_record_id if source_record_id else chash[:16]
    # Sanitize tail for id safety (keep alnum, dash, underscore).
    tail = re.sub(r"[^A-Za-z0-9_-]", "_", tail)[:64]
    rid = f"{source_id}:{rev8}:{tail}"
    record: dict[str, Any] = {
        "id": rid,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "source": ns,
        "target": nt,
        "source_id": source_id,
        "source_revision": source_revision,
        "source_record_id": source_record_id,
        "original_sha256": original_sha,
        "content_sha256": chash,
        "quality_status": "raw",
        "acquisition": {
            "method": method,
            "acquired_utc": datetime.now(timezone.utc).isoformat(),
            "parser_format": parser_format,
            "direction": f"{source_lang}→{target_lang}",
        },
    }
    if extra:
        for key in ("orig_split", "chapter_id", "target_origin"):
            if key in extra and extra[key] not in (None, ""):
                record[key] = extra[key]
    return record
