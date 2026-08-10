# Phase 5A Baseline Report

> **Date:** 2026-08-03
> **Phase:** 5A — Baseline Evaluation
> **Status:** Completed with measurement caveats

---

## 1. Objective

Establish a baseline evaluation of the Atlas training/inference pathway using the controlled LoRA validation pilot setup, prior to metric improvements in Phase 5A.2.

## 2. Model and Hardware

| Item | Value |
|------|-------|
| Model | Qwen/Qwen2.5-7B-Instruct |
| Quantization | 4-bit NF4 |
| Compute dtype | bfloat16 |
| Target hardware | NVIDIA GeForce RTX 5070 12GB |
| Seed | 42 |

## 3. Evaluation Sample Count

- **Evaluation samples:** 29

## 4. Inference Status

- **Status:** Inference completed successfully on the target hardware.
- **Validation:** RTX 5070 inference verified as part of the baseline run.

## 5. Scoring Caveat

The baseline run identified that the evaluation correctness metric needs improvement. Current automatic scoring does not yet reflect the intended calibration target and should not be treated as a final quality gate until Phase 5A.2 is complete.

## 6. Next Step

Proceed to **Phase 5A.2 Evaluation Framework v2** to improve correctness measurement before broader training or release decisions rely on evaluation output.

---

*This document summarizes the baseline evaluation state. Detailed artifacts remain under `experiments/lora_pilot_math_v0.1/`.*
