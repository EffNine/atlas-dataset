"""
manifest.py — Training view manifest construction and checksumming.

Provides TrainingViewManifest for building, serialising, and verifying
the view-level manifest, including integrity checksums.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


class TrainingViewManifest:
    """Build and verify training view manifests.

    A manifest captures the generation policy, applied filters, source
    references, and integrity checksums for a single training view.
    """

    # Required fields in the manifest schema
    MANIFEST_REQUIRED_FIELDS: frozenset[str] = frozenset({
        "training_view_id",
        "source_release",
        "source_records",
        "generation_policy",
        "filters",
        "created_at",
        "checksum",
    })

    # Required sub-fields in generation_policy
    POLICY_REQUIRED_FIELDS: frozenset[str] = frozenset({
        "quality_threshold",
        "license_filter",
        "lifecycle_filter",
        "eligibility_filter",
        "sampling_strategy",
    })

    def __init__(self) -> None:
        self._checksum_algorithm = "SHA-256"

    # ------------------------------------------------------------------
    # Manifest building
    # ------------------------------------------------------------------

    def create_manifest(
        self,
        view_id: str,
        source_release: str,
        source_records: int,
        quality_threshold: int,
        filter_counts: dict[str, Any],
        records: list[dict[str, Any]],
        target_model: str = "",
        sampling_strategy: str = "none",
        max_records: int | None = None,
    ) -> dict[str, Any]:
        """Create a complete training view manifest.

        Args:
            view_id: Unique training view identifier.
            source_release: Source curated release version.
            source_records: Total source records available.
            quality_threshold: Minimum quality score applied.
            filter_counts: Dict of filter rejection/eligibility counts.
            records: The list of records included in the view.
            target_model: Model target for eligibility filter (optional).
            sampling_strategy: Sampling strategy used (default: "none").
            max_records: Maximum records limit (optional).

        Returns:
            A manifest dict conforming to the Training View Spec.
        """
        # Build eligibility filter description
        if target_model:
            eligibility_filter = {target_model: True}
        else:
            eligibility_filter = {"qwen": True, "llama": True, "deepseek": True}

        generation_policy = {
            "quality_threshold": quality_threshold,
            "license_filter": "denied_and_unknown_excluded",
            "lifecycle_filter": "approved_only",
            "eligibility_filter": eligibility_filter,
            "sampling_strategy": sampling_strategy,
        }
        if max_records is not None:
            generation_policy["max_records"] = max_records

        # Build filters block (counts from filter report)
        filters = {
            "quality_below": filter_counts.get("quality_below", 0),
            "license_denied": filter_counts.get("license_denied", 0),
            "lifecycle_invalid": filter_counts.get("lifecycle_invalid", 0),
            "eligibility_missing": filter_counts.get("eligibility_missing", 0),
            "pending_review": filter_counts.get("pending_review", 0),
            "rejected": filter_counts.get("rejected", 0),
            "lineage_incomplete": filter_counts.get("lineage_incomplete", 0),
        }

        created_at = datetime.now(timezone.utc).isoformat()

        # Build checksums
        checksums = self._compute_checksums(records)

        manifest: dict[str, Any] = {
            "training_view_id": view_id,
            "source_release": source_release,
            "source_records": source_records,
            "generation_policy": generation_policy,
            "filters": filters,
            "created_at": created_at,
            "checksum": checksums,
        }

        return manifest

    # ------------------------------------------------------------------
    # Checksum computation
    # ------------------------------------------------------------------

    def _compute_checksums(
        self,
        records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Compute integrity checksums for records.

        Returns:
            A dict with manifest hash (placeholder) and records hash.
        """
        # Records checksum: deterministic JSON dump of sorted records
        sorted_recs = sorted(records, key=lambda r: r.get("id", ""))
        records_json = "\n".join(
            json.dumps(r, sort_keys=True, ensure_ascii=False)
            for r in sorted_recs
        )
        records_hash = hashlib.sha256(
            records_json.encode("utf-8")
        ).hexdigest()

        # Manifest checksum is computed after manifest is fully built
        # but we defer it to finalize_manifest()
        return {
            "manifest": "__PENDING__",  # filled by finalize_manifest()
            "records": records_hash,
            "algorithm": self._checksum_algorithm,
        }

    def finalize_manifest(
        self,
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        """Finalize a manifest by computing its own checksum.

        Call this after the manifest is fully constructed to fill in
        the `checksum.manifest` field with the manifest's own hash.

        Args:
            manifest: The manifest dict to finalize.

        Returns:
            The same manifest with `checksum.manifest` populated.
        """
        # Temporarily clear the manifest checksum so it's deterministic
        manifest["checksum"]["manifest"] = "__SELF__"
        manifest_json = json.dumps(manifest, sort_keys=True, ensure_ascii=False)
        manifest_hash = hashlib.sha256(
            manifest_json.encode("utf-8")
        ).hexdigest()
        manifest["checksum"]["manifest"] = manifest_hash
        return manifest

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify_checksums(
        self,
        manifest: dict[str, Any],
        records: list[dict[str, Any]],
    ) -> list[str]:
        """Verify that checksums in the manifest match computed values.

        Args:
            manifest: The manifest dict to verify.
            records: The list of records to checksum.

        Returns:
            A list of error messages (empty if all pass).
        """
        errors: list[str] = []

        # Verify records checksum
        computed = self._compute_checksums(records)
        stored_records = manifest.get("checksum", {}).get("records", "")
        if computed["records"] != stored_records:
            errors.append(
                f"Records checksum mismatch: "
                f"computed={computed['records']}, "
                f"stored={stored_records}"
            )

        # Verify manifest self-checksum
        stored_manifest = manifest.get("checksum", {}).get("manifest", "")
        finalized = self.finalize_manifest(dict(manifest))
        computed_manifest = finalized.get("checksum", {}).get("manifest", "")
        if computed_manifest != stored_manifest:
            errors.append(
                f"Manifest checksum mismatch: "
                f"computed={computed_manifest}, "
                f"stored={stored_manifest}"
            )

        return errors

    # ------------------------------------------------------------------
    # View ID generation
    # ------------------------------------------------------------------

    @staticmethod
    def generate_view_id(
        source_release: str,
        target_model: str,
        recipe_id: str = "",
    ) -> str:
        """Generate a deterministic training view ID.

        The ID is a composite of recipe (if provided), source release,
        model target, and a content hash prefix.

        Args:
            source_release: The curated release version.
            target_model: The model target (qwen, llama, deepseek).
            recipe_id: Optional recipe identifier.

        Returns:
            A string view ID.
        """
        parts = [source_release, target_model]
        if recipe_id:
            parts.insert(0, recipe_id)
        base = "_".join(parts)
        h = hashlib.sha256(base.encode("utf-8")).hexdigest()[:12]
        return f"{base}_{h}"

    # ------------------------------------------------------------------
    # Schema validation
    # ------------------------------------------------------------------

    @staticmethod
    def validate_manifest_schema(manifest: dict[str, Any]) -> list[str]:
        """Validate manifest structure against required fields.

        Args:
            manifest: The manifest dict to validate.

        Returns:
            A list of error messages (empty if valid).
        """
        errors: list[str] = []

        missing = TrainingViewManifest.MANIFEST_REQUIRED_FIELDS - set(manifest.keys())
        if missing:
            errors.append(f"Manifest missing required fields: {missing}")

        # Check generation_policy sub-fields
        policy = manifest.get("generation_policy", {})
        if not isinstance(policy, dict):
            errors.append("generation_policy must be a dict")
        else:
            policy_missing = (
                TrainingViewManifest.POLICY_REQUIRED_FIELDS - set(policy.keys())
            )
            if policy_missing:
                errors.append(
                    f"generation_policy missing required fields: {policy_missing}"
                )

        # Check checksum structure
        checksum = manifest.get("checksum", {})
        if not isinstance(checksum, dict):
            errors.append("checksum must be a dict")
        else:
            for field in ("manifest", "records", "algorithm"):
                if field not in checksum:
                    errors.append(f"checksum missing required field: {field}")

        # Check filters structure
        filters = manifest.get("filters", {})
        if not isinstance(filters, dict):
            errors.append("filters must be a dict")

        return errors
