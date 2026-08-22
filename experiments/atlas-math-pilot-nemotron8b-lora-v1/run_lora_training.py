#!/usr/bin/env python3
"""
run_lora_training.py — Atlas Nemotron-Orchestrator-8B QLoRA Math Pilot.

Trains a QLoRA adapter on the approved math_300m_v0.1 training view using
nvidia/Nemotron-Orchestrator-8B (NF4 4-bit + double quant + bf16 compute,
LoRA r=8, alpha=16, dropout=0.05 on 7 validated modules).

Configuration follows the validated Phase 5B.1 pilot configuration.

Constraints honored:
  - Does NOT modify the dataset, training views, or release artifacts.
  - Outputs remain under experiments/atlas-math-pilot-nemotron8b-lora-v1/.

Determinism:
  - Fixed seed 42. Examples are presented in deterministic order (stable sort
    by record_id); batch size = 1, so no sampling randomness.

Outputs:
  - config.json, training_log.json, training_log/step_metrics.csv
  - checkpoints/ (LoRA adapter)
  - reproducibility_checklist.json

Run:
  .venv/bin/python experiments/atlas-math-pilot-nemotron8b-lora-v1/run_lora_training.py
"""
from __future__ import annotations

import csv
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

BASE_MODEL = "nvidia/Nemotron-Orchestrator-8B"
REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from credential_helper import get_hf_token
EXPERIMENT = REPO / "experiments" / "atlas-math-pilot-nemotron8b-lora-v1"
OUTPUT_DIR = EXPERIMENT / "checkpoints"
LOGS = EXPERIMENT / "training_log"
TRAIN_JSONL = REPO / "output" / "training_views" / "math_300m_v0.1" / "train.jsonl"
APPROVED_TRAIN_SHA = "6aecc2a754c1a4aec941a9dbb59136445cf04175a0ae02c158e86acd4e4a4572"

SEED = 42
MAX_SEQ_LEN = 1024
BATCH_SIZE = 1
GRAD_ACCUM = 8
MAX_STEPS = 60
LR = 2e-4
WEIGHT_DECAY = 0.01
WARMUP_RATIO = 0.03
LR_SCHEDULE = "cosine"
OPTIMIZER = "paged_adamw_8bit"
MAX_GRAD_NORM = 1.0
LOGGING_STEPS = 10
LORA_R = 8
LORA_ALPHA = 16
LORA_DROPOUT = 0.05
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj",
                  "gate_proj", "up_proj", "down_proj"]

EXPERIMENT_ID = "atlas-math-pilot-nemotron8b-lora-v1"
PHASE = "6.2"


def sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:
        return None


def git_rev():
    return sh(["git", "-C", str(REPO), "rev-parse", "HEAD"])


def git_short():
    return sh(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"])


def checksum(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def model_revision(model_id: str) -> str:
    hub = Path.home() / ".cache" / "huggingface" / "hub" / \
        ("models--" + model_id.replace("/", "--"))
    ref = hub / "refs" / "main"
    if ref.exists():
        return ref.read_text().strip()
    snaps = list(hub.glob("snapshots/*"))
    return snaps[0].name if snaps else None


def set_seed(seed: int):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def get_model_and_tokenizer():
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    cache_dir = str(Path.home() / ".cache" / "huggingface" / "hub")
    hf_token = os.environ.get("HF_TOKEN", "")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, use_fast=True, token=hf_token if hf_token else None,
                                               cache_dir=cache_dir)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        quantization_config=bnb_config,
        device_map="cpu",
        trust_remote_code=False,
        token=hf_token if hf_token else None,
        cache_dir=cache_dir,
    )
    model.config.use_cache = False
    return model, tokenizer


def load_train_examples(tokenizer, max_len: int):
    records = []
    with TRAIN_JSONL.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    # Nemotron chat template uses assistant marker
    marker = tokenizer.encode("<|im_start|>assistant", add_special_tokens=False)
    m = len(marker)

    examples = []
    for rec in records:
        messages = rec.get("messages", [])
        try:
            full = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=False)
        except Exception:
            full = "\n".join(f"{msg['role']}: {msg['content']}" for msg in messages)

        enc = tokenizer(full, truncation=True, max_length=max_len, return_tensors="pt")
        ids = enc["input_ids"][0]
        am = enc["attention_mask"][0]

        full_ids = ids.tolist()
        starts = [i for i in range(len(full_ids) - m + 1) if full_ids[i:i + m] == marker]
        start = starts[-1] + m if starts else -1

        labels = torch.full((ids.shape[0],), -100, dtype=torch.long)
        if start >= 0 and start < labels.shape[0]:
            labels[start:] = ids[start:]

        if not (labels != -100).any():
            labels = ids.clone()

        examples.append({
            "record_id": rec.get("record_id") or rec.get("id"),
            "input_ids": ids,
            "attention_mask": am,
            "labels": labels,
        })

    examples.sort(key=lambda e: str(e["record_id"]))
    return examples


def main():
    set_seed(SEED)
    EXPERIMENT.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    print("=== Nemotron-Orchestrator-8B QLoRA Math Pilot (Phase 6.2) ===")

    train_sha = checksum(TRAIN_JSONL)
    facts = {
        "git_commit": git_rev(),
        "git_short": git_short(),
        "train_jsonl_sha256": train_sha,
        "approved_train_sha256": APPROVED_TRAIN_SHA,
        "checksum_match": train_sha == APPROVED_TRAIN_SHA,
        "model_revision": model_revision(BASE_MODEL),
        "cuda_available": torch.cuda.is_available(),
        "torch_version": torch.__version__,
        "repository": str(REPO),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if torch.cuda.is_available():
        p = torch.cuda.get_device_properties(0)
        facts["gpu"] = {"name": p.name, "vram_total_mib": round(p.total_memory / 1024**2, 2)}
    print(json.dumps(facts, indent=2))

    if not facts["checksum_match"]:
        raise SystemExit("ABORT: training subset checksum mismatch (fail-closed)")

    print("\nLoading model + tokenizer ...")
    model, tokenizer = get_model_and_tokenizer()

    print("Attaching LoRA ...")
    from peft import LoraConfig, get_peft_model

    lora_config = LoraConfig(
        r=LORA_R, lora_alpha=LORA_ALPHA, lora_dropout=LORA_DROPOUT, bias="none",
        task_type="CAUSAL_LM", target_modules=TARGET_MODULES,
    )
    model = get_peft_model(model, lora_config)
    trainable_n, total_n = model.get_nb_trainable_parameters()
    print(f"  trainable {trainable_n:,} / total {total_n:,} "
          f"({(100.0 * trainable_n / total_n):.3f}%)")
    model.train()
    # Enable gradient checkpointing to fit 8B model in 12GB VRAM
    model.enable_input_require_grads()
    model.gradient_checkpointing_enable()
    if torch.cuda.is_available():
        model = model.to("cuda")

    print("\nLoading training examples ...")
    examples = load_train_examples(tokenizer, MAX_SEQ_LEN)
    print(f"  {len(examples)} examples (deterministic order)")

    trainable_params = [p for p in model.parameters() if p.requires_grad]
    if OPTIMIZER == "paged_adamw_8bit":
        import bitsandbytes as bnb
        opt = bnb.optim.AdamW8bit(trainable_params, lr=LR, weight_decay=WEIGHT_DECAY)
    else:
        opt = torch.optim.AdamW(trainable_params, lr=LR, weight_decay=WEIGHT_DECAY)

    total_steps = MAX_STEPS
    warmup = max(1, int(total_steps * WARMUP_RATIO))

    def lr_fac(step):
        if step < warmup:
            return (step + 1) / warmup
        if LR_SCHEDULE == "cosine":
            prog = (step - warmup) / max(total_steps - warmup, 1)
            return float(0.5 * (1 + np.cos(np.pi * prog)))
        return 1.0

    csv_path = LOGS / "step_metrics.csv"
    csvf = open(csv_path, "w", newline="")
    cw = csv.writer(csvf)
    cw.writerow(["step", "loss", "lr", "mem_alloc_mib", "mem_reserved_mib",
                 "tokens_this_step", "tokens_per_sec", "elapsed_s"])

    step = 0
    micro = 0
    loss_window = 0.0
    token_window = 0
    window_t0 = time.perf_counter()
    t_start = time.perf_counter()
    log_rows = []
    peak_mem = 0.0
    idx = 0

    print(f"Training for {total_steps} steps ...")
    while step < total_steps:
        ex = examples[idx % len(examples)]
        idx += 1
        input_ids = ex["input_ids"].unsqueeze(0).to("cuda")
        am = ex["attention_mask"].unsqueeze(0).to("cuda")
        labels = ex["labels"].unsqueeze(0).to("cuda")

        out = model(input_ids=input_ids, attention_mask=am, labels=labels)
        loss = out.loss / GRAD_ACCUM
        loss_window += float(out.loss.detach())
        token_window += int(am.sum().item())
        loss.backward()

        if torch.cuda.is_available():
            peak_mem = max(peak_mem, torch.cuda.max_memory_allocated() / 1024**2)
        micro += 1

        if micro % GRAD_ACCUM == 0:
            torch.nn.utils.clip_grad_norm_(trainable_params, MAX_GRAD_NORM)
            fac = lr_fac(step)
            cur_lr = LR * fac
            for g in opt.param_groups:
                g["lr"] = cur_lr
            opt.step()
            opt.zero_grad()

            now = time.perf_counter()
            step += 1
            avg_loss = loss_window / GRAD_ACCUM
            toks = token_window
            dt = now - window_t0
            tps = toks / dt if dt > 0 else 0.0
            loss_window = 0.0
            token_window = 0
            window_t0 = now

            if torch.cuda.is_available():
                alloc = torch.cuda.memory_allocated() / 1024**2
                reserved = torch.cuda.memory_reserved() / 1024**2
            else:
                alloc = reserved = 0.0

            row = {
                "step": step, "loss": round(avg_loss, 5),
                "lr": round(cur_lr, 7),
                "mem_alloc_mib": round(alloc, 1),
                "mem_reserved_mib": round(reserved, 1),
                "tokens_this_step": toks,
                "tokens_per_sec": round(tps, 2),
                "elapsed_s": round(now - t_start, 3),
            }
            log_rows.append(row)
            cw.writerow([str(row[k]) for k in
                         ["step", "loss", "lr", "mem_alloc_mib", "mem_reserved_mib",
                          "tokens_this_step", "tokens_per_sec", "elapsed_s"]])
            csvf.flush()
            if step % LOGGING_STEPS == 0 or step == 1:
                print(f"  step {step:3d} loss={avg_loss:.4f} lr={row['lr']:.2e} "
                      f"tps={tps:.1f} mem=(alloc {alloc:.0f}, reserved {reserved:.0f})MiB")

    csvf.close()

    if torch.cuda.is_available():
        peak_mem = max(peak_mem, torch.cuda.max_memory_allocated() / 1024**2)

    training_log = {
        "experiment_id": EXPERIMENT_ID, "phase": PHASE,
        "status": "COMPLETED",
        "pre_training": {
            "git_commit": facts["git_commit"], "git_short": facts["git_short"],
            "train_jsonl_sha256": train_sha,
            "approved_train_sha256": APPROVED_TRAIN_SHA,
            "checksum_match": train_sha == APPROVED_TRAIN_SHA,
            "model_revision": facts["model_revision"],
        },
        "config": {
            "experiment_id": EXPERIMENT_ID, "phase": PHASE,
            "training_view_id": "math_300m_v0.1", "base_model": BASE_MODEL,
            "quantization": {"load_in_4bit": True, "bnb_4bit_use_double_quant": True,
                             "bnb_4bit_quant_type": "nf4", "bnb_4bit_compute_dtype": "bfloat16"},
            "lora": {"r": LORA_R, "lora_alpha": LORA_ALPHA, "lora_dropout": LORA_DROPOUT,
                     "bias": "none", "task_type": "CAUSAL_LM", "target_modules": TARGET_MODULES},
            "training": {"seed": SEED, "max_seq_length": MAX_SEQ_LEN, "max_steps": MAX_STEPS,
                         "per_device_train_batch_size": BATCH_SIZE,
                         "gradient_accumulation_steps": GRAD_ACCUM,
                         "effective_batch_size": GRAD_ACCUM * BATCH_SIZE,
                         "learning_rate": LR, "weight_decay": WEIGHT_DECAY,
                         "lr_scheduler_type": LR_SCHEDULE, "warmup_ratio": WARMUP_RATIO,
                         "optim": OPTIMIZER, "max_grad_norm": MAX_GRAD_NORM,
                         "bf16": True, "gradient_checkpointing": True},
        },
        "trainable_parameters": int(trainable_n),
        "trainable_percent": round(100.0 * trainable_n / total_n, 4),
        "training_metrics": {
            "steps": step,
            "examples_consumed": step * GRAD_ACCUM,
            "final_loss": log_rows[-1]["loss"] if log_rows else None,
            "min_loss": min((r["loss"] for r in log_rows), default=None),
            "peak_mem_allocated_mib": round(peak_mem, 1),
            "last_mem_allocated_mib": log_rows[-1]["mem_alloc_mib"] if log_rows else None,
            "last_mem_reserved_mib": log_rows[-1]["mem_reserved_mib"] if log_rows else None,
            "throughput_tps_mean": round(
                sum(r["tokens_per_sec"] for r in log_rows) / len(log_rows), 2) if log_rows else None,
            "wall_time_s": round(time.perf_counter() - t_start, 3),
        },
        "files": {"step_metrics": str(csv_path), "adapter": str(OUTPUT_DIR)},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    (EXPERIMENT / "config.json").write_text(
        json.dumps(training_log["config"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (EXPERIMENT / "training_log.json").write_text(
        json.dumps(training_log, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    model.save_pretrained(str(OUTPUT_DIR))
    print(f"\nAdapter saved -> {OUTPUT_DIR}")
    print(f"steps={step} final_loss={log_rows[-1]['loss'] if log_rows else None} "
          f"peak_mem={peak_mem:.0f}MiB")
    print("training_log.json + config.json written.")


if __name__ == "__main__":
    main()
