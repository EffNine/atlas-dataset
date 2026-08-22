#!/usr/bin/env python3
"""
Atlas 500M Pilot v2 — Format-Aligned Training Script

Trains Qwen/Qwen2.5-0.5B-Instruct with QLoRA on v2 format-aligned data.
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
)
from peft import LoraConfig, get_peft_model, TaskType
from datasets import Dataset

ROOT = Path("/home/afnan/projects/active/atlas-dataset")
PILOT_DIR = ROOT / "pilot" / "v0.2"
ARTIFACTS_DIR = ROOT / "artifacts" / "pilot" / "v0.2"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

# Frozen config
BASE_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
TARGET_TOKENS = 1_000_000
SEED = 42

# LoRA config
LORA_CONFIG = {
    "r": 8,
    "lora_alpha": 16,
    "lora_dropout": 0.05,
    "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    "task_type": TaskType.CAUSAL_LM,
}

# Training config
TRAINING_CONFIG = {
    "max_seq_length": 1024,
    "per_device_train_batch_size": 1,
    "gradient_accumulation_steps": 8,
    "learning_rate": 2e-4,
    "lr_scheduler_type": "cosine",
    "warmup_steps": 30,
    "optim": "paged_adamw_8bit",
    "weight_decay": 0.01,
    "max_grad_norm": 1.0,
    "gradient_checkpointing": True,
    "bf16": True,
    "seed": SEED,
}


def load_dataset(arm_name):
    """Load frozen pilot dataset."""
    path = PILOT_DIR / arm_name / "train.jsonl"
    records = []
    with open(path) as f:
        for line in f:
            records.append(json.loads(line))
    return records


def tokenize_dataset(records, tokenizer, max_len):
    """Tokenize dataset for training."""
    def tokenize_fn(examples):
        texts = []
        for msgs in examples["messages"]:
            text = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
            texts.append(text)

        tokenized = tokenizer(
            texts,
            truncation=True,
            max_length=max_len,
            padding=False,
        )
        tokenized["labels"] = tokenized["input_ids"].copy()
        return tokenized

    # Flatten messages to ensure uniform schema for Arrow
    flat_records = []
    for r in records:
        flat_records.append({
            "messages": r["messages"],
        })

    ds = Dataset.from_list(flat_records)
    ds = ds.map(
        tokenize_fn,
        batched=True,
        remove_columns=ds.column_names,
    )
    return ds


def train_arm(arm_name):
    """Train a single arm."""
    print(f"\n{'='*70}")
    print(f"TRAINING: {arm_name.upper()} (v2)")
    print(f"{'='*70}")

    start_time = time.time()

    # Load dataset
    records = load_dataset(arm_name)
    record_count = len(records)
    print(f"Records: {record_count:,}")

    # Load model
    print(f"Loading base model: {BASE_MODEL}")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )

    # Add LoRA
    print("Applying LoRA config...")
    peft_config = LoraConfig(**LORA_CONFIG)
    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()

    # Tokenize
    print("Tokenizing dataset...")
    ds = tokenize_dataset(records, tokenizer, TRAINING_CONFIG["max_seq_length"])

    # Count actual tokens
    actual_tokens = sum(len(ids) for ids in ds["input_ids"])
    print(f"Actual training tokens: {actual_tokens:,}")

    # Training args
    output_dir = ARTIFACTS_DIR / arm_name
    output_dir.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=1,
        per_device_train_batch_size=TRAINING_CONFIG["per_device_train_batch_size"],
        gradient_accumulation_steps=TRAINING_CONFIG["gradient_accumulation_steps"],
        learning_rate=TRAINING_CONFIG["learning_rate"],
        lr_scheduler_type=TRAINING_CONFIG["lr_scheduler_type"],
        warmup_steps=TRAINING_CONFIG["warmup_steps"],
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

    # Train
    print("Starting training...")
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=ds,
        data_collator=DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False),
    )

    train_result = trainer.train()

    elapsed = time.time() - start_time
    steps = train_result.global_step
    avg_loss = train_result.training_loss

    # Calculate metrics
    tokens_per_step = actual_tokens / steps if steps > 0 else 0
    tokens_per_sec = actual_tokens / elapsed if elapsed > 0 else 0

    print(f"\nTraining complete:")
    print(f"  Steps: {steps}")
    print(f"  Avg loss: {avg_loss:.4f}")
    print(f"  Elapsed: {elapsed:.1f}s")
    print(f"  Tokens/sec: {tokens_per_sec:.1f}")
    eff_epochs = steps * TRAINING_CONFIG['per_device_train_batch_size'] * TRAINING_CONFIG['gradient_accumulation_steps'] / len(ds) if len(ds) > 0 else 0
    print(f"  Effective epochs: {eff_epochs:.2f}")

    # Save adapter
    adapter_path = output_dir / "adapter"
    model.save_pretrained(str(adapter_path))
    tokenizer.save_pretrained(str(adapter_path))

    # Get VRAM usage
    peak_vram = 0
    if torch.cuda.is_available():
        peak_vram = torch.cuda.max_memory_allocated() / 1024**3
        print(f"  Peak VRAM: {peak_vram:.2f} GB")

    # Save metadata
    metadata = {
        "arm": arm_name,
        "base_model": BASE_MODEL,
        "record_count": record_count,
        "actual_tokens": actual_tokens,
        "steps": steps,
        "avg_loss": avg_loss,
        "elapsed_seconds": elapsed,
        "tokens_per_second": tokens_per_sec,
        "peak_vram_gb": peak_vram,
        "effective_epochs": eff_epochs,
        "lora_config": LORA_CONFIG,
        "training_config": TRAINING_CONFIG,
        "adapter_path": str(adapter_path),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pilot_version": "v0.2",
    }

    with open(output_dir / "training_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"  Adapter saved: {adapter_path}")
    return metadata


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", type=str, required=True, help="Arm name: general, math, code, systems, or base")
    args = parser.parse_args()

    if args.arm == "base":
        print("BASE arm: No training, evaluation only")
        print("Skipping training for base model")
        return

    metadata = train_arm(args.arm)

    print(f"\n{'='*70}")
    print(f"{args.arm.upper()} TRAINING COMPLETE (v2)")
    print(f"{'='*70}")
    print(f"  Records: {metadata['record_count']:,}")
    print(f"  Tokens: {metadata['actual_tokens']:,}")
    print(f"  Loss: {metadata['avg_loss']:.4f}")
    print(f"  Time: {metadata['elapsed_seconds']:.1f}s")
    print(f"  Adapter: {metadata['adapter_path']}")


if __name__ == "__main__":
    main()
