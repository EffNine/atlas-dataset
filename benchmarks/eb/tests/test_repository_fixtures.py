"""Tests for repository fixture management — schema validation, hashing, copies."""
import json
import pytest
from pathlib import Path

from eb.runners.repository import RepositoryFixture


class TestRepositoryFixtureSchema:
    def test_from_manifest(self, tmp_path: Path):
        fixture_dir = tmp_path / "eb-test-fix-001"
        fixture_dir.mkdir()
        manifest = {
            "id": "eb-test-fix-001",
            "version": "1.0",
            "language": "python",
            "framework": "pytest",
            "image": "python:3.11-slim",
            "source_path": "source",
            "test_command": "pytest -q",
            "timeout": 60.0,
            "expected_base_state": {"files": ["parser.py"]},
            "metadata": {"description": "Test fixture"},
        }
        (fixture_dir / "fixture.json").write_text(json.dumps(manifest))
        (fixture_dir / "source").mkdir()
        (fixture_dir / "source" / "parser.py").write_text("print('hello')")

        fixture = RepositoryFixture.from_manifest(fixture_dir / "fixture.json")
        assert fixture.fixture_id == "eb-test-fix-001"
        assert fixture.language == "python"
        assert fixture.test_command == "pytest -q"
        assert fixture.image == "python:3.11-slim"
        assert fixture.timeout == 60.0

    def test_missing_id_raises(self, tmp_path: Path):
        fixture_dir = tmp_path / "bad-fixture"
        fixture_dir.mkdir()
        (fixture_dir / "fixture.json").write_text(json.dumps({"version": "1.0"}))
        with pytest.raises(KeyError):
            RepositoryFixture.from_manifest(fixture_dir / "fixture.json")

    def test_defaults(self, tmp_path: Path):
        fixture_dir = tmp_path / "minimal-fixture"
        fixture_dir.mkdir()
        (fixture_dir / "fixture.json").write_text(json.dumps({"id": "minimal-fixture"}))

        fixture = RepositoryFixture.from_manifest(fixture_dir / "fixture.json")
        assert fixture.version == "1.0"
        assert fixture.source_path == "source"
        assert fixture.test_command == ""
        assert fixture.lint_command is None
        assert fixture.typecheck_command is None
        assert fixture.timeout == 300.0
        assert fixture.workspace_path == "/workspace"


class TestFixtureHash:
    def test_compute_hash(self, tmp_path: Path):
        # Fixtures live under repositories/fixtures/<id>/
        fixture_dir = tmp_path / "fixtures" / "hash-test-001"
        fixture_dir.mkdir(parents=True)
        (fixture_dir / "fixture.json").write_text(json.dumps({"id": "hash-test-001"}))
        src = fixture_dir / "source"
        src.mkdir()
        (src / "main.py").write_text("def hello(): pass\n")
        (src / "utils.py").write_text("def util(): return 1\n")

        fixture = RepositoryFixture.from_manifest(fixture_dir / "fixture.json")
        h = fixture.compute_hash(tmp_path)
        assert len(h) == 16
        assert fixture.fixture_hash == h

    def test_hash_is_deterministic(self, tmp_path: Path):
        fixture_dir = tmp_path / "fixtures" / "det-test-001"
        fixture_dir.mkdir(parents=True)
        (fixture_dir / "fixture.json").write_text(json.dumps({"id": "det-test-001"}))
        src = fixture_dir / "source"
        src.mkdir()
        (src / "a.py").write_text("x = 1\n")

        fixture = RepositoryFixture.from_manifest(fixture_dir / "fixture.json")
        h1 = fixture.compute_hash(tmp_path)
        h2 = fixture.compute_hash(tmp_path)
        assert h1 == h2

    def test_hash_changes_on_modification(self, tmp_path: Path):
        fixture_dir = tmp_path / "fixtures" / "mod-test-001"
        fixture_dir.mkdir(parents=True)
        (fixture_dir / "fixture.json").write_text(json.dumps({"id": "mod-test-001"}))
        src = fixture_dir / "source"
        src.mkdir()
        (src / "a.py").write_text("x = 1\n")

        fixture = RepositoryFixture.from_manifest(fixture_dir / "fixture.json")
        h1 = fixture.compute_hash(tmp_path)

        (src / "a.py").write_text("x = 2\n")
        h2 = fixture.compute_hash(tmp_path)
        assert h1 != h2

    def test_git_files_excluded(self, tmp_path: Path):
        fixture_dir = tmp_path / "fixtures" / "git-test-001"
        fixture_dir.mkdir(parents=True)
        (fixture_dir / "fixture.json").write_text(json.dumps({"id": "git-test-001"}))
        src = fixture_dir / "source"
        src.mkdir()
        git_dir = src / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
        (src / "main.py").write_text("x = 1\n")

        fixture = RepositoryFixture.from_manifest(fixture_dir / "fixture.json")
        h = fixture.compute_hash(tmp_path)
        assert len(h) == 16


class TestCleanCopy:
    def test_create_workspace_copy(self, tmp_path: Path):
        """Simulate what _create_workspace_copy does."""
        fixtures_root = tmp_path / "repositories"
        fixture_dir = fixtures_root / "copy-test-001"
        fixture_dir.mkdir(parents=True)
        (fixture_dir / "fixture.json").write_text(json.dumps({"id": "copy-test-001"}))
        src = fixture_dir / "source"
        src.mkdir()
        (src / "main.py").write_text("def main(): pass\n")
        (src / "config.yaml").write_text("key: value\n")

        import shutil
        import tempfile
        workspace = Path(tempfile.mkdtemp(prefix="eb-exec-copy-test-001-"))
        try:
            for item in fixture_dir.iterdir():
                if item.name == "fixture.json":
                    continue
                if item.is_dir():
                    shutil.copytree(item, workspace / item.name, symlinks=True)
                else:
                    shutil.copy2(item, workspace / item.name)

            assert (workspace / "source" / "main.py").exists()
            assert (workspace / "source" / "config.yaml").exists()
            assert (workspace / "source" / "main.py").read_text() == "def main(): pass\n"
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_canonical_fixture_unchanged(self, tmp_path: Path):
        """Verify the canonical fixture is not modified by copy creation."""
        fixtures_root = tmp_path / "repositories"
        fixture_dir = fixtures_root / "unchanged-test-001"
        fixture_dir.mkdir(parents=True)
        orig_content = json.dumps({"id": "unchanged-test-001", "version": "1.0"})
        (fixture_dir / "fixture.json").write_text(orig_content)
        src = fixture_dir / "source"
        src.mkdir()
        (src / "main.py").write_text("original\n")

        import shutil
        import tempfile
        workspace = Path(tempfile.mkdtemp(prefix="eb-exec-unchanged-test-001-"))
        try:
            for item in fixture_dir.iterdir():
                if item.name == "fixture.json":
                    continue
                if item.is_dir():
                    shutil.copytree(item, workspace / item.name, symlinks=True)
                else:
                    shutil.copy2(item, workspace / item.name)

            # Canonical fixture unchanged
            assert (fixture_dir / "fixture.json").read_text() == orig_content
            assert (fixture_dir / "source" / "main.py").read_text() == "original\n"
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
