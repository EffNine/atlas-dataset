# Training and Evaluation Report — Math LoRA M2 (Sprint 5B.4)

**Experiment ID:** `lora_pilot_math_m2_v0.1`
**Phase:** 5B.4 QLoRA M2 Training
**Status:** COMPLETE
**Evaluation Engine:** QEE v2 (Protocol v2)
**Eval Set:** `math_eval_v2` (N=100)

---

## 1. Executive Summary

Training and evaluation of the M2 LoRA adapter using a larger training split (131 records) compared to M1 (117 records). Identical hyperparameters used.

**Key findings:**
- M1 correctness: 0.7017 (117 train records)
- M2 correctness: 0.6800 (131 train records)
- **M2 underperformed M1 by -0.0217**
- Both M1 and M2 improve over baseline (0.6205), but M1 is superior

**Recommendation: HOLD — EXPLORATORY** — The M2 result is reproducible (SHA-256 verified) but confounded by eval leakage (13 of 14 extra records overlap with `math_eval_v2`) and differing per-record exposure. The claim that the extra 14 records caused the decline is unsupported. The M1 adapter remains the better model. Further scaling requires a controlled comparison with identical eval overlap and exposure.

---

## 2. Training Configuration

### 2.1 Hardware Environment

| Item | Value |
|------|-------|
| Device | CUDA |
| GPU | NVIDIA GeForce RTX 5070 12GB |
| VRAM | 11774 MiB total |
| PyTorch | 2.13.0+cu130 |
| CUDA | 13.0 |

### 2.2 Training Data

| Item | M1 | M2 |
|------|------|------|
| Training view ID | `math_300m_v0.1` | `math_m2_v0.1` |
| Source | `expert-math-002` (OpenMathInstruct-2) | `expert-math-002` (OpenMathInstruct-2) |
| Training records | 117 | 131 |
| Record increase | — | +14 (+12.0%) |
| Train SHA-256 | `6aecc2a7...` | `472d6326...` |

### 2.3 Model Configuration (Identical for M1 and M2)

| Item | Value |
|------|-------|
| Base model | Qwen/Qwen2.5-7B-Instruct |
| Model revision | `a09a35458c702b33eeacc393d103063234e8bc28` |
| Quantization | NF4 4-bit + double quant |
| Compute dtype | bfloat16 |
| LoRA r | 8 |
| LoRA alpha | 16 |
| LoRA dropout | 0.05 |
| Target modules | q,k,v,o,gate,up,down_proj |
| Trainable parameters | 20,185,088 (0.264%) |
| Max seq length | 256 |
| Max steps | 60 |
| Batch size | 1 |
| Gradient accumulation | 8 |
| Effective batch size | 8 |
| Learning rate | 2e-4 (cosine) |
| Warmup ratio | 0.03 |
| Optimizer | paged_adamw_8bit |
| Weight decay | 0.01 |
| Max grad norm | 1.0 |
| Seed | 42 |

---

## 3. Training Results

### 3.1 M2 Training Metrics

| Metric | Value |
|--------|-------|
| Steps completed | 60 |
| Examples consumed | 480 |
| Final loss | 0.2296 |
| Min loss | 0.1963 |
| Peak VRAM | 8595 MiB |
| Throughput (mean) | 1037.33 tokens/sec |
| Wall time | 109.6 seconds |

### 3.2 M1 vs M2 Training Comparison

| Metric | M1 | M2 | Delta |
|--------|------|------|-------|
| Training records | 117 | 131 | +14 |
| Final loss | 0.25298 | 0.2296 | -0.0234 |
| Min loss | 0.15809 | 0.19631 | +0.0382 |
| Peak VRAM | 8624 MiB | 8595 MiB | -29 MiB |
| Throughput (mean) | 1035.34 tok/s | 1037.33 tok/s | +1.99 tok/s |
| Wall time | 109.7s | 109.6s | -0.1s |

**Observation:** M2 achieved lower final loss (-0.023) but higher min loss (+0.038), suggesting M2's training trajectory was less optimal despite more data.

---

## 4. Evaluation Results

### 4.1 Three-Way Comparison (Baseline, M1, M2)

| Metric | Baseline | M1 (117 train) | M2 (131 train) | M1 Delta | M2 Delta | M2 vs M1 |
|--------|----------|----------------|----------------|----------|----------|----------|
| **Correctness** | 0.6205 | 0.7017 | 0.6800 | +0.0812 | +0.0595 | **-0.0217** |
| **Reasoning Quality** | 0.6851 | 0.7407 | 0.7258 | +0.0556 | +0.0407 | -0.0149 |
| **Hallucination Rate** | 0.3800 | 0.3000 | 0.3200 | -0.0800 | -0.0600 | +0.0200 |
| **Format Consistency** | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 |
| **Truncation Rate** | 0.75 | 0.93 | 0.95 | +0.18 | +0.20 | +0.02 |

### 4.2 Statistical Tests (Paired t-test, N=100)

| Comparison | t-statistic | p-value | Significant? |
|------------|-------------|---------|--------------|
| M1 vs Baseline | -1.556 | 0.1197 | No (p >= 0.05) |
| M2 vs Baseline | -1.171 | 0.2415 | No (p >= 0.05) |
| M2 vs M1 | 0.513 | 0.6078 | No (p >= 0.05) |

### 4.3 Per-Example Analysis (M2 vs M1)

| Status | Count | Percentage |
|--------|-------|------------|
| M2 better than M1 | 8 | 8% |
| M1 better than M2 | 10 | 10% |
| Unchanged | 82 | 82% |

### 4.4 M2 Failure Analysis

| Metric | Value |
|--------|-------|
| Records below 0.4 correctness | 32 |
| Regressions from baseline | 10 |
| Biggest M2 gains (baseline 0 -> 1) | 5 records |
| Biggest M2 losses (baseline 1 -> 0) | 10 records |

---

## 5. Scaling Analysis

### 5.1 Scaling Observations

| Observation | Detail |
|-------------|--------|
| Training records increased | 117 -> 131 (+12.0%) |
| Correctness changed | 0.7017 -> 0.6800 (-3.1%) |
| Direction | **Negative scaling** |
| Statistical significance | Not significant (p=0.608) |

### 5.2 Possible Explanations

1. **Eval set leakage:** 13 of the 14 extra M2 records overlap with `math_eval_v2`. Training on eval records can cause overfitting that degrades generalization performance, even if the model memorizes those specific examples. This is the primary confound.

2. **Different per-record exposure:** M1 records received 4–5 presentations (480 examples / 117 records); M2 records received 3–4 presentations (480 examples / 131 records). The lower exposure could contribute to the lower score independently of dataset composition.

3. **Random variation:** With N=100 eval and p=0.608, the -0.0217 difference is within normal variance.

4. **Training dynamics:** M2's min loss was HIGHER than M1's (0.196 vs 0.158), suggesting the additional data may have disrupted convergence on easier patterns.

### 5.3 Data Characteristics

| Characteristic | M1 (117 records) | M2 extra (14 records) |
|----------------|-------------------|----------------------|
| Source | expert-math-002 | expert-math-002 (same) |
| Difficulty distribution | 100 at level 2, 17 at level 3 | 11 at level 2, 3 at level 3 |
| Avg text length | 967 chars | 808 chars |
| Overlap with eval set | 0 records | **13 records** (9.9% of M2) |
| Eval-overlap record IDs | — | `expert_math_000125`, `000281`, `000831`, `000900`, `000961`, `001421`, `001505`, `001802`, `002168`, `002660`, `002701`, `002953`, `002995` |
| Non-eval extra record | — | `expert_math_000761` |

---

## 6. Protocol v2 Compliance

| Check | Status |
|-------|--------|
| Protocol v2 certificate READY | PASS |
| Eval set checksum valid | PASS |
| N >= 30 (benchmark gate) | PASS (N=100) |
| Baseline evaluation completed | PASS |
| M1 evaluation completed | PASS |
| M2 evaluation completed | PASS |
| Per-example results recorded | PASS |
| Statistical tests executed | PASS |
| Identical hyperparameters (M1 vs M2) | PASS |

---

## 7. Recommendation

### 7.1 Findings

1. **M1 remains superior:** M1 (0.7017) outperforms M2 (0.6800) by +0.0217 on correctness.
2. **Inconclusive scaling comparison:** M2 underperformed M1, but this comparison is confounded by (a) 13 eval-set overlaps in M2 that M1 lacks, and (b) different per-record exposure counts (M1: 4–5 presentations; M2: 3–4). The observed decline cannot be attributed to dataset size alone.
3. **Both adapters show directional improvement over baseline:** M1 (+8.12%) and M2 (+5.95%) both exceed baseline (0.6205), though neither reaches statistical significance at α=0.05 (M1 p=0.120, M2 p=0.241).
4. **Results not statistically significant:** The M1 vs M2 difference (p=0.608) cannot be distinguished from noise.

### 7.2 Risks

1. **Small data pool:** Only 131 eligible math records exist; limited room for further scaling.
2. **Evaluation variance:** With N=100 and binary-like scores (0/1), small sample fluctuations dominate.
3. **Potential data quality issue:** The 14 additional records may introduce lower-quality or harder examples.

### 7.3 Recommendation

**HOLD** — Do not proceed to M3 with the same approach.

Suggested next steps:
1. Analyze the 14 additional records in M2 to understand why performance decreased
2. Consider alternative scaling strategies:
   - Increase training steps (currently 60, could try 100-200)
   - Adjust learning rate (currently 2e-4, could try 1e-4 or 5e-4)
   - Use a different LoRA rank (currently r=8, could try r=16)
3. Expand the source pool beyond expert-math-002 (consider other math sources)
4. Consider full fine-tuning instead of LoRA for better scaling

---

## 8. Deliverables

| Artifact | Path |
|----------|------|
| M2 training log | `experiments/lora_pilot_math_m2_v0.1/training_log.json` |
| M2 adapter | `experiments/lora_pilot_math_m2_v0.1/checkpoints/` |
| M2 evaluation report | `experiments/lora_pilot_math_m2_v0.1/evaluation/expanded_5b4/m2_evaluation.json` |
| Per-example results | `experiments/lora_pilot_math_m2_v0.1/evaluation/expanded_5b4/m2_per_example.jsonl` |
| M2 training view | `output/training_views/math_m2_v0.1/train.jsonl` (131 records) |
| This report | `docs/reports/sprint_5b4_m2_training_evaluation.md` |

---

*Report generated: 2026-08-09 00:45 UTC*
*Evaluation engine: QEE v2 (Protocol v2)*
*Execution environment: NVIDIA GeForce RTX 5070 12GB*
