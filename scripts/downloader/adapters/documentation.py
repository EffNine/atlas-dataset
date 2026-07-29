#!/usr/bin/env python3
"""Documentation / generic web page source adapter."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .base import DownloadResult, DownloadStatus, SourceAdapter


class DocumentationAdapter(SourceAdapter):
    name = "documentation"
    description = "Fetch and cache documentation / web pages"

    def supports(self, source: dict[str, Any]) -> bool:
        if source.get("source_type") in {"documentation", "docs", "web"}:
            return True
        url = (source.get("url") or "").strip().lower()
        if not url.startswith("http"):
            return False
        # Catch-all for HTTP(S) that other adapters do not claim
        blocked = ("huggingface.co", "github.com", "arxiv.org", "stackexchange", "archive.org")
        return not any(b in url for b in blocked)

    def download(self, source: dict[str, Any], *, dry_run: bool = False) -> DownloadResult:
        url = (source.get("url") or "").strip()
        if not url:
            return DownloadResult(
                source_ref=self.source_ref(source),
                adapter=self.name,
                status=DownloadStatus.FAILED,
                errors=["missing url"],
                summary="Documentation source missing url",
            )

        source_ref = self.source_ref(source)
        parsed = urlparse(url)
        filename = parsed.path.rstrip("/").split("/")[-1] or "index.html"
        result = DownloadResult(
            source_ref=source_ref,
            adapter=self.name,
            status=DownloadStatus.PLANNED,
            url=url,
            files=[{"filename": filename, "url": url}],
            metadata={"host": parsed.netloc},
        )

        if dry_run:
            result.summary = f"Would fetch documentation page {url}"
            return result

        existing = self.cache.get(source_ref)
        if existing is not None and not self.config.get("force"):
            result.status = DownloadStatus.CACHED
            result.entries = [existing]
            result.summary = f"Cache hit for {url}"
            return result

        try:
            entry = self.cache.download_url(
                url,
                source_ref,
                adapter=self.name,
                metadata={"filename": filename, "host": parsed.netloc},
                force=bool(self.config.get("force")),
            )
        except Exception as exc:
            result.status = DownloadStatus.FAILED
            result.errors.append(str(exc))
            result.summary = f"Documentation fetch failed for {url}"
            return result

        result.status = DownloadStatus.DOWNLOADED
        result.entries = [entry]
        result.summary = f"Fetched {url} ({entry.size_bytes} bytes)"
        result.files = [
            {
                "filename": filename,
                "url": url,
                "checksum": entry.checksum,
                "size_bytes": entry.size_bytes,
            }
        ]
        return result
