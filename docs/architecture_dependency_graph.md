# Architecture Dependency Graph

> Phase 4C.0 — Architecture Consolidation & Dependency Unification
> Generated: 2026-07-28

This document maps every subsystem in Atlas, its dependencies, call patterns, shared services, and data flows. It also identifies circular dependencies and recommends unified dependency direction.

---

## 1. Subsystem List

| # | Subsystem | Module | Primary File(s) | Type |
|---|-----------|--------|-----------------|------|
| 1 | **CLI Entrypoint** | CLI | `scripts/atlas.py` | Orchestrator |
| 2 | **Acquisition Engine** | Engine | `scripts/acquisition_engine/engine.py` | Orchestrator |
| 3 | **Checkpoint Manager** | Checkpoint | `scripts/acquisition_engine/checkpoint.py` | Service |
| 4 | **Integrity Engine** | Integrity | `scripts/acquisition_engine/integrity.py` | Service |
| 5 | **Lifecycle Manager** | Lifecycle | `scripts/acquisition_engine/lifecycle.py` | Service |
| 6 | **Version Manager** | Versioning | `scripts/acquisition_engine/versioning.py` | Service |
| 7 | **Knowledge Pack Manager** | KnowledgePack | `scripts/acquisition_engine/knowledge_pack.py` | Service |
| 8 | **Knowledge Collection Manager** | KnowledgeCollection | `scripts/acquisition_engine/knowledge_collection.py` | Service |
| 9 | **Dataset Diff** | DatasetDiff | `scripts/acquisition_engine/dataset_diff.py` | Service |
| 10 | **Release Manager** | Release | `scripts/acquisition_engine/release.py` | Service |
| 11 | **Release Gates** | Release (ReleaseGates) | `scripts/acquisition_engine/release.py` | Service |
| 12 | **Semantic Diff** | Release (SemanticDiff) | `scripts/acquisition_engine/release.py` | Service |
| 13 | **AQL Engine** | AQL | `scripts/acquisition_engine/aql.py` | Service |
| 14 | **Payload Resolver** | PayloadResolver | `scripts/payload_resolver.py` | Service |
| 15 | **Quality Evaluation Engine** | QualityScore | `scripts/quality_score.py` | Service |
| 16 | **License Gate** | License | `scripts/validate_dataset.py` (`is_denied_license`) | Service |
| 17 | **Schema Validation** | SchemaValidator | `scripts/validate_dataset.py` | Service |
| 18 | **Knowledge Object Validator** | KOValidator | `scripts/validate_knowledge_object.py` | Service |
| 19 | **Calibration Engine** | Calibration | `scripts/calibrate_quality.py` | Service |
| 20 | **Progressive Expansion** | Expansion | `scripts/progressive_expansion.py`, `scripts/progressive_expansion_v2.py` | Orchestrator |
| 21 | **Migration Framework** | Migrations | `migrations/runner.py` (+ 001, 002, 003) | Service |
| 22 | **Review Operations** | Review | `review/operations/` | Workflow |
| 23 | **Revision Resolution** | Revision | `review/revisions/` | Workflow |
| 24 | **Training Views** | Views | `scripts/convert_format.py` | Generator |
| 25 | **Self-Test Framework** | SelfTest | `scripts/atlas.py` (`cmd_self_test`) | Validation |
| 26 | **Source Registry** | Registry | `metadata/source_registry.json` | Data Source |
| 27 | **Acquisition Manifest** | Manifest | `metadata/acquisition_manifest_v0.1.json` | Data Source |
| 28 | **Formatting Templates** | Templates | `configs/formatting/templates.json` | Config |

---

## 2. Dependency Graph

```
CLI Entrypoint (atlas.py)
├── License Gate (is_denied_license) ── from validate_dataset.py (stdlib only)
├── Acquisition Engine
│   ├── Checkpoint Manager
│   ├── Integrity Engine
│   │   ├── file_sha256
│   │   ├── compute_file_checksums
│   │   ├── ChecksumRegistry
│   │   └── VerificationLog
│   ├── Lifecycle Manager
│   ├── Version Manager
│   ├── Knowledge Pack Manager ── Integrity Engine (file_sha256)
│   ├── Knowledge Collection Manager ── Integrity Engine (file_sha256)
│   ├── Dataset Diff
│   ├── Release Manager ── Release Gates ── License Gate
│   │                    └─ Semantic Diff
│   ├── AQL Engine
│   └── License Gate (is_denied_license)
│
├── Payload Resolver (standalone — reviews curated/, review_queue/, knowledge_packs/)
├── Quality Evaluation Engine (standalone)
├── Schema Validation (validate_dataset.py)
│   ├── License Gate (is_denied_license)
│   └── Category Registry (metadata/categories.json)
├── Knowledge Object Validator (validate_knowledge_object.py)
│   └── Schema files (schemas/knowledge_object_schema.json)
├── Calibration Engine
│   ├── Quality Evaluation Engine (score_record)
│   └── Review decisions (review/quality_reviews.jsonl)
├── Progressive Expansion (standalone — procedural pipeline)
├── Migration Framework (standalone — transform scripts)
├── Review Operations (workflow files)
├── Revision Resolution (workflow files)
├── Training Views ── Formatting Templates (configs/formatting/templates.json)
├── Self-Test Framework
│   ├── License Gate
│   ├── Acquisition Engine sub-modules
│   ├── Release Manager / Release Gates
│   ├── AQL Engine
│   ├── Migration Framework
│   └── Knowledge Collection Manager
│
Data Sources (read by many):
├── Source Registry (metadata/source_registry.json)
├── Acquisition Manifest (metadata/acquisition_manifest_v0.1.json)
├── Category Registry (metadata/categories.json)
├── Schemas (schemas/{dataset,chat,knowledge_object,quality_review}_schema.json)
└── Lifecycle State (metadata/lifecycle_state.json)
```

---

## 3. Call Graph (Runtime)

```
atlas.py cmd_*
├── cmd_self_test()
│   └── _run_release_self_tests()
│       ├── ReleaseGates.run_all()
│       ├── ReleaseManager.list_releases()
│       ├── AQL.validate_query() / execute_query() / describe_query()
│       ├── KnowledgeCollectionManager.list_collections()
│       ├── SemanticDiff.compute()
│       └── Migration framework (runner.py → load_migrations → up)
│
├── cmd_ingest_pilot()
│   ├── is_denied_license() (from validate_dataset.py)
│   ├── clean_text() (from clean_dataset.py)
│   ├── Migration framework
│   └── Quality scoring (inline)
│
├── cmd_release()
│   └── ReleaseManager.create_release() / list_releases() / verify_release()
│       └── ReleaseGates.run_all()
│           ├── check_quality_gate()
│           ├── check_license_gate() → _denied_license_gate()
│           ├── check_schema_gate()
│           ├── check_verification_gate()
│           ├── check_category_balance_gate()
│           ├── check_no_unknown_license_gate()
│           └── check_no_rejected_source_gate()
│
├── cmd_collection()
│   └── KnowledgeCollectionManager.create_collection() / list_collections()
│
├── cmd_query()
│   └── AQL.execute_query() / validate_query() / preview_query()
│
├── cmd_release_check()
│   ├── ReleaseGates.run_all()
│   ├── ReleaseManager.verify_release_chain()
│   └── SemanticDiff.compute()
│
├── Gen-calibration-sample / Calibrate
│   └── quality_score.py (score_record / evaluate_record)

AcquisitionEngine.dry_run()
├── CheckpointManager.create() / set_status() / update_source_status()
├── VerificationLog.append()
├── is_denied_license()
└── /docs + metadata writes

AcquisitionEngine.execute()
├── CheckpointManager (full lifecycle)
├── LifecycleTracker.transition()
├── VersionManager.freeze()
├── generate_knowledge_pack()
├── compute_diff()
├── ChecksumRegistry.create()
└── VerificationLog.append()
```

---

## 4. Shared Services

| Service | Used By | Module |
|---------|---------|--------|
| `is_denied_license()` | atlas.py, engine.py, release.py, validate_dataset.py, progressive_expansion*.py | `validate_dataset.py` |
| `file_sha256()` | integrity.py, knowledge_pack.py, knowledge_collection.py, release.py | `integrity.py` |
| `compute_file_checksums()` | integrity.py, engine.py | `integrity.py` |
| `dict_sha256()` | integrity.py, release.py (inline) | `integrity.py` |
| `text_sha256()` | integrity.py (VerificationLog) | `integrity.py` |
| `ChecksumRegistry` | engine.py, release.py | `integrity.py` |
| `VerificationLog` | engine.py, integrity.py | `integrity.py` |
| `CheckpointManager` | engine.py only | `checkpoint.py` |
| `LifecycleTracker` | engine.py only | `lifecycle.py` |
| `VersionManager` | engine.py only | `versioning.py` |
| Knowledge Object schema constants | validate_knowledge_object.py, atlas.py cmd_self_test | module-level constants |
| Category sets | validate_dataset.py, validate_knowledge_object.py, release.py | Module-level constants (duplicated) |

**Key Finding**: The `is_denied_license()` function from `validate_dataset.py` is Atlas's SINGLE canonical license gate. Every subsystem that needs license validation imports it — correctly following the principle of a single source of truth.

---

## 5. Data Flow

```
Source Registry ──→ Acquisition Manifest ──→ Acquisition Engine
     │                                                │
     ├── status=accepted/review                        ├── dry_run() → Ingestion Plan
     ├── license, tier, quality_score                  ├── execute() →
     └── id, url, name                                 │    ├── Checkpoint state
                                                       │    ├── Lifecycle transitions
                                                       │    ├── Version freeze
                                                       │    └── Knowledge Packs
                                                       │
            ┌───────────────────────────────────────────┘
            ▼
       Curated Records (curated/v0.1/data/curated/v0.2/data/)
            │
            ▼
       Review Queue ──→ Human Review ──→ Review Decisions
            │                              │
            ├── pending.jsonl               ├── approved.jsonl
            ├── approved.jsonl              ├── rejected.jsonl
            ├── rejected.jsonl              └── needs_revision.jsonl
            └── needs_revision.jsonl
                 │
                 ▼
            Release Manager
                 │
                 ├── Release Gates (quality, license, schema, verification, balance)
                 ├── Release Manifest (metadata/releases/)
                 ├── Release Index (metadata/release_index.json)
                 └── Semantic Diff
                 │
                 ▼
            Knowledge Packs ──→ Knowledge Collections ──→ Training Views
                 │                                         ├── qwen/
                 ├── knowledge_packs/*.jsonl.gz             ├── llama/
                 └── knowledge_packs/*_manifest.json        └── deepseek/
                 │
                 ▼
            Payload Resolver (lookup service — reads all layers)
```

---

## 6. Circular Dependency Detection

| Cycle | Path | Severity | Status |
|-------|------|----------|--------|
| release.py → validate_dataset.py → (no reverse) | release.py imports `_denied_license_gate()` lazily from validate_dataset.py. validate_dataset.py does NOT import from release.py or any acquisition_engine module. | **None** | Safe — one-directional with lazy import |
| engine.py → validate_dataset.py → (no reverse) | engine.py imports `is_denied_license` same pattern. | **None** | Safe |
| knowledge_pack.py → integrity.py → (no reverse) | knowledge_pack.py imports `file_sha256` from integrity.py. integrity.py does NOT import knowledge_pack.py. | **None** | Safe |
| aql.py | Standalone — no imports from other Atlas modules. Pure parsing/filtering. | **None** | Leaf module |
| payload_resolver.py | Standalone — reads files, no imports from acquisition_engine. | **None** | Leaf module |
| quality_score.py | Standalone — no imports from acquisition_engine. | **None** | Leaf module |
| calibration_quality.py → quality_score.py → (no reverse) | calibration imports score_record. quality_score.py does not import calibration. | **None** | Safe |
| progressive_expansion.py → validate_dataset.py + validate_knowledge_object.py + quality_score.py | Reads but does not re-import acquisition_engine modules. | **None** | Safe but tight coupling |

**No circular dependencies detected.** The architecture has a clear DAG structure with stable leaf modules.

---

## 7. Recommended Dependency Direction

```
                ┌──────────────────────┐
                │   Config / Schema    │  ← Leaf layer (no Atlas imports)
                │   (schemas/, configs)│
                └──────────┬───────────┘
                           │ imported by
                ┌──────────▼───────────┐
                │  Service Layer       │  ← Pure services, no engine imports
                │  ├ License Gate      │
                │  ├ Quality Engine    │
                │  ├ Schema Validator  │
                │  ├ AQL Engine        │
                │  ├ Payload Resolver  │
                │  ├ Integrity Engine  │
                │  ├ Dataset Diff      │
                │  └ Migration Runner  │
                └──────────┬───────────┘
                           │ imported by
                ┌──────────▼───────────┐
                │  Engine Layer        │  ← Orchestrators composing services
                │  ├ AcquisitionEngine │
                │  ├ ReleaseManager    │
                │  ├ ReleaseGates      │
                │  ├ SemanticDiff      │
                │  ├ CheckpointManager │
                │  ├ LifecycleTracker  │
                │  ├ VersionManager    │
                │  └ KnowledgePack*    │
                └──────────┬───────────┘
                           │ composed by
                ┌──────────▼───────────┐
                │  Orchestration Layer │  ← Scripts & workflows
                │  ├ atlas.py (CLI)    │
                │  ├ expansion*        │
                │  ├ calibration*      │
                │  └ Self-Test         │
                └──────────────────────┘

RULE: Services never import Engine or Orchestration modules.
      Engine modules only import Service modules.
      Orchestration modules import both.
      Config/Schema modules import nothing from Atlas.
```

---

## 8. Key Architectural Observations

### Strengths
1. **Single license gate** — `is_denied_license()` is the one true gate, correctly reused everywhere
2. **No circular imports** — clean DAG in the acquisition_engine package
3. **Leaf services are pure** — quality_score.py, aql.py, payload_resolver.py have zero acquisition_engine imports
4. **Deterministic by design** — all scoring, validation, and query processing is pure/stdlib-only

### Risks
1. **Category sets duplicated** — `VALID_CATEGORIES`, `KTYPES`, `VSTATES`, `TVE` defined separately in validate_dataset.py, validate_knowledge_object.py, and release.py (`valid_categories` inline). Schema changes require updating 3+ locations.
2. **`valid_categories` inline in release.py** — The `ReleaseGates.check_schema_gate()` duplicates the category enum as a hardcoded set rather than importing from validate_dataset.py.
3. **Calibration engine has tight coupling to quality_score.py internals** — imports `WEIGHTS` dict directly; schema changes to dimension names cascade.
4. **Progressive Expansion V2 duplicates pilot logic** — `progressive_expansion_v2.py` reimplements pipeline stages that already exist in the Acquisition Engine.

### Recommendation
Centralize category/knowledge_type/verification_status enums into `metadata/categories.json` (or a single constants module like `scripts/atlas_constants.py`) so that validate_dataset.py, validate_knowledge_object.py, and release.py all read from one source.
