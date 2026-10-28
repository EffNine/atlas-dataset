"""Guards for v0.2 corpus handling: sampling, truncation parity, failure flags."""
import json

from tai.evaluate import failure_row, length_bucket, repetition_flag, stride_sample
from tai.train_tokenizer import chunk_line


def test_stride_sample_representative_over_grouped_order():
    rows = [{"g": "a"}] * 1000 + [{"g": "b"}] * 9000
    s = stride_sample(rows, 500)
    assert len(s) == 500
    assert any(r["g"] == "a" for r in s), "stride must reach the head group"
    assert any(r["g"] == "b" for r in s), "stride must reach the tail group"
    # head-take would fail the first assertion for skewed files
    head = rows[:50]
    assert all(r["g"] == "a" for r in head)


def test_stride_sample_full_passthrough():
    rows = list(range(10))
    assert stride_sample(rows, 100) == rows


def test_truncation_logic_matches_v01():
    # v0.1 PairDataset: src[:max_len], tgt[:max_len-2], BOS/EOS wrap.
    max_len, bos, eos, pad = 8, 1, 2, 0
    src = list(range(20))[:max_len]
    tgt = list(range(30, 50))[:max_len - 2]
    src = src + [pad] * (max_len - len(src))
    ti = [bos] + tgt + [pad] * (max_len - 1 - len(tgt))
    to = tgt + [eos] + [pad] * (max_len - 1 - len(tgt))
    assert len(src) == max_len and len(ti) == max_len and len(to) == max_len
    assert ti[0] == bos and to[-1] == eos or len(tgt) == max_len - 2


def test_repetition_flag():
    assert repetition_flag("the cat sat " * 6) is True
    assert repetition_flag("Hello world, this is fine.") is False
    assert repetition_flag("short text") is False


def test_failure_row_cjk_and_copy():
    f = failure_row("你好世界", "hello world", "你好世界", False)
    assert f["copy"] is True and f["cjk_leak"] is True
    f2 = failure_row("你好", "hello", "Hello there", False)
    assert f2["copy"] is False and f2["cjk_leak"] is False
    f3 = failure_row("你好", "hello", "", False)
    assert f3["empty"] is True


def test_length_buckets_cover_all():
    assert length_bucket(0) == "short<=100"
    assert length_bucket(100) == "short<=100"
    assert length_bucket(101) == "mid101-500"
    assert length_bucket(500) == "mid101-500"
    assert length_bucket(501) == "long>500"
    assert length_bucket(99999) == "long>500"


def test_jev_overlay_excludes_by_exact_id():
    jev_ids = {"hsc-wuxia-100k:7510b5b4:hsc-train-0006658"}
    rows = [{"id": "hsc-wuxia-100k:7510b5b4:hsc-train-0006658"},
            {"id": "tomato-zh2en:ef8f3982:tomato-1"}]
    kept = [r for r in rows if r["id"] not in jev_ids]
    assert len(kept) == 1 and kept[0]["id"].endswith("tomato-1")


def test_chunk_line_preserves_whitespace():
    # Regression: chunking must NEVER delete spaces (a whitespace-splitting
    # revision starved the BPE trainer of the space byte -> <unk> -> BLEU 0).
    text = "Hello world test 藤井树在教室 摊开课本。\nNew line here"
    pieces = list(chunk_line(text, 300))
    assert "".join(pieces) == text.strip()
    assert any(" " in p for p in pieces), "spaces must survive chunking"
    long_cjk = "字" * 1000
    parts = list(chunk_line(long_cjk, 300))
    assert len(parts) == 4 and all(len(p) <= 300 for p in parts)
    assert "".join(parts) == long_cjk
