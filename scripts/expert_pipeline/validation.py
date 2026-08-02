"""Validation for Atlas Expert records.

- schema validation (required fields + type validity)
- provenance validation
- license validation
- duplicate detection (exact id + near-dup content hash)
- security hard gate scan
"""

from __future__ import annotations

import re
from typing import Any

from .constants import (
    BLOCKED_LICENSE_MARKERS,
    DOMAINS,
    REQUIRED_LEAF,
    SECURITY_PATTERNS,
    TIERS,
    TYPES,
    VERIFY_STATUSES,
)
from .util import normalize_text, sha256_hex, valid_iso_date


def get_path(rec: dict, dotted: str) -> Any:
    cur = rec
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def validate_schema(rec: dict) -> list[str]:
    """Return list of schema errors (empty == valid)."""
    errors: list[str] = []
    for field, ftype in REQUIRED_LEAF.items():
        val = get_path(rec, field)
        if val is None:
            errors.append(f"missing:{field}")
            continue
        if field == "provenance.transformations":
            if not isinstance(val, list) or len(val) == 0:
                errors.append(f"invalid:{field}:empty")
        elif ftype is bool:
            if not isinstance(val, bool):
                errors.append(f"invalid:{field}:not_bool")
        elif ftype is int:
            if not isinstance(val, int) or isinstance(val, bool):
                errors.append(f"invalid:{field}:not_int")
        elif ftype is list:
            if not isinstance(val, list) or len(val) == 0:
                errors.append(f"invalid:{field}:empty")
        elif ftype is str:
            if not isinstance(val, str) or not val.strip():
                errors.append(f"invalid:{field}:empty")

    if rec.get("domain") not in DOMAINS:
        errors.append("invalid:domain")
    if rec.get("expert_tier") not in TIERS:
        errors.append("invalid:expert_tier")
    if not isinstance(rec.get("difficulty"), int) or not (1 <= rec["difficulty"] <= 5):
        errors.append("invalid:difficulty")
    if rec.get("type") not in TYPES:
        errors.append("invalid:type")
    if rec.get("license") in (None, "", "unknown"):
        errors.append("invalid:license:unknown")

    v = rec.get("verification") or {}
    if v.get("status") not in VERIFY_STATUSES:
        errors.append("invalid:verification.status")
    if v.get("status") == "verified" and not v.get("method"):
        errors.append("invalid:verification.method:verified_requires_method")
    if v.get("status") == "verified" and not v.get("evidence"):
        errors.append("invalid:verification.evidence:verified_requires_evidence")

    src = rec.get("source") or {}
    if not valid_iso_date(src.get("accessed_at")):
        errors.append("invalid:source.accessed_at")
    if not valid_iso_date(rec.get("created_at"), full=True):
        errors.append("invalid:created_at")

    qs = (rec.get("metadata") or {}).get("quality_score")
    if not isinstance(qs, int) or not (0 <= qs <= 10):
        errors.append("invalid:metadata.quality_score")

    msgs = rec.get("messages") or []
    roles = [m.get("role") for m in msgs if isinstance(m, dict)]
    if "user" not in roles or "assistant" not in roles:
        errors.append("invalid:messages:missing_user_or_assistant")
    for m in msgs:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant") \
                or not isinstance(m.get("content"), str) or not m["content"].strip():
            errors.append("invalid:messages:malformed_turn")
            break
    return errors


def validate_provenance(rec: dict) -> list[str]:
    """Provenance completeness per quality gate 1.1."""
    errors: list[str] = []
    src = rec.get("source") or {}
    prov = rec.get("provenance") or {}
    if not src.get("source_id"):
        errors.append("missing:source.source_id")
    if not src.get("url"):
        errors.append("missing:source.url")
    if not prov.get("original_id"):
        errors.append("missing:provenance.original_id")
    if not isinstance(prov.get("transformations"), list) or not prov["transformations"]:
        errors.append("invalid:provenance.transformations:empty")
    if not prov.get("ingestion_pipeline"):
        errors.append("missing:provenance.ingestion_pipeline")
    return errors


def validate_license(rec: dict) -> list[str]:
    """License validation per quality gate 1.2."""
    errors: list[str] = []
    lic = rec.get("license") or ""
    if not lic or lic == "unknown":
        errors.append("invalid:license:unknown")
        return errors
    if lic not in ("MIT", "Apache-2.0", "CC-BY-4.0", "arXiv non-exclusive license"):
        low = lic.lower()
        if any(m in low for m in BLOCKED_LICENSE_MARKERS):
            errors.append(f"invalid:license:blocked:{lic}")
    if "cc-by-sa" in lic.lower() and not (rec.get("attribution") or "").strip():
        errors.append("invalid:attribution:required_for_sharealike")
    return errors


def security_scan(rec: dict) -> dict:
    """Return {pattern_name: match} for any hard-gate security hit."""
    blob = " ".join([
        rec.get("problem") or "", rec.get("context") or "", rec.get("solution") or ""
    ])
    hits: dict = {}
    for name, pattern in SECURITY_PATTERNS:
        m = re.search(pattern, blob)
        if m:
            hits[name] = m.group(0)[:40]
    return hits


def detect_duplicates(records: list[dict]) -> dict:
    """Exact duplicate ids and near-duplicate problem+solution clusters."""
    seen_ids: dict[str, int] = {}
    dup_ids: list[str] = []
    for rec in records:
        rid = rec.get("id", "")
        if rid in seen_ids:
            dup_ids.append(rid)
        seen_ids[rid] = 1

    near: dict[str, list[str]] = {}
    for rec in records:
        key = sha256_hex(
            normalize_text(rec.get("problem", "")) + "|" + normalize_text(rec.get("solution", ""))
        )
        near.setdefault(key, []).append(rec.get("id", ""))
    near_groups = [v for v in near.values() if len(v) > 1]

    involved = len(dup_ids) + sum(len(g) for g in near_groups)
    return {
        "exact_duplicate_ids": dup_ids,
        "near_duplicate_groups": near_groups,
        "duplicate_records_count": involved,
    }
