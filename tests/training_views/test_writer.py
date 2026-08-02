#!/usr/bin/env python3
"""Tests for writer.py."""

from __future__ import annotations

import json

import pytest

ROOT = pytest.importorskip("pathlib").Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
import sys

sys.path.insert(0, str(SRC))

from atlas_training.training_views.writer import TrainingViewWriter  # noqa: E402


def test_safe_mode_blocks_writes(tmp_path):
    w = TrainingViewWriter(mode="safe")
    target = tmp_path / "train.jsonl"
    with pytest.raises(PermissionError):
        w.write_jsonl(target, [{"id": 1}])


def test_write_mode_emits_jsonl(tmp_path):
    w = TrainingViewWriter(mode="write")
    target = tmp_path / "train.jsonl"
    path = w.write_jsonl(target, [{"id": 1}, {"id": 2}])
    assert path.exists()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"id": 1}


def test_no_overwrite_jsonl(tmp_path):
    w = TrainingViewWriter(mode="write")
    target = tmp_path / "train.jsonl"
    w.write_jsonl(target, [{"id": 1}])
    with pytest.raises(FileExistsError):
        w.write_jsonl(target, [{"id": 2}])


def test_no_overwrite_json(tmp_path):
    w = TrainingViewWriter(mode="write")
    target = tmp_path / "manifest.json"
    w.write_json(target, {"a": 1})
    with pytest.raises(FileExistsError):
        w.write_json(target, {"a": 2})
