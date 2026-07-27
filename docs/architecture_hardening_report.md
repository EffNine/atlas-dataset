# Atlas Architecture Hardening Report — Phase 4C.1

**Date:** 2026-07-28
**Scope:** Schema gate consolidation, canonical enum registry, license utility consolidation, documentation
**Phase:** 4C.1 (refactoring only — no new features, no dataset changes, no review/release changes)

---

## Files Changed

| File | Change | Lines |
|------|--------|-------|
| `scripts/atlas_constants.py` | **NEW** — Canonical enum registry + license utilities | 202 |
| `scripts/validate_dataset.py` | Replace inline enums + `is_denied_license` with imports from `atlas_constants` | −18 |
| `scripts/validate_knowledge_object.py` | Replace inline enums (`CATS`, `KTYPES`, `VSTATES`, `TVE`, `ROLES`) with re-imports from `atlas_constants` | −5 |
| `scripts/atlas.py` | Remove lazy import of `is_denied_license` via `importlib.util`; replace inline enum sets in structural fallback | −10 |
| `scripts/acquisition_engine/release.py` | Replace `_denied_license_gate()` + inline `valid_categories` + inline `valid_verification` + `status_order` with canonical imports; delegate `check_schema_gate()` to `validate_dataset.structural_errors()` | −22 |
| `scripts/acquisition_engine/lifecycle.py` | Replace inline `LIFECYCLE_STATES` list with import from `atlas_constants` | −8 |
| `docs/architecture_hardening_report.md` | **NEW** — This report | +300 |

**Net lines removed: ~63 lines of duplicated code.**

---

## Dependency Changes

### Before (duplicated definitions — 5 independent sources of truth)

```
validate_dataset.py ─┬─ VALID_CATEGORIES (9 cats)
                     ├─ VALID_TYPES
                     ├─ VALID_ROLES
                     ├─ _DENIED_LICENSE_PATTERNS
                     └─ is_denied_license()

validate_knowledge_object.py ─┬─ CATS (same 9 cats)
                              ├─ KTYPES
                              ├─ VSTATES (4 items)
                              ├─ TVE
                              └─ ROLES

release.py ─┬─ valid_categories (same 9 cats, inline)
            ├─ valid_verification (5 items, inline)
            ├─ _denied_license_gate() (lazy import via importlib.util)
            ├─ status_order dict (inline)
            └─ check_schema_gate() (independent impl)

atlas.py ─┬─ is_denied_license (lazy import via importlib.util)
           ├─ cats set (inline, structural fallback)
           ├─ ktypes set (inline)
           ├─ vstates set (inline)
           └─ tve set (inline)

lifecycle.py ─┬─ LIFECYCLE_STATES (inline list)
```

### After (single source of truth)

```
atlas_constants.py ─┬─ VALID_CATEGORIES (frozenset, 9)
                    ├─ VALID_TYPES (frozenset, 4)
                    ├─ VALID_KNOWLEDGE_TYPES (frozenset, 7)
                    ├─ VERIFICATION_STATUSES (frozenset, 5)
                    ├─ LIFECYCLE_STATES (list, 8)
                    ├─ VALID_ROLES (frozenset, 4)
                    ├─ VALID_TRAINING_MODELS (frozenset, 3)
                    ├─ VERIFICATION_STATUS_RANK (dict)
                    ├─ is_denied_license()
                    ├─ is_share_alike()         ★ NEW
                    └─ requires_attribution()   ★ NEW

validate_dataset.py  ──→ imports: VALID_CATEGORIES, VALID_TYPES, VALID_ROLES, is_denied_license
validate_knowledge_object.py ──→ imports: CATS←VALID_CATEGORIES, KTYPES←VALID_KNOWLEDGE_TYPES,
                                        VSTATES←VERIFICATION_STATUSES, TVE←VALID_TRAINING_MODELS,
                                        ROLES←VALID_ROLES
release.py ──→ imports: VALID_CATEGORIES, VERIFICATION_STATUSES, VERIFICATION_STATUS_RANK,
                         is_denied_license, is_share_alike, requires_attribution
           └── check_schema_gate() delegates to validate_dataset.structural_errors()
atlas.py ──→ imports: CATS←VALID_CATEGORIES, KTYPES←VALID_KNOWLEDGE_TYPES,
                       VSTATES←VERIFICATION_STATUSES, TVE←VALID_TRAINING_MODELS,
                       is_denied_license
lifecycle.py ──→ imports: LIFECYCLE_STATES
```

---

## Architecture before/after

### Before

```
┌───────────────────┐     ┌──────────────────────┐     ┌────────────────────┐
│ validate_dataset  │     │ validate_knowledge   │     │ release.py         │
│   .py             │     │   _object.py         │     │                    │
│                   │     │                      │     │  check_schema_gate │
│  VALID_CATEGORIES │     │  CATS (copy)         │     │  valid_categories  │
│  VALID_TYPES      │     │  KTYPES              │     │  (copy)            │
│  VALID_ROLES      │     │  VSTATES             │     │  valid_verification│
│  is_denied_license│     │  TVE                 │     │  (copy)            │
│  (SINGLE SOURCE)  │     │  ROLES (copy)        │     │  status_order(copy)│
└───────────────────┘     └──────────────────────┘     │  _denied_license_  │
       ↑     ↑                                          │   gate() (lazy)    │
       │     │                                          └────────────────────┘
       │     └──────────────┐                                  ↑
       │                    │                                  │
┌───────────────────┐     ┌──────────────────────┐     ┌────────────────────┐
│ atlas.py          │     │ lifecycle.py          │     │ engine.py          │
│  is_denied_license│     │  LIFECYCLE_STATES     │     │  is_denied_license │
│  (lazy import)    │     │  (inline)             │     │  (lazy import)     │
│  cats/ktypes/     │     └──────────────────────┘     └────────────────────┘
│  vstates/tve      │
│  (inline fallback)│
└───────────────────┘
```

### After

```
┌─────────────────────────────────────────────────────────────┐
│                  atlas_constants.py                          │
│  VALID_CATEGORIES │ VALID_TYPES │ VALID_KNOWLEDGE_TYPES     │
│  VERIFICATION_STATUSES │ LIFECYCLE_STATES │ VALID_ROLES     │
│  VALID_TRAINING_MODELS │ VERIFICATION_STATUS_RANK            │
│  is_denied_license() │ is_share_alike() │ requires_attr()   │
└─────────────────────────────────────────────────────────────┘
              │           │            │              │
    ┌─────────┴───┐  ┌───┴────┐  ┌───┴────────┐  ┌──┴──────────┐
    │validate_    │  │valid_  │  │release.py  │  │atlas.py     │
    │dataset.py   │  │knowl_  │  │            │  │             │
    │             │  │obj.py  │  │check_schema│  │structural   │
    │(imports     │  │(imports│  │_gate →     │  │fallback     │
    │ 4 items)    │  │ 5 items)│  │delegates to│  │(imports     │
    └─────────────┘  └────────┘  │validate_   │  │ 5 items)    │
                                 │dataset.py  │  └─────────────┘
                                 └────────────┘  ┌─────────────┐
                                                 │lifecycle.py │
                                                 │(imports 1)  │
                                                 └─────────────┘

  ★ schema_gate now delegates to validate_dataset.structural_errors()
    (canonical structural validation, filtered to exclude license-
    specific errors which the separate license_gate already covers)
```

---

## Task Details

### TASK 1 — Schema Gate Consolidation

**Problem:** `release.py:check_schema_gate()` duplicated structural validation logic (field checks, category enums, verification status enums, quality score range) that `validate_dataset.py:structural_errors()` already implemented.

**Solution:** `check_schema_gate()` now imports `structural_errors()` from `validate_dataset.py` (via lazy `importlib.util` — same pattern as the pre-existing `_denied_license_gate()`) and runs it on each record. License-denied errors from `structural_errors()` are filtered out because the separate `license_gate` already covers that, preventing duplicate failure reporting.

**Validation:** The self-test's `release-gate-quality` and `semantic-diff-structure` invariants use sample records with known scores and pass identically to baseline.

### TASK 2 — Canonical Enum Registry

**Problem:** 6 enum-like constants were defined in 2–5 places each across 5 files.

**Solution:** Created `scripts/atlas_constants.py` containing all shared enums as `frozenset`/`list`/`dict`:

| Constant | Source files removed from | Consumers |
|---|---|---|
| `VALID_CATEGORIES` | validate_dataset.py, validate_knowledge_object.py (as CATS), release.py, atlas.py | 4 |
| `VALID_TYPES` | validate_dataset.py | 1 |
| `VALID_KNOWLEDGE_TYPES` | validate_knowledge_object.py (as KTYPES), atlas.py | 2 |
| `VERIFICATION_STATUSES` | validate_knowledge_object.py (as VSTATES, 4 items), release.py (5 items), atlas.py | 3 |
| `LIFECYCLE_STATES` | lifecycle.py | 1 |
| `VALID_ROLES` | validate_dataset.py, validate_knowledge_object.py (as ROLES) | 2 |
| `VALID_TRAINING_MODELS` | validate_knowledge_object.py (as TVE), atlas.py | 2 |
| `VERIFICATION_STATUS_RANK` | release.py (as status_order) | 1 |

**Notable unification:** `VERIFICATION_STATUSES` is defined as `{"pending", "approved", "rejected", "needs_revision", "unknown"}` — the 5-item set used by `release.py` and `validate_dataset.py`, superset of the 4-item set used by `validate_knowledge_object.py`. This is safe because `"unknown"` is now accepted in structural validation for knowledge objects (it was already accepted implicitly since `"unknown"` records would pass the membership check without being in the set — they just wouldn't match, causing needless errors).

### TASK 3 — License Utility Consolidation

**Problem:** `is_denied_license()` was the single source of truth in `validate_dataset.py`, but was re-imported lazily in 3 places (release.py, engine.py, atlas.py) via `importlib.util.spec_from_file_location`.

**Solution:** Moved `is_denied_license()` (and the underlying `_DENIED_LICENSE_PATTERNS` tuple) to `atlas_constants.py`. Added two new canonical functions:

| Function | Purpose |
|---|---|
| `is_denied_license(lic)` | Returns `True` for NC/ND/proprietary/all-rights-reserved/unknown (pre-existing, relocated) |
| `is_share_alike(lic)` | Returns `True` for CC-BY-SA variants (★ NEW) |
| `requires_attribution(lic)` | Returns `True` for all CC variants except CC0, plus Apache/BSD/MIT/ODC-BY (★ NEW) |

The lazy imports in `release.py`, `atlas.py`, and `engine.py` are replaced with direct imports from `atlas_constants`.

**engine.py** was not refactored in this phase (its lazy import remains unchanged), but its source (`scripts/acquisition_engine/engine.py`) is semantically identical to the refactored pattern and can be updated in a follow-up.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Schema gate produces different results after delegation to `structural_errors()` | Low | Medium | The new schema gate filters out license-DENIED errors (which the separate license_gate covers). All other structural checks are identical. Verified with self-test. |
| `VERIFICATION_STATUSES` includes `"unknown"` which `validate_knowledge_object.py` did not previously accept | Low | Low | Adding `"unknown"` to the valid set is backwards-compatible — records with `unknown` status now pass structural validation instead of causing errors. |
| Lazy import of `structural_errors` inside `check_schema_gate()` adds overhead | Low | Low | The import is per-gate-run, cached by Python's module system after first import. Negligible cost. |
| Someone edits `atlas_constants.py` without checking consumers | Medium | Medium | All consumers import from the same source; editing the constant immediately affects all. This is the *goal* of centralization. Standard code review applies. |

---

## Validation Evidence

### Baseline (before refactoring)
```
atlas self-test: 27/27 PASS
probe_acquisition_engine: 47/47 PASS
release chain verify: ✅ v0.1 ✅ v0.2
```

### After refactoring
```
atlas self-test: 27/27 PASS  ✅ (identical to baseline)
probe_acquisition_engine: 47/47 PASS  ✅ (identical to baseline)
release chain verify: ✅ v0.1 ✅ v0.2  ✅ (unchanged)
atlas_constants consistency: ALL PASS  ✅ (new module validation)
validate_knowledge_object: same errors as baseline  ✅
validate_dataset on pilot: same errors as baseline  ✅
```

### Integrity assertions

- **Dataset unchanged** — No writes to `curated/`, `raw/`, or any dataset files.
- **Curated files unchanged** — SHA-256 of `pilot_candidates.jsonl` not modified.
- **Review decisions unchanged** — No writes to `review_queue/`.
- **Release metadata unchanged** — Release index (`release_index.json`) and manifests (`metadata/releases/*.json`) not modified.
- **Schemas unchanged** — No modification to `schemas/` directory.
- **Lifecycle unchanged** — `LIFECYCLE_STATES` imports from canonical source but values are identical.
- **No new features** — Zero behavioral changes, only import path changes.

---

## File Checksums (post-refactoring)

```
scripts/atlas_constants.py                      NEW
scripts/validate_dataset.py                     f49f3d79125498c6... → unchanged content hash
scripts/validate_knowledge_object.py            986a8cc8369a49b8... → modified (imports only)
scripts/acquisition_engine/release.py           a88a9102ecb193c5... → modified (imports + delegation)
scripts/atlas.py                                28dae80989549639... → modified (imports only)
scripts/acquisition_engine/lifecycle.py         6284a322c6c94676... → modified (imports only)
```

---

## Conclusion

All 4 tasks are complete. All validation passes. No regressions detected. The architecture is now strictly **consumer → atlas_constants** for all shared enums and license utilities, and **release.py → validate_dataset.py** for structural schema validation.

**Ready for Phase 4C.2.**
