#!/usr/bin/env python3
"""Cleaning pipeline for Atlas ETL v1.7."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from ..types import CanonicalRecord
from ..normalizer import clean_text, normalize_license

# Basic PII patterns (conservative — flags rather than aggressive destruction of code)
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_API_KEY = re.compile(
    r"\b(?:sk|pk|api|token|secret)[-_]?[A-Za-z0-9]{16,}\b"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\bghp_[A-Za-z0-9]{20,}\b"
)
_IPV4 = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

VALID_ROLES = {"system", "user", "assistant", "tool"}


@dataclass
class CleanResult:
    records: list[CanonicalRecord]
    dropped: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def _content_fingerprint(content: Any) -> str:
    blob = repr(content).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _iter_strings(content: Any):
    if isinstance(content, str):
        yield content
    elif isinstance(content, dict):
        for v in content.values():
            yield from _iter_strings(v)
    elif isinstance(content, list):
        for v in content:
            yield from _iter_strings(v)


def _map_strings(content: Any, fn: Callable[[str], str]) -> Any:
    if isinstance(content, str):
        return fn(content)
    if isinstance(content, dict):
        return {k: _map_strings(v, fn) for k, v in content.items()}
    if isinstance(content, list):
        return [_map_strings(v, fn) for v in content]
    return content


def dedup_cleaner(records: list[CanonicalRecord], dropped: list[dict[str, Any]]) -> list[CanonicalRecord]:
    seen: set[str] = set()
    out: list[CanonicalRecord] = []
    for rec in records:
        fp = _content_fingerprint(rec.content)
        if fp in seen:
            dropped.append({"id": rec.id, "reason": "duplicate_content", "fingerprint": fp})
            continue
        seen.add(fp)
        rec.lineage = list(rec.lineage) + ["clean:dedup"]
        out.append(rec)
    return out


def pii_cleaner(records: list[CanonicalRecord], dropped: list[dict[str, Any]]) -> list[CanonicalRecord]:
    out: list[CanonicalRecord] = []
    for rec in records:
        flags: list[str] = []
        text_blob = "\n".join(_iter_strings(rec.content))
        if _EMAIL.search(text_blob):
            flags.append("email")
        if _API_KEY.search(text_blob):
            flags.append("api_key")
        if _SSN.search(text_blob):
            flags.append("ssn")
        # IPs in prose are weak signal; flag but do not drop
        if _IPV4.search(text_blob):
            flags.append("ipv4")

        def _redact(s: str) -> str:
            s = _EMAIL.sub("[REDACTED_EMAIL]", s)
            s = _API_KEY.sub("[REDACTED_SECRET]", s)
            s = _SSN.sub("[REDACTED_SSN]", s)
            return s

        if flags:
            rec.metadata = dict(rec.metadata or {})
            rec.metadata["pii_flags"] = flags
            # Drop only high-severity secrets / SSN; redact emails
            if "api_key" in flags or "ssn" in flags:
                dropped.append({"id": rec.id, "reason": "pii_high_severity", "flags": flags})
                continue
            rec.content = _map_strings(rec.content, _redact)
        rec.lineage = list(rec.lineage) + ["clean:pii"]
        out.append(rec)
    return out


def malformed_cleaner(records: list[CanonicalRecord], dropped: list[dict[str, Any]]) -> list[CanonicalRecord]:
    out: list[CanonicalRecord] = []
    for rec in records:
        content = rec.content
        reason = None

        if rec.record_type == "qa" and isinstance(content, dict):
            if not content.get("question") or not content.get("answer"):
                reason = "malformed_qa_missing_fields"
        elif rec.record_type == "conversation" and isinstance(content, dict):
            msgs = content.get("messages") or []
            if len(msgs) < 2:
                reason = "malformed_conversation_too_short"
            else:
                roles = [m.get("role") for m in msgs if isinstance(m, dict)]
                if any(r not in VALID_ROLES for r in roles):
                    reason = "malformed_conversation_bad_role"
                if any(not (m.get("content") or "").strip() for m in msgs if isinstance(m, dict)):
                    reason = "malformed_conversation_empty_turn"
        elif rec.record_type == "instruction" and isinstance(content, dict):
            if not content.get("instruction") or not content.get("output"):
                reason = "malformed_instruction_missing_fields"
        elif isinstance(content, dict) and "text" in content:
            if not clean_text(content.get("text")):
                reason = "empty_text"
        elif isinstance(content, str) and not content.strip():
            reason = "empty_content"

        if reason:
            dropped.append({"id": rec.id, "reason": reason})
            continue
        rec.lineage = list(rec.lineage) + ["clean:malformed"]
        out.append(rec)
    return out


def license_cleaner(records: list[CanonicalRecord], dropped: list[dict[str, Any]]) -> list[CanonicalRecord]:
    out: list[CanonicalRecord] = []
    for rec in records:
        rec.license = normalize_license(rec.license)
        rec.metadata = dict(rec.metadata or {})
        rec.metadata["license_normalized"] = rec.license
        if rec.license.lower() in {"unknown", ""}:
            rec.metadata["license_warning"] = "unresolved_license"
        rec.lineage = list(rec.lineage) + ["clean:license"]
        out.append(rec)
    return out


def length_cleaner(
    records: list[CanonicalRecord],
    dropped: list[dict[str, Any]],
    *,
    min_chars: int = 8,
    max_chars: int = 100_000,
) -> list[CanonicalRecord]:
    out: list[CanonicalRecord] = []
    for rec in records:
        blob = "\n".join(_iter_strings(rec.content))
        n = len(blob)
        if n < min_chars:
            dropped.append({"id": rec.id, "reason": "too_short", "chars": n})
            continue
        if n > max_chars:
            dropped.append({"id": rec.id, "reason": "too_long", "chars": n})
            continue
        rec.lineage = list(rec.lineage) + ["clean:length"]
        out.append(rec)
    return out


DEFAULT_CLEANERS: tuple[Callable[..., list[CanonicalRecord]], ...] = (
    malformed_cleaner,
    length_cleaner,
    pii_cleaner,
    dedup_cleaner,
    license_cleaner,
)


def run_cleaners(
    records: list[CanonicalRecord],
    *,
    cleaners: tuple[Callable[..., list[CanonicalRecord]], ...] | None = None,
) -> CleanResult:
    dropped: list[dict[str, Any]] = []
    current = list(records)
    for cleaner in cleaners or DEFAULT_CLEANERS:
        current = cleaner(current, dropped)

    stats = {
        "input": len(records),
        "output": len(current),
        "dropped": len(dropped),
        "drop_reasons": {},
    }
    for item in dropped:
        reason = item.get("reason", "unknown")
        stats["drop_reasons"][reason] = stats["drop_reasons"].get(reason, 0) + 1
    return CleanResult(records=current, dropped=dropped, stats=stats)
