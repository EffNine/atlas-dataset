# Sprint 5B.7 — M2' Controlled Training + Evaluation

> **Experiment:** `lora_pilot_math_m2prime_v0.1`
> **Sprint:** 5B.7
> **Status:** READY FOR EXECUTION
> **Date:** 2026-08-09

---

## 1. Experiment Purpose

Controlled validation of the training pipeline with exposure control.
M2' contains exactly one additional training record versus M1:
- **M1:** 117 records
- **M2':** 118 records (+`expert_math_000761`)
- **All other variables identical:** base model, quantization, LoRA config,
  hyperparameters, evaluation set, seed, generation policy.

This isolates the effect of a single additional training record on model
performance, with zero eval-leakage confound.

---

## 2. Pre-Flight Verification

| Check | Expected |
|-------|----------|
| M2' staged_train.jsonl SHA-256 | `7dfa81114f4096286415a672830f6ff334cc95066080fd9f5267e86d0e413dda` |
| M2' record count | 118 |
| M1 ⊆ M2' | Yes (all 117 M1 records present) |
| M2' eval overlap | 0 records |
| M1 eval overlap | 0 records |
| M1 adapter exists | `experiments/lora_pilot_math_v0.1/checkpoints/` |
| CUDA runtime available | RTX 5070 on devpc |

---

## 3. Execution Steps

### Step 1: Verify environment (on devpc)
```bash
ssh afnan@100.103.161.46
cd /mnt/d/atlas-dataset
.venv/bin/python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

### Step 2: Pre-flight checksum verification
```bash
.venv/bin/python -c "
import hashlib
h = hashlib.sha256()
with open('experiments/lora_pilot_math_m2prime_v0.1/staged_train.jsonl', 'rb') as f:
    for chunk in iter(lambda: f.read(65536), b''):
        h.update(chunk)
print(h.hexdigest())
"
```
Expected: `7dfa81114f4096286415a672830f6ff334cc95066080fd9f5267e86d0e413dda`

### Step 3: Train M2'
```bash
.venv/bin/python experiments/lora_pilot_math_m2prime_v0.1/run_m2prime_training.py
```

### Step 4: Evaluate M2'
```bash
.venv/bin/python experiments/lora_pilot_math_m2prime_v0.1/run_m2prime_evaluation.py
```

---

## 4. Identical Variables (vs M1)

| Variable | Value |
|----------|-------|
| Base model | `Qwen/Qwen2.5-7B-Instruct` |
| Quantization | NF4 4-bit + double quant + bf16 |
| LoRA rank (r) | 8 |
| LoRA alpha | 16 |
| LoRA dropout | 0.05 |
| Target modules | q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj |
| Learning rate | 2e-4 |
| Scheduler | cosine |
| Warmup ratio | 0.03 |
| Optimizer | paged_adamw_8bit |
| Batch size | 1 |
| Gradient accumulation | 8 |
| Max steps | 60 |
| Examples consumed | 480 |
| Seed | 42 |
| Max seq length | 256 |
| Eval set | `math_eval_v2` (N=100) | `math_eval_v2` (N=100) |
| Evaluation engine | QEE v2 |
| Generation policy | greedy, max_new_tokens=256 |

---

## 5. M2' vs M1 Differences

| Aspect | M1 | M2' |
|--------|----|-----|
| Training records | 117 | 118 |
| M2' only record | — | `expert_math_000761` |
| Difficulty-2 records | 100 | 101 |
| Difficulty-3 records | 17 | 17 |
| Avg presentations/record | 4.10 | 4.07 |
| Eval overlap | 0 | 0 |

---

## 6. Deliverables

| Artifact | Path |
|----------|------|
| Training log | `experiments/lora_pilot_math_m2prime_v0.1/training_log.json` |
| Config | `experiments/lora_pilot_math_m2prime_v0.1/config.json` |
| Step metrics | `experiments/lora_pilot_math_m2prime_v0.1/training_log/step_metrics.csv` |
| Adapter | `experiments/lora_pilot_math_m2prime_v0.1/checkpoints/` |
| Evaluation report | `experiments/lora_pilot_math_m2prime_v0.1/evaluation/m2prime_evaluation.json` |
| Per-example | `experiments/lora_pilot_math_m2prime_v0.1/evaluation/m2prime_per_example.jsonl` |
| Baseline results | `experiments/lora_pilot_math_m2prime_v0.1/evaluation/m2prime_baseline_results.jsonl` |
| M1 results | `experiments/lora_pilot_math_m2prime_v0.1/evaluation/m2prime_m1_results.jsonl` |
| M2' results | `experiments/lora_pilot_math_m2prime_v0.1/evaluation/m2prime_m2prime_results.jsonl` |

---

## 7. Stop Conditions

- Do NOT start another training run.
- Do NOT modify the dataset.
- Do NOT modify the evaluator.
- Do NOT modify Protocol v2.
- Wait for Technical Lead review before any further action.
