"""validator.py — Training view artifact validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class TrainingViewValidator:
    """Validate training view inputs and outputs."""

    @staticmethod
    def validate_schema(record: dict[str, Any]) -> list[str]:
        required = {
            "view_id",
            "record_id",
            "source",
            "license",
            "quality_score",
            "category",
            "messages",
            "lineage",
        }
        missing = required - set(record.keys())
        errors = [f"missing required fields: {missing}"] if missing else []
        messages = record.get("messages", [])
        if not isinstance(messages, list) or len(messages) < 2:
            errors.append("messages must be a list with at least 2 turns")
        return errors

    @staticmethod
    def validate_duplicates(records: list[dict[str, Any]]) -> list[str]:
        seen = set()
        dupes = []
        for rec in records:
            rid = rec.get("record_id")
            if rid in seen:
                dupes.append(str(rid))
            seen.add(str(rid))
        return [f"duplicate record_id: {rid}" for rid in dupes]

    @staticmethod
    def validate_licenses(records: list[dict[str, Any]]) -> list[str]:
        from .filters import LicenseFilter

        return [
            f"denied license for record {rec.get('record_id')}: {rec.get('license')}"
            for rec in records
            if not LicenseFilter.is_allowed(rec.get("license", ""))
        ]

    @staticmethod
    def validate_split_leakage(
        train: list[dict[str, Any]],
        validation: list[dict[str, Any]],
        eval_: list[dict[str, Any]],
    ) -> list[str]:
        train_ids = {r.get("record_id") for r in train}
        val_ids = {r.get("record_id") for r in validation}
        eval_ids = {r.get("record_id") for r in eval_}
        leakage = (train_ids & val_ids) | (train_ids & eval_ids) | (val_ids & eval_ids)
        return [f"split leakage record_id: {rid}" for rid in sorted(leakage)]

    @staticmethod
    def validate_provenance(records: list[dict[str, Any]]) -> list[str]:
        required = {
            "source_attribution",
            "knowledge_object",
            "curated_release",
            "training_view",
        }
        errors = []
        for rec in records:
            lineage = rec.get("lineage") or {}
            missing = required - set(lineage.keys())
            if missing:
                errors.append(f"provenance missing for {rec.get('record_id')}: {missing}")
        return errors

    def validate_view(
        self,
        manifest: dict[str, Any],
        train: list[dict[str, Any]],
        validation: list[dict[str, Any]],
        eval_: list[dict[str, Any]],
    ) -> list[str]:
        errors: list[str] = []
        from .manifest import TrainingViewManifest as TM

        errors.extend(TM().validate(manifest))
        for rec in train + validation + eval_:
            errors.extend(self.validate_schema(rec))
        errors.extend(self.validate_duplicates(train + validation + eval_))
        errors.extend(self.validate_licenses(train + validation + eval_))
        errors.extend(self.validate_split_leakage(train, validation, eval_))
        errors.extend(self.validate_provenance(train + validation + eval_))
        return errors
