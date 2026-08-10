# Atlas Cross-Domain Transfer Experiments Plan — Phase 8.0 (Redesign)

> **Phase:** 8.0 (Experiment Lock) — redesign v1.0
> **Status:** Planning — **NO training is scheduled or authorized by this plan.**
> **Date:** 2026-08-05
> **Scope:** Redesign of the Phase 8 cross-domain experiment. The previous
> monolithic cross-domain run is split into **four sequential experiments**
> (P8-A → P8-D), a new research question on transfer symmetry (**RQ5**) is
> added, the **Transfer Ratio** is defined, the **positive / negative / neutral
> transfer** taxonomy is specified, and **threats to validity** are documented.
> Documentation only. No training. No dataset modification.

---

## 1. Purpose

Lock the experimental design for Atlas cross-domain transfer runs. This
redesign replaces a single monolithic cross-domain run with four sequential,
single-conclusion experiments so that direction, magnitude, mixed-domain
treatment, and symmetry are isolated and measured separately (experiment matrix
rule: one experiment, one conclusion).

### 1.1 What this redesign changes

| # | Change |
|---|--------|
| 1 | Phase 8 split into four sequential experiments: **P8-A** (Math → Code), **P8-B** (Code → Math), **P8-C** (Mixed-domain), **P8-D** (Transfer Analysis). |
| 2 | New research question **RQ5 — Is transfer symmetric?** |
| 3 | **Transfer Ratio** defined: cross-domain gain / in-domain gain. |
| 4 | Transfer taxonomy defined: **positive / negative / neutral** transfer. |
| 5 | **Threats to validity** section added (mapped to risk register R22–R28). |
| 6 | Experiment matrix updated with transfer cells **T1–T4**. |
| 7 | Research Protocol v1.0 updated → **v1.1** (§8 cross-domain transfer measurement). |

### 1.2 Constraints

- **No training** is performed under this phase. This document only specifies
  the design for approved future runs.
- **No dataset / training-view modification.** Experiments draw from the
  existing approved source pool; nothing frozen is altered. All subsets are
  staged under `experiments/phase8_transfer/subsets/`.
- Fixed variables are identical to the validated Phase 5B.1 math LoRA pilot
  and the Phase 7.2 scaling runs, except for the single variable each sprint
  measures.

---

## 2. Research Questions

RQ1–RQ3 were the Phase 7.0 scaling questions (answered in the Phase 7.2 final
report, `docs/reports/phase7_scaling_final_report.md`). Phase 8 continues the
numbering.

| # | Question | How it is answered | Sprint |
|---|----------|--------------------|--------|
| **RQ4** | Does LoRA training on one Atlas domain (math or code) transfer capability to the other domain, and does mixed-domain training beat single-domain training? | Cross-domain gain Δ_cross on the target eval split vs the same-split baseline for P8-A (M→C) and P8-B (C→M); per-domain gains of the mixed adapter in P8-C; transfer-type classification per protocol §8.3. | P8-A, P8-B, P8-C |
| **RQ5** (new) | **Is cross-domain transfer symmetric?** | Compare `TR_{M→C}` vs `TR_{C→M}` in P8-D (Transfer Analysis) using the Transfer Ratio; decision rule in §7.2. | P8-D |

Answers are scoped to **math and code capability only**. No general-intelligence
claim is made (protocol §5).

---

## 3. Definitions

### 3.1 In-domain and cross-domain gain

Let `X` = source domain (trained on), `Y` = target domain (evaluated on),
`E_X` / `E_Y` the respective eval splits, and `B` the shared baseline (same base
model, same eval split, same inference config, `scope=base`).

- **In-domain gain** (source domain, source eval):
  `Δ_in^X = score(LoRA_X, E_X) − score(B, E_X)`
- **Cross-domain gain** (source domain, target eval):
  `Δ_cross^{X→Y} = score(LoRA_X, E_Y) − score(B, E_Y)`

Scores are QEE v2 metrics: **math** = extracted-answer correctness;
**code** = patch added-line similarity.

### 3.2 Transfer Ratio

```
TR_{X→Y} = Δ_cross^{X→Y} / Δ_in^X
```

| TR value | Interpretation |
|----------|----------------|
| `TR ≥ 1` | Cross-domain gain at least as large as in-domain gain (strong positive transfer). |
| `0 < TR < 1` | Positive transfer, weaker than in-domain. |
| `TR ≈ 0` | Neutral transfer (no cross-domain effect). |
| `TR < 0` | Negative transfer (training on X harms Y). |
| **N/A** | **Undefined** — recorded when `Δ_in^X ≤ 0` (non-positive denominator). Never fabricated; reported as HOLD for the ratio (fail-closed). |

Guardrails:
- `TR` is defined **only** when `Δ_in^X > 0`. Otherwise the ratio is `N/A`.
- A transfer **conclusion** requires target eval `N ≥ 30` (protocol §7).
  Below that, the result is pilot/directional only or `UNDETERMINED`.
- Ratios across directions (`TR_{M→C}` vs `TR_{C→M}`) are comparable only when
  training-set sizes are equal **and** the metrics are commensurate (see T2).

### 3.3 Transfer types

Classification of `Δ_cross^{X→Y}` uses a documented margin `τ = 0.05`
(consistent with the Phase 7.0 non-trivial margin) and the per-example
improved / regressed counts (protocol §7).

| Type | Condition (all must hold) |
|------|---------------------------|
| **Positive transfer** | `Δ_cross ≥ +τ` AND improved-count > regressed-count. |
| **Negative transfer** | `Δ_cross ≤ −τ` AND regressed-count > improved-count. |
| **Neutral transfer** | `\|Δ_cross\| < τ`. Claimable only when target eval `N ≥ 30`. |
| **UNDETERMINED** | Target eval `N < 30` or the effect is not statistically distinguishable. Recorded HOLD for the conclusion; not treated as neutral. |

---

## 4. Fixed Variables (locked)

Identical across all Phase 8 sprints and equal to the validated Phase 5B.1 /
7.2 configuration:

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
| Math eval split | `evaluation/eval_sets/phase6_expansion_v1/math_eval_v1.jsonl` (N=100) |
| Code eval split | `evaluation/eval_sets/phase6_expansion_v1/code_eval_v1.jsonl` (**N=100 as of the Phase 6.2 expansion**; P8-A evaluates on this split; benchmark_plan §5 gate met) |
| Hardware | NVIDIA RTX 5070 12 GB (devpc) |

### 4.1 Single-variable rule

- **P8-A vs P8-B (symmetry arm):** the only difference is the domain of the
  training subset. Training-set size is locked **equal** across the two
  directions: `N_math_train = N_code_train = N` (default `N = 500` per the
  Phase 7.2 M2 sweet-spot recommendation; **P8-A locks `N = 400` per the
  approved P8-A preparation, and P8-B must match**). Any divergence is a
  confound (T7).
- **P8-C (mixed):** trains on the union of the P8-A and P8-B subsets
  (`2N` records total). This intentionally changes both composition and total
  count; it is the mixed-domain treatment, documented as a threat (T6).

---

## 5. Experiments — four sequential sprints

Naming follows the protocol: `atlas-{family}-{tier}-{target}-{scope}-v{n}`.
`scope=transfer` denotes a cross-domain LoRA probe (protocol §2.1 v1.1).

| Sprint | Experiment ID | Train | Eval | Answers |
|--------|---------------|-------|------|---------|
| **P8-A** Math → Code | `atlas-math-small-qwen7b-lora-transfer-v1` | math subset (N) | `code_eval_v1` (N=100) | RQ4 direction M→C: `Δ_cross^{M→C}`, `TR_{M→C}`, type |
| **P8-B** Code → Math | `atlas-code-small-qwen7b-lora-transfer-v1` | code subset (N) | `math_eval_v1` (N=100) | RQ4 direction C→M: `Δ_cross^{C→M}`, `TR_{C→M}`, type |
| **P8-C** Mixed-domain | `atlas-mixed-small-qwen7b-lora-transfer-v1` | math N + code N (union) | `math_eval_v1` + `code_eval_v1` | RQ4 mixed vs single-domain on each domain |
| **P8-D** Transfer Analysis | `atlas-transfer-small-qwen7b-eval-v1` | — (analysis only, no training) | outputs of P8-A–P8-C | RQ5 symmetry; `TR` table; transfer-type taxonomy |

### 5.1 Sequential order and gates

```
P8-A → P8-B → P8-C → P8-D
```

| Gate | Where | Condition |
|------|-------|-----------|
| G1 | before P8-A | `code_eval_v1` expanded to N ≥ 30 (**met — N=100**); code baseline exists on the **same expanded split** (baseline-first rule; exists: `experiments/phase6_baseline_eval`, code domain). |
| G2 | before P8-B | math baseline verified on `math_eval_v1` (exists: Phase 7 M0 / `baseline_eval_v0.2`). |
| G3 | before P8-C | P8-A and P8-B completed; mixed subsets verified disjoint from both eval splits. |
| G4 | before P8-D | P8-A/P8-B/P8-C artifacts complete; `Δ_in` for each direction verified `> 0`, or the ratio recorded `N/A` (HOLD). |

Sprints P8-A and P8-B are independent training runs; the fixed order reflects the
plan, not a data dependency. Sprint P8-D depends on all three training sprints.

### 5.2 Dataset construction (per sprint, deterministic)

1. Source pools: approved math records (`expert-math`) and approved code
   records (`expert-swe`); exact approved record counts
   `[HUMAN MUST SUPPLY at approval]`.
2. **Exclude** the target eval split record IDs (train/eval disjointness).
3. **Exclude** REJECT-reviewed records (governance).
4. Order remaining records deterministically by
   `sha256("phase8-transfer-v1:{record_id}")` and take the first N records
   (default 500; **P8-A locks N = 400 per the approved P8-A preparation**),
   equal across P8-A and P8-B.
5. Sprint P8-C uses the **union** of the P8-A and P8-B subsets (`2N`).
6. Stage subsets under `experiments/phase8_transfer/subsets/`; never modify
   frozen `*_300m_v0.1` views.

### 5.3 Required artifacts (per training sprint)

Stored under `experiments/{experiment_id}/` per protocol §3–4:

| Artifact | Contents |
|----------|----------|
| Dataset checksum | SHA-256 of the training subset (raw file) + manifest records checksum; `checksum_match=true` |
| Training config | full config JSON (quantization, LoRA, optimizer, schedule, seed) |
| Hardware info | GPU name, VRAM, driver, torch/transformers/peft/bnb versions |
| Training log | `training_log.json` + `step_metrics.csv` (loss, lr, VRAM, tokens/s, wall time) |
| Adapter checksum | SHA-256 of `adapter_model.safetensors` |
| QEE evaluation report | per-example + aggregate QEE v2 scores on **both** the source and target eval splits |
| Baseline comparison | same-split baseline metrics + per-example deltas |
| **Transfer record** | `Δ_in^X`, `Δ_cross^{X→Y}`, `TR_{X→Y}` (or `N/A`), transfer type, improved/regressed/unchanged counts |

Sprint P8-D is eval/analysis-only and requires no adapter; it produces the
transfer-analysis report (TR table, symmetry verdict, taxonomy).

---

## 6. Threats to validity

| ID | Threat | Mitigation | Risk |
|----|--------|------------|------|
| T1 | Train/eval overlap → memorization masquerading as transfer | Disjoint record IDs verified per sprint (G3); no shared record_ids (protocol §6.4) | R9 |
| T2 | Incommensurable metrics: math correctness vs code patch-similarity are different scales/extractors, biasing TR comparisons across directions | Report per-metric deltas separately; normalize ratios; document scale limits; treat cross-direction TR comparison as directional, not a hard equality | R22 |
| T3 | Underpowered target eval (code N=2) invalidates any code transfer conclusion | Expand `code_eval_v1` to N ≥ 30 before Sprint P8-A (G1) — **met (N=100)**; below N=30 results are pilot/directional or UNDETERMINED | R23 |
| T4 | Evaluator extraction artifacts (nested braces, unparsable answers, format collapse) mistaken for transfer | Phase 5A.4/6.4 patches frozen; per-example review; format-consistency metric reported alongside correctness | R26 |
| T5 | QEE positive bias vs human review (+2.14) inflates absolute scores | Conclusions use **deltas vs same-split baseline**, not absolute scores; thresholds are deltas | R25-bias |
| T6 | Mixed-domain run confounds composition vs total record count (2N vs N) | Document as the mixed treatment; report per-domain breakdown; optional ablation at equal total count | R27 |
| T7 | Train-size mismatch across directions biases symmetry | Lock equal N across P8-A/P8-B (single-variable rule §4.1) | R24 |
| T8 | Single seed (42) / single model class → no variance estimate for symmetry verdict | Effect sizes + per-example distributions mandatory; optional seed sweep before claiming symmetry as robust | R25 |
| T9 | Baseline drift or engine version change between directions | Freeze QEE v2; record engine commit per run; same-split baselines (protocol §4) | R28 |
| T10 | Source-pool heterogeneity (arXiv-derived math vs SWE-bench code) confounds "domain" effect | Record source provenance per subset; keep subsets single-source; report composition | R2 |

---

## 7. Success criteria and decision rules

### 7.1 Per-sprint success

A sprint succeeds when ALL hold (protocol §5–6):

1. **Reproducibility** — protocol §4 checklist green; no HOLD on inputs.
2. **Baselines** — same-split baseline recorded for source and target eval.
3. **Deltas reported** — `Δ_in`, `Δ_cross`, per-example improved/regressed/
   unchanged counts, and transfer type (or `UNDETERMINED`).
4. **TR or N/A** — Transfer Ratio reported when `Δ_in > 0`; `N/A` (HOLD for the
   ratio) otherwise. No fabricated ratios.

### 7.2 Symmetry decision rule (RQ5, Sprint P8-D)

- If both `TR_{M→C}` and `TR_{C→M}` are defined (both `Δ_in > 0`):
  - **Symmetric** if both have the same transfer-type sign AND
    `|TR_{M→C} − TR_{C→M}| ≤ τ_sym` (default `τ_sym = 0.25`).
  - **Asymmetric** otherwise.
- If either ratio is `N/A`: symmetry is **UNDETERMINED** (HOLD), not asymmetric.
- If either direction is underpowered (`N < 30`): the symmetry verdict is
  **directional only**, not a conclusion.

### 7.3 Type decision thresholds

Per §3.3, with `τ = 0.05`. A type claim requires target eval `N ≥ 30`; below
that the claim is `UNDETERMINED`.

---

## 8. What this plan does NOT do

- **No training.** This is a locked design document only.
- **No dataset / training-view modification.**
- **No claim** of general-intelligence improvement; results are math/code-only.
- **No automated gating**; any future run still requires explicit approval and
  human-in-the-loop review per governance.
- **No commit**; this is a docs-only change pending human approval.

---

## 9. Versioning

| Version | Date | Change |
|---------|------|--------|
| v1.0 | 2026-08-05 | Initial lock (Phase 8.0 redesign): P8-A–P8-D, RQ4 + new RQ5, Transfer Ratio, positive/negative/neutral taxonomy, threats to validity. |
| v1.1 | 2026-08-05 | P8-A preparation: sprint identifiers renamed `Sprint 4A–4D` → `P8-A–P8-D`; `code_eval_v1` confirmed at N=100 (Phase 6.2 expansion, G1 met); P8-A training subset locked at N=400 (P8-B must match for symmetry). See `docs/research/p8a_math_to_code_plan.md`. |

---

## 10. References

- Research Protocol v1.1 — `docs/research/experiment_protocol_v1.md` (§8 transfer measurement)
- Experiment matrix (transfer cells T1–T4) — `docs/research/experiment_matrix.md`
- Benchmark plan — `docs/research/benchmark_plan.md` (code eval expansion gate)
- Risk register (R22–R28) — `docs/research/risk_register.md`
- Phase 7.2 final report — `docs/reports/phase7_scaling_final_report.md`
