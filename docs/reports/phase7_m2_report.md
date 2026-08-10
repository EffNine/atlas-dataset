# Scaling Run M2 — Report (Phase 7.2)

> **Experiment:** `atlas-math-small-qwen7b-lora-scale-m2`
> **Phase:** 7.2
> **Status:** COMPLETED
> **Date:** 2026-08-04
> **Scope:** Math-domain capability only. No unsupported intelligence claims.

---

## 1. Run identity (reproducibility)

| Field | Value |
|-------|-------|
| Subset | `experiments/phase7_scale/subsets/M2_math_train.jsonl` (500 records) |
| Subset SHA-256 | `ba0f1c84eaeb2f4bc4f06c2793891fffba72e73b91611e22a17d1f4f1e8904cd` |
| Checksum match | ✅ true (verified before training, fail-closed) |
| Base model | `Qwen/Qwen2.5-7B-Instruct` |
| Model revision | `a09a35458c702b33eeacc393d103063234e8bc28` |
| Git commit | `d1fb9310c37d5e119327f3baa45f89cab2d4c5b0` |
| Seed | 42 |
| Config | locked Phase 7.2 config (`config.json`) |
| Eval set | `math_eval_v1` (N=100) |
| Nesting | M1 ⊂ M2 (verified in Phase 7.1 audit) |

---

## 2. Training metrics

| Metric | Value |
|--------|-------|
| Steps | 60 / 60 |
| Examples consumed | 480 (~0.96 epochs over 500) |
| Final loss | 0.28892 |
| Min loss | 0.19887 |
| Trainable params | 0.2643% |
| Peak VRAM (alloc) | 17,526.8 MiB |
| Throughput (mean) | 93.74 tokens/s |
| Wall time | 2,260 s (~38 min) |
| Adapter SHA-256 | `93fbce47427cb01f82a9f948167043cf0544bc4c6e46ed0659fd90a5c3e674d6` |

Note: final loss (0.289) is higher than M1 (0.165) because M2's 500 records are
seen only ~1 epoch (vs ~8 epochs for M1) — the expected consequence of holding
the step count fixed while growing the dataset.

---

## 3. Evaluation — QEE v2 on math_eval_v1 (N=100)

| Metric | Baseline (no LoRA) | M2 post-training | Δ |
|--------|--------------------|------------------|---|
| **Correctness** | 0.7779 | **0.9250** | **+0.1471** |
| Reasoning quality | 0.8557 | 0.8938 | +0.0381 |
| Hallucination rate | 0.22 | 0.06 | −0.16 |
| Format consistency | 1.00 | 1.00 | 0.00 |

### 3.1 Per-example delta

- **Improved:** 17 / 100
- **Regressed:** 1 / 100
- **Unchanged:** 82 / 100
- Mean delta: **+0.1471**

### 3.2 Regression analysis (1 record)

| record_id | Baseline | Post | Method | Cause |
|-----------|----------|------|--------|-------|
| `expert_math_002244` | 1.0 | 0.0 | number | **Reasoning error**: answered `200%` instead of correct `36%` (solved a different cubic equation). Parseable but wrong. |

M2 has **zero format regressions** (format consistency 1.0) — the format
collapse seen in M1 is gone at 500 records. The single regression is a genuine
reasoning error on one record.

---

## 4. Required artifacts (all present)

| Artifact | Path |
|----------|------|
| config.json | `experiments/phase7_scale/atlas-math-small-qwen7b-lora-scale-m2/config.json` |
| dataset_manifest.json | `.../dataset_manifest.json` (checksum match, n=500) |
| hardware_info.json | `.../hardware_info.json` |
| training_log.json | `.../training_log.json` |
| step_metrics.csv | `.../training_log/step_metrics.csv` |
| adapter + checksum | `.../checkpoints/` + `adapter_sha256.txt` |
| evaluation report | `.../evaluation/post_training.json` + `comparison_metrics.json` |
| baseline comparison | `.../evaluation/comparison_metrics.json` (delta +0.1471) |

---

## 5. Reproducibility

Checksum gate passed pre-training; seed 42; deterministic ordering; artifacts
all recorded. **Reproducibility check: PASS** (no HOLD).

---

## 6. Stop — result summary

M2 (500 records) improves math correctness on `math_eval_v1` by **+0.147**
(0.778 → 0.925), the best result so far, with hallucination cut to 0.06 and
**no format regressions**. One genuine reasoning regression (`002244`: 200% vs
36%). **Proceeding to M3 requires the next approved step.**
