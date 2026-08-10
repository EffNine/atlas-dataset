# Phase 5B.2 — QLoRA Math Pilot M1 Training Report

> **Phase:** 5B.2  
> **Experiment:** `lora_pilot_math_v0.1`  
> **Date:** 2026-08-08  
> **Status:** COMPLETED  
> **Execution Environment:** Atlas Dev PC (devpc)

---

## 1. Execution Environment

| Item | Value |
|------|-------|
| Host | devpc (Ubuntu 26.04, Linux 7.0.0-29-generic) |
| GPU | NVIDIA GeForce RTX 5070 12GB |
| VRAM total | 11,773 MiB |
| CUDA version | 13.0 |
| PyTorch | 2.13.0+cu130 |
| Python | 3.11.15 |
| transformers | 5.14.1 |
| peft | 0.20.0 |
| bitsandbytes | 0.50.0 |
| venv | `.venv` |

**Environment verification:** CUDA available = `true`, GPU detected = `NVIDIA GeForce RTX 5070`.

---

## 2. Training Configuration

| Parameter | Value |
|-----------|-------|
| Base model | `Qwen/Qwen2.5-7B-Instruct` |
| Model revision | `a09a35458c702b33eeacc393d103063234e8bc28` |
| Quantization | NF4 4-bit + double quant, bf16 compute |
| LoRA r | 8 |
| LoRA alpha | 16 |
| LoRA dropout | 0.05 |
| Target modules | q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj |
| Seed | 42 |
| Max steps | 60 |
| Batch size | 1 |
| Gradient accumulation | 8 (effective batch = 8) |
| Learning rate | 2e-4 |
| LR scheduler | cosine, warmup 0.03 |
| Optimizer | paged_adamw_8bit |
| Max grad norm | 1.0 |
| Max seq length | **256** (reduced from 1024 due to 12GB VRAM constraint) |
| bf16 | true |
| Gradient checkpointing | true |

### VRAM Constraint Resolution

The original configuration used `max_seq_length=1024` with `device_map="auto"`, which caused OOM on the RTX 5070 12GB. The fix:
1. Load model on CPU first, then move to CUDA after LoRA attachment
2. Reduce `max_seq_length` to 256
3. Set `PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:128`

Peak VRAM during training: **8,624 MiB** (73% of 11,773 MiB total).

---

## 3. Dataset Provenance

| Item | Value |
|------|-------|
| Training view | `math_300m_v0.1` |
| Source | expert-math-002 / OpenMathInstruct-2 |
| License | CC-BY-4.0 |
| Train records | 117 |
| Eval records | 13 |
| Train JSONL SHA-256 | `6aecc2a754c1a4aec941a9dbb59136445cf04175a0ae02c158e86acd4e4a4572` |
| Checksum match | `true` |
| Git commit | `d1fb9310c37d5e119327f3baa45f89cab2d4c5b0` |
| Git short | `d1fb931` |

---

## 4. Training Results

| Metric | Value |
|--------|-------|
| Steps completed | 60 / 60 |
| Examples consumed | 480 (60 × 8) |
| Final loss | 0.25298 |
| Min loss | 0.15809 |
| Peak VRAM allocated | 8,624 MiB |
| Throughput (mean) | 1,035 tok/s |
| Wall time | 109.7s (~1.8 min) |
| Trainable parameters | 20,185,088 (0.264% of 7.6B) |

### Loss Trajectory

| Step | Loss | LR | Throughput (tok/s) |
|------|------|----|-------------------|
| 1 | 0.7769 | 2.00e-04 | 802.9 |
| 10 | 0.3320 | 1.91e-04 | 1,083.7 |
| 20 | 0.3247 | 1.58e-04 | 1,028.1 |
| 30 | 0.2930 | 1.08e-04 | 1,037.9 |
| 40 | 0.3544 | 5.63e-05 | 1,071.5 |
| 50 | 0.2428 | 1.67e-05 | 1,022.9 |
| 60 | 0.2530 | 1.00e-07 | 1,059.4 |

Loss decreased from 0.777 (step 1) to 0.253 (step 60), with minimum 0.158.

---

## 5. Evaluation Results (QEE v2, math dispatch)

### Post-Training (LoRA Adapter)

| Metric | Value |
|--------|-------|
| Correctness | **0.9231** |
| Reasoning quality | **0.8923** |
| Hallucination rate | **0.0769** |
| Answer format consistency | 1.0 |
| Evaluated examples | 13 / 13 |
| Mean latency | 2.02 s |
| Tokens/sec | 17.72 |

### Comparison vs. Baseline (Phase 5A.3 / baseline_eval_v0.2)

| Metric | Baseline (5A.3) | Post-training (5B.2) | Delta |
|--------|-----------------|---------------------|-------|
| Correctness | 0.6109 | **0.9231** | **+0.3122** |
| Reasoning quality | 0.6796 | **0.8923** | **+0.2127** |
| Hallucination rate | 0.3846 | **0.0769** | **-0.3077** |
| Answer format consistency | 1.0 | 1.0 | 0.0 |

### Key Findings

1. **Correctness improved +0.312** (0.611 → 0.923) — a substantial gain.
2. **Hallucination rate dropped -0.308** (0.385 → 0.077) — near-zero hallucination.
3. **Reasoning quality improved +0.213** (0.680 → 0.892).
4. Format consistency remained at 1.0 (perfect).
5. Inference throughput improved: 17.72 tok/s vs 7.85 tok/s in Phase 5B.1.
6. Training was **6x faster** than Phase 5B.1 (109s vs 1543s) due to shorter sequences.

---

## 6. Artifacts

| Artifact | Path |
|----------|------|
| Config | `experiments/lora_pilot_math_v0.1/config.json` |
| Training log | `experiments/lora_pilot_math_v0.1/training_log.json` |
| Step metrics | `experiments/lora_pilot_math_v0.1/training_log/step_metrics.csv` |
| Adapter | `experiments/lora_pilot_math_v0.1/checkpoints/` |
| Post-training eval | `experiments/lora_pilot_math_v0.1/evaluation/post_training.json` |
| Per-example results | `experiments/lora_pilot_math_v0.1/evaluation/post_training_per_example.jsonl` |
| Adapter metadata | `experiments/lora_pilot_math_v0.1/evaluation/adapter_metadata.json` |

---

## 7. Known Issues

1. **Reduced sequence length:** `max_seq_length` was reduced from 1024 to 256 to fit within 12GB VRAM. This may truncate longer math problems. The Phase 5B.1 pilot used 1024 but required a different GPU configuration.
2. **Small eval set (N=13):** Below the protocol minimum of N≥30. Results are directional, not statistically robust.
3. **No baseline re-run:** Baseline metrics come from Phase 5A.3 (`baseline_eval_v0.2`). The baseline was run with `max_new_tokens=256`; the post-training eval also uses 256, so comparison is valid.

---

## 8. Recommendation

**GO for continued LoRA exploration on math.**

The QLoRA adapter demonstrates measurable improvement on the math eval split:
- Correctness: +0.312 (0.611 → 0.923)
- Hallucination rate: -0.308 (0.385 → 0.077)

However, N=13 is below the research-protocol minimum (N≥30). The framework infrastructure is validated and ready for expanded eval splits.

---

*Report generated: 2026-08-08 | Execution environment: Atlas Dev PC (devpc)*
