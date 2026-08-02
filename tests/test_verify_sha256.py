#!/usr/bin/env python3
"""Tests for scripts/release/verify_sha256.py — shared release checksum module.

Covers:
- known sha256 vector
- correct file passes
- modified file fails
- missing file fails
- malformed manifest fails
- multiple file manifest
- deterministic output
- manifest self-consistency round-trip

Run:
  python3 -m pytest tests/test_verify_sha256.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS_RELEASE = ROOT / "scripts" / "release"
if str(SCRIPTS_RELEASE) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_RELEASE))

from verify_sha256 import (  # noqa: E402
    ManifestError,
    sha256_file,
    load_checksum_manifest,
    verify_file_sha256,
    verify_manifest_files,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


# ---------------------------------------------------------------------------
# Known vector
# ---------------------------------------------------------------------------

class TestKnownVector:
    def test_sha256_of_empty(self):
        # sha256 of empty string is well-known.
        import hashlib
        expected = hashlib.sha256(b"").hexdigest()
        f = HERE / "__pycache__" / "empty.sha256"
        _write(f, b"")
        assert sha256_file(f) == expected

    def test_sha256_of_ascii(self):
        import hashlib
        data = b"atlas-verify"
        expected = hashlib.sha256(data).hexdigest()
        f = HERE / "__pycache__" / "ascii.sha256"
        _write(f, data)
        assert sha256_file(f) == expected

    def test_sha256_deterministic(self, tmp_path: Path):
        f = tmp_path / "blob.bin"
        _write(f, bytes(range(256)))
        h1 = sha256_file(f)
        h2 = sha256_file(f)
        assert h1 == h2
        assert len(h1) == 64


# ---------------------------------------------------------------------------
# verify_file_sha256
# ---------------------------------------------------------------------------

class TestVerifyFileSha256:
    def test_matching_hash(self, tmp_path: Path):
        f = tmp_path / "ok.txt"
        _write(f, b"hello")
        expected = sha256_file(f)
        ok, actual = verify_file_sha256(f, expected)
        assert ok is True
        assert actual is None

    def test_mismatch_returns_actual(self, tmp_path: Path):
        f = tmp_path / "bad.txt"
        _write(f, b"hello")
        ok, actual = verify_file_sha256(f, "0" * 64)
        assert ok is False
        assert actual == sha256_file(f)

    def test_missing_file(self, tmp_path: Path):
        ok, actual = verify_file_sha256(tmp_path / "nope.txt", "abcd" * 16)
        assert ok is False
        assert actual is None


# ---------------------------------------------------------------------------
# load_checksum_manifest
# ---------------------------------------------------------------------------

class TestLoadChecksumManifest:
    def test_single_entry(self, tmp_path: Path):
        mf = tmp_path / "checksums.sha256"
        mf.write_text("a" * 64 + "  rel/path.txt\n", encoding="utf-8")
        out = load_checksum_manifest(mf)
        assert out == {"rel/path.txt": "a" * 64}

    def test_multiple_files_sorted(self, tmp_path: Path):
        mf = tmp_path / "checksums.sha256"
        mf.write_text(
            "\n".join([
                "a" * 64 + "  z/last.txt",
                "b" * 64 + "  a/first.txt",
                "c" * 64 + "  m/mid.txt",
            ]) + "\n",
            encoding="utf-8",
        )
        out = load_checksum_manifest(mf)
        assert list(out.keys()) == ["z/last.txt", "a/first.txt", "m/mid.txt"]
        assert list(out.values()) == ["a" * 64, "b" * 64, "c" * 64]

    def test_comments_and_blanks_ignored(self, tmp_path: Path):
        mf = tmp_path / "checksums.sha256"
        lines = [
            "# header",
            "",
            "d" * 64 + "  data/file.bin",
            "# trailing",
        ]
        mf.write_text("\n".join(lines) + "\n", encoding="utf-8")
        out = load_checksum_manifest(mf)
        assert list(out.keys()) == ["data/file.bin"]

    def test_malformed_line_raises(self, tmp_path: Path):
        mf = tmp_path / "checksums.sha256"
        mf.write_text("not-a-valid-line\n", encoding="utf-8")
        with pytest.raises(ManifestError, match="malformed"):
            load_checksum_manifest(mf)

    def test_invalid_hex_raises(self, tmp_path: Path):
        mf = tmp_path / "checksums.sha256"
        mf.write_text("xyz  rel.txt\n", encoding="utf-8")
        with pytest.raises(ManifestError, match="invalid sha256 hex"):
            load_checksum_manifest(mf)

    def test_case_normalization(self, tmp_path: Path):
        mf = tmp_path / "checksums.sha256"
        mf.write_text("ABCDEF0123456789" + "a" * 48 + "  rel.txt\n", encoding="utf-8")
        out = load_checksum_manifest(mf)
        assert out["rel.txt"] == ("abcdef0123456789" + "a" * 48)


# ---------------------------------------------------------------------------
# verify_manifest_files
# ---------------------------------------------------------------------------

class TestVerifyManifestFiles:
    def test_all_match(self, tmp_path: Path):
        root = tmp_path / "release"
        f = root / "data" / "file.bin"
        _write(f, b"content")
        expected = sha256_file(f)
        manifest = {"data/file.bin": expected}
        result = verify_manifest_files(root, manifest)
        assert result.ok is True
        assert result.verified == 1
        assert result.failed == 0

    def test_missing_file(self, tmp_path: Path):
        root = tmp_path / "release"
        manifest = {"missing.bin": "a" * 64}
        result = verify_manifest_files(root, manifest)
        assert result.ok is False
        assert "missing.bin" in result.missing
        assert result.verified == 0

    def test_modified_file_fails(self, tmp_path: Path):
        root = tmp_path / "release"
        f = root / "data" / "file.bin"
        _write(f, b"original")
        expected = sha256_file(f)
        # corrupt after recording manifest
        _write(f, b"modified")
        manifest = {"data/file.bin": expected}
        result = verify_manifest_files(root, manifest)
        assert result.ok is False
        assert len(result.mismatches) == 1
        assert "data/file.bin" in result.mismatches[0]

    def test_multiple_files_mixed(self, tmp_path: Path):
        root = tmp_path / "release"
        a = root / "a.txt"
        b = root / "b.txt"
        _write(a, b"aaa")
        _write(b, b"bbb")
        manifest = {
            "a.txt": sha256_file(a),
            "b.txt": "badhash",
            "missing.txt": "0" * 64,
        }
        result = verify_manifest_files(root, manifest)
        assert result.ok is False
        assert result.verified == 1
        assert len(result.mismatches) == 1
        assert len(result.missing) == 1

    def test_deterministic_result(self, tmp_path: Path):
        root = tmp_path / "release"
        f = root / "data" / "file.bin"
        _write(f, b"content")
        expected = sha256_file(f)
        manifest = {"data/file.bin": expected}
        r1 = verify_manifest_files(root, manifest)
        r2 = verify_manifest_files(root, manifest)
        assert r1.ok == r2.ok
        assert r1.verified == r2.verified
        assert r1.mismatches == r2.mismatches
        assert r1.missing == r2.missing


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_manifest_round_trip(self, tmp_path: Path):
        root = tmp_path / "release"
        files = {
            "a.txt": b"alpha",
            "b.txt": b"beta",
            "c.txt": b"gamma",
        }
        for rel, content in files.items():
            _write(root / rel, content)

        # build manifest
        manifest = {rel: sha256_file(root / rel) for rel in files}
        # verify
        result = verify_manifest_files(root, manifest)
        assert result.ok is True
        assert result.verified == len(files)

        # tamper one file
        _write(root / "b.txt", b"BET-A")
        result2 = verify_manifest_files(root, manifest)
        assert result2.ok is False
        assert any("b.txt" in m for m in result2.mismatches)
