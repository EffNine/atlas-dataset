# Canonical Service Registry

> Phase 4C.0 — Architecture Consolidation & Dependency Unification
> Generated: 2026-07-28

This document catalogs every reusable service in Atlas, its public API, consumers, non-consumers, and future extension points.

Services are the building blocks that orchestration layers compose. They are pure (no network, no side effects beyond their own I/O boundary), deterministic, and independently testable.

---

## 1. PayloadResolver

**Module:** `scripts/payload_resolver.py`  
**Class:** `PayloadResolver(dataset_root: str | Path)`

### Purpose
The canonical record lookup service. Every workflow that needs a record payload must use PayloadResolver instead of manually searching files. It implements a defined priority chain with fallback between layers.

### Public API

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `resolve(record_id)` | `record_id: str` | `{found, payload, source_layer, source_file, checksum}` | Look up a record by ID across all data layers |
| `resolve_many(ids)` | `ids: list[str]` | `list[result]` | Batch resolve |
| `explain(record_id)` | `record_id: str` | `{found, source_layer, source_file, priority_chain, ...}` | Explain where a record was found and the full lookup path |
| `refresh()` | — | `None` | Rebuild internal file index |

### Lookup Priority Chain
1. `review_cache` — `review_queue/*.jsonl`
2. `review_input_artifact` — `review/v0.2/batch_001_input.jsonl`, `review/quality_reviews.jsonl`
3. `decision_artifact` — `review/decisions/**/*.jsonl`
4. `curated_dataset` — `curated/v0.2/data/*.jsonl`
5. `knowledge_pack` — `knowledge_packs/*.jsonl.gz`
6. `archived_dataset` — `curated/v0.1/*.jsonl`

### Consumers
- Human review workflow (batch resolution)
- Revision resolution workflow
- Quality calibration (payload validation)
- Any future script that needs to find a record by ID

### Non-consumers
- Acquisition Engine (works with record lists, not single ID lookups)
- Release Manager (operates on curated files, not individual records)
- Quality Evaluation Engine (operates on input records, doesn't look them up)
- AQL (operates on provided record lists)

### Future Extension Points
- Add a `release_layer` priority tier between `curated_dataset` and `knowledge_pack`
- Support `record_id` aliasing for id-repaired records
- Add a reverse lookup (find all records from source_id)
- Add a TTL-based cache for repeated lookups in batch operations

---

## 2. QualityEvaluationEngine (QEE)

**Module:** `scripts/quality_score.py`  
**Entry:** `score_record(rec)`, `evaluate_record(rec)`

### Purpose
Multi-dimensional, deterministic, explainable quality scorer for Atlas knowledge objects. Scores records across 7 dimensions (accuracy, completeness, technical_correctness, clarity, usefulness, originality, relevance), producing a composite 1–10 score with per-dimension rationale and confidence metrics.

### Public API

| Function | Parameters | Returns | Description |
|----------|-----------|---------|-------------|
| `score_record(rec)` | `rec: dict` | `(int quality_score, dict[dimension]->float)` | Legacy API — returns score + dimension dict |
| `evaluate_record(rec)` | `rec: dict` | `{quality_score, quality_continuous, dimensions, confidence, confidence_level, rationale, flags, explanation}` | Full evaluation with rationale |
| `WEIGHTS` | — | `dict[str, float]` | Published dimension weights (sum to 1.0) |

### Design Invariants
- **Stdlib-only** — no pip dependencies
- **Deterministic & pure** — same record → same result
- **Read-only** — never mutates input
- **Tolerant** of missing/partial records
- **Confidence separated from score** — confidence reflects evidence, not quality

### Consumers
- `scripts/calibrate_quality.py` — compares QEE vs human review
- `scripts/gen_calibration_sample.py` — generates stratified sample for review
- `scripts/freeze_calibration_baseline.py` — freezes baseline for regression testing
- `scripts/progressive_expansion.py` — scores new records during expansion
- `scripts/validate_quality_engine.py` — validates quality engine behavior

### Non-consumers
- Acquisition Engine (does inline quality sorting, not QEE — legacy path)
- Release Gates (uses quality_score field, not the engine directly)
- AQL (operates on stored scores)
- Payload Resolver

### Future Extension Points
- Add a plugin system for model-assisted scoring (API-based, optional)
- Add per-category weight overrides (e.g., different weights for code vs creative)
- Add a streaming batch mode for large-scale evaluation
- Expose per-dimension confidence separately

---

## 3. LicenseGate

**Module:** `scripts/validate_dataset.py`  
**Entry:** `is_denied_license(lic: str) -> bool`

### Purpose
The single source of truth for license policy in Atlas. Implements the commercial-safety gate: denies NC, ND, proprietary, all-rights-reserved, and unknown licenses.

### Public API

| Function | Parameters | Returns | Description |
|----------|-----------|---------|-------------|
| `is_denied_license(lic)` | `lic: str` | `bool` | True if license matches a denied pattern (case-insensitive substring match) |

### Denied License Patterns
- `cc-by-nc*` — Non-commercial
- `cc-by-nd*` — No-derivatives
- `proprietary`
- `all-rights-reserved`
- `unknown`

### Consumers
- `atlas.py` (CLI — self-test, ingest-pilot)
- `acquisition_engine/engine.py` (AcquisitionEngine.dry_run)
- `acquisition_engine/release.py` (ReleaseGates.check_license_gate — via lazy import)
- `scripts/validate_dataset.py` itself (direct use)
- `scripts/progressive_expansion.py`
- `scripts/progressive_expansion_v2.py`

### Non-consumers
- `scripts/quality_score.py` (no license logic)
- `scripts/aql.py` (no license logic)
- `scripts/payload_resolver.py` (no license logic)
- `scripts/validate_knowledge_object.py` (uses structural check only)

### Future Extension Points
- Add a `LicenseClassifier` class that returns more granular results (DENIED, ALLOWED, CONDITIONAL) instead of just bool
- Move denied patterns into a config file (e.g., `configs/licensing/denied_patterns.json`) so policy changes don't require code changes
- Add per-source overrides (e.g., some sources have documented exceptions)
- Add attribution obligation tracking (for CC-BY-SA, RAIL-M)

---

## 4. ReleaseGate

**Module:** `scripts/acquisition_engine/release.py`  
**Class:** `ReleaseGates(records, manifest_data)`

### Purpose
Composite gate checker that validates a set of records against all release criteria: quality, license, schema, verification, category balance, unknown license, and rejected sources.

### Public API

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `check_quality_gate(min_score=7)` | `min_score: int` | `ReleaseGateResult` | 100% records ≥ min_score |
| `check_license_gate()` | — | `ReleaseGateResult` | No denied licenses |
| `check_schema_gate()` | — | `ReleaseGateResult` | Structural validity |
| `check_verification_gate(registry, actual)` | optional checksums | `ReleaseGateResult` | File checksum match |
| `check_category_balance_gate(tolerance=0.05)` | `tolerance: float` | `ReleaseGateResult` | Category distribution within tolerance |
| `check_no_unknown_license_gate()` | — | `ReleaseGateResult` | No "unknown" licenses |
| `check_no_rejected_source_gate()` | — | `ReleaseGateResult` | No rejected-source records |
| `run_all(registry, actual)` | optional checksums | `list[ReleaseGateResult]` | Run all 7 gates |
| `all_passed(results)` | `list[ReleaseGateResult]` | `bool` | Static check |
| `format_results(results)` | `list[ReleaseGateResult]` | `str` | Readable report |

### Consumers
- `ReleaseManager.create_release()` — runs gates before releasing
- `atlas.py` `cmd_release_check()` — standalone gate check
- `atlas.py` `_run_release_self_tests()` — invariant testing

### Non-consumers
- Everything in the `processing/` directory
- Quality Evaluation Engine
- Schema Validation modules

### Future Extension Points
- Add a `required_gates` config file so gates can be toggled per release
- Add gate result aggregation into the VerificationLog
- Add a `check_reproducibility_gate` that verifies deterministic reproduction

---

## 5. ReleaseManager

**Module:** `scripts/acquisition_engine/release.py`  
**Class:** `ReleaseManager(dataset_root)`

### Purpose
Creates, lists, verifies, and manages frozen, signed, hash-chained releases of the Atlas dataset. Each release is a verifiable snapshot with gate evidence, semantic diff, and chain-of-custody signatures.

### Public API

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `list_releases()` | — | `list[release_index_entry]` | All releases in index |
| `get_latest_release()` | — | `release_index_entry \| None` | Most recent release |
| `get_release(version)` | `version: str` | `release_index_entry \| None` | Specific release |
| `release_exists(version)` | `version: str` | `bool` | Existence check |
| `load_release_manifest(version)` | `version: str` | `dict \| None` | Full manifest |
| `create_release(version, sources, changelog, ...)` | multiple | `dict` | Create new release |
| `verify_release(version)` | `version: str` | `dict` | Verify gate + checksum + signature |
| `verify_release_chain()` | — | `dict` | Verify entire hash-chain |
| `release_summary()` | — | `dict` | Summary of all releases |

### Consumers
- `atlas.py` CLI (`--release --create`, `--release --verify`, `--release --list`, etc.)
- Self-test framework (`_run_release_self_tests`)
- Any automation that needs to inspect release state

### Non-consumers
- Acquisition Engine (VersionManager is separate; ReleaseManager is post-pipeline)
- Quality Evaluation Engine
- Progressive Expansion (creates records, not releases)

### Future Extension Points
- Add release rollback with full chain recovery
- Add release comparison reports (v0.1 vs v0.2)
- Add downstream consumer notifications on new releases
- Add release batch gating (subset of records per release)

---

## 6. VersionManager

**Module:** `scripts/acquisition_engine/versioning.py`  
**Class:** `VersionManager(dataset_root)`

### Purpose
Manages versioned snapshots of the curated dataset. Each version is a frozen, immutable snapshot with full statistics and changelog. Supports listing, diffing, and rollback.

### Public API

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `list_versions()` | — | `list[dict]` | All recorded versions |
| `current_version()` | — | `str \| None` | Most recent version |
| `get_version_manifest(version)` | `version: str` | `dict \| None` | Read version manifest |
| `freeze(version, source_paths, stats, changelog)` | multiple | `dict` | Freeze a new version |
| `diff(from_version, to_version)` | two versions | `dict \| None` | Compare two versions |
| `rollback(to_version)` | `version: str` | `str \| None` | Roll back pointer |

### Consumers
- `AcquisitionEngine.execute()` — freezes versions after ingestion
- CLI scripts that need to inspect version history

### Non-consumers
- ReleaseManager (separate concern — ReleaseManager handles the signed-release pipeline)
- Quality Evaluation Engine
- AQL
- Payload Resolver

### Future Extension Points
- Add `archive(version)` to move old data to cold storage
- Add version aliasing (`latest`, `stable`)
- Add version freeze validation hook (pre-freeze gate)

---

## 7. LifecycleManager

**Module:** `scripts/acquisition_engine/lifecycle.py`  
**Class:** `LifecycleTracker(metadata_dir)`

### Purpose
State machine enforcing valid record progression through pipeline stages: raw → processing → curated → review → approved → released → archived. Each transition is timestamped and attributed to its source (engine, human, auto).

### Public API

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `transition(record_id, to_state, source, reason)` | key transition params | `dict` | Single record transition |
| `batch_transition(record_ids, to_state, source, reason)` | batch params | `dict[record_id → list]` | Batch transition |
| `get_record_state(record_id)` | `record_id` | `str \| None` | Current state |
| `state_summary()` | — | `dict[str, int]` | Count per state |
| `all_records_in_state(state)` | `state` | `list[str]` | Records in a state |
| `transition_history(record_id)` | `record_id` | `list[dict]` | Full history |
| `report()` | — | `dict` | Full lifecycle report |

### Consumers
- `AcquisitionEngine.execute()` — tracks every record through pipeline stages
- Migration framework (when migrations change state)
- Review workflow (when humans approve/reject)

### Non-consumers
- Release Manager (reads frozen state, doesn't change lifecycle)
- Quality Evaluation Engine (no lifecycle awareness)
- AQL (can query state but doesn't manage it)

### Future Extension Points
- Add lifecycle hooks (pre/post transition callbacks)
- Add state timeout detection (records stuck in a state too long)
- Add lifecycle export for downstream audit tools

---

## 8. KnowledgePackManager

**Module:** `scripts/acquisition_engine/knowledge_pack.py`  
**Entry:** `generate_knowledge_pack(...)`, `verify_knowledge_pack(...)`

### Purpose
Generates and verifies portable, independently-verifiable Knowledge Packs — focused subsets of records with manifest, statistics, and integrity checksums.

### Public API

| Function | Parameters | Returns | Description |
|----------|-----------|---------|-------------|
| `generate_knowledge_pack(name, records, output_dir, ...)` | `name, records, output_dir, category_filter, min_quality, compress, description, metadata` | `dict` (manifest) | Create a pack |
| `verify_knowledge_pack(pack_dir, manifest, ...)` | pack locators | `dict` (verification result) | Verify pack integrity |

### Consumers
- `AcquisitionEngine.execute()` — generates packs post-pipeline
- CLI scripts that need portable dataset subsets

### Non-consumers
- `KnowledgeCollectionManager` (reads packs but doesn't generate them)
- `ReleaseManager` (separate artifact path)
- Quality Evaluation Engine

### Future Extension Points
- Add pack-level quality gate filtering
- Add pack merge operation (combine packs)
- Add pack-to-release linking

---

## 9. KnowledgeCollectionManager

**Module:** `scripts/acquisition_engine/knowledge_collection.py`  
**Class:** `KnowledgeCollectionManager(dataset_root)`

### Purpose
Manages named groupings of Knowledge Packs. Collections form a higher-level organizational layer (e.g., "v0.1-all" groups all v0.1 packs).

### Public API

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `list_collections()` | — | `list[dict]` | All registered collections |
| `get_collection(name)` | `name` | `dict \| None` | Collection by name |
| `collection_exists(name)` | `name` | `bool` | Existence check |
| `create_collection(name, pack_names, description, metadata)` | membership params | `dict` (manifest) | Create collection |
| `verify_collection(name)` | `name` | `dict` | Verify integrity |

### Consumers
- `atlas.py` CLI (`--collection --create`, `--collection --list`, `--collection --verify`)
- Self-test framework

### Non-consumers
- Acquisition Engine (post-pipeline artifact)
- Release Manager (separate organizational layer)

### Future Extension Points
- Add collection-level AQL querying
- Add collection diffing (compare membership)
- Add collection auto-generation from release metadata

---

## 10. AQL Engine

**Module:** `scripts/acquisition_engine/aql.py`  
**Entry:** `execute_query()`, `validate_query()`, `describe_query()`, `preview_query()`, `AQLQuery`

### Purpose
Deterministic query language for selecting, filtering, aggregating, and ordering dataset records. Supports tag-style, SQL-style, and compact syntax variants.

### Public API

| Function | Parameters | Returns | Description |
|----------|-----------|---------|-------------|
| `execute_query(query, records)` | `query: str, records: list[dict]` | `{records, count, total_available, query, ...}` | Execute query |
| `validate_query(query)` | `query: str` | `{valid, errors}` | Validate syntax |
| `describe_query(query)` | `query: str` | `str` | Human-readable description |
| `preview_query(query)` | `query: str` | `{parsed, fields, conditions, ...}` | Parsed representation |
| `AQLQuery(query_string)` | `query: str` | `AQLQuery` object | Parsed query object |

### Consumers
- `atlas.py` CLI (`--query --execute`, `--query --validate`)
- Self-test framework
- Any automation needing record selection

### Non-consumers
- Acquisition Engine (operates on post-hoc record sets, not pipeline)
- Release Manager
- Quality Evaluation Engine

### Future Extension Points
- Add AQL optimization (query plan, index hints)
- Add AQL as a library import for external tools
- Add cross-pack/cross-collection querying

---

## 11. DatasetDiff

**Module:** `scripts/acquisition_engine/dataset_diff.py`  
**Entry:** `compute_diff()`, `load_records_index()`, `render_diff_markdown()`

### Purpose
Computes structured diffs between two record sets (typically two dataset versions), showing added/removed/changed records, field-level changes, and summary statistics.

### Public API

| Function | Parameters | Returns | Description |
|----------|-----------|---------|-------------|
| `load_records_index(file_paths)` | `list[Path]` | `dict[id → record]` | Load JSONL files into ID-keyed index |
| `compute_diff(from_records, to_records)` | two `dict[id→rec]` | `dict` | Compute comprehensive diff |
| `render_diff_markdown(diff)` | diff dict | `str` | Markdown report |

### Consumers
- `VersionManager.diff()` (calls compute_diff-like logic inline)
- `AcquisitionEngine` (via compute_diff)
- Release reports

### Non-consumers
- AQL (separate query concern)
- Payload Resolver

### Future Extension Points
- Add JSON Patch output for programmatic consumers
- Add diff visualization HTML generation
- Add schema-aware diff (field-level semantic tracking)

---

## 12. CheckpointManager

**Module:** `scripts/acquisition_engine/checkpoint.py`  
**Class:** `CheckpointManager(checkpoint_dir)`

### Purpose
Persists execution state for the Acquisition Engine, enabling pause/resume of multi-batch ingestion runs. Each checkpoint is tamper-evident via SHA-256 checksum.

### Public API

| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| `create(session_id, mode, batches, source_ids)` | session params | `EngineCheckpoint` | New checkpoint |
| `load()` | — | `EngineCheckpoint \| None` | Load from disk |
| `get()` | — | `EngineCheckpoint \| None` | Current in-memory |
| `update_source_status(source_id, status, ...)` | status params | `None` | Per-source update |
| `set_batch_completed(batch_id)` | `batch_id` | `None` | Mark batch done |
| `set_status(status)` | `status` | `None` | Set engine status |
| `update_stats(stats)` | `dict` | `None` | Update accumulated stats |
| `resume_candidates()` | — | `list[str]` | Pending/failed sources |
| `summary()` | — | `dict` | Current state summary |

### Consumers
- `AcquisitionEngine` only (engine.py owns checkpoint lifecycle)

### Non-consumers
- All other subsystems — checkpoint is internal to the Engine

### Future Extension Points
- Add checkpoint migration (schema versioning for checkpoint files)
- Add checkpoint sharing across engines (distributed resume)

---

## 13. IntegrityManager

**Module:** `scripts/acquisition_engine/integrity.py`  
**Classes:** `ChecksumRegistry`, `VerificationLog`  
**Functions:** `file_sha256()`, `dict_sha256()`, `text_sha256()`, `compute_file_checksums()`, `verify_stage_integrity()`

### Purpose
Foundation services for data integrity: checksum computation, tamper-evident logging, and staged integrity verification. The verification log uses a hash chain to detect tampering.

### Public API

**ChecksumRegistry:**
| Method | Returns | Description |
|--------|---------|-------------|
| `create(version, file_checksums)` | `dict` | Create registry |
| `load()` | `dict \| None` | Load from disk |
| `verify()` | `{verified, mismatches, missing}` | Full verification |
| `diff_registries(before, after)` | `{changed, added, removed}` | Diff two registries |

**VerificationLog:**
| Method | Returns | Description |
|--------|---------|-------------|
| `append(event, stage, status, details)` | `dict` | Append with hash chaining |
| `verify_chain()` | `bool` | Verify entire hash chain |

**Utility Functions:**
| Function | Returns |
|----------|---------|
| `file_sha256(path)` | hex string |
| `dict_sha256(data)` | hex string |
| `text_sha256(text)` | hex string |
| `compute_file_checksums(dir, pattern)` | `dict[path → checksum]` |
| `verify_stage_integrity(stage, inputs, outputs, log)` | `{passed, checks, event}` |

### Consumers
- `AcquisitionEngine` — verification logging + checksum registry
- `KnowledgePackManager` — `file_sha256()` for pack checksums
- `KnowledgeCollectionManager` — `file_sha256()` for collection checksums
- `ReleaseManager` — `ChecksumRegistry` for release manifests
- `Self-Test Framework` — checksum verification invariants

### Non-consumers
- Quality Evaluation Engine
- AQL
- Payload Resolver

### Future Extension Points
- Add multiple hash algorithm support (BLAKE3, SHA-512)
- Add Merkle tree verification for large directories
- Add remote verification endpoint for external consumers

---

## Summary: Service Classification

| Service | Type | Dependencies | Consumers |
|---------|------|-------------|-----------|
| PayloadResolver | Lookup | File system only | Review, revision, calibration |
| QualityEvaluationEngine | Evaluation | Stdlib only | Calibration, expansion |
| LicenseGate | Policy | Stdlib only | Engine, Release, Validation (many) |
| ReleaseGate | Validation | LicenseGate, stdlib | ReleaseManager, CLI |
| ReleaseManager | Lifecycle | ReleaseGate, Integrity | CLI, self-test |
| VersionManager | Lifecycle | Stdlib, shutil | Engine |
| LifecycleManager | State Machine | Stdlib only | Engine |
| KnowledgePackManager | Packaging | Integrity (file_sha256) | Engine |
| KnowledgeCollectionManager | Organization | Integrity (file_sha256) | CLI, self-test |
| AQLEngine | Query | Stdlib only, re | CLI, self-test |
| DatasetDiff | Diff | Stdlib only | VersionManager, Release |
| CheckpointManager | Persistence | Stdlib only, hashlib | Engine only |
| IntegrityManager | Verification | Stdlib only, hashlib | Engine, Release, Pack, Collection |
