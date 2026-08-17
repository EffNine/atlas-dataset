"""Tests for eb/paths.py — EB path resolution and safety."""
import pytest
from pathlib import Path

from eb.paths import (
    APPROVED_WRITE_ROOTS,
    config_dir,
    discover_eb_root,
    get_root,
    is_write_safe,
    metadata_dir,
    outputs_dir,
    reports_dir,
    reset_root_cache,
    runs_dir,
    tasks_dir,
    templates_dir,
)


class TestDiscoverRoot:
    def setup_method(self):
        reset_root_cache()

    def test_discovers_from_eb_dir(self, tmp_eb_root: Path):
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_eb_root)
            root = discover_eb_root()
            assert root == tmp_eb_root
        finally:
            os.chdir(original_cwd)

    def test_discovers_from_subdir(self, tmp_eb_root: Path):
        import os
        original_cwd = os.getcwd()
        subdir = tmp_eb_root / "eb" / "core"
        subdir.mkdir(parents=True, exist_ok=True)
        try:
            os.chdir(subdir)
            root = discover_eb_root()
            assert root == tmp_eb_root
        finally:
            os.chdir(original_cwd)

    def test_cache(self, tmp_eb_root: Path):
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_eb_root)
            r1 = get_root()
            r2 = get_root()
            assert r1 == r2
        finally:
            os.chdir(original_cwd)


class TestPathHelpers:
    def setup_method(self):
        reset_root_cache()

    def test_tasks_dir(self, tmp_eb_root: Path):
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_eb_root)
            assert tasks_dir() == tmp_eb_root / "tasks"
        finally:
            os.chdir(original_cwd)

    def test_outputs_dir(self, tmp_eb_root: Path):
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_eb_root)
            assert outputs_dir() == tmp_eb_root / "outputs"
        finally:
            os.chdir(original_cwd)

    def test_metadata_dir(self, tmp_eb_root: Path):
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_eb_root)
            assert metadata_dir() == tmp_eb_root / "metadata"
        finally:
            os.chdir(original_cwd)

    def test_config_dir(self, tmp_eb_root: Path):
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_eb_root)
            assert config_dir() == tmp_eb_root / "config"
        finally:
            os.chdir(original_cwd)

    def test_reports_dir(self, tmp_eb_root: Path):
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_eb_root)
            assert reports_dir() == tmp_eb_root / "reports"
        finally:
            os.chdir(original_cwd)

    def test_runs_dir(self, tmp_eb_root: Path):
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_eb_root)
            assert runs_dir() == tmp_eb_root / "outputs" / "runs"
        finally:
            os.chdir(original_cwd)


class TestWriteSafety:
    def setup_method(self):
        reset_root_cache()

    def test_approved_paths_are_safe(self, tmp_eb_root: Path):
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_eb_root)
            assert is_write_safe(tmp_eb_root / "outputs" / "runs" / "test.json")
            assert is_write_safe(tmp_eb_root / "metadata" / "reg.json")
            assert is_write_safe(tmp_eb_root / "reports" / "r.txt")
        finally:
            os.chdir(original_cwd)

    def test_outside_root_is_unsafe(self, tmp_eb_root: Path):
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_eb_root)
            outside = tmp_eb_root.parent / "somewhere_else" / "file.txt"
            assert not is_write_safe(outside)
        finally:
            os.chdir(original_cwd)

    def test_approved_roots_constant(self):
        assert "outputs" in APPROVED_WRITE_ROOTS
        assert "metadata" in APPROVED_WRITE_ROOTS
        assert "reports" in APPROVED_WRITE_ROOTS
        assert "tasks" in APPROVED_WRITE_ROOTS
        assert "raw" not in APPROVED_WRITE_ROOTS
        assert "curated" not in APPROVED_WRITE_ROOTS
