# Atlas v1.0 Specification

**Status:** Specification Freeze  
**Project:** Atlas Knowledge Platform  
**Version spec:** 1.0.0  
**Frozen contracts:** platforms/APIs/schemas/lifecycle/quality/licensing/release/AQL  
**Status notes and routing:** `docs/specs/status_notes_conventions.md`

---

# Section 1 — Platform Vision

## 1.1 Purpose

Atlas is a model-agnostic, long-term knowledge foundation for training and evaluating 8B-class LLMs. The dataset is the durable asset; models are replaceable. Atlas defines the stable structure, metadata, lineage, quality, licensing, and release contracts for knowledge objects so downstream models, evaluators, and tools can rely on a single source of truth.

## 1.2 Non-goals

- Atlas is not a model runtime.
- Atlas is not a preference-tuning dataset contract unless explicitly declared in a training recipe.
- Atlas does not enforce one chat template in canonical storage.
- Atlas does not replace upstream source attribution obligations.
- Atlas does not guarantee legal advice; users must confirm license use-fit obligations themselves.

## 1.3 Core Principles

1. Raw data remains immutable.
2. Canonical storage is plain JSONL with JSON Schema validation.
3. Model-specific formats are generated downstream, never stored as the source of truth.
4. Quality over quantity is a first-class invariant.
5. Commercial safety is mandatory and non-negotiable.
6. Reproducibility and determinism are required properties, not afterthoughts.
7. Traceability from source to model training is required for every record.
8. Human review retains final authority over dataset changes.

## 1.4 Commercial Safety

Atlas must remain commercial-safe from day one. Denied-license classes to block from all dataset layers are `CC-BY-NC*`, `CC-BY-ND*`, proprietary / all-rights-reserved, unknown/ambiguous, and ToS-violating sources such as ShareGPT and Reddit exports. Rejected sources remain as reference-only metadata for auditability.

## 1.5 Reproducibility

Every pipeline transformation must be scripted, deterministic, and replayable. Results must be derived from stable inputs plus immutable config and code. Randomization is allowed only when explicitly declared and controlled in a training view or recipe.

## 1.6 Determinism

Schema validation, AQL queries, quality scoring, checksum computation, release manifest generation, migration transformations, and packaging must be deterministic given identical inputs.

## 1.7 Explainability

Quality scores, review outcomes, compilation decisions, and compilation artifacts must include structured reasons or metadata sufficient for audit and future receiver explanation.

## 1.8 Long-term Maintainability

Contracts, schemas, and lifecycle states must be versioned. Additive evolution must follow the required path:

Specification → ADR → Migration → Implementation

Implementation never leads.

---

# Section 2 — Architecture

## 2.1 Subsystem Map

Atlas is composed of the following subsystems. Each is a public contract surface. Internal refactors may occur; external behavior must not change without a spec change and migration.

### 2.1.1 Source Registry

The `metadata/source_registry.json` registry is the authoritative machine-readable source inventory. Every candidate, accepted, review, or rejected source is recorded here. The registry is append-corrected by ADR, not by raw ingestion. It is the input to license gating, attribution checking, and ingestion planning.

Key public contract:
- `id`, `name`, `url`, `category`, `license`, `tier`, `status`, `scores`, `recommendation`, `notes`

Rejected records are preserved with `status: rejected` and are never promoted into dataset data.

### 2.1.2 Acquisition Engine

Resumable ingestion with versioning, packs, lifecycle, and diff. Responsibilities include:
- coordinating pipeline stages across records
- generating knowledge packs and collections
- writing version snapshots
- producing release manifests and hash chains
- exposing deterministic query and selection interfaces

### 2.1.3 License Engine

Single-point license gating. Allowed, conditional, and denied license classes are policy encoded in source registry and acquisition manifest policy. The license engine deterministically classifies each record’s resolved license and rejects denied and unknown licenses at curation and release boundaries.

### 2.1.4 Integrity Engine

Tamper-evident checksum verification and hash-chain audit. Files under integrity protection include curated artifacts, schemas, manifests, packs, and review artifacts. The integrity system normalizes dict/list registry formats and supports dataset-specific and engine-specific checksum registries.

### 2.1.5 Knowledge Objects

Canonical operational record shape, including messages, lineage, attribution, verification, and quality. Knowledge objects never store model-specific formatting.

### 2.1.6 Knowledge Packs

Focused subsets of curated records packaged as JSONL plus manifest and checksums. Packs include aggregation statistics, filter criteria, and file integrity metadata.

### 2.1.7 Knowledge Collections

Named aggregations of packs forming higher-level bundles. Collections compute aggregate statistics across member packs and verify collection-level checksums.

### 2.1.8 Training Views

Derived, reproducible, disposable model-specific renderings of collections or curated subsets. Views are generated from canonical data and templates. The canonical dataset remains the source of truth.

### 2.1.9 Training Recipes

Declarative, non-data specifications of how to generate a training view or dataset slice. Recipes encode collections, filters, thresholds, sampling, deduplication, output target, supported models, and compatibility constraints.

### 2.1.10 Release Engineering

Frozen release artifacts assembled from manifest, gates, semantic diff, download integrity, hash chain, signatures, and release metadata. Releasability requires all required gates to pass.

### 2.1.11 AQL

Deterministic query language with tag-style and SQL-style syntax for selecting, filtering, aggregating, and ordering dataset objects.

### 2.1.12 Lifecycle

Immutable state machine governing record progression from raw through processing, curation, review, release, archival, and rejection.

### 2.1.13 Quality Engine

Automated 7-dimension scoring, human review schema, calibration artifacts, and explainable outputs.

### 2.1.14 Calibration

Automated scoring versus human review comparison. Reports may include accuracy, bias by category/source, confidence weighting, and threshold recommendations.

### 2.1.15 Migration Framework

Every schema or canonical contract change is delivered as a named, versioned migration. Migrations extend records via additive or transform steps and must be reversibly recorded in an applied migrations ledger.

### 2.1.16 ADR Framework

Architecture Decision Records formalize contract-level choices. No contract change is accepted without an accepted ADR describing context, decision, alternatives, consequences, and compatibility notes.

### 2.1.17 Self-Test Framework

A deterministic, network-isolated probe validates invariants including schema gates, license correctness, dependency checks, checksum registry integrity, migration ledger presence, and lineage completeness.

### 2.1.18 Versioning

Semantic versioning applies to the Atlas spec, dataset versions, packs, collections, recipes, training views, and releases. Each version target has its own index and changelog route.

---

# Section 3 — Canonical Knowledge Object

## 3.1 Coordinate Identity

The canonical record is defined by:
- `schemas/dataset_schema.json` for the strict curated gate
- `schemas/knowledge_object_schema.json` for the full operational superset
- `schemas/chat_schema.json` for message turn contracts

## 3.2 Frozens Fields

| Field | Purpose | Data Type | Constraints | Validation Rules | Migration Rules | Deprecation Strategy |
|------|---------|-----------|------------|------------------|-----------------|----------------------|
| `id` | Stable unique key | String | ASCII lowercase, digits, `-`, `_`; 3-128 chars | Must match category/subcategory/sequence pattern | Add new patterns only via migration; preserve historical IDs | Freeze during release lifecycle |
| `category` | Top taxonomy bucket | Enum, string | One of nine Atlas categories | Strict enum | Add enum via migration with index update | Strict freeze per release |
| `subcategory` | Local taxonomy bucket | String | 1-64 chars | Aligned to category/subcategory index | Add valid subcategories via manifest; sync docs | Additive only |
| `type` | Structural shape | Enum, string | instruction/conversation/qa/reasoning | Validate enum | Deprecate shapes via ADR + migration | Retire via removal policy |
| `source` | Origin metadata | Object | Must include `name` and `license` | Provider class plus license declared in source registry | Extend fields as additive | Non-breaking additions only |
| `messages` | Conversation turns | Array | minItems 2, each turn 1-64000 chars | Base schema/chat schema plus user/assistant presence | Extend message metadata via additive migration | Backward-compatible additions only |
| `language` | Coverage tracking | String | ISO 639-1 plus optional region | Regex `[a-z]{2}(-[A-Z]{2})?` | Add dialect coverage via additive policy | No removal |
| `difficulty` | Curriculum aid | Integer | 0-3 | Enum range | Unchanged | Freeze as optional default 0 |
| `tags` | Retrieval/keywords | String array | lowercase hyphenated; unique; max 20 | Schema-level uniqueness and pattern | Add tag taxonomy via metadata index | Backward-compatible additions only |
| `quality_score` | Heuristic/human score | Integer | 0-10 | Strict 0-10 integer range | Same scale forever; if model changes, keep scale and recalibrate via release | Scale freeze |
| `verified` | Reviewer approval mirror | Boolean | true only when `verification_status == approved` | Crosscheck both fields during validation | Maintain invariant in migrations | Do not decouple without ADR |
| `notes` | Audit signal | String | max 2000 | Empty string if none | Markdown or plain text allowed without schema change | None planned |
| `knowledge_type` | Knowledge kind | Enum, string | fact/procedure/concept/reasoning/code/reference/creative | Superset schema only | Add enum via migration | Additive only |
| `canonical_answer` | Authoritative answer | String | Non-empty | Required in superset schema | No breaking schema rule changes | Freeze |
| `metadata` | Structured metadata | Object | Free form | Validate `language`, `synthetic`, `model_generated`, `source_confidence` shape | Additional properties allowed in license-safe cases | Avoids breaking finalizers |
| `source_attribution` | Provenance/compliance | Object | Requires `source_id`, `name`, `url`, `license`, `attribution_text` | Must resolve to `metadata/source_registry.json`; share-alike must match license; attribution_text required for CC-BY-SA | Extend only with additive fields | None |
| `license` | Resolved license | String | 1-64 chars; never `unknown` at curated stage | Must pass denied-license gate; never ingest denied/unknown in curated/released | Reclassification requires source evidence and ADR | Reclassifying is exceptional |
| `verification_status` | Human workflow state | Enum, string | pending/approved/rejected/needs_revision | Valid lifecycle transition required to change state | Do not widen enum without ADR | Legacy mapping preserved |
| `lineage` | Traceability chain | Object | Required keys: source, transformations, knowledge_object, curated_dataset, training_view, future_model | Structural required keys; transformations ordered | Extend chain fields only by additive migration | Breaking chain requires data regeneration |
| `training_view_eligibility` | Eligibility flags | Object | qwen, llama, deepseek booleans required | Must match model support declarations from recipes | Add future model flags by migration or recipe config | Backward-compatible additions only |

## 3.3 Null Handling Policy

- Missing optional fields may be omitted or set to documented defaults.
- Missing required fields fail validation.
- `unknown` license is not accepted outside raw/processing.
- Empty strings must be explicit defaults, not placeholder nulls.

## 3.4 Stability Guarantees

Curated records are immutable. Raw records are never modified. Processing outputs may be regenerated. A Knowledge Object schema change applies to future objects; historical objects may be transformed via explicit migrations only.

---

# Section 4 — Knowledge Lineage

## 4.1 Lineage Chain

`Source → Transformations → Knowledge Object → Knowledge Pack → Collection → Training Recipe → Training View → Model Training → Evaluation → Release`

## 4.2 Required Metadata Per Stage

| Stage | Required Metadata |
|------|------------------|
| Source | `source_id`, `name`, `url`, `license_class`, `access_date`, `constraints` |
| Transformations | Ordered list of clean/dedup/score/migrate identifiers |
| Knowledge Object | `id`, `canonical_answer`, `messages`, `knowledge_type`, `verification_status`, `lineage` |
| Knowledge Pack | `pack_name`, `pack_version`, `filter_criteria`, `statistics`, `files`, `signature` |
| Collection | `collection_name`, `pack_names`, `statistics`, `collection_checksum` |
| Training Recipe | `recipe_id`, `recipe_version`, `collections`, `filters`, `thresholds`, `sampling`, `dedup`, `output_target`, `supported_models` |
| Training View | `view_id`, `recipe_id`, `model_target`, `generated_at`, `checksums`, `source_anchor` |
| Model Training | Not stored in Atlas |
| Evaluation | Not stored in Atlas unless Atlas-owned evaluation sets are versioned |
| Release | `release_id`, `chain_hash`, `content_hash`, `gates_passed`, `release_type`, `previous_hash` |

## 4.3 Traceability Requirements

- Every released object must be traceable to a source and collection.
- Every collection must be traceable to packs and recipes.
- Every recipe must avoid embedding actual training data.
- Source_registry changes require ADR.

---

# Section 5 — Lifecycle

## 5.1 Lifecycle States

- `raw`: immutable ingestion source
- `processing`: in pipeline
- `curated`: passed pipeline quality/license/schema gates; not yet human-approved
- `review`: in explicit review queue
- `approved`: human-approved
- `released`: included in a frozen release
- `archived`: superseded or deprecated; retained for lineage
- `rejected`: did not pass gates or review; may re-enter pipeline only with explicit transition record

## 5.2 Legal Transitions

| From | To |
|------|----|
| raw | processing, rejected |
| processing | curated, rejected, raw |
| curated | review, processing, rejected |
| review | approved, rejected, needs_revision |
| needs_revision | review, rejected, curated |
| approved | released, review |
| released | archived |
| archived | — |
| rejected | raw |

Any transition not listed is invalid and must fail validation.

## 5.3 Audit Requirements

Every state change is recorded with `timestamp`, `source`, and `reason`. The lifecycle registry is part of integrity coverage.

---

# Section 6 — Quality Model

## 6.1 Dimensions

1. Accuracy
2. Completeness
3. Technical correctness
4. Clarity
5. Usefulness
6. Originality
7. Relevance

## 6.2 Automated Scoring

Automated scorer returns an integer 0-10, computed from weighted dimensions.

## 6.3 Human Scoring

Human review uses the same dimension scale plus `verdict` and `confidence`.

## 6.4 Calibration

Calibration reports measure automated score accuracy against human review, including bias by category/source and confidence-weighted metrics.

## 6.5 Quality Score Invariants

- Automated and human scores use the same 1-10 integer scale.
- Curated gating minimum is configurable per scope, but must never lower than the current freeze gate.
- Records below threshold must be routed explicitly; silent promotion is forbidden.
- Records without valid review evidence cannot be promoted to approved/released unless the release gate explicitly approves that class.

---

# Section 7 — Licensing

## 7.1 Allowed Licenses

MIT, Apache-2.0, BSD-2/3, CC-BY-3.0/4.0, CC0-1.0, ODC-BY, Public Domain, arXiv non-exclusive license, and other permissive licenses explicitly allowlisted in the source registry.

## 7.2 Allowed with Conditions

- CC-BY-SA-3.0/4.0 with per-record attribution_text and share-alike tracking
- BigCode Open RAIL-M with permissive-file subsetting and documented RAIL-M obligations in the ingestion runbook
- Gated/access-restricted sources with re-verified license and recorded accepted terms

## 7.3 Rejected Licenses

- CC-BY-NC-*, CC-BY-ND-*
- Proprietary/all-rights-reserved
- Unknown/ambiguous
- ToS-violating sources such as ShareGPT and Reddit exports

## 7.4 Unknown License Policy

`license: unknown` is never allowed in curated or training data. Unresolved unknown records must be rejected or deferred until review resolves license.

## 7.5 Attribution Requirements

Attribution text must be included in `source_attribution.attribution_text` when source license requires it. Copying and downstream redistribution must preserve source attribution records.

---

# Section 8 — Knowledge Packs

## 8.1 Pack Format

Each pack is independently verifiable and includes:
- data file: `{name}.jsonl.gz` or `.jsonl`
- manifest: `{name}_manifest.json`
- checksums: `{name}_checksums.json`

## 8.2 Manifest Contract

| Field | Contract |
|------|----------|
| `pack_name` | Stable identifier |
| `pack_version` | Semver pack version |
| `generated` | ISO-8601 timestamp |
| `description` | Human description |
| `total_records` | Count after filtering |
| `filter_criteria` | categories and min_quality |
| `statistics` | by_category, by_license, avg_quality, min/max quality |
| `files` | filename → sha256 |
| `metadata` | optional engine/run metadata |

## 8.3 Checksums

A detached `{name}_checksums.json` must include sha256 for every data file and for the manifest.

## 8.4 Compatibility

Pack consumers must not mutate pack files. Pack checksum mismatch invalidates the pack.

---

# Section 9 — Knowledge Collections

## 9.1 Collection Format

Collections live under `knowledge_packs/collections/<name>/` and include:
- collection manifest: `{name}_collection.json`
- index entry in `metadata/collection_index.json`

## 9.2 Aggregation Rules

- Aggregate statistics are composed from member pack manifests only.
- Collection checksum is computed over canonical collection identity: name, packs, total_records, generated timestamp.

## 9.3 Compatibility Rules

Missing referred packs invalidate collection creation. Collection index may contain at most one entry per `name`.

## 9.4 Integrity Rules

Recompute `collection_checksum` during verification. Mismatch or missing manifest means collection is invalid.

---

# Section 10 — Training Recipes

## 10.1 Definition

A Training Recipe is a declarative description of how to produce a reproducible training slice or view. A recipe never contains training data.

## 10.2 Required Fields

- `recipe_id`
- `recipe_version`
- `collections`
- `filters`
- `quality_thresholds`
- `confidence_thresholds`
- `sampling_strategy`
- `deduplication_strategy`
- `output_target`
- `supported_models`
- `compatibility` / `min_atlas_version`

## 10.3 Behavior Requirements

- Recipes must be replayable from canonical Atlas data plus config.
- Recipe changes that alter selection semantics require a new recipe version.
- Recipes must not expose model-specific formatting constraints that belong to templates.

---

# Section 11 — Training Views

## 11.1 Definition

A Training View is a generated, disposable, reproducible rendering of canonical data for a target model or evaluation scenario.

## 11.2 Stability Rules

- Canonical Atlas records are the source of truth.
- Training views may be regenerated or invalidated without changing underlying objects.
- Generated views must include checksums, `generated_at`, and source anchors to originating collections/recipes.

## 11.3 Model Agnosticism

New target models are supported by adding templates/config, not by changing canonical objects.

---

# Section 12 — Atlas Query Language

## 12.1 Guarantees

- Deterministic execution
- Safe parser; never evaluates raw expressions
- Supports selection, filtering, grouping, ordering, limit/offset, aggregation

## 12.2 Grammar

### 12.2.1 Tag Style

Condition expressions joined by whitespace. Equality via colon. Numeric comparisons via operators. IN lists supported. Field aliases normalized to canonical form.

### 12.2.2 SQL Style

```sql
SELECT [fields|*]
[WHERE condition (AND condition)*]
[GROUP BY field]
[ORDER BY field [ASC|DESC]]
[LIMIT N]
[OFFSET N]
```

## 12.3 Operators

=, >=, <=, >, <, !=, in, exists

## 12.4 Reserved Keywords

SELECT, WHERE, GROUP, BY, ORDER, LIMIT, OFFSET, ASC, DESC, AND, OR, IN, NOT, AS, COUNT, MIN, MAX, AVG, SUM

## 12.5 Deterministic Execution Rules

- Query on identical data/tie behavior must return same result
- Case-insensitive string matching for fields without explicit case sensitivity requirement
- Lexicographic ordering default when ordering equal keys
- Grouping is lexicographic on selected key
- No hidden mutation during query execution

---

# Section 13 — Release Engineering

## 13.1 Release Manifest

Each release includes:
- `release_id`
- `version`
- `release_type`
- `created_at`
- `total_records`
- `chain_hash`
- `content_hash`
- `previous_hash`
- `gates_passed`
- `release_id` derived from chain hash prefix for readability

## 13.2 Release Gates

Required gates:
- `quality_gate`
- `license_gate`
- `schema_gate`
- `verification_gate`
- `category_balance_gate`
- `no_unknown_license_gate`
- `no_rejected_source_gate`

Gates are pass/fail/warn. Releasable artifacts require all required gates passing.

## 13.3 Dataset Diff

Computes added, removed, and changed record ids between versions; version manifests store source_files and statistics for diff reproducibility.

## 13.4 Semantic Diff

Semantic diff identifies breaking or non-additive changes and reports impact.

## 13.5 Hash Chain

Genesis release has no previous hash. Each subsequent release stores `previous_hash` and a `chain_hash` for audit continuity.

## 13.6 Release Signature

Signatures are derived from stable content hashes and retained for verification.

## 13.7 Verification

Release verification re-checks checksums, integrity chain, gate results, and release index consistency.

## 13.8 Rollback

Atlas release rollback is a reference-only operation: superseded versions remain intact in `curated/` for lineage and audit. Training views generated from prior versions are disposable and may be regenerated from canonical history.

---

# Section 14 — Migration

## 14.1 Migration Contract

Every schema or contract change must include:
- migration script with ordered `up`/`down` semantics
- compatibility validation output
- ADR reference
- release note describing usage impact
- backward compatibility statement accepting old records unless explicitly breaking

## 14.2 Applied Ledger

Applied migrations are recorded in an immutable ledger path, default `migrations/applied.json`, such that engine self-tests can assert migration reproducibility on fresh artifacts.

---

# Section 15 — Extension Points

## 15.1 Allowed Additive Extensions

- New licenses added to allowlist with source registry entry
- New categories and subcategories via taxonomy index
- New quality metrics via schema additions
- New model targets via template/config instead of canonical change
- New recipes via programmatic registration without core changes
- New collections via composition only
- New knowledge packs via filter config

## 15.2 Planned Extension Points

- vector indexes
- graph storage
- retrieval-augmented interfaces
- score-to-preference ties for RLHF/data selection without canonical data schema changes
- multilingual metadata and retrieval hooks

## 15.3 Breaking Extensions (Forbidden Without ADR)

- Changing required field semantics
- Renaming categories/ids
- Changing lineage chain structure in ways that invalidate old object attestations
- Adding license classes that invalidate commercial-safe guarantees

---

# Section 16 — Security

## 16.1 Trust Boundaries

Raw sources may be external, human-reviewed, or generated. Curated data is the internal trust boundary. Model output formatting is untrusted.

## 16.2 Network Policy

Self-tests and validation suites must be runnable without network if possible. Network use must be explicit and recorded.

## 16.3 Write Policy

Write paths are limited to:
- processing outputs
- curated outputs after human approval
- metadata/collection/version/registry/index artifacts
- review queueSigned releases are append-only after finalization.

## 16.4 Integrity Verification

Integrity check is required before any release, collection promotion, or view generation.

## 16.5 Tamper Detection

Any modification to integrated files invalidates discovered checksums and recorded hash chain entries.

## 16.6 Audit Logging

State transitions, release events, review actions, and migration applications are required log events with timestamps and actor attribution where supported.

---

# Section 17 — Testing

## 17.1 Required Suites

- Self-test: network-isolated probe for invariant validation
- Release-check: infrastructure + manifest + chain + collections
- Schema validation: base schema and knowledge object schema
- Quality validation: scorer and reviewer schema/format
- License validation: denied/allowed/unknown coverage
- Migration validation: applied ledger present and ordered
- Integrity validation: checksum registry matches filesystem
- Determinism validation: same inputs produce identical outputs and AQL query results

## 17.2 Independence

Each validation suite must be independently invocable. CI must run at least schema, license, integrity, and self-test suites.

---

# Section 18 — Versioning Policy

## 18.1 Atlas Specification Versioning

Specification changes follow semver. Major bump reserved for breaking contract change. Minor for additive public contract. Patch for clarifications/typographic changes.

## 18.2 Dataset Versioning

`curated/v{MAJOR}.{MINOR}` with manifest, changelog, and index entry. Data files frozen and checksum-protected.

## 18.3 Pack/Collection/Recipe/View/Release Versioning

Each artifact carries its own versioning scheme aligned to dataset and spec compatibility. Downstream components must reject incompatible combinations according to compatibility metadata.

---

# Section 19 — Roadmap

## 19.1 Implemented

- Phase 1–3A/3B/C pipeline, schemas, license gating, human review, quality calibration
- Phase 3D resumable acquisition engine with versioning, packs, lifecycle, diff
- Phase 4A.5 release engineering: release manifest, release gates, semantic diff, hash chain, collections, AQL, self-test invariants

## 19.2 Approved

- Atlas v1.0 Specification Freeze per this document
- Deterministic quality calibration and reviewer workflow
- Release-check and self-test guardrails for releases

## 19.3 Planned

- Phase 4B — Progressive Expansion
- Phase 5 — Training View Generator
- Phase 6 — QLoRA Pipeline integration using recipes/views
- Phase 7 — Evaluation Framework
- Phase 8 — Hermes-v1 knowledge loop integration

## 19.4 Experimental

- RAG retrieval indexing
- graph-backed lineage dashboards
- preference/RLAIF hooks without canonical data schema change
- automated migration replay tooling

---

# Section 20 — Atlas Constitution

1. Atlas is the single source of truth.
2. Training views are disposable.
3. Knowledge objects are immutable after release.
4. Every release must be reproducible.
5. Commercial safety is mandatory.
6. Human review has final authority.
7. Every object must be traceable.
8. Every score must be explainable.
9. No implementation may violate this constitution.
