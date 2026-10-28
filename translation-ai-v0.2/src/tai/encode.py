"""Step T3 — Deterministically pre-tokenize the zh-only corpus slices.

Reads the Atlas v1.1 split files (read-only), filters to zh ALLOW rows,
excludes JEV tombstoned ids, and applies EXACTLY the v0.1 PairDataset
truncation logic once:

    src    = encode("<zh> " + source)[:max_len]
    tgt    = encode(target)[:max_len-2]
    tgt_in  = [BOS] + tgt
    tgt_out = tgt + [EOS]

Writes per split: <split>.npz (uint16 src/tgt_in/tgt_out) + <split>_meta.jsonl
(id, source_id, chapter_id?, src/tgt char lengths) for val/test breakdowns.
Train meta is counts-only (see encode_manifest.json) to avoid a ~400MB file.

Why pre-tokenize: 2M rows re-encoded every epoch in worker processes is
slow and RAM-heavy; this step is deterministic, provenance-preserving, and
reproducible from (tokenizer sha + Atlas split shas + JEV list).

Writes ONLY under --out (inside translation-ai-v0.2/). Never touches Atlas.

Usage:
    PYTHONPATH=src .venv/bin/python -m tai.encode \
        --splits <atlas splits> --tokenizer data/tokenizer/tokenizer.json \
        --jev-removals <post_jev_removals.json> --out data/encoded --max-len 128
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from tokenizers import Tokenizer

SPLITS = ("training_ready.train", "training_ready.val", "training_ready.test")
CHUNK = 50_000
BATCH = 2048  # encode_batch width: Rust-parallel BPE, ~10-50x per-row encode


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--splits", required=True)
    ap.add_argument("--tokenizer", required=True)
    ap.add_argument("--jev-removals", default=None)
    ap.add_argument("--out", default="data/encoded")
    ap.add_argument("--max-len", type=int, default=128)
    args = ap.parse_args()

    splits = Path(args.splits)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    jev_ids: set[str] = set()
    if args.jev_removals:
        with open(args.jev_removals, encoding="utf-8") as f:
            jev_ids = {r["record_id"] for r in json.load(f).get("removed", [])}

    tok = Tokenizer.from_file(args.tokenizer)
    pad_id = tok.token_to_id("<pad>")
    bos_id = tok.token_to_id("<s>")
    eos_id = tok.token_to_id("</s>")
    unk_id = tok.token_to_id("<unk>")
    tok_sha = sha256_file(Path(args.tokenizer))
    max_len = args.max_len

    manifest = {"tokenizer_sha256": tok_sha, "max_len": max_len,
                "jev_excluded": len(jev_ids), "splits": {}}

    for split in SPLITS:
        src_chunks: list[np.ndarray] = []
        ti_chunks: list[np.ndarray] = []
        to_chunks: list[np.ndarray] = []
        acc_src, acc_ti, acc_to = [], [], []
        meta_f = None
        if split != "training_ready.train":
            meta_f = open(out / f"{split}_meta.jsonl", "w", encoding="utf-8")
        n_in, n_kept, n_jev, n_nonzh = 0, 0, 0, 0
        by_src: dict[str, int] = {}
        batch: list[tuple[str, str, dict]] = []

        def flush():
            if acc_src:
                src_chunks.append(np.array(acc_src, dtype=np.uint16))
                ti_chunks.append(np.array(acc_ti, dtype=np.uint16))
                to_chunks.append(np.array(acc_to, dtype=np.uint16))
                acc_src.clear(); acc_ti.clear(); acc_to.clear()

        def encode_batch_rows(rows: list[tuple[str, str, dict]]):
            # v0.1 PairDataset logic, verbatim, applied batch-wise:
            #   src = encode(tagged source)[:max_len]
            #   tgt = encode(target)[:max_len-2]; BOS/tgt and tgt/EOS + pad
            src_ids = tok.encode_batch([s for s, _, _ in rows])
            tgt_ids = tok.encode_batch([t for _, t, _ in rows])
            for (raw_src, raw_tgt, info), se, te in zip(rows, src_ids, tgt_ids):
                s = se.ids[:max_len]
                t = te.ids[:max_len - 2]
                acc_src.append(s + [pad_id] * (max_len - len(s)))
                acc_ti.append([bos_id] + t + [pad_id] * (max_len - 1 - len(t)))
                acc_to.append(t + [eos_id] + [pad_id] * (max_len - 1 - len(t)))
                by_src[info["source_id"]] = by_src.get(info["source_id"], 0) + 1
                if meta_f is not None:
                    meta_f.write(json.dumps(info, ensure_ascii=False) + "\n")

        with open(splits / f"{split}.jsonl", encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                n_in += 1
                if rec.get("source_lang") != "zh":
                    n_nonzh += 1
                    continue
                if rec.get("id") in jev_ids:
                    n_jev += 1
                    continue
                n_kept += 1
                batch.append((
                    f"<zh> {rec['source']}", rec["target"],
                    {"id": rec.get("id"), "source_id": rec.get("source_id"),
                     "chapter_id": rec.get("chapter_id"),
                     "target_origin": rec.get("target_origin"),
                     "src_chars": len(rec.get("source", "")),
                     "tgt_chars": len(rec.get("target", ""))},
                ))
                if len(batch) >= BATCH:
                    encode_batch_rows(batch)
                    batch.clear()
                    if n_kept % CHUNK == 0:
                        flush()
                        print(f"{split}: {n_kept} rows encoded", flush=True)
        if batch:
            encode_batch_rows(batch)
            batch.clear()
        flush()
        if meta_f is not None:
            meta_f.close()
        src = np.concatenate(src_chunks) if src_chunks else np.zeros((0, max_len), np.uint16)
        ti = np.concatenate(ti_chunks) if ti_chunks else np.zeros((0, max_len), np.uint16)
        to = np.concatenate(to_chunks) if to_chunks else np.zeros((0, max_len), np.uint16)
        np.savez_compressed(out / f"{split}.npz", src=src, tgt_in=ti, tgt_out=to)
        # <unk> canary: spaces must never encode as <unk> (tokenizer bug canary).
        n_unk = int(((src == unk_id).sum() + (ti == unk_id).sum() + (to == unk_id).sum()))
        n_real = int(((src != pad_id).sum() + (ti != pad_id).sum() + (to != pad_id).sum()))
        unk_rate = n_unk / max(1, n_real)
        assert unk_rate < 0.01, f"{split}: <unk> rate {unk_rate:.4f} — tokenizer corrupt?"
        entry = {"n_in": n_in, "n_kept_zh": n_kept, "n_nonzh_skipped": n_nonzh,
                 "n_jev_excluded": n_jev, "by_source": by_src,
                 "unk_rate": round(unk_rate, 6),
                 "npz_sha256": sha256_file(out / f"{split}.npz")}
        manifest["splits"][split] = entry
        print(f"{split}: in={n_in} kept_zh={n_kept} nonzh={n_nonzh} jev={n_jev} src={by_src}", flush=True)

    with open(out / "encode_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print("wrote", out / "encode_manifest.json")


if __name__ == "__main__":
    main()
