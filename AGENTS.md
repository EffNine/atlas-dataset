# AGENTS.md — Atlas Project Context for Future AI Agents

> **Purpose:** Permanent project context for any AI agent working in this repository.
> **Status:** Canonical reference — do not override with older snippets.
> **Last updated:** 2026-08-07

---

## 1. Atlas Project Mission

Atlas is a **model-agnostic, long-term knowledge foundation** for training and evaluating 8B-class LLMs. The canonical storage format is plain JSONL; model-specific formats are generated downstream and never stored as the source of truth. The dataset is the long-term asset. Models are replaceable.

Core goals:
- Reproducible, versioned dataset generation from raw sources.
- Commercial-safe licensing with mandatory provenance on every record.
- Human-in-the-loop governance with automated quality, provenance, revision, validation, and release gates.
- Deterministic processing across all pipeline stages.
- Modular architecture so source types, quality dimensions, and model targets can be added without modifying existing code.

---

## 2. Overall Architecture Summary

### Repository Layout
```
atlas-dataset/
├── README.md                      # Project overview, quick start, status
├── AGENTS.md                      # This file — permanent agent context
├── PROJECT_STATE.md               # Exact current snapshot
├── ATLAS_SUBSYSTEM_CONTRACTS.md   # Extracted subsystem contracts
├── IDEA.md                        # Hermes ecosystem vision
├── docs/                          # Design, ADRs, specs, releases, governance, evaluation, training, reports
│   └── research/                  # Research Protocol v1.0, experiment matrix, benchmark plan, risk register
├── raw/                           # Original sources (immutable)
├── processing/                    # Cleaners / dedup / validators / converters
├── curated/                       # Versioned, reviewed output
│   ├── v0.1/                      # Scaffold + synthetic test data
│   └── v0.2/                      # Expanded pilot + phase4b expansion
├── evaluation/                    # Benchmarks / test_sets
├── metadata/                      # Sources, categories, acquisition logs, releases, evaluation reports
├── schemas/                       # JSON Schema for dataset, chat, knowledge objects, quality reviews
├── configs/                       # Training + formatting templates
├── migrations/                    # DB/schema migrations with versioned runner
├── governance/                    # Phase reports, continuity baselines, metadata sync
├── review/                        # Human review artifacts
├── review_queue/                  # Queue state
├── knowledge_packs/               # Knowledge pack collections, manifests
├── training_views/                # Per-model training view placeholders
├── scripts/                       # All pipeline code
│   ├── atlas.py                   # CLI entry point
│   ├── automation/                # Pipeline agents, state machine, approval gate
│   ├── automation_runner.py       # Automation pipeline CLI
│   ├── acquisition_engine/        # AQL, checkpoint/resume, integrity, lifecycle, release, versioning
│   ├── downloader/                # v1.6 source adapters + cache
│   ├── etl/                       # v1.7 extract → normalize → clean
│   ├── transform/                 # v1.8 training-type transformers
│   ├── view_builder/              # v1.8 model-family training views
│   ├── release_builder/           # v1.8 release bundles
│   ├── parallel/                  # v1.9 thread-pool worker
│   ├── incremental/               # v1.9 per-source stage state
│   ├── evaluation_engine/         # Evaluation framework
│   ├── training_view_engine/      # Training view generation
│   └── ...
└── experiments/                   # Controlled pilots and ad-hoc experiments
    ├── lora_pilot_math_v0.1/      # Phase 5B.1 math LoRA pilot artifacts
    └── lora_pilot_code_v0.1/      # Phase 5B.2 code LoRA pilot artifacts
```

### Data Lifecycle
```
Raw Knowledge
   ↓ Acquisition
   ↓ Transformation
   ↓ Intelligence
   ↓ Training Views
   ↓ Evaluation
   ↓ Release
   ↓ Model Training
   ↓ Knowledge Feedback
```

### Automation Layer
- State machine with 7 states and mandatory `WAITING_HUMAN_APPROVAL` before release.
- Agents: Acquisition, Quality, Provenance, Validation, Revision, Release, Failure Recovery.
- Never writes to `curated/`, `raw/`, `review_queue/`, or `training_views/`. Pipeline state lives under `metadata/`.

---

## 3. Current Development Phase

- **Current phase:** Phase 6.1 completed (Atlas Research Protocol v1.0).
- **Status:** GO
- **Next recommended step:** Execute `docs/research/benchmark_plan.md` (first gate: expand math/code eval splits to N ≥ 30).
- **Primary known issue:** Evaluation correctness metric requires improvement; current eval splits are underpowered.

### Completed Milestones
- Dataset v1.0 frozen
- Release pipeline completed
- Automation layer completed
- Intelligence layer completed
- Baseline evaluation completed
- RTX 5070 inference verified
- Phase 5A.4 math evaluator robustness patch (nested-brace extraction)
- Phase 5B.1 math LoRA pilot + QEE v2 analysis
- Phase 5B.2 code LoRA pilot
- Phase 6.1 Atlas Research Protocol v1.0 (`docs/research/`)

---

## 4. Active Tasks

- Execute Research Protocol v1.0 for all future experiments (naming, metadata, reproducibility checklist).
- Expand math/code eval splits to N ≥ 30 (first benchmark gate in `docs/research/benchmark_plan.md`).
- Run aiml family baseline evaluation.
- Improve evaluation correctness metric.
- Maintain dataset quality gate calibration against human review signals.

---

## 5. Important Rules and Constraints

1. **Immutable data protection:** Never modify `curated/`, `raw/`, `review_queue/`, or `training_views/` directly. Corrections create new versions.
2. **Fail closed:** When any invariant is uncertain, stop. Do not guess or infer missing values.
3. **Human approval boundary:** Automation may prepare decisions. It may not bypass human approval for releases, license exceptions, or governance overrides.
4. **Provenance first:** Every record must carry complete provenance. If provenance is lost, the artifact is untrusted.
5. **Deterministic execution:** Given the same input and config, every stage produces the same output and checksum.
6. **Reproducible releases:** Every release can be rebuilt from raw sources using pipeline code and configuration.
7. **No fabricated data:** Never invent URLs, author names, post titles, license evidence, metrics, or external facts. Use explicit placeholders like `[HUMAN MUST SUPPLY]`.
8. **Baseline audit rule:** If expected view artifacts are missing on disk, report exact missing paths/IDs and stop. Do not generate fake counts, placeholder hashes, or invented distributions.
9. **CUDA/runtime guard:** If verification is unavailable, create explicit HOLD artifacts with null metrics and real blocker notes. Do not invent baseline numbers or claim evaluation ran.

---

## 6. Development Hardware

| Role | Hardware | Notes |
|------|----------|-------|
| Development workhorse | Ubuntu-24.04 bare metal (devpc) | 16 proc / 30GB RAM / 8GB swap; `/mnt/d/atlas-dataset` |
| Training / inference | NVIDIA GeForce RTX 5070 12GB | Primary CUDA target for pilots and training |
| Remote control | Mac → devpc via SSH (Tailscale 100.103.161.46) | Mac is the control surface only |

### Dev Box (devpc)
- **OS:** Ubuntu-24.04
- **CPU:** 16 cores
- **RAM:** 30 GB
- **Swap:** 8 GB
- **Storage:** `/mnt/d/atlas-dataset`
- **SSH:** `ssh afnan@100.103.161.46` (device: devpc)
- **Tooling:** `gh` v2.45.0 + `hf` CLI authenticated as `EffNine`

---

## 7. Model Information

| Model | Role | Status |
|-------|------|--------|
| Qwen/Qwen2.5-7B-Instruct | Baseline / pilot model | Used in LoRA validation pilot |
| Future 8B-class models | Training targets | Qwen, Llama, DeepSeek, Mistral, Gemma supported |

### LoRA Pilot Configuration
- **Base model:** `Qwen/Qwen2.5-7B-Instruct`
- **Quantization:** 4-bit NF4 (`bnb_4bit_quant_type: "nf4"`, `load_in_4bit: true`)
- **Compute dtype:** bfloat16
- **LoRA:** `r=8`, `lora_alpha=16`, `lora_dropout=0.05`, target modules: `q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj`
- **Training:** `max_steps=60`, `per_device_train_batch_size=1`, `gradient_accumulation_steps=8`, `lr=2e-4`, cosine scheduler, `bf16=true`, `gradient_checkpointing=true`, `max_seq_length=1024`
- **Seed:** 42

---

## 8. Dataset Information

| Version | Status | Records | Notes |
|---------|--------|---------|-------|
| v0.1 | scaffold + synthetic test data | 1000 target | Clean structure + reproducible pipeline |
| v0.2 | active | 663 curated | Expanded pilot + phase4b expansion |
| v1.0 | released | — | Automation pipeline integrated |

- **Canonical format:** JSONL, one JSON object per line.
- **Supported model formats:** Qwen ChatML, Llama Instruction, Mistral Instruct, Gemma Instruct, ShareGPT, Alpaca.
- **Quality threshold:** ≥ 7 on the 0–10 scale.
- **All sources classified:** Yes, by difficulty and category.

---

## 9. Evaluation Methodology

### Current Evaluation Engine
- Location: `scripts/evaluation_engine/`
- Layers: Knowledge Quality, Safety, Engineering.
- Read-only by design. No network access during execution.
- Outputs: `docs/evaluation/` and `metadata/` only.

### Known Calibration Issue
- Phase 5B QEE-Human Alignment Report (`docs/evaluation/qee_human_alignment_report.md`) documents a **systematic positive bias of +2.14 points** versus human reviewers.
- The QEE shows 0% exact agreement and 2% within-1 agreement on reviewed records.
- **Conclusion:** QEE is not ready for unsupervised automated approval in its current form.
- **Action required:** Phase 5C/QEE recalibration is needed after evaluation infrastructure validation.

### LoRA Pilot Evaluation
- Experiment: `experiments/lora_pilot_math_v0.1/`
- Evaluation metrics tracked: `correctness`, `reasoning_quality`, `hallucination_rate`, `answer_format_consistency`
- Current status: HOLD pending CUDA-capable runtime for actual inference.
- Baseline/post-training artifacts exist as structured JSON with explicit HOLD placeholders where metrics could not be measured.

---

## 10. Coding Conventions

- **Language:** Python 3.11 preferred.
- **Dependency philosophy:** Prefer Python standard library. External dependencies (`jsonschema`, `datasets`, `transformers`, `peft`, `bitsandbytes`, `trl`, `accelerate`) are used only where stdlib alternatives do not exist, and are wrapped behind importable interfaces.
- **Script style:** Deterministic, reproducible, stdlib-only where practical.
- **State machine:** Strict transition rules. `VALIDATION → RELEASED` is forbidden; pipeline must pass through `WAITING_HUMAN_APPROVAL`.
- **Checksums:** SHA-256 on sorted, serialized JSON.
- **Naming:** snake_case for Python files and functions.
- **Documentation:** Markdown in `docs/`. ADRs required for contract-level changes.
- **Commit style:** Conventional commits preferred. Per-version commits for dataset/release changes.

---

## 11. Things Future Agents Must NOT Do Without Approval

1. **Do not modify core project code or datasets** unless explicitly requested by the user.
2. **Do not change configs** without approval.
3. **Do not modify `curated/`, `raw/`, `review_queue/`, or `training_views/`** directly.
4. **Do not promote a release candidate to release** without human approval.
5. **Do not run model training or fine-tuning** unless explicitly authorized.
6. **Do not bypass governance gates** (review, lineage, provenance, license, quality).
7. **Do not invent metrics, URLs, authors, licenses, or external facts.** Use `[HUMAN MUST SUPPLY]` placeholders.
8. **Do not claim evaluation ran** when CUDA/runtime was unavailable. Create HOLD artifacts with null metrics instead.
9. **Do not commit, push, or rewrite history** unless explicitly asked.
10. **Do not read, print, or commit secrets.** Leave `.env` and credential files alone.

---

## 12. Quick Reference for New Agents

When starting work in this repository:

1. Read this file (`AGENTS.md`).
2. Read `PROJECT_STATE.md` for the exact current snapshot.
3. Read the latest reports under `docs/reports/` and `docs/evaluation/`.
4. Understand the current phase and whether training/release gates are blocked.
5. Do not modify frozen assets without explicit approval.
6. Follow the Research Protocol v1.0 for any experiment: `docs/research/experiment_protocol_v1.md` (naming, metadata, reproducibility checklist, success/failure criteria), `docs/research/experiment_matrix.md`, `docs/research/benchmark_plan.md`, `docs/research/risk_register.md`.
7. Follow the Engineering Handbook: `docs/project/atlas_engineering_handbook.md`.
8. Follow the Project Context: `docs/project/atlas_project_context.md`.

---

*This file is maintained by the Atlas lead agent. Update it when phase, architecture, or governance rules change.*
