# Architecture Health Report

> Phase 4C.0 — Architecture Consolidation & Dependency Unification
> Generated: 2026-07-28

This report evaluates Atlas architecture across 9 dimensions on a 1–10 scale (10 = excellent, 1 = critical concern). Each score is explained with evidence from code inspection, dependency analysis, and subsystem contract extraction.

---

## Overall Health Score: **7.4 / 10**

| Dimension | Score | Summary |
|-----------|-------|---------|
| Coupling | 7 | Well-layered DAG; license gate is single source of truth; minor leaf→engine duplication |
| Cohesion | 8 | Each module has a clear single responsibility; engine/manager separation is clean |
| Reusability | 7 | Services are importable; CLI exposes most operations; some inline logic in expansion scripts |
| Maintainability | 7 | Well-documented modules; stdlib-only design; ADR-based spec evolution; enum duplication risk |
| Determinism | 9 | Pure functions, stdlib-only, no network, no randomness; very strong design principle |
| Testability | 6 | Self-test framework covers invariants; but no unit-test suite; no pytest harness yet |
| Scalability | 5 | Single-threaded, synchronous; no streaming/batching in most paths; 1K–250K record range |
| Governance | 8 | Lifecycle state machine enforced; release gates mandatory; ADR-driven spec changes |
| Technical Debt | 6 | Moderate debt: schema gate duplication, duplicate SHA-256 utils, no shared constants, ununified expansion paths |

---

## Dimension 1: Coupling — **7 / 10**

### Definition
How tightly interconnected are subsystems? Low coupling means modules can change independently.

### Strengths
- **Single license gate:** `is_denied_license()` is the one source of truth, imported by 5+ consumers via importlib. This is textbook low coupling.
- **Acquisition Engine → Service pattern:** Engine imports Services (Checkpoint, Integrity, Lifecycle, Versioning, KnowledgePack) — Services never import the Engine.
- **Leaf services are isolated:** AQL, QualityEngine, PayloadResolver, DatasetDiff have zero dependencies on other Atlas modules (stdlib only).
- **No circular imports** in the acquisition_engine package graph.

### Weaknesses
- **`release.py` hardcodes schema validation logic** instead of composing `validate_dataset.py`. If the dataset schema changes, `release.py:check_schema_gate()` diverges silently.
- **Progressive Expansion has tight coupling** — `progressive_expansion.py` hardcodes file paths and imports specific validator/quality functions rather than composing the Acquisition Engine.
- **Category enums duplicated** across validate_dataset.py, validate_knowledge_object.py, release.py, and atlas.py — a category addition requires 4-file change.
- **`atlas.py` CLI has mixed concerns** — some commands directly orchestrate (self-test, ingest-pilot) while others delegate to engine modules.

### Recommendation
Reduce coupling by:
1. Making `release.py:check_schema_gate()` call `validate_dataset.structural_errors()`
2. Extracting shared constants to `scripts/atlas_constants.py`
3. Refactoring progressive expansion to use the Acquisition Engine API

---

## Dimension 2: Cohesion — **8 / 10**

### Definition
Whether each module has a clear, single responsibility.

### Strengths
- **Each acquisition_engine module has one job:** `lifecycle.py` = state machine, `checkpoint.py` = persist/resume, `integrity.py` = checksums + verification, `versioning.py` = version snapshots
- **`quality_score.py`** — single purpose (evaluation), well-scoped API (score_record + evaluate_record)
- **`aql.py`** — single purpose (query parsing + execution), no imported Atlas dependencies
- **`payload_resolver.py`** — single purpose (record lookup), well-documented priority chain
- **Validator separation** — `validate_dataset.py` (base schema) vs `validate_knowledge_object.py` (superset schema) is a clean separation of concerns.

### Weaknesses
- **`release.py` contains THREE cohesive units** — `ReleaseGates`, `ReleaseManager`, `SemanticDiff` — all in one file. While logically related, the file is 1077 lines. SemanticDiff has a different lifecycle than ReleaseManager and could be cleanly extracted.
- **`atlas.py` is 1608 lines** — it mixes CLI commands, self-test logic, pilot ingestion, and network-blocking utilities. This is acceptable for a CLI entry point but the self-test `_run_release_self_tests()` especially has grown large.
- **`progressive_expansion_v2.py`** duplicates the structure of `progressive_expansion.py` — two similar but separate expansion scripts with parallel logic.

### Recommendation
Improve cohesion by:
1. Extracting `SemanticDiff` to its own module
2. Unifying progressive expansion into one pipeline that calls the Engine
3. Considering splitting `atlas.py` into `atlas_cli.py` + `atlas_self_test.py` (low priority)

---

## Dimension 3: Reusability — **7 / 10**

### Definition
How easily modules can be reused in different contexts.

### Strengths
- **Service modules are importable** — all acquisition_engine modules expose clean class/function APIs
- **CLI exposes all major operations** via subcommands (release, collection, query, self-test, release-check)
- **Stdlib-only design** means zero dependency management for reuse — runs anywhere Python 3.11 does
- **Configuration-driven formatting** — `configs/formatting/templates.json` makes adding model formats a config edit, not a code change

### Weaknesses
- **`progressive_expansion.py` is a standalone script** that doesn't expose its stages as reusable functions. It hardcodes file paths and runs procedurally.
- **No pip package** — Atlas is a directory of scripts, not a pip-installable package. Reuse requires cloning the repo or copying files.
- **No public API surface** — there's no `from atlas import ...` pattern; users must know the file structure.
- **`ReleaseGates` duplicates schema validation** — the gate logic is tightly coupled to inlined `valid_categories` instead of being generic.

### Recommendation
Improve reusability by:
1. Creating a `setup.py`/`pyproject.toml` for pip installation
2. Refactoring progressive expansion into the Engine pipeline so it's reusable
3. Making `ReleaseGates` accept a validator callable rather than hardcoding validation

---

## Dimension 4: Maintainability — **7 / 10**

### Definition
How easy it is to understand, change, and extend the system.

### Strengths
- **Well-documented code** — every module has a detailed docstring, public API comments, and design invariants
- **ADR-driven evolution** — `docs/adr/` contains structured decision records for every contract change
- **README + design docs** — `docs/dataset_design.md`, `docs/source_policy.md`, `docs/quality_standard.md` etc.
- **`ATLAS_SUBSYSTEM_CONTRACTS.md`** is an excellent single-source reference for all subsystem contracts
- **Schemas are self-documenting** — JSON Schema files with descriptions
- **Consistent coding style** — all scripts use `from __future__ import annotations`, type hints, `Path` over `os.path`

### Weaknesses
- **Enum duplication** — category, knowledge_type, verification_status defined in 4 files. Schema changes require multi-file edits that are easy to miss.
- **No version changelog** — the repo has releases but no CHANGELOG.md tracking changes between versions
- **`progressive_expansion_v2.py`** exists alongside `progressive_expansion.py` without clear documentation of which is current
- **Review operations** (`review/operations/`) are workflow files without a corresponding Python module to manage them
- **Migration runner** is in `migrations/` directory, not `scripts/` — inconsistent with other modules
- **No type stubs** — no `.pyi` files, so IDE assistance is limited

### Recommendation
Improve maintainability by:
1. Centralizing enums in a shared constants module
2. Creating CHANGELOG.md
3. Documenting expansion script lineage (which is active, which is deprecated)
4. Standardizing module locations

---

## Dimension 5: Determinism — **9 / 10**

### Definition
Whether identical inputs always produce identical outputs.

### Strengths
- **Stdlib-only scoring** — `quality_score.py` uses no randomness, no network, no external state
- **AQL is pure** — same query + same records = same results every time
- **Schema validation is deterministic** — purely structural or JSON Schema based
- **Self-test is deterministic** — all checks use assert conditions, no timing-dependent behavior
- **Network blocks enforced** — `install_network_block()` patches socket + urllib to raise on any network access
- **SHA-256 hash chains** — VerificationLog and ReleaseManager chain use content-addressed hashing
- **Deterministic planning** — `AcquisitionEngine.dry_run()` produces the same plan from the same manifest + registry

### Weaknesses
- **`scripts/progressive_expansion.py` line ~25** uses `random` for sampling — but it's not seeded deterministically:
  ```python
  import random
  ```
  Any `random.choice()` or `random.sample()` call without a fixed seed breaks reproducibility across runs.
- **`scripts/progressive_expansion_v2.py`** — may have the same issue depending on random usage
- **File modification times** — some scripts use `datetime.now()` for timestamps, which is non-deterministic but acceptable for metadata

### Recommendation
- Seed `random` with a deterministic value in expansion scripts or use `hash`-based selection instead
- Document which outputs are expected to vary (timestamps) vs which must be invariant (scores, plans, diffs)

---

## Dimension 6: Testability — **6 / 10**

### Definition
How easy it is to write tests and verify correctness.

### Strengths
- **Self-test framework** in `atlas.py` covers ~30 invariants including schema, license gate, AQL parsing, release gates, and chain verification — all runnable with `python scripts/atlas.py self-test`
- **Pure functions are very testable** — `quality_score.score_record()`, `aql.execute_query()`, `validate_dataset.structural_errors()` are all pure functions
- **Services accept dependencies via constructors** — `LifecycleTracker(metadata_dir)`, `ReleaseManager(dataset_root)` can be instantiated with temp directories
- **ChecksumRegistry.verify()** and **VerificationLog.verify_chain()** are self-validating

### Weaknesses
- **No unit test suite** — `tests/` directory exists but contains no pytest tests. The only testing is the self-test framework.
- **No mock/patch strategy** — tests that need network blocks or fake data must use the live filesystem
- **No CI configuration** — no `.github/workflows/` or CI config. Self-test must be run manually.
- **No test fixtures** — tests reuse live dataset files rather than minimal synthetic fixtures
- **`tests/` directory is empty** of Python test files:
  ```
  ./tests/
  ./tests/__pycache__/
  ```
- **Hardcoded paths** in many scripts (e.g., `progressive_expansion.py` line 30: `REPO = Path("/Users/afnanrudy/Github-Projects/ai-datasets/atlas-dataset")`) make them fail when run from a different checkout location

### Recommendation
1. Add pytest with fixtures for each service module
2. Make hardcoded paths configurable (environment variable or CLI argument)
3. Add CI configuration (GitHub Actions) running `self-test` on push
4. Add per-module `test_*.py` files in `tests/`

---

## Dimension 7: Scalability — **5 / 10**

### Definition
How well the system handles increasing data volume (records, files, operations).

### Strengths
- **Checkpoint-based resume** allows interrupting and resuming batch ingestion
- **Release chain design** supports an unbounded number of releases
- **AQL execution** is O(n) over records — acceptable for dataset-scale (1000–250K records)
- **Integrity verification** uses streaming SHA-256 (8MB chunks) — memory efficient

### Weaknesses
- **Single-threaded** — no parallelism in Acquisition Engine, Quality Evaluation, or Release Gates. Batch operations process records sequentially.
- **No record streaming** — `execute_query()` loads all records into memory. At 250K+ records, memory usage becomes a concern.
- **`load_records_index()`** loads ALL records into a dict before diffing — O(n) memory
- **No pagination** in many operations — file loads are all-or-nothing
- **No lazy/deferred evaluation** — quality scoring evaluates all dimensions even if only the score is needed
- **JSONL.gz handling** — `knowledge_pack.py` decompresses entire files into memory
- **No database backend** — everything is file-based. At scale, file I/O becomes a bottleneck.

### Recommendation
- Calculate maximum record count before memory becomes a concern (~500K records × 2KB = 1GB heap)
- Add record streaming/iteration support to AQL and DatasetDiff
- Consider SQLite for metadata indexing at scale (>100K records)
- Document scalability limits explicitly

---

## Dimension 8: Governance — **8 / 10**

### Definition
How well policies, workflows, and lifecycle constraints are enforced.

### Strengths
- **Lifecycle state machine** is enforced — `LifecycleTracker.transition()` validates every transition and raises `ValueError` for invalid ones
- **Release gates are mandatory** — `ReleaseManager.create_release()` blocks release unless all gates pass (unless `force=True`)
- **ADR-driven evolution** — spec changes require ADR first, then migration, then implementation
- **Network/write guards** — `install_network_block()` prevents accidental network access; `_assert_write_safe()` prevents unauthorized file writes
- **Write approval roots** — only `curated/`, `review_queue/`, `training_views/`, `metadata/`, `docs/`, `tmp/`, `raw/pilot/`, `migrations/`, `knowledge_packs/` are writable
- **Immutable raw data** — `raw/` is never modified by any pipeline script
- **Hash-chain signatures** — every release is hash-chained to its predecessor, forming an audit trail
- **Self-test enforces invariants** — exits non-zero if any invariant fails

### Weaknesses
- **Review state governance is file-based** — review decisions live in `review/decisions/` JSONL files without a state machine equivalent. Missing or corrupt review manifests cause issues.
- **No automated policy enforcement** for license attribution tracking (CC-BY-SA, RAIL-M) — the system relies on documentation + manual runbook steps
- **Calibration is advisory** — calibration reports are generated but aren't enforced as a gate
- **No governance for Training View eligibility** — the `training_view_eligibility` field exists in the schema but no automation blocks ineligible records from view generation

### Recommendation
- Add Review state machine (similar to LifecycleTracker) for decisions
- Add automated attribution tracking for conditional licenses
- Consider making calibration verdict a release gate (configurable)

---

## Dimension 9: Technical Debt — **6 / 10**

### Definition
The accumulated cost of suboptimal design decisions that will require future correction.

### Assessed Debt Items

| Item | Severity | Effort to Fix | Risk if Unaddressed |
|------|----------|---------------|---------------------|
| Schema gate duplicated in release.py | High | 1 day | Divergent validation → silent policy gaps |
| Category/KType/VStatus enums ×4 | Medium | 0.5 day | Schema drift on category/type changes |
| Two SHA-256 utils duplicated | Low | 0.5 day | Minimal (cosmetic) |
| Two progressive expansion scripts | Medium | 2 days | Confusion about which is authoritative |
| Hardcoded paths in expansion | Medium | 0.5 day | Fails on different machines |
| `release-check` orchestration parallel | Low | 0.5 day | Redundant CLI code |
| No canonical `is_share_alike()` | Low | 0.25 day | Inline share-alike detection inconsistent |
| No unit tests | High | 5 days | Changes require manual regression testing |
| No CI | Medium | 1 day | No automated regression detection |
| Review state file-based (no state machine) | Medium | 2 days | Corrupt review files hard to detect |
| No CHANGELOG | Low | 0.5 day | Hard to track what changed between releases |

### Total Estimated Fix Effort: ~13 person-days

### Debt Ratio
- Total LOC: ~30,000 (scripts/ + schemas/ + tests/)
- Known debt items: 11
- Priority items (P0–P1): 4
- **Estimated debt ratio: ~15%** (code that should be refactored vs. code that's clean)

### Recommendation
Dedicate a focused consolidation sprint to:
1. Fix the schema gate duplication (P0)
2. Centralize enums (P1)
3. Add unit test skeleton with 1–2 working tests per module (sustainable habit)
4. Unify expansion scripts
5. Set up CI

---

## Dimension Summary Table

| Dimension | Score | Trend | Key Risk |
|-----------|-------|-------|----------|
| **Coupling** | 7 | → | Schema gate reimplements validator |
| **Cohesion** | 8 | → | release.py triple concern (Gates+Manager+Diff) |
| **Reusability** | 7 | ↗ | No pip package limits sharing |
| **Maintainability** | 7 | → | Enum duplication ×4 |
| **Determinism** | 9 | ↗ | Strong principle; minor untracked randomness |
| **Testability** | 6 | → | No unit tests, no CI |
| **Scalability** | 5 | → | Single-threaded, all-in-memory |
| **Governance** | 8 | → | Review state lacks state machine |
| **Technical Debt** | 6 | → | 4 P0–P1 items, ~13 days to clear |

**Overall: 7.4 / 10** — Solid foundation with clear, actionable improvement areas. The architecture is well-conceived but needs a consolidation pass before scaling beyond v0.2.
