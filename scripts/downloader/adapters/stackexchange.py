#!/usr/bin/env python3
"""StackExchange / Archive.org dump source adapter."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .base import DownloadResult, DownloadStatus, SourceAdapter


class StackExchangeAdapter(SourceAdapter):
    name = "stackexchange"
    description = "Download StackExchange data dumps (Archive.org / direct XML)"

    def supports(self, source: dict[str, Any]) -> bool:
        if source.get("source_type") in {"stackexchange", "stack_overflow", "stackoverflow"}:
            return True
        url = (source.get("url") or "").lower()
        name = (source.get("name") or "").lower()
        return any(
            token in url or token in name
            for token in ("stackexchange", "stackoverflow", "stack overflow", "archive.org/details/stackexchange")
        )

    def download(self, source: dict[str, Any], *, dry_run: bool = False) -> DownloadResult:
        url = (source.get("download_url") or source.get("url") or "").strip()
        source_ref = self.source_ref(source)
        result = DownloadResult(
            source_ref=source_ref,
            adapter=self.name,
            status=DownloadStatus.PLANNED,
            url=url,
        )

        # Listing pages (archive.org/details/…) are metadata; prefer an explicit dump URL.
        dump_url = (source.get("download_url") or self.config.get("download_url") or "").strip()
        if not dump_url:
            if url.lower().endswith((".7z", ".zip", ".xml", ".xml.gz", ".gz")):
                dump_url = url
            else:
                # Fall back to caching the listing/metadata page so acquisition is auditable
                dump_url = url
                result.warnings.append(
                    "no explicit dump URL; caching listing/metadata page only "
                    "(set download_url for full dump)"
                )

        if not dump_url:
            result.status = DownloadStatus.FAILED
            result.errors.append("missing StackExchange download URL")
            result.summary = "StackExchange source missing URL"
            return result

        parsed = urlparse(dump_url)
        filename = parsed.path.rstrip("/").split("/")[-1] or "stackexchange-listing"
        result.url = dump_url
        result.files = [{"filename": filename, "url": dump_url}]

        if dry_run:
            result.summary = f"Would download StackExchange artifact {dump_url}"
            return result

        existing = self.cache.get(source_ref)
        if existing is not None and not self.config.get("force"):
            result.status = DownloadStatus.CACHED
            result.entries = [existing]
            result.summary = f"Cache hit for {dump_url}"
            return result

        try:
            entry = self.cache.download_url(
                dump_url,
                source_ref,
                adapter=self.name,
                metadata={"filename": filename},
                force=bool(self.config.get("force")),
            )
        except Exception as exc:
            result.status = DownloadStatus.FAILED
            result.errors.append(str(exc))
            result.summary = "StackExchange download failed"
            return result

        result.status = DownloadStatus.DOWNLOADED
        result.entries = [entry]
        result.summary = f"Downloaded StackExchange artifact ({entry.size_bytes} bytes)"
        result.files = [
            {
                "filename": filename,
                "url": dump_url,
                "checksum": entry.checksum,
                "size_bytes": entry.size_bytes,
            }
        ]
        return result
