# Atlas Architecture Dependency Audit — v0.2

**Date:** 2026-07-28
**Phase:** 4C.2 — Architecture Hardening: Dependency Decoupling & Contract Enforcement

---

## Current Dependency Graph (After Phase 4C.1 + 4C.2)

### Layer 1 — Foundation (stdlib-only, no project imports)

```
atlas_constants.py  (enums, license utilities)
        ↑
atlas_schema.py     (field definitions, patterns, ranges)
        ↑
atlas_paths.py      (path registry, root discovery)
```

### Layer 2 — Validation & Lifecycle (imports Layer 1)

```
validate_dataset.py  ──→ atlas_constants, atlas_schema, atlas_paths
         ↑
validate_knowledge_object.py ──→ atlas_constants, atlas_schema
         ↑
lifecycle.py ──→ atlas_constants
         ↑
quality_score.py ──→ (stdlib only)
```

### Layer 3 — Engine & Release (imports Layer 1 + Layer 2)

```
acquisition_engine/
    engine.py ──→ atlas_constants, .lifecycle, .checkpoint, .integrity, ...
    release.py ──→ atlas_constants, atlas_schema (via validate_dataset),
                   atlas_paths (root discovery)
    lifecycle.py ──→ atlas_constants
    aql.py ──→ (stdlib only)
    knowledge_collection.py ──→ ...
    knowledge_pack.py ──→ ...
    integrity.py ──→ ...
    versioning.py ──→ ...
    checkpoint.py ──→ ...
    dataset_diff.py ──→ ...
```

### Layer 4 — CLI & Tooling (imports all lower layers)

```
atlas.py ──→ atlas_constants, atlas_schema, engine, release, aql, ...
payload_resolver.py ──→ (stdlib only, path discovery independent)
```

### Layer 5 — Tests, Probes, Scripts (use Layer 1-4)

```
tests/  ──→ any layer
scripts/  (standalone) ──→ any layer
```

---

## Import Layering Rules

```
  Layer 1  (constants, schema, paths, utilities)
      ↓
  Layer 2  (validation, lifecycle, quality)
      ↓
  Layer 3  (engine, release, payload resolver)
      ↓
  Layer 4  (CLI — atlas.py)
      ↓
  Layer 5  (tests, probes, standalone scripts)
```

**Validation:** No Layer N module imports from Layer N+1.

---

## Removed Duplication

| What | Before | After |
|------|--------|-------|
| `VALID_CATEGORIES` | 4 copies (validate_dataset, validate_knowledge_object, release, atlas) | 1 copy in atlas_constants |
| `VALID_TYPES` | 1 copy in validate_dataset | 1 copy in atlas_constants |
| `VALID_ROLES` | 2 copies | 1 copy in atlas_constants |
| `is_denied_license` | 4 imports (3 lazy via importlib) | 1 canonical, direct imports everywhere |
| Required fields list (base) | Inline in validate_dataset | `BASE_ALLOWED_KEYS` in atlas_schema |
| Required fields list (KO) | 3 copies (validate_knowledge_object, atlas self-test ×2) | `KNOWLEDGE_OBJECT_REQUIRED_FIELDS` in atlas_schema |
| Lineage sub-fields | Inline tuple in validate_knowledge_object | `LINEAGE_SUB_FIELDS` in atlas_schema |
| Quality score range (0-10) | 2 copies (validate_dataset, validate_knowledge_object) | `QUALITY_SCORE_MIN/MAX` in atlas_schema |
| Difficulty range (0-3) | 2 copies | `DIFFICULTY_MIN/MAX` in atlas_schema |
| Min message turns (2) | 2 copies | `MIN_MESSAGE_TURNS` in atlas_schema |
| ID/Tag/Date regex patterns | 3 copies (validate_dataset) | 1 copy in atlas_schema |
| `LIFECYCLE_STATES` | 1 copy in lifecycle.py → now imported | 1 copy in atlas_constants |
| `VERIFICATION_STATUS_RANK` | Inline in release.py | 1 copy in atlas_constants |
| Repo root discovery | Per-file Path(__file__).resolve().parents[N] | `atlas_paths.discover_root()` |
| Approved write roots | 2 copies (atlas.py, engine.py) | `atlas_paths.APPROVED_WRITE_ROOTS` |
| Lazy importlib license import | 3 places (release, engine, atlas) | Direct from atlas_constants |
| Hardcoded config thresholds | Inline in validate_dataset, validate_knowledge_object, release, atlas | `metadata/config_policy_v1.json` |

---

## Remaining Architecture Risks

| Risk | Severity | Notes |
|------|----------|-------|
| **engine.py still has hardcoded paths** | Medium | `ROOT`, `APPROVED_ROOTS`, SIZE_REF table are all still hardcoded. SIZE_REF is data, not architecture — low priority. |
| **atlas.py APPROVED_ROOTS duplicated in engine.py** | Low | Both define the same tuple. Could be centralized via `atlas_paths.approved_write_paths()`. |
| **payload_resolver.py has independent root discovery** | Low | `_guess_root()` duplicates `atlas_paths.discover_root()` logic but has different fallback strategy. |
| **Config policy created but not consumed** | Low | `metadata/config_policy_v1.json` is the canonical source but no code reads from it yet. Behavioral change deferred to later phase. |
| **Circular import risk: atlas_schema → atlas_constants** | None | atlas_schema imports nothing from atlas_constants. Safe. |
| **Circular import risk: atlas_paths → atlas_constants** | None | atlas_paths imports nothing from atlas_constants or atlas_schema. Safe. |
| **atlas_constants imports from atlas_schema** | None | It does not — atlas_constants is independent. |
| **atlas.py still has hardcoded pilot max=100** | Low | Should read from config_policy_v1.json. Deferred. |
| **release.py category_balance_targets hardcoded** | Low | Inline dict in `print_stats()` and release gates. Deferred. |

---

## Circular Dependency Check

All layers checked via static analysis:

```
atlas_constants     → (none)                                 ✓ NO CYCLES
atlas_schema        → atlas_constants                        ✓ NO CYCLES
atlas_paths         → (none)                                 ✓ NO CYCLES
validate_dataset    → atlas_constants, atlas_schema, atlas_paths  ✓ NO CYCLES
validate_knowledge_object → atlas_constants, atlas_schema    ✓ NO CYCLES
lifecycle           → atlas_constants                        ✓ NO CYCLES
engine              → atlas_constants                         ✓ NO CYCLES
release             → atlas_constants                         ✓ NO CYCLES
atlas               → atlas_constants, atlas_schema           ✓ NO CYCLES
```

No circular import chains found. All dependencies flow top-down from Layer 1 → Layer 4.

---

## File Inventory (After Phase 4C.2)

### New files

| File | Purpose |
|------|---------|
| `scripts/atlas_constants.py` | Phase 4C.1 — enum registry + license utils (already existed) |
| `scripts/atlas_schema.py` | Phase 4C.2 — canonical schema field definitions |
| `scripts/atlas_paths.py` | Phase 4C.2 — canonical path registry |
| `metadata/config_policy_v1.json` | Phase 4C.2 — centralized configuration |
| `docs/architecture_hardening_report.md` | Phase 4C.1 — hardening report |
| `docs/architecture_dependency_audit_v0.2.md` | Phase 4C.2 — this document |

### Modified files

| File | Change |
|------|--------|
| `scripts/validate_dataset.py` | Import `ID_PATTERN`, `TAG_PATTERN`, `DATE_PATTERN`, `BASE_ALLOWED_KEYS`, `QUALITY_SCORE_MIN/MAX`, `DIFFICULTY_MIN/MAX`, `MIN_MESSAGE_TURNS` from atlas_schema |
| `scripts/validate_knowledge_object.py` | Import `KNOWLEDGE_OBJECT_REQUIRED_FIELDS`, `LINEAGE_SUB_FIELDS`, `QUALITY_SCORE_MIN/MAX`, `DIFFICULTY_MIN/MAX`, `MIN_MESSAGE_TURNS` from atlas_schema |
| `scripts/atlas.py` | Import `KNOWLEDGE_OBJECT_REQUIRED_FIELDS` from atlas_schema; remove inline required field lists |
| `scripts/acquisition_engine/engine.py` | Replace lazy `importlib.util` import of `is_denied_license` with direct import from `atlas_constants` |
| `scripts/acquisition_engine/release.py` | Phase 4C.1 already migrated; schema gate now delegates to validate_dataset.structural_errors() |
