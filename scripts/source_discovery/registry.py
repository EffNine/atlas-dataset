"""Versioned source registry for Source Discovery v1.0.

Field names are deliberately prefixed (sd_*) where they could collide with
Atlas canonical constants, so validate_architecture.py ownership checks never
fire. Nothing here redefines atlas_constants / atlas_schema / atlas_paths.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .license_policy import SD_LICENSE_STATES, classify_license

REGISTRY_SCHEMA_ID = "atlas-source-discovery-registry-v1"
REGISTRY_VERSION = "1.0"

SD_SOURCE_STATUSES = frozenset({
    "DISCOVERED", "VERIFIED", "DOWNLOADABLE", "INGESTED", "REJECTED",
    "BLOCKED_LICENSE", "BLOCKED_ACCESS", "FAILED",
})

SD_SOURCE_TYPES = frozenset({
    "parallel_corpus", "literary_corpus", "dictionary", "terminology",
    "linguistic", "eval_benchmark", "translation_memory", "other",
})

SD_DOMAINS = frozenset({
    "general", "literary", "novel", "light_novel", "web_novel", "manga",
    "dialogue", "subtitle", "dictionary", "terminology", "academic", "other",
})

SD_LANGS = frozenset({"zh", "ja", "ko", "ms", "en"})

SD_REGISTRY_REQUIRED_FIELDS = [
    "source_id", "name", "source_type", "languages", "directions",
    "url", "repo_id", "license", "license_evidence", "publisher",
    "citation", "estimated_size", "format", "access_method",
    "discovery_timestamp", "source_revision", "checksum", "status",
    "license_state", "domain", "notes",
]

# Optional-but-tracked fields (may be empty string / empty list).
SD_REGISTRY_OPTIONAL_FIELDS = ["source_type_detail", "verification"]

SD_ALLOWED_TRANSITIONS: dict[str, frozenset] = {
    "DISCOVERED": frozenset({"VERIFIED", "REJECTED", "BLOCKED_LICENSE",
                             "BLOCKED_ACCESS", "FAILED", "DOWNLOADABLE"}),
    "VERIFIED": frozenset({"DOWNLOADABLE", "INGESTED", "REJECTED",
                           "BLOCKED_LICENSE", "BLOCKED_ACCESS", "FAILED"}),
    "DOWNLOADABLE": frozenset({"INGESTED", "REJECTED", "BLOCKED_LICENSE",
                               "BLOCKED_ACCESS", "FAILED"}),
    "INGESTED": frozenset({"REJECTED", "BLOCKED_LICENSE", "FAILED"}),
    "REJECTED": frozenset({"DISCOVERED"}),
    "BLOCKED_LICENSE": frozenset({"DISCOVERED"}),
    "BLOCKED_ACCESS": frozenset({"DISCOVERED"}),
    "FAILED": frozenset({"DISCOVERED"}),
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def blank_entry(source_id: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "name": "",
        "source_type": "other",
        "languages": [],
        "directions": [],
        "url": "",
        "repo_id": "",
        "license": "UNKNOWN",
        "license_evidence": "",
        "publisher": "",
        "citation": "",
        "estimated_size": "",
        "format": "",
        "access_method": "",
        "discovery_timestamp": utcnow(),
        "source_revision": "",
        "checksum": "",
        "status": "DISCOVERED",
        "license_state": "UNKNOWN",
        "domain": "other",
        "notes": "",
    }


def validate_source_entry(entry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(entry, dict):
        return ["entry_not_a_dict"]
    for field in SD_REGISTRY_REQUIRED_FIELDS:
        if field not in entry:
            errors.append(f"missing_field:{field}")
    if errors:
        return errors
    if not entry.get("source_id") or not isinstance(entry["source_id"], str):
        errors.append("bad_source_id")
    if entry.get("source_type") not in SD_SOURCE_TYPES:
        errors.append(f"bad_source_type:{entry.get('source_type')!r}")
    if entry.get("status") not in SD_SOURCE_STATUSES:
        errors.append(f"bad_status:{entry.get('status')!r}")
    if entry.get("license_state") not in SD_LICENSE_STATES:
        errors.append(f"bad_license_state:{entry.get('license_state')!r}")
    if entry.get("domain") not in SD_DOMAINS:
        errors.append(f"bad_domain:{entry.get('domain')!r}")
    langs = entry.get("languages")
    if not isinstance(langs, list) or not langs \
            or any(L not in SD_LANGS for L in langs):
        errors.append(f"bad_languages:{langs!r}")
    dirs = entry.get("directions")
    if not isinstance(dirs, list):
        errors.append("bad_directions:not_a_list")
    else:
        for d in dirs:
            if not isinstance(d, str) or "→" not in d:
                errors.append(f"bad_direction:{d!r}")
                break
    return errors


def refresh_license_state(entry: dict[str, Any]) -> dict[str, Any]:
    state, reason = classify_license(entry.get("license", "UNKNOWN"),
                                     entry.get("license_evidence", ""))
    entry["license_state"] = state
    note = f"license_state={state} ({reason})"
    existing = entry.get("notes") or ""
    if note not in existing:
        entry["notes"] = (existing + f" [{note}]").strip()
    return entry


def transition(entry: dict[str, Any], new_status: str,
               note: str = "") -> dict[str, Any]:
    if new_status not in SD_SOURCE_STATUSES:
        raise ValueError(f"unknown status {new_status!r}")
    cur = entry.get("status")
    if not isinstance(cur, str):
        raise ValueError(f"illegal transition {cur!r} -> {new_status}")
    allowed = SD_ALLOWED_TRANSITIONS.get(cur, frozenset())
    if new_status not in allowed:
        raise ValueError(f"illegal transition {cur} -> {new_status}")
    entry["status"] = new_status
    if note:
        entry["notes"] = ((entry.get("notes") or "") + f" [{note}]").strip()
    return entry


def load_registry(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "sources" not in data:
        raise ValueError("registry file must be {schema..., sources:[...]}")
    return data


def save_registry(path: str | Path, sources: list[dict],
                  verification: dict | None = None) -> dict:
    ordered = sorted(sources, key=lambda e: e.get("source_id", ""))
    payload = {
        "schema_id": REGISTRY_SCHEMA_ID,
        "registry_version": REGISTRY_VERSION,
        "updated_utc": utcnow(),
        "n_sources": len(ordered),
        "sources": ordered,
    }
    if verification is not None:
        payload["verification"] = verification
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                              sort_keys=False) + "\n", encoding="utf-8")
    tmp.replace(p)
    return payload


def registry_stats(sources: list[dict]) -> dict[str, Any]:
    from collections import Counter
    return {
        "n_sources": len(sources),
        "by_status": dict(Counter(e.get("status") for e in sources)),
        "by_license_state": dict(Counter(e.get("license_state")
                                         for e in sources)),
        "by_domain": dict(Counter(e.get("domain") for e in sources)),
        "by_source_type": dict(Counter(e.get("source_type")
                                       for e in sources)),
    }
