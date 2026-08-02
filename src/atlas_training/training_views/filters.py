"""filters.py — License, quality, difficulty, domain, and provenance filtering."""

from __future__ import annotations

from typing import Any


class LicenseFilter:
    """License policy enforcement."""

    DENIED_LICENSES = frozenset(
        {
            "unknown",
            "CC-BY-NC",
            "CC-BY-NC-SA",
            "CC-BY-NC-ND",
            "GFDL",
            "non-commercial",
            "nc",
            "restricted",
            "custom",
        }
    )

    @classmethod
    def is_allowed(cls, license_id: str) -> bool:
        lic = (license_id or "").strip().lower()
        if not lic:
            return False
        if lic in cls.DENIED_LICENSES:
            return False
        if "nc" in lic:
            return False
        return True


class QualityFilter:
    """Quality threshold filtering."""

    def __init__(self, min_quality: int = 7) -> None:
        if not (0 <= min_quality <= 10):
            raise ValueError(f"min_quality must be 0-10, got {min_quality}")
        self.min_quality = min_quality

    def passes(self, record: dict[str, Any]) -> bool:
        try:
            return int(record.get("quality_score", 0)) >= self.min_quality
        except (TypeError, ValueError):
            return False


class DifficultyFilter:
    """Difficulty distribution filtering."""

    def passes(self, record: dict[str, Any], *, min_difficulty: int, max_difficulty: int) -> bool:
        try:
            d = int(record.get("difficulty", 0))
        except (TypeError, ValueError):
            return False
        return min_difficulty <= d <= max_difficulty


class DomainFilter:
    """Domain and category filtering."""

    def passes(self, record: dict[str, Any], allowed_source_ids: list[str]) -> bool:
        if not allowed_source_ids:
            return True
        return record.get("source", {}).get("source_id") in set(allowed_source_ids)


class ProvenanceFilter:
    """Provenance completeness filter."""

    REQUIRED_LINEAGE = {
        "source",
        "transformations",
        "knowledge_object",
        "curated_dataset",
        "training_view",
        "future_model",
    }

    @classmethod
    def passes(cls, record: dict[str, Any]) -> bool:
        lineage = record.get("lineage") or {}
        return cls.REQUIRED_LINEAGE.issubset(lineage.keys()) and bool(lineage.get("source"))


class TrainingViewFilters:
    """Compose all training view filters."""

    def __init__(self, *, min_quality: int = 7) -> None:
        self.license_filter = LicenseFilter()
        self.quality_filter = QualityFilter(min_quality=min_quality)
        self.difficulty_filter = DifficultyFilter()
        self.domain_filter = DomainFilter()
        self.provenance_filter = ProvenanceFilter()

    def is_eligible(self, record: dict[str, Any], config: dict[str, Any]) -> bool:
        if not self.license_filter.is_allowed(record.get("license", "")):
            return False
        if not self.quality_filter.passes(record):
            return False
        d = record.get("difficulty", 0)
        try:
            d = int(d)
        except (TypeError, ValueError):
            return False
        min_d, max_d = config.get("difficulty_range", [1, 10])
        if not (min_d <= d <= max_d):
            return False
        if not self.domain_filter.passes(record, config.get("source_ids", [])):
            return False
        if not self.provenance_filter.passes(record):
            return False
        return True
