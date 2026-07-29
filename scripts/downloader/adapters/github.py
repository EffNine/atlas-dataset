#!/usr/bin/env python3
"""GitHub repository source adapter (tarball download via stdlib HTTP)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from .base import DownloadResult, DownloadStatus, SourceAdapter

_GH_RE = re.compile(
    r"https?://github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?(?:/|$)",
    re.IGNORECASE,
)


class GitHubAdapter(SourceAdapter):
    name = "github"
    description = "Download GitHub repository tarballs"

    def supports(self, source: dict[str, Any]) -> bool:
        url = (source.get("url") or "").strip()
        if "github.com" in url.lower():
            return True
        return source.get("source_type") == "github"

    def download(self, source: dict[str, Any], *, dry_run: bool = False) -> DownloadResult:
        owner, repo = self._parse(source)
        ref = (source.get("ref") or self.config.get("ref") or "HEAD").strip()
        source_ref = self.source_ref(source)
        # Codeload supports ref names and avoids API auth for public repos
        url = f"https://codeload.github.com/{quote(owner)}/{quote(repo)}/tar.gz/{quote(ref)}"
        result = DownloadResult(
            source_ref=source_ref,
            adapter=self.name,
            status=DownloadStatus.PLANNED,
            url=url,
            metadata={"owner": owner, "repo": repo, "ref": ref},
            files=[{"filename": f"{repo}-{ref}.tar.gz", "url": url}],
        )

        if dry_run:
            result.summary = f"Would download {owner}/{repo}@{ref} tarball"
            return result

        existing = self.cache.get(source_ref)
        if existing is not None and not self.config.get("force"):
            result.status = DownloadStatus.CACHED
            result.entries = [existing]
            result.summary = f"Cache hit for {owner}/{repo}@{ref}"
            return result

        try:
            entry = self.cache.download_url(
                url,
                source_ref,
                adapter=self.name,
                headers={"Accept": "application/octet-stream"},
                metadata={"owner": owner, "repo": repo, "ref": ref},
                force=bool(self.config.get("force")),
            )
        except Exception as exc:
            result.status = DownloadStatus.FAILED
            result.errors.append(str(exc))
            result.summary = f"GitHub download failed for {owner}/{repo}"
            return result

        result.status = DownloadStatus.DOWNLOADED
        result.entries = [entry]
        result.summary = f"Downloaded {owner}/{repo}@{ref} ({entry.size_bytes} bytes)"
        result.files = [
            {
                "filename": f"{repo}-{ref}.tar.gz",
                "url": url,
                "checksum": entry.checksum,
                "size_bytes": entry.size_bytes,
            }
        ]
        return result

    def _parse(self, source: dict[str, Any]) -> tuple[str, str]:
        url = (source.get("url") or "").strip()
        match = _GH_RE.search(url)
        if match:
            return match.group("owner"), match.group("repo")
        name = (source.get("name") or "").strip()
        if "/" in name:
            owner, repo = name.split("/", 1)
            return owner, repo.split()[0]
        raise ValueError(f"cannot parse GitHub owner/repo from source {source.get('id')}")
