"""formatter.py — Atlas schema to specialist training format conversion."""

from __future__ import annotations

import copy
from typing import Any


class TrainingViewFormatter:
    """Convert Atlas knowledge-object records to training-view records.

    Output records preserve core content while adding view-specific
    fields and trimming lineage to the training-view contract.
    """

    def __init__(self, view_id: str, curated_release: str) -> None:
        self.view_id = view_id
        self.curated_release = curated_release

    def format(self, record: dict[str, Any]) -> dict[str, Any]:
        out = {
            "view_id": self.view_id,
            "record_id": record.get("id"),
            "source": record.get("source", {}).get("name"),
            "license": record.get("license"),
            "quality_score": record.get("quality_score"),
            "category": record.get("category"),
            "subcategory": record.get("subcategory"),
            "difficulty": record.get("difficulty"),
            "knowledge_type": record.get("knowledge_type"),
            "messages": copy.deepcopy(record.get("messages", [])),
            "eligibility": copy.deepcopy(record.get("training_view_eligibility", {})),
            "lineage": self._trimmed_lineage(record),
        }
        return out

    def _trimmed_lineage(self, record: dict[str, Any]) -> dict[str, Any]:
        lineage = record.get("lineage") or {}
        source_attribution = record.get("source_attribution") or {}
        return {
            "source_attribution": source_attribution.get("source_id"),
            "knowledge_object": lineage.get("knowledge_object"),
            "curated_release": self.curated_release,
            "training_view": self.view_id,
        }

    def format_batch(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.format(r) for r in records]
