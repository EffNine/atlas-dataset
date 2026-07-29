#!/usr/bin/env python3
"""Source adapter interface for Atlas Downloader v1.6."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from ..cache import CacheEntry, CacheManager


class DownloadStatus(str, Enum):
    PLANNED = "planned"
    CACHED = "cached"
    DOWNLOADED = "downloaded"
    SKIPPED = "skipped"
    FAILED = "failed"

    def __str__(self) -> str:
        return self.value


@dataclass
class DownloadResult:
    """Outcome of a single adapter download attempt."""

    source_ref: str
    adapter: str
    status: DownloadStatus
    url: str = ""
    summary: str = ""
    entries: list[CacheEntry] = field(default_factory=list)
    files: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in {
            DownloadStatus.DOWNLOADED,
            DownloadStatus.CACHED,
            DownloadStatus.PLANNED,
            DownloadStatus.SKIPPED,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["entries"] = [e.to_dict() if hasattr(e, "to_dict") else e for e in self.entries]
        return payload


class SourceAdapter(ABC):
    """Abstract source adapter.

    Subclasses implement ``supports()`` and ``download()``. All network I/O
    should go through ``CacheManager.download_url`` / ``put_bytes`` so resume,
    checksum verification, and retry behaviour stay centralized.
    """

    name: str = "base"
    description: str = "Base source adapter"

    def __init__(self, cache: CacheManager, config: dict[str, Any] | None = None) -> None:
        self.cache = cache
        self.config = config or {}

    @abstractmethod
    def supports(self, source: dict[str, Any]) -> bool:
        """Return True if this adapter can handle *source*."""
        ...

    @abstractmethod
    def download(self, source: dict[str, Any], *, dry_run: bool = False) -> DownloadResult:
        """Download (or plan) *source* into the cache."""
        ...

    def source_ref(self, source: dict[str, Any]) -> str:
        """Stable cache key for a source record."""
        sid = source.get("id") or source.get("source_id") or source.get("name") or "unknown"
        return f"{self.name}:{sid}"

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"
