#!/usr/bin/env python3
"""Atlas Downloader v1.6 — Source adapters + content-addressable cache.

Enables Atlas to download data from external sources (HuggingFace, GitHub,
documentation sites, StackExchange dumps, arXiv) into ``raw/.cache/`` with
resume support, SHA-256 verification, retry/backoff, and a SQLite index.
"""

from __future__ import annotations

from .cache import CacheEntry, CacheManager
from .download_agent import DownloadAgent
from .adapters.base import DownloadResult, DownloadStatus, SourceAdapter
from .adapters import build_adapters, select_adapter

__all__ = [
    "CacheEntry",
    "CacheManager",
    "DownloadAgent",
    "DownloadResult",
    "DownloadStatus",
    "SourceAdapter",
    "build_adapters",
    "select_adapter",
]
