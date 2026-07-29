#!/usr/bin/env python3
"""Extractor registry — pick the right extractor for a cached file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Extractor
from .json_extractors import JsonExtractor, JsonlExtractor
from .parquet_extractor import ParquetExtractor
from .text_extractors import HtmlExtractor, MarkdownExtractor
from ..types import RawRecord

# Order: more specific first. HTML sniffing is last among text formats.
EXTRACTOR_CLASSES: tuple[type[Extractor], ...] = (
    ParquetExtractor,
    JsonlExtractor,
    JsonExtractor,
    MarkdownExtractor,
    HtmlExtractor,
)


def build_extractors() -> list[Extractor]:
    return [cls() for cls in EXTRACTOR_CLASSES]


def select_extractor(
    path: Path,
    extractors: list[Extractor] | None = None,
    *,
    format_hint: str = "",
) -> Extractor | None:
    extractors = extractors or build_extractors()
    for ext in extractors:
        if ext.supports(path, format_hint=format_hint):
            return ext
    return None


def extract_file(
    path: Path,
    *,
    source_ref: str = "",
    format_hint: str = "",
    context: dict[str, Any] | None = None,
) -> tuple[Extractor | None, list[RawRecord]]:
    extractor = select_extractor(path, format_hint=format_hint)
    if extractor is None:
        return None, []
    return extractor, extractor.extract(path, source_ref=source_ref, context=context)
