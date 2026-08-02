"""Base class for expert source adapters.

Each adapter:
- declares static source metadata (id, name, url, license, domain, tier)
- yields raw source rows via iter_raw()
- converts a raw row into an Atlas Expert Record via to_record()
- provides deterministic per-source id prefix and original_id derivation
"""

from __future__ import annotations

import abc
import datetime
from typing import Any, Iterator

from ..util import content_hash


class SourceAdapter(abc.ABC):
    """Common interface for GO-calibrated expert sources."""

    # Static source metadata (overridden per adapter)
    source_id: str = ""
    source_name: str = ""
    source_url: str = ""
    source_license: str = ""
    domain: str = ""
    expert_tier: str = "E2"
    id_prefix: str = "expert"
    accessed_at: str = ""
    stream_source: str = ""

    def __init__(self, accessed_at: str | None = None) -> None:
        self.accessed_at = accessed_at or datetime.date.today().isoformat()

    @abc.abstractmethod
    def iter_raw(self, limit: int | None = None) -> Iterator[dict]:
        """Yield raw source rows. Must be deterministic in order."""

    @abc.abstractmethod
    def to_record(self, raw: dict, idx: int) -> dict:
        """Convert one raw row into an Atlas Expert Record (schema v0.1)."""

    def original_id(self, raw: dict, *parts: str) -> str:
        """Deterministic original id for sources without an upstream id."""
        return f"{self.source_id.replace('-', '_')}_{content_hash(*parts)}"

    def source_meta(self) -> dict:
        return {
            "source_id": self.source_id,
            "name": self.source_name,
            "url": self.source_url,
            "license": self.source_license,
            "accessed_at": self.accessed_at,
        }
