"""Train the from-scratch encoder-decoder Transformer.

Features: deterministic seed, mixed precision (AMP), gradient clipping,
label smoothing, warmup+cosine schedule, checkpointing + resume
(model/optimizer/scheduler/scaler/RNG states), early stopping on val loss,
JSONL train log, run manifest with hyperparams + hardware info.

Usage:
    PYTHONPATH=src .venv/bin/python -m tai.train --config configs/base.yaml
    # resume:
    PYTHONPATH=src .venv/bin/python -m tai.train --config configs/base.yaml --resume checkpoints/run/ckpt_best.pt
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import time
from pathlib import Path

import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset
from tokenizers import Tokenizer

from tai.model import NMTTransformer
from tai.utils import hardware_info, read_jsonl, set_seed

LANGS = ("zh", "ja", "ko", "ms")


class PairDataset(Dataset):
    def __init__(self, paths, tok: Tokenizer, max_len: int, bos: int, eos: int):
        self.rows = []
        for p in paths:
            self.rows.extend(list(read_jsonl(p)))
        self.tok, self.max_len, self.bos, self.eos = tok, max_len, bos, eos

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        src = self.tok.encode(f"<{r['source_lang']}> {r['source']}").ids[: self.max_len]
        tgt = self.tok.encode(r["target"]).ids[: self.max_len - 2]
        return {"src": src, "tgt_in": [self.bos] + tgt,
                "tgt_out": tgt + [self.eos], "lang": r["source_lang"]}


def collate(batch, pad_id: int):
    def pad(seqs):
        m = max(len(s) for s in seqs)
        return torch.tensor([s + [pad_id] * (m - len(s)) for s in seqs], dtype=torch.long)

    src, ti, to = pad([b["src"] for b in batch]), pad([b["tgt_in"] for b in batch]), \
        pad([b["tgt_out"] for b in batch])
    return {"src": src, "tgt_in": ti, "tgt_out": to,
            "langs": [b["lang"] for b in batch]}


def loss_fn(logits, tgt_out, pad_id: int, smoothing: float):
    return F.cross_entropy(logits.reshape(-1, logits.size(-1)),
                           tgt_out.reshape(-1), ignore_index=pad_id,
                           label_smoothing=smoothing)


@torch.no_grad()
def evaluate(model, loader, pad_id, smoothing, device):
    model.eval()
    tot_loss, tot_tok, per_lang = 0.0, 0, {}
    for b in loader:
        src, ti, to = b["src"].to(device), b["tgt_in"].to(device), b["tgt_out"].to(device)
        skm = src == pad_id
        logits = model(src, ti, skm, ti == pad_id)
        l = F.cross_entropy(logits.reshape(-1, logits.size(-1)), to.reshape(-1),
                            ignore_index=pad_id, reduction="sum")
        ntok = (to != pad_id).sum().item()
        tot_loss += l.item()
        tot_tok += ntok
        for lang in set(b["langs"]):
            d = per_lang.setdefault(lang, [0.0, 0])
            # approximate: attribute batch-average loss share by token share
            d[0] += l.item() * (sum(1 for x in b["langs"] if x == lang) / len(b["langs"]))
            d[1] += ntok * (sum(1 for x in b["langs"] if x == lang) / len(b["langs"]))
    out = {"loss": tot_loss / max(1, tot_tok)}
    for lang, (l, t) in per_lang.items():
        out[f"loss_{lang}"] = l / max(1, t)
    return out


def load_config(path: str) -> dict:
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--resume", default=None)
    ap.add_argument("--override", nargs="*", default=[],
                    help="key=value overrides, e.g. max_epochs=2 train_scale=0.01")
    args = ap.parse_args()

    try:
        import yaml  # noqa
    except ImportError:
        raise SystemExit("pyyaml required: .venv/bin/python -m pip install pyyaml")

    cfg = load_config(args.config)
    for ov in args.override:
        k, v = ov.split("=", 1)
        try:
            v = json.loads(v)
        except json.JSONDecodeError:
            pass
        cfg[k] = v

    set_seed(cfg.get("seed", 7))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    run_dir = Path(cfg.get("run_dir", "checkpoints/run"))
    run_dir.mkdir(parents=True, exist_ok=True)

    tok = Tokenizer.from_file(cfg["tokenizer"])
    pad_id = tok.token_to_id("<pad>")
    bos_id = tok.token_to_id("<s>")
    eos_id = tok.token_to_id("</s>")

    model_cfg = {k: cfg[k] for k in
                 ("vocab_size", "d_model", "n_heads", "d_ff", "n_enc_layers",
                  "n_dec_layers", "dropout", "max_len")}
    model_cfg.update({"pad_id": pad_id, "bos_id": bos_id, "eos_id": eos_id})
    assert model_cfg["vocab_size"] == tok.get_vocab_size(), \
        f"config vocab {model_cfg['vocab_size']} != tokenizer {tok.get_vocab_size()}"

    # data (optional subsample for smoke runs)
    def pick(split):
        paths = [Path(cfg["splits"]) / f"{split}_{l}-en.jsonl" for l in LANGS]
        rows = []
        for p in paths:
            rows.extend(list(read_jsonl(p)))
        return rows

    import random as pyrandom
    rng = pyrandom.Random(cfg.get("seed", 7))
    train_rows = pick("train")
    if cfg.get("train_scale", 1.0) < 1.0:
        # stratified subsample per language
        by_lang: dict = {}
        for r in train_rows:
            by_lang.setdefault(r["source_lang"], []).append(r)
        train_rows = []
        for l, rs in by_lang.items():
            rng.shuffle(rs)
            train_rows.extend(rs[: max(10, int(len(rs) * cfg["train_scale"]))])
        rng.shuffle(train_rows)
    val_rows = pick("val")

    def rows_to_ds(rows):
        d = PairDataset.__new__(PairDataset)
        d.rows, d.tok, d.max_len, d.bos, d.eos = rows, tok, cfg["max_len"], bos_id, eos_id
        return d

    train_ds, val_ds = rows_to_ds(train_rows), rows_to_ds(val_rows)
    nw = cfg.get("num_workers", 2)
    train_loader = DataLoader(train_ds, batch_size=cfg["batch_size"], shuffle=True,
                              num_workers=nw, collate_fn=lambda b: collate(b, pad_id))
    val_loader = DataLoader(val_ds, batch_size=cfg["batch_size"], shuffle=False,
                            num_workers=nw, collate_fn=lambda b: collate(b, pad_id))

    model = NMTTransformer(model_cfg).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=cfg["lr"],
                            weight_decay=cfg.get("weight_decay", 0.01),
                            betas=(0.9, 0.98), eps=1e-9)
    use_amp = bool(cfg.get("amp", True)) and device.type == "cuda"
    scaler = torch.cuda.amp.GradScaler(enabled=use_amp)

    steps_per_epoch = max(1, math.ceil(len(train_ds) / cfg["batch_size"]) //
                        max(1, int(cfg.get("accum_steps", 1))))
    total_steps = steps_per_epoch * cfg["max_epochs"]
    warmup = cfg.get("warmup_steps", min(4000, total_steps // 10))

    def lr_at(step):
        if step < warmup:
            return cfg["lr"] * (step + 1) / max(1, warmup)
        p = (step - warmup) / max(1, total_steps - warmup)
        return cfg["lr"] * 0.5 * (1 + math.cos(math.pi * min(1.0, p)))

    start_epoch, gstep, best_val = 0, 0, float("inf")
    bad_epochs = 0
    if args.resume:
        ck = torch.load(args.resume, map_location=device, weights_only=False)
        model.load_state_dict(ck["model"])
        opt.load_state_dict(ck["optimizer"])
        scaler.load_state_dict(ck["scaler"])
        start_epoch, gstep, best_val = ck["epoch"] + 1, ck["global_step"], ck["best_val"]
        torch.set_rng_state(ck["rng_cpu"].cpu().byte())
        if device.type == "cuda":
            torch.cuda.set_rng_state_all([s.cpu() for s in ck["rng_cuda"]])
        print(f"resumed from {args.resume}: epoch={start_epoch} step={gstep}")

    logf = open(run_dir / "train_log.jsonl", "a" if args.resume else "w", encoding="utf-8")
    t0 = time.time()
    stop = False
    epoch = start_epoch - 1
    accum = max(1, int(cfg.get("accum_steps", 1)))
    opt.zero_grad(set_to_none=True)
    for epoch in range(start_epoch, cfg["max_epochs"]):
        model.train()
        for bi, b in enumerate(train_loader):
            src, ti, to = b["src"].to(device), b["tgt_in"].to(device), b["tgt_out"].to(device)
            for pg in opt.param_groups:
                pg["lr"] = lr_at(gstep)
            with torch.cuda.amp.autocast(enabled=use_amp):
                logits = model(src, ti, src == pad_id, ti == pad_id)
                loss = loss_fn(logits, to, pad_id, cfg.get("label_smoothing", 0.1)) / accum
            scaler.scale(loss).backward()
            if (bi + 1) % accum == 0:
                scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.get("clip", 1.0))
                scaler.step(opt)
                scaler.update()
                opt.zero_grad(set_to_none=True)
                gstep += 1
            if gstep % cfg.get("log_every", 50) == 0 and (bi + 1) % accum == 0:
                rec = {"epoch": epoch, "step": gstep, "train_loss": round(loss.item() * accum, 4),
                       "lr": round(opt.param_groups[0]["lr"], 8),
                       "elapsed_s": round(time.time() - t0, 1)}
                logf.write(json.dumps(rec) + "\n")
                logf.flush()
                print(rec, flush=True)
        val = evaluate(model, val_loader, pad_id, 0.0, device)
        rec = {"epoch": epoch, "step": gstep, "val": {k: round(v, 4) for k, v in val.items()},
               "elapsed_s": round(time.time() - t0, 1)}
        logf.write(json.dumps(rec) + "\n")
        logf.flush()
        print(rec, flush=True)

        ckpt = {"model": model.state_dict(), "optimizer": opt.state_dict(),
                "scaler": scaler.state_dict(), "epoch": epoch, "global_step": gstep,
                "best_val": best_val, "model_cfg": model_cfg,
                "rng_cpu": torch.get_rng_state(),
                "rng_cuda": torch.cuda.get_rng_state_all() if device.type == "cuda" else None}
        torch.save(ckpt, run_dir / "ckpt_last.pt")
        if val["loss"] < best_val - cfg.get("min_delta", 1e-4):
            best_val, bad_epochs = val["loss"], 0
            ckpt["best_val"] = best_val
            torch.save(ckpt, run_dir / "ckpt_best.pt")
            print(f"new best val {best_val:.4f}", flush=True)
        else:
            bad_epochs += 1
            if bad_epochs >= cfg.get("patience", 3):
                print(f"early stop at epoch {epoch}", flush=True)
                stop = True
                break
    logf.close()

    manifest = {"config": cfg, "model_cfg": model_cfg, "n_params": model.n_params(),
                "train_rows": len(train_ds), "val_rows": len(val_ds),
                "best_val_loss": best_val, "epochs_run": epoch + 1,
                "global_steps": gstep, "train_time_s": round(time.time() - t0, 1),
                "hardware": hardware_info(), "device": str(device), "amp": use_amp}
    with open(run_dir / "run_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print("n_params:", model.n_params(), "best_val:", round(best_val, 4))


if __name__ == "__main__":
    main()
