#!/usr/bin/env python3
"""Tests for Phase 7C-B upload_huggingface.py hardening.

Covers:
  - U-1 worker resolution: CLI > env > config > default 4
  - U-2/U-3 checksum-aware resume: SHA-256 match skips, mismatch/uploads
    size-only fallback warning when remote sha256 unavailable
  - U-4 retry classification: 429/5xx retryable, 401/403/404 fatal
  - U-5/U-6 pre-upload verification gate: valid manifest passes,
    corrupted/missing file blocks before network I/O

Run:
  .venv-release/bin/python -m pytest tests/test_upload_hardening.py -v
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS_RELEASE = ROOT / "scripts" / "release"
if str(SCRIPTS_RELEASE) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_RELEASE))


# ---------------------------------------------------------------------------
# Module loader helpers
# ---------------------------------------------------------------------------

def _load_upload_module():
    import importlib

    name = "upload_huggingface"
    path = SCRIPTS_RELEASE / "upload_huggingface.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _load_verify_module():
    import importlib

    name = "verify_sha256"
    path = SCRIPTS_RELEASE / "verify_sha256.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------------------------------------------------------------------------
# U-1: worker resolution
# ---------------------------------------------------------------------------

class TestResolveUploadWorkers:
    def test_default_is_four(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("ATLAS_WORKERS_RELEASE", raising=False)
        mod = _load_upload_module()
        assert mod.resolve_upload_workers() == 4

    def test_explicit_overrides_default(self):
        mod = _load_upload_module()
        assert mod.resolve_upload_workers(explicit=3) == 3


# ---------------------------------------------------------------------------
# U-2/U-3: checksum-aware resume
# ---------------------------------------------------------------------------

class TestChecksumAwareResume:
    def _build_release(self, tmp_path: Path) -> tuple[Path, Path, Path]:
        root = tmp_path / "release"
        (root / "metadata").mkdir(parents=True)
        (root / "docs").mkdir(parents=True)
        a = root / "metadata" / "a.json"
        b = root / "docs" / "b.md"
        a.write_text('{"x": 1}', encoding="utf-8")
        b.write_text("# b", encoding="utf-8")
        return root, a, b

    def test_checksum_match_skips(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        mod = _load_upload_module()
        root, a, b = self._build_release(tmp_path)
        import importlib
        vm = _load_verify_module()
        checksums = {
            str(a.relative_to(root)): vm.sha256_file(a),
            str(b.relative_to(root)): vm.sha256_file(b),
        }
        remote_sizes = {
            str(a.relative_to(root)): a.stat().st_size,
            str(b.relative_to(root)): b.stat().st_size,
        }
        remote_checksums = dict(checksums)
        sections = [
            ("metadata", [a]),
            ("docs", [b]),
        ]
        pending, warnings = mod._resume_skip(sections, remote_sizes, remote_checksums, root)
        assert pending == []
        assert warnings == 0

    def test_checksum_mismatch_uploads(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        mod = _load_upload_module()
        root, a, b = self._build_release(tmp_path)
        vm = _load_verify_module()
        remote_sizes = {
            str(a.relative_to(root)): a.stat().st_size,
            str(b.relative_to(root)): b.stat().st_size,
        }
        remote_checksums = {
            str(a.relative_to(root)): "0" * 64,
            str(b.relative_to(root)): vm.sha256_file(b),
        }
        sections = [
            ("metadata", [a]),
            ("docs", [b]),
        ]
        pending, warnings = mod._resume_skip(sections, remote_sizes, remote_checksums, root)
        assert {s for s, _ in pending} == {"metadata"}
        assert warnings == 0

    def test_size_only_fallback_warns(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        mod = _load_upload_module()
        root, a, b = self._build_release(tmp_path)
        remote_sizes = {
            str(a.relative_to(root)): a.stat().st_size,
            str(b.relative_to(root)): 9999,
        }
        remote_checksums = {}
        sections = [
            ("metadata", [a]),
            ("docs", [b]),
        ]
        pending, warnings = mod._resume_skip(sections, remote_sizes, remote_checksums, root)
        assert {s for s, _ in pending} == {"docs"}
        assert warnings == 2

    def test_modified_file_uploads_after_skip(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        mod = _load_upload_module()
        root, a, b = self._build_release(tmp_path)
        vm = _load_verify_module()
        original_a_hash = vm.sha256_file(a)
        remote_sizes = {
            str(a.relative_to(root)): a.stat().st_size,
            str(b.relative_to(root)): b.stat().st_size,
        }
        remote_checksums = {
            str(a.relative_to(root)): original_a_hash,
            str(b.relative_to(root)): vm.sha256_file(b),
        }
        a.write_text('{"x": 2}', encoding="utf-8")
        sections = [
            ("metadata", [a]),
            ("docs", [b]),
        ]
        pending, warnings = mod._resume_skip(sections, remote_sizes, remote_checksums, root)
        assert {s for s, _ in pending} == {"metadata"}
        assert warnings == 0


class TestPathPrefixResume:
    """Release files live under releases/<version>/… on the Hub; resume must
    compare against the prefixed repo paths."""

    def _build_release(self, tmp_path: Path):
        root = tmp_path / "rel"
        (root / "metadata").mkdir(parents=True)
        f = root / "metadata" / "a.json"
        f.write_text('{"x": 1}', encoding="utf-8")
        return root, f

    def test_prefix_match_skips(self, tmp_path: Path):
        mod = _load_upload_module()
        root, a = self._build_release(tmp_path)
        vm = _load_verify_module()
        rpath = "releases/v1.0/metadata/a.json"
        remote_sizes = {rpath: a.stat().st_size}
        remote_checksums = {rpath: vm.sha256_file(a)}
        pending, warnings = mod._resume_skip(
            [("metadata", [a])], remote_sizes, remote_checksums, root,
            path_prefix="releases/v1.0",
        )
        assert pending == []
        assert warnings == 0

    def test_prefix_mismatch_uploads(self, tmp_path: Path):
        mod = _load_upload_module()
        root, a = self._build_release(tmp_path)
        rpath = "releases/v1.0/metadata/a.json"
        # Same rel path WITHOUT prefix must NOT match when prefix is used.
        remote_sizes = {str(a.relative_to(root)): a.stat().st_size}
        pending, _ = mod._resume_skip(
            [("metadata", [a])], remote_sizes, {}, root,
            path_prefix="releases/v1.0",
        )
        assert {s for s, _ in pending} == {"metadata"}


# ---------------------------------------------------------------------------
# U-4: retry classification
# ---------------------------------------------------------------------------

class TestRetryClassification:
    def test_429_is_retryable(self):
        mod = _load_upload_module()
        exc = Exception("HTTPError: 429 Too Many Requests")
        assert mod._classify_upload_error(exc) == mod.UploadErrorCategory.RETRYABLE

    def test_500_is_retryable(self):
        mod = _load_upload_module()
        exc = Exception("Server Error: 500 Internal Server Error")
        assert mod._classify_upload_error(exc) == mod.UploadErrorCategory.RETRYABLE

    def test_connection_error_is_retryable(self):
        mod = _load_upload_module()
        exc = ConnectionError("connection timed out")
        assert mod._classify_upload_error(exc) == mod.UploadErrorCategory.RETRYABLE

    def test_401_is_fatal(self):
        mod = _load_upload_module()
        exc = Exception("401 Unauthorized")
        assert mod._classify_upload_error(exc) == mod.UploadErrorCategory.FATAL

    def test_403_is_fatal(self):
        mod = _load_upload_module()
        exc = Exception("403 Forbidden")
        assert mod._classify_upload_error(exc) == mod.UploadErrorCategory.FATAL

    def test_404_is_fatal(self):
        mod = _load_upload_module()
        exc = Exception("404 Repository Not Found")
        assert mod._classify_upload_error(exc) == mod.UploadErrorCategory.FATAL

    def test_bad_credentials_is_fatal(self):
        mod = _load_upload_module()
        exc = Exception("permission denied: bad credentials")
        assert mod._classify_upload_error(exc) == mod.UploadErrorCategory.FATAL

    def test_retries_only_retryable(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        mod = _load_upload_module()
        call_count = 0

        def fake_upload(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise Exception("500 Server Error")

        api = type("Api", (), {"upload_folder": fake_upload})()
        with pytest.raises(RuntimeError, match="upload failed"):
            mod._upload_section_with_retry(
                api,
                "dataset",
                [],
                repo_id="x/y",
                token="t",
                release_root=tmp_path,
                commit_message="msg",
                dry_run=False,
            )
        assert call_count == 3

    def test_fatal_aborts_immediately(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        mod = _load_upload_module()
        call_count = 0

        def fake_upload(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise Exception("401 Unauthorized")

        api = type("Api", (), {"upload_folder": fake_upload})()
        with pytest.raises(RuntimeError, match="fatal upload error"):
            mod._upload_section_with_retry(
                api,
                "dataset",
                [],
                repo_id="x/y",
                token="t",
                release_root=tmp_path,
                commit_message="msg",
                dry_run=False,
            )
        assert call_count == 1


# ---------------------------------------------------------------------------
# U-5/U-6: pre-upload verification gate
# ---------------------------------------------------------------------------

class TestPreUploadVerification:
    def test_valid_manifest_continues(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        mod = _load_upload_module()
        root = tmp_path / "release"
        data = root / "dataset" / "x.jsonl.zst"
        data.parent.mkdir(parents=True)
        (root / "metadata").mkdir(parents=True, exist_ok=True)
        data.write_bytes(b"content")
        vm = _load_verify_module()
        manifest_path = root / "metadata" / "checksums.sha256"
        manifest_path.write_text(
            vm.sha256_file(data) + "  " + str(data.relative_to(root)) + "\n",
            encoding="utf-8",
        )
        mod._pre_upload_verify(root)

    def test_corrupted_file_blocks_upload(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        mod = _load_upload_module()
        root = tmp_path / "release"
        data = root / "dataset" / "x.jsonl.zst"
        data.parent.mkdir(parents=True)
        (root / "metadata").mkdir(parents=True, exist_ok=True)
        data.write_bytes(b"content")
        vm = _load_verify_module()
        manifest_path = root / "metadata" / "checksums.sha256"
        manifest_path.write_text(
            vm.sha256_file(data) + "  " + str(data.relative_to(root)) + "\n",
            encoding="utf-8",
        )
        data.write_bytes(b"corrupted")
        with pytest.raises(RuntimeError, match="Pre-upload verification failed"):
            mod._pre_upload_verify(root)

    def test_missing_manifest_blocks_upload(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        mod = _load_upload_module()
        root = tmp_path / "release"
        with pytest.raises(SystemExit):
            mod._pre_upload_verify(root)


# ---------------------------------------------------------------------------
# Regression: existing upload behavior
# ---------------------------------------------------------------------------

class TestUploadRegression:
    def test_dry_run_plan(self, tmp_path: Path):
        mod = _load_upload_module()
        root = tmp_path / "release"
        (root / "docs").mkdir(parents=True)
        (root / "docs" / "card.md").write_text("# card", encoding="utf-8")
        rc = mod.main([
            "--repo-id", "fake/atlas-dataset",
            "--release", "v1.0-RC1",
            "--output", str(root),
            "--dry-run",
        ])
        assert rc == 0

    def test_resume_size_only_behavior_preserved(self, tmp_path: Path):
        mod = _load_upload_module()
        root = tmp_path / "release"
        (root / "docs").mkdir(parents=True)
        card = root / "docs" / "card.md"
        card.write_text("# card", encoding="utf-8")
        sections = [("docs", [card])]
        remote_sizes = {"docs/card.md": card.stat().st_size}
        pending, _ = mod._resume_skip(sections, remote_sizes, {}, root)
        assert pending == []
