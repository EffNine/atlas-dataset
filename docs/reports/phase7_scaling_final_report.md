# Controlled Math Scaling — Final Report (Phase 7.2)

> **Phase:** 7.2
> **Status:** COMPLETE — all three scaling runs (M1/M2/M3) executed + evaluated
> **Date:** 2026-08-05
> **Scope:** Math-domain capability only. No unsupported intelligence claims.
> **Human approval:** granted to proceed (Phase 7.2). Human approval remains
> mandatory for any downstream use/release.

---

## 1. Design (locked)

- Base model `Qwen/Qwen2.5-7B-Instruct` (rev `a09a3545…`), NF4 double-quant +
  bf16, LoRA r=8/α=16 on 7 modules, `paged_adamw_8bit` 2e-4 cosine, batch 8,
  seq 1024, **60 steps**, **seed 42**.
- Only training-subset size varies: **M1=117 ⊂ M2=500 ⊂ M3=1000** (nested,
  verified in Phase 7.1 audit; staged under `experiments/phase7_scale/subsets/`).
- Eval: `math_eval_v1` (N=100), QEE v2, greedy, max_new_tokens 512.
- Every run: checksum gate (fail-closed), config, dataset manifest, hardware
  info, training log, step metrics, adapter checksum, eval report, baseline
  comparison — all recorded.

---

## 2. Training summary

| Run | Records | Epochs | Final loss | Min loss | Throughput (t/s) | Wall time | Adapter SHA (first 8) |
|-----|---------|--------|-----------|----------|------------------|-----------|------------------------|
| M1 | 117 | ~8.2 | 0.165 | 0.153 | 71.8 | ~47 min | `e3760444` |
| M2 | 500 | ~0.96 | 0.289 | 0.199 | 93.7 | ~38 min | `93fbce47` |
| M3 | 1000 | ~0.48 | 0.277 | 0.228 | 53.1 | ~64 min | `f20572e7` |

Step count held constant → larger sets get fewer epochs (this is the scaling
signal). Loss rises with size as expected.

---

## 3. Evaluation — QEE v2 on math_eval_v1 (N=100)

| Metric | Baseline | M1 (117) | M2 (500) | M3 (1000) |
|--------|----------|----------|----------|-----------|
| **Correctness** | 0.7779 | 0.8755 | **0.9250** | **0.9280** |
| Reasoning quality | 0.8557 | 0.8557 | 0.8938 | 0.8959 |
| Hallucination rate | 0.22 | 0.12 | 0.06 | 0.06 |
| Format consistency | 1.00 | 0.97 | 1.00 | 1.00 |
| **Δ correctness vs baseline** | — | +0.098 | +0.147 | **+0.150** |

### 3.1 Per-example classification

| Run | Improved | Regressed | Unchanged | Mean delta |
|-----|----------|-----------|-----------|------------|
| M1 | 17 | 7 | 76 | +0.0975 |
| M2 | 17 | 1 | 82 | +0.1471 |
| M3 | 19 | 2 | 79 | +0.1500 |

### 3.2 Regression detail

| Run | Record | Baseline→Post | Method | Type |
|-----|--------|---------------|--------|------|
| M1 | 6 records (000221, 001820, 002137, 002426, 002689, 002844) | 1.0→0.0 | no_final_answer / unparsable | **format collapse** (overfit @ ~8 epochs) |
| M1 | 002375 | 0.042→0.039 | unparsable | negligible (both ≈0) |
| M2 | 002244 | 1.0→0.0 | number | **reasoning error** (200% vs 36%) |
| M3 | 001277 | 1.0→0.0 | number | **reasoning error** (wrong digit-sum) |
| M3 | 002578 | 1.0→0.25 | unparsable | format (correct `48` emitted unboxed) |

---

## 4. Research-question answers (math-only)

**RQ1 — Does dataset size correlate with capability improvement?**
Yes, but with diminishing returns. Correctness rises
0.778 → 0.876 (M1) → 0.925 (M2) → 0.928 (M3). The jump from 117→500 records
(+0.049) is much larger than 500→1000 (+0.003). The trend saturates near 0.93
on this eval set within the tested range.

**RQ2 — What is the minimum useful dataset size?**
M1 (117 records) already exceeds baseline by +0.098 and meets the Phase 7.0
success criterion (+0.05), so the minimum useful size is **≤ 117** for this
domain/task. M2 (500) is the point of maximum marginal gain; beyond it gains
plateau.

**RQ3 — Does scaling reduce overfitting?**
Yes. M1 (8.2 epochs) shows **format collapse** (7 regressions, format
consistency 0.97). M2 (0.96 epochs) and M3 (0.48 epochs) have **no format
collapse** (format consistency 1.0) and only 1-2 genuine reasoning errors each.
Fewer epochs per record on a larger, more diverse set reduces the 
memorize-then-truncate-format failure mode.

---

## 5. Success criteria (Phase 7.0 §6) — status

| Criterion | Status |
|-----------|--------|
| Improvement over baseline ≥ +0.05 on the two largest sizes | ✅ M2 +0.147, M3 +0.150 |
| No regression beyond documented/justified change | ✅ regressions documented; no baseline-correct record lost in a larger size beyond the listed cases |
| Reproducible run (checksums, seed 42, determinism) | ✅ all three runs PASS; no HOLD |

**All success criteria met.**

---

## 6. Recommendation

1. **Scaling conclusion (math):** 500 records is the practical sweet spot for
   this task/config; 1000 adds negligible gain on this eval split. Recommend
   M2-scale (≈500) as the default budget for math-domain LoRA on this base
   model unless a harder eval split shows the curve continuing.
2. **Config note:** 60 steps at batch 8 is a fixed-schedule design; an
   epoch-matched or early-stopped schedule might shift these conclusions. This
   is a documented design choice, not a change to locked variables.
3. **Do not claim general intelligence:** results are math-domain only.
4. **Human approval remains mandatory** for any release or training decision
   based on these results. These adapters are research artifacts; no automated
   gating is authorized.

---

## 7. Artifacts

| Run | Dir |
|-----|-----|
| M1 | `experiments/phase7_scale/atlas-math-small-qwen7b-lora-scale-m1/` |
| M2 | `experiments/phase7_scale/atlas-math-small-qwen7b-lora-scale-m2/` |
| M3 | `experiments/phase7_scale/atlas-math-small-qwen7b-lora-scale-m3/` |
| Reports | `docs/reports/phase7_m1_report.md`, `phase7_m2_report.md`, `phase7_m3_report.md` |
| Frozen views / Phase 5B.1 artifacts | untouched (checksums verified) |
