"""Unit tests: preprocessing checks (no network, no data files needed)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from tai.preprocess import check_pair, script_ok  # noqa: E402


def rec(src, tgt, sl="zh"):
    return {"id": "x", "source_lang": sl, "source": src,
            "target_lang": "en", "target": tgt}


def test_script_ok_zh():
    assert script_ok("夜色的街道，雨点落在积水上", "zh")
    assert not script_ok("Hello world this is english", "zh")


def test_script_ok_ja():
    assert script_ok("夜の街角、雨粒が路面に散った", "ja")
    assert not script_ok("Hello world this is english", "ja")


def test_script_ok_ko():
    assert script_ok("어두운 골목에 비가 내렸다", "ko")
    assert not script_ok("Hello world this is english", "ko")


def test_script_ok_ms_en():
    assert script_ok("Selamat pagi, apa khabar hari ini", "ms")
    assert script_ok("Good morning, how are you today", "en")
    assert not script_ok("夜色的街道雨点落", "ms")


def test_malformed_and_empty():
    seen = set()
    assert check_pair({"source": "x"}, seen) == "malformed_pair"
    assert check_pair(rec("  ", "hello"), seen) == "empty_pair"
    assert check_pair(rec("你好世界", "   "), seen) == "empty_pair"


def test_copy_and_too_long_and_misaligned():
    seen = set()
    assert check_pair(rec("hello world", "hello world", sl="ms"), seen) == "copy_pair"
    assert check_pair(rec("你好" * 600, "hi there friend"), seen) == "too_long"
    assert check_pair(rec("你好", " ".join(["word"] * 100)), seen) == "misaligned"


def test_duplicate_and_keep():
    seen = set()
    assert check_pair(rec("夜色很好", "The night is nice"), seen) is None
    seen.add(("夜色很好", "The night is nice"))
    assert check_pair(rec("夜色很好", "The night is nice"), seen) == "duplicate"


def test_provenance_preserved(tmp_path):
    import json
    from tai.preprocess import clean_file
    raw = tmp_path / "raw_zh-en.jsonl"
    rows = [
        {"id": "a1", "source_lang": "zh", "source": "夜色很好",
         "target_lang": "en", "target": "The night is nice",
         "provenance": {"dataset": "opus-100", "row_offset": 0}},
        {"id": "a2", "source_lang": "zh", "source": "   ",
         "target_lang": "en", "target": "empty source",
         "provenance": {"dataset": "opus-100", "row_offset": 1}},
    ]
    raw.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                   encoding="utf-8")
    stats = clean_file(raw, tmp_path / "c.jsonl", tmp_path / "r.jsonl")
    assert stats["kept"] == 1 and stats["empty_pair"] == 1
    kept = json.loads((tmp_path / "c.jsonl").read_text(encoding="utf-8"))
    assert kept["provenance"]["dataset"] == "opus-100"  # provenance untouched
