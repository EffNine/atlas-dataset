#!/usr/bin/env python3
"""Transformation layer v1.8 — map cleaned ETL records into 5 training types.

Types:
  instruction | qa_pair | conversation | reasoning | knowledge

Input: cleaned CanonicalRecords or atlas_staging JSONL from metadata/etl/.
Output: metadata/etl/<source_id>/transformed.jsonl (typed training records).
Never writes curated/.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from etl.types import CanonicalRecord, read_jsonl, utc_now, write_jsonl
from etl.normalizer import clean_text, to_atlas_record


TRAINING_TYPES = ("instruction", "qa_pair", "conversation", "reasoning", "knowledge")


@dataclass
class TrainRecord:
    """One typed training record produced by a transformer."""

    id: str
    training_type: str
    content: dict[str, Any]
    source_id: str = ""
    license: str = "unknown"
    lineage: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _as_canonical(obj: dict[str, Any]) -> CanonicalRecord | None:
    """Accept either CanonicalRecord dicts or atlas_staging records."""
    if "record_type" in obj and "content" in obj and "source" in obj and isinstance(obj.get("source"), str):
        return CanonicalRecord(
            id=obj["id"],
            source=obj.get("source") or "",
            license=obj.get("license") or "unknown",
            content=obj.get("content"),
            created_at=obj.get("created_at") or utc_now(),
            lineage=list(obj.get("lineage") or []),
            metadata=dict(obj.get("metadata") or {}),
            source_id=obj.get("source_id") or "",
            record_type=obj.get("record_type") or "raw",
        )

    # atlas_staging shape
    if "messages" in obj:
        msgs = obj.get("messages") or []
        q = next((m["content"] for m in msgs if m.get("role") == "user"), "")
        a = next((m["content"] for m in msgs if m.get("role") == "assistant"), "")
        atlas_type = obj.get("type") or "qa"
        if atlas_type == "reasoning" or ("<<" in a and "####" in a):
            record_type = "qa"
            content: Any = {"question": q, "answer": a, "is_reasoning": True}
        elif atlas_type == "conversation":
            record_type = "conversation"
            content = {"messages": msgs}
        elif atlas_type == "instruction":
            record_type = "instruction"
            content = {"instruction": q, "input": "", "output": a}
        else:
            record_type = "qa"
            content = {"question": q, "answer": a}
        src = obj.get("source") or {}
        return CanonicalRecord(
            id=obj.get("id") or "unknown",
            source=(src.get("name") if isinstance(src, dict) else str(src)) or "",
            license=(src.get("license") if isinstance(src, dict) else "unknown") or "unknown",
            content=content,
            created_at=utc_now(),
            lineage=list((obj.get("lineage") or {}).get("transformations") or [])
            if isinstance(obj.get("lineage"), dict)
            else list(obj.get("lineage") or []),
            metadata={
                **dict(obj.get("metadata") or {}),
                "category": obj.get("category"),
                "subcategory": obj.get("subcategory"),
                "atlas_id": obj.get("id"),
                "source_url": src.get("url") if isinstance(src, dict) else "",
                "source_name": src.get("name") if isinstance(src, dict) else "",
            },
            source_id=_source_id_from_atlas(obj),
            record_type=record_type,
        )
    return None


def _source_id_from_atlas(obj: dict[str, Any]) -> str:
    meta = obj.get("metadata") or {}
    if meta.get("source_id"):
        return str(meta["source_id"])
    # ids like 06_science_engineering_mathematics_c1_000001
    parts = str(obj.get("id") or "").split("_")
    for p in parts:
        if re.fullmatch(r"[a-z]\d+", p):
            return p
    return str(meta.get("raw_id") or "")


# ── transformers ──────────────────────────────────────────────────────


def transform_qa(rec: CanonicalRecord) -> list[TrainRecord]:
    content = rec.content if isinstance(rec.content, dict) else {}
    q = clean_text(content.get("question"))
    a = clean_text(content.get("answer"))
    if not q or not a:
        return []
    is_reasoning = bool(content.get("is_reasoning")) or ("<<" in a and "####" in a)
    training_type = "reasoning" if is_reasoning else "qa_pair"
    return [
        TrainRecord(
            id=f"{rec.id}_{training_type}",
            training_type=training_type,
            content={"question": q, "answer": a},
            source_id=rec.source_id,
            license=rec.license,
            lineage=list(rec.lineage) + [f"transform:{training_type}"],
            metadata=dict(rec.metadata or {}),
        )
    ]


def transform_instruction(rec: CanonicalRecord) -> list[TrainRecord]:
    content = rec.content if isinstance(rec.content, dict) else {}
    instruction = clean_text(content.get("instruction"))
    output = clean_text(content.get("output") or content.get("response"))
    if not instruction or not output:
        # Doc → instruction: title + text
        title = clean_text(content.get("title") or "")
        text = clean_text(content.get("text") or "")
        if text:
            instruction = f"Explain the key points from: {title}" if title else "Summarize the following documentation."
            output = text
        else:
            return []
    return [
        TrainRecord(
            id=f"{rec.id}_instruction",
            training_type="instruction",
            content={
                "instruction": instruction,
                "input": clean_text(content.get("input") or ""),
                "output": output,
            },
            source_id=rec.source_id,
            license=rec.license,
            lineage=list(rec.lineage) + ["transform:instruction"],
            metadata=dict(rec.metadata or {}),
        )
    ]


def transform_conversation(rec: CanonicalRecord) -> list[TrainRecord]:
    content = rec.content if isinstance(rec.content, dict) else {}
    msgs = content.get("messages") or []
    if len(msgs) < 2:
        return []
    cleaned = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        role = (m.get("role") or "user").lower()
        if role in {"human", "prompt"}:
            role = "user"
        if role in {"gpt", "bot", "model"}:
            role = "assistant"
        text = clean_text(m.get("content") or "")
        if not text:
            continue
        cleaned.append({"role": role, "content": text})
    if len(cleaned) < 2:
        return []
    return [
        TrainRecord(
            id=f"{rec.id}_conversation",
            training_type="conversation",
            content={"messages": cleaned},
            source_id=rec.source_id,
            license=rec.license,
            lineage=list(rec.lineage) + ["transform:conversation"],
            metadata=dict(rec.metadata or {}),
        )
    ]


def transform_knowledge(rec: CanonicalRecord) -> list[TrainRecord]:
    """Build a knowledge object from factual QA / doc content."""
    content = rec.content if isinstance(rec.content, dict) else {}
    if "question" in content and "answer" in content:
        title = clean_text(content.get("question"))
        body = clean_text(content.get("answer"))
    elif "text" in content:
        title = clean_text(content.get("title") or "Knowledge")
        body = clean_text(content.get("text"))
    else:
        return []
    if not body:
        return []
    return [
        TrainRecord(
            id=f"{rec.id}_knowledge",
            training_type="knowledge",
            content={
                "title": title,
                "canonical_answer": body,
                "knowledge_type": "fact" if "question" in content else "reference",
            },
            source_id=rec.source_id,
            license=rec.license,
            lineage=list(rec.lineage) + ["transform:knowledge"],
            metadata=dict(rec.metadata or {}),
        )
    ]


_DISPATCH: dict[str, Callable[[CanonicalRecord], list[TrainRecord]]] = {
    "qa": transform_qa,
    "instruction": transform_instruction,
    "conversation": transform_conversation,
    "raw": transform_instruction,  # docs/raw → instruction (+ knowledge)
}


def transform_record(rec: CanonicalRecord) -> list[TrainRecord]:
    """Apply the appropriate transformer(s) for a canonical record."""
    fn = _DISPATCH.get(rec.record_type, transform_instruction)
    out = fn(rec)
    # Additionally emit knowledge objects for QA / docs
    if rec.record_type in {"qa", "raw"}:
        out.extend(transform_knowledge(rec))
    for tr in out:
        tr.metadata = dict(tr.metadata or {})
        tr.metadata.setdefault("source_name", rec.source)
        tr.metadata.setdefault("source_url", (rec.metadata or {}).get("source_url") or "")
        tr.metadata.setdefault("category", (rec.metadata or {}).get("category"))
        tr.metadata.setdefault("subcategory", (rec.metadata or {}).get("subcategory"))
    return out


def train_record_to_atlas(tr: TrainRecord, *, seq: int) -> dict[str, Any]:
    """Convert a TrainRecord into atlas dataset_schema-shaped staging record."""
    category = (tr.metadata or {}).get("category") or "06_science_engineering"
    subcategory = (tr.metadata or {}).get("subcategory") or "general"
    content = tr.content

    if tr.training_type in {"qa_pair", "reasoning"}:
        messages = [
            {"role": "user", "content": content.get("question") or ""},
            {"role": "assistant", "content": content.get("answer") or ""},
        ]
        atlas_type = "reasoning" if tr.training_type == "reasoning" else "qa"
    elif tr.training_type == "instruction":
        user = content.get("instruction") or ""
        if content.get("input"):
            user = f"{user}\n\n{content['input']}"
        messages = [
            {"role": "user", "content": user.strip()},
            {"role": "assistant", "content": content.get("output") or ""},
        ]
        atlas_type = "instruction"
    elif tr.training_type == "conversation":
        messages = list(content.get("messages") or [])
        atlas_type = "conversation"
    else:  # knowledge
        messages = [
            {"role": "user", "content": content.get("title") or "Explain this."},
            {"role": "assistant", "content": content.get("canonical_answer") or ""},
        ]
        atlas_type = "qa"

    safe_cat = re.sub(r"[^a-z0-9_]", "", str(category))
    safe_sub = re.sub(r"[^a-z0-9_]", "", str(subcategory).replace("-", "_"))
    atlas_id = f"{safe_cat}_{safe_sub}_{tr.source_id or 'src'}_{tr.training_type}_{seq:06d}"

    return {
        "id": atlas_id,
        "category": category,
        "subcategory": subcategory,
        "type": atlas_type,
        "source": {
            "name": (tr.metadata or {}).get("source_name") or tr.source_id or "unknown",
            "url": (tr.metadata or {}).get("source_url") or "",
            "license": tr.license,
            "date": "",
        },
        "messages": messages,
        "language": "en",
        "difficulty": 0,
        "tags": sorted({tr.source_id or "source", tr.training_type, str(subcategory).replace("_", "-")}),
        "quality_score": 0,
        "verified": False,
        "notes": f"transformed:{tr.training_type}",
        "training_type": tr.training_type,
        "lineage": {
            "source": tr.source_id,
            "transformations": list(tr.lineage),
            "knowledge_object": atlas_id,
            "curated_dataset": "",
            "training_view": "",
            "future_model": "",
        },
        "metadata": {
            "transform_id": tr.id,
            "knowledge_type": content.get("knowledge_type"),
            **{k: v for k, v in (tr.metadata or {}).items() if k not in {"category", "subcategory"}},
        },
    }


def run_transform(
    root: str | Path,
    source_id: str,
    *,
    limit: int | None = None,
    prefer: str = "cleaned",  # cleaned | atlas_staging | normalized
) -> dict[str, Any]:
    root = Path(root).resolve()
    etl_dir = root / "metadata" / "etl" / source_id
    if prefer == "atlas_staging":
        src = etl_dir / "atlas_staging.jsonl"
    elif prefer == "normalized":
        src = etl_dir / "normalized.jsonl"
    else:
        src = etl_dir / "cleaned.jsonl"
        if not src.exists():
            src = etl_dir / "atlas_staging.jsonl"

    if not src.exists():
        return {
            "source_id": source_id,
            "status": "failed",
            "errors": [f"missing ETL input: {src} — run etl first"],
            "summary": "Transform failed: no ETL input",
        }

    rows = read_jsonl(src)
    if limit is not None:
        rows = rows[: int(limit)]

    train_records: list[TrainRecord] = []
    skipped = 0
    for row in rows:
        canonical = _as_canonical(row)
        if canonical is None:
            skipped += 1
            continue
        if not canonical.source_id:
            canonical.source_id = source_id
        produced = transform_record(canonical)
        if not produced:
            skipped += 1
        train_records.extend(produced)

    type_counts: dict[str, int] = {}
    for tr in train_records:
        type_counts[tr.training_type] = type_counts.get(tr.training_type, 0) + 1

    atlas_rows = [
        train_record_to_atlas(tr, seq=i)
        for i, tr in enumerate(train_records, start=1)
    ]

    write_jsonl(etl_dir / "transformed.jsonl", [t.to_dict() for t in train_records])
    write_jsonl(etl_dir / "transformed_atlas.jsonl", atlas_rows)

    report = {
        "source_id": source_id,
        "status": "passed",
        "input": str(src),
        "input_records": len(rows),
        "transformed": len(train_records),
        "atlas_records": len(atlas_rows),
        "skipped": skipped,
        "type_counts": type_counts,
        "generated_at": utc_now(),
        "output_dir": str(etl_dir),
        "summary": (
            f"Transform {source_id}: {len(train_records)} train records "
            f"from {len(rows)} inputs ({skipped} skipped)"
        ),
    }
    (etl_dir / "transform_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report
