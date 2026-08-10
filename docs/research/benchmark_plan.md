# Atlas Benchmark Plan

> **Phase:** 6.1
> **Status:** Adopted
> **Date:** 2026-08-04
> **Scope:** Defines the benchmark schedule tiers (Pilot → Production), the
> benchmark set used at each tier, resource envelopes, and gating rules.
> Documentation only. No training is scheduled by this plan until approved.

---

## 1. Tiers

| Tier | Identifier | Purpose | Typical eval N | GPU envelope | Time envelope |
|------|------------|---------|----------------|--------------|---------------|
| Pilot | `pilot` | Direction-finding; infrastructure validation; method sanity | 2–30 | 1× RTX 5070 12 GB | < 1 day |
| Small | `small` | Statistical signal; single-variable comparisons | 30–200 | 1× RTX 5070 12 GB | 1–3 days |
| Medium | `medium` | Robust capability estimates; cross-config comparisons | 200–1,000 | 1× RTX 5070 or 1× ≥ 24 GB | 3–7 days |
| Large | `large` | High-confidence capability evaluation; near-final model candidates | 1,000–5,000 | 1–2× ≥ 24 GB or multi-GPU | 1–3 weeks |
| Production | `prod` | Final gated model candidate; release-quality evidence | full held-out split | full available cluster | 3–6 weeks |

The tier names appear in the experiment identifier (`atlas-{family}-{tier}-…`).

---

## 2. Benchmark Set

Primary scoring engine is **QEE v2** (`scripts/evaluation_engine/v2`) — frozen
for the duration of any experiment; the engine version is recorded per run.

### 2.1 Internal (Atlas-native) benchmarks

| Benchmark | Family | Metric | Status |
|-----------|--------|--------|--------|
| Atlas math view eval split (`math_300m_v0.1/eval.jsonl`) | math | extracted-answer correctness | **current N=13, underpowered** |
| Atlas code view eval split (`code_300m_v0.1/eval.jsonl`) | code | patch added-line similarity | **current N=2, underpowered** |
| Atlas aiml view eval split (`aiml_300m_v0.1/eval.jsonl`) | aiml | semantic rubric | to be baseline-evaluated |
| Atlas quality benchmark (registry) | mixed | quality_score_agreement | draft |
| Provenance benchmark (registry) | mixed | provenance_accuracy | draft |
| Review agreement benchmark (registry) | mixed | cohens_kappa | draft |

### 2.2 External (registered placeholders; NOT downloaded/stored)

From `metadata/benchmark_registry.json` — placeholders for future integration.

| Benchmark | Family | Metric | Status |
|-----------|--------|--------|--------|
| MMLU | mixed | accuracy | placeholder |
| GSM8K | math | exact_match | placeholder |
| HumanEval | code | pass@k | placeholder |
| ARC | aiml/mixed | accuracy | placeholder |

External benchmarks are **not** part of any current tier until downloaded,
checksummed, and registered as approved assets per governance rules.

---

## 3. Tier Gates

### 3.1 Pilot
- Gate: infrastructure runs end-to-end; pre-training record block complete;
  evaluation produces per-example output.
- Not allowed to support statistical conclusions (N < 30 default minimum).

### 3.2 Small
- Gate: eval N ≥ 30 per family; baseline + one experimental arm both complete;
  protocol §4 checklist green.
- May support single-variable directional conclusions.

### 3.3 Medium
- Gate: eval N ≥ 200 per family; multi-config comparison; effect sizes and
  per-example distributions reported; determinism spot-check passed.

### 3.4 Large
- Gate: eval N ≥ 1,000 per family; runs on ≥ 24 GB or multi-GPU hardware with
  recorded determinism; results reviewed by human governance.

### 3.5 Production
- Gate: full held-out split; mandatory `WAITING_HUMAN_APPROVAL` before any
  release decision; all checklist items green; claims scoped to the tested
  domain(s) only.

---

## 4. Benchmark Schedule (proposed, pending approval)

Each row requires an approved experiment ID and the §4 reproducibility
checklist. Ordering is dependency-ordered (baseline → pilot → scale).

| # | Family | Tier | Experiment (proposed) | Depends on |
|---|--------|------|-----------------------|-----------|
| 1 | mixed | pilot | `atlas-mixed-pilot-qwen7b-eval-v2` — full baseline refresh | — |
| 2 | aiml | pilot | `atlas-aiml-pilot-qwen7b-eval-v1` — aiml baseline | #1 |
| 3 | math | pilot | `atlas-math-pilot-qwen7b-lora-v1` | done (Phase 5B.1) |
| 4 | code | pilot | `atlas-code-pilot-qwen7b-lora-v1` | done (Phase 5B.2) |
| 5 | math | small | `atlas-math-small-qwen7b-lora-v1` — expanded eval split (N≥30) | view expansion |
| 6 | code | small | `atlas-code-small-qwen7b-lora-v1` — expanded code eval | view expansion |
| 7 | aiml | small | `atlas-aiml-small-qwen7b-lora-v1` | #2, view adequacy |
| 8 | math | small | `atlas-math-small-qwen7b-lora-hp-v1` — LR/r sweep | #5 |
| 9 | math | medium | `atlas-math-medium-qwen7b-lora-v1` — high-confidence estimate | #5, #8 |
| 10 | mixed | small | `atlas-mixed-small-qwen7b-lora-v1` — combined-data adapter | #5–7 |
| 11 | code | medium | `atlas-code-medium-qwen7b-lora-v1` | #6 |
| 12 | mixed | large | `atlas-mixed-large-qwen8b-full-v1` — model-class sweep | #9–11 |
| 13 | math | large | `atlas-math-large-llama8b-lora-v1` — cross-model | #9 |
| 14 | mixed | prod | `atlas-mixed-prod-*` — final gated candidate | #12–13 |

> **Resource dependency:** items 1–8 require only the existing RTX 5070 12 GB
> box. Items 9+ require either an expanded eval split (still achievable on the
> 5070 for lora) or ≥ 24 GB hardware for `full` scopes.

---

## 5. Data-Size Requirement

The current code/math eval splits (N=2 and N=13) are **below** the protocol
minimum (N ≥ 30). The first benchmark gate for math and code is therefore a
**view expansion** (approved source records exist: 6,500 in the expert pilot
release) to produce adequate train/eval splits, without modifying the frozen
`*_300m_v0.1` views.

---

## 6. Review and Revision

- This plan is reviewed whenever the matrix, protocol, or dataset version
  changes.
- Any change is a docs-only edit; no code, training, or dataset change is
  implied by this plan itself.
