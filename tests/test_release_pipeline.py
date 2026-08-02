#!/usr/bin/env python3
"""Unit + integration tests for the Atlas Hugging Face release pipeline.

Coverage:
  - compression: routing by category, mixed shards, verification, report
  - checksums: generate + verify (tamper detection)
  - verify_release: structure, counts, hashes; failure on tampered data
  - upload: dry-run plan, resume skip logic, token enforcement
  - release_index update: chain hashes preserved
  - download: checksum verification on a restored tree

Run (from repo root, with the release venv):
  .venv-release/bin/python -m pytest tests/test_release_pipeline.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "scripts" / "release"

sys.path.insert(0, str(SCRIPTS))

from common import CATEGORIES, count_jsonl_zst, sha256_file  # noqa: E402


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

def _rec(cat: str, sub: str, i: int) -> dict:
    return {
        "id": f"test_{cat.split('_')[0]}_{i:05d}",
        "category": cat,
        "subcategory": sub,
        "type": "instruction",
        "source": {
            "name": f"source-{cat}",
            "url": "https://example.invalid/source",
            "license": "MIT",
            "date": "2026-01-01",
        },
        "messages": [
            {"role": "user", "content": f"Question {i} about {sub}?"},
            {"role": "assistant", "content": f"Answer {i} with detail."},
        ],
        "language": "en",
        "difficulty": 2,
        "tags": ["test", cat],
        "quality_score": 8,
        "verified": True,
        "notes": "",
    }


@pytest.fixture()
def shards_dir(tmp_path: Path) -> Path:
    """Two shards: one single-category, one mixed."""
    d = tmp_path / "input"
    d.mkdir()
    # Single-category shard (06_science_engineering).
    with (d / "wiki_sci_shard0_atlas.jsonl").open("w", encoding="utf-8") as fh:
        for i in range(5):
            fh.write(json.dumps(_rec("06_science_engineering", "science", i)) + "\n")
    # Mixed shard (01_foundation + 08_creative_knowledge).
    with (d / "ultrafeedback_atlas.jsonl").open("w", encoding="utf-8") as fh:
        for i in range(3):
            fh.write(json.dumps(_rec("01_foundation", "general", i)) + "\n")
        for i in range(4):
            fh.write(json.dumps(_rec("08_creative_knowledge", "arts", i)) + "\n")
    return d


@pytest.fixture()
def release_dir(tmp_path: Path, shards_dir: Path) -> Path:
    """Build a release tree via the compress script (integration step)."""
    out = tmp_path / "releases" / "v1.0-RC1"
    cmd = [
        sys.executable,
        str(SCRIPTS / "compress_release.py"),
        "--input", str(shards_dir),
        "--pattern", "*_atlas.jsonl",
        "--output", str(out),
        "--workers", "2",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    assert res.returncode == 0, res.stderr
    # Add static metadata/docs so verify_release has a full bundle.
    (out / "metadata").mkdir(parents=True, exist_ok=True)
    (out / "docs").mkdir(parents=True, exist_ok=True)
    # All 9 category dirs exist in the real release skeleton (with .gitkeep).
    for cat in CATEGORIES:
        (out / "dataset" / cat).mkdir(parents=True, exist_ok=True)
    (out / "metadata" / "release.json").write_text(
        json.dumps(
            {"release_version": "v1.0-RC1", "status": "release_candidate",
             "total_records": 12, "gates_passed": True}
        ),
        encoding="utf-8",
    )
    (out / "metadata" / "provenance.json").write_text(
        json.dumps({"release_version": "v1.0-RC1", "sources": []}),
        encoding="utf-8",
    )
    (out / "docs" / "dataset_card.md").write_text("# card\n", encoding="utf-8")
    (out / "docs" / "release_notes.md").write_text("# notes\n", encoding="utf-8")
    return out


# --------------------------------------------------------------------------
# Phase 2 — compression
# --------------------------------------------------------------------------

class TestCompress:
    def test_routes_by_category_and_mixed_shards(self, release_dir: Path):
        sci = release_dir / "dataset" / "06_science_engineering"
        fnd = release_dir / "dataset" / "01_foundation"
        cre = release_dir / "dataset" / "08_creative_knowledge"
        assert (sci / "wiki_sci_shard0_atlas.jsonl.zst").exists()
        assert (fnd / "ultrafeedback_atlas.jsonl.zst").exists()
        assert (cre / "ultrafeedback_atlas.jsonl.zst").exists()

        # Filenames preserved; mixed shard split by category.
        assert count_jsonl_zst(sci / "wiki_sci_shard0_atlas.jsonl.zst") == 5
        assert count_jsonl_zst(fnd / "ultrafeedback_atlas.jsonl.zst") == 3
        assert count_jsonl_zst(cre / "ultrafeedback_atlas.jsonl.zst") == 4

    def test_statistics_and_report(self, release_dir: Path):
        stats = json.loads(
            (release_dir / "metadata" / "statistics.json").read_text(encoding="utf-8")
        )
        assert stats["total_records"] == 12
        assert stats["by_category"]["06_science_engineering"] == 5
        assert stats["by_category"]["01_foundation"] == 3
        assert stats["by_category"]["08_creative_knowledge"] == 4

        report = json.loads(
            (release_dir / "metadata" / "compression_report.json").read_text(
                encoding="utf-8"
            )
        )
        assert report["total_records"] == 12
        assert report["failures"] == []
        assert report["by_category"]["01_foundation"]["records"] == 3

    def test_dry_run_writes_nothing(self, tmp_path: Path, shards_dir: Path):
        out = tmp_path / "dryout"
        cmd = [
            sys.executable,
            str(SCRIPTS / "compress_release.py"),
            "--input", str(shards_dir),
            "--pattern", "*_atlas.jsonl",
            "--output", str(out),
            "--dry-run",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        assert res.returncode == 0, res.stderr
        assert not out.exists()

    def test_skips_existing(self, tmp_path: Path, shards_dir: Path):
        out = tmp_path / "rel"
        cmd = [
            sys.executable,
            str(SCRIPTS / "compress_release.py"),
            "--input", str(shards_dir),
            "--pattern", "*_atlas.jsonl",
            "--output", str(out),
            "--workers", "1",
        ]
        assert subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT).returncode == 0
        # Second run with --skip-existing should be a no-op success.
        cmd.append("--skip-existing")
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        assert res.returncode == 0, res.stderr
        assert "Nothing to do" in res.stdout or "Skipping" in res.stdout


# --------------------------------------------------------------------------
# Phase 3 — checksums
# --------------------------------------------------------------------------

class TestChecksums:
    def test_generate_and_verify(self, release_dir: Path):
        cmd = [
            sys.executable,
            str(SCRIPTS / "generate_checksums.py"),
            "--output", str(release_dir / "metadata" / "checksums.sha256"),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        assert res.returncode == 0, res.stderr
        lines = [
            l for l in (release_dir / "metadata" / "checksums.sha256")
            .read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")
        ]
        assert len(lines) > 5
        for line in lines:
            hexd, rel = line.split("  ", 1)
            assert len(hexd) == 64
            assert (release_dir / rel).exists()

        # Verify mode passes.
        res = subprocess.run(cmd + ["--verify"], capture_output=True, text=True, cwd=ROOT)
        assert res.returncode == 0, res.stdout + res.stderr

    def test_verify_detects_tamper(self, release_dir: Path):
        cmd = [
            sys.executable,
            str(SCRIPTS / "generate_checksums.py"),
            "--output", str(release_dir / "metadata" / "checksums.sha256"),
        ]
        subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        # Tamper with a dataset file.
        target = next(
            (release_dir / "dataset").rglob("*.jsonl.zst")
        )
        data = bytearray(target.read_bytes())
        data[0] ^= 0xFF
        target.write_bytes(bytes(data))
        res = subprocess.run(
            cmd + ["--verify"], capture_output=True, text=True, cwd=ROOT
        )
        assert res.returncode == 1
        assert "MISMATCH" in res.stdout


# --------------------------------------------------------------------------
# Phase 5 — verify_release
# --------------------------------------------------------------------------

class TestVerifyRelease:
    def test_passes_on_good_release(self, release_dir: Path):
        # Generate checksums first.
        subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "generate_checksums.py"),
                "--output", str(release_dir / "metadata" / "checksums.sha256"),
            ],
            capture_output=True, text=True, cwd=ROOT,
        )
        res = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "verify_release.py"),
                "--output", str(release_dir),
            ],
            capture_output=True, text=True, cwd=ROOT,
        )
        assert res.returncode == 0, res.stdout + res.stderr
        assert "RESULT: RELEASE OK" in res.stdout

    def test_fails_on_tampered_data(self, release_dir: Path):
        subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "generate_checksums.py"),
                "--output", str(release_dir / "metadata" / "checksums.sha256"),
            ],
            capture_output=True, text=True, cwd=ROOT,
        )
        target = next((release_dir / "dataset").rglob("*.jsonl.zst"))
        data = bytearray(target.read_bytes())
        data[-1] ^= 0xFF
        target.write_bytes(bytes(data))
        res = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "verify_release.py"),
                "--output", str(release_dir),
            ],
            capture_output=True, text=True, cwd=ROOT,
        )
        assert res.returncode == 1
        assert "FAIL" in res.stdout


# --------------------------------------------------------------------------
# Phase 4 — upload (no network; dry-run + resume logic)
# --------------------------------------------------------------------------

class TestUpload:
    def test_dry_run_requires_no_token(self, release_dir: Path, monkeypatch):
        monkeypatch.delenv("HF_TOKEN", raising=False)
        cmd = [
            sys.executable,
            str(SCRIPTS / "upload_huggingface.py"),
            "--repo-id", "fake/atlas-dataset",
            "--release", "v1.0-RC1",
            "--output", str(release_dir),
            "--dry-run",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        assert res.returncode == 0, res.stderr
        assert "DRY RUN" in res.stdout
        assert "dataset" in res.stdout

    def test_missing_checksums_manifest_fails_before_token_check(self, release_dir: Path, monkeypatch):
        monkeypatch.delenv("HF_TOKEN", raising=False)
        cmd = [
            sys.executable,
            str(SCRIPTS / "upload_huggingface.py"),
            "--repo-id", "fake/atlas-dataset",
            "--release", "v1.0-RC1",
            "--output", str(release_dir),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        assert res.returncode == 2
        assert "missing checksums manifest" in res.stdout

    def test_resume_plan_skips_matching_remote(self, tmp_path: Path):
        """Files matching remote size are skipped; differing/missing are pending."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "upload_huggingface", SCRIPTS / "upload_huggingface.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

        # Build a release tree with two files.
        root = tmp_path / "release"
        (root / "metadata").mkdir(parents=True)
        (root / "docs").mkdir(parents=True)
        (root / "metadata" / "release.json").write_text('{"a": 1}', encoding="utf-8")
        (root / "docs" / "card.md").write_text("# card", encoding="utf-8")
        sections = [("metadata", [root / "metadata" / "release.json"]),
                    ("docs", [root / "docs" / "card.md"])]

        # Remote has release.json with the same size -> skipped.
        remote = {
            "metadata/release.json": (root / "metadata" / "release.json").stat().st_size,
            "docs/card.md": 999999,  # differs -> pending
        }
        pending, _ = mod._resume_skip(sections, remote, {}, root)
        pending_names = {s for s, _ in pending}
        assert "metadata" not in pending_names
        assert "docs" in pending_names

        # Unknown remote size (-1) never skips.
        remote2 = {"docs/card.md": -1}
        pending2, _ = mod._resume_skip(sections, remote2, {}, root)
        assert {s for s, _ in pending2} == {"metadata", "docs"}

    def test_upload_collects_local_files(self, release_dir: Path):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "upload_huggingface", SCRIPTS / "upload_huggingface.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        files = mod._collect_local_files(release_dir)
        assert len(files) > 3
        sections = mod._plan_sections(release_dir)
        names = {s for s, _ in sections}
        assert {"dataset", "metadata", "docs"} <= names


# --------------------------------------------------------------------------
# Phase 6 — release_index update
# --------------------------------------------------------------------------

class TestReleaseIndex:
    def test_update_preserves_chain_hashes(self, tmp_path: Path):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "update_release_index", SCRIPTS / "update_release_index.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

        idx = tmp_path / "release_index.json"
        idx.write_text(
            json.dumps(
                {
                    "releases": [
                        {
                            "version": "v1.0-RC1",
                            "chain_hash": "e66408aa594d9438cae0f8bb393322e4e1433900fc4d515c2582bbf1d037b3cf",
                            "content_hash": "c2e117b9829f4dea994937c87782d59c3d9ff925a0bb1e6b8d4805f2f8f970a2",
                            "previous_hash": "009285f2099075e6c2eb8bc17ad27c76442a19cca547cc6ffa1643caebdf093c",
                            "release_id": "e66408aa594d9438",
                        }
                    ],
                    "genesis_hash": "34e190d38030793a5b2455997051d0be57bd6fc987278229f7c11f435ab82b4b",
                }
            ),
            encoding="utf-8",
        )
        mod.update_index(
            release="v1.0-RC1",
            repo_id="EffNine/atlas-dataset",
            commit_url="https://huggingface.co/datasets/EffNine/atlas-dataset/commit/abc",
            commit_hash="abc123",
            files=42,
            index_path=idx,
        )
        updated = json.loads(idx.read_text(encoding="utf-8"))
        entry = updated["releases"][0]
        assert entry["chain_hash"].startswith("e66408aa594d9438")
        assert entry["content_hash"].startswith("c2e117b9829f4dea")
        assert entry["previous_hash"].startswith("009285f2099075e6")
        assert entry["hub"]["repo_id"] == "EffNine/atlas-dataset"
        assert entry["hub"]["files"] == 42
        assert entry["hub"]["verified"] is True
        assert updated["genesis_hash"].startswith("34e190d38030793a")


# --------------------------------------------------------------------------
# Phase 7 — download (checksum verification path, no network)
# --------------------------------------------------------------------------

class TestDownload:
    def test_missing_token_fails(self, monkeypatch):
        monkeypatch.delenv("HF_TOKEN", raising=False)
        cmd = [
            sys.executable,
            str(SCRIPTS / "download_release.py"),
            "--repo-id", "fake/atlas-dataset",
            "--release", "v1.0-RC1",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        assert res.returncode == 1
        assert "HF_TOKEN" in res.stderr
