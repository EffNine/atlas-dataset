"""Tests for evaluation_research."""
import sys
from pathlib import Path
_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import pytest
from evaluation_research.artifacts import (
    sha256_file,
    sha256_text,
    canonical_json,
    ArtifactVerifier,
)


class TestHashing:
    def test_sha256_text_deterministic(self):
        h1 = sha256_text("hello world")
        h2 = sha256_text("hello world")
        assert h1 == h2
        assert len(h1) == 64

    def test_sha256_text_different_inputs(self):
        assert sha256_text("hello") != sha256_text("world")

    def test_sha256_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        h = sha256_file(f)
        assert len(h) == 64
        assert sha256_file(f) == h

    def test_canonical_json_sorted(self):
        obj = {"b": 2, "a": 1, "c": [3, 2, 1]}
        j1 = canonical_json(obj)
        j2 = canonical_json(obj)
        assert j1 == j2
        assert j1.startswith('{"a":1,"b":2,"c":[3,2,1]}')


class TestArtifactVerifier:
    def test_verify_file_match(self, tmp_path):
        f = tmp_path / "data.jsonl"
        f.write_text('{"id": "r1"}\n{"id": "r2"}\n', encoding="utf-8")
        verifier = ArtifactVerifier(tmp_path)
        verified, actual = verifier.verify_file("data.jsonl", sha256_file(f))
        assert verified is True
        assert actual == sha256_file(f)

    def test_verify_file_mismatch(self, tmp_path):
        f = tmp_path / "data.jsonl"
        f.write_text("hello", encoding="utf-8")
        verifier = ArtifactVerifier(tmp_path)
        verified, _ = verifier.verify_file("data.jsonl", "wronghash")
        assert verified is False

    def test_verify_file_missing(self, tmp_path):
        verifier = ArtifactVerifier(tmp_path)
        verified, actual = verifier.verify_file("nonexistent.jsonl", "any")
        assert verified is False
        assert actual == ""

    def test_verify_jsonl(self, tmp_path):
        f = tmp_path / "records.jsonl"
        import json
        records = [{"id": f"r{i}", "value": i} for i in range(5)]
        f.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        verifier = ArtifactVerifier(tmp_path)
        result = verifier.verify_jsonl(f)
        assert result["record_count"] == 5
        assert result["file_sha256"] == sha256_file(f)

    def test_verify_experiment_dir(self, tmp_path):
        exp_dir = tmp_path / "experiments" / "test-exp"
        exp_dir.mkdir(parents=True)
        (exp_dir / "run_metadata.json").write_text("{}", encoding="utf-8")
        (exp_dir / "config.json").write_text("{}", encoding="utf-8")
        verifier = ArtifactVerifier(tmp_path)
        result = verifier.verify_experiment_dir(exp_dir)
        assert result["run_metadata.json"]["exists"] is True
        assert result["config.json"]["exists"] is True
