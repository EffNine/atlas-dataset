"""
filter.py — Record filtering and eligibility logic for Training Views.

Provides TrainingViewFilter which enforces lifecycle state, verification
status, license, quality, and eligibility constraints on curated records
before view generation.
"""

from __future__ import annotations

import hashlib
from typing import Any

from atlas_constants import (
    VALID_TRAINING_MODELS,
    is_denied_license,
)


class TrainingViewFilter:
    """Filter curated records for training-view eligibility.

    Enforces:
      - Only approved records
      - No rejected or pending records
      - Valid licenses (not denied, not unknown)
      - Minimum quality threshold
      - Model eligibility flags
      - Complete lineage
    """

    def __init__(self, quality_threshold: int = 7) -> None:
        if not (0 <= quality_threshold <= 10):
            raise ValueError(
                f"quality_threshold must be 0-10, got {quality_threshold}"
            )
        self._quality_threshold = quality_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def filter_records(
        self,
        records: list[dict[str, Any]],
        target_model: str = "",
    ) -> list[dict[str, Any]]:
        """Filter a list of records for training-view eligibility.

        Args:
            records: List of curated knowledge-object records.
            target_model: Optional model target (qwen, llama, deepseek).
                         If empty, checks eligibility for all supported models.

        Returns:
            Filtered list of eligible records.

        Raises:
            ValueError: If target_model is specified but not in VALID_TRAINING_MODELS.
        """
        if target_model and target_model not in VALID_TRAINING_MODELS:
            raise ValueError(
                f"target_model must be one of {sorted(VALID_TRAINING_MODELS)}, "
                f"got {target_model!r}"
            )

        result: list[dict[str, Any]] = []
        for rec in records:
            if self._is_eligible(rec, target_model):
                result.append(rec)
        return result

    def filter_report(
        self,
        records: list[dict[str, Any]],
        target_model: str = "",
    ) -> dict[str, Any]:
        """Produce a detailed filter report for a set of records.

        Returns counts of records rejected by each filter criterion.

        Args:
            records: List of curated knowledge-object records.
            target_model: Optional model target.

        Returns:
            A dict with counts per rejection reason.
        """
        report: dict[str, Any] = {
            "total_input": len(records),
            "quality_below": 0,
            "license_denied": 0,
            "lifecycle_invalid": 0,
            "eligibility_missing": 0,
            "pending_review": 0,
            "rejected": 0,
            "lineage_incomplete": 0,
            "eligible": 0,
        }

        for rec in records:
            # Lifecycle / verification checks
            vs = rec.get("verification_status", "")
            if vs == "rejected":
                report["rejected"] += 1
                continue
            if vs != "approved":
                report["pending_review"] += 1
                continue

            # License check
            lic = rec.get("license", "")
            if is_denied_license(lic):
                report["license_denied"] += 1
                continue
            if not lic or lic == "unknown":
                report["license_denied"] += 1
                continue

            # Quality check
            qs = rec.get("quality_score", 0)
            try:
                qs_val = int(qs)
            except (TypeError, ValueError):
                qs_val = 0
            if qs_val < self._quality_threshold:
                report["quality_below"] += 1
                continue

            # Eligibility check
            tve = rec.get("training_view_eligibility", {})
            if target_model:
                if not tve.get(target_model, False):
                    report["eligibility_missing"] += 1
                    continue
            else:
                # Require at least one model
                if not any(tve.get(m, False) for m in VALID_TRAINING_MODELS):
                    report["eligibility_missing"] += 1
                    continue

            # Lineage check
            lineage = rec.get("lineage", {})
            if not self._lineage_complete(lineage):
                report["lineage_incomplete"] += 1
                continue

            report["eligible"] += 1

        return report

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _is_eligible(
        self,
        rec: dict[str, Any],
        target_model: str,
    ) -> bool:
        """Return True if a single record passes all filters."""
        # Lifecycle / verification
        vs = rec.get("verification_status", "")
        if vs != "approved":
            return False

        # License
        lic = rec.get("license", "")
        if is_denied_license(lic) or not lic or lic == "unknown":
            return False

        # Quality
        try:
            qs = int(rec.get("quality_score", 0))
        except (TypeError, ValueError):
            qs = 0
        if qs < self._quality_threshold:
            return False

        # Eligibility
        tve = rec.get("training_view_eligibility", {})
        if target_model:
            if not tve.get(target_model, False):
                return False
        else:
            if not any(tve.get(m, False) for m in VALID_TRAINING_MODELS):
                return False

        # Lineage
        lineage = rec.get("lineage", {})
        if not self._lineage_complete(lineage):
            return False

        return True

    @staticmethod
    def _lineage_complete(lineage: dict[str, Any]) -> bool:
        """Check that required lineage fields are present and non-empty."""
        required = {
            "source", "transformations", "knowledge_object",
            "curated_dataset", "training_view", "future_model",
        }
        return required.issubset(lineage.keys()) and bool(lineage.get("source", ""))

    @staticmethod
    def deterministic_hash(records: list[dict[str, Any]]) -> str:
        """Compute a deterministic hash of a filtered record set.

        Sorts records by ID, then produces a SHA-256 hash of the
        concatenated JSON. This is used to verify reproducibility.
        """
        sorted_recs = sorted(records, key=lambda r: r.get("id", ""))
        raw = "\n".join(
            __import__("json").dumps(r, sort_keys=True, ensure_ascii=False)
            for r in sorted_recs
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
