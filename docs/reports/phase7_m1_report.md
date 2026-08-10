# Scaling Run M1 — Report (Phase 7.2)

> **Experiment:** `atlas-math-small-qwen7b-lora-scale-m1`
> **Phase:** 7.2
> **Status:** COMPLETED
> **Date:** 2026-08-04
> **Scope:** Math-domain capability only. No unsupported intelligence claims.

---

## 1. Run identity (reproducibility)

| Field | Value |
|-------|-------|
| Subset | `experiments/phase7_scale/subsets/M1_math_train.jsonl` (117 records) |
| Subset SHA-256 | `2dad9e241c3fa1684767ba6f88572d697cba9b641454e7a1afa1faf5f854a451` |
| Checksum match | ✅ true (verified before training, fail-closed) |
| Base model | `Qwen/Qwen2.5-7B-Instruct` |
| Model revision | `a09a35458c702b33eeacc393d103063234e8bc28` |
| Git commit | `d1fb9310c37d5e119327f3baa45f89cab2d4c5b0` |
| Seed | 42 |
| Config | locked Phase 7.2 config (`config.json`) |
| Eval set | `math_eval_v1` (N=100) |

---

## 2. Training metrics

| Metric | Value |
|--------|-------|
| Steps | 60 / 60 |
| Examples consumed | 480 (~8.2 epochs over 117) |
| Final loss | 0.16511 |
| Min loss | 0.153 |
| Trainable params | 0.2643% |
| Peak VRAM (alloc) | 17,525.6 MiB |
| Throughput (mean) | 71.76 tokens/s |
| Wall time | 2,827 s (~47 min) |
| Adapter SHA-256 | `e3760444e002c87364cb2a572b37bc49b703ad558d55f14a8e5be13e7505cd76` |

---

## 3. Evaluation — QEE v2 on math_eval_v1 (N=100)

| Metric | Baseline (no LoRA) | M1 post-training | Δ |
|--------|--------------------|------------------|---|
| **Correctness** | 0.7779 | **0.8755** | **+0.0976** |
| Reasoning quality | 0.8557 | 0.8557 | 0.0000 |
| Hallucination rate | 0.22 | 0.12 | −0.10 |
| Format consistency | 1.00 | 0.97 | −0.03 |

### 3.1 Per-example delta

- **Improved:** 17 / 100
- **Regressed:** 7 / 100
- **Unchanged:** 76 / 100
- Mean delta: **+0.0975**

### 3.2 Regression analysis (7 records)

| record_id | Baseline | Post | Method | Cause |
|-----------|----------|------|--------|-------|
| `expert_math_000221` | 1.0 | 0.0 | numeric_sampling | final value not extracted |
| `expert_math_001820` | 1.0 | 0.0 | no_final_answer | no final answer emitted |
| `expert_math_002137` | 1.0 | 0.0 | unparsable | answer `$600` unparsed |
| `expert_math_002375` | 0.0417 | 0.0385 | unparsable | negligible drift (both near-0) |
| `expert_math_002426` | 1.0 | 0.0 | no_final_answer | no final answer emitted |
| `expert_math_002689` | 1.0 | 0.0 | unparsable | final answer not boxed/parseable |
| `expert_math_002844` | 1.0 | 0.0 | unparsable | final answer not boxed/parseable |

All 6 meaningful regressions are **correct-in-baseline records that the LoRA
adapter now answers without a parseable final answer** (`no_final_answer` /
`unparsable`) — a **format collapse**, not a reasoning loss. The reasoning text
is present but the final answer is missing/malformed. This is the expected
overfitting signature on a 117-record set at ~8.2 epochs.

---

## 4. Required artifacts (all present)

| Artifact | Path |
|----------|------|
| config.json | `experiments/phase7_scale/atlas-math-small-qwen7b-lora-scale-m1/config.json` |
| dataset_manifest.json | `.../dataset_manifest.json` (checksum match) |
| hardware_info.json | `.../hardware_info.json` |
| training_log.json | `.../training_log.json` |
| step_metrics.csv | `.../training_log/step_metrics.csv` |
| adapter + checksum | `.../checkpoints/` + `adapter_sha256.txt` |
| evaluation report | `.../evaluation/post_training.json` + `comparison_metrics.json` |
| baseline comparison | `.../evaluation/comparison_metrics.json` (delta +0.0976) |

---

## 5. Reproducibility

Checksum gate passed pre-training; seed 42; deterministic ordering; artifacts
all recorded. **Reproducibility check: PASS** (no HOLD).

---

## 6. Stop — result summary

M1 (117 records) improves math correctness on `math_eval_v1` by **+0.098**
(0.778 → 0.876), reduces hallucination (0.22 → 0.12), with 6 format regressions
on already-correct records (overfit signature at ~8 epochs). **Proceeding to M2
requires the next approved step.** Human approval is requested before the M2 run
per the execution protocol.
