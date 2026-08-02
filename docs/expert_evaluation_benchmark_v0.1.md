# Atlas Expert Evaluation Benchmark v0.1

## Purpose

Define how Atlas measures whether expert data and future 300M specialist
models improve.

This document is analysis and design only:
- no ingestion
- no downloads
- no dataset modifications
- no model training

## Scope

Applies to expert-domain evaluation for:
- software engineering
- AI/ML
- mathematics
- science
- system engineering

It is intended to sit downstream of `docs/expert_quality_gate_v0.1.md` and
upstream of model comparison and training-view validation.

## Compatibility

This benchmark is designed to be compatible with:
- `docs/expert_quality_gate_v0.1.md`
- `docs/expert_record_schema_v0.1.md`

Where this benchmark adds evaluation-specific structure, it does not replace
the expert quality gate or canonical record schema. It reuses their concepts:
expert tier, difficulty, domain, verification status, provenance, and
training-turn format.

## Unknowns

The following items are marked `[UNKNOWN]` because they depend on future
calibration, human review, or model training results:
- exact benchmark size for production use
- human evaluation minimum sample sizes
- calibrated baseline differences for 300M specialists
- final pass/fail thresholds for model promotion

These must be resolved during benchmark calibration, not assumed now.

---

## 1. Benchmark Goals

### 1.1 Measure expert knowledge quality

Determine whether expert records preserve high-quality domain knowledge
through ingestion, filtering, and training.

### 1.2 Measure reasoning ability

Determine whether a specialist model can reproduce multi-step reasoning,
derivation, or design justification rather than memorizing surface form.

### 1.3 Detect hallucination

Determine whether a model invents unsupported facts, libraries, APIs,
theorems, or experimental results.

### 1.4 Compare baseline vs Atlas-trained models

Provide a repeatable evaluation surface for comparing:
- base model
- Atlas fine-tuned model

## 2. Domain Evaluation

### 2.1 Software Engineering

| Evaluation target | Example focus |
|-------------------|--------------|
| debugging tasks | Identify defect, trace symptom, propose fix |
| code explanation | Explain non-trivial code behavior or idiom |
| architecture reasoning | Justify tradeoffs, module boundaries, failure modes |
| system design questions | Propose components, interfaces, and operational constraints |

### 2.2 AI/ML

| Evaluation target | Example focus |
|-------------------|--------------|
| paper understanding | Explain method, assumptions, and main claim |
| methodology comparison | Contrast algorithms or training recipes accurately |
| experiment analysis | Interpret results with baseline, dataset, and metric awareness |
| troubleshooting training issues | Diagnose loss spikes, overfit, data leakage, or instability |

### 2.3 Mathematics

| Evaluation target | Example focus |
|-------------------|--------------|
| multi-step reasoning | Chain algebraic, combinatorial, or analytic steps |
| derivation | Derive formula or identity from stated assumptions |
| proof validation | Verify logical correctness and completeness |

### 2.4 Science and System Engineering

Science and System Engineering benchmarks are deferred from this version.
Analogous evaluation targets should be added when expert data for these
domains enters the pipeline.

---

## 3. Evaluation Metrics

### 3.1 correctness

Whether the model answer is factually or technically correct.

- For code: behavior matches specification and is internally consistent.
- For AI/ML: claims align with authoritative methodology or paper content.
- For math: final result and intermediate steps are valid.

### 3.2 reasoning quality

Whether the answer shows coherent multi-step reasoning rather than
asserting conclusions without justification.

### 3.3 explanation completeness

Whether the answer covers required context, constraints, assumptions,
and edge cases needed for a 300M specialist to learn the concept.

### 3.4 hallucination rate

Fraction of model outputs containing unsupported claims, invented APIs,
fictitious theorems, or fabricated experimental details.

### 3.5 domain accuracy

Fraction of answers that are correct within the target domain, ignoring
stylistic issues.

### 3.6 confidence calibration

Whether model confidence aligns with actual correctness.
Well-calibrated models should be more accurate when they express higher
confidence.

---

## 4. Benchmark Format

### 4.1 Question format

Each benchmark item should include:
- `id`
- `domain`
- `expert_tier`
- `difficulty`
- `question`
- optional `context`
- `source_reference`
- `expected_answer_type`
- `scoring_rubric`
- `verification_evidence`

### 4.2 Expected answer format

- `answer` for short factual or derivation responses
- `derivation` for step-by-step math or reasoning
- `code` for code explanation or debugging responses
- `explanation` for conceptual or design responses

### 4.3 Scoring method

Use structured scoring aligned with the quality gate dimensions:
- correctness
- reasoning quality
- explanation completeness
- hallucination presence
- domain accuracy
- confidence calibration evidence

Scoring should be compatible with `docs/expert_quality_gate_v0.1.md` so
that benchmark success criteria map cleanly to expert record acceptance.

### 4.4 Human evaluation requirements

- Human evaluation is required for all benchmark subsets before promotion.
- Minimum human review coverage: `[UNKNOWN]` until pilot study defines
  confidence intervals.
- Human evaluation should record:
  - correctness
  - reasoning quality
  - explanation completeness
  - hallucination flag
  - reviewer notes

---

## 5. Difficulty Levels

Difficulty maps to expert tiers for benchmark construction.

| Expert tier | Benchmark meaning | Target model behavior |
|-------------|-------------------|-----------------------|
| E1 Professional | Authoritative knowledge retrieval and application | Correct, complete, well-cited answers |
| E2 Advanced Reasoning | Multi-step reasoning, debugging, derivation | Correct reasoning chain and final answer |
| E3 Frontier | Research-level or novel problem solving | Insightful analysis with explicit assumptions and limitations |

This mapping should be preserved in benchmark metadata so evaluation
results can be stratified by tier.

---

## 6. Baseline Comparison

### 6.1 Models under comparison

- base model
- Atlas fine-tuned model

Only these two should be compared in the initial benchmark phase.

### 6.2 Comparison protocol

1. Use identical benchmark questions for both models.
2. Score both sets using the same rubric and evaluator guidelines.
3. Keep evaluators blind to model identity where possible.
4. Record per-tier and per-domain results separately.
5. Report aggregate and stratified metrics.

### 6.3 Success criteria

- Atlas fine-tuned model should improve on expert-domain metrics relative
  to the base model.
- Improvement should be strongest on E2 and E3 content, where expert
  training adds the most signal.
- Hallucination rate should not increase relative to the base model.

Exact numeric improvement thresholds are `[UNKNOWN]` and must be defined
after pilot evaluation.

---

## 7. Recommended Initial Benchmark Size

The following size is a starting point for pilot evaluation.

| Component | Count | Notes |
|-----------|-------|-------|
| total questions | 600 | Initial pilot benchmark |
| software engineering | 200 | debugging, explanation, architecture, design |
| AI/ML | 200 | paper understanding, methodology, experiments, troubleshooting |
| mathematics | 200 | reasoning, derivation, proof validation |

### Difficulty mix

| Tier | Mix | Rationale |
|------|-----|-----------|
| E1 | 60% | Professional knowledge baseline |
| E2 | 30% | Advanced reasoning emphasis |
| E3 | 10% | Frontier signal without overwhelming the benchmark |

This mix aligns with the 300M specialist training mix and allows
stratified evaluation.

---

## 8. Recommended Implementation Order

The following order is recommended for implementing the benchmark.

### Phase 1: Benchmark schema and item authoring
Define the benchmark item format and create the initial 600-item pilot
set. Ensure each item includes domain, tier, difficulty, source reference,
expected answer type, and scoring rubric.

### Phase 2: Scoring harness
Implement deterministic scoring aligned with the quality gate dimensions.
Reuse concepts from `docs/expert_quality_gate_v0.1.md` so scores are
compatible with downstream filtering and review.

### Phase 3: Human evaluation workflow
Build the human review workflow for benchmark answers. Require reviewer
identity, calibration notes, and hallucination flags.

### Phase 4: Baseline model evaluation
Run the base model against the benchmark under blind conditions.

### Phase 5: Atlas model evaluation
Run the Atlas fine-tuned model against the same benchmark.

### Phase 6: Analysis and threshold calibration
Compare results, compute per-domain and per-tier deltas, and define
production thresholds for benchmark success.

### Phase 7: Integration with quality and training workflows
Connect benchmark results to:
- expert data acceptance thresholds
- training-view curation decisions
- future model promotion gates

## Out of Scope

- Model training or fine-tuning
- Release or publication workflows
- Any operation that modifies `raw/`, `curated/`, or existing datasets
