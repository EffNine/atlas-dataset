#!/usr/bin/env python3
"""HTML and Markdown extractors (stdlib)."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .base import Extractor
from ..types import RawRecord


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag in {"p", "div", "li", "h1", "h2", "h3", "h4"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self._chunks.append(text)

    def text(self) -> str:
        raw = " ".join(self._chunks)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


class HtmlExtractor(Extractor):
    name = "html"
    extensions = (".html", ".htm")

    def supports(self, path: Path, *, format_hint: str = "") -> bool:
        if format_hint in {"html", "htm", "documentation"}:
            return True
        suffix = path.suffix.lower()
        if suffix in {".html", ".htm"}:
            return True
        # Cached docs pages may have no extension; sniff content
        try:
            head = path.read_bytes()[:200].lower()
        except OSError:
            return False
        return b"<html" in head or b"<!doctype html" in head

    def extract(
        self,
        path: Path,
        *,
        source_ref: str = "",
        context: dict[str, Any] | None = None,
    ) -> list[RawRecord]:
        html = path.read_text(encoding="utf-8", errors="replace")
        parser = _TextExtractor()
        parser.feed(html)
        text = parser.text()
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else path.stem
        return [
            RawRecord(
                id=f"{path.stem}_doc",
                content={"title": title, "text": text},
                source_ref=source_ref or str(path),
                format="html",
                metadata={"filename": path.name, "char_count": len(text)},
            )
        ]


class MarkdownExtractor(Extractor):
    name = "markdown"
    extensions = (".md", ".markdown")

    def supports(self, path: Path, *, format_hint: str = "") -> bool:
        if format_hint in {"markdown", "md"}:
            return True
        return path.suffix.lower() in {".md", ".markdown"}

    def extract(
        self,
        path: Path,
        *,
        source_ref: str = "",
        context: dict[str, Any] | None = None,
    ) -> list[RawRecord]:
        text = path.read_text(encoding="utf-8", errors="replace")
        heading_re = re.compile(r"(?m)^(#{1,3})\s+(.+)$")
        matches = list(heading_re.finditer(text))
        records: list[RawRecord] = []

        if matches:
            for idx, match in enumerate(matches):
                start = match.end()
                end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
                title = match.group(2).strip()
                body = text[start:end].strip()
                if not body:
                    continue
                records.append(
                    RawRecord(
                        id=f"{path.stem}_sec_{idx:04d}",
                        content={"title": title, "text": body},
                        source_ref=source_ref or str(path),
                        format="markdown",
                        metadata={"filename": path.name, "heading": title},
                    )
                )

        if not records:
            records.append(
                RawRecord(
                    id=f"{path.stem}_md",
                    content={"title": path.stem, "text": text},
                    source_ref=source_ref or str(path),
                    format="markdown",
                    metadata={"filename": path.name},
                )
            )
        return records
