# Scaling Run M3 — Report (Phase 7.2)

> **Experiment:** `atlas-math-small-qwen7b-lora-scale-m3`
> **Phase:** 7.2
> **Status:** COMPLETED
> **Date:** 2026-08-05
> **Scope:** Math-domain capability only. No unsupported intelligence claims.

---

## 1. Run identity (reproducibility)

| Field | Value |
|-------|-------|
| Subset | `experiments/phase7_scale/subsets/M3_math_train.jsonl` (1000 records) |
| Subset SHA-256 | `c1bddd4c566da11b9a694fd29bb7d288bf0bd7e6e247a7bf6aae5b07b1dec3af` |
| Checksum match | ✅ true (verified before training, fail-closed) |
| Base model | `Qwen/Qwen2.5-7B-Instruct` |
| Model revision | `a09a35458c702b33eeacc393d103063234e8bc28` |
| Git commit | `d1fb9310c37d5e119327f3baa45f89cab2d4c5b0` |
| Seed | 42 |
| Config | locked Phase 7.2 config (`config.json`) |
| Eval set | `math_eval_v1` (N=100) |
| Nesting | M1 ⊂ M2 ⊂ M3 (verified in Phase 7.1 audit) |

---

## 2. Training metrics

| Metric | Value |
|--------|-------|
| Steps | 60 / 60 |
| Examples consumed | 480 (~0.48 epochs over 1000) |
| Final loss | 0.27717 |
| Min loss | 0.22757 |
| Trainable params | 0.2643% |
| Peak VRAM (alloc) | 17,546.9 MiB |
| Throughput (mean) | 53.10 tokens/s |
| Wall time | 3,847 s (~64 min) |
| Adapter SHA-256 | `f20572e727e8a6d848457bd87ce3627da3145da4ba116bfa11e06e69c970592a` |

Note: final loss (0.277) is the highest of the three — M3's 1000 records are
seen ~0.48 epochs (fewest epochs of the series), the expected consequence of
holding the step count fixed while growing the dataset.

---

## 3. Evaluation — QEE v2 on math_eval_v1 (N=100)

| Metric | Baseline (no LoRA) | M3 post-training | Δ |
|--------|--------------------|------------------|---|
| **Correctness** | 0.7779 | **0.9280** | **+0.1501** |
| Reasoning quality | 0.8557 | 0.8959 | +0.0402 |
| Hallucination rate | 0.22 | 0.06 | −0.16 |
| Format consistency | 1.00 | 1.00 | 0.00 |

### 3.1 Per-example delta

- **Improved:** 19 / 100
- **Regressed:** 2 / 100
- **Unchanged:** 79 / 100
- Mean delta: **+0.1500**

### 3.2 Regression analysis (2 records)

| record_id | Baseline | Post | Method | Cause |
|-----------|----------|------|--------|-------|
| `expert_math_001277` | 1.0 | 0.0 | number | **Reasoning error**: wrong digit-sum total (partial computation, not 7456) |
| `expert_math_002578` | 1.0 | 0.25 | unparsable | **Format regression**: correct answer `48` produced but not boxed → not extracted |

M3 has **no format-collapse** (format consistency 1.0 overall). It has 1 genuine
reasoning regression (`001277`) and 1 format regression where the *correct*
answer was emitted unboxed (`002578`).

---

## 4. Required artifacts (all present)

| Artifact | Path |
|----------|------|
| config.json | `experiments/phase7_scale/atlas-math-small-qwen7b-lora-scale-m3/config.json` |
| dataset_manifest.json | `.../dataset_manifest.json` (checksum match, n=1000) |
| hardware_info.json | `.../hardware_info.json` |
| training_log.json | `.../training_log.json` |
| step_metrics.csv | `.../training_log/step_metrics.csv` |
| adapter + checksum | `.../checkpoints/` + `adapter_sha256.txt` |
| evaluation report | `.../evaluation/post_training.json` + `comparison_metrics.json` |
| baseline comparison | `.../evaluation/comparison_metrics.json` (delta +0.1501) |

---

## 5. Reproducibility

Checksum gate passed pre-training; seed 42; deterministic ordering; artifacts
all recorded. **Reproducibility check: PASS** (no HOLD).

---

## 6. Stop — result summary

M3 (1000 records) improves math correctness on `math_eval_v1` by **+0.150**
(0.778 → 0.928), the best result of the series, hallucination cut to 0.06, no
format collapse. Two regressions: 1 genuine reasoning error (`001277`) and 1
format regression where the correct answer (`48`) was emitted unboxed
(`002578`).

**All three scaling runs (M1/M2/M3) are complete.** Proceeding to the final
cross-run scaling report.
