# Subsystem Refactor Audit

> Phase 4C.0 — Architecture Consolidation & Dependency Unification
> Generated: 2026-07-28

This audit detects duplicate implementations across Atlas subsystems for 7 critical functions. Each finding lists the duplicated sites and recommends whether to replace with canonical services.

---

## 1. Payload Lookup

### Canonical Service
**`scripts/payload_resolver.py`** — `PayloadResolver(dataset_root)` with priority-chain lookup

### Duplicated Implementations

#### 🚩 Finding D-1: Inline record search in `atlas.py` `cmd_ingest_pilot()`
- **File:** `scripts/atlas.py` lines 417–489
- **Code:** Manually opens `raw/pilot/seed.jsonl`, iterates lines, parses JSON, and filters
- **Risk:** Low — this reads from a specific known path, not an ID-based lookup
- **Recommendation:** No change. The pilot ingestion reads raw input, not looking up existing records.

#### 🚩 Finding D-2: Inline record loading in `scripts/progressive_expansion.py` lines 50–80
- **File:** `scripts/progressive_expansion.py`
- **Code:** `load_pilot_manifest()` and direct file reads for existing records
- **Risk:** Medium — duplicates PayloadResolver's priority-chain logic for reading existing curated data
- **Recommendation:** Refactor to use `PayloadResolver.resolve_many()` when performing ID-based lookups. Accept as-is for file-level bulk reads.

#### 🚩 Finding D-3: Inline record loading in `scripts/acquisition_engine/engine.py`
- **File:** `scripts/acquisition_engine/engine.py` lines 490–500+
- **Code:** Direct file iteration over curated files
- **Risk:** Medium — the engine reads curated files directly rather than using PayloadResolver
- **Recommendation:** The Engine operates on record sets (not single record lookups), so the bulk pattern is acceptable. No change needed.

### Verdict
**No urgent payload lookup duplication.** The PayloadResolver is the canonical single-record lookup service. Bulk record loading is intentionally handled at the Engine/Expansion level because PayloadResolver is optimized for single-ID resolution, not streaming reads.

---

## 2. License Validation

### Canonical Service
**`scripts/validate_dataset.py:is_denied_license(lic)`** — single function, `_DENIED_LICENSE_PATTERNS` tuple

### Duplicated Implementations

#### 🚩 Finding L-1: Inline license check in `atlas.py` `cmd_ingest_pilot()` (line 441)
- **Code:** `if is_denied_license(lic):` ← **CORRECTLY USES CANONICAL SERVICE**
- **Status:** Reuses `is_denied_license` via `importlib`. ✅

#### 🚩 Finding L-2: Lazy import in `release.py` via `_denied_license_gate()` (lines 33–40)
- **Code:** `_denied_license_gate()` → `import _v_mod.is_denied_license`
- **Status:** Correctly imports canonical service. ✅

#### 🚩 Finding L-3: Inline license check in `engine.py` (line 66)
- **Code:** `is_denied_license = _v_mod.is_denied_license` — same import pattern
- **Status:** Correctly imports canonical service. ✅

#### 🚩 Finding L-4: Inline license check in `progressive_expansion.py` line ~150
- **Code:** Imports and calls `is_denied_license`
- **Status:** Correctly reuses canonical service. ✅

#### 🚩 Finding L-5: Duplicate `share_alike` detection logic
- **Files:**
  - `scripts/atlas.py` line 447: `sa["share_alike"] = "sa" in lic.lower()`
  - `scripts/progressive_expansion_v2.py`: similar inline check
  - `ATLAS_SUBSYSTEM_CONTRACTS.md` line 158: mentions `share_alike=True` implies license starts with `cc-by-sa`
- **Issue:** Share-alike detection is duplicated inline across at least 2 modules
- **Recommendation:** Add a canonical `is_share_alike(lic: str) -> bool` function to `validate_dataset.py` alongside `is_denied_license`

### Verdict
**License validation is well-unified** around the canonical `is_denied_license()` service. The only minor gap is the missing `is_share_alike()` canonicalization.

---

## 3. Checksum Generation

### Canonical Service
**`scripts/acquisition_engine/integrity.py`** — `file_sha256()`, `dict_sha256()`, `text_sha256()`, `compute_file_checksums()`

### Duplicated Implementations

#### 🚩 Finding C-1: Inline SHA-256 in `payload_resolver.py` (line 64–66)
- **Code:** `_compute_checksum(payload)` — standalone function with identical `json.dumps(sort_keys=True).encode()` + `hashlib.sha256`
- **File:** `scripts/payload_resolver.py`
- **Severity:** Low — this is a lightweight helper, not a full checksum registry
- **Recommendation:** **Replace with `integrity.dict_sha256()`**. This is a safe refactor — PayloadResolver already has `hashlib` imported.

#### 🚩 Finding C-2: Inline SHA-256 in `checkpoint.py` (line 87–89)
- **Code:** `_compute_checksum(data)` — same pattern, `json.dumps(sort_keys=True)` + `hashlib.sha256`
- **File:** `scripts/acquisition_engine/checkpoint.py`
- **Severity:** Medium — duplicates `integrity.dict_sha256()` exactly
- **Recommendation:** **Replace with `integrity.dict_sha256(data)`**. CheckpointManager already has `hashlib` imported — remove the duplication.

#### 🚩 Finding C-3: Inline file content hash in `scripts/progressive_expansion.py`
- **Code:** Direct `hashlib.sha1()` usage for dedup (line ~458 in atlas.py has same SHA-1 pattern)
- **Severity:** Low — SHA-1 is used for dedup signatures, not integrity verification. Different purpose from SHA-256 checksums.

#### 🚩 Finding C-4: Checksum computation in `engine.py` (line ~560 area)
- **Code:** Computes file checksums using `file_sha256()` from integrity module
- **Status:** Correctly uses canonical service. ✅

### Verdict
**Two small replacements recommended.** PayloadResolver and CheckpointManager each define their own `_compute_checksum()` that duplicates `integrity.dict_sha256()`. These are straightforward find-and-replace changes.

---

## 4. Quality Scoring

### Canonical Service
**`scripts/quality_score.py`** — `score_record(rec)`, `evaluate_record(rec)`, `WEIGHTS`

### Duplicated Implementations

#### 🚩 Finding Q-1: Inline quality logic in `atlas.py` `cmd_ingest_pilot()` (lines 466–472)
- **Code:** `q = int(rec.get("quality_score", 0)); q = max(0, min(10, q))` — a clamp, not full scoring
- **Risk:** Low — this clamps an existing score field, it doesn't compute a new score
- **Recommendation:** No change. The pilot ingestion preserves authored quality scores, not recomputing them.

#### 🚩 Finding Q-2: Inline quality threshold in `release.py` `check_quality_gate()`
- **Code:** Implements the quality gate min_score check
- **Status:** This IS the gate logic, not a quality score computation. Different concern. ✅

#### 🚩 Finding Q-3: Inline quality evaluation in `scripts/progressive_expansion.py`
- **Code:** Calls `quality_score.evaluate_record()` for new records
- **Status:** Correctly uses canonical QEE service. ✅

#### 🚩 Finding Q-4: Calibration engine in `scripts/calibrate_quality.py`
- **Code:** `from quality_score import score_record, WEIGHTS`
- **Status:** Correctly imports canonical QEE. ✅

### Verdict
**Quality scoring is well-unified.** No duplicated scoring logic exists. Every module that needs quality scores either reads the stored field or calls the canonical QEE.

---

## 5. Record Loading (JSONL parsing)

### Canonical Service
**`scripts/acquisition_engine/dataset_diff.py:load_records_index(file_paths)`** — loads JSONL files into `{id: record}` dict

### Duplicated Implementations

#### 🚩 Finding R-1: Inline `_load_records()` in `release.py` (lines 43–57)
- **Code:** `_load_records(file_paths)` — iterates JSONL files, parses lines, skips non-existent files and JSON errors
- **Severity:** Medium — functionally identical to `dataset_diff.load_records_index()` but returns a flat list instead of a dict
- **Recommendation:** **Refactor to use `load_records_index()` when ID-keyed access is needed.** For list-only use cases, keep `_load_records` but add it to a shared utility module.

#### 🚩 Finding R-2: Inline file reading in `payload_resolver.py` `_search_jsonl()`
- **Code:** Custom JSONL search with record ID matching
- **Risk:** Low — this implements a specific search pattern (find by ID) that `load_records_index` doesn't support directly
- **Recommendation:** No change. Different use case.

#### 🚩 Finding R-3: Inline file reading in `atlas.py` `cmd_ingest_pilot()`
- **Code:** Direct `open(seed_path).read_text()` iteration
- **Risk:** Low — procedural pilot ingestion, non-reusable
- **Recommendation:** No change.

#### 🚩 Finding R-4: Inline loading in `scripts/progressive_expansion.py`
- **Code:** Multiple direct file reads for pilot manifest, source registry, curated files
- **Risk:** Moderate — duplicates `load_records_index` pattern
- **Recommendation:** Refactor expansion to reuse `load_records_index()` for curated data reads.

### Verdict
**Record loading has moderate duplication.** `release.py` duplicates `load_records_index()` (returning list vs dict). Progressive expansion also does its own file reads. Consider extracting a `read_jsonl(file_path) -> list[dict]` utility to `integrity.py` or a new `scripts/atlas_io.py`.

---

## 6. Schema Validation

### Canonical Service
- **Base schema:** `scripts/validate_dataset.py:structural_errors(rec)` + JSON Schema `schemas/dataset_schema.json`
- **KO schema:** `scripts/validate_knowledge_object.py:structural_errors(rec)` + JSON Schema `schemas/knowledge_object_schema.json`

### Duplicated Implementations

#### 🚩 Finding S-1: Inline schema check in `release.py:ReleaseGates.check_schema_gate()` (lines 169–205)
- **Code:** Defines its own `required_fields`, `valid_categories`, `valid_verification` sets and runs structural checks
- **Severity:** **HIGH** — this duplicates `validate_dataset.py:structural_errors()` with a different field set and enum values:
  - `validate_dataset.py` requires `ID_RE.match(id)`, `VALID_TYPES`, `VALID_ROLES`, `TAG_RE`
  - `release.py` only checks `required_fields`, `valid_categories`, `valid_verification`, message length, quality_score range
  - `valid_verification` in release.py includes `"unknown"` which is NOT in `validate_knowledge_object.py`'s VSTATES
- **Recommendation:** **Replace with calls to `validate_dataset.structural_errors()` or `validate_knowledge_object.structural_errors()`**. The release gate should compose the canonical validator rather than reimplementing it.

#### 🚩 Finding S-2: Category enum duplicated in 3+ locations
- **Files:**
  - `scripts/validate_dataset.py` line 37: `VALID_CATEGORIES`
  - `scripts/validate_knowledge_object.py` line 25: `CATS`
  - `scripts/acquisition_engine/release.py` lines 173–177: `valid_categories` (inline)
  - `scripts/atlas.py` line 226: `cats` (inline in self-test)
- **Severity:** Medium — any addition/removal of a category requires updates in 4 places
- **Recommendation:** **Extract to `metadata/categories.json` or a shared `scripts/atlas_constants.py`** and import everywhere.

#### 🚩 Finding S-3: Knowledge types duplicated
- **Files:**
  - `validate_knowledge_object.py` line 28: `KTYPES`
  - `ATLAS_SUBSYSTEM_CONTRACTS.md` (documentation only)
- **Severity:** Low — only 2 locations
- **Recommendation:** Include in the shared constants module.

### Verdict
**Schema validation has the most impactful duplication.** `release.py:check_schema_gate()` reimplements structural validation instead of composing the canonical validators. Category and knowledge type enums are duplicated across 4 modules. **This is the highest-priority refactor target.**

---

## 7. Release Checking

### Canonical Service
**`scripts/acquisition_engine/release.py:ReleaseGates`** — 7 gate checks

### Duplicated Implementations

#### 🚩 Finding E-1: Self-test inline in `atlas.py` `_run_release_self_tests()`
- **Code:** Direct instantiation of `ReleaseGates`, `ReleaseManager`, `SemanticDiff` and runs checks
- **Status:** This is testing the services, not duplicating them. ✅

#### 🚩 Finding E-2: `release-check` command in `atlas.py`
- **Code:** `cmd_release_check()` — separate entry point that duplicates the gate-running logic from `ReleaseManager.create_release()`
- **Severity:** Medium — the release-check command re-runs gates independently from create_release. The gate logic itself is not duplicated (both use `ReleaseGates`), but the orchestration path is parallel.
- **Recommendation:** **Unify `release-check` to share the same gate runner as `create_release`.** Have `release-check` call `ReleaseManager.verify_release()` instead of standalone gate runs.

#### 🚩 Finding E-3: `v0.2_review_gate_status.json`
- **Location:** `metadata/v0.2_review_gate_status.json`
- **Code:** Pre-computed gate status stored as metadata
- **Status:** This is a data artifact, not duplicated logic. ✅

### Verdict
**Release checking has minor orchestration duplication** between `cmd_release_check()` and `ReleaseManager.create_release()`. The actual gate logic lives in `ReleaseGates` which is the canonical service. Recommend unifying the CLI orchestration path.

---

## Summary: Prioritized Refactor Targets

| Priority | Issue | Location | Impact | Recommendation |
|----------|-------|----------|--------|---------------|
| **P0** | Schema gate reimplements validation | `release.py:check_schema_gate()` | **HIGH** — divergent validation logic | Replace with canonical `validate_dataset.structural_errors()` |
| **P1** | Category enums duplicated ×4 | validate_dataset.py, validate_knowledge_object.py, release.py, atlas.py | Medium — schema drift risk | Extract to shared constants module |
| **P2** | `_compute_checksum()` duplicated ×2 | payload_resolver.py, checkpoint.py | Low-medium — 3 identical SHA-256 utils | Replace with `integrity.dict_sha256()` |
| **P3** | `_load_records()` duplicates `load_records_index()` | release.py | Low — different return shape | Extract shared JSONL reader utility |
| **P4** | No canonical `is_share_alike()` | atlas.py, expansion_v2.py | Low — inline pattern matching | Add to validate_dataset.py |
| **P5** | `release-check` orchestration path parallel | atlas.py `cmd_release_check` vs `create_release` | Low — gate logic not duplicated | Unify CLI → ReleaseManager.verify_release() |

### Safe-to-Automate Refactors
1. Replace `payload_resolver._compute_checksum()` → `integrity.dict_sha256()` — **safe, pure function swap**
2. Replace `checkpoint._compute_checksum()` → `integrity.dict_sha256()` — **safe, pure function swap**
3. Extract category/knowledge_type/verification_status constants to shared module — **safe, no behavior change**

### DO NOT Automate
- Schema gate replacement in `release.py.check_schema_gate()` — requires careful verification that the canonical validator covers all edge cases the gate needs (including the `valid_verification` set that includes `"unknown"` which the KO validator rejects). Manual review required.
- `release-check` orchestration unification — requires CLI behavior analysis.
