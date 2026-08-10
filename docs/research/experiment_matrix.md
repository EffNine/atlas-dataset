# Atlas Experiment Matrix

> **Phase:** 6.1 (matrix) — revised for Phase 8.0 transfer cells
> **Status:** Adopted
> **Date:** 2026-08-05
> **Scope:** Defines the experiment families Atlas will run, the matrix of cells
> that follow the Research Protocol v1.0, and how existing pilots map onto it.
> Transfer cells T1–T4 (Phase 8.0) reference
> `docs/research/phase8_transfer_plan.md`.

---

## 1. Experiment Families

| Family | Training view(s) | QEE v2 dispatch | Primary metric | Purpose |
|--------|------------------|-----------------|----------------|---------|
| **math** | `math_300m_v0.1` | `math` | correctness (extracted final answer) | Arithmetic/stepwise reasoning capability |
| **code** | `code_300m_v0.1` | `code` | patch added-line similarity | SWE patch/diff production |
| **aiml** | `aiml_300m_v0.1` | `semantic` | semantic rubric score | AI/ML concept answer quality |
| **mixed** | ≥2 views combined | per-record dispatch | per-family correctness | Cross-domain robustness |

The matrix below lists **planned cells**. Each cell is an experiment class; a
concrete run instantiates it with the Research Protocol naming convention and
must satisfy the reproducibility checklist.

---

## 2. Matrix — Family × Training Scope × Tier

Legend for tiers: **P** = pilot, **S** = small, **M** = medium, **L** = large,
**PR** = production. `base` = baseline inference (no training), `lora` = QLoRA
adapter, `full` = full parameter finetune, `hp` = hyperparameter search,
`scale` = data-scaling study, `eval` = inference-only evaluation,
`transfer` = cross-domain LoRA probe (training on one domain, evaluating on
another; see §2.7 and `docs/research/phase8_transfer_plan.md`).

### 2.1 Math

| Cell | scope | Tiers | Inputs | Notes |
|------|-------|-------|--------|-------|
| M1 | base | P, S, M, L, PR | math_300m eval, Qwen7B | Official baseline (exists: `baseline_eval_v0.2`) |
| M2 | lora | P, S, M | math_300m train, Qwen7B | P exists: `atlas-math-pilot-qwen7b-lora-v1` |
| M3 | full | S, M | math view, target model | Full finetune; require GPU ≥ 24 GB or offload |
| M4 | hp | S | math, lora, fixed eval | LR / r / alpha / dropout grid |
| M5 | scale | S, M | 10%→100% of view | Curve of correctness vs data size |

### 2.2 Code

| Cell | scope | Tiers | Inputs | Notes |
|------|-------|-------|--------|-------|
| C1 | base | P, S, M, L, PR | code_300m eval, Qwen7B | Baseline exists; N=2 eval is underpowered |
| C2 | lora | P, S, M | code_300m train, Qwen7B | P exists: `atlas-code-pilot-qwen7b-lora-v1` |
| C3 | full | S, M | code view, target model | Requires adequate code view size |
| C4 | hp | S | code, lora, fixed eval | Hyperparameter grid |
| C5 | scale | S, M | subset of code view | Data-scaling curve |

### 2.3 AI/ML

| Cell | scope | Tiers | Inputs | Notes |
|------|-------|-------|--------|-------|
| A1 | base | P, S, M, L, PR | aiml_300m eval, Qwen7B | Baseline required before any training |
| A2 | lora | P, S, M | aiml_300m train, Qwen7B | Pending dataset adequacy check |
| A3 | full | S, M | aiml view | Full finetune |
| A4 | hp | S | aiml, lora | Hyperparameter grid |
| A5 | scale | S, M | aiml view subsets | Data-scaling curve |

### 2.4 Mixed-domain

| Cell | scope | Tiers | Inputs | Notes |
|------|-------|-------|--------|-------|
| X1 | base | P, S, M | math+code+aiml eval | Cross-family baseline aggregate |
| X2 | lora | P, S, M | combined views | Single adapter trained on combined data |
| X3 | full | S, M | combined views | Full finetune across domains |
| X4 | eval | P, S, M | all eval splits | Cross-domain generalization probe |

### 2.5 Scaling

| Cell | scope | Tiers | Inputs | Notes |
|------|-------|-------|--------|-------|
| SC1 | scale | S, M | any family view subsets | Correctness vs training-data size |
| SC2 | scale | S, M | model-size sweep | 7B vs 8B class targets (Qwen, Llama, DeepSeek) |
| SC3 | scale | S, M | step/epoch sweep | Loss and eval vs steps (overfit detection) |

### 2.6 Hyperparameter search

| Cell | scope | Tiers | Inputs | Notes |
|------|-------|-------|--------|-------|
| H1 | hp | S | any family, lora | Grid over LR, r, alpha, dropout |
| H2 | hp | S | any family, lora | Optimizer / scheduler / warmup sweep |
| H3 | hp | S | any family, lora | Quantization config sweep (NF4/int8/bf16) |

### 2.7 Cross-domain transfer (Phase 8.0)

Planned cells per `docs/research/phase8_transfer_plan.md`. `transfer` scope =
LoRA trained on one domain, evaluated on the other. Equal training-set sizes
across directions are mandatory (single-variable for the symmetry arm).

| Cell | scope | Tiers | Inputs | Notes |
|------|-------|-------|--------|-------|
| T1 | transfer | P, S | math train (N=400), code eval | **P8-A Math → Code**; requires code eval N ≥ 30 (**met — N=100**) |
| T2 | transfer | P, S | code train (N=400), math eval | **P8-B Code → Math**; uses `math_eval_v1` |
| T3 | lora | P, S | combined math+code subsets (union, 2N) | **P8-C Mixed-domain**; per-domain eval both splits |
| T4 | eval | P, S | outputs of T1–T3 | **P8-D Transfer Analysis**; no training; RQ5 symmetry verdict |

Cross-domain measurement rules (Transfer Ratio, positive/negative/neutral
taxonomy, symmetry decision rule) live in Research Protocol §8.

---

## 3. Cross-cutting rules for every cell

1. **Baseline-first:** no training cell may be run before its family's `base`
   cell exists on the same eval split.
2. **Single-variable:** a cell changes exactly one dimension from the validated
   configuration (e.g., LR, or data size, or model class) — never multiple.
3. **Eval split is never trained on:** train/eval disjointness is mandatory.
4. **One experiment, one conclusion:** each run answers one question.
5. **Matrix revision:** adding a family or scope is a matrix revision; removing
   or changing an approved cell requires this document to be updated (docs-only
   change, no code).
6. **Transfer cells (T1–T4):** target-domain baseline must exist on the exact
   eval split used; training-set sizes are locked equal across directions;
   Transfer Ratio / transfer-type reporting follows protocol §8, with `N/A`
   (HOLD) when in-domain gain is not positive.

---

## 4. Mapping of completed artifacts

| Family | scope | Existing artifact | Matrix cell |
|--------|-------|-------------------|-------------|
| math | base | `baseline_eval_v0.2` | M1-P |
| math | lora | `lora_pilot_math_v0.1` | M2-P |
| code | base | `baseline_eval_v0.2` (code rows) | C1-P |
| code | lora | `lora_pilot_code_v0.1` | C2-P |
| mixed | eval | `baseline_eval_v0.2` | X1-P |

---

## 5. Acceptance for adding a new experiment to the matrix

A new experiment may be added when:
- its `family` has a baseline (`base`) cell on the intended eval split,
- its eval split meets the protocol's minimum-N rule (default N ≥ 30, or an
  explicitly justified pilot),
- the training view exists with verified checksums,
- the full metadata/reproducibility checklist (protocol §3–4) is satisfiable.

---

## 6. Revision log

| Date | Change |
|------|--------|
| 2026-08-04 | Initial adoption (Phase 6.1). |
| 2026-08-05 | Phase 8.0 transfer cells added (§2.7, T1–T4, `transfer` scope); cross-cutting rule 6; header updated. References `docs/research/phase8_transfer_plan.md` and protocol §8.
| 2026-08-05 | Sprint identifiers renamed `Sprint 4A–4D` → `P8-A–P8-D`; T1/T2 training N updated to 400 per approved P8-A preparation (symmetry arm — P8-B matches P8-A). |
