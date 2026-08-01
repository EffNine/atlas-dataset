#!/usr/bin/env python3
"""Tests for the Atlas Release Join Stage (scripts/release/join_release.py).

Coverage:
  - streaming: full-record pass + stub resolution without loading everything
  - deterministic output: two runs produce identical files
  - category routing: records land in the right category dir
  - record counts: total = full + stubs, all stubs resolved
  - duplicate detection: repeated ids flagged
  - validation: manifest category counts enforced
  - output formats: jsonl (spec) and zst (disk-safe)

Run (from repo root, with the release venv):
  .venv-release/bin/python -m pytest tests/test_join_release.py -v
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "scripts" / "release"

sys.path.insert(0, str(SCRIPTS))

from join_release import ReleaseJoiner, merge_record  # noqa: E402


def _full(cat: str, i: int, source: str = "src-test") -> dict:
    return {
        "id": f"full_{cat.split('_')[0]}_{i:05d}",
        "category": cat,
        "subcategory": "general",
        "type": "instruction",
        "source": {"name": source, "url": "https://example.invalid", "license": "MIT",
                   "date": "2026-01-01"},
        "messages": [
            {"role": "user", "content": f"Q{i}"},
            {"role": "assistant", "content": f"A{i} with real content"},
        ],
        "language": "en",
        "difficulty": 2,
        "tags": ["test", cat],
        "quality_score": 8,
        "verified": True,
        "notes": "",
    }


def _stub(cat: str, i: int, prefix: str = "s6") -> dict:
    return {
        "id": f"{prefix}_{cat}_{i:04d}",
        "category": cat,
        "subcategory": "reviewed",
        "quality_score": 7,
        "license": "ODC-BY",
        "verification_status": "approved",
        "verification_date": "2026-07-30",
        "reviewer": "auto-batch",
    }


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

@pytest.fixture()
def join_env(tmp_path: Path):
    """Synthetic approved.jsonl + shards + pilot sources mirroring the real model."""
    env = tmp_path / "env"
    (env / "shards").mkdir(parents=True)
    (env / "pilot").mkdir(parents=True)
    (env / "out").mkdir(parents=True)
    (env / "reports").mkdir(parents=True)

    # approved.jsonl: 3 full records + 4 stubs
    approved = [
        _full("01_foundation", 0),
        _full("02_software_engineering", 0),
        _full("06_science_engineering", 0),
        _stub("03_system_engineering", 0, "s6"),   # -> resolved from shard
        _stub("04_ai_machine_learning", 0, "s6"),  # -> resolved from shard
        _stub("05_hardware_engineering", 0, "pilot"),  # -> resolved from pilot
        _stub("07_business_knowledge", 0, "pilot"),    # -> resolved from pilot
    ]
    (env / "approved.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in approved),
        encoding="utf-8",
    )

    # Shard with content for the two s6 stubs (mixed categories like real data)
    shard_recs = [
        _full("03_system_engineering", 1, "shard-sys"),  # extra, not in approved
        {**_full("03_system_engineering", 0, "shard-sys"), "id": "s6_03_system_engineering_0000"},
        {**_full("04_ai_machine_learning", 0, "shard-ml"), "id": "s6_04_ai_machine_learning_0000"},
    ]
    (env / "shards" / "shard0_atlas.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in shard_recs),
        encoding="utf-8",
    )

    # Pilot source with content for the two pilot stubs
    pilot_recs = [
        {**_full("05_hardware_engineering", 0, "pilot-src"), "id": "pilot_05_hardware_engineering_0000"},
        {**_full("07_business_knowledge", 0, "pilot-src"), "id": "pilot_07_business_knowledge_0000"},
    ]
    (env / "pilot" / "pilot_records.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in pilot_recs),
        encoding="utf-8",
    )

    # Manifest: 7 records, by_category = full (3) + stubs (4)
    manifest = {
        "release_version": "v1.0-RC1",
        "total_records": 7,
        "statistics": {"by_category": {
            "01_foundation": 1,
            "02_software_engineering": 1,
            "03_system_engineering": 1,
            "04_ai_machine_learning": 1,
            "05_hardware_engineering": 1,
            "06_science_engineering": 1,
            "07_business_knowledge": 1,
            "08_creative_knowledge": 0,
            "09_personal_assistant": 0,
        }},
    }
    (env / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return env


def _run_join(env: Path, *extra: str) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(SCRIPTS / "join_release.py"),
        "--approved", str(env / "approved.jsonl"),
        "--shards", str(env / "shards"),
        "--pattern", "*_atlas.jsonl",
        "--pilot-dirs", str(env / "pilot"),
        "--output", str(env / "out"),
        "--manifest", str(env / "manifest.json"),
        "--report", str(env / "reports" / "join_report.json"),
        *extra,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)


# --------------------------------------------------------------------------
# Unit tests
# --------------------------------------------------------------------------

class TestMerge:
    def test_merge_preserves_content_and_approved_review(self):
        stub = _stub("03_system_engineering", 0)
        content = _full("03_system_engineering", 0)
        merged = merge_record(stub, content)
        # approved review fields win
        assert merged["quality_score"] == 7
        assert merged["license"] == "ODC-BY"
        assert merged["reviewer"] == "auto-batch"
        assert merged["verification_status"] == "approved"
        assert merged["category"] == "03_system_engineering"
        # content preserved
        assert merged["messages"] == content["messages"]
        assert merged["source"] == content["source"]
        assert merged["id"] == stub["id"]

    def test_merge_keeps_stub_id(self):
        stub = _stub("04_ai_machine_learning", 0)
        content = _full("04_ai_machine_learning", 0)
        merged = merge_record(stub, content)
        assert merged["id"] == stub["id"]


class TestJoiner:
    def test_streaming_counts(self, join_env: Path):
        joiner = ReleaseJoiner(
            output_dir=join_env / "out",
            manifest_path=join_env / "manifest.json",
        )
        joiner.scan_approved(join_env / "approved.jsonl")
        assert joiner.full_records == 3
        assert joiner.stub_records == 4
        assert len(joiner.stub_meta) == 4
        joiner.resolve_from_shards(join_env / "shards", "*_atlas.jsonl")
        assert joiner.joined_from_shards == 2
        joiner.resolve_from_pilot([join_env / "pilot"])
        assert joiner.joined_from_pilot == 2
        assert len(joiner.stub_meta) == 0
        joiner.close()

    def test_category_routing_and_counts(self, join_env: Path):
        res = _run_join(join_env)
        assert res.returncode == 0, res.stderr
        # per-category files exist with the right record count
        for cat, count in [
            ("01_foundation", 1),
            ("02_software_engineering", 1),
            ("03_system_engineering", 1),
            ("04_ai_machine_learning", 1),
            ("05_hardware_engineering", 1),
            ("06_science_engineering", 1),
            ("07_business_knowledge", 1),
        ]:
            f = join_env / "out" / cat / f"{cat}.jsonl"
            assert f.exists(), f"missing {f}"
            lines = [l for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
            assert len(lines) == count, f"{cat}: {len(lines)} != {count}"

    def test_total_and_validation(self, join_env: Path):
        res = _run_join(join_env)
        assert res.returncode == 0, res.stderr
        report = json.loads(
            (join_env / "reports" / "join_report.json").read_text(encoding="utf-8")
        )
        assert report["statistics"]["approved_records"] == 7
        assert report["statistics"]["joined_from_shards"] == 2
        assert report["statistics"]["joined_from_pilot"] == 2
        assert report["statistics"]["duplicate_count"] == 0
        assert report["validation"]["all_ok"] is True

    def test_deterministic_output(self, join_env: Path):
        out1 = join_env / "out1"
        out2 = join_env / "out2"
        res1 = _run_join(join_env, "--output", str(out1))
        res2 = _run_join(join_env, "--output", str(out2))
        assert res1.returncode == 0 and res2.returncode == 0
        hashes1 = {
            p.relative_to(out1): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in out1.rglob("*.jsonl")
        }
        hashes2 = {
            p.relative_to(out2): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in out2.rglob("*.jsonl")
        }
        assert hashes1 == hashes2

    def test_duplicate_detection(self, join_env: Path):
        # duplicate stub id in shards + a duplicate full record in approved
        with (join_env / "approved.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_full("01_foundation", 0)) + "\n")  # same id as existing
        with (join_env / "shards" / "shard0_atlas.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps({**_full("03_system_engineering", 0, "shard-sys"),
                            "id": "s6_03_system_engineering_0000"}) + "\n"
            )
        res = _run_join(join_env)
        report = json.loads(
            (join_env / "reports" / "join_report.json").read_text(encoding="utf-8")
        )
        # The duplicate full record is flagged; the duplicate stub id in the
        # shard is correctly ignored (stub popped on first resolution).
        assert report["statistics"]["duplicate_count"] >= 1
        assert report["validation"]["checks"]["no_duplicate_ids"]["ok"] is False

    def test_zst_output_mode(self, join_env: Path):
        out = join_env / "out_zst"
        res = _run_join(join_env, "--output", str(out), "--output-format", "zst")
        assert res.returncode == 0, res.stderr
        zst_files = sorted(out.rglob("*.jsonl.zst"))
        assert len(zst_files) == 7
        # decompress and count one category
        import zstandard
        dctx = zstandard.ZstdDecompressor()
        with open(out / "03_system_engineering" / "03_system_engineering.jsonl.zst", "rb") as fh:
            reader = dctx.stream_reader(fh)
            data = reader.read()
        lines = [l for l in data.decode("utf-8").splitlines() if l.strip()]
        assert len(lines) == 1

    def test_missing_stub_fails_validation(self, join_env: Path):
        # remove the pilot source -> 2 stubs unresolved
        (join_env / "pilot" / "pilot_records.jsonl").unlink()
        res = _run_join(join_env)
        assert res.returncode == 1
        report = json.loads(
            (join_env / "reports" / "join_report.json").read_text(encoding="utf-8")
        )
        assert report["statistics"]["missing_stub_count"] == 2
        assert report["validation"]["checks"]["no_missing_stubs"]["ok"] is False


class TestPilotNestedRecord:
    def test_review_input_wrapped_record(self, join_env: Path, tmp_path: Path):
        """review/v0.2/batch_001_input.jsonl wraps records under 'record'."""
        pilot = tmp_path / "nested"
        pilot.mkdir()
        rec = {**_full("05_hardware_engineering", 0, "nested-src"),
               "id": "pilot_05_hardware_engineering_0000"}
        (pilot / "batch_input.jsonl").write_text(
            json.dumps({"record_id": rec["id"], "record": rec}) + "\n", encoding="utf-8"
        )
        joiner = ReleaseJoiner(output_dir=tmp_path / "out",
                               manifest_path=join_env / "manifest.json")
        joiner.scan_approved(join_env / "approved.jsonl")
        joiner.resolve_from_shards(join_env / "shards", "*_atlas.jsonl")
        joiner.resolve_from_pilot([pilot])
        assert joiner.joined_from_pilot >= 1
        joiner.close()
