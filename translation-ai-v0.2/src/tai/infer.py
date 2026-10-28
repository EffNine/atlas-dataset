"""Inference: load checkpoint + tokenizer, translate stdin or a file.

Usage:
    echo "夜色的街道" | PYTHONPATH=src .venv/bin/python -m tai.infer \
        --checkpoint checkpoints/run/ckpt_best.pt \
        --tokenizer data/tokenizer/tokenizer.json --lang zh
"""
from __future__ import annotations

import argparse
import sys

import torch
from tokenizers import Tokenizer
from tokenizers.decoders import ByteLevel

from tai.evaluate import greedy_translate
from tai.model import NMTTransformer


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--tokenizer", required=True)
    ap.add_argument("--lang", required=True, choices=["zh", "ja", "ko", "ms"])
    ap.add_argument("--input", default=None)
    ap.add_argument("--max-len", type=int, default=None)
    args = ap.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ck = torch.load(args.checkpoint, map_location=device, weights_only=False)
    tok = Tokenizer.from_file(args.tokenizer)
    if tok.decoder is None:
        tok.decoder = ByteLevel()
    model = NMTTransformer(ck["model_cfg"]).to(device)
    model.load_state_dict(ck["model"])
    max_len = args.max_len or ck["model_cfg"]["max_len"]

    if args.input:
        with open(args.input, encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
    else:
        lines = [l.strip() for l in sys.stdin if l.strip()]
    texts = [f"<{args.lang}> {l}" for l in lines]
    hyps, _ = greedy_translate(model, tok, texts, device, max_len)
    for hyp in hyps:
        print(hyp)


if __name__ == "__main__":
    main()
