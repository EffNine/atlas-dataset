"""Evaluate a checkpoint: teacher-forced loss + BLEU/chrF + samples + baseline.

- Loss (val + test, overall and per-language) via teacher forcing.
- BLEU + chrF via sacrebleu, separately per source language, greedy decode.
- Echo baseline (predict source text as target) for honest comparison.
- Representative translations saved to JSONL (first N test rows per language).
- NEVER trains, tunes, or selects on test data.

Usage:
    PYTHONPATH=src .venv/bin/python -m tai.evaluate \
        --checkpoint checkpoints/run/ckpt_best.pt \
        --tokenizer data/tokenizer/tokenizer.json \
        --splits data/splits --out reports/eval_run.json
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import sacrebleu
import torch
from tokenizers import Tokenizer
from tokenizers.decoders import ByteLevel

from tai.model import NMTTransformer
from tai.train import PairDataset, collate, evaluate
from tai.utils import hardware_info, read_jsonl
from torch.utils.data import DataLoader

LANGS = ("zh", "ja", "ko", "ms")


def greedy_translate(model, tok: Tokenizer, texts: list[str], device,
                     max_len: int, batch_size: int = 64) -> list[str]:
    pad_id = tok.token_to_id("<pad>")
    model.eval()
    outs = []
    with torch.no_grad():
        for i in range(0, len(texts), batch_size):
            chunk = texts[i:i + batch_size]
            ids = [tok.encode(t).ids[:max_len] for t in chunk]
            m = max(len(s) for s in ids)
            src = torch.tensor([s + [pad_id] * (m - len(s)) for s in ids],
                               dtype=torch.long, device=device)
            hyp = model.greedy(src, src == pad_id)
            for h in hyp.tolist():
                seq = []
                for t in h[1:]:  # skip BOS
                    if t == tok.token_to_id("</s>"):
                        break
                    seq.append(t)
                outs.append(tok.decode(seq))
    return outs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--tokenizer", required=True)
    ap.add_argument("--splits", default="data/splits")
    ap.add_argument("--out", default="reports/eval.json")
    ap.add_argument("--max-test", type=int, default=2000,
                    help="Cap test rows per language for decode (loss uses all).")
    ap.add_argument("--n-samples", type=int, default=8)
    args = ap.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ck = torch.load(args.checkpoint, map_location=device, weights_only=False)
    tok = Tokenizer.from_file(args.tokenizer)
    if tok.decoder is None:
        # tokenizers saved before the decoder was registered: byte-level
        # pre-tokenizer requires the matching byte-level decoder, else
        # decode() emits raw Ġ/Ċ markers and BLEU/chrF are underestimated.
        tok.decoder = ByteLevel()
    pad_id = tok.token_to_id("<pad>")
    model = NMTTransformer(ck["model_cfg"]).to(device)
    model.load_state_dict(ck["model"])
    max_len = ck["model_cfg"]["max_len"]

    report: dict = {"checkpoint": args.checkpoint,
                    "hardware": hardware_info(), "per_lang": {}}
    t0 = time.time()
    for lang in LANGS:
        sp = Path(args.splits)
        val_rows = list(read_jsonl(sp / f"val_{lang}-en.jsonl"))
        test_rows = list(read_jsonl(sp / f"test_{lang}-en.jsonl"))
        for name, rows in (("val", val_rows), ("test", test_rows)):
            ds = PairDataset.__new__(PairDataset)
            ds.rows, ds.tok, ds.max_len = rows, tok, max_len
            ds.bos, ds.eos = tok.token_to_id("<s>"), tok.token_to_id("</s>")
            loader = DataLoader(ds, batch_size=128, shuffle=False,
                                collate_fn=lambda b: collate(b, pad_id))
            ev = evaluate(model, loader, pad_id, 0.0, device)
            report["per_lang"].setdefault(lang, {})[f"{name}_loss"] = round(ev["loss"], 4)
            report["per_lang"][lang][f"{name}_rows"] = len(rows)

        dec_rows = test_rows[: args.max_test]
        srcs = [f"<{lang}> {r['source']}" for r in dec_rows]
        refs = [r["target"] for r in dec_rows]
        hyps = greedy_translate(model, tok, srcs, device, max_len)
        bleu = sacrebleu.corpus_bleu(hyps, [refs])
        chrf = sacrebleu.corpus_chrf(hyps, [refs])
        # echo baseline: source text (without tag) as the "translation"
        echo = [r["source"] for r in dec_rows]
        bleu_b = sacrebleu.corpus_bleu(echo, [refs])
        chrf_b = sacrebleu.corpus_chrf(echo, [refs])
        report["per_lang"][lang].update({
            "test_decode_rows": len(dec_rows),
            "bleu": round(bleu.score, 2), "chrf": round(chrf.score, 2),
            "baseline_echo_bleu": round(bleu_b.score, 2),
            "baseline_echo_chrf": round(chrf_b.score, 2),
            "samples": [{"source": r["source"], "reference": r["target"], "hypothesis": h}
                        for r, h in zip(dec_rows[: args.n_samples], hyps[: args.n_samples])],
        })
        print(f"{lang}: " + json.dumps(report["per_lang"][lang], ensure_ascii=False)[:400],
              flush=True)

    report["eval_time_s"] = round(time.time() - t0, 1)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("wrote", out)


if __name__ == "__main__":
    main()
