#!/usr/bin/env python3
"""JSON / JSONL extractors (stdlib)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import Extractor
from ..types import RawRecord


class JsonlExtractor(Extractor):
    name = "jsonl"
    extensions = (".jsonl", ".jsonl.gz")

    def supports(self, path: Path, *, format_hint: str = "") -> bool:
        if format_hint in {"jsonl", "ndjson"}:
            return True
        return path.suffix.lower() == ".jsonl"

    def extract(
        self,
        path: Path,
        *,
        source_ref: str = "",
        context: dict[str, Any] | None = None,
    ) -> list[RawRecord]:
        records: list[RawRecord] = []
        with path.open(encoding="utf-8") as fh:
            for idx, line in enumerate(fh):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rid = str(obj.get("id") or f"{path.stem}_{idx:06d}")
                records.append(
                    RawRecord(
                        id=rid,
                        content=obj,
                        source_ref=source_ref or str(path),
                        format="jsonl",
                        metadata={"line": idx, "filename": path.name},
                    )
                )
        return records


class JsonExtractor(Extractor):
    name = "json"
    extensions = (".json",)

    def supports(self, path: Path, *, format_hint: str = "") -> bool:
        if format_hint == "json":
            return True
        return path.suffix.lower() == ".json" and path.suffix.lower() != ".jsonl"

    def extract(
        self,
        path: Path,
        *,
        source_ref: str = "",
        context: dict[str, Any] | None = None,
    ) -> list[RawRecord]:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows: list[Any]
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            for key in ("data", "rows", "examples", "items", "records"):
                if isinstance(data.get(key), list):
                    rows = data[key]
                    break
            else:
                rows = [data]
        else:
            return []

        records: list[RawRecord] = []
        for idx, obj in enumerate(rows):
            if not isinstance(obj, dict):
                obj = {"value": obj}
            rid = str(obj.get("id") or f"{path.stem}_{idx:06d}")
            records.append(
                RawRecord(
                    id=rid,
                    content=obj,
                    source_ref=source_ref or str(path),
                    format="json",
                    metadata={"index": idx, "filename": path.name},
                )
            )
        return records
