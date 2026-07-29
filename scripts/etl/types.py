#!/usr/bin/env python3
"""Shared ETL record types for Atlas v1.7 Extract → Normalize → Clean."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RawRecord:
    """Output of an extractor — source-native fields, minimal structure."""

    id: str
    content: Any
    source_ref: str = ""
    format: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CanonicalRecord:
    """Intermediate Atlas Canonical Schema (pre-curated).

    This is the v1.7 normalize target — not yet the full curated dataset
    schema. Downstream cleaners operate on this shape. Promotion to
    curated ``dataset_schema.json`` records happens in ``to_atlas_record``.
    """

    id: str
    source: str
    license: str
    content: Any
    created_at: str
    lineage: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    source_id: str = ""
    record_type: str = "raw"  # raw | qa | instruction | conversation | reasoning

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def write_jsonl(path, records: list[dict[str, Any]]) -> int:
    from pathlib import Path
    import json

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    return len(records)


def read_jsonl(path) -> list[dict[str, Any]]:
    from pathlib import Path
    import json

    path = Path(path)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
