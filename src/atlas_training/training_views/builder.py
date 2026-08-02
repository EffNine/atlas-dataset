"""builder.py — Training view build orchestrator."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .filters import TrainingViewFilters
from .formatter import TrainingViewFormatter
from .manifest import TrainingViewManifest
from .splitter import DeterministicSplitter
from .validator import TrainingViewValidator
from .writer import TrainingViewWriter


class TrainingViewBuilder:
    """Coordinate filtering, splitting, formatting, manifesting, and validation."""

    def __init__(self, *, config: dict[str, Any], writer: TrainingViewWriter | None = None) -> None:
        self.config = config
        self.filters = TrainingViewFilters(min_quality=int(config.get("min_quality", 7)))
        self.splitter = DeterministicSplitter(seed="atlas-training-views-v0.1")
        self.manifest_builder = TrainingViewManifest()
        self.writer = writer or TrainingViewWriter(mode="safe")
        self.validator = TrainingViewValidator()

    def build(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        view_id = self.config["view_id"]
        eligible = [r for r in records if self.filters.is_eligible(r, self.config)]
        if not eligible:
            return {
                "status": "blocked",
                "view_id": view_id,
                "source_records": len(records),
                "eligible_records": 0,
            }

        train, validation, eval_ = self.splitter.split(
            eligible,
            train_ratio=float(self.config.get("train_ratio", 0.8)),
            validation_ratio=float(self.config.get("validation_ratio", 0.1)),
        )
        formatter = TrainingViewFormatter(
            view_id=view_id,
            curated_release=self.config.get("source_release", "v0.1"),
        )
        train_f = formatter.format_batch(train)
        validation_f = formatter.format_batch(validation)
        eval_f = formatter.format_batch(eval_)
        filter_counts = {
            "quality_below": len(records) - len(eligible),
            "license_denied": 0,
            "lifecycle_invalid": 0,
            "eligibility_missing": 0,
            "pending_review": 0,
            "rejected": 0,
            "lineage_incomplete": 0,
        }
        manifest = self.manifest_builder.create(
            view_id=view_id,
            source_release=self.config.get("source_release", "v0.1"),
            source_records=len(records),
            quality_threshold=int(self.config.get("min_quality", 7)),
            filter_counts=filter_counts,
            records=train_f + validation_f + eval_f,
            target_model=self.config.get("target_model", ""),
        )
        return {
            "status": "ok",
            "view_id": view_id,
            "source_records": len(records),
            "eligible_records": len(eligible),
            "train_records": len(train_f),
            "validation_records": len(validation_f),
            "eval_records": len(eval_f),
            "manifest": manifest,
            "train": train_f,
            "validation": validation_f,
            "eval": eval_f,
        }

    def validate(self, build_result: dict[str, Any]) -> list[str]:
        if build_result.get("status") != "ok":
            return []
        return self.validator.validate_view(
            manifest=build_result["manifest"],
            train=build_result.get("train", []),
            validation=build_result.get("validation", []),
            eval_=build_result.get("eval", []),
        )

    @staticmethod
    def deterministic_run_hash(build_result: dict[str, Any]) -> str:
        payload = json.dumps(build_result, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
