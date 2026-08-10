# Expanded Evaluation Report — Math LoRA Adapter v0.1 (Sprint 5B.3)

**Experiment ID:** `lora_pilot_math_v0.1`
**Phase:** 5B.3 Expanded Evaluation
**Status:** COMPLETE
**Evaluation Engine:** QEE v2 (Protocol v2)
**Eval Set:** `math_eval_v2` (N=100)

---

## 1. Executive Summary

Extended evaluation of the frozen M1 LoRA adapter on the Protocol v2-certified `math_eval_v2` eval set (N=100).

**Key findings:**
- Correctness: baseline 0.6205 → adapter 0.7017, **delta +0.0812**
- Reasoning quality: baseline 0.685 → adapter 0.7407, **delta +0.0557**
- Hallucination rate: baseline 0.38 → adapter 0.30, **delta -0.08**
- Format consistency: 1.0 (unchanged)
- **Statistical significance:** p=0.225 (not significant), Cohen's d=0.17 (small effect)

**Recommendation: HOLD** — Adapter improves across multiple metrics, but statistical significance is insufficient. Proceed with caution pending larger-scale validation.

---

## 2. Evaluation Configuration

### 2.1 Hardware Environment

| Item | Value |
|------|-------|
| Device | CUDA |
| GPU | NVIDIA GeForce RTX 5070 12GB |
| VRAM | 11773.06 MiB total |
| PyTorch | 2.13.0+cu130 |
| CUDA | 13.0 |

### 2.2 Eval Set

| Item | Value |
|------|-------|
| Eval set ID | `math_eval_v2` |
| Records | N=100 |
| Source | `expert-pilot-6500-v0.1` |
| Checksum | `16288500568c4dc161beaf55d557709519ab5d41eea0aeddd01c5fc735989056` |
| Protocol v2 certificate | READY |

### 2.3 Model Configuration

| Item | Baseline | Adapter |
|------|----------|---------|
| Base model | Qwen/Qwen2.5-7B-Instruct | Same |
| Quantization | NF4 4-bit + double quant | Same |
| Compute dtype | bfloat16 | Same |
| Sampling | greedy | greedy |
| max_new_tokens | Dynamic budget (P8) | Dynamic budget (P8) |

### 2.4 LoRA Adapter Configuration

| Item | Value |
|------|-------|
| Path | `experiments/lora_pilot_math_v0.1/checkpoints` |
| r | 8 |
| lora_alpha | 16 |
| lora_dropout | 0.05 |
| target_modules | q,k,v,o,gate,up,down_proj |
| Trainable parameters | 20,185,088 (0.264%) |
| Total parameters | 7,635,801,600 |
| Training steps | 60 |
| Training data | `math_300m_v0.1` (117 records) |
| Learning rate | 2e-4 (cosine) |

---

## 3. Evaluation Results

### 3.1 Aggregate Metrics Comparison

| Metric | Baseline | Adapter | Delta | Direction |
|--------|----------|---------|-------|-----------|
| **Correctness** | 0.6205 ± 0.4872 | 0.7017 ± 0.4583 | **+0.0812** | ↑ |
| **Reasoning Quality** | 0.6850 ± 0.3337 | 0.7407 ± 0.3139 | **+0.0557** | ↑ |
| **Hallucination Rate** | 0.3800 ± 0.4878 | 0.3000 ± 0.4606 | **-0.0800** | ↓ |
| **Answer Format Consistency** | 1.0000 ± 0.0000 | 1.0000 ± 0.0000 | 0.0000 | - |

### 3.2 Statistical Tests

| Item | Value |
|------|-------|
| Sample size (baseline) | N=100 |
| Sample size (adapter) | N=100 |
| t-statistic | 1.2134 |
| p-value (two-tailed) | 0.224958 |
| Cohen's d | 0.1716 |
| **Significance verdict** | Not significant (p ≥ 0.05) |
| Effect size verdict | Small |

### 3.3 Truncation Analysis

| Item | Baseline | Adapter |
|------|----------|---------|
| Truncated records | 75 | 93 |
| Truncation rate | 0.75 | 0.93 |
| EOS stop | 25 | 7 |
| max_length stop | 75 | 93 |

**Note:** High adapter truncation rate (93%) indicates longer model outputs that may not complete within budget.

---

## 4. Per-Example Analysis

### 4.1 Sample Status Distribution

| Status | Count | Percentage |
|--------|-------|------------|
| **Improved** | 18 | 18% |
| **Regressed** | 10 | 10% |
| **Unchanged** | 72 | 72% |

### 4.2 Biggest Gains (Top 5)

| record_id | Baseline | Adapter | Delta |
|-----------|----------|---------|-------|
| expert_math_000512 | 0.0 | 1.0 | +1.0 |
| expert_math_000513 | 0.0 | 1.0 | +1.0 |
| expert_math_000788 | 0.0 | 1.0 | +1.0 |
| expert_math_000831 | 0.0 | 1.0 | +1.0 |
| expert_math_000900 | 0.0 | 1.0 | +1.0 |

### 4.3 Biggest Regressions (Top 5)

| record_id | Baseline | Adapter | Delta |
|-----------|----------|---------|-------|
| expert_math_000221 | 1.0 | 0.0 | -1.0 |
| expert_math_000732 | 1.0 | 0.0 | -1.0 |
| expert_math_001177 | 1.0 | 0.0 | -1.0 |
| expert_math_001199 | 1.0 | 0.0 | -1.0 |
| expert_math_001362 | 1.0 | 0.0 | -1.0 |

**Analysis:** 10 samples fully regressed (1.0 → 0.0). Root cause: adapter changed scoring method from `number`/`numeric_sampling` to `unparsable` for previously-correct responses.

---

## 5. Analysis by Difficulty

| Difficulty | Count | Baseline mean | Adapter mean | Delta |
|------------|-------|---------------|--------------|-------|
| 2 (Easy) | 82 | 0.6104 | 0.7094 | **+0.099** |
| 3 (Medium) | 16 | 0.6875 | 0.6250 | **-0.0625** |
| 4 (Hard) | 2 | 0.5000 | 1.0000 | +0.500 |

**Observations:**
- Difficulty 2: Adapter performs better (+9.9%)
- Difficulty 3: Adapter performs worse (-6.25%)
- Difficulty 4: Too few samples (N=2) to draw conclusions

---

## 6. Failure Analysis

### 6.1 Records Below 0.4 Correctness

The adapter evaluation produced **10 records** with correctness = 0.0 (fully incorrect).

### 6.2 Scoring Method Distribution

| Method | Count |
|--------|-------|
| number | 50 |
| unparsable | 30 |
| numeric_sampling | 20 |

**Note:** 30% of records scored as "unparsable", indicating the adapter produced outputs where the final answer could not be extracted or compared.

---

## 7. Comparison with Phase 5B.1 Results

| Metric | Phase 5B.1 (N=13) | Sprint 5B.3 (N=100) | Delta |
|--------|-------------------|---------------------|-------|
| Baseline Correctness | 0.6109 | 0.6205 | +0.0096 |
| Adapter Correctness | 0.6538 | 0.7017 | +0.0479 |
| **Delta Correctness** | **+0.0429** | **+0.0812** | **+0.0383** |
| Baseline Hallucination | 0.3846 | 0.3800 | -0.0046 |
| Adapter Hallucination | 0.3077 | 0.3000 | -0.0077 |
| **Delta Hallucination** | **-0.0769** | **-0.0800** | **-0.0031** |

**Trends:**
- Expanded evaluation shows larger correctness gain (+8.12% vs +4.29%)
- Hallucination reduction is consistent (-8.00% vs -7.69%)
- Baseline consistency across eval sets confirms eval set integrity

---

## 8. Protocol v2 Compliance Checklist

| Check | Status |
|-------|--------|
| Eval set checksum matches manifest | ✅ PASS |
| Protocol v2 certificate READY | ✅ PASS |
| N ≥ 30 (benchmark gate) | ✅ PASS (N=100) |
| Baseline evaluation completed | ✅ PASS |
| Adapter evaluation completed | ✅ PASS |
| Per-example results recorded | ✅ PASS |
| Statistical tests executed | ✅ PASS |

---

## 9. Recommendation

### 9.1 Strengths

1. **Measurable correctness improvement:** +8.12% (0.6205 → 0.7017)
2. **Stable hallucination reduction:** -8.00% (0.38 → 0.30)
3. **Reasoning quality improvement:** +5.57%
4. **Format consistency maintained:** 1.0 (no change)
5. **More improved samples than regressed:** 18 vs 10

### 9.2 Risks

1. **Statistical significance insufficient:** p=0.225, cannot rule out random variation
2. **Small effect size:** Cohen's d=0.17
3. **High truncation rate:** 93% of adapter responses truncated
4. **Sample regression:** 10% of samples regressed from correct to incorrect
5. **Difficulty 3 performance drop:** Medium-difficulty samples decreased by 6.25%

### 9.3 Recommendation

**HOLD** — Current results support continued optimization but do not justify deployment.

Suggested next steps:
1. Increase training data size (current 117 → recommended 1000+)
2. Tune hyperparameters (learning rate, steps, rank)
3. Expand eval set (N=100 → N=500+)
4. Conduct larger-scale LoRA training experiments

---

## 10. Deliverables

| Artifact | Path |
|----------|------|
| Evaluation report | `experiments/lora_pilot_math_v0.1/evaluation/expanded_5b3/expanded_evaluation.json` |
| Per-example results | `experiments/lora_pilot_math_v0.1/evaluation/expanded_5b3/expanded_per_example.jsonl` |
| Baseline raw results | `experiments/lora_pilot_math_v0.1/evaluation/expanded_5b3/expanded_baseline_results.jsonl` |
| Adapter raw results | `experiments/lora_pilot_math_v0.1/evaluation/expanded_5b3/expanded_adapter_results.jsonl` |
| This report | `docs/reports/sprint_5b3_expanded_evaluation.md` |

---

*Report generated: 2026-08-08 12:15 UTC*
*Evaluation engine: QEE v2 (Protocol v2)*
*Execution environment: NVIDIA GeForce RTX 5070 12GB*
