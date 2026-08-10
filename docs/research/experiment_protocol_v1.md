# Atlas Research Protocol v1.0

> **Phase:** 6.1 (protocol v1.1 adds cross-domain transfer measurement)
> **Status:** Adopted — governs all future Atlas training/evaluation experiments
> **Date:** 2026-08-05
> **Scope:** Turns Atlas from an engineering project into a reproducible LLM
> research platform. Documentation only. No code, training, or dataset changes.

---

## 1. Purpose

Every future Atlas experiment must be **reproducible from recorded inputs alone**.
Given the same *git commit, dataset checksum, model revision, training config,
evaluation version, and random seed*, any qualified researcher must be able to
regenerate the exact experiment and obtain the same results.

This protocol codifies:
- a naming convention for experiments,
- the mandatory metadata every experiment must record,
- a reproducibility checklist every experiment must pass,
- explicit success and failure criteria.

---

## 2. Experiment Naming Convention

### 2.1 Format

```
atlas-{family}-{tier}-{target}-{scope}-v{n}
```

| Segment | Allowed values | Meaning |
|---------|----------------|---------|
| `family` | `math`, `code`, `aiml`, `mixed` | Domain family (see experiment matrix) |
| `tier` | `pilot`, `small`, `medium`, `large`, `prod` | Benchmark scale tier (see benchmark plan) |
| `target` | `qwen7b`, `llama8b`, `deepseek8b`, `mistral7b`, `gemma7b` | Target model class |
| `scope` | `base`, `lora`, `full`, `hp`, `scale`, `transfer`, `eval` | Training scope / purpose (`transfer` = cross-domain LoRA probe, Phase 8; see §8) |
| `v{n}` | `v1`, `v2`, … | Experiment iteration for identical inputs |

Examples:
- `atlas-math-pilot-qwen7b-lora-v1` — the Phase 5B.1 math LoRA pilot.
- `atlas-code-small-qwen7b-lora-v1` — a small-scale code LoRA sweep.
- `atlas-aiml-medium-llama8b-full-v1` — a medium AI/ML full-finetune run.
- `atlas-mixed-pilot-qwen7b-lora-hp-v1` — a hyperparameter-search pilot.

### 2.2 Rules

1. `family`, `tier`, and `target` are **required**; `scope` and `v{n}` are
   **required** for any training run (inference-only evaluations may use
   `scope=eval`).
2. `v{n}` increments only when inputs are identical but the run is re-attempted
   (e.g., hardware drift investigation). A change to *any* input (config,
   dataset, model, evaluator, seed) is a **new experiment**, not a new version.
3. Naming is **snake_case**, lower-case, hyphen-separated segments.
4. The experiment directory under `experiments/` uses the same identifier, e.g.
   `experiments/atlas-math-pilot-qwen7b-lora-v1/`.

### 2.3 Mapping to existing pilots

| Existing artifact | Assigned identifier |
|-------------------|---------------------|
| `experiments/lora_pilot_math_v0.1` | `atlas-math-pilot-qwen7b-lora-v1` |
| `experiments/lora_pilot_code_v0.1` | `atlas-code-pilot-qwen7b-lora-v1` |
| `experiments/baseline_eval_v0.2` | `atlas-mixed-pilot-qwen7b-eval-v1` |

---

## 3. Required Experiment Metadata

Every experiment MUST record the following in a top-level `metadata.json`
(and/or the `training_log.json`/`evaluation/*.json` artifacts) **before the run
starts and verified after it completes**.

### 3.1 Inputs (recorded pre-run)

| Field | Required | Example |
|-------|----------|---------|
| `experiment_id` | yes | `atlas-math-pilot-qwen7b-lora-v1` |
| `phase` | yes | `5B.1` |
| `git_commit` | yes | `d1fb9310c37d5e119327f3baa45f89cab2d4c5b0` |
| `git_short` | yes | `d1fb931` |
| `git_status_clean` | yes | `true` |
| `training_view_id` | yes | `math_300m_v0.1` |
| `train_jsonl_sha256` | yes | raw file SHA-256 |
| `manifest_records_sha256` | yes | approved manifest records checksum |
| `checksum_match` | yes | `true`/`false` |
| `eval_jsonl_sha256` | yes | raw eval file SHA-256 |
| `base_model` | yes | `Qwen/Qwen2.5-7B-Instruct` |
| `model_revision` | yes | Hugging Face revision SHA |
| `evaluation_engine_version` | yes | `scripts/evaluation_engine/v2` + commit |
| `seed` | yes | `42` |
| `hardware` | yes | GPU name, VRAM, driver, CUDA/torch versions |
| `training_config` | yes | full config JSON (quantization, LoRA, optimizer, schedule) |

### 3.2 Results (recorded post-run)

| Field | Required | Notes |
|-------|----------|-------|
| `status` | yes | `COMPLETED`, `FAILED`, `HOLD` |
| `training_metrics` | yes | steps, final/min loss, VRAM, throughput, wall time |
| `evaluation_results` | yes | per-example + aggregate QEE v2 scores |
| `baseline_metrics` | yes | the baseline run this experiment is compared to |
| `delta` | yes | baseline vs post-training deltas per metric |
| `artifacts` | yes | paths to adapter, logs, step metrics, eval JSONs |
| `generated_at` | yes | UTC ISO timestamp |

### 3.3 Provenance invariants

- A record with **missing or untrusted provenance** is untrusted (AGENTS rule 4).
- If any input checksum does not match its recorded value, the experiment is
  **invalid** and must not be used for conclusions until resolved.
- `checksum_match` must be verified *before* training starts; the pre-run facts
  block is written before model loading.

---

## 4. Mandatory Reproducibility Checklist

Every experiment MUST pass ALL of the following before it may be used for any
research conclusion. This is the release gate for a research result.

| # | Check | Verification |
|---|-------|--------------|
| 1 | Git commit recorded and `git status` clean at start | `metadata.json` pre-run block |
| 2 | Training-view file SHA-256 recorded | `sha256sum train.jsonl` matches |
| 3 | Manifest records checksum matches on-disk records | canonical sorted-JSON checksum |
| 4 | Eval split SHA-256 recorded | `sha256sum eval.jsonl` |
| 5 | Model revision recorded | HF `refs/main` or snapshot |
| 6 | Full training config recorded (quantization, LoRA, optimizer, schedule) | config JSON |
| 7 | Random seed recorded and applied | seed set before any randomness |
| 8 | Evaluation engine version + commit recorded | engine path + git commit |
| 9 | Inference config recorded (max tokens, sampling, quantization) | eval JSON |
| 10 | Hardware + software versions recorded | GPU, torch, transformers, peft, bnb |
| 11 | Baseline recorded for the same eval split | baseline JSON + per-example |
| 12 | Determinism spot-check (same config twice → same aggregate) | CI or manual re-run |
| 13 | Outputs written under `experiments/{id}/` only | path audit |
| 14 | No dataset/view/release artifact modified | diff check against frozen hashes |
| 15 | Result declared `HOLD` when any check is not verifiable | fail-closed rule |

> **Fail-closed rule:** if ANY checklist item is unverifiable, the experiment is
> recorded as `HOLD` with null metrics and an explicit blocker note. Do not
> fabricate counts, checksums, or numbers (AGENTS rules 7–9).

---

## 5. Success Criteria

An experiment **succeeds** (result usable) when ALL hold:

1. **Reproducibility passed** — the full §4 checklist is green.
2. **Inputs verified** — every checksum/revision/config/seed matches the record.
3. **Evaluation completed** — QEE v2 produced per-example and aggregate scores on
   the full intended eval split, with a recorded baseline for comparison.
4. **Sufficient evidence** — the eval split size and effect size permit the
   claimed conclusion (no conclusion on N < minimum; see §7 power rule).
5. **Failure criteria did not trigger** (see §6).
6. **Claims scoped correctly** — conclusions are limited to the trained domain
   (math/code/AI-ML); no general-intelligence claim is made unless explicitly
   tested across domains.

## 6. Failure Criteria

An experiment **fails** (result unusable / conclusion invalid) when ANY holds:

1. **Reproducibility broken** — any §4 checklist item fails or is unverifiable
   (recorded `HOLD`/`FAILED`, not `COMPLETED`).
2. **Provenance lost** — dataset, model, config, or evaluator identity cannot be
   pinned to a recorded value.
3. **Immutability violated** — a dataset, training view, baseline output, or
   frozen release artifact was modified during the experiment.
4. **Underpowered** — the eval split is too small for the claim (N < minimum for
   the intended conclusion; default minimum N=30 per family unless justified).
5. **Evaluation invalid** — the evaluation engine was modified mid-experiment or
   the recorded engine version does not match the one executed.
6. **Training did not reproduce** — given identical inputs, a re-run diverges in
   final loss by more than the determinism tolerance, or the run did not reach
   the recorded number of steps.
7. **Metrics fabricated** — any number, checksum, or count was not measured
   (e.g., claiming evaluation ran when CUDA was unavailable).

A failed experiment is retained with its artifacts and a failure reason; it is
never deleted, never merged into conclusions, and never used for gating.

---

## 7. Power and Minimum Sample Rule

- A conclusion "X improves Y" requires a minimum eval sample of **N ≥ 30** per
  family under the default protocol, with the specific N recorded and justified.
- Smaller pilots (N < 30) are allowed **only as scoped pilots** that may report
  direction and observations, never as statistically reliable conclusions.
- Effect-size reporting is mandatory: report the delta, the per-example
  distribution, and the count of improved/regressed/unchanged records, not just
  the aggregate mean.
- All aggregate metrics MUST be accompanied by the per-example breakdown.

---

## 8. Cross-Domain Transfer Measurement

Applies to any experiment that trains on one domain and evaluates on another,
or trains on combined domains (Phase 8 P8-A–P8-D, matrix cells T1–T4). Uses
QEE v2 per-family metrics: math = extracted-answer correctness, code = patch
added-line similarity.

### 8.1 Gain definitions

Let `X` = source domain (trained on), `Y` = target domain (evaluated on),
`E_X` / `E_Y` the eval splits, and `B` the shared same-split baseline (same base
model, same eval split, same inference config, `scope=base`).

- **In-domain gain:** `Δ_in^X = score(LoRA_X, E_X) − score(B, E_X)`
- **Cross-domain gain:** `Δ_cross^{X→Y} = score(LoRA_X, E_Y) − score(B, E_Y)`

### 8.2 Transfer Ratio

```
TR_{X→Y} = Δ_cross^{X→Y} / Δ_in^X
```

| TR value | Interpretation |
|----------|----------------|
| `TR ≥ 1` | Cross-domain gain ≥ in-domain gain (strong positive transfer). |
| `0 < TR < 1` | Positive transfer, weaker than in-domain. |
| `TR ≈ 0` | Neutral transfer. |
| `TR < 0` | Negative transfer. |
| `N/A` | **Undefined** when `Δ_in^X ≤ 0`; recorded as HOLD for the ratio (fail-closed). Never fabricated. |

Rules:
- `TR` is defined **only** when `Δ_in^X > 0`; otherwise `N/A`.
- A transfer conclusion requires target eval `N ≥ 30` (power rule §7).
- Cross-direction ratios are comparable only with equal training-set sizes and
  commensurate metrics (threats T2, T7 in the Phase 8 plan).

### 8.3 Transfer-type classification

`Δ_cross^{X→Y}` is classified with a documented margin `τ = 0.05`
(consistent with Phase 7.0) plus per-example improved/regressed counts (§7):

| Type | Condition (all must hold) |
|------|---------------------------|
| **Positive transfer** | `Δ_cross ≥ +τ` AND improved-count > regressed-count. |
| **Negative transfer** | `Δ_cross ≤ −τ` AND regressed-count > improved-count. |
| **Neutral transfer** | `\|Δ_cross\| < τ`, claimable only when target eval `N ≥ 30`. |
| **UNDETERMINED** | Target eval `N < 30` or effect not distinguishable; recorded HOLD for the conclusion. |

### 8.4 Symmetry analysis (RQ5)

Compare `TR_{X→Y}` and `TR_{Y→X}`:

- **Symmetric** — both ratios defined, same transfer-type sign, and
  `|TR_{X→Y} − TR_{Y→X}| ≤ τ_sym` (default `τ_sym = 0.25`).
- **Asymmetric** — otherwise (sign differs, or gap > `τ_sym`).
- **UNDETERMINED** — either ratio is `N/A`; or either direction underpowered
  (verdict is then directional only, never a conclusion).

### 8.5 Required reporting for transfer runs

A transfer run MUST record: same-split baseline for both source and target
eval, `Δ_in^X`, `Δ_cross^{X→Y}`, `TR_{X→Y}` (or `N/A`), transfer type (or
`UNDETERMINED`), and per-example improved/regressed/unchanged counts on the
target eval split. Any missing value is a HOLD (fail-closed).

---

## 9. Versioning of This Protocol

| Version | Date | Change |
|---------|------|--------|
| v1.0 | 2026-08-04 | Initial adoption (Phase 6.1). |
| v1.1 | 2026-08-05 | Added §8 cross-domain transfer measurement (gain definitions, Transfer Ratio, transfer-type taxonomy, symmetry rules) for Phase 8; added `transfer` scope value (§2.1). |
