"""Deterministic exact dedup for Source Discovery v1.0.

Key: content_sha256 (normalized source + target + direction). First record in
input order wins; later copies are reported as duplicates with pointer to the
kept id. No near-dup / fuzzy matching in v1.0 (documented limitation).
"""

from __future__ import annotations

from typing import Any


def dedup_by_content(records: list[dict[str, Any]]) -> tuple[list[dict], list[dict], dict]:
    kept: list[dict] = []
    dups: list[dict] = []
    seen: dict[str, str] = {}
    for rec in records:
        ch = rec.get("content_sha256") if isinstance(rec, dict) else None
        rid = rec.get("id") if isinstance(rec, dict) else None
        if not isinstance(ch, str) or not ch:
            dups.append({"id": rid, "reason": "missing_content_sha256"})
            continue
        if ch in seen:
            dups.append({"id": rid, "reason": "duplicate_content",
                         "kept_id": seen[ch], "content_sha256": ch})
        else:
            seen[ch] = rid if isinstance(rid, str) else ch
            kept.append(rec)
    stats = {"n_input": len(records), "n_kept": len(kept),
             "n_duplicates": len(dups)}
    return kept, dups, stats
