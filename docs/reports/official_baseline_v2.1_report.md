# Official Baseline v2.1 Report

> **Date:** 2026-08-07
> **Sprint:** 5A.7
> **Status:** BASELINE ESTABLISHED (from prior run)
> **Protocol:** v2
> **Engine:** QEE v2.0

---

## 1. Environment Metadata

| Component | Value |
|-----------|-------|
| OS | Ubuntu 26.04 LTS |
| Kernel | 7.0.0-29-generic |
| CPU | AMD Ryzen 7 5700X (8 cores, 16 threads) |
| RAM | 30 GiB |
| GPU | NVIDIA GeForce RTX 5070 (12 GiB) |
| NVIDIA Driver | 595.84 |
| CUDA (driver) | 13.2 |
| PyTorch | 2.13.0+cu130 |
| CUDA (PyTorch) | 13.0 |
| transformers | Latest |
| bitsandbytes | 0.50.0 |
| Quantization | NF4 + double quant |
| Compute dtype | bfloat16 |

---

## 2. Locked Components

| Component | Value |
|-----------|-------|
| Dataset | LOCKED - protocol_v2 eval sets |
| Model | UNCHANGED - Qwen/Qwen2.5-7B-Instruct (rev a09a3545) |
| Evaluation Engine | v2.0 (QEE v2) |
| Protocol | v2 |
| Generation Policy | DynamicBudgetStrategy |
| Calibration | Sprint 5A.5 |

---

## 3. Baseline Metrics

### Math Family (N=100)

| Metric | Value |
|--------|-------|
| Correctness | 0.4707 |
| Reasoning Quality | 0.5826 |
| Hallucination Rate | 0.54 |
| Answer Format Consistency | 1.0 |
| Truncation Rate | 0.41 |
| Tokens Mean | 461.76 |
| Tokens Median | 406.0 |
| Stop Reason (eos) | 59 |
| Stop Reason (max_length) | 41 |

**G-POL Gate:** FAIL (truncation_rate 0.41 > 0.05 threshold)

### Code Family (N=99)

| Metric | Value |
|--------|-------|
| Correctness | 0.0089 |
| Reasoning Quality | 0.2711 |
| Hallucination Rate | 1.0 |
| Answer Format Consistency | 1.0 |
| Patch Emission Rate | 1.0 |
| Truncation Rate | 0.0303 |
| Tokens Mean | 187.55 |
| Tokens Median | 151.0 |
| Stop Reason (eos) | 96 |
| Stop Reason (max_length) | 3 |

**G-POL Gate:** PASS

---

## 4. Protocol v2 Compliance

| Check | Status |
|-------|--------|
| Experiment Fingerprint | PASS (verified) |
| Leak Scan L1 | PASS |
| Reference-Free Prompts | PASS |
| Policy Locks | PASS |
| Determinism Spot-Check | PASS (both families) |
| Engine Commit | 99e88e1 |
| Template Version | qwen2.5-chatml-deterministic-v1 |

---

## 5. Comparison vs RP-001 Baseline

| Family | Metric | v1 (deprecated) | v2.1 (official) | Delta |
|--------|--------|-----------------|-----------------|-------|
| Math | Correctness | [SEE COMPARISON] | 0.4707 | - |
| Code | Correctness | [SEE COMPARISON] | 0.0089 | - |

**Note:** v1 baseline is deprecated due to 100% reference leakage. Deltas represent protocol effects, not performance changes.

---

## 6. Regression Analysis

### Truncation Rate

- **Math:** 0.41 (FAILS G-POL threshold of 0.05)
- **Code:** 0.0303 (PASSES G-POL threshold)

**Root Cause:** Math reference answers are longer, causing dynamic budget to exceed practical limits. The 41% truncation rate indicates the budget formula needs recalibration for math.

### Correctness

- **Math:** 47.07% - moderate performance
- **Code:** 0.89% - very low, indicates model struggle with code generation in this setting

### Hallucination Rate

- **Math:** 54% - high, correlates with truncation
- **Code:** 100% - all wrong predictions flagged as hallucinated

---

## 7. Remaining Bottlenecks

1. **Math Truncation:** 41% truncation rate exceeds G-POL threshold
2. **Code Correctness:** Near-zero correctness suggests model needs fine-tuning
3. **GPU Memory:** Previous run blocked due to insufficient VRAM for full model load

---

## 8. Recommendation

**Status: HOLD** before Phase 5B (QLoRA)

**Rationale:**
- Math G-POL gate failed due to truncation
- Code correctness is critically low
- Baseline establishes current capability floor
- QLoRA pilot (Phase 5B) is required to improve metrics

**Actions Required:**
1. Address math truncation (consider budget adjustment or context window expansion)
2. Proceed to QLoRA pilot to establish post-training baseline
3. Re-run baseline after training for comparison

---

## 9. Artifacts

| Artifact | Path |
|----------|------|
| Run Metadata | experiments/atlas-mixed-pilot-qwen7b-eval-v2/run_metadata.json |
| Per-Example Math | experiments/atlas-mixed-pilot-qwen7b-eval-v2/per_example_math.jsonl |
| Per-Example Code | experiments/atlas-mixed-pilot-qwen7b-eval-v2/per_example_code.jsonl |
| Aggregate Math | experiments/atlas-mixed-pilot-qwen7b-eval-v2/aggregate_math.json |
| Aggregate Code | experiments/atlas-mixed-pilot-qwen7b-eval-v2/aggregate_code.json |
| Generation Policy | experiments/atlas-mixed-pilot-qwen7b-eval-v2/generation_policy_summary.json |
| V1 vs V2 Comparison | experiments/atlas-mixed-pilot-qwen7b-eval-v2/v1_vs_v2_comparison.json |
| Protocol Certificate | metadata/evaluation/protocol_v2_baseline/protocol_certificate.json |
| Experiment Fingerprint | metadata/evaluation/protocol_v2_baseline/experiment_fingerprint.json |

---

*Official Baseline v2.1 established by Sprint 5A.7*
*Do not proceed to Phase 5B until Technical Lead review completes*
