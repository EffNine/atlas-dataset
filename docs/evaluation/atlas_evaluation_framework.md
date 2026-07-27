# Atlas Evaluation Framework

This document defines the Atlas evaluation infrastructure: the layered evaluation model, lifecycle, and architectural principles that govern all measurement activity.

## 1. Invariants

- All evaluation is **read-only** on datasets, reviews, and release metadata.
- Evaluation does not modify curated content, review decisions, or release state.
- Evaluation runs are **deterministic** given the same inputs and configuration.
- Evaluation **does not train models**. All measurements are static.
- Evaluation has **no network access** during execution.
- Evaluation outputs go to `docs/evaluation/` and `metadata/` only.

## 2. Evaluation Layers

### 2.1 Knowledge Quality Evaluation

Measures the intrinsic quality of knowledge objects independent of any model.

| Dimension | Description | Metric |
|-----------|-------------|--------|
| **Factual Correctness** | Whether statements in the object are verifiably true | fact_accuracy |
| **Completeness** | Whether the object covers the expected scope of the topic | coverage_score |
| **Reasoning Quality** | Clarity, logical flow, and depth of reasoning steps | reasoning_coherence |
| **Provenance Quality** | Whether sources are properly attributed and verifiable | provenance_accuracy |
| **Instruction Following** | Whether the object correctly follows its instruction template | instruction_adherence |

### 2.2 Safety Evaluation

Measures risk and compliance dimensions.

| Dimension | Description | Metric |
|-----------|-------------|--------|
| **License Compliance** | All objects have approved licenses with proper attribution | license_pass_rate |
| **Prohibited Content** | No harmful, illegal, or policy-violating content | content_safety_rate |
| **Hallucination Risk** | Likelihood of unsupported or fabricated claims | hallucination_risk_score |
| **Unsupported Claims** | Claims lacking citation or source evidence | unsupported_claim_rate |

### 2.3 Engineering Evaluation

Measures system-level properties of the dataset pipeline.

| Dimension | Description | Metric |
|-----------|-------------|--------|
| **Reproducibility** | Pipeline outputs are identical across runs | reproducibility_hash |
| **Determinism** | Same inputs always produce same outputs | determinism_score |
| **Schema Compliance** | All objects validate against canonical schemas | schema_pass_rate |
| **Lifecycle Correctness** | State transitions follow the lifecycle state machine | lifecycle_validity |

## 3. Evaluation Lifecycle

```
candidate
  │
  ▼
automated evaluation    ← deterministic, no model, no network
  │
  ▼
human validation        ← optional, for calibration
  │
  ▼
benchmark comparison    ← against registered benchmark baselines
  │
  ▼
release decision        ← gates pass / fail
```

### Stage 1: Candidate

A candidate is a knowledge object, dataset version, or view that is ready for measurement. Candidates are identified by their ID and version.

### Stage 2: Automated Evaluation

The evaluation engine runs all registered metrics against the candidate:

- No model inference — metrics are static analysis
- No network calls
- Results written to an evaluation report
- All intermediate data is local and ephemeral

### Stage 3: Human Validation (Optional)

For quality calibration, a human can validate a subset of automated evaluation results. This does not modify evaluation reports — it produces a separate validation record stored in `metadata/evaluation_validations.json`.

### Stage 4: Benchmark Comparison

Automated results are compared against benchmark baselines stored in `metadata/benchmark_registry.json`. Deviations are flagged but do not modify baseline data.

### Stage 5: Release Decision

The evaluation summary feeds into the release gate system. A release gate may query evaluation results, but the evaluation engine does not make or enforce release decisions.

## 4. Architecture

```
scripts/evaluation_engine/
├── __init__.py          # Package exports
├── engine.py            # Evaluation orchestration (EvaluationOrchestrator)
├── metrics.py           # Metric definitions and registry
├── registry.py          # Benchmark registry loader
└── report.py            # Evaluation report generator

metadata/
└── benchmark_registry.json   # Registered benchmarks

docs/
├── evaluation/
│   └── atlas_evaluation_framework.md   # This document
└── specs/
    └── evaluation_report_spec.md       # Report format specification

tests/
└── probe_evaluation_foundation.py      # Verification probe
```

## 5. Dependencies

- The evaluation engine imports from `atlas_paths` (for path resolution) and `atlas_schema` (for schema validation).
- It does NOT import from `acquisition_engine`, `validate_dataset`, or any review/curation modules.
- Network access is explicitly blocked during evaluation runs.
- All evaluation code is stdlib-compatible (no external ML frameworks, no GPU dependencies).

## 6. Related Documents

- Evaluation Report Spec: `docs/specs/evaluation_report_spec.md`
- Benchmark Registry: `metadata/benchmark_registry.json`
- Architecture Governance: `docs/governance/atlas_architecture_governance.md`
