# P8-A Evaluation Report — Math → Code Cross-Domain Transfer

> **Phase:** 8, Experiment A (P8-A)
> **Experiment ID:** `atlas-math-small-qwen7b-lora-transfer-v1`
> **Research Question (RQ1):** Does math-domain instruction tuning improve
> code evaluation performance?
> **Status:** COMPLETE — training and code evaluation executed. P8-B NOT
> started. Waiting for architecture review.
> **Date:** 2026-08-05

---

## 1. Summary

A QLoRA adapter was trained on the deterministic P8-A math training subset
(N=400) using the locked Phase 7 configuration, then evaluated **only** on the
frozen `code_eval_v1` split (N=100) with the frozen QEE v2 engine, compared
against the same-split Phase 6.3 baseline.

**Headline result: NEUTRAL cross-domain transfer.**

| Metric | Baseline | Post-training | Δ |
|--------|----------|---------------|---|
| Correctness | 0.2217 | 0.2235 | **+0.0018** |
| Reasoning quality | 0.4169 | 0.4181 | +0.0012 |
| Hallucination rate | 0.76 | 0.77 | +0.01 |
| Format consistency | 1.0 | 1.0 | 0.0 |
| N evaluated | 100 | 100 | — |

`Δ_cross^{M→C} = +0.0018` (|Δ| = 0.0018 < τ = 0.05, N=100 ≥ 30) →
**neutral transfer** (protocol v1.1 §8.3). Per-example: **22 improved, 24
regressed, 54 unchanged**.

**Transfer Ratio `TR_{M→C}`: N/A (HOLD).** `Δ_in^M` (in-domain gain on
`math_eval_v1`) was not measured because P8-A evaluation is restricted to
`code_eval_v1` only (mission scope). Fail-closed — the ratio is not fabricated.

---

## 2. Reproducibility & Versioning

| Item | Value |
|------|-------|
| Git commit (QEE v2 freeze) | `99e88e1345c8e08092e9e63b44013f8f7086f3bb` (`99e88e1`) |
| Parent commit | `d1fb931` |
| QEE v2 engine | `scripts/evaluation_engine/v2` @ `99e88e1` (frozen, committed before training) |
| Base model / revision | `Qwen/Qwen2.5-7B-Instruct` / `a09a35458c702b33eeacc393d103063234e8bc28` |
| Training subset | `experiments/phase8_transfer/subsets/P8A_math_train.jsonl` (N=400) |
| Subset SHA-256 | `55e15fda53c16a9c10dc6de23e5ead069c97bbb730fb5a43b55bf1c453b6bbc0` |
| Subset records SHA-256 | `d31af8214f0573dc8183e173d0379e835bf40a0ab6d0702a7a1d047a647ee9af` |
| Target eval split | `evaluation/eval_sets/phase6_expansion_v1/code_eval_v1.jsonl` (N=100) |
| Eval split SHA-256 | `37b9c42a9b6aa514f602ad0d90e1d4c9ec243625d6f34774c41066de6fdf6b1b` |
| Eval records SHA-256 | `8ff09120446b5c87f94b2acde6aefb29255015be0bb8c3d23c05e900457c4c67` |
| Seed | 42 |
| Hardware | NVIDIA GeForce RTX 5070 12 GB (devpc Ubuntu-24.04), torch 2.13.0+cu130 |
| Adapter SHA-256 | `8853ecc251d04b262d50a20c34ef0df89a49e575bbe99d01128040a9689c85c2` |
| Experiment manifest | `experiments/atlas-math-small-qwen7b-lora-transfer-v1/experiment_manifest.json` |

### 2.1 Gates verified before training

- [x] Dataset checksum — subset raw-file SHA-256 matched manifest.
- [x] Evaluation checksum — `code_eval_v1` file + records checksums matched.
- [x] Deterministic subset — builder re-run produced identical hashes; leakage
      audit clean (no overlap with `math_eval_v1`, `code_eval_v1`, tv-eval).
- [x] Frozen artifact integrity — no tracked modification of `curated/`,
      `raw/`, `training_views/`, `review_queue/`; QEE v2 unchanged and committed.
- [x] Same-split baseline — Phase 6.3 baseline on the exact `code_eval_v1`
      split with identical inference config (greedy, NF4+bf16, max_new_tokens 512).

---

## 3. Training

| Parameter | Value |
|-----------|-------|
| Records | 400 (P8-A math subset) |
| Steps / effective batch | 60 / 8 (batch 1, grad accum 8) |
| Final loss / min loss | 0.29998 / 0.20346 |
| Peak VRAM (allocated) | 17,532 MiB (reserved 20,492 MiB) |
| Throughput | 162.4 tok/s mean |
| Wall time | 1,649 s (~27.5 min) |
| Config | Locked Phase 7 (NF4+double-quant+bf16, LoRA r=8 α=16, lr 2e-4 cosine, warmup 0.03, seed 42, paged_adamw_8bit) |

Training reproduced the validated configuration: `checksum_match=true`,
`model_revision` matched, seed applied. Adapter saved to `checkpoints/`.

---

## 4. Baseline Comparison & Transfer Delta

Same-split comparison on `code_eval_v1` (N=100), frozen QEE v2:

| Metric | Baseline (Phase 6.3) | Post-training (P8-A) | Delta |
|--------|----------------------|----------------------|-------|
| Correctness | 0.2217 | 0.2235 | +0.0018 |
| Reasoning quality | 0.4169 | 0.4181 | +0.0012 |
| Hallucination rate | 0.76 | 0.77 | +0.01 |
| Answer format consistency | 1.0 | 1.0 | 0.0 |

**Transfer delta** `Δ_cross^{M→C}` (correctness) = **+0.0018**.
The effect is statistically tiny and within the neutral band.

---

## 5. Per-Example Analysis

Per-example delta = post_correctness − baseline_correctness on the same 100
record_ids, threshold `τ = 0.05`:

| Classification | Count | Condition |
|----------------|-------|-----------|
| Improved | 22 | Δ > +0.05 |
| Regressed | 24 | Δ < −0.05 |
| Unchanged | 54 | \|Δ\| ≤ 0.05 |

### 5.1 By category

| Category | N | Mean Δ | Improved | Regressed | Unchanged |
|----------|---|--------|----------|-----------|-----------|
| algorithm reasoning | 10 | +0.1333 | 3 | 2 | 5 |
| bug fixing | 48 | −0.0056 | 12 | 11 | 25 |
| code review | 15 | −0.0157 | 3 | 5 | 7 |
| debugging | 20 | −0.0762 | 1 | 5 | 14 |
| refactoring | 7 | +0.1253 | 3 | 1 | 3 |

### 5.2 Top gains (examples)

Records where the adapter moved a code record from 0.0 → 1.0 patch similarity:
`expert_swe_000064`, `expert_swe_000133`, `expert_swe_000166`,
`expert_swe_000239`, `expert_swe_000246`, `expert_swe_000391`,
`expert_swe_000394`, `expert_swe_000409`, `expert_swe_000456` (all Δ=+1.0),
`expert_swe_000287` (Δ=+0.9231).

### 5.3 Top regressions (examples)

Records where the adapter moved a code record from 1.0 → 0.0:
`expert_swe_000051`, `expert_swe_000085`, `expert_swe_000091`,
`expert_swe_000101`, `expert_swe_000114`, `expert_swe_000160`,
`expert_swe_000251`, `expert_swe_000275`, `expert_swe_000308` (all Δ=−1.0),
`expert_swe_000018` (Δ=−0.8).

Full per-example deltas: `analysis/p8a_per_example_deltas.jsonl`.

---

## 6. Transfer Type Classification

Protocol v1.1 §8.3 with `τ = 0.05`, target eval `N=100` (≥ 30):

- `Δ_cross^{M→C} = +0.0018`, `|Δ| = 0.0018 < 0.05`
- Per-example improved (22) ≤ regressed (24)

**Verdict: NEUTRAL transfer.** Math-domain instruction tuning produced no
measurable effect on code evaluation performance within the QEE v2 metric.

> RQ1 answer: **No** — under this configuration and metric, math-domain
> instruction tuning does not improve code evaluation performance. The effect
> is indistinguishable from zero (neutral), with a slight, non-significant
> positive aggregate and mixed per-example movement.

---

## 7. Transfer Ratio

`TR_{M→C} = Δ_cross^{M→C} / Δ_in^M`

| Field | Value |
|-------|-------|
| Δ_cross^{M→C} | +0.0018 |
| Δ_in^M | **not measured** (evaluation restricted to `code_eval_v1` per mission) |
| TR | **N/A (HOLD)** |

`Δ_in^M` requires post-training evaluation on `math_eval_v1`, which is outside
the authorized P8-A evaluation scope. Per protocol §8.2, the ratio is undefined
when the denominator is unavailable; it is recorded `N/A` (HOLD) and not
fabricated.

---

## 8. Regression Analysis

| Metric | Value |
|--------|-------|
| Regressed count | 24 / 100 |
| Mean Δ of regressed records | −0.655 |
| Maximum single regression | −1.0 (1.0 → 0.0 patch similarity) |
| Mean Δ by difficulty | diff 2: +0.0613; diff 3: −0.0425; diff 4: 0.0; diff 5: +0.0399 |

Regressions concentrate in **debugging** (mean Δ −0.0762, 5 regressed) and
**code review** (mean Δ −0.0157). Difficulty-3 records show the largest mean
regression (−0.0425). The ~±1.0 swings (0↔1) indicate patch-similarity scoring
is sensitive to exact patch content: a model that produces a plausible but
incorrect patch scores 0.

---

## 9. Final Answer Reliability (code)

| Metric | Value |
|--------|-------|
| Scoring method distribution | `patch`: 100/100 |
| Patch / similarity production fraction | 1.0 |
| Answer format consistency | 1.0 |

Every post-training response was scored via the **patch added-line similarity**
method — no empty or syntax-failure responses. The adapter reliably emits
patch-formatted answers. Note: for code the QEE v2 "correctness" is patch
similarity, not final-answer extraction; format consistency (1.0) and patch
production (1.0) are the reliability proxies. "Final answer reliability" as
used for math (extraction) does not apply to code.

---

## 10. Interpretation & Caveats

1. **Neutral transfer is scoped and honest.** With `Δ_cross=+0.0018` and
   improved≈regressed, no cross-domain capability gain is claimable.
2. **`TR` is HOLD**, not 0 or negative — the denominator was not measured.
3. **Metric sensitivity:** patch added-line similarity is binary-ish; small
   patch deviations flip scores 0↔1, inflating per-example movement counts.
4. **QEE bias caveat:** conclusions use deltas vs the same-split baseline, not
   absolute scores (threat T5).
5. **Single seed / single run** — no variance estimate; a seed sweep would be
   required before any stronger symmetry claim (threat T8).
6. **Symmetry (RQ5) is out of scope for P8-A** — it requires P8-B (Code→Math).

---

## 11. Rules Compliance

- [x] No dataset, frozen view, or QEE engine modified.
- [x] No hyperparameter change from the locked Phase 7 configuration.
- [x] Evaluation on `code_eval_v1` ONLY (N=100), frozen QEE v2.
- [x] P8-B NOT started.
- [x] Stopped after P8-A evaluation; waiting for architecture review.

---

## 12. Artifacts

| Artifact | Path |
|----------|------|
| Experiment manifest | `experiments/atlas-math-small-qwen7b-lora-transfer-v1/experiment_manifest.json` |
| Config | `experiments/atlas-math-small-qwen7b-lora-transfer-v1/config.json` |
| Training log | `experiments/atlas-math-small-qwen7b-lora-transfer-v1/training_log.json` |
| Step metrics | `experiments/atlas-math-small-qwen7b-lora-transfer-v1/training_log/step_metrics.csv` |
| Adapter | `experiments/atlas-math-small-qwen7b-lora-transfer-v1/checkpoints/` |
| Post-training aggregate | `experiments/atlas-math-small-qwen7b-lora-transfer-v1/evaluation/post_training.json` |
| Post-training per-example | `experiments/atlas-math-small-qwen7b-lora-transfer-v1/evaluation/post_training_per_example.jsonl` |
| Adapter metadata | `experiments/atlas-math-small-qwen7b-lora-transfer-v1/evaluation/adapter_metadata.json` |
| Transfer analysis | `experiments/atlas-math-small-qwen7b-lora-transfer-v1/analysis/p8a_transfer_analysis.json` |
| Per-example deltas | `experiments/atlas-math-small-qwen7b-lora-transfer-v1/analysis/p8a_per_example_deltas.jsonl` |
