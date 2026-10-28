"""Train the from-scratch encoder-decoder Transformer (zh→en, v0.2).

Same architecture, optimizer, schedule, AMP, checkpointing, resume, and
early-stopping semantics as translation-ai-v0.1's train.py (controlled
data-scaling experiment — only the DATA changes, not the training recipe).

Differences from v0.1 (all data-plumbing, no recipe change):
- zh-only; data comes from pre-tokenized npz slices (see tai.encode)
  instead of per-language raw JSONL.
- train_scale subsampling is a deterministic STRIDE over the encoded train
  array (file order is source-grouped, so head-takes would skew hsc/tomato).
- val reporting adds exact per-source loss via val meta (order-preserved).

Usage:
    PYTHONPATH=src .venv/bin/python -m tai.train --config configs/base.yaml
    # resume:
    PYTHONPATH=src .venv/bin/python -m tai.train --config configs/base.yaml \
        --resume checkpoints/run-zh-v1/ckpt_last.pt
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset
from tokenizers import Tokenizer

from tai.model import NMTTransformer
from tai.utils import hardware_info, read_jsonl, set_seed


class EncodedDataset(Dataset):
    """Wraps uint16 npz arrays; casts to long on the fly (cheap)."""

    def __init__(self, npz_path: str | Path, idx: np.ndarray | None = None):
        z = np.load(npz_path)
        self.src = z["src"]
        self.tgt_in = z["tgt_in"]
        self.tgt_out = z["tgt_out"]
        self.idx = idx if idx is not None else np.arange(len(self.src))

    def __len__(self):
        return len(self.idx)

    def __getitem__(self, i):
        j = int(self.idx[i])
        return {"src": torch.from_numpy(self.src[j].astype(np.int64)),
                "tgt_in": torch.from_numpy(self.tgt_in[j].astype(np.int64)),
                "tgt_out": torch.from_numpy(self.tgt_out[j].astype(np.int64))}


def collate(batch, pad_id: int):
    src = torch.stack([b["src"] for b in batch])
    ti = torch.stack([b["tgt_in"] for b in batch])
    to = torch.stack([b["tgt_out"] for b in batch])
    return {"src": src, "tgt_in": ti, "tgt_out": to}


def loss_fn(logits, tgt_out, pad_id: int, smoothing: float):
    return F.cross_entropy(logits.reshape(-1, logits.size(-1)),
                           tgt_out.reshape(-1), ignore_index=pad_id,
                           label_smoothing=smoothing)


@torch.no_grad()
def evaluate(model, loader, pad_id, device):
    """Teacher-forced token-mean loss (label smoothing off), overall only."""
    model.eval()
    tot_loss, tot_tok = 0.0, 0
    for b in loader:
        src, ti, to = b["src"].to(device), b["tgt_in"].to(device), b["tgt_out"].to(device)
        logits = model(src, ti, src == pad_id, ti == pad_id)
        l = F.cross_entropy(logits.reshape(-1, logits.size(-1)), to.reshape(-1),
                            ignore_index=pad_id, reduction="sum")
        tot_loss += l.item()
        tot_tok += (to != pad_id).sum().item()
    return {"loss": tot_loss / max(1, tot_tok), "tokens": tot_tok}


@torch.no_grad()
def evaluate_per_source(model, loader, pad_id, device, val_meta: list[dict]):
    """Exact per-source token-mean loss (val loader must be unshuffled)."""
    model.eval()
    agg: dict[str, list[float]] = {}
    i = 0
    for b in loader:
        src, ti, to = b["src"].to(device), b["tgt_in"].to(device), b["tgt_out"].to(device)
        logits = model(src, ti, src == pad_id, ti == pad_id)
        # per-row token-sum loss
        per_row = F.cross_entropy(
            logits.reshape(-1, logits.size(-1)), to.reshape(-1),
            ignore_index=pad_id, reduction="none").view(to.shape[0], -1).sum(-1)
        ntok = (to != pad_id).sum(-1)
        for r in range(to.shape[0]):
            sid = val_meta[i + r].get("source_id", "?")
            d = agg.setdefault(sid, [0.0, 0])
            d[0] += per_row[r].item()
            d[1] += ntok[r].item()
        i += to.shape[0]
    return {k: v[0] / max(1, v[1]) for k, v in agg.items()}


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
    run_dir = Path(cfg.get("run_dir", "checkpoints/run-zh-v1"))
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

    enc = Path(cfg["encoded"])
    n_train = int(np.load(enc / "training_ready.train.npz")["src"].shape[0])
    if cfg.get("train_scale", 1.0) < 1.0:
        # deterministic stride subsample (representative over grouped order)
        target = max(10, int(n_train * cfg["train_scale"]))
        step = max(1, n_train // target)
        offset = cfg.get("seed", 7) % step
        idx = np.arange(n_train)[offset::step][:target]
    else:
        idx = None
    train_ds = EncodedDataset(enc / "training_ready.train.npz", idx)
    val_ds = EncodedDataset(enc / "training_ready.val.npz")
    val_meta = list(read_jsonl(enc / "training_ready.val_meta.jsonl"))
    assert len(val_meta) == len(val_ds), "val meta/rows mismatch"

    nw = cfg.get("num_workers", 2)
    train_loader = DataLoader(train_ds, batch_size=cfg["batch_size"], shuffle=True,
                              num_workers=nw, collate_fn=lambda b: collate(b, pad_id),
                              drop_last=True)
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
        val = evaluate(model, val_loader, pad_id, device)
        per_src = evaluate_per_source(model, val_loader, pad_id, device, val_meta)
        rec = {"epoch": epoch, "step": gstep,
               "val": {"loss": round(val["loss"], 4),
                       **{f"loss_{k}": round(v, 4) for k, v in per_src.items()}},
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
