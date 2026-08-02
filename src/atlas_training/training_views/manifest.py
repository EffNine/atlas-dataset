from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


class TrainingViewManifest:
    """Deterministic manifest construction for training views."""

    REQUIRED_FIELDS = frozenset(
        {
            "training_view_id",
            "source_release",
            "source_records",
            "generation_policy",
            "filters",
            "created_at",
            "checksum",
        }
    )
    POLICY_REQUIRED_FIELDS = frozenset(
        {
            "quality_threshold",
            "license_filter",
            "lifecycle_filter",
            "eligibility_filter",
            "sampling_strategy",
        }
    )

    def create(
        self,
        *,
        view_id: str,
        source_release: str,
        source_records: int,
        quality_threshold: int,
        filter_counts: dict[str, Any],
        records: list[dict[str, Any]],
        target_model: str = "",
        sampling_strategy: str = "none",
        max_records: int | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        generation_policy = {
            "quality_threshold": quality_threshold,
            "license_filter": "denied_and_unknown_excluded",
            "lifecycle_filter": "approved_only",
            "eligibility_filter": {target_model: True} if target_model else {},
            "sampling_strategy": sampling_strategy,
        }
        if max_records is not None:
            generation_policy["max_records"] = max_records

        filters = {
            "quality_below": filter_counts.get("quality_below", 0),
            "license_denied": filter_counts.get("license_denied", 0),
            "lifecycle_invalid": filter_counts.get("lifecycle_invalid", 0),
            "eligibility_missing": filter_counts.get("eligibility_missing", 0),
            "pending_review": filter_counts.get("pending_review", 0),
            "rejected": filter_counts.get("rejected", 0),
            "lineage_incomplete": filter_counts.get("lineage_incomplete", 0),
        }

        manifest = {
            "training_view_id": view_id,
            "source_release": source_release,
            "source_records": source_records,
            "generation_policy": generation_policy,
            "filters": filters,
            "created_at": created_at or datetime.now(timezone.utc).isoformat(),
            "checksum": {
                "manifest": "__PENDING__",
                "records": self._records_hash(records),
                "algorithm": "SHA-256",
            },
        }
        manifest["checksum"]["manifest"] = self._manifest_hash(manifest)
        return manifest

    def _records_hash(self, records: list[dict[str, Any]]) -> str:
        payload = "\n".join(
            json.dumps(r, sort_keys=True, ensure_ascii=False)
            for r in sorted(records, key=lambda r: r.get("record_id", ""))
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _manifest_hash(self, manifest: dict[str, Any]) -> str:
        tmp = dict(manifest)
        tmp["checksum"] = dict(tmp.get("checksum", {}))
        tmp["checksum"]["manifest"] = "__SELF__"
        tmp.pop("created_at", None)
        payload = json.dumps(tmp, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def validate(self, manifest: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        missing = self.REQUIRED_FIELDS - set(manifest.keys())
        if missing:
            errors.append(f"missing manifest fields: {missing}")
        policy = manifest.get("generation_policy") or {}
        if not isinstance(policy, dict):
            errors.append("generation_policy must be a dict")
        else:
            missing_policy = self.POLICY_REQUIRED_FIELDS - set(policy.keys())
            if missing_policy:
                errors.append(f"missing generation_policy fields: {missing_policy}")
        checksum = manifest.get("checksum") or {}
        if not isinstance(checksum, dict):
            errors.append("checksum must be a dict")
        else:
            for field in ("manifest", "records", "algorithm"):
                if field not in checksum:
                    errors.append(f"missing checksum field: {field}")
        return errors
