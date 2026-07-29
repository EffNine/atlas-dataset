#!/usr/bin/env python3
"""arXiv paper source adapter (PDF + abstract metadata via stdlib HTTP)."""

from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree as ET

from .base import DownloadResult, DownloadStatus, SourceAdapter
from ..http_util import fetch_bytes

_ARXIV_ID_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/|arxiv:)?(?P<id>\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+/\d{7})",
    re.IGNORECASE,
)


class ArxivAdapter(SourceAdapter):
    name = "arxiv"
    description = "Download arXiv PDFs and Atom abstract metadata"

    def supports(self, source: dict[str, Any]) -> bool:
        if source.get("source_type") == "arxiv":
            return True
        url = (source.get("url") or "").lower()
        name = (source.get("name") or "").lower()
        return "arxiv.org" in url or "arxiv" in name or bool(_ARXIV_ID_RE.search(url))

    def download(self, source: dict[str, Any], *, dry_run: bool = False) -> DownloadResult:
        arxiv_id = self._arxiv_id(source)
        source_ref = self.source_ref(source)
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        abs_url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
        result = DownloadResult(
            source_ref=source_ref,
            adapter=self.name,
            status=DownloadStatus.PLANNED,
            url=pdf_url,
            metadata={"arxiv_id": arxiv_id},
            files=[
                {"filename": f"{arxiv_id}.pdf", "url": pdf_url},
                {"filename": f"{arxiv_id}.atom.xml", "url": abs_url},
            ],
        )

        if dry_run:
            result.summary = f"Would download arXiv {arxiv_id} PDF + abstract"
            return result

        entries = []
        errors: list[str] = []

        # Abstract / metadata (small)
        meta_ref = f"{source_ref}:abstract"
        try:
            body, _, content_type = fetch_bytes(
                abs_url,
                timeout=self.cache.timeout,
                max_retries=self.cache.max_retries,
                backoff_base=self.cache.backoff_base,
            )
            # Light validation that we got Atom XML
            try:
                ET.fromstring(body)
            except ET.ParseError:
                result.warnings.append("abstract response was not valid XML")
            entry = self.cache.put_bytes(
                meta_ref,
                body,
                url=abs_url,
                adapter=self.name,
                content_type=content_type,
                metadata={"arxiv_id": arxiv_id, "kind": "abstract"},
            )
            entries.append(entry)
        except Exception as exc:
            errors.append(f"abstract: {exc}")

        # PDF
        pdf_ref = f"{source_ref}:pdf"
        try:
            entry = self.cache.download_url(
                pdf_url,
                pdf_ref,
                adapter=self.name,
                metadata={"arxiv_id": arxiv_id, "kind": "pdf"},
                force=bool(self.config.get("force")),
            )
            entries.append(entry)
        except Exception as exc:
            errors.append(f"pdf: {exc}")

        result.errors = errors
        result.entries = entries
        if entries and not errors:
            result.status = DownloadStatus.DOWNLOADED
            result.summary = f"Downloaded arXiv {arxiv_id} ({len(entries)} artifact(s))"
        elif entries:
            result.status = DownloadStatus.DOWNLOADED
            result.warnings.extend(errors)
            result.summary = f"Partial download for arXiv {arxiv_id}"
        else:
            result.status = DownloadStatus.FAILED
            result.summary = f"Failed to download arXiv {arxiv_id}"

        self.cache.write_manifest(
            source_ref,
            [
                {
                    "checksum": e.checksum,
                    "size_bytes": e.size_bytes,
                    "source_ref": e.source_ref,
                    "kind": (e.metadata or {}).get("kind"),
                }
                for e in entries
            ],
        )
        return result

    def _arxiv_id(self, source: dict[str, Any]) -> str:
        for key in ("arxiv_id", "id", "name", "url"):
            value = (source.get(key) or "").strip()
            match = _ARXIV_ID_RE.search(value)
            if match:
                return match.group("id")
        raise ValueError(f"cannot determine arXiv id from source {source.get('id')}")
