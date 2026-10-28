"""Step T2 — Train a shared zh<->en subword tokenizer (BPE), zh→en ONLY.

CRITICAL: trains on the zh TRAIN split only. Val/test are never seen here.
Mirrors translation-ai-v0.1's train_tokenizer (same backend, same special
tokens, same 16k vocab) except:

- zh-only (the v0.2 experiment scope).
- Deterministic STRIDE sampling: the v1.1 split files are grouped by source
  (hsc rows first, then tomato), so a naive head-take would be hsc-skewed.
  We stream-count eligible rows, then take every k-th row for an exactly
  representative sample.
- JEV tombstoned ids (post_jev_removals.json) are excluded.

Backend: HuggingFace `tokenizers` (BPE, byte-level alphabet, full CJK coverage).

Usage:
    PYTHONPATH=src .venv/bin/python -m tai.train_tokenizer \
        --splits <atlas v1.1 corpus/splits> --out data/tokenizer \
        --vocab-size 16000 --jev-removals <post_jev_removals.json>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tokenizers import Tokenizer
from tokenizers.decoders import ByteLevel as ByteLevelDecoder
from tokenizers.models import BPE
from tokenizers.pre_tokenizers import ByteLevel
from tokenizers.trainers import BpeTrainer

# Kept identical to v0.1 (architecture control: same vocab structure).
SPECIAL = ["<pad>", "<s>", "</s>", "<unk>", "<zh>", "<ja>", "<ko>", "<ms>", "<en>"]
TRAIN_FILE = "training_ready.train.jsonl"


def load_jev_ids(path: str | None) -> set[str]:
    if not path:
        return set()
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    return {r["record_id"] for r in doc.get("removed", [])}


def count_eligible(train_path: Path, jev_ids: set[str]) -> int:
    n = 0
    with open(train_path, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("source_lang") != "zh":
                continue
            if rec.get("id") in jev_ids:
                continue
            n += 1
    return n


def chunk_line(text: str, cap: int):
    """Slice a training line into <=cap-char pieces, preserving ALL bytes.

    Why slicing (not whitespace-splitting): an earlier revision split on
    whitespace, which deleted every space from the BPE training text. The
    trainer then never observed the space byte, mapped it to <unk>, and the
    whole corpus encoded/decoded spaceless (BLEU 0.0 artifact). Char-slicing
    keeps spaces/newlines observable while still bounding BPE counting
    memory on paragraph-length web-novel text (the reason for chunking:
    spaceless CJK runs would otherwise make every paragraph one giant
    unique "word"). Recorded in tokenizer_config.
    """
    text = text.strip()
    while len(text) > cap:
        yield text[:cap]
        text = text[cap:]
    if text:
        yield text


def iter_stride_texts(train_path: Path, jev_ids: set[str], n_pairs: int, seed: int,
                      chunk_chars: int):
    """Yield training lines for a stride sample.

    Deterministic: eligible rows enumerated in file order, every k-th row
    taken with offset derived from seed (offset=seed % k, no RNG state).
    Each sampled line is chunked (see chunk_line) to bound BPE memory.
    """
    total = count_eligible(train_path, jev_ids)
    if n_pairs >= total:
        step, offset = 1, 0
    else:
        step = total // n_pairs
        offset = seed % step
    yielded = 0
    idx = 0
    with open(train_path, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("source_lang") != "zh":
                continue
            if rec.get("id") in jev_ids:
                continue
            if (idx - offset) % step == 0 and yielded < n_pairs:
                for piece in chunk_line(f"<zh> {rec['source']}", chunk_chars):
                    yield piece
                for piece in chunk_line(rec["target"], chunk_chars):
                    yield piece
                yielded += 1
            idx += 1
    print(f"tokenizer sample: {yielded}/{n_pairs} requested pairs from {total} eligible zh train rows (step={step})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--splits", required=True,
                    help="Atlas v1.1 corpus/splits dir (read-only)")
    ap.add_argument("--out", default="data/tokenizer")
    ap.add_argument("--vocab-size", type=int, default=16000)
    ap.add_argument("--n-pairs", type=int, default=25000,
                    help="Stride-sampled train pairs for BPE statistics. 25k pairs "
                         "(~100MB text at v1.1 chunk sizes) is ample for a 16k "
                         "vocab; larger samples blow up trainer counting memory "
                         "on paragraph-length web-novel text.")
    ap.add_argument("--max-lines", type=int, default=None,
                    help="Legacy alias: pairs = max-lines // 2 when --n-pairs unset.")
    ap.add_argument("--min-frequency", type=int, default=2)
    ap.add_argument("--jev-removals", default=None)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--chunk-chars", type=int, default=300,
                    help="Cap training-text piece length (memory bound, see chunk_line).")
    args = ap.parse_args()

    train_path = Path(args.splits) / TRAIN_FILE
    assert train_path.exists(), f"missing {train_path}"
    jev_ids = load_jev_ids(args.jev_removals)
    if args.n_pairs is None:
        args.n_pairs = (args.max_lines or 400_000) // 2
    n_pairs = args.n_pairs

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    tok = Tokenizer(BPE(unk_token="<unk>"))
    tok.pre_tokenizer = ByteLevel(add_prefix_space=False)
    tok.decoder = ByteLevelDecoder()
    trainer = BpeTrainer(vocab_size=args.vocab_size, min_frequency=args.min_frequency,
                         special_tokens=SPECIAL, show_progress=True)
    iterator = iter_stride_texts(train_path, jev_ids, n_pairs, args.seed,
                                   args.chunk_chars)
    # length hint ≈ pieces; each pair yields ~10-20 chunked pieces.
    tok.train_from_iterator(iterator, trainer=trainer, length=n_pairs * 16)
    tok.save(str(out / "tokenizer.json"))
    with open(out / "tokenizer_config.json", "w", encoding="utf-8") as f:
        json.dump({"backend": "huggingface-tokenizers BPE byte-level",
                   "vocab_size": tok.get_vocab_size(),
                   "special_tokens": SPECIAL,
                   "trained_on": "zh TRAIN split only (never val/test; JEV tombstones excluded)",
                   "sampling": "deterministic stride over file order",
                   "n_pairs": n_pairs,
                   "chunk_chars": args.chunk_chars,
                   "train_file": TRAIN_FILE,
                   "jev_excluded": len(jev_ids),
                   "max_lines": args.max_lines,
                   "min_frequency": args.min_frequency,
                   "seed": args.seed}, f, indent=2)
    print("vocab size:", tok.get_vocab_size())
    # FAIL-FAST roundtrip guard: spaces/CJK must survive encode→decode, and
    # the space byte must never map to <unk>. (Regression test for the
    # whitespace-stripping bug that once spaceless-encoded the whole corpus.)
    unk = tok.token_to_id("<unk>")
    probes = ["夜色的街道，雨点落在积水上。 The street was empty.",
              "Hello world test", "Shangguan Tianyou snorted coldly",
              "微微一思索，他旋即恍然 With a little thinking, he realized"]
    for p in probes:
        enc = tok.encode(p)
        assert unk not in enc.ids, f"space/byte mapped to <unk> in {p!r}: {enc.tokens}"
        rt = tok.decode(enc.ids)
        assert rt == p, f"roundtrip mismatch: {p!r} -> {rt!r}"
    # Special-tag probe: v0.1 drops the tag on decode ('<zh> X' -> ' X');
    # same behavior required here (model never decodes the source-side tag).
    tag_probe = "<zh> 夜色的街道"
    rt = tok.decode(tok.encode(tag_probe).ids)
    assert rt == " 夜色的街道", f"tag behavior changed: {tag_probe!r} -> {rt!r}"
    print("roundtrip guard: OK (spaces + CJK survive, no <unk>, tag-drop matches v0.1)")
    sample = "<zh> 夜色的街道，雨点落在积水上。 The street was empty."
    print("sample ids:", tok.encode(sample).ids[:20])


if __name__ == "__main__":
    main()
