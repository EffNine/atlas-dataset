# Atlas Research Automation — Architecture Proposal

> **Phase:** 0 (Architecture Audit)
> **Date:** 2026-08-12
> **Status:** PROPOSAL
> **Scope:** Benchmark + Generation-Policy Calibration Infrastructure

---

## 1. Executive Summary

The immediate research objective is to make the evaluation/research pipeline strong enough to answer
the scaling question scientifically — not to train more data or run more evaluations yet.

This proposal outlines how to extend existing Atlas automation infrastructure to support:

1. Generation-policy calibration (multi-alpha experiment)
2. External benchmark onboarding (discovery → acquisition → validation → freeze)
3. Contamination audit (benchmark vs M1/M2/M2' training records)
4. Clean held-out evaluation dataset creation
5. Automated M1/M2/M2' comparison with statistical rigor
6. A research experiment state machine with `WAITING_HUMAN_APPROVAL` semantics

**Core design principle:** Extend existing infrastructure; never duplicate.

---

## 2. Existing Infrastructure Reused (No Changes Required)

| Component | Location | Reuse |
|-----------|----------|-------|
| Generation Policy Lock | `scripts/evaluation_engine/generation_policy/` | `DynamicBudgetStrategy` with calibrated params; immutability; hash versioning; validation gates |
| Leakage Prevention | `scripts/evaluation_engine/leakage/` | `prompts.py` (reference-free), `scan.py` (L1), `audit.py` (L3) |
| QEE v2 Engine | `scripts/evaluation_engine/v2/` | Math/code/semantic evaluators; unchanged |
| T3 Baseline Runner | `scripts/evaluation_engine/run_baseline_t3.py` | Reference-free inference with per-record budget, G-POL, determinism spot-check, checkpoint/resume |
| Parallel Scheduler | `scripts/parallel/scheduler.py` | Adaptive worker pool with retry, backpressure, TaskRegistry |
| Download Cache | `scripts/downloader/cache.py` | Content-addressable cache with SQLite index, resume, checksum verification |
| HuggingFace Adapter | `scripts/downloader/adapters/huggingface.py` | Dataset download from HF Hub |
| State Machine | `scripts/automation/state_machine.py` | FSM with `WAITING_HUMAN_APPROVAL` gate |
| Approval Gate | `scripts/automation/approval_gate.py` | Human approval workflow |
| Checkpoint System | `scripts/acquisition_engine/checkpoint.py` | Checksummed JSON persistence |
| Benchmark Registry | `metadata/benchmark_registry.json` + `scripts/evaluation_engine/registry.py` | Extensible benchmark catalog |
| CLI Framework | `scripts/atlas.py` | Subcommand registration pattern |
| Test Infrastructure | `tests/evaluation_v2/` | conftest.py, pytest structure |

---

## 3. New Components Required

### 3.1 `scripts/evaluation_research/` — Research Automation Package

```
scripts/evaluation_research/
├── __init__.py
├── calibration.py          # Multi-policy calibration experiment runner
├── benchmark_discover.py   # Benchmark discovery + license/provenance check
├── benchmark_acquire.py    # Benchmark acquisition via downloader + cache
├── contamination.py        # Contamination audit against training records
├── eval_set_builder.py     # Build versioned clean eval sets
├── matrix_runner.py        # Automated M1/M2/M2' evaluation matrix
├── statistics.py           # Paired comparison, CIs, p-values
├── state_machine.py        # Research experiment FSM
├── cli.py                  # CLI command dispatch (extends atlas.py)
└── artifacts.py            # Artifact integrity + provenance tracking
```

### 3.2 Research Experiment State Machine

New state machine in `scripts/evaluation_research/state_machine.py` extending the
existing `PipelineState` philosophy with research-specific states:

```
BENCHMARK_DISCOVERY
  → BENCHMARK_ACQUIRED
  → LICENSE_VALIDATED
  → CONTAMINATION_AUDIT
  → EVAL_SET_FROZEN
  → POLICY_CALIBRATION
  → POLICY_FROZEN
  → EVALUATION_RUNNING
  → EVALUATION_COMPLETE
  → STATISTICAL_ANALYSIS
  → HUMAN_REVIEW
  → CONCLUDED
```

Transitions preserve the `WAITING_HUMAN_APPROVAL` invariant at:
- `LICENSE_VALIDATED → CONTAMINATION_AUDIT`
- `EVAL_SET_FROZEN → POLICY_CALIBRATION`
- `POLICY_FROZEN → EVALUATION_RUNNING`
- `STATISTICAL_ANALYSIS → HUMAN_REVIEW`

Verdict states: `PASS`, `FAIL`, `HOLD`, `INCONCLUSIVE` — always with evidence references.

### 3.3 Generation-Policy Calibration Runner

`calibration.py` runs a deterministic experiment across candidate policies:

- Fixed seed (N=30 math records from a stratified sample of `math_eval_v2_clean.jsonl`)
- For each `(family, alpha)` candidate:
  - Same base model, tokenizer, quantization, prompt, generation config
  - Collect: N, truncation_rate, stop_reasons, mean/p50/p95 tokens, budget fallback count, G-POL status, determinism check
- **Never** measures or optimizes against correctness
- Produces `metadata/evaluation/calibration/{run_id}/` with per-policy artifacts
- Verifies deterministic repeatability (two runs → identical outputs)

### 3.4 Benchmark Onboarding Pipeline

`benchmark_discover.py`:
- Accepts a benchmark spec (name, URL/repo, family, expected N)
- Checks license compatibility (reuse `is_denied_license`)
- Fetches metadata from HuggingFace (or local manifest)
- Produces a discovery report with: license, source, version, record count estimate, canonical answer availability, contamination risk assessment

`benchmark_acquire.py`:
- Downloads benchmark files via the existing HF adapter + cache
- Computes per-file SHA-256 checksums
- Registers the benchmark in `metadata/benchmark_registry.json` (updates status from "placeholder" to "acquired")
- Validates schema: every record has `problem` + `canonical_answer` (or derives `canonical_answer` from available answer fields)

### 3.5 Contamination Auditor

`contamination.py`:
- Loads M1/M2/M2' training records from `experiments/phase7_scale/subsets/`
- For each benchmark record:
  1. Exact ID overlap check
  2. Exact text overlap (problem field vs training problem fields)
  3. Normalized text overlap (whitespace-collapsed, lowercased)
  4. Near-duplicate overlap using existing dedup infrastructure where applicable
- Produces: total benchmark records, exact overlaps, normalized overlaps, near-duplicate overlaps,
  records removed, final clean count, manifest, checksum
- If clean N < 1000: reports this explicitly rather than fabricating the target

### 3.6 Clean Eval Set Builder

`eval_set_builder.py`:
- Takes acquired benchmark data + contamination audit results
- Creates versioned eval set under `evaluation/eval_sets/production/`
- Immutable after freeze: no modification of benchmark questions
- Includes manifest, source/provenance metadata, checksum, contamination audit report, evaluation protocol metadata

### 3.7 Evaluation Matrix Runner

`matrix_runner.py`:
- Extends `run_baseline_t3.py` pattern for adapter evaluation
- Loads frozen adapters (M1, M2, M2') from `experiments/lora_pilot_math_m2_v0.1/` and related
- Every model uses: identical base model revision, tokenizer, quantization, prompt, generation policy, evaluator, benchmark records
- Produces per-example results with: question ID, model, correctness, reasoning quality, hallucination, format consistency, truncation, stop reason, generated token count
- Produces aggregate results with: N, correctness, confidence interval, delta vs M1, paired comparison, p-value, truncation rate, G-POL, policy covariates

### 3.8 Statistical Comparison Module

`statistics.py`:
- Paired t-test or Wilcoxon signed-rank for same-record comparisons
- Confidence intervals via binomial proportion (Clopper-Pearson) for correctness
- Effect size calculation (Cohen's d for paired)
- HOLD when N < 30 or evidence insufficient

---

## 4. Architecture Diagram

```
                    ┌─────────────────────────────────────────────────┐
                    │           atlas CLI (scripts/atlas.py)          │
                    │  benchmark discover / acquire / audit / freeze  │
                    │  eval calibrate-policy / run / compare / status │
                    └────────────────────┬────────────────────────────┘
                                         │
                    ┌────────────────────▼────────────────────────────┐
                    │      evaluation_research (new package)           │
                    │                                                 │
                    │  ┌─────────────┐  ┌──────────────┐             │
                    │  │ calibration │  │  benchmark_   │             │
                    │  │    .py      │  │  acquire.py   │             │
                    │  └──────┬──────┘  └──────┬───────┘             │
                    │         │                │                      │
                    │  ┌──────▼──────┐  ┌──────▼───────┐             │
                    │  │contamination│  │  eval_set_   │             │
                    │  │    .py      │  │  builder.py  │             │
                    │  └──────┬──────┘  └──────┬───────┘             │
                    │         │                │                      │
                    │  ┌──────▼────────────────▼──────┐              │
                    │  │     matrix_runner.py          │              │
                    │  │  (extends run_baseline_t3)   │              │
                    │  └──────────────┬───────────────┘              │
                    │                 │                              │
                    │  ┌──────────────▼──────────────┐              │
                    │  │    statistics.py             │              │
                    │  │  (paired tests, CIs, pvals) │              │
                    │  └──────────────┬───────────────┘              │
                    │                 │                              │
                    │  ┌──────────────▼──────────────┐              │
                    │  │  research_state_machine.py   │              │
                    │  │  (extends PipelineState)     │              │
                    │  └─────────────────────────────┘              │
                    └─────────────────────────────────────────────────┘
                                     ▲           ▲
                                     │           │
              ┌──────────────────────┘           └──────────────────────┐
              │                                                         │
    ┌─────────▼──────────┐                                ┌─────────────▼───────────┐
    │ Existing Atlas Infra│                                │ Frozen Artifacts         │
    │                     │                                │                          │
    │ • generation_policy/│                                │ • M1/M2/M2' adapters     │
    │ • leakage/prompts.py│                                │ • math_eval_v2_clean     │
    │ • v2/engine.py      │                                │ • phase7_scale/subsets   │
    │ • parallel/sched    │                                │ • calibration_5A5 report │
    │ • downloader/cache  │                                │ • run_baseline_t3 outputs│
    │ • acquisition/check │                                │                          │
    └─────────────────────┘                                └─────────────────────────┘
```

---

## 5. File Layout

### New files:
```
scripts/evaluation_research/__init__.py
scripts/evaluation_research/calibration.py
scripts/evaluation_research/benchmark_discover.py
scripts/evaluation_research/benchmark_acquire.py
scripts/evaluation_research/contamination.py
scripts/evaluation_research/eval_set_builder.py
scripts/evaluation_research/matrix_runner.py
scripts/evaluation_research/statistics.py
scripts/evaluation_research/state_machine.py
scripts/evaluation_research/cli.py
scripts/evaluation_research/artifacts.py

tests/evaluation_research/
  __init__.py
  test_calibration.py
  test_benchmark_discover.py
  test_contamination.py
  test_eval_set_builder.py
  test_matrix_runner.py
  test_statistics.py
  test_state_machine.py
  test_artifacts.py
  conftest.py
```

### Modified files:
```
scripts/atlas.py                    # Add benchmark/eval subcommands
metadata/benchmark_registry.json    # Update with acquired benchmarks
docs/research/generation_policy_calibration_5A5.md  # Append calibration experiment results
```

---

## 6. Implementation Order

1. **Phase 1:** `calibration.py` + `test_calibration.py` — small, self-contained, directly addresses the G-POL FAIL on math
2. **Phase 2:** `benchmark_discover.py` + `benchmark_acquire.py` + tests — bench GSM8K/MATH acquisition design
3. **Phase 3:** `contamination.py` + tests — mandatory, no training expansion
4. **Phase 4:** `eval_set_builder.py` + tests — clean eval set creation
5. **Phase 5:** `matrix_runner.py` + tests — M1/M2/M2' evaluation (requires CUDA)
6. **Phase 6:** `state_machine.py` + `artifacts.py` — research experiment FSM
7. **Phase 7:** `cli.py` + `atlas.py` integration — user-facing commands
8. **Phase 8:** Final test run + verification

---

## 7. Constraints Enforced

- **No training data expansion** — all new code is read-only on `curated/`, `raw/`, `training_views/`
- **No benchmark contamination** — contamination audit is mandatory before eval set freeze
- **No fabricated metrics** — null values where evidence is unavailable; explicit HOLD
- **No silent protocol changes** — calibration results documented; old policy preserved as historical
- **Deterministic, reproducible** — every artifact has checksum; resume supported
- **Human approval boundary** — research state machine requires approval at critical gates

---

*Proposal ready for Technical Lead review before implementation begins.*
