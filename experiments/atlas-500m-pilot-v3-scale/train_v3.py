#!/usr/bin/env python3
"""
Atlas 500M Pilot v3 — Training Script

Trains Qwen/Qwen2.5-0.5B-Instruct with QLoRA on v3 scaled data.
Saves checkpoints at ~1M token intervals for learning curve analysis.
"""
import json
import hashlib
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TrainingArguments,
    Trainer,
    DataCollatorForLanguageModeling,
    TrainerCallback,
)
from peft import LoraConfig, get_peft_model, TaskType
from datasets import Dataset

ROOT = Path("/home/afnan/projects/active/atlas-dataset")
DATA_DIR = ROOT / "experiments" / "atlas-500m-pilot-v3-scale" / "data"
ARTIFACTS_DIR = ROOT / "experiments" / "atlas-500m-pilot-v3-scale" / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

BASE_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
TARGET_TOKENS = 5_000_000
SEED = 42
CHECKPOINT_TOKEN_INTERVAL = 1_000_000

LORA_CONFIG = {
    "r": 8,
    "lora_alpha": 16,
    "lora_dropout": 0.05,
    "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    "task_type": TaskType.CAUSAL_LM,
}

TRAINING_CONFIG = {
    "max_seq_length": 1024,
    "per_device_train_batch_size": 1,
    "gradient_accumulation_steps": 8,
    "learning_rate": 2e-4,
    "lr_scheduler_type": "cosine",
    "warmup_ratio": 0.03,
    "optim": "paged_adamw_8bit",
    "weight_decay": 0.01,
    "max_grad_norm": 1.0,
    "gradient_checkpointing": True,
    "bf16": True,
    "seed": SEED,
}


class CheckpointCallback(TrainerCallback):
    """Save adapter checkpoint at token intervals."""
    def __init__(self, model, tokenizer, output_dir, interval_tokens, batch_size, grad_steps):
        self.model = model
        self.tokenizer = tokenizer
        self.output_dir = Path(output_dir)
        self.interval = interval_tokens
        self.bs = batch_size
        self.gs = grad_steps
        self.tokens_seen = 0
        self.checkpoints = []

    def on_step_end(self, args, state, control, **kwargs):
        self.tokens_seen += self.bs * self.gs
        # Save checkpoint at interval boundaries
        for boundary in range(self.interval, int(self.tokens_seen // self.interval) * self.interval + 1, self.interval):
            if boundary == int(self.tokens_seen // self.interval) * self.interval and self.tokens_seen >= boundary:
                cp_dir = self.output_dir / f"checkpoint_{boundary // 1000}K"
                cp_dir.mkdir(parents=True, exist_ok=True)
                self.model.save_pretrained(str(cp_dir))
                self.tokenizer.save_pretrained(str(cp_dir))
                self.checkpoints.append({
                    "tokens": boundary,
                    "steps": state.global_step,
                    "loss": state.log_history[-1].get("loss") if state.log_history else None,
                    "path": str(cp_dir),
                })
                print(f"    [CHECKPOINT] {boundary//1000}K tokens, step {state.global_step}, loss={self.checkpoints[-1]['loss']:.4f}")
                break


def load_tokenizer():
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    return tokenizer


def tokenize_record(r, tokenizer, max_len):
    msgs = r.get("messages", [])
    try:
        text = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
    except Exception:
        text = "\n".join(f"{m['role']}: {m['content']}" for m in msgs)
    tokenized = tokenizer(text, truncation=True, max_length=max_len, padding=False)
    tokenized["labels"] = tokenized["input_ids"].copy()
    return tokenized["input_ids"]


def load_and_tokenize(arm_name, tokenizer, max_len):
    path = DATA_DIR / f"{arm_name}_train.jsonl"
    if not path.exists():
        print(f"  ERROR: {path} not found")
        return None, 0, 0

    records = []
    with open(path) as f:
        for line in f:
            records.append(json.loads(line))

    print(f"  Loaded {len(records):,} records from {path}")

    # Tokenize in batches
    all_ids = []
    total_tokens = 0
    batch_size = 32
    for i in range(0, len(records), batch_size):
        batch = records[i:i+batch_size]
        texts = []
        for r in batch:
            ids = tokenize_record(r, tokenizer, max_len)
            texts.append(ids)
            total_tokens += len(ids)
        all_ids.extend(texts)

    flat = []
    for ids in all_ids:
        flat.append({"input_ids": ids})

    ds = Dataset.from_list(flat)
    print(f"  Tokenized: {total_tokens:,} tokens, {len(ds):,} examples")
    return ds, total_tokens, len(records)


def train_arm(arm_name):
    print(f"\n{'='*70}")
    print(f"TRAINING: {arm_name.upper()} (v3)")
    print(f"{'='*70}")

    start_time = time.time()

    # Load tokenizer
    tokenizer = load_tokenizer()

    # Load model with quantization
    print(f"Loading base model: {BASE_MODEL}")
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
        quantization_config=None,  # Will use bitsandbytes via PEFT
    )

    # Apply LoRA
    print("Applying LoRA config...")
    peft_config = LoraConfig(**LORA_CONFIG)
    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()

    # Load and tokenize data
    ds, total_tokens, record_count = load_and_tokenize(
        arm_name, tokenizer, TRAINING_CONFIG["max_seq_length"]
    )
    if ds is None:
        return None

    print(f"  Effective training tokens: {total_tokens:,}")

    # Calculate steps needed for 5M tokens
    effective_bs = TRAINING_CONFIG["per_device_train_batch_size"] * TRAINING_CONFIG["gradient_accumulation_steps"]
    steps_for_target = max(1, (TARGET_TOKENS // total_tokens) * len(ds) // effective_bs + 1)
    actual_steps = min(steps_for_target, len(ds) * 3 // effective_bs + 1)  # Cap at ~3 epochs max
    # Ensure we hit at least ~5M tokens
    actual_steps = max(actual_steps, (TARGET_TOKENS * 2 // total_tokens) * len(ds) // effective_bs + 1)

    print(f"  Records: {record_count:,}")
    print(f"  Dataset size: {len(ds):,}")
    print(f"  Effective batch size: {effective_bs}")
    print(f"  Planned steps: ~{actual_steps} (to reach ~{TARGET_TOKENS:,} tokens)")

    # Output dir
    output_dir = ARTIFACTS_DIR / arm_name
    output_dir.mkdir(parents=True, exist_ok=True)

    # Training args
    training_args = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=1,
        max_steps=actual_steps,
        per_device_train_batch_size=TRAINING_CONFIG["per_device_train_batch_size"],
        gradient_accumulation_steps=TRAINING_CONFIG["gradient_accumulation_steps"],
        learning_rate=TRAINING_CONFIG["learning_rate"],
        lr_scheduler_type=TRAINING_CONFIG["lr_scheduler_type"],
        warmup_ratio=TRAINING_CONFIG["warmup_ratio"],
        optim=TRAINING_CONFIG["optim"],
        weight_decay=TRAINING_CONFIG["weight_decay"],
        max_grad_norm=TRAINING_CONFIG["max_grad_norm"],
        gradient_checkpointing=TRAINING_CONFIG["gradient_checkpointing"],
        bf16=TRAINING_CONFIG["bf16"],
        seed=TRAINING_CONFIG["seed"],
        logging_steps=10,
        save_strategy="no",
        report_to="none",
    )

    # Callback for checkpoints
    ckpt_callback = CheckpointCallback(
        model, tokenizer, output_dir,
        CHECKPOINT_TOKEN_INTERVAL,
        TRAINING_CONFIG["per_device_train_batch_size"],
        TRAINING_CONFIG["gradient_accumulation_steps"],
    )

    # Train
    print("Starting training...")
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=ds,
        data_collator=DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False),
        callbacks=[ckpt_callback],
    )

    train_result = trainer.train()

    elapsed = time.time() - start_time
    steps = train_result.global_step
    avg_loss = train_result.training_loss

    # Token accounting
    tokens_per_step = effective_bs * TRAINING_CONFIG["max_seq_length"]
    effective_training_tokens = steps * tokens_per_step
    repeat_factor = effective_training_tokens / total_tokens if total_tokens > 0 else 0
    effective_epochs = steps * effective_bs / len(ds) if len(ds) > 0 else 0

    print(f"\nTraining complete:")
    print(f"  Steps: {steps}")
    print(f"  Avg loss: {avg_loss:.4f}")
    print(f"  Elapsed: {elapsed:.1f}s")
    print(f"  Effective training tokens: {effective_training_tokens:,}")
    print(f"  Repeat factor: {repeat_factor:.2f}x")
    print(f"  Effective epochs: {effective_epochs:.2f}")

    # Save final adapter
    adapter_path = output_dir / "adapter"
    model.save_pretrained(str(adapter_path))
    tokenizer.save_pretrained(str(adapter_path))

    # VRAM
    peak_vram = 0
    if torch.cuda.is_available():
        peak_vram = torch.cuda.max_memory_allocated() / 1024**3
        print(f"  Peak VRAM: {peak_vram:.2f} GB")

    # Save metadata
    metadata = {
        "arm": arm_name,
        "experiment_id": "atlas-500m-pilot-v3-scale",
        "base_model": BASE_MODEL,
        "model_revision": "a09a35458c702b33eeacc393d103063234e8bc28",
        "record_count": record_count,
        "dataset_size": len(ds),
        "total_source_tokens": total_tokens,
        "effective_training_tokens": effective_training_tokens,
        "target_tokens": TARGET_TOKENS,
        "steps": steps,
        "avg_loss": avg_loss,
        "elapsed_seconds": elapsed,
        "peak_vram_gb": peak_vram,
        "repeat_factor": round(repeat_factor, 2),
        "effective_epochs": round(effective_epochs, 2),
        "lora_config": LORA_CONFIG,
        "training_config": TRAINING_CONFIG,
        "adapter_path": str(adapter_path),
        "checkpoints": ckpt_callback.checkpoints,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pilot_version": "v3",
    }

    with open(output_dir / "training_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"  Adapter saved: {adapter_path}")
    return metadata


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", type=str, required=True,
                        choices=["general", "math", "code", "systems", "all"])
    args = parser.parse_args()

    arms = ["general", "math", "code", "systems"] if args.arm == "all" else [args.arm]

    all_metadata = {}
    for arm in arms:
        meta = train_arm(arm)
        if meta:
            all_metadata[arm] = meta

    if len(all_metadata) > 1:
        summary_path = ARTIFACTS_DIR / "training_summary.json"
        with open(summary_path, "w") as f:
            json.dump(all_metadata, f, indent=2)
        print(f"\nSummary saved to {summary_path}")


if __name__ == "__main__":
    main()
