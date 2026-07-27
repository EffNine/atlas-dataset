# Atlas Subsystem Contract Extraction

Repository root: `/Users/afnanrudy/Github-Projects/ai-datasets/atlas-dataset`

## 1. Self-Test Invariant Names

**Source:** `scripts/atlas.py` (`cmd_self_test`, `_run_release_self_tests`)

- `no-network-access`
- `no-unauthorized-writes`
- `approved-write-allowed`
- `license-gate-integrity`
- `manifest-validation`
- `canonical-schema-validation`
- `deterministic-planning`
- `knowledge-object-integrity`
- `training-view-safety`
- `aql-parse:<query[:30]>`
- `aql-reject:<query[:20]>`
- `aql-describe`
- `aql-execute`
- `release-gate-quality`
- `release-manager-structure`
- `release-dir-exists`
- `collection-manager-structure`
- `release-chain-empty`
- `release-summary`
- `collection-list-empty`
- `semantic-diff-structure`

Sample invariant payloads:
- Manifest check: `total_target_examples == 1000`, `batches == 9`, `global_constraints` present.
- Knowledge-object integrity: required fields after migrations = `id, category, subcategory, difficulty, knowledge_type, canonical_answer, metadata, source_attribution, license, tags, quality_score, verification_status, lineage, training_view_eligibility, messages`.
- Training-view safety: `training_view_eligibility` keys must be exactly `{qwen, llama, deepseek}`.
- AQL acceptance tests for tag-style, SQL-style, compact forms; reject empty query and nonexistent fields.

---

## 2. License Subsystem

**Sources:** `scripts/validate_dataset.py`, `scripts/atlas.py`, `scripts/acquisition_engine/release.py`

### Denied License Patterns
- `cc-by-nc*`
- `cc-by-nd*`
- `proprietary`
- `all-rights-reserved`
- `unknown`

### Allowed License Examples (from self-test)
- `mit`
- `Apache-2.0`
- `CC-BY-4.0`
- `ODC-BY`
- `CC-BY-SA-4.0`
- `BigCode Open RAIL-M`
- `Public Domain`
- `arXiv non-exclusive license`

### License Gate Behavior
- Single gate source: `scripts/validate_dataset.py:is_denied_license`.
- Gate is substring-insensitive after lowercasing.
- Curated-stage restriction: `license` must not be `unknown`.
- `RAIL-M` / `CC-BY-SA` allowed but carry attribution + subsetting obligations handled in runbook/metadata.

---

## 3. Quality Scoring Subsystem

**Source:** `scripts/quality_score.py`

### Quality Contract
- Output score: `int` in `[0..10]`.
- Primary API: `score_record(rec) -> (int quality_score, dict[dimension]->float)`.
- Rich API: `evaluate_record(rec) -> dict` with keys:
  - `quality_score`: int `1..10`
  - `quality_continuous`: float `0..1`
  - `dimensions`: dict of dimension name to `0..1`
  - `confidence`: float `0..1`
  - `confidence_level`: int `1..5`
  - `rationale`: list of `{dimension, score, reason}`
  - `flags`: list[str]
  - `explanation`: str

### Quality Dimensions & Weights
- `accuracy`: 0.20
- `completeness`: 0.15
- `technical_correctness`: 0.20
- `clarity`: 0.15
- `usefulness`: 0.15
- `originality`: 0.05
- `relevance`: 0.10

### Quality Validation Rules
- `quality_score` must be `int`, range `0..10` (`schemas/dataset_schema.json`).
- Release gate default threshold: `min_score == 7` (`ReleaseGates.check_quality_gate`).
- Schema-gate rejects `quality_score` < 0 or > 10.
- `validate_knowledge_object.py --strict` enforces `verified==True AND quality_score >= 8.5` as curated gate in strict mode.
- `metadata/quality_review_schema.json` dimension names mirror `WEIGHTS` keys exactly.

---

## 4. Schema Subsystem

**Sources:** `schemas/dataset_schema.json`, `schemas/knowledge_object_schema.json`, `schemas/chat_schema.json`, `scripts/validate_dataset.py`, `scripts/validate_knowledge_object.py`

### Base Dataset Record Fields (`dataset_schema.json`)
Required:
- `id`: string, `^[a-z0-9_-]+$`, length 3..128
- `category`: enum of 9 categories
- `subcategory`: string, length 1..64
- `type`: enum `instruction | conversation | qa | reasoning`
- `source`: object with `name`, `license`, optional `url`, optional `date` (`YYYY-MM-DD`)
- `messages`: array with `minItems: 2`, each ref `chat_schema.json#/$defs/message`, must contain at least user + assistant
- `tags`: array of strings matching `^[a-z0-9][a-z0-9_-]*$`, maxItems 20
- `quality_score`: int `[0..10]`
- `verified`: bool
- `notes`: string, maxLength 2000

Optional:
- `language`: string matching `^[a-z]{2}(-[A-Z]{2})?$`, default `"en"`
- `difficulty`: int `[0..3]`, default `0`

### Canonical Knowledge Object Superset Fields (`knowledge_object_schema.json`)
All base required fields plus:
- `difficulty`: int `[0..3]`
- `knowledge_type`: enum `fact | procedure | concept | reasoning | code | reference | creative`
- `canonical_answer`: string
- `metadata`: object; known properties = `language`, `synthetic`, `model_generated`, `source_confidence`
- `source_attribution`: object; required = `source_id`, `name`, `url`, `license`, `attribution_text`, optional `access_date`, `share_alike`
- `license`: string, minLength 1, maxLength 64
- `verification_status`: enum `pending | approved | rejected | needs_revision`
- `lineage`: object; required = `source`, `transformations`, `knowledge_object`, `curated_dataset`, `training_view`, `future_model`
- `training_view_eligibility`: object; required keys = `qwen`, `llama`, `deepseek`, all bool
- `verified`: bool

### Chat Turn Contract (`chat_schema.json`)
- `role`: enum `system | user | assistant | tool`
- `content`: string, minLength 1, maxLength 64000

### Controlled Vocabularies
- Categories: `01_foundation`, `02_software_engineering`, `03_system_engineering`, `04_ai_machine_learning`, `05_hardware_engineering`, `06_science_engineering`, `07_business_knowledge`, `08_creative_knowledge`, `09_personal_assistant`
- Subcategories defined per category in `metadata/categories.json`.
- Knowledge types: `fact`, `procedure`, `concept`, `reasoning`, `code`, `reference`, `creative`
- Verification statuses: `pending`, `approved`, `rejected`, `needs_revision`
- Record types: `instruction`, `conversation`, `qa`, `reasoning`
- Message roles: `system`, `user`, `assistant`, `tool`

### Structural Validator Constraints (`scripts/validate_dataset.py` / `validate_knowledge_object.py`)
- `id` matches `^[a-z0-9_-]+$`
- `subcategory` must be non-empty; recommended to align with `metadata/categories.json`.
- `source.license` must be non-empty and not denied; `source.date` optional ISO-8601 (`YYYY-MM-DD`).
- `messages` list must be >= 2 with at least one user + one assistant; no empty content.
- `tags` must be non-empty list of strings matching `^[a-z0-9][a-z0-9_-]*$`.
- `verified` must be bool; strict mode requires `verified == True`.
- `verified` must equal `(verification_status == "approved")`.
- `share_alike=True` implies license starts with `cc-by-sa`.

---

## 5. Lifecycle Subsystem

**Source:** `scripts/acquisition_engine/lifecycle.py`

### Lifecycle States (ordered)
1. `raw`
2. `processing`
3. `curated`
4. `review`
5. `approved`
6. `released`
7. `archived`
8. `rejected`

### Valid Transitions
- `raw` -> `processing`, `rejected`
- `processing` -> `curated`, `rejected`, `raw`
- `curated` -> `review`, `processing`, `rejected`
- `review` -> `approved`, `rejected`, `needs_revision`
- `needs_revision` -> `review`, `rejected`, `curated`
- `approved` -> `released`, `review`
- `released` -> `archived`
- `archived` -> []
- `rejected` -> `raw`

### Lifecycle Registry Schema (`metadata/lifecycle_state.json`)
```json
{
  "generated": "<ISO timestamp>",
  "record_count": <int>,
  "records": {
    "<record_id>": {
      "state": "<one of LIFECYCLE_STATES>",
      "history": [
        {
          "from": "<state>",
          "to": "<state>",
          "timestamp": "<ISO timestamp>",
          "source": "engine|human|auto",
          "reason": "<str>"
        }
      ],
      "created_at": "<ISO timestamp>",
      "updated_at": "<ISO timestamp>"
    }
  }
}
```

### Entrypoint Contract
- `LifecycleTracker(metadata_dir)` reads/writes `metadata/lifecycle_state.json`.
- `transition(record_id, to_state, source, reason)` returns transition dict or raises `ValueError`.
- `batch_transition(record_ids, to_state, source, reason)` returns `{record_id: [transitions]}`, raises on first error.
- `state_summary()` returns dict of state -> count.

---

## 6. AQL (Atlas Query Language) Subsystem

**Source:** `scripts/acquisition_engine/aql.py`

### Supported Syntax Variants
1. **Tag-style:** `category:01_foundation quality_score>=7 license:mit`
2. **SQL-style:** `SELECT * WHERE category = "01_foundation" AND quality_score >= 7`
3. **Compact:** `category=01_foundation quality>=7`

### Field Aliases
- `cat` -> `category`
- `subcat` -> `subcategory`
- `q` / `quality` -> `quality_score`
- `lic` -> `license`
- `ver` / `status` -> `verification_status`
- `type` -> `knowledge_type`
- `lang` -> `language`
- `diff` -> `difficulty`
- `source` -> `source_id`

### Valid Field Names for Filtering
`category, subcategory, license, quality_score, verification_status, verified, difficulty, knowledge_type, language, source_id, type, tags, id`

### Operators
- Equality shorthand: `field:value`
- Comparison: `=`, `!=`, `>`, `>=`, `<`, `<=`
- Membership: `in (val1, val2, ...)`
- Existence: bare field name -> `exists` operator
- Boolean parsing: `true/yes` -> True, `false/no` -> False

### SQL-Style Grammar
```sql
SELECT [fields|*]
[WHERE condition (AND condition)*]
[GROUP BY field]
[ORDER BY field [ASC|DESC]]
[LIMIT N]
[OFFSET N]
```

### AQL Aggregations
Supported functions:
- `COUNT(*)`
- `MIN(field)`
- `MAX(field)`
- `AVG(field)`
- `SUM(field)`

### AQL Execution Result Contract
```json
{
  "records": [...],
  "count": <int>,
  "total_available": <int>,
  "query": {
    "select_fields": [...],
    "conditions": [...],
    "group_by": "...",
    "order_by": ["field", "ASC|DESC"],
    "limit": <int>,
    "offset": <int>,
    "aggregations": [["func", "field"], ...]
  },
  "query_raw": "<original query>",
  "groups": {"<group_key>": <count>, ...},
  "aggregations": {"count(*)": ..., "avg(field)": ..., ...}
}
```

### Validate Query Contract
```json
{ "valid": true }
// or
{ "valid": false, "errors": ["..."] }
```

---

## 7. Release Mangement Subsystem

**Source:** `scripts/acquisition_engine/release.py`

### Release Manager Entrypoints
- `ReleaseManager(dataset_root)`
- `list_releases()` -> list of release index entries
- `get_latest_release()`
- `get_release(version)`
- `release_exists(version)`
- `load_release_manifest(version)`
- `create_release(version, source_paths, changelog, records, manifest_data, checksums_registry, actual_checksums, force)`
- `verify_release(version)`
- `verify_release_chain()`
- `release_summary()`

### Release Version Format
- Regex: `^v(\d+)\.(\d+)(?:\.(\d+))?$`
- Examples: `v0.1`, `v0.2`, `v1.0.0`

### Release Manifest Structure (`metadata/releases/<version>_release.json`)
```json
{
  "release_version": "v0.1",
  "release_type": "major | minor | patch",
  "created_at": "<ISO timestamp>",
  "changelog": "<str>",
  "from_version": "<previous version or null>",
  "total_records": <int>,
  "statistics": {
    "by_category": {...},
    "by_license": {...},
    "by_verification_status": {...},
    "quality": {"avg": <float>, "min": <int>, "max": <int>}
  },
  "gate_results": [{"gate", "status", "message", "details"}],
  "gates_passed": <bool>,
  "diff_from_previous": {...},
  "breaking_changes": [...],
  "has_breaking_changes": <bool>,
  "checksum_registry": {
    "version": "...",
    "algorithm": "sha256",
    "total_files": <int>,
    "registry_path": "..."
  },
  "status": "created",
  "release_signature": {
    "content_hash": "<sha256>",
    "previous_release_hash": "<sha256>",
    "chain_hash": "<sha256>",
    "signature_algorithm": "sha256-chain-v1"
  },
  "release_id": "<first 16 chars of chain_hash>"
}
```

### Release Index Structure (`metadata/release_index.json`)
```json
{
  "releases": [
    {
      "version": "v0.1",
      "release_type": "minor",
      "created_at": "<ISO timestamp>",
      "total_records": <int>,
      "chain_hash": "<sha256>",
      "content_hash": "<sha256>",
      "previous_hash": "<sha256>",
      "gates_passed": <bool>,
      "release_id": "<str>"
    }
  ],
  "genesis_hash": "<sha256>"
}
```

### Release Gates (all must pass unless force=True)
1. `quality_gate`: 100% records have `quality_score >= 7` (default)
2. `license_gate`: no denied licenses
3. `schema_gate`: all records pass structural/knowledge-object validation
4. `verification_gate`: file checksums match registry
5. `category_balance_gate`: each category within ±5% of target
6. `no_unknown_license_gate`: license != "unknown"
7. `no_rejected_source_gate`: no records from `status=rejected` registry sources

### SemanticDiff Breaking Change Types
- `schema_field_removed`
- `category_removed`
- `license_policy_change`
- `verification_status_regression`
- `quality_score_degradation`
- `knowledge_type_removed`

### SemanticDiff Output Contract
```json
{
  "summary": {
    "from_total": <int>, "to_total": <int>,
    "added": <int>, "removed": <int>, "changed": <int>, "unchanged": <int>,
    "net_change": <int>, "churn": <int>, "stability_score": <float>
  },
  "breaking_changes": [...],
  "has_breaking_changes": <bool>,
  "changed_records": [...],
  "field_change_counts": {"field": count, ...},
  "added_ids": [...], "removed_ids": [...],
  "generated": "<ISO timestamp>"
}
```

---

## 8. Knowledge Pack Subsystem

**Source:** `scripts/acquisition_engine/knowledge_pack.py`

### Pack Manifest Contract (`knowledge_packs/<name>_manifest.json`)
```json
{
  "pack_name": "<name>",
  "pack_version": "1.0",
  "generated": "<ISO timestamp>",
  "description": "<str>",
  "total_records": <int>,
  "filter_criteria": {
    "categories": ["<category>", ...],
    "min_quality": <int>
  },
  "statistics": {
    "by_category": {...},
    "by_license": {...},
    "avg_quality": <float>,
    "quality_min": <int>,
    "quality_max": <int>
  },
  "files": {
    "<name>.jsonl.gz": "<sha256>"
  },
  "metadata": {...}
}
```

### Pack Checksum Contract (`knowledge_packs/<name>_checksums.json`)
```json
{
  "pack_name": "<name>",
  "algorithm": "sha256",
  "checksums": {
    "<filename>": "<sha256>",
    "manifest": "<sha256>"
  }
}
```

### Verification Contract
```json
{
  "verified": <bool>,
  "packs": [
    {
      "manifest": "<name_manifest.json>",
      "pack_name": "<name>",
      "verified": <bool>,
      "record_count": <int>,
      "errors": ["..."]
    }
  ]
}
```

---

## 9. Knowledge Collection Subsystem

**Source:** `scripts/acquisition_engine/knowledge_collection.py`

### Collection Contract
- Collections live under `knowledge_packs/collections/<name>/`.
- Collection manifest path: `knowledge_packs/collections/<name>/<name>_collection.json`.
- Collection index: `metadata/collection_index.json`.

### Collection Manifest Contract
```json
{
  "collection_name": "<name>",
  "collection_version": "1.0",
  "generated": "<ISO timestamp>",
  "description": "<str>",
  "total_packs": <int>,
  "total_records": <int>,
  "pack_names": ["<pack_name>", ...],
  "packs": [
    {
      "pack_name": "<name>",
      "manifest": "<path>",
      "total_records": <int>
    }
  ],
  "statistics": {
    "by_category": {...},
    "by_license": {...},
    "avg_quality": <float>
  },
  "collection_checksum": "<sha256>",
  "metadata": {...}
}
```

### Collection Index Contract (`metadata/collection_index.json`)
```json
{
  "collections": [
    {
      "name": "<name>",
      "description": "<str>",
      "total_packs": <int>,
      "total_records": <int>,
      "generated": "<ISO timestamp>",
      "collection_checksum": "<sha256>"
    }
  ],
  "generated": "<ISO timestamp>"
}
```

### Collection Verification Contract
```json
{
  "verified": <bool>,
  "collection_name": "<name>",
  "total_packs": <int>,
  "total_records": <int>,
  "checksum_match": <bool>,
  "errors": ["..."]
}
```

---

## 10. Migration Subsystem

**Source:** `migrations/runner.py`, `migrations/001_initial_schema.py`, `migrations/002_add_lineage.py`, `migrations/003_add_training_views.py`

### Migration Module Contract
Each migration file exposes:
- `MIGRATION_ID`: string, e.g. `"001_initial_schema"`
- `DEPENDS_ON`: list[str], e.g. `["001_initial_schema"]`
- `IDEMPOTENT`: bool, default `True`
- `up(record: dict) -> dict`: idempotent transform; must NOT delete fields.

### Known Migrations
1. `001_initial_schema`: Adds superset fields when missing; idempotent.
2. `002_add_lineage`: Normalizes `lineage` object; depends on `001_initial_schema`.
3. `003_add_training_views`: Adds `training_view_eligibility`; depends on `001_initial_schema`, `002_add_lineage`.

### Lineage Object Contract
```json
{
  "source": "<origin>",
  "transformations": ["pipeline_step", "migrate:MIGRATION_ID", ...],
  "knowledge_object": "<record_id>",
  "curated_dataset": "curated/v0.1",
  "training_view": "<comma-separated eligible views>",
  "future_model": "<model class description>"
}
```

### Applied State (`migrations/applied.json`)
```json
{
  "applied": ["001_initial_schema", "002_add_lineage", ...],
  "applied_by": "<str>"
}
```

---

## 11. Versioning Subsystem

**Source:** `scripts/acquisition_engine/versioning.py`

### Version Manager Entrypoints
- `VersionManager(dataset_root)`
- `list_versions()` -> list of `{version, frozen_at, total_records}`
- `current_version()` -> latest `vN.N[.N]` or None
- `get_version_manifest(version)`
- `freeze(version, source_paths, stats, changelog)`
- `diff(from_version, to_version)`
- `rollback(to_version)`

### Version Manifest Contract (`curated/<version>/version_manifest.json`)
```json
{
  "version": "v0.1",
  "frozen_at": "<ISO timestamp>",
  "total_records": <int>,
  "source_files": ["<filename>", ...],
  "statistics": {
    "by_category": {...},
    "by_license": {...},
    "by_verification_status": {...},
    "quality": {
      "avg": <float>,
      "min": <int>,
      "max": <int>,
      "scores": [<sorted subset>, "...", <sorted subset>]
    }
  },
  "pipeline_stats": {...},
  "changelog": "<str>"
}
```

### Version Diff Contract
```json
{
  "from_version": "v0.1", "to_version": "v0.2",
  "from_records": <int>, "to_records": <int>,
  "added": <int>, "removed": <int>, "changed": <int>,
  "added_ids": [...], "removed_ids": [...], "changed_ids": [...],
  "note": "..."
}
```

---

## 12. Integrity Subsystem

**Source:** `scripts/acquisition_engine/integrity.py`

### Checksum Registry Contract (`metadata/engine_checksums.json`)
```json
{
  "version": "v0.1",
  "generated": "<ISO timestamp>",
  "algorithm": "sha256",
  "files": {
    "<relative_path>": "<sha256>"
  },
  "summary": {"total_files": <int>, "total_checksums": <int>},
  "checksum": "<sha256-of-all-above-fields>"
}
```

### Verification Log Contract (`metadata/verification_log.json`)
```json
{
  "genesis_hash": "<sha256>",
  "log_version": "1.0",
  "entries": [
    {
      "timestamp": "<ISO timestamp>",
      "event": "stage_verification | dry_run_complete | ...",
      "stage": "<str>",
      "status": "passed | failed",
      "previous_hash": "<sha256>",
      "details": {...},
      "hash": "<sha256>"
    }
  ]
}
```

### Stage Verification Contract
```json
{
  "passed": <bool>,
  "checks": {
    "input_exists:<filename>": <bool>,
    "output_valid:<filename>": <bool>
  },
  "event": {
    "timestamp": "...", "event": "stage_verification", "stage": "...",
    "status": "...", "previous_hash": "...", "details": {...}, "hash": "..."
  }
}
```

---

## 13. Checkpoint Subsystem

**Source:** `scripts/acquisition_engine/checkpoint.py`

### Checkpoint Data Classes
- `SourceCheckpoint`: `source_id`, `status` (`pending|resolving|downloading|pipelining|validating|completed|failed|skipped`), `batch_id`, `records_processed`, `records_accepted`, `records_rejected`, `error`, `started_at`, `completed_at`
- `EngineCheckpoint`: `session_id`, `engine_version` (`"0.1.0"`), `mode` (`"dry-run"|"execute"`), `started_at`, `updated_at`, `status` (`"created"|"running"|"paused"|"completed"|"failed"`), `current_batch`, `completed_batches`, `sources`, `stats`, `checksum`

### Checkpoint File Contract (`metadata/engine_checkpoint.json`)
```json
{
  "session_id": "...",
  "engine_version": "0.1.0",
  "mode": "dry-run",
  "started_at": "<ISO timestamp>",
  "updated_at": "<ISO timestamp>",
  "status": "running",
  "current_batch": "<batch_id or null>",
  "completed_batches": ["<batch_id>", ...],
  "sources": {
    "<source_id>": {
      "source_id": "...", "status": "...", "batch_id": "...",
      "records_processed": <int>, "records_accepted": <int>,
      "records_rejected": <int>, "error": null,
      "started_at": "...", "completed_at": "..."
    }
  },
  "stats": {...},
  "checksum": "<sha256>"
}
```

---

## 14. Acquisition Manifest Subsystem

**Source:** `metadata/acquisition_manifest_v0.1.json`

### Manifest Top-Level Fields
- `manifest_version`: `"0.1.0"`
- `atlas_target_version`: `"v0.1"`
- `generated`: `<date>`
- `status`: `<str>`
- `policy_ref`: `"docs/source_policy.md"`
- `registry_ref`: `"metadata/source_registry.json"`
- `total_target_examples`: `1000`
- `global_constraints`: {...}
- `category_targets`: map of category -> target count
- `success_criteria`: list[str]
- `evaluation_plan`: {...}
- `batches`: list of batch objects

### Batch Object Contract
```json
{
  "batch_id": "B01",
  "order": <int>,
  "theme": "<str>",
  "priority": "tier-2",
  "datasets": [
    {
      "source_id": "f1",
      "name": "...",
      "url": "...",
      "license": "...",
      "license_class": "permissive | share-alike | use-restricted",
      "license_constraints": ["...", ...],
      "category": "...",
      "subcategories": ["...", ...],
      "target_examples": <int>,
      "extraction_method": "...",
      "synthetic": <bool>,
      "attribution_required": <bool>,
      "attribution_note": "...",
      "quality_gate": {"min_quality_score": 7},
      "preprocess": ["clean", "dedup", "score", "human_review", ...],
      "notes": "..."
    }
  ]
}
```

---

## 15. Source Registry Subsystem

**Source:** `metadata/source_registry.json`

### Source Object Contract
```json
{
  "id": "f1",
  "name": "...",
  "source": "...",
  "url": "...",
  "category": "...",
  "subcategory_hint": "...",
  "tier": "Tier 1",
  "license": "...",
  "format": "...",
  "size": "...",
  "status": "candidate | accepted | review | rejected",
  "quality_score": <int 1-10>,
  "scores": {
    "accuracy": <int>, "technical": <int>, "diversity": <int>,
    "cleanliness": <int>, "license_clarity": <int>
  },
  "recommendation": "accept | review | reject",
  "notes": "..."
}
```

---

## 16. Engine-Level Contracts

**Source:** `scripts/acquisition_engine/engine.py`

### Execution State Machine
`DRY_RUN -> PLANNING -> RESOLVING -> PIPELINING -> VALIDATING -> REVIEWING -> RELEASING`

### Engine Constraints
- Zero network access during any command (`install_network_block()`).
- Approved write roots: `curated`, `review_queue`, `training_views`, `metadata`, `docs`, `tmp`, `raw/pilot`, `migrations`, `knowledge_packs`.
- Reuses `scripts/validate_dataset.py:is_denied_license` as the single license gate.

### Engine Checkpoints
- `size_ref` table maps `source_id` -> `(estimated_bytes, basis)`.

---

## 17. Categories Taxonomy

**Source:** `metadata/categories.json`

| Category ID | Title | Subcategories |
|---|---|---|
| `01_foundation` | Foundation Skills | general-reasoning, instruction-following, communication, problem-solving |
| `02_software_engineering` | Software Engineering | programming, algorithms, software-architecture, debugging, code-review, open-source |
| `03_system_engineering` | System Engineering | linux, windows, networking, docker, kubernetes, virtualization, performance-tuning |
| `04_ai_machine_learning` | AI & Machine Learning | machine-learning, deep-learning, transformers, llm, rag, ai-agents, mlops, prompt-engineering |
| `05_hardware_engineering` | Hardware Engineering | cpu, gpu, embedded-systems, firmware, bios, validation, benchmarking |
| `06_science_engineering` | Science & Engineering | mathematics, physics, electronics, engineering-concepts |
| `07_business_knowledge` | Business Knowledge | finance, management, strategy, entrepreneurship |
| `08_creative_knowledge` | Creative Knowledge | writing, storytelling, design, creativity |
| `09_personal_assistant` | Personal Assistant | planning, productivity, decision-making, workflow-optimization |

---

## 18. Pilot / Pipeline Write Contracts

**Source:** `scripts/atlas.py`, `scripts/acquisition_engine/engine.py`

### ingest-pilot Outputs
- `curated/v0.1/pilot_candidates.jsonl`: Knowledge Objects with full superset schema.
- `review_queue/<status>.jsonl`: Sharded by verification_status.
- `training_views/{qwen,llama,deepseek}/README.md`: Placeholder only.
- `metadata/pilot_manifest.json`: Pilot stats.
- `docs/phase3a_pilot_report.md`: Optional report.

### Review Queue Entry Contract
```json
{
  "id": "<record_id>",
  "category": "<category>",
  "subcategory": "<subcategory>",
  "quality_score": <int>,
  "license": "<license>",
  "verification_status": "<pending | approved | rejected | needs_revision>"
}
```
