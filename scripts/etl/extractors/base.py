#!/usr/bin/env python3
"""Extractor interface for Atlas ETL v1.7."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..types import RawRecord


class Extractor(ABC):
    """Parse a cached raw file into RawRecords."""

    name: str = "base"
    extensions: tuple[str, ...] = ()

    @abstractmethod
    def supports(self, path: Path, *, format_hint: str = "") -> bool:
        ...

    @abstractmethod
    def extract(
        self,
        path: Path,
        *,
        source_ref: str = "",
        context: dict[str, Any] | None = None,
    ) -> list[RawRecord]:
        ...
