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
├── docs/                     # design, guidelines, quality, roadmap
├── raw/                      # ORIGINAL sources (immutable) — external/generated/documentation/conversations/personal_knowledge
├── processing/               # cleaners / deduplication / validators / converters
├── curated/                  # v0.1 / v1.0 — reviewed, versioned output
├── evaluation/               # benchmarks / test_sets
├── metadata/                 # sources.json, categories.json, dataset_card.md
├── schemas/                  # dataset_schema.json, chat_schema.json (JSON Schema)
├── configs/                  # training + formatting templates
├── scripts/                  # clean / validate / convert / quality_score
└── examples/                 # sample_dataset.jsonl (seed examples)
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

## Documentation

- `docs/dataset_design.md` — architecture & layering
- `docs/contribution_guidelines.md` — how to add data
- `docs/quality_standard.md` — scoring rules & rejection criteria
- `docs/roadmap.md` — milestones & decision gates
- `docs/ingestion_runbook.md` — operational procedure for bulk filling v0.1

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
| v1.0 | planned | first production dataset |

Every release includes: **changelog, statistics, added/removed data, frozen manifest**.

---

## Status

- ✅ Project scaffold (folders, schemas, docs, scripts, seed examples)
- ⏸ Model training paused
- 🔜 Bulk data ingestion — **awaiting approval** (see roadmap)

## License

Dataset assets: **CC-BY-4.0** unless a per-source license in `metadata/sources.json`
states otherwise. Raw upstream material retains its original license.
