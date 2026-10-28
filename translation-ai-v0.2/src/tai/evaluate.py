"""Evaluate a v0.2 checkpoint on the FIXED held-out zh→en test set.

Same core methodology as translation-ai-v0.1's evaluate.py (teacher-forced
loss on ALL test rows, sacrebleu BLEU + chrF with greedy decode, echo
baseline, representative samples) so v0.1 → v0.2 numbers are comparable.
NEVER trains, tunes, or selects on test data. Early stopping used val only.

v0.2 additions (analysis only, no methodology change to primary metrics):
- decode set is a deterministic STRIDE sample (test file is source-grouped;
  a head-take would be hsc-only). Per-source stride slices for hsc/tomato.
- failure taxonomy per decoded row: repetition / untranslated-source (CJK
  leak) / empty / copy / truncation (hit max_new with longer reference).
- breakdowns: by source (provenance), by source-length bucket, dialogue-like
  rows, latin-in-source rows (entity/code-switch proxy, heuristic).
- terminology-coverage diagnostic from the CC-CEDICT-derived sidecar rows
  (terminology.jsonl, EVAL-ONLY — never training data; RESTRICTED share-alike,
  local analysis, no redistribution).

Usage:
    PYTHONPATH=src .venv/bin/python -m tai.evaluate \
        --checkpoint checkpoints/run-zh-v1/ckpt_best.pt \
        --tokenizer data/tokenizer/tokenizer.json \
        --encoded data/encoded --splits <atlas splits> \
        --terminology <atlas terminology.jsonl> --out reports/eval_run-zh-v1.json
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import sacrebleu
import torch
from tokenizers import Tokenizer
from tokenizers.decoders import ByteLevel
from torch.utils.data import DataLoader

from tai.model import NMTTransformer
from tai.train import EncodedDataset, collate, evaluate, evaluate_per_source
from tai.utils import hardware_info, read_jsonl

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")
QUOTE_RE = re.compile(r"[“”\"「『」 dialogue:]|^\s*[\"“「『-]")


def greedy_translate(model, tok: Tokenizer, texts: list[str], device,
                     max_len: int, batch_size: int = 64) -> tuple[list[str], list[bool]]:
    """Greedy decode; also reports per-row hit_max (no EOS before max_new)."""
    pad_id = tok.token_to_id("<pad>")
    eos_id = tok.token_to_id("</s>")
    model.eval()
    outs, hit_max = [], []
    with torch.no_grad():
        for i in range(0, len(texts), batch_size):
            chunk = texts[i:i + batch_size]
            ids = [tok.encode(t).ids[:max_len] for t in chunk]
            m = max(len(s) for s in ids)
            src = torch.tensor([s + [pad_id] * (m - len(s)) for s in ids],
                               dtype=torch.long, device=device)
            hyp = model.greedy(src, src == pad_id, max_new=max_len)
            for h in hyp.tolist():
                seq = []
                stopped = False
                for t in h[1:]:  # skip BOS
                    if t == eos_id:
                        stopped = True
                        break
                    seq.append(t)
                outs.append(tok.decode(seq))
                hit_max.append(not stopped)
    return outs, hit_max


def repetition_flag(text: str) -> bool:
    toks = text.split()
    if len(toks) < 12:
        return False
    # any trigram occurring >= 5 times, or same sentence 3x
    tris: dict[tuple, int] = {}
    for i in range(len(toks) - 2):
        k = (toks[i], toks[i + 1], toks[i + 2])
        tris[k] = tris.get(k, 0) + 1
        if tris[k] >= 5:
            return True
    sents = [s.strip() for s in re.split(r"[.!?。！？]+", text) if s.strip()]
    if len(sents) >= 3 and len(set(sents)) == 1:
        return True
    return False


def stride_sample(rows: list, n: int, seed: int = 7) -> list:
    if n >= len(rows):
        return rows
    step = len(rows) / n
    return [rows[int(i * step)] for i in range(n)]


def failure_row(src: str, ref: str, hyp: str, hit_max: bool) -> dict:
    return {
        "empty": not hyp.strip(),
        "copy": hyp.strip() == src.strip() and bool(src.strip()),
        "cjk_leak": bool(CJK_RE.search(hyp)),
        "repetition": repetition_flag(hyp),
        "truncated_decode": bool(hit_max),
        "ref_much_longer": len(ref) > max(200, 2 * len(hyp)),
    }


def summarize_failures(cases: list[dict]) -> dict:
    keys = ("empty", "copy", "cjk_leak", "repetition", "truncated_decode", "ref_much_longer")
    return {k: sum(1 for c in cases if c["flags"][k]) for k in keys}


def length_bucket(src_chars: int) -> str:
    if src_chars <= 100:
        return "short<=100"
    if src_chars <= 500:
        return "mid101-500"
    return "long>500"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--tokenizer", required=True)
    ap.add_argument("--encoded", required=True)
    ap.add_argument("--splits", required=True,
                    help="Atlas v1.1 corpus/splits dir (read-only, for decode text)")
    ap.add_argument("--terminology", default=None)
    ap.add_argument("--out", default="reports/eval_run-zh-v1.json")
    ap.add_argument("--decode-n", type=int, default=2000)
    ap.add_argument("--decode-n-per-source", type=int, default=2000)
    ap.add_argument("--n-samples", type=int, default=12)
    args = ap.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ck = torch.load(args.checkpoint, map_location=device, weights_only=False)
    tok = Tokenizer.from_file(args.tokenizer)
    if tok.decoder is None:
        tok.decoder = ByteLevel()
    pad_id = tok.token_to_id("<pad>")
    model = NMTTransformer(ck["model_cfg"]).to(device)
    model.load_state_dict(ck["model"])
    max_len = ck["model_cfg"]["max_len"]

    enc = Path(args.encoded)
    report: dict = {"checkpoint": args.checkpoint, "pair": "zh->en",
                    "hardware": hardware_info(),
                    "method": "teacher-forced loss on ALL rows; sacrebleu BLEU/chrF greedy on "
                              "deterministic stride samples (grouped file order)"}
    t0 = time.time()

    # ---- loss on full val + test (overall + per-source) ----
    for split, meta_name in (("training_ready.val", "training_ready.val_meta.jsonl"),
                             ("training_ready.test", "training_ready.test_meta.jsonl")):
        ds = EncodedDataset(enc / f"{split}.npz")
        meta = list(read_jsonl(enc / meta_name))
        loader = DataLoader(ds, batch_size=128, shuffle=False,
                            collate_fn=lambda b: collate(b, pad_id))
        ev = evaluate(model, loader, pad_id, device)
        per_src = evaluate_per_source(model, loader, pad_id, device, meta)
        name = "val" if "val" in split else "test"
        report[f"{name}_loss"] = round(ev["loss"], 4)
        report[f"{name}_rows"] = len(ds)
        report[f"{name}_loss_per_source"] = {k: round(v, 4) for k, v in per_src.items()}
        print(f"{name}: loss={ev['loss']:.4f} rows={len(ds)} per_source={per_src}", flush=True)

    # ---- decode text (raw test rows, zh only, file order preserved) ----
    test_rows = []
    with open(Path(args.splits) / "training_ready.test.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("source_lang") == "zh":
                test_rows.append(r)
    print(f"zh test rows for decode pool: {len(test_rows)}", flush=True)

    def decode_set(rows: list) -> dict:
        srcs = [f"<zh> {r['source']}" for r in rows]
        refs = [r["target"] for r in rows]
        hyps, hit_max = greedy_translate(model, tok, srcs, device, max_len)
        bleu = sacrebleu.corpus_bleu(hyps, [refs])
        chrf = sacrebleu.corpus_chrf(hyps, [refs])
        echo = [r["source"] for r in rows]
        bleu_b = sacrebleu.corpus_bleu(echo, [refs])
        chrf_b = sacrebleu.corpus_chrf(echo, [refs])
        cases = []
        for r, h, hm in zip(rows, hyps, hit_max):
            cases.append({"source": r["source"], "reference": r["target"],
                          "hypothesis": h, "source_id": r.get("source_id"),
                          "src_chars": len(r["source"]),
                          "flags": failure_row(r["source"], r["target"], h, hm)})
        return {"rows": len(rows), "bleu": round(bleu.score, 2),
                "chrf": round(chrf.score, 2),
                "baseline_echo_bleu": round(bleu_b.score, 2),
                "baseline_echo_chrf": round(chrf_b.score, 2),
                "failures": summarize_failures(cases), "cases": cases}

    # primary decode set: representative stride over all zh test
    primary_rows = stride_sample(test_rows, args.decode_n)
    primary = decode_set(primary_rows)
    primary_cases = primary.pop("cases")
    report["primary"] = primary
    print(f"primary zh: BLEU={primary['bleu']} chrF={primary['chrf']} "
          f"failures={primary['failures']}", flush=True)

    # per-source slices (provenance breakdown)
    report["per_source"] = {}
    src_groups: dict[str, list] = {}
    for r in test_rows:
        src_groups.setdefault(r.get("source_id", "?"), []).append(r)
    for sid, rows in sorted(src_groups.items()):
        sub = decode_set(stride_sample(rows, args.decode_n_per_source))
        cases = sub.pop("cases")
        sub["samples"] = [{"source": c["source"][:400], "reference": c["reference"][:400],
                           "hypothesis": c["hypothesis"][:400]} for c in cases[:args.n_samples]]
        report["per_source"][sid] = sub
        print(f"src {sid}: n_pool={len(rows)} BLEU={sub['bleu']} chrF={sub['chrf']} "
              f"failures={sub['failures']}", flush=True)

    # characteristic breakdowns on the primary decoded cases
    by_bucket: dict[str, list[str]] = {}
    by_bucket_ref: dict[str, list[str]] = {}
    dialogue_idx, latin_idx = [], []
    for j, c in enumerate(primary_cases):
        b = length_bucket(c["src_chars"])
        by_bucket.setdefault(b, []).append(c["hypothesis"])
        by_bucket_ref.setdefault(b, []).append(c["reference"])
        if QUOTE_RE.search(c["source"]):
            dialogue_idx.append(j)
        if LATIN_RE.search(c["source"]):
            latin_idx.append(j)
    report["by_length"] = {}
    for b in sorted(by_bucket):
        hyps, refs = by_bucket[b], by_bucket_ref[b]
        report["by_length"][b] = {
            "rows": len(hyps),
            "bleu": round(sacrebleu.corpus_bleu(hyps, [refs]).score, 2),
            "chrf": round(sacrebleu.corpus_chrf(hyps, [refs]).score, 2)}
    for label, idxs in (("dialogue_like", dialogue_idx), ("latin_in_source", latin_idx)):
        hyps = [primary_cases[j]["hypothesis"] for j in idxs]
        refs = [primary_cases[j]["reference"] for j in idxs]
        if hyps:
            report[f"subset_{label}"] = {
                "rows": len(hyps),
                "bleu": round(sacrebleu.corpus_bleu(hyps, [refs]).score, 2),
                "chrf": round(sacrebleu.corpus_chrf(hyps, [refs]).score, 2)}
        else:
            report[f"subset_{label}"] = {"rows": 0}
    print("by_length:", report["by_length"], flush=True)

    # samples: first N primary cases (file-order head would be hsc-only, so
    # take evenly across the stride sample) + worst failure examples
    report["samples"] = [{"source": c["source"][:600], "reference": c["reference"][:600],
                          "hypothesis": c["hypothesis"][:600], "source_id": c["source_id"],
                          "flags": c["flags"]}
                         for c in primary_cases[:args.n_samples]]
    for fkey in ("repetition", "cjk_leak", "copy", "empty"):
        ex = next((c for c in primary_cases if c["flags"][fkey]), None)
        if ex:
            report.setdefault("failure_examples", {})[fkey] = {
                "source": ex["source"][:600], "reference": ex["reference"][:600],
                "hypothesis": ex["hypothesis"][:600], "source_id": ex["source_id"]}

    # terminology-coverage diagnostic (EVAL ONLY)
    if args.terminology:
        terms: list[tuple[str, list[str]]] = []
        with open(args.terminology, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if r.get("source_lang") != "zh":
                    continue
                st = r.get("source_term", "")
                if len(st) < 2 or CJK_RE.search(r.get("target_term", "")):
                    continue
                glosses = [g.strip().lower() for g in
                           re.split(r"[;/,]", r.get("target_term", "")) if g.strip()]
                if st and glosses:
                    terms.append((st, glosses))
                if len(terms) >= 20000:
                    break
        hits = covered = 0
        for c in primary_cases:
            for st, glosses in terms:
                if st in c["source"]:
                    hits += 1
                    h = c["hypothesis"].lower()
                    if any(g in h for g in glosses[:4]):
                        covered += 1
                    break  # first matching term per row keeps it bounded
        report["terminology_diagnostic"] = {
            "note": "EVAL-ONLY heuristic on primary decoded rows; CC-CEDICT-derived "
                    "sidecar terms (RESTRICTED share-alike, local analysis only). "
                    "First-matching-term per row; gloss match is substring-based.",
            "term_list": len(terms), "rows_with_term": hits,
            "rows_with_gloss": covered,
            "coverage": round(covered / max(1, hits), 4)}
        print("terminology:", report["terminology_diagnostic"], flush=True)

    report["eval_time_s"] = round(time.time() - t0, 1)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("wrote", out)


if __name__ == "__main__":
    main()
