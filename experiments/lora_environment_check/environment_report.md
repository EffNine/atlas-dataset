# Environment Report — QLoRA Training Environment Validation (Phase 5B.0)

**Experiment:** `lora_environment_check`
**Status:** COMPLETE — **VERDICT: GO** for Phase 5B.1 pilot training
**Date (UTC):** 2026-08-03 23:37

## Purpose

Validate that the RTX 5070 development box can run a QLoRA LoRA pilot before
any real training begins. No dataset, training-view, or release artifacts were
modified. No full QLoRA training was started.

## Hardware

| Item | Value |
|------|-------|
| GPU | NVIDIA GeForce RTX 5070 |
| Compute capability | (12, 0) — sm_120 |
| VRAM total | 12,226.56 MiB (≈ 12 GB) |
| Multiprocessors | 48 |
| Driver | 610.62 |
| CUDA UMD version | 13.3 |
| CUDA runtime (torch) | 13.0 |

## Software Stack

| Package | Version |
|---------|---------|
| Python | 3.12.3 |
| PyTorch | 2.13.0+cu130 |
| transformers | 5.14.1 |
| peft | 0.20.0 |
| trl | 1.9.2 |
| bitsandbytes | 0.50.0 |
| accelerate | 1.14.0 |
| datasets | 5.0.1 |
| numpy | 2.5.1 |

## Model Load Configuration (validated)

- Base model: `Qwen/Qwen2.5-7B-Instruct`
- Quantization: 4-bit NF4, double quant, bf16 compute (`BitsAndBytesConfig`)
- `device_map="auto"`; model dtype after load: `torch.bfloat16`

## LoRA Adapter (validated)

- `r=8`, `lora_alpha=16`, `lora_dropout=0.05`, `bias="none"`, `task_type="CAUSAL_LM"`
- Target modules: `q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj`
- Trainable parameters: 20,185,088 (0.2643% of 7,635,801,600)

## Validation Results

| Check | Status | Detail |
|-------|--------|--------|
| Environment facts | OK | torch CUDA available, RTX 5070 sm_120 |
| Import checks | OK | transformers / peft / trl / bitsandbytes / accelerate / torch.cuda |
| Model load (NF4 dq, bf16) | OK | dtype=torch.bfloat16 |
| LoRA attach | OK | 20.19M trainable params |
| Forward pass | OK | logits shape [1, 16, 152064] |
| Backward pass | OK | loss = 1.333145 |
| Gradient step | OK | 392 LoRA params changed after one AdamW step |
| Adapter save/load | OK | save → reload → `adapter_config.json` + `adapter_model.safetensors` |

## VRAM Utilization

| Metric | Value |
|--------|-------|
| Peak allocated | 9,058.6 MiB |
| Peak reserved | 8,994.0 MiB |
| Headroom vs 12 GB | ≈ 3.2 GB |

The 12 GB VRAM budget fits the 4-bit 7B model with LoRA adapter with ~3.2 GB
headroom, consistent with the `max_steps=60` / `per_device_train_batch_size=1`
pilot configuration being feasible.

## Issues

- None. All checks passed on the second run; the only fix during the run was
  freeing the trained model before reloading the base for the adapter round-trip
  (two full 7B models cannot coexist in 12 GB).
- `device_map` attribute reported as `None` on transformers 5.14.1; model loads
  onto GPU correctly (verified by CUDA forward pass).

## Recommendation

**GO** for Phase 5B.1 LoRA pilot training on the RTX 5070 box.

Caveats carried forward from Phase 5B.0:
- QEE v2 output is raw scores only; calibrated unsupervised gating is NOT
  authorized. Human approval gates remain mandatory.
- Phase 5B.1 must re-score with the same QEE v2 engine used in Phase 5A.3.
- Runtime checks should include VRAM headroom monitoring during real training.
