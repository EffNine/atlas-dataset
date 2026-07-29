#!/usr/bin/env python3
"""Source adapter registry — pick the right adapter for a source record."""

from __future__ import annotations

from typing import Any

from .base import SourceAdapter
from .arxiv import ArxivAdapter
from .documentation import DocumentationAdapter
from .github import GitHubAdapter
from .huggingface import HuggingFaceAdapter
from .stackexchange import StackExchangeAdapter
from ..cache import CacheManager


# Order matters: more specific adapters first; DocumentationAdapter is the HTTP fallback.
ADAPTER_CLASSES: tuple[type[SourceAdapter], ...] = (
    HuggingFaceAdapter,
    GitHubAdapter,
    ArxivAdapter,
    StackExchangeAdapter,
    DocumentationAdapter,
)


def build_adapters(
    cache: CacheManager,
    config: dict[str, Any] | None = None,
) -> list[SourceAdapter]:
    """Instantiate the default adapter set sharing one CacheManager."""
    cfg = config or {}
    adapters: list[SourceAdapter] = []
    for cls in ADAPTER_CLASSES:
        adapter_cfg = dict(cfg.get(cls.name, {}) or {})
        # Bubble up shared knobs
        for key in ("force", "max_files", "files", "ref", "download_url"):
            if key in cfg and key not in adapter_cfg:
                adapter_cfg[key] = cfg[key]
        adapters.append(cls(cache, config=adapter_cfg))
    return adapters


def select_adapter(
    source: dict[str, Any],
    adapters: list[SourceAdapter],
) -> SourceAdapter | None:
    """Return the first adapter that supports *source*, or None."""
    for adapter in adapters:
        if adapter.supports(source):
            return adapter
    return None
