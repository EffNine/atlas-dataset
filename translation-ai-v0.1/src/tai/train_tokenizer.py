"""Step 4 — Train a shared multilingual subword tokenizer (BPE).

CRITICAL: trains on TRAIN split only. Val/test are never seen here.
Source lines are prefixed with a language tag (<zh> etc.) so the model
can condition on the source language; tags are registered as special tokens.

Backend: HuggingFace `tokenizers` (BPE, byte-level alphabet for full CJK coverage).

Usage:
    PYTHONPATH=src .venv/bin/python -m tai.train_tokenizer \
        --splits data/splits --out data/tokenizer --vocab-size 16000
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

LANGS = ("zh", "ja", "ko", "ms")
SPECIAL = ["<pad>", "<s>", "</s>", "<unk>", "<zh>", "<ja>", "<ko>", "<ms>", "<en>"]


def iter_train_texts(splits: Path, max_lines: int):
    n = 0
    for lang in LANGS:
        with open(splits / f"train_{lang}-en.jsonl", encoding="utf-8") as f:
            for line in f:
                if n >= max_lines:
                    return
                rec = json.loads(line)
                yield f"<{lang}> {rec['source']}"
                n += 1
                if n >= max_lines:
                    return
                yield rec["target"]
                n += 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--splits", default="data/splits")
    ap.add_argument("--out", default="data/tokenizer")
    ap.add_argument("--vocab-size", type=int, default=16000)
    ap.add_argument("--max-lines", type=int, default=400_000)
    ap.add_argument("--min-frequency", type=int, default=2)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    tok = Tokenizer(BPE(unk_token="<unk>"))
    tok.pre_tokenizer = ByteLevel(add_prefix_space=False)
    tok.decoder = ByteLevelDecoder()
    trainer = BpeTrainer(vocab_size=args.vocab_size, min_frequency=args.min_frequency,
                         special_tokens=SPECIAL, show_progress=True)
    tok.train_from_iterator(iter_train_texts(Path(args.splits), args.max_lines),
                            trainer=trainer, length=args.max_lines)
    tok.save(str(out / "tokenizer.json"))
    with open(out / "tokenizer_config.json", "w", encoding="utf-8") as f:
        json.dump({"backend": "huggingface-tokenizers BPE byte-level",
                   "vocab_size": tok.get_vocab_size(),
                   "special_tokens": SPECIAL,
                   "trained_on": "train split only (never val/test)",
                   "max_lines": args.max_lines,
                   "min_frequency": args.min_frequency}, f, indent=2)
    print("vocab size:", tok.get_vocab_size())
    # sanity: every CJK char encodable (byte-level => no UNK for text)
    sample = "<zh> 夜色的街道，雨点落在积水上。 <ja> 夜の街角 <ko> 어두운 골목 <ms> Selamat pagi"
    print("sample ids:", tok.encode(sample).ids[:20])


if __name__ == "__main__":
    main()
