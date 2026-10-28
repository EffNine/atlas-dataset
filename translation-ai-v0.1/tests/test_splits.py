"""Unit tests: split leak prevention + determinism."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tai.splits import norm_key, split_of  # noqa: E402


def test_norm_key_groups_near_identical():
    assert norm_key("Hello, World!") == norm_key("hello world")
    assert norm_key("夜色，很好。") == norm_key("夜色很好")


def test_split_of_deterministic_and_covering():
    assert split_of("abc") == split_of("abc")
    seen = {split_of(f"key-{i}") for i in range(3000)}
    assert seen == {"train", "val", "test"}


def test_split_ratios_approx():
    from collections import Counter
    c = Counter(split_of(f"sent-{i}-xyz") for i in range(20000))
    assert 0.03 < c["test"] / 20000 < 0.07
    assert 0.03 < c["val"] / 20000 < 0.07
    assert 0.85 < c["train"] / 20000 < 0.95
