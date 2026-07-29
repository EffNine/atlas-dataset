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
7. **Multi-format conversion.** Qwen / Llama / ShareGPT / Alpaca via config.
8. **Quality over quantity.** v0.1 targets 1000 *high-quality* examples.

---

## Repository Layout

```
atlas-dataset/
├── README.md                 # this file
├── docs/                     # design, guidelines, quality, roadmap, releases, release notes
│   └── releases/             # versioned release notes
├── raw/                      # ORIGINAL sources (immutable) — external/generated/documentation/conversations/personal_knowledge
├── processing/               # cleaners / deduplication / validators / converters
├── curated/                  # v0.1 / v1.0 — reviewed, versioned output
├── evaluation/               # benchmarks / test_sets
├── metadata/                 # sources.json, categories.json, dataset_card.md
├── schemas/                  # dataset_schema.json, chat_schema.json (JSON Schema)
├── configs/                  # training + formatting templates
├── scripts/                  # clean / validate / convert / quality_score / automation
│   ├── automation/           # Pipeline agents, state machine, approval gate, failure recovery
│   ├── downloader/           # v1.6 source adapters + content-addressable cache (raw/.cache/)
│   └── automation_runner.py  # CLI entry point for the automation pipeline
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

# 4. Convert curated data to a model format
python scripts/convert_format.py --format qwen_chatml \
    --input examples/sample_dataset.jsonl --output tmp/qwen.jsonl
```

### Quality Calibration (pre-bulk-ingestion gate)

Before bulk ingestion, measure how much to trust the automated scorer against
structured human review. This phase is **read-only on the dataset** (no size
growth) — it emits review artifacts keyed by existing `record_id`s.

```bash
# 1. Generate a deterministic, stratified review worksheet (read-only on data)
python scripts/atlas.py gen-calibration-sample
#    -> review_queue/calibration_sample.jsonl  (worksheet)
#    -> review_queue/quality_reviews.example.jsonl (ILLUSTRATIVE seed; delete before real runs)

# 2. A human fills review_queue/quality_reviews.jsonl from the worksheet
#    (schema: schemas/quality_review_schema.json).

# 3. Calibrate: accuracy, bias by category/source, confidence, recommendations
python scripts/atlas.py calibrate --reviews review_queue/quality_reviews.jsonl
#    -> metadata/calibration_report.json + docs/quality_calibration_report.md
```

The readiness verdict gates the roadmap's "Begin bulk ingestion" decision. See
`docs/quality_calibration.md`.

---

## Scripts

| Script | Purpose |
|---|---|
| `scripts/clean_dataset.py` | Normalize loosely-structured raw JSONL into canonical Atlas records (non-destructive). |
| `scripts/validate_dataset.py` | Schema + duplicate + category + curated-gate checks, with `--stats` balance report. |
| `scripts/quality_score.py` | 7-dimension heuristic quality scorer (1–10). |
| `scripts/dedup_dataset.py` | Exact (SHA-1) + near-duplicate (MinHash/LSH, stdlib-only) detection and optional drop. |
| `scripts/convert_format.py` | Convert canonical JSONL → 6 model formats (see below). |
| `scripts/eval_dataset.py` | Reproducible train/eval split + coverage/quality gate report. |
| `scripts/gen_calibration_sample.py` | Stratified review-worksheet generator for the quality-calibration framework (READ-ONLY on data). |
| `scripts/calibrate_quality.py` | Calibrate `quality_score.py` vs structured human review: accuracy, bias by category/source, confidence, bulk-ingestion recommendations. |
| `scripts/automation_runner.py` | Automation pipeline CLI: `run`, `status`, `approve`, `deny`, `release`, `retry`, `resume`, and more. See [Automation Layer](#automation-layer-v10) below. |

All scripts are **stdlib-only** (no pip install) and deterministic, so the
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

## Automation Layer v1.0

Atlas includes an automated pipeline framework that runs quality,
provenance, revision, validation, and release checks in a deterministic
sequence with a mandatory human approval gate before release.

```bash
# Run the full pipeline from current state
python -m scripts.automation_runner run --pipeline-id release-v0.3

# Check pipeline status
python -m scripts.automation_runner status --pipeline-id release-v0.3

# Retry a failed agent after fixing data
python -m scripts.automation_runner retry --pipeline-id release-v0.3
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

## Documentation

- `docs/dataset_design.md` — architecture & layering
- `docs/contribution_guidelines.md` — how to add data
- `docs/quality_standard.md` — scoring rules & rejection criteria
- `docs/roadmap.md` — milestones & decision gates
- `docs/ingestion_runbook.md` — operational procedure for bulk filling v0.1
- `docs/automation_layer_v1.md` — automation pipeline architecture
- `docs/releases/atlas-automation-v1.0.md` — v1.0 release notes
- `docs/downloader_v1_6.md` — Downloader + Cache Manager (v1.6)
- `docs/roadmap/atlas_e2e_roadmap.md` — long-term E2E architecture plan

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

## Versioning

| Version | Status | Notes |
|---|---|---|
| v0.1 | scaffold → filling | 1000 high-quality examples target; clean structure + reproducible pipeline |
| v0.2 | planned | improved categories, dedup at scale |
| v1.0 | released | automation pipeline with quality, provenance, revision, validation, approval gate, failure recovery |

Every release includes: **changelog, statistics, added/removed data, frozen manifest**.

---

## Status

- ✅ Project scaffold (folders, schemas, docs, scripts, seed examples)
- ✅ Automation Layer v1.0 released (pipeline orchestrator, state machine, approval gate, 5 agents, CLI, failure recovery)
- ✅ AcquisitionAgent v1 + Downloader/Cache v1.6 (`raw/.cache/`, source adapters)
- ⏸ Model training paused
- 🔜 v1.7 Extract + Normalize + Clean (see `docs/roadmap/atlas_e2e_roadmap.md`)

## License

Dataset assets: **CC-BY-4.0** unless a per-source license in `metadata/sources.json`
states otherwise. Raw upstream material retains its original license.
