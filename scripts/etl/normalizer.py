#!/usr/bin/env python3
"""Normalize extracted RawRecords into Atlas intermediate CanonicalRecords."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

from .types import CanonicalRecord, RawRecord, utc_now

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS = re.compile(r"[ \t]+")

# Common license string normalizations
_LICENSE_MAP = {
    "mit": "MIT",
    "apache-2.0": "Apache-2.0",
    "apache 2.0": "Apache-2.0",
    "apache2": "Apache-2.0",
    "cc-by-4.0": "CC-BY-4.0",
    "cc by 4.0": "CC-BY-4.0",
    "cc-by-sa-4.0": "CC-BY-SA-4.0",
    "bsd-3-clause": "BSD-3-Clause",
    "gpl-3.0": "GPL-3.0",
    "public domain": "Public Domain",
}


def clean_text(text: Any) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    text = unicodedata.normalize("NFC", text)
    text = _CTRL.sub("", text)
    text = "\n".join(_WS.sub(" ", line).strip() for line in text.split("\n"))
    return text.strip()


def normalize_license(value: Any) -> str:
    if not value:
        return "unknown"
    text = str(value).strip()
    key = text.lower()
    return _LICENSE_MAP.get(key, text)


def _stable_id(source_id: str, raw_id: str, content: Any) -> str:
    basis = f"{source_id}|{raw_id}|{repr(content)[:500]}"
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]
    safe_src = re.sub(r"[^a-z0-9]+", "_", (source_id or "src").lower()).strip("_")
    safe_raw = re.sub(r"[^a-z0-9_-]+", "_", str(raw_id).lower()).strip("_")[:48]
    return f"{safe_src}_{safe_raw}_{digest}"


def _detect_type_and_content(content: Any) -> tuple[str, Any]:
    """Map source-native payloads into typed content blobs."""
    if isinstance(content, str):
        return "raw", clean_text(content)

    if not isinstance(content, dict):
        return "raw", content

    # GSM8K / QA style
    if "question" in content and "answer" in content:
        return "qa", {
            "question": clean_text(content.get("question")),
            "answer": clean_text(content.get("answer")),
        }

    # Instruction style
    if "instruction" in content and ("output" in content or "response" in content):
        return "instruction", {
            "instruction": clean_text(content.get("instruction")),
            "input": clean_text(content.get("input") or ""),
            "output": clean_text(content.get("output") or content.get("response") or ""),
        }

    # ShareGPT / messages
    if isinstance(content.get("messages"), list):
        msgs = []
        for m in content["messages"]:
            if not isinstance(m, dict):
                continue
            role = (m.get("role") or m.get("from") or "user").lower()
            if role in {"human", "prompt"}:
                role = "user"
            if role in {"gpt", "bot", "model"}:
                role = "assistant"
            msgs.append({"role": role, "content": clean_text(m.get("content") or m.get("value") or "")})
        return "conversation", {"messages": msgs}

    # Doc section
    if "text" in content:
        return "raw", {
            "title": clean_text(content.get("title") or ""),
            "text": clean_text(content.get("text")),
        }

    # Generic dict — clean string fields
    cleaned = {}
    for k, v in content.items():
        cleaned[k] = clean_text(v) if isinstance(v, str) else v
    return "raw", cleaned


def normalize_record(
    raw: RawRecord,
    *,
    source_id: str = "",
    source_name: str = "",
    license: str = "unknown",
    category: str = "",
    subcategory: str = "",
) -> CanonicalRecord:
    record_type, content = _detect_type_and_content(raw.content)
    lineage = [
        f"extract:{raw.format or 'unknown'}",
        "normalize:v1.7",
    ]
    if raw.source_ref:
        lineage.insert(0, f"cache:{raw.source_ref}")

    meta = dict(raw.metadata or {})
    if category:
        meta["category"] = category
    if subcategory:
        meta["subcategory"] = subcategory
    meta["raw_id"] = raw.id
    meta["raw_format"] = raw.format

    return CanonicalRecord(
        id=_stable_id(source_id or "src", raw.id, content),
        source=source_name or source_id or raw.source_ref or "unknown",
        license=normalize_license(license),
        content=content,
        created_at=utc_now(),
        lineage=lineage,
        metadata=meta,
        source_id=source_id,
        record_type=record_type,
    )


def to_atlas_record(canonical: CanonicalRecord, *, seq: int = 0) -> dict[str, Any]:
    """Promote a CanonicalRecord toward curated dataset_schema shape.

    Does NOT set verified=True — human review still required.
    Writes to staging only; never curated/.
    """
    category = (canonical.metadata or {}).get("category") or "06_science_engineering"
    subcategory = (canonical.metadata or {}).get("subcategory") or "general"
    content = canonical.content

    messages: list[dict[str, str]]
    notes = ""
    atlas_type = "qa"

    if canonical.record_type == "qa" and isinstance(content, dict):
        messages = [
            {"role": "user", "content": content.get("question") or ""},
            {"role": "assistant", "content": content.get("answer") or ""},
        ]
        atlas_type = "reasoning" if "<<" in (content.get("answer") or "") else "qa"
    elif canonical.record_type == "instruction" and isinstance(content, dict):
        user = content.get("instruction") or ""
        if content.get("input"):
            user = f"{user}\n\n{content['input']}"
        messages = [
            {"role": "user", "content": user.strip()},
            {"role": "assistant", "content": content.get("output") or ""},
        ]
        atlas_type = "instruction"
    elif canonical.record_type == "conversation" and isinstance(content, dict):
        messages = list(content.get("messages") or [])
        atlas_type = "conversation"
    elif isinstance(content, dict) and content.get("text"):
        title = content.get("title") or "Document"
        messages = [
            {"role": "user", "content": f"Summarize the key points from: {title}"},
            {"role": "assistant", "content": content.get("text") or ""},
        ]
        atlas_type = "instruction"
        notes = "auto-promoted from documentation extract; needs human review"
    else:
        messages = [
            {"role": "user", "content": "Provide the content."},
            {"role": "assistant", "content": clean_text(content) if not isinstance(content, dict) else clean_text(str(content))},
        ]
        notes = "auto-promoted from raw extract; needs human review"

    # Prefer human-readable sequential id for staging readability
    safe_cat = re.sub(r"[^a-z0-9_]", "", category)
    safe_sub = re.sub(r"[^a-z0-9_]", "", subcategory.replace("-", "_"))
    atlas_id = f"{safe_cat}_{safe_sub}_{canonical.source_id or 'src'}_{seq:06d}"

    return {
        "id": atlas_id,
        "category": category,
        "subcategory": subcategory,
        "type": atlas_type,
        "source": {
            "name": canonical.source,
            "url": (canonical.metadata or {}).get("source_url") or "",
            "license": canonical.license,
            "date": "",
        },
        "messages": messages,
        "language": "en",
        "difficulty": 0,
        "tags": sorted(
            {
                canonical.source_id or "source",
                subcategory.replace("_", "-"),
                atlas_type,
            }
        ),
        "quality_score": 0,
        "verified": False,
        "notes": notes,
        "lineage": {
            "source": canonical.source_id or canonical.source,
            "transformations": list(canonical.lineage) + ["promote:atlas_dataset_schema_v1"],
            "knowledge_object": atlas_id,
            "curated_dataset": "",
            "training_view": "",
            "future_model": "",
        },
        "metadata": {
            "canonical_id": canonical.id,
            "etl_record_type": canonical.record_type,
            **{k: v for k, v in (canonical.metadata or {}).items() if k not in {"category", "subcategory"}},
        },
    }
