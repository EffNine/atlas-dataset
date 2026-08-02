#!/usr/bin/env python3
"""Tests for splitter.py."""

from __future__ import annotations

import pytest

ROOT = pytest.importorskip("pathlib").Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
import sys

sys.path.insert(0, str(SRC))

from atlas_training.training_views.splitter import DeterministicSplitter  # noqa: E402


def _records(n: int):
    return [{"id": f"rec_{i:03d}", "content": str(i)} for i in range(n)]


def test_split_empty_input():
    s = DeterministicSplitter(seed="s")
    train, validation, eval_ = s.split([])
    assert train == validation == eval_ == []


def test_split_determinism():
    s = DeterministicSplitter(seed="atlas")
    recs = _records(50)
    a = s.split(recs)
    b = s.split(recs)
    assert a == b


def test_split_counts():
    s = DeterministicSplitter(seed="atlas")
    recs = _records(100)
    train, validation, eval_ = s.split(recs)
    assert len(train) + len(validation) + len(eval_) == 100
    assert len(train) > 0
    assert len(validation) > 0
    assert len(eval_) >= 0


def test_split_ratios_default():
    s = DeterministicSplitter(seed="atlas")
    recs = _records(1000)
    train, validation, eval_ = s.split(recs)
    assert 0.75 <= len(train) / 1000 <= 0.85
    assert 0.05 <= len(validation) / 1000 <= 0.15


def test_split_invalid_ratios():
    s = DeterministicSplitter(seed="atlas")
    with pytest.raises(ValueError):
        s.split(_records(10), train_ratio=0.9, validation_ratio=0.2)


def test_split_stable_by_id():
    s = DeterministicSplitter(seed="atlas")
    recs_a = [{"id": "a", "x": 1}, {"id": "b", "x": 2}]
    recs_b = [{"id": "b", "x": 2}, {"id": "a", "x": 1}]
    train_a, val_a, eval_a = s.split(recs_a)
    train_b, val_b, eval_b = s.split(recs_b)
    assert [r["id"] for r in train_a] == [r["id"] for r in train_b]
