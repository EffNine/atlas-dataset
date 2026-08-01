# Atlas v1.1 — Architecture & Implementation Plan

> **Status:** Planning document — no production code, no dataset modification, no release modification
> **Scope:** Atlas v1.1 Intelligence & Training Platform Evolution
> **Date:** 2026-08-01
> **Author:** Architecture Planning (Hermes)

---

## Table of Contents

1. [Current State Assessment](#1-current-state-assessment)
2. [Problems Identified](#2-problems-identified)
3. [Proposed Architecture](#3-proposed-architecture)
4. [New Components](#4-new-components)
5. [Folder Changes](#5-folder-changes)
6. [Data Flow Diagrams](#6-data-flow-diagrams)
7. [Migration Strategy](#7-migration-strategy)
8. [Implementation Phases](#8-implementation-phases)
9. [Priority Ranking](#9-priority-ranking)
10. [Risks and Mitigation](#10-risks-and-mitigation)

---

## 1. Current State Assessment

### 1.1 Repository State

| Component | State | Location |
|-----------|-------|----------|
| Acquisition pipeline | Production | `scripts/acquisition_engine/`, `scripts/downloader/` |
| ETL pipeline | Production | `processing/`, `scripts/etl/` |
| Deduplication pipeline | Production | `processing/deduplication/` |
| Release pipeline | Production | `scripts/release/` |
| Intelligence Layer v1.1 | Production | `metadata/intelligence/` |
| Release metadata system | Production | `metadata/releases/`, `metadata/release_index.json` |
| Evaluation structure | Skeleton | `evaluation/`, `configs/training/` |
| Training configs | Skeleton | `configs/training/qlora_qwen3_8b.yaml` |
| Training views | Placeholder stubs | `training_views/{qwen,llama,deepseek}/` |
| Governance | Enforced | `docs/governance/`, ADRs, policy validator |
| Architecture | Layered, governed | ADR-010, canonical modules |

### 1.2 Dataset State

| Metric | Value |
|--------|-------|
| Total records | 9,515,938 |
| Categories | 9 |
| Release | v1.0 Final (frozen, immutable) |
| HF repo | `EffNine/atlas-dataset` |
| v1.0 release_id | `4dcfd43e9da2d756...` |
| v1.0 chain_hash | `4dcfd43e...` (chained from RC2 `d7cab614...`) |

### 1.3 Intelligence State

| Metric | Value |
|--------|-------|
| Classified records (v1.1) | 2,575,622 / 9,515,938 (27.1%) |
| Sources classified | Tulu-3, OpenWebMath, ArXiv CS/ML, C4 AI/ML |
| Unclassified | Wikipedia (6.2M), Synthetic, PersonaHub, Code, QA, MMLU, etc. |
| Difficulty distribution (classified only) | L1: 1.30M, L2: 640k, L3: 594k, L4: 37k, L5: 11 |
| Confidence | Mean 0.55, 31.5% low-confidence |
| Reasoning types | factual, explanation, coding, debugging, design, analysis, research |
| Skill domains | ai_ml, science, software_engineering, system_engineering, business, creative |
| v1.2 classification | In progress (full-source, all 313 shards) |

### 1.4 Existing ADRs Relevant to v1.1

| ADR | Title | Relevance |
|-----|-------|-----------|
| ADR-004 | Training Views | Defines on-demand view generation, eligibility flags, no dataset duplication |
| ADR-010 | Architecture Governance | Enforces dependency boundaries, policy validator, canonical modules |
| ADR-005 | Knowledge Lineage | Provenance tracking for all records |
| ADR-003 | Synthetic Data Policy | Governs synthetic data usage and labeling |

---

## 2. Problems Identified

### 2.1 Critical Gaps

| # | Problem | Impact | Current Workaround |
|---|---------|--------|-------------------|
| 1 | **L4/L5 scarcity** — only 37k L4, 11 L5 records | Cannot train for expert reasoning without expert sources | None |
| 2 | **Coverage gap** — only 27% classified | Training views lack difficulty metadata for 73% of records | v1.2 classification in progress |
| 3 | **No query engine** — cannot filter by difficulty+domain+reasoning | Manual dataset curation for training | Ad-hoc scripts |
| 4 | **No reproducibility guarantee for views** — training_views/ are stubs | Risk of format drift between builds | Manual regeneration |
| 5 | **Storage split** — 22GB raw on dev-pc, 4.8GB dataset on HF LFS | No unified cache strategy | None |
| 6 | **No evaluation pipeline** — benchmark framework is skeleton | Cannot measure model improvement after training | Manual eval |
| 7 | **No expert knowledge** — missing RFCs, kernel docs, CUDA, DB internals | Weakness in system/engineering training | None |
| 8 | **v1.1 schema is flat** — single-level difficulty only | Cannot express nuanced complexity (coding depth, reasoning steps) | None |

### 2.2 Architectural Constraints

- **v1.0 immutability** — canonical dataset cannot be modified
- **No dataset duplication** — training views must be generated, not stored
- **Governance compliance** — all changes require ADR, policy validator passes
- **HF LFS limits** — large artifacts must stay on HF LFS, not Git
- **dev-pc resource limits** — 8 cores, 23GB RAM, sequential processing preferred for large shards

---

## 3. Proposed Architecture

### 3.1 High-Level Platform Vision

```
┌─────────────────────────────────────────────────────────────────┐
│                     ATLAS v1.1 PLATFORM                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │   Canonical   │    │  Intelligence │    │   Training   │      │
│  │   Dataset     │───▶│   Layer v2   │───▶│   Views      │      │
│  │   (v1.0)      │    │   (v1.2+)    │    │   Engine     │      │
│  └──────────────┘    └──────────────┘    └──────┬───────┘      │
│         ▲                    ▲                    │              │
│         │                    │                    ▼              │
│  ┌──────┴──────┐    ┌────────┴────────┐   ┌──────────────┐      │
│  │  Acquisition│    │  Query Engine   │   │   Model      │      │
│  │  Pipeline    │    │  + Indexes      │   │   Adapters   │      │
│  └─────────────┘    └─────────────────┘   └──────┬───────┘      │
│                                                  │              │
│                                          ┌───────┴───────┐      │
│                                          │  AtlasBench   │      │
│                                          │  Evaluation   │      │
│                                          └───────────────┘      │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Knowledge Packs                        │   │
│  │  linux/ kubernetes/ embedded/ ai_ml/ hardware/ networking/│   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Core Principles

1. **Canonical-first** — v1.0 dataset is the single source of truth; never modified
2. **Metadata-driven** — all filtering, views, and queries derive from intelligence metadata
3. **Reproducible** — every view and query is version-controlled and deterministic
4. **No duplication** — training views are generated artifacts, not stored copies
5. **Extensible** — new models, domains, and signals are config-driven, not code-driven
6. **Governed** — all changes require ADR, policy validator passes, and human approval gates

### 3.3 Layered Architecture

```
Layer 4: Training Platform
    ↓
Layer 3: Intelligence Layer
    ↓
Layer 2: Query Engine
    ↓
Layer 1: Canonical Dataset (v1.0, immutable)
    ↓
Layer 0: Raw Sources (22GB on dev-pc, gitignored)
```

**Dependency rule:** Higher layers may depend on lower layers only. No reverse dependencies.

### 3.4 Component Interaction Model

```
Query Engine ←→ Intelligence Layer ←→ Canonical Dataset
     ↓               ↓                    ↓
Training Views ←→ Knowledge Packs ←→ AtlasBench
     ↓               ↓                    ↓
Model Adapters ←→ Eval Pipeline ←→ HF LFS
```

---

## 4. New Components

### 4.1 Training View Engine

**Purpose:** Generate model-specific training datasets on-demand from canonical + intelligence metadata.

**Architecture:**

```
training_view_engine/
├── __init__.py
├── engine.py                 # Core ViewEngine class
├── schema.py                 # ViewSpec, ViewManifest, eligibility rules
├── filters/
│   ├── __init__.py
│   ├── difficulty.py         # L1-L5 filtering
│   ├── domain.py             # category/subcategory filtering
│   ├── reasoning.py          # reasoning_type filtering
│   ├── quality.py            # quality_score threshold
│   └── composite.py          # AND/OR/NOT composition
├── formatters/
│   ├── __init__.py
│   ├── base.py               # BaseFormatter ABC
│   ├── qwen.py               # Qwen ChatML format
│   ├── llama.py              # Llama 3 instruction format
│   ├── deepseek.py           # DeepSeek R1 format
│   ├── hermes.py             # Hermes 2 tool-use format
│   └── custom.py             # User-defined template
├── generators/
│   ├── __init__.py
│   ├── deterministic.py      # Reproducible generation (seed, sort)
│   ├── balanced.py           # Difficulty-balanced sampling
│   └── stratified.py         # Domain-stratified sampling
├── manifest.py               # ViewManifest — provenance, hash, reproducibility
└── cli.py                    # `atlas build-view`, `atlas list-views`, `atlas verify-view`
```

**Schema:**

```yaml
# ViewSpec (configs/views/)
view_id: "qwen3-8b-balanced"
version: "1.0.0"
description: "Balanced Qwen3 8B training view"
base_release: "v1.0"
intelligence_snapshot: "v1.2"

filters:
  difficulty: [1, 2, 3, 4, 5]
  domains: ["software_engineering", "ai_ml", "science"]
  reasoning_types: ["coding", "analysis", "research"]
  min_quality_score: 7
  max_low_confidence_fraction: 0.5

sampling:
  strategy: "stratified"
  max_per_difficulty: 100000
  shuffle_seed: 42

format: "qwen"
output:
  format: "jsonl"
  compression: "zstd"
  destination: "hf://datasets/EffNine/atlas-training-views"
```

**CLI Design:**

```bash
# Build a view
atlas build-view --spec configs/views/qwen3-8b-balanced.yaml

# List all views
atlas list-views

# Verify a view's reproducibility
atlas verify-view --view_id qwen3-8b-balanced --against-manifest metadata/views/qwen3-8b-balanced.json

# Show view statistics
atlas view-stats --view_id qwen3-8b-balanced
```

**Folder Structure:**

```
configs/views/
├── qwen3-8b-balanced.yaml
├── llama3-70b-expert.yaml
├── deepseek-r1-science.yaml
└── README.md

metadata/views/
├── qwen3-8b-balanced.json      # ViewManifest (provenance, hashes, stats)
├── llama3-70b-expert.json
└── index.json                  # View registry

training_views/
├── qwen/                       # Generated artifacts (gitignored, HF-backed)
│   ├── README.md               # Placeholder per ADR-004
│   └── .gitkeep
├── llama/
├── deepseek/
└── hermes/
```

### 4.2 Dataset Query Engine

**Purpose:** Allow ad-hoc filtering and exploration of the canonical dataset via metadata.

**Architecture:**

```
query/
├── __init__.py
├── engine.py                   # QueryEngine — parses, plans, executes
├── parser/
│   ├── __init__.py
│   ├── ast.py                  # Query AST nodes
│   └── lexer.py                # Tokenizer for query language
├── planner/
│   ├── __init__.py
│   ├── index_planner.py        # Chooses optimal index
│   └── filter_planner.py       # Pushes filters to metadata layer
├── executor/
│   ├── __init__.py
│   ├── metadata_filter.py      # Filters against intelligence metadata
│   ├── record_filter.py        # Filters against canonical records
│   └── sampler.py              # Random/stratified sampling
├── indexes/
│   ├── __init__.py
│   ├── difficulty_index.py     # difficulty → record IDs
│   ├── domain_index.py         # domain → record IDs
│   ├── reasoning_index.py      # reasoning_type → record IDs
│   └── composite_index.py      # Multi-field B-tree or bitmap
└── cli.py                      # `atlas query ...`
```

**Query Language:**

```sql
-- Select records with difficulty L4-L5 in software_engineering
SELECT * FROM atlas
WHERE difficulty IN (4, 5)
  AND domain = 'software_engineering'
  AND quality_score >= 7
ORDER BY difficulty DESC
LIMIT 1000;

-- Count by reasoning type
SELECT reasoning_type, COUNT(*)
FROM atlas
WHERE domain = 'ai_ml'
GROUP BY reasoning_type;

-- Stratified sample
SAMPLE 1000 STRATIFIED BY difficulty;
```

**CLI Design:**

```bash
# Ad-hoc query
atlas query --difficulty L4,L5 --domain software_engineering --reasoning planning --quality 9+

# Count query
atlas query --count --domain ai_ml --group-by reasoning_type

# Export to view spec
atlas query --export configs/views/custom-query.yaml --difficulty L4,L5 --limit 5000
```

**Indexes:**

| Index | Field | Type | Size (est.) |
|-------|-------|------|-------------|
| difficulty_idx | difficulty | B-tree | 9.5M entries |
| domain_idx | primary_domain | Hash | 9.5M entries |
| reasoning_idx | reasoning_types | Inverted | 9.5M entries |
| quality_idx | quality_score | B-tree | 9.5M entries |
| composite_idx | (difficulty, domain, quality) | Bitmap | 9.5M entries |

**Performance Considerations:**

- Indexes built once after v1.2 classification completes
- Stored as `metadata/indexes/` (JSONL + binary formats)
- Query engine loads indexes into memory (~2-4GB for 9.5M records)
- Filters pushed to metadata layer; only matching records loaded from canonical
- Cache hot indexes in `metadata/indexes/.cache/`

### 4.3 Intelligence Layer v2

**Purpose:** Expand metadata beyond difficulty to cover quality, safety, complexity, and educational value.

**Current Schema (v1.1):**

```json
{
  "difficulty": {"level": 1-5, "confidence": 0.0-1.0},
  "reasoning_types": ["factual", "coding", ...],
  "skill_domains": ["ai_ml", "science", ...]
}
```

**Proposed Schema (v2.0):**

```json
{
  "difficulty": {
    "level": 1-5,
    "confidence": 0.0-1.0,
    "reasoning_depth": 1-5,
    "coding_complexity": 1-5
  },
  "quality": {
    "overall_score": 1-10,
    "instruction_quality": 1-10,
    "answer_completeness": 1-10,
    "hallucination_risk": 0.0-1.0,
    "ambiguity_score": 0.0-1.0
  },
  "educational_value": {
    "score": 1-10,
    "prerequisites": ["..."],
    "learning_objectives": ["..."]
  },
  "content": {
    "token_length": 1234,
    "language": "en",
    "safety_category": ["safe", "borderline"],
    "topics": ["..."],
    "entities": ["..."]
  },
  "reasoning_types": ["factual", "coding", ...],
  "skill_domains": ["ai_ml", "science", ...]
}
```

**Schema Changes:**

| Field | Type | Source | Notes |
|-------|------|--------|-------|
| difficulty.reasoning_depth | int 1-5 | LLM classifier | Number of reasoning steps |
| difficulty.coding_complexity | int 1-5 | Heuristic + LLM | Lines of code, cyclomatic complexity |
| quality.overall_score | int 1-10 | LLM judge | Aggregated quality |
| quality.instruction_quality | int 1-10 | LLM judge | Clarity, specificity |
| quality.answer_completeness | int 1-10 | LLM judge | Coverage, correctness |
| quality.hallucination_risk | float 0-1 | LLM judge + fact-check | Probability of hallucination |
| quality.ambiguity_score | float 0-1 | LLM judge | Vagueness, multiple interpretations |
| educational_value.score | int 1-10 | LLM judge | Pedagogical value |
| educational_value.prerequisites | list[str] | LLM + knowledge graph | Required prior knowledge |
| educational_value.learning_objectives | list[str] | LLM | What learner gains |
| content.token_length | int | Tokenizer | Exact token count |
| content.language | str | FastText/langdetect | ISO 639-1 |
| content.safety_category | list[str] | Classifier | safe, borderline, unsafe |
| content.topics | list[str] | LLM + TF-IDF | Extracted topics |
| content.entities | list[str] | NER | Named entities |

**Migration Strategy:**

1. **Backward-compatible schema** — v2.0 adds fields, does not remove v1.1 fields
2. **Versioned metadata** — `metadata/intelligence/v1.1/` stays frozen; v2.0 writes to `metadata/intelligence/v2.0/`
3. **Dual-write during transition** — new classification writes both v1.1 and v2.0 formats
4. **Gradual rollout** — v2.0 classifiers run on new sources first; v1.0 records backfilled in batches
5. **Compatibility layer** — `intelligence/adapters/v1_to_v2.py` converts old records

**Compatibility with v1.0:**

- v1.0 canonical records remain unchanged
- Intelligence metadata is separate from canonical records
- Training View Engine reads intelligence metadata via adapters
- Queries default to v2.0 fields when available, fall back to v1.1

### 4.4 Expert Knowledge Expansion

**Purpose:** Address L4/L5 scarcity by adding expert-level sources.

**Target Sources:**

| Domain | Sources | Estimated Records | License |
|--------|---------|-------------------|---------|
| System Engineering | Linux kernel docs, PostgreSQL internals, Kubernetes docs, systemd docs | 500k | Mixed (GPL, CC-BY, Apache) |
| AI/ML | LLVM docs, CUDA docs, Intel/AMD optimization guides, ONNX spec | 300k | Mixed (Apache, MIT, CC-BY) |
| Hardware | Intel SDM, AMD APM, RISC-V specs, ARM ARM | 200k | Mixed (CC-BY, permissive) |
| Networking | RFCs (full text), IETF drafts, Wireshark docs | 150k | Public domain, CC-BY |
| Research | ArXiv CS/ML (expanded), technical reports, conference papers | 400k | Varies (need screening) |
| **Total** | | **1.55M** | |

**Acquisition Strategy:**

1. **Bulk download** — RFCs (public domain), kernel docs (bulk tarballs), ArXiv (API + bulk)
2. **Web scraping** — PostgreSQL docs, Kubernetes docs, LLVM docs (permitted by robots.txt + terms)
3. **API ingestion** — arXiv API, Crossref API for papers
4. **Human review** — All new sources pass through review queue before classification

**Quality Gates:**

- Minimum 500 words per document (filter out stubs)
- Must pass prose fluency check (no garbled text)
- Must have clear Q/A pairs extractable
- License must be in `commercial_safe` or `attribution_required` category (per ADR-002)
- Each source gets a `source_quality_score` before classification

**Licensing Considerations:**

- Follow ADR-002 (commercial-safe licensing)
- Flag attribution-required sources separately
- Do not include GPL-licensed code examples without clear transformation
- Maintain `metadata/license_matrix.json` per source

### 4.5 Knowledge Packs

**Purpose:** Allow specialized training without rebuilding the full dataset.

**Design:**

```
knowledge_packs/
├── linux/
│   ├── pack.yaml              # Pack definition
│   ├── sources/               # Source metadata
│   ├── manifest.json          # Records, stats, provenance
│   └── README.md
├── kubernetes/
├── embedded/
├── ai_ml/
├── hardware/
├── networking/
├── science/
├── mathematics/
└── README.md
```

**Pack Schema (`pack.yaml`):**

```yaml
pack_id: "linux"
version: "1.0.0"
description: "Linux kernel, system administration, and DevOps"
base_release: "v1.0"
intelligence_snapshot: "v2.0"

sources:
  - id: "linux-kernel-docs"
    path: "raw/external/linux-docs/"
    license: "GPL-2.0"
    attribution: "Linux kernel documentation"
  - id: "postgresql-internals"
    path: "raw/external/postgresql-docs/"
    license: "PostgreSQL Licence"

filters:
  domains: ["system_engineering", "software_engineering"]
  min_difficulty: 3
  reasoning_types: ["analysis", "debugging", "design"]

generation:
  strategy: "stratified"
  max_records: 50000
  format: "jsonl"
  compression: "zstd"

output:
  destination: "hf://datasets/EffNine/atlas-knowledge-packs/linux-v1.0"
```

**Generation Process:**

1. User creates `pack.yaml` defining sources, filters, and output
2. `atlas build-pack linux` reads pack definition
3. Query Engine filters canonical records + new expert sources
4. Training View Engine formats records
5. Output written to HF dataset repo under `knowledge-packs/`
6. Pack manifest registered in `metadata/knowledge_packs/index.json`

**Release Model:**

- Packs are versioned independently from main dataset
- Each pack has its own `pack_id`, `version`, and `manifest`
- Packs can be updated without touching canonical dataset
- Packs are HF datasets themselves (`EffNine/atlas-knowledge-packs`)

### 4.6 AtlasBench — Evaluation Framework

**Purpose:** Benchmark framework for measuring model performance on Atlas-derived tasks.

**Design:**

```
evaluation/
├── benchmarks/
│   ├── reasoning/
│   │   ├── benchmark.yaml      # Benchmark definition
│   │   ├── test_set.jsonl      # Questions + gold answers
│   │   ├── rubric.json         # Scoring criteria
│   │   └── README.md
│   ├── coding/
│   ├── science/
│   ├── hardware/
│   ├── ai_ml/
│   └── system_engineering/
├── pipeline/
│   ├── runner.py               # BenchmarkRunner
│   ├── scorer.py               # Exact match, LLM judge, code execution
│   ├── reporter.py             # HTML/JSON/Markdown reports
│   └── comparator.py           # Model-vs-model comparison
├── configs/
│   ├── qwen3-8b.yaml
│   ├── llama3-70b.yaml
│   └── deepseek-r1.yaml
└── results/
    ├── runs/                   # Timestamped evaluation runs
    └── leaderboard.json        # Model comparison scores
```

**Benchmark Format:**

```yaml
benchmark_id: "atlas-reasoning-l4-l5"
version: "1.0.0"
description: "Expert-level reasoning from Atlas L4/L5 records"
category: "reasoning"
difficulty_range: [4, 5]

test_set:
  source: "metadata/views/expert-reasoning.json"
  size: 1000
  split: "test"

scoring:
  - type: "exact_match"
    weight: 0.3
  - type: "llm_judge"
    model: "gpt-4o"
    rubric: "rubrics/expert-reasoning.json"
    weight: 0.7

pass_threshold: 0.7
```

**Evaluation Pipeline:**

```bash
# Run benchmark
atlas eval run --benchmark reasoning-l4-l5 --model qwen3-8b

# Compare models
atlas eval compare --benchmarks reasoning-l4-l5 coding-l3 --models qwen3-8b llama3-70b deepseek-r1

# Generate report
atlas eval report --run-id 20260801-001 --format html
```

**Scoring Methods:**

| Method | Use Case | Implementation |
|--------|----------|----------------|
| Exact match | Factual QA, math | String equality |
| LLM judge | Open-ended reasoning | GPT-4o / Claude Sonnet rubric |
| Code execution | Coding tasks | Docker sandbox, pytest |
| Multi-turn | Conversational | Turn-by-turn scoring |
| Composite | Mixed benchmarks | Weighted average |

### 4.7 Training Pipeline Integration

**Purpose:** Connect Atlas → Training Views → QLoRA/Fine-tuning → Evaluation → Model Release.

**Architecture:**

```
┌──────────────────────────────────────────────────────────────────┐
│                    TRAINING PIPELINE (v1.1)                       │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │ Atlas Query  │───▶│ View Engine  │───▶│   Dataset    │       │
│  │ Engine       │    │              │    │   Formatter  │       │
│  └──────────────┘    └──────────────┘    └──────┬───────┘       │
│                                                  │                │
│  ┌──────────────┐    ┌──────────────┐           │                │
│  │  Training    │◀───│   Model      │◀──────────┘                │
│  │  Config      │    │   Adapter    │                            │
│  └──────┬───────┘    └──────────────┘                            │
│         │                                                         │
│         ▼                                                         │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │   QLoRA /    │───▶│   Model      │───▶│  AtlasBench  │       │
│  │   Fine-tune  │    │   Release    │    │   Eval       │       │
│  └──────────────┘    └──────────────┘    └──────────────┘       │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

**Dataset Formatting:**

- **Qwen:** ChatML format with system prompts
- **Llama:** Llama 3 instruction format (BOS/EOS tokens)
- **DeepSeek:** DeepSeek R1 format (reasoning chains)
- **Hermes:** Tool-use format with function definitions

**Model-Specific Adapters:**

```yaml
# configs/adapters/qwen3-8b.yaml
model_id: "Qwen/Qwen2.5-8B-Instruct"
template: "chatml"
system_prompt: "You are a helpful assistant."
max_seq_length: 4096
lora:
  r: 16
  alpha: 32
  target_modules: ["q_proj", "v_proj"]
```

**Training Configs:**

```yaml
# configs/training/qwen3-8b-balanced.yaml
base_model: "Qwen/Qwen2.5-8B-Instruct"
view: "qwen3-8b-balanced"
output: "models/qwen3-8b-atlas-v1.1"
training:
  method: "qlora"
  batch_size: 4
  gradient_accumulation: 8
  learning_rate: 2e-4
  epochs: 3
  warmup_steps: 100
evaluation:
  benchmarks: ["atlas-reasoning-l4-l5", "atlas-coding-l3"]
```

### 4.8 Storage Strategy

**Current:**

| Data | Location | Size | Git-tracked |
|------|----------|------|-------------|
| Raw shards | dev-pc `raw/generated/` | 22GB | No (gitignored) |
| Canonical dataset | HF LFS `releases/v1.0/dataset/` | 4.8GB | Skeleton only |
| Metadata | Git + HF | ~100MB | Yes |
| Intelligence outputs | Git `metadata/intelligence/` | ~500MB | Yes (temp files gitignored) |
| Release artifacts | HF LFS + Git skeleton | 4.8GB | Skeleton only |

**Proposed Storage Strategy:**

```yaml
# .gitignore (updated)
raw/                        # 22GB, dev-pc only
curated/*.jsonl             # Generated, gitignored
releases/*/dataset/**/*.zst # HF LFS only
metadata/intelligence/_tmp/ # Temp classification outputs
training_views/*/           # Generated views, HF-backed
knowledge_packs/*/          # Generated packs, HF-backed

# Git tracks:
# - code, schemas, configs, docs
# - metadata manifests, indexes, views manifests
# - release skeletons (not dataset content)

# HF LFS stores:
# - releases/*/dataset/**/*.zst
# - training_views/*/data/**/*.zst
# - knowledge_packs/*/data/**/*.zst
# - evaluation/results/runs/*/

# dev-pc local cache:
# - raw/generated/ (22GB, persistent)
# - metadata/indexes/ (2-4GB, rebuildable)
# - metadata/intelligence/_tmp/ (temp, cleanable)
```

**Cache Strategy for dev-pc:**

| Cache | Location | Size | Policy |
|-------|----------|------|--------|
| Raw shards | `raw/generated/` | 22GB | Persistent, rsync from backup |
| Classification temp | `metadata/intelligence/_tmp/` | ~5GB | Clean after each v1.x run |
| Intelligence indexes | `metadata/indexes/` | 2-4GB | Rebuild after v1.x classification |
| Views cache | `training_views/.cache/` | ~1GB | LRU, max 3 views |
| Pack cache | `knowledge_packs/.cache/` | ~500MB | Clean on pack update |

**Sync Strategy:**

- Mac ↔ dev-pc: `rsync` for raw shards (one-way, Mac → dev-pc for new sources)
- Git: Mac → origin (GitHub)
- HF: dev-pc → HF (publish script)
- No raw data on Mac (storage constraint)

---

## 5. Folder Changes

### 5.1 New Directories

```
docs/roadmap/
└── atlas_v1.1_architecture_plan.md    # This document

configs/views/                          # Training view specs
├── qwen3-8b-balanced.yaml
├── llama3-70b-expert.yaml
├── deepseek-r1-science.yaml
└── README.md

configs/adapters/                       # Model-specific adapters
├── qwen3-8b.yaml
├── llama3-70b.yaml
├── deepseek-r1.yaml
└── hermes2.yaml

query/                                  # Query engine
├── __init__.py
├── engine.py
├── parser/
├── planner/
├── executor/
├── indexes/
└── cli.py

knowledge_packs/                        # Expert knowledge packs
├── linux/
├── kubernetes/
├── embedded/
├── ai_ml/
├── hardware/
├── networking/
├── science/
└── README.md

evaluation/
├── benchmarks/
│   ├── reasoning/
│   ├── coding/
│   ├── science/
│   ├── hardware/
│   ├── ai_ml/
│   └── system_engineering/
├── pipeline/
│   ├── runner.py
│   ├── scorer.py
│   ├── reporter.py
│   └── comparator.py
├── configs/
│   ├── qwen3-8b.yaml
│   ├── llama3-70b.yaml
│   └── deepseek-r1.yaml
└── results/
    ├── runs/
    └── leaderboard.json

metadata/
├── views/                              # View manifests
│   ├── qwen3-8b-balanced.json
│   ├── llama3-70b-expert.json
│   └── index.json
├── indexes/                            # Query indexes
│   ├── difficulty_idx.jsonl
│   ├── domain_idx.jsonl
│   ├── reasoning_idx.jsonl
│   ├── quality_idx.jsonl
│   └── composite_idx.jsonl
└── knowledge_packs/
    ├── linux/
    ├── kubernetes/
    └── index.json
```

### 5.2 Modified Directories

| Directory | Change | Reason |
|-----------|--------|--------|
| `training_views/` | Add `hermes/` stub | Hermes model support |
| `scripts/intelligence/` | Add `v2_classifier.py` | Intelligence Layer v2 signals |
| `scripts/release/` | Add `build_view.py` | View generation in release pipeline |
| `metadata/intelligence/` | Add `v2.0/` subdirectory | Backward-compatible v2 metadata |
| `configs/training/` | Add adapter configs, view configs | Training pipeline integration |
| `docs/adr/` | Add ADR-011 (Query Engine), ADR-012 (Intelligence v2) | Governance |

### 5.3 Files to Remove/Restructure

| File/Dir | Action | Reason |
|----------|--------|--------|
| `training_views/{qwen,llama,deepseek}/` | Keep stubs, add `hermes/` | Per ADR-004, stubs only until v1.1 |
| `configs/training/qlora_qwen3_8b.yaml` | Move to `configs/adapters/qwen3-8b.yaml` | Separation of concerns |
| `run_classify_all_v2.py` (root) | Move to `scripts/intelligence/` | Temporary runner, cleanup after v1.2 |

---

## 6. Data Flow Diagrams

### 6.1 Full-Classification Flow (v1.2)

```
raw/generated/*.jsonl (313 shards, 22GB)
    │
    ▼
batch_classify_v2.py (parallel, 8 workers)
    │
    ├── Stage 1: Wikipedia (7 sources, 2 workers)
    │   ├── wiki_ai (41 shards)
    │   ├── wiki_sw (10 shards)
    │   ├── wiki_sys (8 shards)
    │   ├── wiki_sci (16 shards)
    │   ├── wiki_biz (14 shards)
    │   ├── wiki_cre (8 shards)
    │   └── wiki_hw (9 shards)
    │
    └── Stage 2: Remaining sources (6 workers)
        ├── synthetic_pa, tulu3, openwebmath, arxiv, c4
        ├── swebench, codealpaca, ultrafeedback, oasst1
        ├── sciq, gsm8k, mmlu, capybara, fin_alpaca
        └── github_readmes, stackoverflow, gutenberg, batch_new
    │
    ▼
metadata/intelligence/_tmp/classified_*.jsonl
    │
    ▼
merge_and_report()
    │
    ├── metadata/intelligence/classification_summary_v1.2.json
    ├── metadata/intelligence/difficulty_distribution_v1.2.json
    └── metadata/intelligence/per_source/*.json
    │
    ▼
v1.2 Intelligence Layer (100% coverage)
```

### 6.2 Training View Generation Flow

```
configs/views/qwen3-8b-balanced.yaml (ViewSpec)
    │
    ▼
ViewEngine.load_spec()
    │
    ▼
QueryEngine.execute(filters)
    │
    ├── Load indexes: difficulty_idx, domain_idx, reasoning_idx
    ├── Filter: difficulty IN (1,2,3,4,5) AND domain IN (...)
    └── Return matching record IDs
    │
    ▼
Sampler.stratified(record_ids, max_per_difficulty=100000)
    │
    ▼
FormatterRegistry.get("qwen").format(records)
    │
    ├── Apply ChatML template
    ├── Add system prompt
    └── Validate output schema
    │
    ▼
ViewManifest.create(records, format, sampling_strategy)
    │
    ├── Compute manifest hash (SHA-256)
    ├── Record provenance (base_release, intelligence_snapshot)
    └── Write to metadata/views/qwen3-8b-balanced.json
    │
    ▼
Output: training_views/qwen/data/*.zst (gitignored, HF-backed)
```

### 6.3 Query Engine Flow

```
User: atlas query --difficulty L4,L5 --domain software_engineering --limit 100
    │
    ▼
QueryParser.parse("--difficulty L4,L5 --domain software_engineering --limit 100")
    │
    ▼
QueryAST(
    filters=[DifficultyFilter([4,5]), DomainFilter("software_engineering")],
    limit=100
)
    │
    ▼
QueryPlanner.plan(ast)
    │
    ├── Choose indexes: difficulty_idx + domain_idx
    ├── Push filters to metadata layer
    └── Estimate cost: 37k L4/L5 records × 10% SE domain = ~3.7k records
    │
    ▼
QueryExecutor.execute(plan)
    │
    ├── Load indexes into memory
    ├── Intersect: difficulty_idx[4,5] ∩ domain_idx["software_engineering"]
    ├── Load canonical records for matching IDs
    └── Apply limit + shuffle
    │
    ▼
Result: 100 records (JSONL or pretty-print)
```

### 6.4 Intelligence v2 Classification Flow

```
raw/generated/*.jsonl + raw/external/expert-sources/
    │
    ▼
v2_classifier.py (parallel)
    │
    ├── Stage 1: Difficulty classifier (existing)
    ├── Stage 2: Quality classifier (new)
    │   ├── quality_score (1-10)
    │   ├── instruction_quality (1-10)
    │   ├── answer_completeness (1-10)
    │   └── hallucination_risk (0-1)
    ├── Stage 3: Content classifier (new)
    │   ├── token_length
    │   ├── language
    │   ├── safety_category
    │   ├── topics
    │   └── entities
    └── Stage 4: Educational classifier (new)
        ├── educational_value (1-10)
        ├── prerequisites
        └── learning_objectives
    │
    ▼
metadata/intelligence/v2.0/classified_*.jsonl
    │
    ▼
merge_and_report()
    │
    ├── metadata/intelligence/v2.0/classification_summary.json
    ├── metadata/intelligence/v2.0/difficulty_distribution.json
    └── metadata/intelligence/v2.0/quality_distribution.json
    │
    ▼
v2.0 Intelligence Layer (100% coverage, enriched)
```

### 6.5 Knowledge Pack Generation Flow

```
knowledge_packs/linux/pack.yaml
    │
    ▼
PackEngine.load_pack("linux")
    │
    ▼
QueryEngine.execute(pack.filters)
    │
    ├── Load indexes
    ├── Filter: domain IN (system_engineering, software_engineering) AND min_difficulty=3
    └── Return matching record IDs + expert source records
    │
    ▼
Sampler.stratified(record_ids, max_records=50000)
    │
    ▼
FormatterRegistry.get("jsonl").format(records)
    │
    ▼
PackManifest.create(records, pack_id="linux", version="1.0.0")
    │
    ├── Compute pack hash
    ├── Record provenance
    └── Write to metadata/knowledge_packs/linux/manifest.json
    │
    ▼
Output: HF dataset EffNine/atlas-knowledge-packs/linux-v1.0
```

---

## 7. Migration Strategy

### 7.1 v1.0 → v1.1 Migration

**Principle:** v1.0 is immutable. v1.1 builds on top of v1.0 without modifying it.

| Step | Action | Impact | Rollback |
|------|--------|--------|----------|
| 1 | Complete v1.2 classification (100% coverage) | Metadata only | Delete v1.2 temp files |
| 2 | Build Intelligence Layer v2 indexes | Metadata only | Delete indexes |
| 3 | Implement Query Engine (read-only) | New code, no data changes | Disable query engine |
| 4 | Implement Training View Engine (read-only) | New code, no data changes | Disable view engine |
| 5 | Add expert knowledge sources | New raw data, new classification | Remove raw data, reclassify |
| 6 | Build Knowledge Packs | Generated artifacts | Delete packs |
| 7 | Implement AtlasBench | New evaluation data | Delete benchmarks |
| 8 | Integrate training pipeline | New scripts | Disable training scripts |

### 7.2 Schema Evolution

| Version | Schema | Backward Compatible | Migration |
|---------|--------|---------------------|-----------|
| v1.0 | Canonical records (no intelligence) | N/A | Baseline |
| v1.1 | + difficulty, reasoning_types, skill_domains | Yes | v1.0 records get v1.1 metadata |
| v1.2 | + full-source coverage | Yes | v1.1 metadata unchanged |
| v2.0 | + quality, educational_value, content | Yes | v1.1/v1.2 records get v2.0 fields |

**Backward Compatibility Rules:**

1. Old intelligence versions remain readable
2. New fields are additive only (no field removal)
3. Adapters convert old → new formats
4. Queries default to latest version, fall back to older versions

### 7.3 Data Migration

| Data | From | To | Method |
|------|------|----|--------|
| Canonical dataset | v1.0 | v1.1 | No change (immutable) |
| Intelligence metadata | v1.1 | v1.2 | Re-classify full sources |
| Intelligence metadata | v1.2 | v2.0 | Add new classifier passes |
| Training views | stubs | generated | On-demand via ViewEngine |
| Knowledge packs | none | generated | On-demand via PackEngine |
| Indexes | none | built | Post-classification batch job |

---

## 8. Implementation Phases

### Phase 1: Foundation (Weeks 1-4)

**Goal:** Complete v1.2 classification, build indexes, implement read-only query/view engines.

| Week | Task | Deliverable | Status |
|------|------|-------------|--------|
| 1 | Complete v1.2 full-source classification | `metadata/intelligence/v1.2/*.json` | In progress |
| 1 | Verify v1.2 coverage (target: 100%) | Coverage report | Pending |
| 2 | Build Intelligence Layer v2 indexes | `metadata/indexes/*.jsonl` | Planned |
| 2 | Implement Query Engine core (parser + executor) | `query/engine.py` | Planned |
| 3 | Implement Query Engine indexes | `query/indexes/*.py` | Planned |
| 3 | Implement Query Engine CLI | `atlas query` | Planned |
| 4 | Implement Training View Engine core | `training_view_engine/engine.py` | Planned |
| 4 | Implement View Engine CLI | `atlas build-view`, `atlas list-views` | Planned |

**Milestone:** v1.2 classification complete, query engine functional, view engine functional (read-only).

### Phase 2: Enrichment (Weeks 5-8)

**Goal:** Add Intelligence Layer v2 signals, expert knowledge sources, knowledge packs.

| Week | Task | Deliverable | Status |
|------|------|-------------|--------|
| 5 | Implement Intelligence v2 classifiers | `scripts/intelligence/v2_classifier.py` | Planned |
| 5 | Run v2 classification on v1.2 sources | `metadata/intelligence/v2.0/*.json` | Planned |
| 6 | Acquire expert knowledge sources (RFCs, kernel docs) | `raw/external/*/` | Planned |
| 6 | Classify expert sources with v2 classifier | `metadata/intelligence/v2.0/expert_*.json` | Planned |
| 7 | Implement Knowledge Pack engine | `knowledge_packs/` + `atlas build-pack` | Planned |
| 7 | Build initial packs: linux, ai_ml, networking | Pack manifests + HF datasets | Planned |
| 8 | Integrate v2 metadata with Query Engine | Query Engine reads v2.0 fields | Planned |
| 8 | Update training view specs to use v2 fields | `configs/views/*.yaml` | Planned |

**Milestone:** v2.0 intelligence complete, expert sources integrated, 3+ knowledge packs published.

### Phase 3: Evaluation (Weeks 9-12)

**Goal:** Implement AtlasBench evaluation framework, connect training pipeline.

| Week | Task | Deliverable | Status |
|------|------|-------------|--------|
| 9 | Design benchmark format + rubric | `evaluation/benchmarks/*/benchmark.yaml` | Planned |
| 9 | Implement BenchmarkRunner | `evaluation/pipeline/runner.py` | Planned |
| 10 | Implement scorer (exact match + LLM judge) | `evaluation/pipeline/scorer.py` | Planned |
| 10 | Build initial benchmarks: reasoning, coding, science | Test sets + rubrics | Planned |
| 11 | Implement training pipeline integration | `scripts/training/` + configs | Planned |
| 11 | Implement model adapters (Qwen, Llama, DeepSeek, Hermes) | `configs/adapters/*.yaml` | Planned |
| 12 | Run first end-to-end training + eval | Model checkpoint + eval report | Planned |
| 12 | Publish AtlasBench leaderboard | `evaluation/results/leaderboard.json` | Planned |

**Milestone:** First trained model checkpoint, evaluation pipeline functional, leaderboard published.

### Phase 4: Platform (Weeks 13-16)

**Goal:** Polish, documentation, CI/CD, community readiness.

| Week | Task | Deliverable | Status |
|------|------|-------------|--------|
| 13 | Policy validator updates for new modules | CI passes | Planned |
| 13 | Architecture governance review | ADR-011, ADR-012 | Planned |
| 14 | Documentation: query language, view specs, pack format | `docs/` | Planned |
| 14 | Integration tests for all new components | `tests/` | Planned |
| 15 | Performance testing (query latency, view generation time) | Benchmarks | Planned |
| 15 | dev-pc cache strategy implementation | Cache cleanup scripts | Planned |
| 16 | v1.1 release candidate | v1.1-RC1 manifest | Planned |

**Milestone:** v1.1-RC1 ready for human review.

---

## 9. Priority Ranking

### 9.1 Priority Matrix

| Priority | Component | Impact | Effort | Dependencies |
|----------|-----------|--------|--------|--------------|
| P0 | Complete v1.2 classification | High | Medium | None |
| P0 | Intelligence Layer v2 indexes | High | Low | v1.2 complete |
| P1 | Query Engine (core) | High | High | Indexes |
| P1 | Training View Engine (core) | High | High | Query Engine |
| P1 | Intelligence v2 classifiers | High | High | v1.2 complete |
| P2 | Expert knowledge sources | High | High | v2 classifiers |
| P2 | Knowledge Packs | Medium | Medium | View Engine |
| P2 | AtlasBench | Medium | High | View Engine |
| P3 | Training pipeline integration | Medium | Medium | AtlasBench |
| P3 | Model adapters (Hermes, etc.) | Low | Low | Training pipeline |
| P4 | Performance optimization | Low | Medium | All components |
| P4 | Documentation polish | Low | Low | All components |

### 9.2 Critical Path

```
v1.2 classification → v2 indexes → Query Engine → View Engine → AtlasBench → Training pipeline
```

**Bottleneck:** v1.2 classification must complete before indexes can be built.

**Parallel tracks:**
- Track A: v1.2 classification → v2 indexes → Query Engine
- Track B: View Engine design (can start in parallel with Query Engine)
- Track C: Expert source acquisition (can start immediately)

### 9.3 Effort Estimates

| Component | Lines of Code (est.) | Weeks | Risk |
|-----------|---------------------|-------|------|
| Query Engine | ~3,000 | 3 | Medium (parser complexity) |
| Training View Engine | ~2,500 | 2 | Low (reuses existing formatters) |
| Intelligence v2 classifiers | ~2,000 | 2 | High (LLM judge reliability) |
| Expert source acquisition | ~1,500 | 2 | Medium (licensing) |
| Knowledge Packs | ~1,000 | 1 | Low |
| AtlasBench | ~2,500 | 3 | Medium (scoring reliability) |
| Training pipeline | ~1,500 | 2 | Low |
| **Total** | **~14,000** | **15** | |

---

## 10. Risks and Mitigation

### 10.1 Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| LLM judge inconsistency for v2 quality scores | High | High | Use multiple judges, agreement threshold, human calibration |
| OOM during full-source classification | Medium | High | Sequential processing for large shards, streaming I/O |
| Query Engine performance with 9.5M records | Medium | Medium | Indexes, memory-mapped files, caching |
| Training view format drift | Low | Medium | Versioned templates, manifest hashing |
| Expert source licensing issues | Medium | High | Pre-screen all sources, maintain license matrix, ADR-002 compliance |
| v1.0 immutability violation | Low | Critical | Governance policy validator, ADR process, human approval gate |

### 10.2 Schedule Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| v1.2 classification takes longer than expected | Medium | Medium | Parallel workers, progress monitoring, fallback to sequential |
| Expert source acquisition delayed | Medium | Low | Start with public domain sources (RFCs), add others later |
| LLM API rate limits during v2 classification | High | Medium | Batch processing, exponential backoff, local classifier fallback |
| dev-pc hardware failure | Low | High | Rsync backups, cloud fallback (HF + GitHub) |

### 10.3 Quality Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Low-confidence classifications in v2 | Medium | Medium | Human review queue for low-confidence records |
| Benchmark gaming (model overfits to AtlasBench) | Medium | Medium | Held-out test sets, multiple benchmark versions |
| Training view bias (over-representation of certain domains) | Medium | Medium | Stratified sampling, balance checks |
| Knowledge Pack quality varies by domain | Medium | Low | Per-pack quality gates, source screening |

### 10.4 Governance Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Architecture drift in new components | Medium | Medium | Policy validator updates, ADR-010 enforcement |
| Schema changes break downstream consumers | Low | High | Backward-compatible schema, versioned metadata, adapters |
| License contamination in expert sources | Low | Critical | Pre-screen, license matrix, human review |

---

## Appendix A: Current File Inventory (Key Files)

### scripts/

| File | Purpose | Status |
|------|---------|--------|
| `intelligence/batch_classify.py` | v1.1 classification (4 sources) | Production |
| `intelligence/batch_classify_v2.py` | Full-source classification (v1.2) | In progress |
| `intelligence/difficulty_analyzer.py` | Core classifier | Production |
| `release/promote_release.py` | RC → final promotion | Production |
| `release/publish_promotion.py` | HF publish | Production |
| `release/build_release_metadata.py` | Release metadata builder | Production |

### metadata/

| File/Dir | Purpose | Status |
|----------|---------|--------|
| `releases/v1.0_release.json` | v1.0 final manifest | Production |
| `release_index.json` | Release chain index | Production |
| `intelligence/classification_summary_v1.1.json` | v1.1 summary | Production |
| `intelligence/difficulty_distribution_v1.1.json` | v1.1 distribution | Production |
| `intelligence/v1.2/` | v1.2 classification outputs | In progress |

### configs/

| File | Purpose | Status |
|------|---------|--------|
| `training/qlora_qwen3_8b.yaml` | QLoRA training config | Skeleton |
| `views/*.yaml` | Training view specs | Planned |
| `adapters/*.yaml` | Model adapters | Planned |

---

## Appendix B: Open Questions

| # | Question | Decision Needed | Owner |
|---|----------|----------------|-------|
| 1 | Should v2.0 classification run on all sources or only new/expert sources? | Scope v2.0 | User |
| 2 | Which LLM judge to use for quality scoring? (GPT-4o, Claude, local?) | v2 classifier | User |
| 3 | Should AtlasBench use LLM judges or deterministic scoring? | Evaluation design | User |
| 4 | Which expert sources to prioritize first? (RFCs, kernel docs, CUDA?) | Expert expansion | User |
| 5 | Should Knowledge Packs be public or private HF datasets? | Pack release model | User |
| 6 | Should training pipeline support multi-GPU or single-GPU only? | Training configs | User |
| 7 | Should v1.1 be a separate HF repo or same repo with different branch/tag? | Release strategy | User |

---

## Appendix C: Success Criteria

| Criterion | Target | Measurement |
|-----------|--------|-------------|
| v1.2 classification coverage | 100% | All 313 shards classified |
| v2.0 classification coverage | 100% | All records have v2.0 metadata |
| L4/L5 record count | >100k | Difficulty distribution |
| Query Engine latency | <1s for 90th percentile | Benchmark |
| View generation time | <5 min for 100k records | Benchmark |
| AtlasBench reliability | ±3% score variance | Re-run same benchmark |
| Training pipeline E2E | <24h for 8B model | End-to-end timing |
| Knowledge Pack count | 6+ packs | Pack registry |
| Expert source count | 1.55M+ records | Acquisition logs |

---

*End of Atlas v1.1 Architecture Plan*
