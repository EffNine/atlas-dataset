# Atlas AI Dataset Foundation

> **The dataset is the long-term asset. Models are replaceable.**

Atlas is a **model-agnostic, long-term knowledge foundation** for training and
evaluating 8B-class LLMs — Qwen, Llama, DeepSeek, Mistral, Gemma, and future
models. It is deliberately decoupled from any single model's chat template.
The canonical format is plain JSONL; model-specific formats are produced by
downstream converters and never stored as the source of truth.

Model training (e.g. the in-progress Qwen3-8B QLoRA experiment) is **paused**.
The priority is a high-quality, reproducible, versioned dataset system first.

---

## Core Principles

1. **Preserve raw data permanently.** Original sources are never modified.
2. **Never modify original sources.** Raw lives under `raw/`, immutable.
3. **Build a clean processing pipeline.** Every step is scripted and reproducible.
4. **Separate data stages.** `raw/` → `processing/` → `curated/` → training formats.
5. **Version everything.** Semantic dataset versions with manifests + changelogs.
6. **Store metadata per item.** Source, license, tags, quality, verification.
7. **Multi-format conversion.** Qwen / Llama / ShareGPT / Alpaca / Mistral / Gemma via config.
8. **Quality over quantity.** Curated releases prioritise verified, high-scoring records.

---

## Repository Layout

```
atlas-dataset/
├── README.md                      # this file
├── IDEA.md                        # Hermes ecosystem vision & pillars
├── ATLAS_SUBSYSTEM_CONTRACTS.md   # subsystem contract extraction reference
│
├── docs/                          # design, ADRs, specs, releases, governance
│   ├── adr/                       # Architecture Decision Records (10 docs)
│   ├── project/                   # engineering handbook, project context
│   ├── specs/                     # schema specs (AQL, quality engine, lifecycle, etc.)
│   ├── releases/                  # versioned release notes
│   ├── roadmap/                   # long-term E2E architecture plan
│   ├── evaluation/                # evaluation framework & alignment reports
│   ├── governance/                # architecture governance docs
│   ├── training/                  # training readiness reports & simulations
│   └── review/                    # review workflow hardening feedback
│
├── raw/                           # ORIGINAL sources (immutable)
│   ├── external/                  # externally-sourced data
│   ├── generated/                 # synthetic / model-generated drafts
│   ├── documentation/             # raw documentation extracts
│   ├── conversations/             # anonymised conversation logs
│   ├── personal_knowledge/        # author's own expertise exports
│   ├── pilot/                     # pilot ingestion seed data
│   └── .cache/                    # downloader content-addressable cache
│
├── processing/                    # cleaners / deduplication / validators / converters
│
├── curated/                       # versioned, reviewed output
│   ├── v0.1/                      # scaffold + synthetic test data
│   └── v0.2/                      # expanded pilot + phase4b expansion
│
├── evaluation/                    # benchmarks / test_sets
├── metadata/                      # sources, categories, acquisition logs, releases, evaluation reports
├── schemas/                       # JSON Schema for dataset, chat, knowledge objects, quality reviews
├── configs/                       # training + formatting templates
├── migrations/                    # DB/schema migrations with versioned runner
│
├── governance/                    # phase reports, continuity baselines, metadata sync
├── review/                        # human review artifacts (calibration, decisions, operations, revisions)
├── review_queue/                  # queue state (pending, approved, rejected, needs_revision)
├── knowledge_packs/               # knowledge pack collections, manifests
├── training_views/                # per-model training view placeholders
│
└── scripts/                       # all pipeline code
    ├── atlas.py                   # CLI entry point (self-test, calibrate, AQL, release, etc.)
    ├── atlas_constants.py         # shared constants
    ├── atlas_paths.py             # path resolution
    ├── atlas_schema.py            # schema definitions
    │
    ├── automation/                # Pipeline agents, state machine, approval gate
    │   ├── pipeline_orchestrator.py    # main orchestrator
    │   ├── state_machine.py            # FSM (7 states)
    │   ├── approval_gate.py            # human approval gate
    │   ├── acquisition_agent.py        # source acquisition
    │   ├── quality_agent.py            # quality scoring agent
    │   ├── provenance_agent.py         # provenance resolution
    │   ├── validation_agent.py         # validation agent
    │   ├── revision_agent.py           # content revision
    │   ├── release_manager.py          # release management
    │   └── failure_recovery.py         # failure recovery
    │
    ├── automation_runner.py       # CLI entry point for automation pipeline
    ├── e2e_pipeline.py            # v2.0 single atlas pipeline e2e command
    │
    ├── acquisition_engine/        # Acquisition Engine (v2)
    │   ├── engine.py              # core acquisition engine
    │   ├── aql.py                 # Atlas Query Language
    │   ├── checkpoint.py          # checkpoint/resume
    │   ├── dataset_diff.py        # dataset diff operations
    │   ├── integrity.py           # integrity checks
    │   ├── knowledge_collection.py # knowledge collection management
    │   ├── knowledge_pack.py       # knowledge pack management
    │   ├── lifecycle.py           # lifecycle management
    │   ├── release.py             # release operations
    │   └── versioning.py          # versioning utilities
    │
    ├── downloader/                # v1.6 source adapters + cache
    │   ├── download_agent.py      # download orchestrator
    │   ├── cache.py               # content-addressable cache
    │   ├── http_util.py           # HTTP utilities
    │   └── adapters/              # per-source adapters (arxiv, github, huggingface, etc.)
    │
    ├── etl/                       # v1.7 extract → normalize → clean
    │   ├── pipeline.py            # ETL pipeline
    │   ├── extract_agent.py       # extraction agent
    │   ├── normalizer.py          # text normalization
    │   ├── types.py               # type definitions
    │   └── extractors/            # file format extractors
    │
    ├── transform/                 # v1.8 training-type transformers
    ├── view_builder/              # v1.8 model-family training views
    ├── release_builder/           # v1.8 release bundles
    ├── parallel/                  # v1.9 thread-pool worker
    ├── incremental/               # v1.9 per-source stage state
    │
    ├── evaluation_engine/         # evaluation framework
    │   ├── engine.py              # evaluation engine
    │   ├── metrics.py             # metric implementations
    │   ├── registry.py            # metric registry
    │   ├── runner.py              # evaluation runner
    │   └── report.py              # report generator
    │
    ├── training_view_engine/      # training view generation
    │   ├── generator.py           # view generator
    │   ├── filter.py              # view filter
    │   ├── manifest.py            # manifest management
    │   └── validator.py           # view validation
    │
    ├── progressive_expansion.py   # v0.2 expansion engine
    ├── progressive_expansion_v2.py
    ├── metadata_sync.py           # metadata synchronisation
    ├── payload_resolver.py        # payload resolution
    ├── provenance_resolver.py     # provenance resolution
    └── validate_architecture.py   # architecture validation
```

---

## Data Pipeline

```
Raw Data
   │
   ▼  processing/cleaners   (clean_dataset.py)
Data Cleaning
   │
   ▼  processing/deduplication
Deduplication
   │
   ▼  processing/validators + scripts/quality_score
Quality Filtering
   │
   ▼  human review (verified=true)
Human Review
   │
   ▼  curated/vX.Y
Curated Dataset
   │
   │  ┌──────────────────────────────────────────┐
   │  │  Atlas Automation Layer v1.0              │
   │  │  python -m scripts.automation_runner run  │
   │  │                                           │
   │  │  INGESTED → QUALITY_CHECK → PROVENANCE    │
   │  │  → CONTENT_REVISION → VALIDATION          │
   │  │  → WAITING_HUMAN_APPROVAL → RELEASED      │
   │  └──────────────────────────────────────────┘
   │
   ▼  processing/converters + scripts/convert_format.py
Model-Specific Formatting
   ├── Qwen ChatML
   ├── Llama Instruction
   ├── Mistral Instruct
   ├── Gemma Instruct
   ├── ShareGPT
   └── Alpaca
```

---

## Quick Start

```bash
# 1. Validate the seed examples against the schema
python scripts/validate_dataset.py --input examples/sample_dataset.jsonl

# 2. Run the quality scorer on the seed examples
python scripts/quality_score.py --input examples/sample_dataset.jsonl

# 3. Clean a raw file into canonical form
python scripts/clean_dataset.py --input raw/generated/draft.jsonl --output tmp/cleaned.jsonl

# 4. Deduplicate
python scripts/dedup_dataset.py --input tmp/cleaned.jsonl --report

# 5. Convert curated data to a model format
python scripts/convert_format.py --format qwen_chatml \
    --input examples/sample_dataset.jsonl --output tmp/qwen.jsonl

# 6. Run the automation pipeline
python -m scripts.automation_runner run --pipeline-id release-v0.3

# 7. Check pipeline status
python -m scripts.automation_runner status --pipeline-id release-v0.3

# 8. Atlas CLI — self-test, calibration, AQL, release management
python scripts/atlas.py self-test
python scripts/atlas.py calibrate --reviews review/quality_reviews.jsonl
```

---

## Automation Layer v1.0

Atlas includes an automated pipeline framework that runs quality,
provenance, revision, validation, and release checks in a deterministic
sequence with a mandatory human approval gate before release.

```bash
# Run the full pipeline from current state
python -m scripts.automation_runner run --pipeline-id release-v0.3

# Check pipeline status
python -m scripts.automation_runner status --pipeline-id release-v0.3

# Approve/deny a release
python -m scripts.automation_runner approve --pipeline-id release-v0.3
python -m scripts.automation_runner deny --pipeline-id release-v0.3

# Retry a failed agent after fixing data
python -m scripts.automation_runner retry --pipeline-id release-v0.3

# Resume a paused pipeline
python -m scripts.automation_runner resume --pipeline-id release-v0.3
```

The automation layer:
- **Never modifies existing tools or dataset files.** All existing
  scripts continue to work unchanged.
- **Never writes to curated/, review_queue/, training_views/, or raw/.**
  All pipeline state is persisted under `metadata/`.
- **Requires human approval before release.** The WAITING_HUMAN_APPROVAL
  gate is mandatory.

See the full [release notes](docs/releases/atlas-automation-v1.0.md) and
[architecture documentation](docs/automation_layer_v1.md) for details.

---

## Scripts Reference

| Script | Purpose |
|---|---|
| `scripts/atlas.py` | CLI: self-test, calibrate quality, AQL queries, release management, knowledge packs |
| `scripts/clean_dataset.py` | Normalize loosely-structured raw JSONL into canonical Atlas records (non-destructive). |
| `scripts/validate_dataset.py` | Schema + duplicate + category + curated-gate checks, with `--stats` balance report. |
| `scripts/quality_score.py` | 7-dimension heuristic quality scorer (1–10). |
| `scripts/dedup_dataset.py` | Exact (SHA-1) + near-duplicate detection and optional drop. |
| `scripts/convert_format.py` | Convert canonical JSONL → 6 model formats (see below). |
| `scripts/eval_dataset.py` | Reproducible train/eval split + coverage/quality gate report. |
| `scripts/gen_calibration_sample.py` | Stratified review-worksheet generator (read-only on data). |
| `scripts/calibrate_quality.py` | Calibrate scorer vs human review: accuracy, bias, recommendations. |
| `scripts/automation_runner.py` | Automation pipeline CLI: run, status, approve, deny, release, retry, resume. |
| `scripts/e2e_pipeline.py` | Single end-to-end pipeline command (v2.0). |
| `scripts/pilot_seed.py` | Generate pilot seed data. |
| `scripts/progressive_expansion.py` | v0.2 progressive expansion logic. |
| `scripts/provenance_resolver.py` | Automated provenance resolution. |
| `scripts/payload_resolver.py` | Payload resolution and recovery. |
| `scripts/metadata_sync.py` | Metadata synchronisation across subsystems. |
| `scripts/build_acquisition_decisions.py` | Build acquisition human decision records. |
| `scripts/validate_architecture.py` | Validate architecture dependency layering. |

All core scripts are **stdlib-only** (no pip install) and deterministic, so the
pipeline runs anywhere and is reproducible in CI.

## Supported model formats (6)

Defined declaratively in `configs/formatting/templates.json`, so adding a future
model is a config edit — never a data migration:

1. `qwen_chatml` — Qwen2 / Qwen2.5 / Qwen3
2. `llama_instruction` — Llama-3 / Llama-3.1
3. `mistral_instruct` — Mistral / Mixtral
4. `gemma_instruct` — Gemma-2 / Gemma-3
5. `sharegpt` — OpenChat / vLLM / many stacks
6. `alpaca` — Stanford Alpaca / llama.cpp

---

## Documentation Index

| Area | Documents |
|---|---|
| **Architecture** | `docs/dataset_design.md`, `docs/project/atlas_project_context.md` (2,276 lines) |
| **Engineering rules** | `docs/project/atlas_engineering_handbook.md` (983 lines) |
| **ADRs** | 10 ADRs in `docs/adr/` — quality calibration, knowledge objects, licensing, synthetic data, training views, lineage, quality gates, review queues, v1 spec, architecture governance |
| **Pipeline** | `docs/automation_layer_v1.md`, `docs/downloader_v1_6.md`, `docs/etl_v1_7.md`, `docs/v1_8_transform_views_release.md` |
| **Quality** | `docs/quality_standard.md`, `docs/quality_calibration.md`, `docs/calibration_baseline_report.md`, `docs/human_calibration_report.md` |
| **Specs** | `docs/specs/` — AQL spec, atlas v1 spec, collection spec, evaluation report spec, knowledge object schema, knowledge pack spec, lifecycle spec, quality engine spec, release manifest spec, training dataset contract, training recipe spec, training view spec |
| **Governance** | `docs/governance/` — architecture governance, phase 5E reports |
| **Training** | `docs/training/` — readiness dashboard, release decision simulation |
| **Source discovery** | `docs/dataset_candidates.md`, `docs/acquisition_strategy_v0.1.md`, `docs/source_policy.md` |
| **Review** | `docs/` — v0.2 batch review reports, review state audits, revision feedback analysis |
| **Quick reference** | `ATLAS_SUBSYSTEM_CONTRACTS.md` — extracted subsystem contracts |

---

## Versioning

| Version | Status | Notes |
|---|---|---|
| v0.1 | scaffold + synthetic test data | 1000 high-quality examples target; clean structure + reproducible pipeline |
| v0.2 | **active** | expanded pilot, phase4b expansion, progressive expansion data |
| v1.0 | released | automation pipeline with quality, provenance, revision, validation, approval gate, failure recovery |

Every release includes: **changelog, statistics, added/removed data, frozen manifest**.

---

## Canonical Record Format (extended)

See `schemas/dataset_schema.json` (and `schemas/chat_schema.json` for turns).
Every example is one JSON object per line:

```json
{
  "id": "04_ai_machine_learning_llm_0001",
  "category": "04_ai_machine_learning",
  "subcategory": "llm",
  "type": "qa",
  "source": { "name": "...", "url": "...", "license": "CC-BY-4.0", "date": "2026-07-27" },
  "messages": [ {"role":"system","content":""}, {"role":"user","content":""}, {"role":"assistant","content":""} ],
  "language": "en",
  "difficulty": 0,
  "tags": ["llm","fine-tuning"],
  "quality_score": 0,
  "verified": false,
  "notes": ""
}
```

---

## Status

- ✅ Project scaffold (folders, schemas, docs, scripts, seed examples)
- ✅ Automation Layer v1.0 released (pipeline orchestrator, state machine, approval gate, 5 agents, CLI, failure recovery)
- ✅ AcquisitionAgent v1 + Downloader/Cache v1.6 (`raw/.cache/`, source adapters)
- ✅ ETL v1.7 Extract → Normalize → Clean
- ✅ v1.8 Transform + Training Views + Release Builder
- ✅ v1.9 Parallel workers + Incremental state
- ✅ v2.0 Single `e2e_pipeline.py` command
- ✅ Acquisition Engine v2 (AQL, checkpoint/resume, integrity, lifecycle, release, versioning)
- ✅ v0.2 progressive expansion with human review pipeline
- ✅ Evaluation framework (`evaluation_engine/`)
- ✅ Architecture governance & dependency validation
- ⏸ Model training paused — unblock by completing human review of staged records

## License

Dataset assets: **CC-BY-4.0** unless a per-source license in `metadata/sources.json`
states otherwise. Raw upstream material retains its original license.
