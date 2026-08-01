"""
generator.py — Training view generation orchestrator.

Provides TrainingViewGenerator, the top-level orchestrator for
producing training view metadata from approved knowledge objects.
All operations are read-only and deterministic (dry-run by default).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from atlas_constants import VALID_TRAINING_MODELS, is_denied_license
from atlas_paths import curated_dir, docs_dir, metadata_dir, training_views_dir

from .filter import TrainingViewFilter
from .manifest import TrainingViewManifest
from .validator import TrainingViewValidator


class TrainingViewGenerator:
    """Top-level orchestrator for training view generation.

    Generates training view metadata from approved knowledge objects
    only, enforcing quality thresholds, license gates, lifecycle
    constraints, and model eligibility.

    All generation is dry-run by default — no data is written to disk
    unless explicitly requested.
    """

    def __init__(
        self,
        root: Path,
        mode: str = "dry-run",
    ) -> None:
        """Initialise the generator.

        Args:
            root: Project root path.
            mode: "dry-run" (default, no writes) or "generate" (writes views).

        Raises:
            ValueError: If mode is not "dry-run" or "generate".
        """
        self._root = Path(root).resolve()
        if mode not in ("dry-run", "generate"):
            raise ValueError(f"mode must be 'dry-run' or 'generate', got {mode!r}")
        self._mode = mode
        self._filter = TrainingViewFilter()
        self._manifest = TrainingViewManifest()
        self._validator = TrainingViewValidator(self._root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_training_views(self) -> list[dict[str, Any]]:
        """List existing training views in training_views/.

        Returns:
            A list of view metadata dicts (id, model, records, status).
        """
        views: list[dict[str, Any]] = []
        tv_root = training_views_dir(self._root)

        if not tv_root.exists():
            return views

        for model_dir in sorted(tv_root.iterdir()):
            if not model_dir.is_dir():
                continue
            # Look for generated view manifests
            for manifest_file in sorted(model_dir.glob("*_view_manifest.json")):
                try:
                    data = json.loads(
                        manifest_file.read_text(encoding="utf-8")
                    )
                    views.append({
                        "training_view_id": data.get("training_view_id", "?"),
                        "model": model_dir.name,
                        "source_release": data.get("source_release", "?"),
                        "source_records": data.get("source_records", 0),
                        "eligible_records": data.get("filters", {}).get(
                            "quality_below", 0
                        ),
                        "created_at": data.get("created_at", "?"),
                        "checksum": data.get("checksum", {}).get("records", "?")[:16],
                        "manifest_file": str(
                            manifest_file.relative_to(self._root)
                        ),
                    })
                except (json.JSONDecodeError, KeyError):
                    continue

        return views

    def dry_run(
        self,
        target_model: str = "",
        quality_threshold: int = 7,
        recipe_id: str = "",
        source_release: str = "v0.1",
    ) -> dict[str, Any]:
        """Run a dry-run view generation.

        This is the primary API for verifying the training view pipeline
        without writing any data. It loads curated records, applies filters,
        validates, builds a manifest, and reports results.

        Args:
            target_model: Optional model target (qwen/llama/deepseek).
            quality_threshold: Minimum quality score (0-10).
            recipe_id: Optional recipe identifier.
            source_release: Source curated release version.

        Returns:
            A dict with full dry-run report:
              - status, mode, source_release, target_model
              - recipe_id, quality_threshold
              - total_source_records, eligible_records
              - filter_report, validation_results
              - manifest (preview, without self-checksum)
              - reproducibility_hash
              - warnings, errors
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Validate inputs
        errors.extend(
            self._validator.validate_source_release(source_release)
        )
        if target_model:
            errors.extend(
                self._validator.validate_target_model(target_model)
            )
        errors.extend(
            self._validator.validate_quality_threshold(quality_threshold)
        )

        if errors:
            return {
                "status": "error",
                "mode": "dry-run",
                "errors": errors,
                "source_release": source_release,
                "target_model": target_model or "all",
                "recipe_id": recipe_id,
            }

        # Load curated records
        source_records = self._load_curated_records(source_release)
        if not source_records:
            return {
                "status": "blocked",
                "mode": "dry-run",
                "errors": [
                    f"No curated records found for release {source_release}"
                ],
                "source_release": source_release,
                "target_model": target_model or "all",
                "recipe_id": recipe_id,
            }

        total_source = len(source_records)
        warnings.append(
            f"Source release {source_release}: {total_source} records"
        )

        # Check how many are approved
        approved = [r for r in source_records
                     if r.get("verification_status") == "approved"]
        if not approved:
            # This is expected at current project state — report BLOCKED
            return {
                "status": "blocked",
                "mode": "dry-run",
                "source_release": source_release,
                "target_model": target_model or "all",
                "recipe_id": recipe_id,
                "total_source_records": total_source,
                "approved_records": 0,
                "eligible_records": 0,
                "filter_report": {},
                "errors": [
                    "BLOCKED: No approved records found. "
                    "Training view generation requires approved "
                    "(human-reviewed) records only."
                ],
                "reproducibility_hash": self._compute_run_hash(
                    source_release, target_model, quality_threshold, recipe_id, []
                ),
            }

        # Apply filter
        filter_obj = TrainingViewFilter(quality_threshold=quality_threshold)
        eligible = filter_obj.filter_records(approved, target_model)
        filter_report = filter_obj.filter_report(
            approved, target_model
        )

        # Validate each eligible record (parallel via unified config)
        view_workers = self._load_view_workers()
        validation_results = self._validator.validate_records(
            eligible, quality_threshold, workers=view_workers
        )
        validation_errors = [
            v for v in validation_results if not v["valid"]
        ]

        # Build manifest (preview)
        view_id = TrainingViewManifest.generate_view_id(
            source_release, target_model or "all", recipe_id
        )
        manifest = self._manifest.create_manifest(
            view_id=view_id,
            source_release=source_release,
            source_records=total_source,
            quality_threshold=quality_threshold,
            filter_counts=filter_report,
            records=eligible,
            target_model=target_model,
        )

        # Compute reproducibility hash
        run_hash = self._compute_run_hash(
            source_release, target_model, quality_threshold,
            recipe_id, eligible
        )

        result: dict[str, Any] = {
            "status": "ok",
            "mode": "dry-run",
            "source_release": source_release,
            "target_model": target_model or "all",
            "recipe_id": recipe_id,
            "quality_threshold": quality_threshold,
            "total_source_records": total_source,
            "approved_records": len(approved),
            "eligible_records": len(eligible),
            "filter_report": filter_report,
            "validation_results": {
                "total_checked": len(validation_results),
                "valid": len(validation_results) - len(validation_errors),
                "errors": len(validation_errors),
                "details": validation_errors[:10],  # First 10 only
            },
            "manifest": manifest,
            "reproducibility_hash": run_hash,
            "warnings": warnings,
            "message": (
                f"Dry-run {'with warnings' if warnings else 'completed'}. "
                f"Use --generate to write view metadata. "
                f"{len(eligible)}/{total_source} records eligible."
            ),
        }

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_view_workers(self) -> int:
        """Load training view workers from config/parallelism.yaml.

        Falls back to the classification worker count, then 1.
        """
        cfg_path = self._root / "config" / "parallelism.yaml"
        try:
            import yaml
            with open(cfg_path, "r") as f:
                cfg = yaml.safe_load(f) or {}
            workers = cfg.get("parallelism", {}).get("training_views", {}).get("workers")
            if workers is None:
                workers = cfg.get("parallelism", {}).get("classification", {}).get("stage2_shard_workers")
            return int(workers or 1)
        except Exception:
            return 1

    def _load_curated_records(
        self,
        version: str = "v0.1",
    ) -> list[dict[str, Any]]:
        """Load curated records from a specific release version.

        Scans curated/<version>/ for JSONL files, reading them in
        parallel when the unified config enables it.

        Args:
            version: The curated version directory name (e.g., "v0.1").

        Returns:
            List of record dicts.
        """
        records: list[dict[str, Any]] = []
        curated_path = curated_dir(self._root) / version
        if not curated_path.exists():
            return records

        files = sorted(curated_path.rglob("*.jsonl"))
        workers = self._load_view_workers()

        def _load_one(fp: Path) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            try:
                with open(fp, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                out.append(json.loads(line))
                            except json.JSONDecodeError:
                                continue
            except (OSError, IOError):
                return out
            return out

        if workers > 1 and len(files) > 1:
            from concurrent.futures import ProcessPoolExecutor
            with ProcessPoolExecutor(max_workers=workers) as ex:
                for chunk in ex.map(_load_one, files):
                    records.extend(chunk)
        else:
            for fp in files:
                records.extend(_load_one(fp))

        return records

    @staticmethod
    def _compute_run_hash(
        source_release: str,
        target_model: str,
        quality_threshold: int,
        recipe_id: str,
        records: list[dict[str, Any]],
    ) -> str:
        """Compute a deterministic hash for a complete generation run.

        Includes config and sorted record content.

        Args:
            source_release: Source release version.
            target_model: Target model identifier.
            quality_threshold: Quality threshold used.
            recipe_id: Recipe identifier.
            records: The resulting records (or empty list for blocked state).

        Returns:
            SHA-256 hex digest.
        """
        config = {
            "source_release": source_release,
            "target_model": target_model,
            "quality_threshold": quality_threshold,
            "recipe_id": recipe_id,
        }
        sorted_recs = sorted(
            records, key=lambda r: r.get("id", "")
        )
        raw = json.dumps(config, sort_keys=True, ensure_ascii=False)
        for rec in sorted_recs:
            raw += json.dumps(rec, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
