# Atlas Specialist Model Data Strategy v0.1

## Purpose

Define the Atlas training direction for multiple specialist ~300M parameter
models. This document is **strategy documentation only**:

- no training
- no dataset expansion
- no unverified sources
- no dataset modifications

It converts the validated Phase 0.5 calibration results and the Atlas expert
layer design into a concrete multi-model data plan.

## Compatibility

This strategy is designed to be compatible with:

- `docs/expert_definition_v0.1.md`
- `docs/expert_record_schema_v0.1.md`
- `docs/expert_quality_gate_v0.1.md`
- `docs/expert_pilot_sample_calibration_plan_v0.1.md`
- `docs/expert_pilot_execution_checklist_v0.1.md`
- `docs/expert_gap_report_v0.1.json`
- `metadata/expert_source_registry_v0.1.json`
- `metadata/expert_math_source_resolution_v0.1.json`
- `configs/training/qlora_qwen3_8b.yaml` (reference template; training paused)

## Phase 0.5 Calibration Status (input to this strategy)

Validated by real sample calibration (measured, not estimated):

| Source | Domain | License | Calibration Result |
|--------|--------|---------|--------------------|
| SWE-bench Verified (expert-swe-001) | software_engineering | MIT | **GO** — schema pass 1.0, KEEP 100/100, dup rate 0.0 |
| ArXiv cs.LG/cs.CL/cs.AI/stat.ML (expert-aiml-001) | ai_machine_learning | arXiv non-exclusive | **GO** — schema pass 1.0, KEEP 12/12, dup rate 0.0 |
| OpenMathInstruct-2 (expert-math-002) | mathematics | CC-BY-4.0 | **GO** — schema pass 1.0, KEEP 100/100, dup rate 0.0 |
| Open-Platypus (expert-aiml-002) | ai_machine_learning | mixed (23.5% NC + 14.9% unresolved) | **HOLD** — license filtering required only |

Open-Platypus is excluded from this strategy until a license filtering policy
is decided. It is not required for the Priority 1 initial plan.

---

## 1. Architecture Concept

A single orchestration layer routes requests to multiple small specialist
models. Each specialist is a ~300M parameter model trained on one expert
domain.

```
                    +----------------+
                    |  Orchestrator   |
                    +----------------+
                          |
        +-----------------+-----------------+
        |                 |                 |
+---------------+ +---------------+ +---------------+
| Code          | | Math          | | AI/ML Research|
| Specialist    | | Specialist    | | Specialist    |
| 300M          | | 300M          | | 300M          |
+---------------+ +---------------+ +---------------+
        |                 |                 |
+---------------+ +---------------+
| System Eng    | | Science       |
| Specialist    | | Specialist    |
| 300M          | | 300M          |
+---------------+ +---------------+
```

**Design notes:**

- Specialists are kept small (300M) so that several can be resident on a
  single 12GB GPU (see Section 5).
- The orchestrator is a routing layer (classifier/embedding or small router
  model), not a large generative model itself. It may be a lightweight
  intent classifier or a 0.5-1B router.
- Datasets remain **model-agnostic** (per Atlas principle): the same curated
  JSONL feeds any specialist; only the chat template and adapter differ.
- Specialists may share the same base architecture with domain-specific
  adapters, or be distinct 300M checkpoints. This is a training-time decision,
  not a data decision.

---

## 2. Specialist Objectives

### 2.1 Code Specialist (300M)

| Aspect | Target |
|--------|--------|
| Domain | software_engineering |
| Intended capability | debugging, issue-to-patch reasoning, code review, patch generation |
| Training data requirements | verified issue-to-patch pairs (SWE-bench Verified), high-quality code Q&A, review examples |
| Quality requirements | quality_score >= 7, correctness >= 3, verification evidence present |
| Evaluation approach | held-out SWE-bench test instances (no gold leakage), patch plausibility, unit-test pass on eval subset |

### 2.2 Math Specialist (300M)

| Aspect | Target |
|--------|--------|
| Domain | mathematics |
| Intended capability | competition-style reasoning, step-by-step derivation, quantitative problem solving |
| Training data requirements | OpenMathInstruct-2 (CC-BY-4.0, model-generated solutions flagged), competition math (MATH benchmark where license-safe), NuminaMath-CoT (Apache-2.0) as secondary |
| Quality requirements | quality_score >= 7, reasoning_depth >= 3, expected_answer presence where available |
| Evaluation approach | held-out MATH/GSM8K-style problems, answer-string match, step-validity human sample |

### 2.3 AI/ML Research Specialist (300M)

| Aspect | Target |
|--------|--------|
| Domain | ai_machine_learning |
| Intended capability | paper-to-explanation, method explanation, experiment analysis, concept Q&A |
| Training data requirements | ArXiv cs.LG/cs.CL/cs.AI/stat.ML abstract-grounded records, ML textbook derivations (when a verified source exists), experiment analysis |
| Quality requirements | quality_score >= 7, attribution non-empty, provenance complete |
| Evaluation approach | held-out arXiv abstracts, citation/attribution check, concept-explainability rubric |

### 2.4 System Engineering Specialist (300M) — Priority 2

| Aspect | Target |
|--------|--------|
| Domain | system_engineering |
| Intended capability | OS/networking troubleshooting, operational runbooks, performance reasoning |
| Training data requirements | kernel docs, man-pages, Kubernetes/Docker docs (existing accepted sources), verified operational Q&A |
| Quality requirements | quality_score >= 7, provenance complete, share-alike attribution honored |
| Evaluation approach | doc-grounded Q&A, troubleshooting scenario rubric |

### 2.5 Science Specialist (300M) — Priority 2

| Aspect | Target |
|--------|--------|
| Domain | science |
| Intended capability | graduate-level explanations, experimental analysis, research Q&A |
| Training data requirements | openly licensed science corpus, paper-derived explanations (arxiv-based, license-safe) |
| Quality requirements | quality_score >= 7, attribution non-empty |
| Evaluation approach | held-out science Q&A, fact-grounded rubric |

---

## 3. Initial Target Domains

### Priority 1 (validated calibration, ready to plan around)

1. **Software Engineering** — SWE-bench Verified (GO)
2. **Mathematics** — OpenMathInstruct-2 (GO)
3. **AI/ML** — ArXiv (GO)

### Priority 2 (existing accepted sources; calibration not yet run)

4. **System Engineering** — kernel/man-pages/Kubernetes/Docker docs (accepted in registry)
5. **Science** — paper-derived explanations (arxiv-based path, license-safe)

Priority 2 does not block the Priority 1 plan. The first three specialists can
be specified, sourced, and trained independently.

---

## 4. Dataset Strategy

### 4.1 Target record count per specialist

Calibration targets are minimums for a 300M specialist to reach meaningful
capability. These are planning targets, not commitments:

| Specialist | Target expert records | Notes |
|------------|----------------------|-------|
| Code | 100k–200k | SWE-bench Verified (~22k) is a strong core; needs supplement |
| Math | 100k–200k | OpenMathInstruct-2 is 14M; subset to quality-gated sample |
| AI/ML | 100k–150k | ArXiv abstracts scalable; textbook derivations needed |
| System Eng | 50k–100k | doc-derived Q&A scalable |
| Science | 50k–100k | paper-derived explanations scalable |

The Atlas Expert v1 total target is 700k records across all domains
(`docs/expert_gap_report_v0.1.json`).

### 4.2 E1/E2/E3 mix

| Tier | Share | Role |
|------|-------|------|
| E1 | 60% | stable professional knowledge (docs, verified Q&A) |
| E2 | 30% | reasoning-heavy content (issue-to-patch, competition math) |
| E3 | 10% | frontier signal (research papers, olympiad) |

Per-specialist mixes may shift (e.g., Math leans E2/E3, System Eng leans E1),
but the global 60/30/10 balance is the default for 300M specialist training.

### 4.3 Synthetic vs human data policy

- Human/verified data is the anchor: SWE-bench (gold patches), ArXiv
  (author-written abstracts), MATH (official solutions where license-safe).
- Model-generated data is **allowed with mandatory flags**:
  `metadata.model_generated=true` and `metadata.synthetic=true` must be
  accurate (OpenMathInstruct-2 solutions are Llama3.1-405B-Instruct generated;
  Open-Platypus contains model-generated content but is HOLD).
- Synthetic data must not exceed the verified anchor share for E1/E2 content.
  For E3 frontier signal, synthetic augmentation is acceptable but must be
  quality-gated and labeled.
- Open-Platypus is excluded until license filtering resolves; no unverified
  sources enter training views.

### 4.4 Provenance requirement

Every training record must carry, per `docs/expert_record_schema_v0.1.md`:

- `source.source_id` (registry id) + `source.name` + `source.url`
- `source.license` + resolved record-level `license`
- `provenance.original_id` (upstream id or documented content hash)
- `provenance.ingestion_pipeline` + ordered `transformations`
- `verification.method/status/evidence`
- extraction metadata (per-source fields)

Provenance completeness target: **100%** on promoted records (measured 1.0 in
all GO calibrations).

### 4.5 License requirement

- Permissive or Atlas-approved licenses only: MIT, Apache-2.0, CC-BY-4.0,
  arXiv non-exclusive, CC-BY-SA-4.0 (with attribution handling).
- No NC/restricted licenses (e.g., CC-BY-NC-SA) without an explicit policy
  exception. NC sources are rejected at the gate.
- License is verified at source level (registry status VERIFIED) and record
  level (`license != unknown`).
- No `unknown` licenses in curated expert data.

---

## 5. Training Assumptions

### 5.1 Target model size

- ~300M parameter models (base + optional LoRA/QLoRA adapters).
- The existing `configs/training/qlora_qwen3_8b.yaml` is a REFERENCE template
  only; training is paused. A 300M target is consistent with the same
  pipeline (model-agnostic dataset, chat-template conversion).

### 5.2 Hardware: single RTX 5070 12GB

- Single-GPU consumer environment: RTX 5070, 12GB VRAM.
- A 300M model in fp16 is ~0.6GB of weights; bf16 similar. Even with
  optimizer states and activations, a 300M full-fine-tune or QLoRA run fits
  comfortably in 12GB (8B QLoRA reference is heavier and is explicitly
  paused).
- Inference for a single 300M model is trivially feasible on 12GB.

### 5.3 Multiple specialist loading concept

- Two or more 300M specialists can be resident simultaneously on 12GB:
  - e.g., 3 × 300M fp16 checkpoints ≈ 1.8GB weights; KV cache and
    activations per request are small at this size.
  - Adapter-based specialists (shared base + per-domain LoRA) reduce memory
    further: one base 300M + N small adapters.
- Concretely: load base model once, hot-swap domain adapters per routed
  request, or keep 2–3 full checkpoints pinned.

### 5.4 Orchestrator routing concept

- Routing is a classification step, not generation:
  - domain classifier over user prompt → specialist selector.
  - Options: (a) small fine-tuned router (0.5–1B), (b) embedding similarity
    to per-domain exemplars, (c) rule-based fallback for unambiguous domains.
- Routing must be evaluated for precision (correct domain) and coverage
  (no domain → default/refusal), not for answer quality.
- The orchestrator itself is out of scope for the data plan beyond requiring
  per-domain training views.

---

## 6. Constraints

1. **No training yet.** This document is strategy only; the training pause
   in `configs/training/qlora_qwen3_8b.yaml` remains in force.
2. **No dataset expansion yet.** Calibration samples (100 records per GO
   source) are the only acquired data; no 10K pilot, no full acquisition.
3. **No unverified sources.** Only VERIFIED registry sources and GO
   calibration sources enter this plan. Open-Platypus is HOLD; AIME/AMC
   NC sets and unresolved corpora (Proof-Pile) are rejected.
4. **No dataset modifications.** This strategy changes no curated data, no
   raw data, no release artifacts.
5. Any future training run must pass the standing gates: license check →
   quality filter → difficulty scoring → expert layer → training view.

---

## Next Steps (not started; for approval)

1. Decide Open-Platypus license filtering policy (HOLD resolution).
2. Approve 10K pilot scope for the three Priority 1 GO sources.
3. Define per-specialist training-view generation from the expert schema.
4. Specify 300M base-model choice and adapter strategy (training-time).
5. Build per-domain evaluation harness (extend `evaluation/`).
