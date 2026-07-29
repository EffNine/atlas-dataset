#!/usr/bin/env python3
"""Parquet extractor — optional ``pyarrow`` dependency."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Extractor
from ..types import RawRecord


class ParquetExtractor(Extractor):
    name = "parquet"
    extensions = (".parquet",)

    def supports(self, path: Path, *, format_hint: str = "") -> bool:
        if format_hint == "parquet":
            return True
        name = path.name.lower()
        return name.endswith(".parquet") or ".parquet" in name

    def extract(
        self,
        path: Path,
        *,
        source_ref: str = "",
        context: dict[str, Any] | None = None,
    ) -> list[RawRecord]:
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise RuntimeError(
                "Parquet extraction requires pyarrow. "
                "Install with: pip install pyarrow"
            ) from exc

        context = context or {}
        limit = context.get("limit")
        table = pq.read_table(path)
        if limit is not None:
            table = table.slice(0, int(limit))

        columns = table.column_names
        records: list[RawRecord] = []
        for idx in range(table.num_rows):
            row = {col: _cell(table.column(col)[idx].as_py()) for col in columns}
            rid = str(row.get("id") or f"{path.stem}_{idx:06d}")
            # sanitize id
            rid = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in rid)
            records.append(
                RawRecord(
                    id=rid,
                    content=row,
                    source_ref=source_ref or str(path),
                    format="parquet",
                    metadata={
                        "index": idx,
                        "filename": path.name,
                        "columns": columns,
                    },
                )
            )
        return records


def _cell(value: Any) -> Any:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.hex()
    return value
