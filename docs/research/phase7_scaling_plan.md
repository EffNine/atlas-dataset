# Atlas Scaling Experiments Plan — Phase 7.0

> **Phase:** 7.0 (Experiment Lock)
> **Status:** Planning — **NO training is scheduled or authorized by this plan.**
> **Date:** 2026-08-04
> **Scope:** Defines the dataset-scaling experiment matrix that will measure how
> Atlas training-data size affects math capability. Documentation only.

---

## 1. Purpose

Lock the experimental design for Atlas dataset-scaling runs. The plan fixes all
variables except **training dataset size**, so any observed capability change
can be attributed to data size. It inherits the Research Protocol v1.0
(`docs/research/experiment_protocol_v1.md`) for naming, metadata,
reproducibility, and success/failure criteria, and the benchmark schedule
(`docs/research/benchmark_plan.md`) for tiers.

### 1.1 Constraints

- **No training** is performed under this phase. This document only specifies
  the design for approved future runs.
- **No dataset / training-view modification.** Experiments draw from the
  existing approved source pool; nothing frozen is altered.
- Fixed variables are identical to the validated Phase 5B.1 math LoRA pilot.

---

## 2. Research Questions

| # | Question | How it is answered |
|---|----------|--------------------|
| RQ1 | Does dataset size correlate with capability improvement? | Compare QEE v2 math correctness across M0→M3 on the identical eval split; fit a monotone trend and report per-size means and deltas. |
| RQ2 | What is the minimum useful dataset size? | Locate the smallest size at which post-training correctness exceeds baseline (M0 baseline = no-LoRA) with a non-trivial margin (≥ +0.05 correctness) and stable per-sample scores. |
| RQ3 | Does scaling reduce overfitting? | Track train loss vs eval correctness per size. Overfit signal = low train loss with flat/declining eval. Report the train/eval gap at each size and the eval-per-step curve. |

Answers are scoped to **math capability only**. No general-intelligence claim is
made (protocol §5).

---

## 3. Fixed Variables (locked)

Identical across all experiments and equal to the validated Phase 5B.1 math
pilot:

| Variable | Locked value |
|----------|--------------|
| Base model | `Qwen/Qwen2.5-7B-Instruct` |
| Model revision | `a09a35458c702b33eeacc393d103063234e8bc28` |
| Tokenizer | Qwen2.5 tokenizer (`use_fast=True`), pad = eos |
| Quantization | NF4 4-bit + double quant, bf16 compute |
| LoRA | r=8, alpha=16, dropout=0.05, bias=none, task=CAUSAL_LM |
| LoRA target modules | `q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj` |
| Optimizer | `paged_adamw_8bit` |
| LR / schedule | 2e-4, cosine, warmup 0.03 |
| Batch | batch=1, grad accum=8 (effective 8) |
| Weight decay / grad norm | 0.01 / 1.0 |
| Max seq length | 1024 |
| **Seed** | **42** |
| **Evaluator version** | QEE v2 `scripts/evaluation_engine/v2` at repo commit `d1fb931` with Phase 5A.4 (nested-brace) + Phase 6.4 (percentage/unit/format) patches |
| Eval split | `evaluation/eval_sets/phase6_expansion_v1/math_eval_v1.jsonl` (N=100) |
| Hardware | NVIDIA RTX 5070 12 GB (devpc) |

### 3.1 Single-variable rule

Only **training-view record count** varies. All other inputs (model, config,
seed, evaluator, eval split, prompt format, max_new_tokens=512) are fixed.
`max_steps` is held constant at 60 (identical schedule); therefore larger sets
receive **fewer epochs per record**, which is the intended scaling signal. This
differs from the Phase 5B.1 pilot schedule note and is documented here as the
scaling design choice.

---

## 4. Experiments

Naming follows the protocol: `atlas-{family}-{tier}-{target}-{scope}-v{n}` →
`atlas-math-small-qwen7b-lora-scale-v1` per size cell.

| ID | Training records | Source | Tier | Approx. epochs (60 steps × 8) |
|----|------------------|--------|------|-------------------------------|
| M0 | **0** (no-LoRA baseline) | — | pilot | — |
| M1 | **117** | `math_300m_v0.1/train.jsonl` | small | ~4.1 |
| M2 | **500** | `expert-pilot-6500` math subset | small | ~0.96 |
| M3 | **1000** | `expert-pilot-6500` math subset | medium | ~0.48 |

### 4.1 Feasibility note (M3 target)

The requested M3 size is **5000 records**, but the available math source pool is
**3000 records** (`expert-math-002`; all `needs_review`, `curated=false`).
Therefore:

- **M3 is defined as 1000 records here** (the largest size with headroom to hold
  out a disjoint eval split from the same source).
- A 5000-record run would require either (a) additional approved math sources
  beyond `expert-math-002`, or (b) an explicit governance decision to mix
  domains, which is outside this plan's single-variable scope.
- The eval split (`math_eval_v1`, N=100) is disjoint from M1's 117 train
  records; M2/M3 subsets must also exclude the 100 eval record IDs.

### 4.2 Dataset construction (per size, deterministic)

1. Start from the full `expert-pilot-6500` math pool (3000).
2. **Exclude** the 100 `math_eval_v1` record IDs (eval disjointness).
3. **Exclude** REJECT-reviewed records (governance).
4. Order remaining records deterministically by `sha256("phase7-scale-v1:{record_id}")`
   and take the first N records (500, 1000). M1 uses the existing 117-record
   training view verbatim.
5. Write each subset to `output/training_views/` **only if an approved,
   separate scaling view is created**; otherwise stage under
   `experiments/phase7_scale/` and never touch frozen views. (Protocol rule: no
   modification of frozen `*_300m_v0.1` views.)

---

## 5. Required Artifacts (per experiment)

Each scaling run MUST produce all of the following (per Research Protocol §3–4),
stored under `experiments/atlas-math-small-qwen7b-lora-scale-v1/{M1,M2,M3}/`:

| Artifact | Contents |
|----------|----------|
| **Dataset checksum** | SHA-256 of the training subset (raw file) + manifest records checksum; `checksum_match=true` |
| **Training config** | full config JSON (quantization, LoRA, optimizer, schedule, seed) |
| **Hardware info** | GPU name, VRAM, driver, torch/transformers/peft/bnb versions |
| **Training log** | `training_log.json` + `step_metrics.csv` (loss, lr, VRAM, tokens/s, wall time) |
| **Adapter checksum** | SHA-256 of `adapter_model.safetensors` (or per-file manifest) |
| **QEE evaluation report** | per-example + aggregate QEE v2 math scores on `math_eval_v1` (N=100) |
| **Baseline comparison** | same-split baseline (M0) metrics + per-size deltas |

Reproducibility: given the fixed inputs above, any qualified researcher can
regenerate each run (protocol checklist items 1–15).

---

## 6. Success Criteria

An experiment passes when ALL hold (protocol §5–6):

1. **Improvement over baseline (M0):** post-training math correctness on
   `math_eval_v1` > M0 correctness by ≥ **+0.05** for at least the two largest
   feasible sizes (M2, M3); M1 may be directional only.
2. **No regression:** no eval record that is correct in the baseline becomes
   incorrect in a larger-size run beyond a documented, justified change; the
   per-family correct-count must not drop vs the immediately smaller size.
3. **Reproducible run:** all §5 artifacts present, checksums match, seed 42,
   determinism spot-check green, and the run passes the protocol checklist.

### 6.1 Decision rules for RQ2 (minimum useful size)

- **Minimum useful size** = the smallest size whose correctness ≥ baseline + 0.05
  **and** whose per-sample correct set is stable (≥ 90% of baseline-correct
  records still correct).
- If no size reaches the threshold, the conclusion is "no minimum useful size
  within the tested range" — not a failure, a finding (fail-closed, no
  fabrication).

---

## 7. What this plan does NOT do

- **No training.** This is a locked design document only.
- **No dataset / training-view modification.**
- **No claim** of general-intelligence improvement; results are math-only.
- No automated gating; any future run still requires explicit approval and
  human-in-the-loop review per governance.

---

## 8. Versioning

| Version | Date | Change |
|---------|------|--------|
| v1.0 | 2026-08-04 | Initial lock (Phase 7.0). |
