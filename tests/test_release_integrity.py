#!/usr/bin/env python3
"""Tests for release integrity checking."""
import json
import tempfile
from pathlib import Path

import pytest


class TestReleaseIntegrityCheck:
    """Test release integrity verification functions."""

    def test_check_manifest_integrity_valid(self, tmp_path: Path):
        """Test manifest integrity check with valid manifest."""
        from scripts.release.integrity_check import check_manifest_integrity

        manifest = {
            "release_version": "v1.0",
            "total_records": 100,
            "release_signature": {
                "content_hash": "abc123",
                "chain_hash": "def456",
            },
        }
        manifest_path = tmp_path / "metadata" / "releases" / "v1.0_release.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(json.dumps(manifest))

        result = check_manifest_integrity(manifest_path)
        assert result["exists"] is True
        assert result["valid_json"] is True
        assert result["has_signature"] is True

    def test_check_manifest_integrity_missing(self, tmp_path: Path):
        """Test manifest integrity check with missing file."""
        from scripts.release.integrity_check import check_manifest_integrity

        manifest_path = tmp_path / "nonexistent.json"
        result = check_manifest_integrity(manifest_path)
        assert result["exists"] is False

    def test_check_human_review_evidence_missing(self, tmp_path: Path):
        """Test human review evidence check when approved.jsonl is missing."""
        from scripts.release.integrity_check import check_human_review_evidence

        result = check_human_review_evidence(tmp_path)
        assert result["evidence_exists"] is False
        assert "approved.jsonl does not exist" in result.get("error", "")

    def test_check_human_review_evidence_exists(self, tmp_path: Path):
        """Test human review evidence check when approved.jsonl exists."""
        from scripts.release.integrity_check import check_human_review_evidence

        approved = tmp_path / "review_queue" / "approved.jsonl"
        approved.parent.mkdir(parents=True)
        approved.write_text('{"id": "1"}\n{"id": "2"}\n')

        result = check_human_review_evidence(tmp_path)
        assert result["evidence_exists"] is True
        assert result["approved_count"] == 2
        assert result["has_evidence"] is True

    def test_check_dataset_exists_with_gitkeep_only(self, tmp_path: Path):
        """Test dataset check when only .gitkeep files exist."""
        from scripts.release.integrity_check import check_dataset_exists

        # Create a fake release structure with only .gitkeep in each category
        release_dir = tmp_path / "releases" / "v1.0" / "dataset" / "01_foundation"
        release_dir.mkdir(parents=True)
        (release_dir / ".gitkeep").write_text("")

        manifest = {"release_version": "v1.0"}
        result = check_dataset_exists(tmp_path, manifest)
        assert result["dataset_exists"] is True
        assert result["has_only_gitkeep"] is True
        assert result["has_data_files"] is False

    def test_check_dataset_exists_with_data(self, tmp_path: Path):
        """Test dataset check when data files exist."""
        from scripts.release.integrity_check import check_dataset_exists

        # Create a fake release structure with actual data
        release_dir = tmp_path / "releases" / "v1.0" / "dataset" / "01_foundation"
        release_dir.mkdir(parents=True)
        (release_dir / "data.jsonl").write_text('{"id": "1"}\n')

        manifest = {"release_version": "v1.0"}
        result = check_dataset_exists(tmp_path, manifest)
        assert result["dataset_exists"] is True
        assert result["has_data_files"] is True
        assert result["is_valid"] is True
