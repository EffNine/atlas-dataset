# Atlas Architecture Governance Contract

**Version:** 1.0
**Date:** 2026-07-28
**Status:** Ratified
**Supersedes:** Architecture Dependency Audit v0.2 (informal layering)

---

## 1. Purpose

This contract defines the enforceable architectural boundaries, ownership
boundaries, and policy constraints that govern the Atlas Dataset Foundation
codebase. Every module, script, and test must conform to these rules.

Violations are detected automatically by `scripts/validate_architecture.py`
and must be resolved before any non-documentation change is merged.

---

## 2. Dependency Layering

The codebase is organised into 4 numbered layers plus a test/script layer.
Dependencies must flow **downward only** — a layer may import from any lower
layer but may **never** import from a higher layer.

```
  Layer 1 — Foundation (stdlib-only, no project imports)
  Layer 2 — Validation & Lifecycle
  Layer 3 — Engine & Release
  Layer 4 — CLI & Tooling
  Layer 5 — Tests & Standalone Scripts (may import any lower layer)
```

### 2.1 Layer 1 — Foundation

**Files:** `scripts/atlas_constants.py`, `scripts/atlas_schema.py`,
`scripts/atlas_paths.py`

**Allowed imports:** Python stdlib only.

**Rules:**
- No import of any other `scripts/` module or `acquisition_engine/` module.
- No import of any `tests/` module.
- No import of any `metadata/`, `schemas/`, or `docs/` content.

**Rationale:** Layer 1 is the single source of truth for enums, schema
definitions, path resolution, and configuration. Any dependency on runtime
code would create circular import risk and violate the axiom that foundation
modules are independently importable.

### 2.2 Layer 2 — Validation & Lifecycle

**Files:** `scripts/validate_dataset.py`, `scripts/validate_knowledge_object.py`,
`scripts/acquisition_engine/lifecycle.py`, `scripts/quality_score.py`

**Allowed imports:** Python stdlib + any Layer 1 module.

**Rules:**
- May import `atlas_constants`, `atlas_schema`, `atlas_paths`.
- Must **not** import from `acquisition_engine/` (except lifecycle.py which
  *is* in Layer 2).
- Must **not** import from `atlas.py`, `payload_resolver.py`, or any CLI.
- Must **not** import from `tests/`.

**Rationale:** Validation and lifecycle logic operates on data structures
defined in Layer 1. It must remain independent of the engine and CLI layers
so it can be reused by any consumer (engine, CLI, tests, external scripts).

### 2.3 Layer 3 — Engine & Release

**Files:** All modules under `scripts/acquisition_engine/` (except lifecycle.py
which is Layer 2), `scripts/payload_resolver.py`.

**Allowed imports:** Python stdlib + any Layer 1 + any Layer 2 module.

**Rules:**
- May import `atlas_constants`, `atlas_schema`, `atlas_paths`.
- May import `validate_dataset`, `validate_knowledge_object`, `lifecycle`,
  `quality_score`.
- Must **not** import from `atlas.py` or any CLI command.
- Must **not** import from `tests/`.
- `release.py` must delegate structural validation to
  `validate_dataset.structural_errors()` (not re-implement it).

**Rationale:** Engine modules orchestrate validation, lifecycle, and quality
components from Layer 2. They form the reusable backend that the CLI layer
invokes. They must not depend on CLI presentation logic.

### 2.4 Layer 4 — CLI & Tooling

**Files:** `scripts/atlas.py`, `scripts/calibrate_quality.py`,
`scripts/clean_dataset.py`, `scripts/convert_format.py`,
`scripts/dedup_dataset.py`, `scripts/eval_dataset.py`,
`scripts/freeze_calibration_baseline.py`, `scripts/gen_calibration_sample.py`,
`scripts/ingest_dryrun.py`, `scripts/pilot_seed.py`,
`scripts/progressive_expansion.py`, `scripts/progressive_expansion_v2.py`

**Allowed imports:** Python stdlib + any lower layer (Layer 1, 2, or 3).

**Rules:**
- May import from any `scripts/` module except `tests/`.
- May import from `acquisition_engine/` modules.
- **CLI commands must not contain business logic.** Business logic must live
  in Layer 2 or Layer 3 modules. CLI commands may only parse arguments,
  call lower-layer functions, and format output.
- Must **not** import from `tests/`.

### 2.5 Layer 5 — Tests & Standalone Scripts

**Files:** All modules under `tests/`.

**Allowed imports:** Python stdlib + any module from any layer.

**Rules:**
- No restrictions on imports (tests may verify any part of the system).
- Tests must **not** modify datasets, reviews, or release artifacts.
- Standalone scripts in `tmp/` or `migrations/` follow the same rules as
  Layer 5.

### 2.6 Layer Dependency Matrix

| Module | Layer | Imports From |
|--------|-------|-------------|
| `atlas_constants.py` | 1 | stdlib only |
| `atlas_schema.py` | 1 | stdlib only |
| `atlas_paths.py` | 1 | stdlib only |
| `validate_dataset.py` | 2 | Layer 1 |
| `validate_knowledge_object.py` | 2 | Layer 1 |
| `lifecycle.py` | 2 | Layer 1 |
| `quality_score.py` | 2 | stdlib only |
| `acquisition_engine/*.py` | 3 | Layer 1, Layer 2 |
| `payload_resolver.py` | 3 | Layer 1, Layer 2 |
| `release.py` | 3 | Layer 1, Layer 2 |
| `atlas.py` | 4 | Layer 1, 2, 3 |
| Standalone `scripts/*.py` | 4 | Layer 1, 2, 3 |
| `tests/*.py` | 5 | Any |

### 2.7 Enforcement

The architecture validator (`scripts/validate_architecture.py`) will flag any
violation as a hard error (exit code 1). CI pipelines must run the validator
before merging.

---

## 3. Ownership Boundaries

Each canonical module owns a specific domain. No other module may redefine
the same concept.

### 3.1 Schema Ownership — `atlas_schema.py`

**Exclusive ownership:**
- `BASE_REQUIRED_FIELDS`, `BASE_OPTIONAL_FIELDS`, `BASE_ALLOWED_KEYS`
- `KNOWLEDGE_OBJECT_REQUIRED_FIELDS`, `LINEAGE_SUB_FIELDS`
- `SELF_TEST_REQUIRED_FIELDS`
- `SCHEMA_VERSION_BASE`, `SCHEMA_VERSION_KNOWLEDGE_OBJECT`,
  `CHAT_SCHEMA_VERSION`, `SUPPORTED_SCHEMA_VERSIONS`
- `ID_PATTERN`, `TAG_PATTERN`, `DATE_PATTERN`, `LANGUAGE_PATTERN`
- `QUALITY_SCORE_MIN`, `QUALITY_SCORE_MAX`
- `DIFFICULTY_MIN`, `DIFFICULTY_MAX`
- `MIN_MESSAGE_TURNS`
- `validate_quality_score()`, `validate_difficulty()`, `validate_messages()`,
  `validate_id()`, `field_info()`

**No other module may define these constants or functions.**

### 3.2 License & Enum Ownership — `atlas_constants.py`

**Exclusive ownership:**
- `VALID_CATEGORIES`, `VALID_TYPES`, `VALID_KNOWLEDGE_TYPES`
- `VERIFICATION_STATUSES`, `LIFECYCLE_STATES`, `VALID_ROLES`
- `VALID_TRAINING_MODELS`, `VERIFICATION_STATUS_RANK`
- `is_denied_license()`, `is_share_alike()`, `requires_attribution()`
- Internal pattern tuples (`_DENIED_LICENSE_PATTERNS`,
  `_SHARE_ALIKE_PATTERNS`, `_ATTRIBUTION_REQUIRED_PATTERNS`,
  `_ATTRIBUTION_ALWAYS_REQUIRED`)

**No other module may define these constants or functions.**

### 3.3 Path Ownership — `atlas_paths.py`

**Exclusive ownership:**
- `discover_root()`, `get_root()`
- All `*_dir()` and `*_path()` factory functions
- `APPROVED_WRITE_ROOTS`, `approved_write_paths()`, `is_write_safe()`
- `resolve_from_script()`

**No other module may construct paths by concatenating strings with project
directory names (e.g., `ROOT / "curated"`).** All project path construction
must go through `atlas_paths`.

### 3.4 Quality Ownership — `quality_score.py`

**Exclusive ownership:**
- `WEIGHTS` (dimension weights dict)
- `score_record()` (primary scoring API)
- `evaluate_record()` (detailed evaluation API with rationale)

**No other module may implement scoring logic.**

### 3.5 Release Ownership — `release.py`

**Exclusive ownership:**
- `ReleaseManager` class and all release lifecycle
- Release gates (quality, license, schema, verification, category balance)
- Semantic diff computation
- Release manifest creation and signing

**No other module may create, sign, or modify release artifacts.**
Structural validation within release gates must delegate to
`validate_dataset.structural_errors()`.

### 3.6 Lifecycle Ownership — `lifecycle.py`

**Exclusive ownership:**
- `LifecycleManager` class and all lifecycle state transitions
- Lifecycle state constants (sourced from `atlas_constants.LIFECYCLE_STATES`)

**No other module may implement lifecycle state transitions.**

---

## 4. Cross-Cutting Rules

### 4.1 No Business Logic in CLI

CLI commands (`atlas.py` and standalone scripts at Layer 4) must not contain
business logic beyond argument parsing, calling lower-layer functions, and
formatting output.

**Allowed in CLI:**
- Argument parsing (`argparse`, `sys.argv`)
- Function calls to Layer 2/3 modules
- Print/format output
- Simple conditionals for help text, usage messages

**Forbidden in CLI:**
- Schema validation logic
- License checking logic
- Scoring logic
- Dataset transformation logic
- Path construction using string concatenation (must use `atlas_paths`)

### 4.2 No Validation Duplication in Release

`release.py` must delegate all structural record validation to
`validate_dataset.structural_errors()`. It may layer release-specific checks
on top (category balance, license gate, verification gate) but must not
re-implement field-level validation.

### 4.3 No Duplicate Schema Definitions

The field sets defined in `atlas_schema.py` must be the **only** source of
truth. No module may define its own `REQUIRED_FIELDS`, `ALLOWED_KEYS`, or
field-pattern constants.

### 4.4 No Duplicate License Functions

`is_denied_license()`, `is_share_alike()`, and `requires_attribution()` are
owned by `atlas_constants.py`. No other module may redefine them.

### 4.5 Direct Filesystem Path Construction

No module (except `atlas_paths.py`) may construct filesystem paths by
concatenating directory names like `"curated"`, `"metadata"`, `"raw"`,
`"review_queue"`, `"training_views"`, `"schemas"`, `"docs"`, or `"tmp"`
with a root path.

Every consumer must use `atlas_paths.*_dir()` or `atlas_paths.*_path()`
functions.

---

## 5. Style and Structure Rules

### 5.1 Module Header

Every Python module must begin with:
```python
#!/usr/bin/env python3
"""
module_name.py — One-line description.

Extended description (2-5 lines) covering purpose and primary API.
"""
```

### 5.2 Import Order

1. Python stdlib (alphabetical)
2. Third-party (if any)
3. Layer 1 project imports (alphabetical)
4. Layer 2 project imports (alphabetical)
5. Layer 3+ project imports (alphabetical)

Each group separated by a blank line.

### 5.3 Naming Conventions

- **Public API constants:** `UPPER_CASE`
- **Private/internal constants:** `_leading_underscore`
- **Functions:** `snake_case`
- **Classes:** `PascalCase`
- **Files:** `snake_case.py`

---

## 6. Exception Process

Any change that would violate this governance contract must follow:

1. File an ADR (Architecture Decision Record) in `docs/adr/`
2. Describe the violation, rationale, and mitigating controls
3. Obtain explicit maintainer approval
4. Update the governance contract and architecture validator
5. Implement the change

Temporary violations during refactoring are permitted only if:
- A tracking issue is filed
- The violation is resolved within the same PR
- The validator is updated to allow the transient exception

---

## 7. Contract Versioning

| Version | Date | Change |
|---------|------|--------|
| 1.0 | 2026-07-28 | Initial governance contract — ratified after Phase 4C.2 hardening |
