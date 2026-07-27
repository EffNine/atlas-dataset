#!/usr/bin/env python3
"""
versioning.py — Atlas Acquisition Engine dataset versioning.

Manages versioned releases of the curated dataset. Each version is a
frozen snapshot with:
  * Version manifest (targets, statistics, checksums)
  * Snapshot of the curated records
  * Full metadata: category distribution, license stats, quality distribution
  * Changelog linking to the previous version
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class VersionManager:
    """
    Manages dataset versioning and release snapshots.

    Versions follow semver (v0.1, v0.2, v1.0, etc.). Each version is stored
    under curated/<version>/ and includes a manifest, the curated records,
    and checksum metadata.
    """

    def __init__(self, dataset_root: str | Path):
        self.root = Path(dataset_root)
        self.curated_dir = self.root / "curated"
        self.metadata_dir = self.root / "metadata"
        self.version_index_path = self.metadata_dir / "version_index.json"

    def list_versions(self) -> list[dict[str, Any]]:
        """List all recorded versions with metadata."""
        if not self.version_index_path.exists():
            return []
        try:
            data = json.loads(self.version_index_path.read_text(encoding="utf-8"))
            return data.get("versions", [])
        except (json.JSONDecodeError, KeyError):
            return []

    def current_version(self) -> str | None:
        """Return the most recent version string, or None."""
        versions = self.list_versions()
        if not versions:
            return None
        # Sort by version (assumes vN.N format, can compare lexically within same major)
        def _sort_key(v: dict) -> tuple:
            parts = v.get("version", "v0.0").lstrip("v").split(".")
            try:
                return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
            except (ValueError, IndexError):
                return (0, 0)
        versions_sorted = sorted(versions, key=_sort_key)
        return versions_sorted[-1].get("version")

    def get_version_manifest(self, version: str) -> dict[str, Any] | None:
        """Read the version manifest for a specific version."""
        man_path = self.curated_dir / version / "version_manifest.json"
        if not man_path.exists():
            return None
        try:
            return json.loads(man_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError):
            return None

    def freeze(
        self,
        version: str,
        source_paths: list[Path],
        stats: dict[str, Any] | None = None,
        changelog: str | None = None,
    ) -> dict[str, Any]:
        """
        Freeze a new version snapshot.

        Copies the source curated files into curated/<version>/,
        computes summary stats, and writes the version manifest.

        Args:
            version: Version string (e.g. "v0.2")
            source_paths: Paths to JSONL files to include in this version
            stats: Optional pre-computed statistics
            changelog: Optional human-readable changelog

        Returns:
            The version manifest dict
        """
        version_dir = self.curated_dir / version
        version_dir.mkdir(parents=True, exist_ok=True)
        data_dir = version_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        # Copy source files
        copied_files: list[str] = []
        total_records = 0
        category_counts: dict[str, int] = {}
        license_counts: dict[str, int] = {}
        quality_scores: list[int] = []
        status_counts: dict[str, int] = {}

        for src in source_paths:
            if not src.exists():
                continue
            dest = data_dir / src.name
            shutil.copy2(str(src), str(dest))
            copied_files.append(src.name)

            # Count records and aggregate stats
            with open(src, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    total_records += 1
                    cat = rec.get("category", "unknown")
                    category_counts[cat] = category_counts.get(cat, 0) + 1
                    lic = rec.get("license", "unknown")
                    license_counts[lic] = license_counts.get(lic, 0) + 1
                    qs = rec.get("quality_score", 0)
                    if isinstance(qs, (int, float)):
                        quality_scores.append(int(qs))
                    vs = rec.get("verification_status", "unknown")
                    status_counts[vs] = status_counts.get(vs, 0) + 1

        # Compute quality stats
        avg_q = round(sum(quality_scores) / len(quality_scores), 2) if quality_scores else 0
        min_q = min(quality_scores) if quality_scores else 0
        max_q = max(quality_scores) if quality_scores else 0

        now = datetime.now(timezone.utc).isoformat()

        # Build manifest
        manifest: dict[str, Any] = {
            "version": version,
            "frozen_at": now,
            "total_records": total_records,
            "source_files": copied_files,
            "statistics": {
                "by_category": dict(sorted(category_counts.items())),
                "by_license": dict(sorted(license_counts.items())),
                "by_verification_status": dict(sorted(status_counts.items())),
                "quality": {
                    "avg": avg_q,
                    "min": min_q,
                    "max": max_q,
                    "scores": sorted(quality_scores)[:5] + ["..."] + sorted(quality_scores)[-5:],
                },
            },
        }
        if stats:
            manifest["pipeline_stats"] = stats
        if changelog:
            manifest["changelog"] = changelog

        # Write manifest
        man_path = version_dir / "version_manifest.json"
        man_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

        # Update version index
        self._update_version_index(version, now, total_records)

        print(f"[version] Frozen version '{version}' — {total_records} records, "
              f"{len(copied_files)} source file(s)")
        return manifest

    def _update_version_index(
        self, version: str, timestamp: str, record_count: int
    ) -> None:
        """Update the global version index."""
        versions = self.list_versions()
        # Remove existing entry for this version if present
        versions = [v for v in versions if v.get("version") != version]
        versions.append({
            "version": version,
            "frozen_at": timestamp,
            "total_records": record_count,
        })
        self.version_index_path.write_text(
            json.dumps({"versions": versions}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def diff(
        self, from_version: str, to_version: str
    ) -> dict[str, Any] | None:
        """
        Compute a diff between two frozen versions by comparing record IDs
        and file checksums.

        Returns a dict with added/removed/changed record counts, or None
        if either version doesn't exist.
        """
        from_man = self.get_version_manifest(from_version)
        to_man = self.get_version_manifest(to_version)
        if from_man is None or to_man is None:
            return None

        # Collect record IDs for each version
        def _load_ids(manifest: dict) -> set[str]:
            ids: set[str] = set()
            for fname in manifest.get("source_files", []):
                fpath = self.curated_dir / manifest["version"] / "data" / fname
                if fpath.exists():
                    with open(fpath, encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    rec = json.loads(line)
                                    ids.add(rec.get("id", ""))
                                except json.JSONDecodeError:
                                    pass
            return ids

        from_ids = _load_ids(from_man)
        to_ids = _load_ids(to_man)

        added = sorted(to_ids - from_ids)
        removed = sorted(from_ids - to_ids)
        changed: list[str] = []

        # Check common IDs for content changes
        common = from_ids & to_ids
        if common:
            # Build content maps for common IDs
            def _load_content_map(manifest: dict) -> dict[str, str]:
                cm: dict[str, str] = {}
                for fname in manifest.get("source_files", []):
                    fpath = self.curated_dir / manifest["version"] / "data" / fname
                    if fpath.exists():
                        with open(fpath, encoding="utf-8") as f:
                            for line in f:
                                line = line.strip()
                                if line:
                                    try:
                                        rec = json.loads(line)
                                        rid = rec.get("id", "")
                                        cm[rid] = json.dumps(rec, sort_keys=True)
                                    except json.JSONDecodeError:
                                        pass
                return cm

            from_content = _load_content_map(from_man)
            to_content = _load_content_map(to_man)
            for rid in sorted(common):
                if from_content.get(rid) != to_content.get(rid):
                    changed.append(rid)

        return {
            "from_version": from_version,
            "to_version": to_version,
            "from_records": len(from_ids),
            "to_records": len(to_ids),
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "added_ids": added[:20],  # show first 20
            "removed_ids": removed[:20],
            "changed_ids": changed[:20],
            "note": "ID lists truncated at 20 items; full lists available on request",
        }

    def rollback(self, to_version: str) -> str | None:
        """
        Roll back the current version pointer to a previous version.
        Returns the new current version string, or None if the target
        version doesn't exist.
        """
        versions = self.list_versions()
        target = None
        for v in versions:
            if v.get("version") == to_version:
                target = v
                break
        if target is None:
            return None
        # The current version is just the latest; rollback means we remove
        # entries after the target version from the index
        idx = versions.index(target)
        versions = versions[: idx + 1]
        self.version_index_path.write_text(
            json.dumps({"versions": versions}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return to_version
