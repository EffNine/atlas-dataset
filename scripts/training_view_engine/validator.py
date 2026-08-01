"""
validator.py — Training view validation logic.

Provides TrainingViewValidator for validating inputs, content, and
outputs of training view generation. All validation is read-only
and deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from atlas_constants import VALID_TRAINING_MODELS, is_denied_license
from atlas_schema import KNOWLEDGE_OBJECT_REQUIRED_FIELDS, LINEAGE_SUB_FIELDS

from .manifest import TrainingViewManifest


def validate_record_standalone(
    rec: dict[str, Any],
    quality_threshold: int = 7,
) -> list[str]:
    """Validate a single record for training-view eligibility.

    Module-level so ProcessPoolExecutor workers can pickle it
    (a bound method or closure is not picklable).

    Args:
        rec: A knowledge object record.
        quality_threshold: Minimum quality score.

    Returns:
        A list of error messages (empty if valid).
    """
    errors: list[str] = []

    # Verification status
    vs = rec.get("verification_status", "")
    if vs != "approved":
        errors.append(
            f"record {rec.get('id', '?')}: verification_status={vs!r}, "
            f"expected 'approved'"
        )

    # License
    lic = rec.get("license", "")
    if is_denied_license(lic):
        errors.append(
            f"record {rec.get('id', '?')}: denied license {lic!r}"
        )
    elif not lic or lic == "unknown":
        errors.append(
            f"record {rec.get('id', '?')}: unknown license {lic!r}"
        )

    # Quality
    try:
        qs = int(rec.get("quality_score", 0))
    except (TypeError, ValueError):
        qs = 0
    if qs < quality_threshold:
        errors.append(
            f"record {rec.get('id', '?')}: quality_score {qs} "
            f"below threshold {quality_threshold}"
        )

    # Lineage
    lineage = rec.get("lineage", {})
    required_lineage = set(LINEAGE_SUB_FIELDS)
    missing_lineage = required_lineage - set(lineage.keys())
    if missing_lineage:
        errors.append(
            f"record {rec.get('id', '?')}: lineage missing fields: "
            f"{missing_lineage}"
        )

    # Required fields
    missing_fields = [
        f for f in KNOWLEDGE_OBJECT_REQUIRED_FIELDS
        if f not in rec
    ]
    if missing_fields:
        errors.append(
            f"record {rec.get('id', '?')}: missing required fields: "
            f"{missing_fields}"
        )

    return errors


def _validate_chunk_standalone(
    args: tuple[list[dict[str, Any]], int],
) -> list[dict[str, Any]]:
    """Validate a chunk of records in a worker process."""
    chunk, quality_threshold = args
    out: list[dict[str, Any]] = []
    for rec in chunk:
        errs = validate_record_standalone(rec, quality_threshold)
        out.append({
            "record_id": rec.get("id", "?"),
            "valid": len(errs) == 0,
            "errors": errs,
        })
    return out


def _validate_task(task) -> list[dict[str, Any]]:
    """Universal Scheduler worker: validate a record-range Task.

    Module-level so it can be pickled into process workers. The Task's
    extra carries the record chunk and quality threshold (mirrors
    _validate_chunk_standalone args); offset_start/offset_end identify the
    original record range for deterministic merging.
    """
    extra = getattr(task, "extra", {}) or {}
    chunk = extra.get("records", [])
    qt = int(extra.get("quality_threshold", 7))
    return _validate_chunk_standalone((chunk, qt))


class TrainingViewValidator:
    """Validate training view inputs, content, and outputs.

    Enforces the rules defined in the Training View Specification:
      - No pending records
      - No rejected records
      - No unknown licenses
      - Complete lineage
      - Quality threshold compliance
      - Input/output structural integrity
    """

    def __init__(self, root: Path | None = None) -> None:
        self._root = root

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    def validate_source_release(
        self,
        source_release: str,
    ) -> list[str]:
        """Validate that a source release reference is well-formed.

        Args:
            source_release: The release version string (e.g., "v0.2").

        Returns:
            A list of error messages (empty if valid).
        """
        errors: list[str] = []
        if not source_release or not isinstance(source_release, str):
            errors.append("source_release must be a non-empty string")
        elif not source_release.startswith("v"):
            errors.append(
                f"source_release should start with 'v': {source_release!r}"
            )
        return errors

    def validate_target_model(self, target_model: str) -> list[str]:
        """Validate that a target model is recognised.

        Args:
            target_model: Model identifier (qwen, llama, deepseek, or empty).

        Returns:
            A list of error messages (empty if valid).
        """
        errors: list[str] = []
        if target_model and target_model not in VALID_TRAINING_MODELS:
            errors.append(
                f"target_model {target_model!r} not in "
                f"{sorted(VALID_TRAINING_MODELS)}"
            )
        return errors

    def validate_quality_threshold(self, threshold: int) -> list[str]:
        """Validate a quality threshold value.

        Args:
            threshold: The quality threshold (0-10).

        Returns:
            A list of error messages (empty if valid).
        """
        errors: list[str] = []
        if not isinstance(threshold, int):
            errors.append(f"quality_threshold must be int, got {type(threshold)}")
        elif not (0 <= threshold <= 10):
            errors.append(
                f"quality_threshold must be 0-10, got {threshold}"
            )
        return errors

    # ------------------------------------------------------------------
    # Content validation (per-record)
    # ------------------------------------------------------------------

    def validate_record(
        self,
        rec: dict[str, Any],
        quality_threshold: int = 7,
    ) -> list[str]:
        """Validate a single record for training-view eligibility.

        Checks:
          - verification_status == "approved"
          - license not denied and not unknown
          - quality_score >= threshold
          - lineage is complete

        Args:
            rec: A knowledge object record.
            quality_threshold: Minimum quality score.

        Returns:
            A list of error messages (empty if valid).
        """
        return validate_record_standalone(rec, quality_threshold)

    def validate_records(
        self,
        records: list[dict[str, Any]],
        quality_threshold: int = 7,
        workers: int = 1,
    ) -> list[dict[str, Any]]:
        """Validate a list of records for training-view eligibility.

        Args:
            records: List of knowledge object records.
            quality_threshold: Minimum quality score.
            workers: Parallel process workers (1 = sequential).

        Returns:
            A list of validation result dicts, one per record, each with:
              - record_id: str
              - valid: bool
              - errors: list[str]
        """
        if workers > 1 and len(records) > 100:
            # Universal Scheduler path: record-range tasks, deterministic
            # ordering (task_id encodes the offset range, so results sorted
            # by task_id preserve original record order). Falls back to the
            # manual ProcessPoolExecutor below on any scheduler error.
            try:
                from parallel.models import Task
                from parallel.scheduler import Scheduler

                chunk_size = max(1, len(records) // (workers * 4))
                tasks: list[Task] = []
                for start in range(0, len(records), chunk_size):
                    end = min(len(records), start + chunk_size)
                    tasks.append(Task(
                        task_id=f"tv:validate:{start:06d}:{end:06d}",
                        source="training_views",
                        operation="validate_record_range",
                        input="",
                        offset_start=start,
                        offset_end=end,
                        extra={
                            "records": records[start:end],
                            "quality_threshold": quality_threshold,
                        },
                    ))
                sched = Scheduler(
                    "training_views",
                    registry_root=str(
                        Path(self._root) / "metadata" / "pipeline_state"
                        if self._root else "metadata/pipeline_state"
                    ),
                    workers=workers,
                    pool="process",
                    max_retries=2,
                )
                trs = sched.run(tasks, _validate_task)
                results: list[dict[str, Any]] = []
                for tr in trs:
                    if tr.status == "completed" and isinstance(tr.result, list):
                        results.extend(tr.result)
                    elif tr.status == "failed":
                        # Keep the failure visible: mark every record in range failed.
                        start = int(tr.task_id.split(":")[2])
                        end = int(tr.task_id.split(":")[3])
                        for ridx in range(start, end):
                            results.append({
                                "record_id": records[ridx].get("id", "?"),
                                "valid": False,
                                "errors": [f"scheduler task failed: {tr.error}"],
                            })
                    # skipped tasks (completed in a prior run): reconstruct
                    # from registry result is not stored — re-validate inline.
                    elif tr.status == "skipped":
                        start = int(tr.task_id.split(":")[2])
                        end = int(tr.task_id.split(":")[3])
                        for rec in records[start:end]:
                            errs = validate_record_standalone(rec, quality_threshold)
                            results.append({
                                "record_id": rec.get("id", "?"),
                                "valid": len(errs) == 0,
                                "errors": errs,
                            })
                return results
            except Exception:
                pass  # fall through to manual ProcessPoolExecutor

            from concurrent.futures import ProcessPoolExecutor
            # Chunk records for balanced distribution
            chunk_size = max(1, len(records) // (workers * 4))
            chunks = [records[i:i + chunk_size] for i in range(0, len(records), chunk_size)]

            results: list[dict[str, Any]] = []
            with ProcessPoolExecutor(max_workers=workers) as ex:
                for chunk_results in ex.map(
                    _validate_chunk_standalone,
                    [(chunk, quality_threshold) for chunk in chunks],
                ):
                    results.extend(chunk_results)
            return results

        results = []
        for rec in records:
            errs = self.validate_record(rec, quality_threshold)
            results.append({
                "record_id": rec.get("id", "?"),
                "valid": len(errs) == 0,
                "errors": errs,
            })
        return results

    # ------------------------------------------------------------------
    # Output validation
    # ------------------------------------------------------------------

    def validate_manifest(
        self,
        manifest: dict[str, Any],
    ) -> list[str]:
        """Validate a training view manifest against the spec schema.

        Args:
            manifest: The manifest dict to validate.

        Returns:
            A list of error messages (empty if valid).
        """
        return TrainingViewManifest.validate_manifest_schema(manifest)

    def validate_view_records(
        self,
        manifest: dict[str, Any],
        records: list[dict[str, Any]],
    ) -> list[str]:
        """Validate generated view records against the manifest.

        Checks:
          - Every record has a view_id matching the manifest
          - Every record has the required per-record fields

        Args:
            manifest: The training view manifest.
            records: The generated view records.

        Returns:
            A list of error messages (empty if valid).
        """
        errors: list[str] = []
        view_id = manifest.get("training_view_id", "")

        required_per_record = {
            "view_id", "record_id", "source", "license",
            "quality_score", "category", "lineage", "messages",
        }

        for i, rec in enumerate(records):
            rid = rec.get("record_id", f"index_{i}")

            # Check view_id matches
            if rec.get("view_id") != view_id:
                errors.append(
                    f"record {rid}: view_id mismatch "
                    f"({rec.get('view_id')!r} vs manifest {view_id!r})"
                )

            # Check required fields
            missing = required_per_record - set(rec.keys())
            if missing:
                errors.append(f"record {rid}: missing fields: {missing}")

            # Check messages exist
            msgs = rec.get("messages", [])
            if not isinstance(msgs, list) or len(msgs) < 2:
                errors.append(
                    f"record {rid}: messages must have at least 2 turns"
                )

        return errors

    def validate_determinism(
        self,
        records_a: list[dict[str, Any]],
        records_b: list[dict[str, Any]],
    ) -> list[str]:
        """Compare two record sets for deterministic equivalence.

        Args:
            records_a: First record set.
            records_b: Second record set.

        Returns:
            A list of error messages (empty if identical).
        """
        errors: list[str] = []

        if len(records_a) != len(records_b):
            errors.append(
                f"Record count mismatch: {len(records_a)} vs {len(records_b)}"
            )
            return errors

        for i, (ra, rb) in enumerate(zip(
            sorted(records_a, key=lambda r: r.get("record_id", "")),
            sorted(records_b, key=lambda r: r.get("record_id", "")),
        )):
            ra_json = json.dumps(ra, sort_keys=True, ensure_ascii=False)
            rb_json = json.dumps(rb, sort_keys=True, ensure_ascii=False)
            if ra_json != rb_json:
                errors.append(
                    f"Record {i} differs: "
                    f"{ra.get('record_id', '?')} vs {rb.get('record_id', '?')}"
                )
                break  # Report first difference only

        return errors

    # ------------------------------------------------------------------
    # No-mutation checks
    # ------------------------------------------------------------------

    @staticmethod
    def assert_no_dataset_mutation(
        before: dict[str, str],
        after: dict[str, str],
    ) -> list[str]:
        """Compare SHA-256 hashes of curated files to detect mutation.

        Args:
            before: Dict of file path -> SHA-256 before generation.
            after: Dict of file path -> SHA-256 after generation.

        Returns:
            A list of error messages (empty if none mutated).
        """
        errors: list[str] = []
        all_paths = set(before) | set(after)
        for fp in all_paths:
            b = before.get(fp)
            a = after.get(fp)
            if b != a:
                errors.append(
                    f"Dataset changed: {fp} "
                    f"(before={b}, after={a})"
                )
        return errors

    @staticmethod
    def assert_no_review_mutation(
        before: dict[str, str],
        after: dict[str, str],
    ) -> list[str]:
        """Compare SHA-256 hashes of review files to detect mutation.

        Args:
            before: Dict of review file path -> SHA-256.
            after: Dict of review file path -> SHA-256.

        Returns:
            A list of error messages (empty if none mutated).
        """
        return TrainingViewValidator.assert_no_dataset_mutation(before, after)

    @staticmethod
    def assert_no_release_mutation(
        before: dict[str, str],
        after: dict[str, str],
    ) -> list[str]:
        """Compare SHA-256 hashes of release metadata to detect mutation.

        Args:
            before: Dict of release file path -> SHA-256.
            after: Dict of release file path -> SHA-256.

        Returns:
            A list of error messages (empty if none mutated).
        """
        return TrainingViewValidator.assert_no_dataset_mutation(before, after)
