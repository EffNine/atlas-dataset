# AGENTS.md — Atlas Project Context

> **Status:** Canonical — update when phase or governance rules change.
> **Last updated:** 2026-08-15
> **Purpose:** Single onboarding and handoff document for AI agents working on Atlas.

---

## 1. What Atlas Is

### 1.1 Core Identity

Atlas is a **governed AI data and training infrastructure platform**. It is no longer simply a dataset-generation project.

The long-term pipeline is:

```
Raw Sources
  → Acquisition
  → ETL / Normalization
  → Deduplication
  → Curation
  → Intelligence / Classification
  → Quality Validation
  → Evaluation
  → Governance / Approval
  → Release
  → Training Data
  → Model Training
  → Model Evaluation
```

The ultimate objective is to provide reliable training infrastructure for models such as **atan-v1**.

### 1.2 What Atlas Is NOT

- Atlas is not a model training project. It produces training data, not models.
- Atlas is not a one-shot dataset generator. It is a governed, reproducible pipeline.
- Atlas is not a collection of independent scripts. It is a system with architectural boundaries.

### 1.3 Core Principles

**Quality over quantity.** Atlas optimizes for:
- quality + traceability + diversity + correctness + reproducibility

**Model-agnostic.** The dataset is the long-term asset; models are replaceable. The canonical storage format is plain JSONL. Model-specific formats (Qwen ChatML, Llama Instruction, etc.) are generated downstream and never stored as the source of truth.

**Governance over speed.** Every state transition must pass through defined gates. No short-circuits.

---

## 2. What Atlas Is Building Toward: atan-v1

Atlas is intended to become the data infrastructure behind **atan-v1**.

atan-v1 is a Malaysian-oriented expert software engineering / architecture / agentic model with capabilities in:
- Software engineering
- Architecture planning
- Long-horizon coding
- Agentic workflows
- Software project advisory
- Malaysian communication style

**Key relationship:** Atlas is the data/training infrastructure. atan-v1 is a downstream model objective. Atlas should remain useful as general AI training infrastructure even if the target model changes.

Do not couple Atlas architecture directly to one specific model implementation.

---

## 3. Current Project State

### 3.1 Verified Current State (as of 2026-08-15)

| Item | Status |
|------|--------|
| Dataset v1.0 | **Released** — 9,515,938 records across 9 categories |
| v1.0 Release | `metadata/releases/v1.0_release.json` — status: final |
| Release chain | Hash-linked from v0.1 through v1.0-RC1/RC2 to v1.0 |
| Phase 6.1 | **Completed** — Atlas Research Protocol v1.0 adopted |
| Intelligence Layer v1.1 | **Complete** — 2,575,622 records classified (difficulty L1-L5) |
| Automation Layer v1.0 | **Implemented** — 11-state pipeline FSM |
| QEE v2 | **Frozen** for Phase 8 experiments |
| Pilot v0.2 data | **Available** — 4,499 records (math 1000, code 401, general 1098, systems 2000) |
| model-eval-finetune | **Separate project** — Qwen3-8B LoRA pipeline ready |

### 3.2 Current Blockers

| Issue | Severity | Details |
|-------|----------|---------|
| Training Readiness | **BLOCKED** | 5 of 6 gates blocked (review, lineage, provenance, license, quality). Evaluation gate is CONDITIONAL. |
| Architecture audit | **IN PROGRESS** | Deep audit of repository to identify authoritative vs legacy vs duplicated subsystems |

### 3.3 Current Project Priority

> **Architectural clarity and consolidation before adding more complexity.**

The current phase is: **Repository Archaeology + Architecture Audit + State/Ownership Clarification**

The goal is to establish a reliable architectural foundation before continuing major feature expansion.

---

## 4. Repository Structure

### 4.1 Directory Map

| Path | Purpose | Write-safe? |
|------|---------|-------------|
| `raw/` | Original sources — **immutable** | ❌ Never write |
| `raw/pilot/` | Pilot ingestion seed data (exception to raw/ immutability) | ✅ Yes |
| `processing/` | Cleaners, dedup, validators, converters | ✅ Yes |
| `curated/` | Versioned, reviewed output | Managed — new versions only via pipeline |
| `evaluation/` | Benchmark and eval-set definitions | ✅ Yes |
| `metadata/` | Sources, categories, acquisition logs, releases, pipeline state | ✅ Yes |
| `schemas/` | JSON Schema definitions | ✅ Yes (read-only preferred) |
| `config/` | Operational/runtime configuration (e.g. `parallelism.yaml`) | ✅ Yes |
| `configs/` | Training + formatting templates (e.g. `formatting/templates.json`) | ❌ Never change without approval |
| `migrations/` | DB/schema migrations with versioned runner | ✅ Yes |
| `governance/` | Phase reports, continuity baselines | ✅ Yes |
| `review/` | Human review artifacts | ✅ Yes |
| `review_queue/` | Queue state (pending, approved, rejected, needs_revision) | Managed — pipeline writes approved.jsonl |
| `knowledge_packs/` | Knowledge pack collections and manifests | ✅ Yes |
| `training_views/` | Per-model training view placeholders | Managed — engine-generated only |
| `tmp/` | Temporary working files | ✅ Yes |
| `docs/` | Design, ADRs, specs, releases, governance | ✅ Yes |
| `scripts/` | All pipeline code (~223 Python files, ~62K lines) | ✅ Yes |
| `tests/` | Test suite (1,269 tests) | ✅ Yes |
| `experiments/` | Controlled pilots and ad-hoc experiments | ✅ Yes |
| `releases/` | Frozen release bundles | ❌ Never modify released artifacts |
| `pilot/` | Pilot dataset versions (v0.1, v0.2) — training-ready data | ✅ Yes |
| `artifacts/` | Pilot training artifacts (adapters, checkpoints) | ✅ Yes |
| `reports/` | Audit reports, phase reports, analysis | ✅ Yes |

**Any script writing outside these approved roots must fail fast.** See `scripts/atlas_paths.py:is_write_safe()`.

### 4.2 Subsystem Directory Map

| Directory | Subsystem | Status |
|-----------|-----------|--------|
| `scripts/acquisition_engine/` | Data acquisition engine | ✅ Implemented |
| `scripts/automation/` | Pipeline automation layer (11-state FSM) | ✅ Implemented |
| `scripts/automation_runner.py` | CLI orchestration | ✅ Implemented |
| `scripts/downloader/` | Multi-source downloader (arxiv, github, huggingface, stackexchange, documentation) | ✅ Implemented |
| `scripts/etl/` | ETL pipeline (extractors, normalizer, cleaners) | ✅ Implemented |
| `scripts/evaluation_engine/v2/` | QEE v2 (math/code/semantic eval) | ✅ Implemented, frozen |
| `scripts/evaluation_research/` | Evaluation research (calibration, matrix, state machine) | ✅ Implemented |
| `scripts/experiment_framework/` | Experiment protocol implementation | ✅ Implemented |
| `scripts/expert_pipeline/` | Expert dataset acquisition pipeline | ✅ Implemented |
| `scripts/intelligence/` | Difficulty classification layer | ✅ Implemented v1.1 |
| `scripts/metadata/` | Metadata synchronization | ✅ Implemented |
| `scripts/parallel/` | Universal adaptive scheduler | ✅ Implemented |
| `scripts/release/` | Release builder and promotion | ✅ Implemented |
| `scripts/release_builder/` | Release bundle builder | ✅ Implemented |
| `scripts/training_view_engine/` | Training view generation engine | ✅ Implemented |
| `scripts/view_builder/` | Model-format view builder | ✅ Implemented |
| `scripts/progressive_expansion.py` | Legacy expansion (superseded) | ⚠️ LEGACY |
| `scripts/progressive_expansion_v2.py` | Legacy expansion v2 (superseded) | ⚠️ LEGACY |
| `scripts/tui_backend.py` | TUI backend | ⚠️ Known violation (hardcoded workers) |
| `scripts/atlas.py` | Main CLI (2,467 lines) | ✅ Core interface |
| `scripts/atlas_tui.py` | Terminal UI | ✅ Implemented |
| `scripts/validate_architecture.py` | Architecture governance enforcer | ✅ Critical |
| `scripts/convert_format.py` | Multi-format converter | ✅ Implemented |
| `scripts/dedup_dataset.py` | Deduplication | ✅ Implemented |
| `scripts/clean_dataset.py` | Dataset cleaning | ✅ Implemented |
| `scripts/quality_score.py` | Quality scoring | ✅ Implemented |
| `scripts/provenance_resolver.py` | Provenance resolution | ✅ Implemented |
| `scripts/training_readiness.py` | Training readiness gate | ✅ Implemented |
| `scripts/e2e_pipeline.py` | End-to-end pipeline v2.0 | ✅ Implemented |
| `scripts/pilot_train.py`, `scripts/pilot_train_v2.py` | Pilot training scripts | ✅ Implemented |
| `scripts/pilot_eval.py`, `scripts/pilot_eval_v2.py` | Pilot evaluation scripts | ✅ Implemented |
| `scripts/p0_acquire.py`, `scripts/p0_acquisition.py`, `scripts/p0_execute.py`, `scripts/p0_final.py` | Phase 0 acquisition scripts | ✅ Implemented |
| `scripts/p1_acquisition.py` | Phase 1 acquisition | ✅ Implemented |
| `scripts/build_pilot_v2.py` | Pilot v2 builder | ✅ Implemented |
| `scripts/build_clean_math_eval.py` | Clean math eval builder | ✅ Implemented |
| `scripts/credential_helper.py` | Credential management | ✅ Implemented |
| `scripts/eval_dataset.py` | Dataset evaluation CLI | ✅ Implemented |
| `scripts/freeze_calibration_baseline.py` | Calibration baseline freezing | ✅ Implemented |
| `scripts/gen_calibration_sample.py` | Calibration sample generation | ✅ Implemented |
| `scripts/gen_postmortem.py` | Postmortem generation | ✅ Implemented |
| `scripts/metadata_sync.py` | Metadata synchronization | ✅ Implemented |
| `scripts/publish_agent.py` | Publishing agent | ✅ Implemented |
| `scripts/validate_dataset.py` | Dataset validation | ✅ Implemented |
| `scripts/validate_knowledge_object.py` | Knowledge object validation | ✅ Implemented |
| `scripts/validate_quality_engine.py` | Quality engine validation | ✅ Implemented |
| `scripts/extract_wiki_*.py` | Wiki extraction scripts | ✅ Implemented |

---

## 5. Architectural Philosophy

### 5.1 The Central Question

The question is no longer:

> "Can this script run?"

It is:

> "Does this capability belong in the Atlas architecture, what owns it, what state does it produce, what evidence proves it succeeded, and can the operation be reproduced and resumed?"

### 5.2 State vs Artifact vs Evidence

Atlas must rigorously distinguish between three categories:

**State** — What the system officially believes has happened. Stored in authoritative JSON files. Examples:
- `metadata/releases/v1.0_release.json` — the system's record that v1.0 was released
- `metadata/pipeline_state/<id>.json` — the system's record of pipeline progress
- `metadata/intelligence/classification_summary_v1.1.json` — the system's record of classification results

**Artifact** — A file/output produced by some operation. Examples:
- `curated/v1.0/atlas_v1.0.jsonl` — the released dataset file
- `experiments/{id}/checkpoints/` — a trained LoRA adapter
- `metadata/views/v1.0/qwen/train.jsonl` — a generated training view

**Evidence** — Information demonstrating that an operation actually succeeded. Examples:
- SHA-256 checksums in release manifests
- Agent output logs
- Checksum verification reports
- Per-example evaluation results

**Critical rule:**
> Artifact existence alone is not proof of successful pipeline execution.

Always verify against authoritative state, never assume success from file presence.

---

## 6. Source of Truth Hierarchy

When multiple files represent the same conceptual state, this is the precedence order:

1. **Release manifest** — `metadata/releases/<version>_release.json` (authoritative; immutable once written)
2. **Pipeline state** — `metadata/pipeline_state/<pipeline-id>.json` (authoritative for active pipeline runs)
3. **Approved records** — `review_queue/approved.jsonl` (authoritative list of records approved for release)
4. **Curated data** — `curated/v*/` (versioned, immutable after freeze)
5. **Raw sources** — `raw/` (immutable; original sources)
6. **Intelligence metadata** — `metadata/intelligence/*.json` (difficulty classifications, append-only)
7. **Evaluation results** — `metadata/evaluation/*.json` (frozen after computation)

---

## 7. The Desired Execution Model

A healthy Atlas operation should conceptually follow:

```
Input
  → Validate
  → Execute
  → Produce Artifact
  → Validate Artifact
  → Record Evidence
  → Update Authoritative State
  → Require Approval where appropriate
  → Publish / Release
```

Not every operation necessarily needs every step. The important principle is that execution, evidence, state and release should be explicit.

The system should be:
- **Reproducible** — same inputs → same outputs
- **Inspectable** — you can see what happened at every stage
- **Resumable** — failures can be recovered from
- **Auditable** — every transition has evidence
- **Failure-aware** — failures are diagnosed, not silently swallowed

---

## 8. Major Subsystems in Detail

### 8.1 Foundation Layer (`scripts/atlas_constants.py`, `scripts/atlas_schema.py`, `scripts/atlas_paths.py`)

**Purpose:** Single sources of truth for all shared constants, schema definitions, and path resolution.

**Ownership:**
- `atlas_constants.py` — Categories, types, roles, lifecycle states, license utilities
- `atlas_schema.py` — Schema field sets, validation patterns
- `atlas_paths.py` — Path resolution, root discovery, write-safety enforcement

**Key invariant:** No other module may redefine these constants. `validate_architecture.py` enforces this.

### 8.2 Automation Layer (`scripts/automation/`)

**Purpose:** Pipeline orchestration with enforced state transitions and human approval gates.

**Implementation:**
- `state_machine.py` — 11-state FSM (`INGESTED → QUALITY_CHECK → PROVENANCE_CHECK → CONTENT_REVISION → VALIDATION → WAITING_HUMAN_APPROVAL → READY_FOR_RELEASE → RELEASED`, plus `FAILED`, `CANCELLED`, `RELEASE_REJECTED`)
- `approval_gate.py` — Enforces human approval before `RELEASED`
- `pipeline_orchestrator.py` — Composes agents into pipeline runs
- Agent modules: `acquisition_agent.py`, `provenance_agent.py`, `quality_agent.py`, `revision_agent.py`, `validation_agent.py`, `release_manager.py`, `failure_recovery.py`

**State storage:** `metadata/pipeline_state/<pipeline-id>.json` — written ONLY by `StateMachine._persist()`

**CLI entry point:** `python -m scripts.automation_runner <command> --pipeline-id <id>`

**Key invariant:** `VALIDATION → RELEASED` transition is forbidden. Must pass through `WAITING_HUMAN_APPROVAL` first.

### 8.3 Acquisition Engine (`scripts/acquisition_engine/`)

**Purpose:** Data acquisition from diverse sources with lifecycle tracking.

**Implementation:**
- `engine.py` — Core acquisition orchestration
- `aql.py` — Atlas Query Language (SQL-like querying over records)
- `lifecycle.py` — Record lifecycle state machine (`raw → processing → curated → review → approved → released → archived → rejected`)
- `release.py` — Release composition and semantic diffing
- `knowledge_pack.py` — Knowledge pack management
- `knowledge_collection.py` — Collection management
- `versioning.py` — Version management for curated data
- `checkpoint.py` — Checkpoint management
- `integrity.py` — Data integrity verification
- `dataset_diff.py` — Dataset comparison

**Key property:** The `LifecycleTracker` generates `metadata/lifecycle_state.json` at runtime. The file does not pre-exist.

### 8.4 ETL Pipeline (`scripts/etl/`)

**Purpose:** Extract, transform, and normalize data from raw sources into canonical Atlas format.

**Implementation:**
- `pipeline.py` — ETL orchestration
- `extract_agent.py` — Extraction orchestration
- `normalizer.py` — Canonical normalization
- `extractors/` — Source-specific extractors (parquet, json, text)
- `cleaners/` — Data cleaning modules
- `types.py` — Shared type definitions

**Output:** Transformed records written to `metadata/etl/<source-id>/transformed_atlas.jsonl`

### 8.5 Downloader (`scripts/downloader/`)

**Purpose:** Multi-source data download with caching and scheduling.

**Implementation:**
- `download_agent.py` — Download orchestration
- `cache.py` — Download caching
- `http_util.py` — HTTP utilities
- `scheduler_tasks.py` — Scheduled download tasks
- `adapters/` — Source-specific adapters:
  - `arxiv.py` — arXiv paper downloads
  - `github.py` — GitHub repository downloads
  - `huggingface.py` — Hugging Face dataset downloads
  - `stackexchange.py` — StackExchange data downloads
  - `documentation.py` — Documentation site downloads

### 8.6 Intelligence Layer (`scripts/intelligence/`)

**Purpose:** Assign per-record difficulty levels (L1–L5) and reasoning types for curriculum-aware training views.

**Implementation:**
- `difficulty_analyzer.py` — Core classifier (deterministic, stdlib-only)
- `batch_classify_v2.py` — Parallel runner for full-source classification
- `adaptive_scheduler.py` — Resource-aware scheduling
- `archive/production_v1_1/` — Legacy production classifiers

**Current state:** v1.1 complete — 2,575,622 records classified, 0 remaining unknown.

**Outputs (append-only, versioned):**
- `metadata/intelligence/classification_summary_v1.1.json`
- `metadata/intelligence/difficulty_distribution_v1.1.json`
- `metadata/intelligence/difficulty_taxonomy_v1.json`
- `metadata/intelligence/intelligence_schema_v1.json`

**Key properties:**
- Read-only on canonical records — never modifies input data
- Crash-safe: appends per-source output immediately, deletes per-source file on completion
- Deterministic: same input → same classification every time
- Skips already-classified sources on resume (`--skip <labels>`)

### 8.7 Evaluation System (`scripts/evaluation_engine/`)

**Purpose:** Read-only evaluation of model outputs against gold standards.

**Implementation:**
- `v2/engine.py` — QEE v2 dispatcher (math/code/semantic)
- `v2/math_eval.py` — Expression-equivalence checking
- `v2/code_eval.py` — Patch alignment + syntax checking
- `v2/semantic_eval.py` — Rubric-based evaluation
- `v2/calibration.py` — v1-vs-v2 comparison and affine calibration fitting
- `registry.py` — Evaluation benchmark registry
- `metrics.py` — Metric computation
- `report.py` — Evaluation reporting
- `runner.py` — Evaluation runner
- `leakage/` — Data leakage detection and auditing
- `generation_policy/` — Eval set generation policy

**Current state:** QEE v2 frozen for Phase 8 experiments. Eval sets in `evaluation/eval_sets/protocol_v2/`.

**Key rules:**
- Evaluation is **read-only and network-free** by design
- QEE v2 scores are **not** used for automated approval — human review required
- Known issue: QEE has systematic positive bias of +2.14 vs human reviewers
- **Never modify evaluation code to improve reported results** — investigate the cause instead
- Minimum eval split size: N ≥ 30 per family for any statistical conclusion

### 8.8 Evaluation Research (`scripts/evaluation_research/`)

**Purpose:** Research-grade evaluation tools for calibration, contamination analysis, and benchmark discovery.

**Implementation:**
- `artifacts.py` — Evaluation artifact management
- `benchmark_acquire.py` — Benchmark acquisition
- `benchmark_discover.py` — Benchmark discovery
- `calibration.py` — Model calibration analysis
- `cli.py` — CLI interface
- `contamination.py` — Data contamination detection
- `eval_set_builder.py` — Eval set construction
- `matrix_runner.py` — Evaluation matrix execution
- `state_machine.py` — Evaluation state management

### 8.9 Experiment Framework (`scripts/experiment_framework/`)

**Purpose:** Protocol-compliant experiment management for training and evaluation.

**Implementation:**
- `config.py` — `ExperimentConfig` — protocol-compliant naming and validation
- `registry.py` — `ExperimentRegistry` — track all experiments
- `scaffold.py` — `ExperimentScaffold` — generate experiment directory layout
- `training_runner.py` — `TrainingRunner` — base class with resume support
- `eval_runner.py` — `EvaluationRunner` — base class
- `manifests.py` — Experiment manifest management
- `metadata.py` — Experiment metadata handling
- `reproducibility.py` — Reproducibility checking
- `results.py` — `ResultRegistry` — aggregate + per-example results

**All experiment artifacts go under `experiments/{experiment_id}/` and never modify frozen dataset or release artifacts.**

### 8.10 Release System (`scripts/release/`, `scripts/release_builder/`)

**Purpose:** Build, verify, promote, and publish dataset releases.

**Implementation:**
- `join_release.py` — Join approved records into release JSONL
- `build_release_metadata.py` — Build release bundle metadata
- `promote_release.py` — Promote RC to final release (immutable — new manifest, same bytes)
- `verify_release.py` — End-to-end bundle verification
- `verify_sha256.py` — SHA-256 verification
- `generate_checksums.py` — Compute per-file SHA-256
- `compress_release.py` — zstd compression
- `download_release.py` — Release download
- `dedup_release.py` — Release deduplication
- `upload_huggingface.py` — Hugging Face publishing
- `update_release_index.py` — Release index updates
- `publish_promotion.py` — Promotion publishing
- `scheduler_tasks.py` — Release scheduling
- `audit_duplicates.py` — Duplicate auditing
- `common.py` — Shared release utilities
- `release_builder/__init__.py` — Release bundle builder

**Release Pipeline Flow:**
```
1. Build: acquire → download → etl → transform → views → release bundle
2. Verify: checksums, record counts, folder structure
3. Candidate: manifest written as RC (e.g. v1.0-RC1)
4. Human approval required
5. Promote: RC → final release (manifest chain continues, dataset bytes identical)
```

**Release Immutability (ADR-011):**
- Once a release manifest is written, its content is frozen
- RC manifests are immutable; promotion creates a **new** manifest (never modifies the RC)
- Corrections require a new release version, never in-place edits
- Release bundles in `releases/<version>/` are never modified after promotion
- The release chain is hash-linked: each manifest's `chain_hash` references the previous release's `chain_hash`

**Current releases:** v0.1, v0.2, v0.3, v1.0-RC1, v1.0-RC2, v1.0 (final)

### 8.11 Training View Engine (`scripts/training_view_engine/`, `scripts/view_builder/`)

**Purpose:** Generate model-specific training views from canonical Atlas records.

**Implementation:**
- `training_view_engine/filter.py` — Record filtering for training views
- `training_view_engine/generator.py` — View generation logic
- `training_view_engine/manifest.py` — View manifest management
- `training_view_engine/validator.py` — View validation
- `view_builder/__init__.py` — View builder (wraps `convert_format.py`)

**Supported formats:** qwen_chatml, llama_instruction, sharegpt, alpaca, mistral_instruct, gemma_instruct

**Output location:** `metadata/views/<version>/` (never `curated/`)

**Format templates:** `configs/formatting/templates.json`

### 8.12 Expert Pipeline (`scripts/expert_pipeline/`)

**Purpose:** Acquisition and processing of expert-level dataset sources.

**Implementation:**
- `runner.py` — Expert pipeline orchestration
- `quality.py` — Expert data quality assessment
- `review_assign.py` — Review assignment
- `review_sample.py` — Review sampling
- `validation.py` — Expert data validation
- `sonnet_input.py` — Sonnet input processing
- `report.py` — Expert pipeline reporting
- `util.py` — Shared utilities
- `constants.py` — Expert pipeline constants
- `adapters/` — Source adapters:
  - `base.py` — Base adapter
  - `openmath.py` — OpenMath adapter
  - `swebench.py` — SWE-bench adapter
  - `arxiv.py` — arXiv adapter

### 8.13 Parallel Processing (`scripts/parallel/`)

**Purpose:** Resource-aware parallel execution for classification, extraction, and other compute-heavy operations.

**Implementation:**
- `config.py` — Parallelism configuration (worker counts from `config/parallelism.yaml`)
- `models.py` — Parallel task models
- `monitor.py` — Resource monitoring
- `planner.py` — Task planning
- `registry.py` — Task registry
- `resource.py` — Resource management
- `runner.py` — Parallel runner
- `scheduler.py` — Universal scheduler

**Worker counts:** Read from `config/parallelism.yaml` via `parallel.config.resolve_worker_count()`. Hardcoding is a violation. Environment overrides: `ATLAS_WORKERS_<STAGE_UPPER>`. Hardware profiles: `ATLAS_PROFILE`.

### 8.14 Incremental State (`scripts/incremental/`)

**Purpose:** Track which sources have been processed to enable resumable pipelines.

**Implementation:** `scripts/incremental/` — State tracking for e2e pipeline incremental execution.

### 8.15 Metadata Sync (`scripts/metadata/`)

**Purpose:** Synchronize and validate metadata across the repository.

**Implementation:** `scripts/metadata/` — Includes `_training_cache/` and `acquisition_logs/`.

---

## 9. Architecture Layering (Enforced)

Modules are organized into 5 layers. **Lower layers must never import higher layers.** Enforced by `scripts/validate_architecture.py`.

| Layer | Modules |
|-------|---------|
| 1 — Foundation | `atlas_constants`, `atlas_schema`, `atlas_paths` |
| 2 — Validation & Lifecycle | `validate_dataset`, `quality_score`, `acquisition_engine.lifecycle` |
| 3 — Engines | `acquisition_engine.*`, `evaluation_engine.*`, `training_view_engine.*`, `payload_resolver` |
| 4 — CLI & Tooling | `atlas.py`, `clean_dataset.py`, `convert_format.py`, `eval_dataset.py`, etc. |
| 5 — Tests | anything under `tests/` |

**Key invariant:** `VALIDATION → RELEASED` transition is forbidden in the automation pipeline. Pipeline must pass through `WAITING_HUMAN_APPROVAL` first. Enforced by `scripts/automation/state_machine.py`.

---

## 10. State Management Rules

### 10.1 Pipeline State
- Stored in `metadata/pipeline_state/<pipeline-id>.json`
- Written ONLY by `StateMachine._persist()`
- Load with `StateMachine.load()` before making decisions
- **Never edit pipeline state files by hand**

### 10.2 Record Lifecycle
Records tracked via `metadata/lifecycle_state.json` — **generated at runtime** by `LifecycleTracker` in `scripts/acquisition_engine/lifecycle.py`. The file does not pre-exist; it is created on first lifecycle transition. States:
`raw → processing → curated → review → approved → released → archived → rejected`

Valid transitions enforced by `scripts/acquisition_engine/lifecycle.py`.

### 10.3 Approval Gate
- State stored in `metadata/pipeline_approvals.json` (gitignored; generated by `ApprovalGate`)
- Only transitions from `WAITING_HUMAN_APPROVAL` require human sign-off
- Agents cannot self-approve

### 10.4 Current Pipeline State
The default pipeline is currently in `CANCELLED` state (test cancellation). This is expected during the architecture audit phase.

---

## 11. Data Safety Rules

### 11.1 Never Modify (Read-Only Without Approval)
- `raw/` — original sources are immutable by design (exception: `raw/pilot/` is an approved ingestion workspace)
- `curated/` — corrections create new versions; never edit in-place
- `review_queue/` — queue state managed by pipeline, not scripts
- `training_views/` — generated by engine only
- `configs/` — affects all downstream consumers
- `releases/*/` — once promoted, release bundles are immutable (ADR-011)

### 11.2 Direct-Write-Safe Paths (agents may create/modify freely)
`metadata/`, `docs/`, `tmp/`, `raw/pilot/`, `migrations/`, `knowledge_packs/`, `processing/`, `evaluation/`, `scripts/`, `tests/`, `experiments/`, `pilot/`, `artifacts/`, `reports/`

### 11.3 Managed/Generated Paths (write-safe for pipeline, not for direct agent modification)
- `curated/` — versioned output; use `scripts/acquisition_engine/versioning.py` or the e2e pipeline
- `review_queue/` — queue state; use `scripts/automation_runner.py approve/deny`
- `training_views/` — placeholders; actual views generated by `scripts/view_builder/` to `metadata/views/<version>/`
- `releases/*/` — frozen bundles; use `scripts/release/promote_release.py` for promotion

### 11.4 Destructive Operations
Before any operation that could modify more than ~100 records:
1. Identify all dependencies (what reads this data?)
2. Run `scripts/validate_dataset.py --input <file> --stats` to understand composition
3. Create a backup under `tmp/` if the operation is not idempotent
4. Run relevant tests before and after

---

## 12. The Current Architecture Audit

### 12.1 What Is Being Audited

The repository contains a large number of scripts and multiple generations of architecture accumulated over many development phases. The current work determines:

1. What is authoritative.
2. What is duplicated.
3. What is legacy.
4. What is still actively used.
5. Which scripts should become proper subsystem interfaces.
6. Which state sources are authoritative.
7. Which artifacts are evidence versus source-of-truth state.
8. Where responsibilities overlap.
9. Where the architecture is fragile.
10. What should be consolidated, removed or redesigned.

### 12.2 Known Issues Discovered

| Issue | Severity | Location |
|-------|----------|----------|
| Duplicated constant `SUPPORTED_SCHEMA_VERSIONS` | VIOLATION | `scripts/evaluation_engine/generation_policy/versioning.py` |
| Duplicated `is_denied_license` function | KNOWN | `scripts/progressive_expansion.py`, `scripts/progressive_expansion_v2.py` |
| Hardcoded worker count | VIOLATION | `scripts/tui_backend.py:workers=0` |
| Self-test invariant failure | LOW | `release-chain-empty` — empty chain should be trivially verifiable |
| TUI test failures | LOW | 2 tests failing related to cancelled pipeline state |

### 12.3 Audit Methodology

The correct sequence is:

**Understand → Map → Verify → Decide → Consolidate → Remove**

NOT: **See duplicate → Delete**

Before any consolidation:
1. Trace all callers and consumers of each script/module
2. Identify the authoritative state source
3. Check test coverage
4. Determine migration risk
5. Plan incremental migration

---

## 13. The "No More Script Sprawl" Principle

One major architectural risk is continuing to solve every new problem by adding another script.

**Before adding a new script, determine whether an existing subsystem already owns the capability.**

Ask:
- Does this capability already exist?
- Is there an existing entry point?
- Is there an existing abstraction?
- Is the new script merely another orchestration layer?
- Is it duplicating state management?
- Is it creating another source of truth?
- Should the capability belong inside an existing subsystem instead?

**Prefer consolidation over parallel implementations.**

Legacy examples of sprawl:
- `progressive_expansion.py` and `progressive_expansion_v2.py` — superseded by `acquisition_engine/engine.py`
- Multiple generations of scheduler code — being consolidated into `scripts/parallel/`

---

## 14. Automated Governance

### 14.1 Architecture Validation

```bash
# Run architecture governance checks
python scripts/validate_architecture.py
```

Checks enforced:
- Check 3: Duplicated constants
- Check 4: Duplicated license functions
- Check 5: Duplicated schema definitions
- Check 6: Direct path construction (tracks hardcoded paths as debt)
- Hardcoded worker counts (ADR-013)

**Current status:** 2 violations found. These are known and tracked.

### 14.2 CLI Self-Test

```bash
# Run CLI self-test (invariants, license gate, AQL, release manager)
python scripts/atlas.py self-test
```

**Current status:** 1 invariant failing (`release-chain-empty`). This is a known issue.

### 14.3 Test Suite

```bash
# Full test suite (1269 tests, ~90s)
python -m pytest tests/ -q

# Single test file
python -m pytest tests/test_automation_layer.py -q
```

**Current status:** 1267 passed, 2 failed (TUI tests related to cancelled pipeline state).

### 14.4 Pre-commit Hooks

```bash
# Run pre-commit hooks (architecture + stabilization)
pre-commit run --all-files
```

---

## 15. Training Direction

### 15.1 Current Training Readiness

**Status: BLOCKED**

The training readiness gate (`scripts/training_readiness.py`) evaluates 4 dimensions:
- **Review readiness:** BLOCKED — 150 pending records, review cycle not completed
- **Data quality:** BLOCKED — No curated records in v0.2 pipeline
- **License:** BLOCKED — 6 denied licenses in source registry
- **Evaluation:** CONDITIONAL — Benchmarks exist but no verified/reproducible evaluations

**All 6 gates must pass before production training.**

### 15.2 Pilot Training Data

Pilot v0.2 data IS available for experimental training:
- `pilot/v0.2/math/train.jsonl` — 1,000 records (OpenMathInstruct-2, CC-BY-4.0)
- `pilot/v0.2/code/train.jsonl` — 401 records (SWE-smith-mini, MIT)
- `pilot/v0.2/general/train.jsonl` — 1,098 records
- `pilot/v0.2/systems/train.jsonl` — 2,000 records
- **Total: 4,499 records**

Format: `[user, assistant]` messages (no system prompt in raw data).

### 15.3 Training Infrastructure

**Atlas-side:**
- `scripts/pilot_train.py`, `scripts/pilot_train_v2.py` — Training scripts for pilot data
- `scripts/convert_format.py` — Converts canonical JSONL to model-specific formats
- `configs/training/qlora_qwen3_8b.yaml` — QLoRA training config template
- `scripts/view_builder/` — Generates model-specific training views
- `scripts/training_readiness.py` — Training readiness gate

**Separate project (`model-eval-finetune/`):**
- `scripts/train_lora.py` — Qwen3-8B 4-bit LoRA trainer using TRL
- `configs/lora_qwen3_8b_4bit.yaml` — Training config
- `configs/lora_qwen3_8b_agentic_4bit.yaml` — Agentic training config
- `scripts/convert_atlas_data.py` — Converts Atlas pilot data → model-eval-finetune SFT format
- `scripts/run_atlas_train.sh` — Launcher for Atlas-trained models
- Hardware: RTX 5070 12GB, torch 2.11 + CUDA ready

### 15.4 Existing Experiments

| Experiment ID | Status | Notes |
|--------------|--------|-------|
| `atlas-math-pilot-qwen7b-lora-v1` | Completed | Phase 5B.1 math LoRA pilot |
| `atlas-code-pilot-qwen7b-lora-v1` | Completed | Phase 5B.2 code LoRA pilot |
| `atlas-mixed-pilot-qwen7b-eval-v2` | Completed | Baseline evaluation |
| `atlas-math-pilot-nemotron8b-lora-v1` | TRAINING_COMPLETED | Nemotron 8B pilot |
| `atlas-math-pilot-nemotron-nano9b-v2-base-lora-v1` | BLOCKED | PEFT+NF4 incompatible with NemotronH mamba layers |
| `atlas-math-small-qwen7b-lora-transfer-v1` | COMPLETED | Phase 8-A math→code transfer |
| `phase7_scale` | Staged | M1(117)/M2(500)/M3(1000) scaling subsets |
| `phase8_transfer` | Staged | P8-A transfer subsets |

### 15.5 Experimental Training Config

Config for training on Atlas pilot data (in `model-eval-finetune/`):
- Code-only: `configs/lora_qwen3_8b_atlas_code_4bit.yaml` — 361 train / 40 val
- Mixed: `configs/lora_qwen3_8b_atlas_mixed_4bit.yaml` — 4,050 train / 449 val
- Base model: Qwen/Qwen3-8B, NF4 4-bit + double quant, bf16 compute
- LoRA: r=16, alpha=32, dropout=0.05
- Optim: paged_adamw_8bit, LR=2e-4, cosine schedule
- Max seq length: 2048

---

## 16. Experiment Protocol

All experiments must follow the **Atlas Research Protocol v1.0** (`docs/research/experiment_protocol_v1.md`), revised to v1.1 for cross-domain transfer measurement.

### 16.1 Naming Convention
```
atlas-{family}-{tier}-{target}-{scope}-v{n}
```
- `family`: math, code, aiml, mixed
- `tier`: pilot, small, medium, large, prod
- `target`: qwen7b, llama8b, deepseek8b, mistral7b, gemma7b, nemotron8b
- `scope`: base, lora, full, hp, scale, transfer, eval
- `v{n}`: iteration number

### 16.2 Mandatory Reproducibility Checklist (15 items)
1. Git commit recorded and `git status` clean
2. Training-view file SHA-256 recorded
3. Manifest records checksum matches on-disk
4. Eval split SHA-256 recorded
5. Model revision recorded (HF snapshot, not `refs/main`)
6. Full training config recorded
7. Random seed recorded and applied
8. Evaluation engine version + commit recorded
9. Inference config recorded
10. Hardware + software versions recorded
11. Baseline recorded on same eval split
12. Determinism spot-check completed
13. Outputs written only under `experiments/{id}/`
14. No dataset/view/release artifact modified
15. **Fail-closed:** if ANY check is unverifiable, record `HOLD` with null metrics — never fabricate numbers

### 16.3 Cross-Domain Transfer (Phase 8, v1.1)
- In-domain gain: `Δ_in^X = score(LoRA_X, E_X) − score(B, E_X)`
- Cross-domain gain: `Δ_cross^{X→Y} = score(LoRA_X, E_Y) − score(B, E_Y)`
- Transfer Ratio: `TR_{X→Y} = Δ_cross^{X→Y} / Δ_in^X`
- TR ≥ 1: strong positive transfer; 0 < TR < 1: positive but weaker; TR ≈ 0: neutral; TR < 0: negative
- If `Δ_in^X ≤ 0`, TR is **N/A (HOLD)** — never fabricate

---

## 17. Constants and Schema Ownership

### 17.1 Single Sources of Truth

| What | Owner | Import From |
|------|-------|-------------|
| Categories, types, roles, lifecycle states | `atlas_constants` | `scripts/atlas_constants.py` |
| Schema field sets, validation patterns | `atlas_schema` | `scripts/atlas_schema.py` |
| Path resolution, root discovery | `atlas_paths` | `scripts/atlas_paths.py` |
| License gate | `atlas_constants.is_denied_license()` | `scripts/atlas_constants.py` |
| Parallelism config | `parallel.config` | `scripts/parallel/config.py` |

**Never redefine constants that exist in these modules.** `validate_architecture.py` enforces this (check 3: duplicated constants, check 4: duplicated license functions, check 5: duplicated schema definitions).

### 17.2 Worker Counts (ADR-013)
Read from `config/parallelism.yaml` via `parallel.config.resolve_worker_count()`. Hardcoding `workers=N` or `max_workers=N` is a violation. Exempt files: `run_classify_all_v2`, `run_extract_all`, `validate_dataset`.

### 17.3 Checksums
SHA-256 on sorted, serialized JSON. See `scripts/experiment_framework/metadata.py` and `scripts/evaluation_research/artifacts.py`. Never use SHA-1 for release artifacts.

---

## 18. Testing and Validation

### 18.1 Commands (Verified)

```bash
# Full test suite (1269 tests, ~90s)
python -m pytest tests/ -q

# Single test file
python -m pytest tests/test_automation_layer.py -q

# Pre-commit hooks (architecture + stabilization)
pre-commit run --all-files

# Architecture governance check
python scripts/validate_architecture.py

# CLI self-test (invariants, license gate, AQL, release manager)
python scripts/atlas.py self-test

# Parallel stabilization tests (deterministic, CI-safe)
python -m pytest tests/test_parallel_stabilization.py -q
```

### 18.2 What to Run After Changing Code
1. **New module or import change:** `python scripts/validate_architecture.py`
2. **Pipeline agent change:** `python -m pytest tests/test_automation_layer.py -q`
3. **Dataset schema change:** `python -m pytest tests/ -q`
4. **Release system change:** `python -m pytest tests/test_release_pipeline.py -q`
5. **Intelligence layer change:** `python -m pytest tests/test_intelligence_layer.py -q`
6. **Full validation before committing:** `pre-commit run --all-files`

Tests import from `scripts/` automatically via `pytest.ini` (`pythonpath = scripts`). No extra setup needed.

---

## 19. Git Workflow

- Branch on `main` for all work; no feature branch convention enforced but recommended for PRs
- Commit scope: one logical change per commit; do not mix cleanup with functional changes
- **Review your diff before declaring completion:** `git diff --stat && git diff`
- Generated files excluded from git per `.gitignore`: `.zst` bundles, large JSONL, `tmp/`, `outputs/`
- Release manifests in `metadata/releases/` are tracked (exception to general metadata ignore)
- Do not commit secrets, `.env`, or credential files
- Dataset records in `curated/` and `raw/` are not committed (only manifests and skeletons)

---

## 20. Failure and Recovery

### 20.1 Pipeline Failure
1. Check `metadata/pipeline_state/<id>.json` for current state and failure info
2. Check agent output logs for error details
3. Fix the underlying issue (data, config, or code)
4. Use `python -m scripts.automation_runner retry --pipeline-id <id>` to resume
5. Do NOT manually edit pipeline state files

### 20.2 Inconsistent State
If authoritative state conflicts with artifact evidence:
1. Inspect the authoritative source (release manifest, pipeline state, lifecycle registry)
2. Inspect execution evidence (agent logs, checksums)
3. Identify the divergence
4. Determine the safest recovery path (re-run, manual fix, or new version)
5. Validate after recovery

### 20.3 HOLD Artifacts
When CUDA/runtime is unavailable or any reproducibility check fails:
- Create explicit `HOLD` artifacts with null metrics and real blocker notes
- Never fabricate counts, checksums, or numbers
- Document what prevented completion

---

## 21. Forbidden Behaviors

These are hard boundaries. Violations must be rejected:

1. **Modify `raw/`, `curated/`, `review_queue/`, or `training_views/` directly** — corrections create new versions
2. **Change `configs/` without approval** — affects all downstream consumers
3. **Promote a release candidate without human approval** — bypasses `WAITING_HUMAN_APPROVAL`
4. **Run model training or fine-tuning without explicit authorization**
5. **Bypass governance gates** (review, provenance, license, quality)
6. **Invent metrics, URLs, authors, licenses, or external facts** — use `[HUMAN MUST SUPPLY]`
7. **Claim evaluation ran when CUDA/runtime was unavailable** — create HOLD artifacts instead
8. **Commit, push, or rewrite history unless explicitly asked**
9. **Read, print, or commit secrets** (`.env`, credential files)
10. **Override architecture governance checks** — `validate_architecture.py` violations block commits
11. **Delete "duplicate-looking" scripts without tracing consumers**
12. **Introduce a second state source for the same concept**
13. **Treat artifact existence as pipeline success**
14. **Create another orchestration layer without architectural justification**
15. **Assume old code is useless merely because it is old**

---

## 22. Development Workflow

When starting new work in this repository:

1. **Understand:** Read `PROJECT_STATE.md` for current phase and known issues
2. **Inspect:** Read relevant code before modifying — trace the actual execution path
3. **Identify source of truth:** Which file/state wins when there's conflict?
4. **Plan:** What is the smallest correct change? Which existing abstraction to reuse?
5. **Implement:** Make the change, preserving architectural boundaries
6. **Test:** Run targeted tests first, then broader suite
7. **Validate:** Run `scripts/validate_architecture.py` and `python scripts/atlas.py self-test`
8. **Review diff:** `git diff` — ensure no unrelated changes, no secrets, no fabricated data
9. **Report:** Document what changed and why

### For Large Changes

Before making architectural changes, explain:
- Current behavior
- Problem
- Root cause
- Proposed architecture
- Files/subsystems affected
- Migration risk
- Validation strategy

---

## 23. Critical Gotchas

### Paths
Use `atlas_paths.py` for all directory access. Never hardcode `"curated"` or `"metadata"`. `validate_architecture.py` check 6 tracks direct path construction as debt.

### Quality Score Gates
- Release gate default: `quality_score >= 7`
- Strict curated gate: `verified=True AND quality_score >= 8.5`
- Score range: 0–10 (int)

### License Gate
Single source of truth: `atlas_constants.is_denied_license()`. Denied patterns: `cc-by-nc*`, `cc-by-nd*`, `proprietary`, `all-rights-reserved`, `unknown`.

### Known QEE Bias
The QEE has a systematic positive bias of +2.14 vs human reviewers. **QEE is not ready for unsupervised automated approval.** See `docs/evaluation/qee_human_alignment_report.md`.

### Training Views
View generation reads from approved records and writes to `metadata/views/<version>/` (never `curated/`). Supported models: qwen, llama, deepseek. Format templates in `configs/formatting/templates.json`.

### Parallelism Config
All worker counts flow from `config/parallelism.yaml` through `parallel.config.resolve_worker_count()`. Environment overrides: `ATLAS_WORKERS_<STAGE_UPPER>`. Hardware profiles: `ATLAS_PROFILE`.

---

## 24. Definition of Done

Work is complete when ALL of the following hold:

### Always
1. Relevant validation performed for the change scope
2. `git diff` reviewed — no unrelated changes, no secrets, no fabricated data
3. Changes documented in relevant doc (ADR, report, or inline comments)

### Code changes
4. Targeted tests pass: `python -m pytest tests/<relevant>.py -q`
5. Architecture governance passes if imports/constants changed: `python scripts/validate_architecture.py`
6. CLI self-test passes if core modules changed: `python scripts/atlas.py self-test`

### Dataset/schema/pipeline/release changes
7. Run the broader validation appropriate to the affected subsystem:
   - Pipeline agent: `python -m pytest tests/test_automation_layer.py -q`
   - Release system: `python -m pytest tests/test_release_pipeline.py -q`
   - Intelligence layer: `python -m pytest tests/test_intelligence_layer.py -q`
   - Schema: `python -m pytest tests/ -q`

### Full validation (major work)
8. Full test suite passes: `python -m pytest tests/ -q`
9. Pre-commit hooks pass: `pre-commit run --all-files`

### For experiment work
10. All 15 reproducibility checklist items verified

---

## 25. Architectural Decision Principles

### 1. One authoritative source of truth
Avoid competing state sources. If two files claim to represent the same state, one is wrong or redundant.

### 2. Evidence-backed state
State transitions should have evidence where practical. A state file without supporting evidence is suspect.

### 3. Artifacts are not automatically truth
A file existing does not prove the pipeline succeeded. Always check the authoritative state.

### 4. Reproducibility
Important outputs should be reproducible from recorded inputs/configuration/code.

### 5. Idempotency
Operations should avoid corrupting state when safely re-run.

### 6. Explicit ownership
Every artifact/state transition should have an identifiable owner (module, script, or subsystem).

### 7. Consolidation over duplication
Prefer extending an existing subsystem over adding a parallel implementation.

### 8. Compatibility before destruction
Do not remove legacy behavior until consumers and migration paths are understood.

### 9. Inspect before modifying
Repository archaeology comes before refactoring.

### 10. Small architectural steps
Large transformations should be decomposed into verifiable migrations.

---

## 26. If You Are a New Agent

Read in this order:

1. **This document** (`AGENTS.md`)
2. **`docs/adr/`** — Architecture Decision Records (ADR-010 through ADR-015)
3. **`docs/research/experiment_protocol_v1.md`** — Research protocol
4. **`metadata/releases/v1.0_release.json`** — Current authoritative release state
5. **`metadata/training_readiness_report.json`** — Current training readiness
6. **`docs/project/atlas_engineering_handbook.md`** — Detailed engineering rules
7. **`ATLAS_SUBSYSTEM_CONTRACTS.md`** — Subsystem interface contracts
8. **Relevant subsystem source code** — `scripts/<subsystem>/`
9. **Relevant tests** — `tests/test_<subsystem>.py`
10. **`PROJECT_STATE.md`** — Current phase snapshot

Then inspect the specific task. Do not start modifying code immediately.

---

## 27. Current State Summary

### Implemented ✅

| Capability | Status | Key Files |
|-----------|--------|-----------|
| v1.0 Release | 9.5M records, 9 categories | `metadata/releases/v1.0_release.json` |
| Automation Layer v1.0 | 11-state FSM, approval gates | `scripts/automation/` |
| Intelligence Layer v1.1 | 2.57M records classified | `scripts/intelligence/` |
| QEE v2 | Frozen for Phase 8 | `scripts/evaluation_engine/v2/` |
| Expert Pipeline | 6,500 pilot extracted | `scripts/expert_pipeline/` |
| Phase 0/1 Acquisition | Sources acquired and validated | `scripts/p0_*.py`, `scripts/p1_*.py` |
| E2E Pipeline v2.0 | Single command: acquire→etl→views→release | `scripts/e2e_pipeline.py` |
| Training View Engine | Model-format generation | `scripts/view_builder/`, `scripts/training_view_engine/` |
| Experiment Framework | Protocol-compliant experiment management | `scripts/experiment_framework/` |
| Release System | Build, verify, promote, publish | `scripts/release/`, `scripts/release_builder/` |
| Parallel Processing | Universal adaptive scheduler | `scripts/parallel/` |
| Architecture Validation | Enforcement of dependency boundaries | `scripts/validate_architecture.py` |
| Pilot v0.2 Data | 4,499 records ready for training | `pilot/v0.2/` |
| model-eval-finetune Integration | Qwen3-8B LoRA pipeline | `model-eval-finetune/` |

### Under Audit 🔍

| Area | Status | Notes |
|------|--------|-------|
| Architecture drift | IN PROGRESS | Deep audit of subsystem ownership |
| Duplicated constants | 2 violations known | `versioning.py`, `progressive_expansion*.py` |
| TUI worker count | VIOLATION | `tui_backend.py:workers=0` |
| Self-test invariant | 1 failing | `release-chain-empty` |
| Legacy script identification | IN PROGRESS | `progressive_expansion.py`, `progressive_expansion_v2.py` |
| State source reconciliation | IN PROGRESS | Multiple review manifest variants exist |

### In Transition 🔄

| Area | Status | Notes |
|------|--------|-------|
| Scheduler consolidation | IN PROGRESS | Multiple scheduler generations → `scripts/parallel/` |
| Architecture hardening | IN PROGRESS | Based on `docs/architecture/` design docs |
| Eval set expansion | PLANNED | Need N≥30 per family for statistical conclusions |
| atan-v1 integration | PLANNED | Atlas to feed atan-v1 training pipeline |

### Planned 📋

| Capability | Notes |
|-----------|-------|
| Human review completion | Unblock training readiness gate |
| Eval split expansion | Math/code to N≥30 |
| atan-v1 model training | Once data readiness is achieved |
| Legacy script removal | After consumer tracing completes |
| Architecture consolidation | Based on audit findings |

### Open Architectural Questions

1. Which of the multiple scheduler implementations should be the canonical one?
2. What is the migration path for `progressive_expansion.py` and `progressive_expansion_v2.py`?
3. Should the TUI (`atlas_tui.py`, `tui_backend.py`) be consolidated or deprecated?
4. How many review manifest variants in `metadata/` are authoritative vs historical?
5. What is the role of `scripts/evaluation_research/` vs `scripts/evaluation_engine/`?
6. Should the experiment framework be expanded to cover the full Phase 7-8 experiment matrix?

---

## 28. Important References

| Topic | Source |
|-------|--------|
| Architecture governance | `docs/adr/ADR-010-architecture-governance.md` |
| Release immutability | `docs/adr/ADR-011-release-immutability.md` |
| Intelligence layer design | `docs/adr/ADR-012-intelligence-layer.md` |
| Parallel processing | `docs/adr/ADR-013-parallel-processing.md` |
| Release pipeline | `docs/adr/ADR-014-release-pipeline.md` |
| Universal scheduler | `docs/adr/ADR-015-universal-scheduler.md` |
| Research protocol | `docs/research/experiment_protocol_v1.md` |
| Experiment matrix | `docs/research/experiment_matrix.md` |
| Benchmark plan | `docs/research/benchmark_plan.md` |
| Risk register | `docs/research/risk_register.md` |
| Phase 8 transfer plan | `docs/research/phase8_transfer_plan.md` |
| Engineering handbook | `docs/project/atlas_engineering_handbook.md` |
| Project context | `docs/project/atlas_project_context.md` |
| Subsystem contracts | `ATLAS_SUBSYSTEM_CONTRACTS.md` |
| QEE calibration | `docs/evaluation/qee_human_alignment_report.md` |
| Current state | `PROJECT_STATE.md` |
| Architecture audit | `docs/subsystem_refactor_audit.md` |
| v0.2 review audit | `docs/v0.2_review_state_audit.md` |
| Roadmap | `docs/roadmap.md` |
| E2E roadmap | `docs/roadmap/atlas_e2e_roadmap.md` |
| v1.1 architecture plan | `docs/roadmap/atlas_v1.1_architecture_plan.md` |

---

*Updated 2026-08-15. This file is the canonical agent reference for this repo.*
