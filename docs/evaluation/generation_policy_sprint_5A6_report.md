# Sprint 5A.6 — Dynamic Budget Implementation Report

> **Sprint:** 5A.6 — Dynamic Budget Strategy (implementation)
> **Status:** COMPLETE — ready for Technical Lead review. Stopped; no further
> scope implemented.
> **Date:** 2026-08-06
> **Base commit:** `99e88e1`
> **Driving specification:** Approved Protocol v2 architecture + Sprint 5A.5
> calibration report (`docs/research/generation_policy_calibration_5A5.md` §12).

---

## 1. Implementation Summary

Implemented `DynamicBudgetStrategy` and integrated it into the existing
`BudgetStrategy` interface (Sprint 5A.4 infrastructure). `GenerationPolicy`
now selects between `StaticBudget` and `DynamicBudgetStrategy` via the
`budget_strategy` field — **configuration-driven only, no hardcoded model
names**.

Key design decisions:
- `DynamicBudgetStrategy` uses the **same formula** as `StaticBudget`
  (`min(max, max(min, base + ceil(alpha * N_ref)))`) but its four parameters
  (`base_budget`, `alpha`, `minimum_budget`, `maximum_budget`) are configurable
  at construction time from the Sprint 5A.5 calibrated values.
- Both strategies implement the same `BudgetStrategy` Protocol and expose the
  same interface (`compute`, `fixed_fallback`, `rule`, `minimum_budget`,
  `maximum_budget`, `fallback_budget`), so validation and metadata code is
  strategy-agnostic.
- `GenerationPolicy.budget_strategy` defaults to `"static"` for backward
  compatibility; `from_family` sets `"dynamic"` for all three families using
  the calibrated params from `FAMILY_BUDGET_PARAMS`.
- `GenerationPolicy.budget_rule` is `"dynamic-reference-derived"` for dynamic
  families and `"budget_i = min(...)"` for static (canonical).
- No frozen assets, configs, evaluators, prompts, datasets, or benchmarks were
  modified.

---

## 2. Files Changed

All changes are to the existing `generation_policy/` package and its test suite:

| File | Change |
|------|--------|
| `scripts/evaluation_engine/generation_policy/budget.py` | Added `DynamicBudgetStrategy` class (same formula, configurable params, `minimum_budget`/`maximum_budget` properties on `StaticBudget` for interface alignment) |
| `scripts/evaluation_engine/generation_policy/versioning.py` | Added `RULE_DYNAMIC_REFERENCE_DERIVED`, `FAMILY_BUDGET_PARAMS` (per-family calibrated params), updated `SUPPORTED_BUDGET_RULES` |
| `scripts/evaluation_engine/generation_policy/policy.py` | Added `budget_strategy` and `budget_params` fields to `GenerationPolicy`; updated `from_family` and `from_dict` to set dynamic strategy for families with calibrated params |
| `scripts/evaluation_engine/generation_policy/validation.py` | Added dynamic-param validation (`_validate_dynamic_params`); updated `validate_policy` to check `budget_strategy` and dynamic params; updated `validate_budget_result` to use `minimum_budget`/`maximum_budget` (works for both strategies) |
| `scripts/evaluation_engine/generation_policy/__init__.py` | Exported `DynamicBudgetStrategy` and `RULE_DYNAMIC_REFERENCE_DERIVED` |
| `tests/evaluation_v2/test_generation_policy.py` | Updated existing tests for new defaults; added `TestDynamicBudgetStrategy`, `TestStrategySelection`, `TestBackwardCompatibility` (22 new tests) |

No files outside `scripts/evaluation_engine/generation_policy/` and
`tests/evaluation_v2/test_generation_policy.py` were modified.

---

## 3. Public API Changes

### New exports from `evaluation_engine.generation_policy`

| Symbol | Type | Description |
|--------|------|-------------|
| `DynamicBudgetStrategy` | frozen dataclass | Configurable reference-derived budget strategy |
| `RULE_DYNAMIC_REFERENCE_DERIVED` | `str` | Budget rule identifier for dynamic strategies |

### `GenerationPolicy` new fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `budget_strategy` | `str` | `"static"` | `"static"` or `"dynamic"` — selects strategy at construction time |
| `budget_params` | `dict \| None` | `None` | Per-family calibrated params when `budget_strategy == "dynamic"` |

### `StaticBudget` interface alignment

`StaticBudget` now exposes `minimum_budget` and `maximum_budget` properties
(aliasing `min_budget` / `max_budget`) so both strategies share the same
validation interface. No behavior change.

### Strategy selection

```python
from evaluation_engine.generation_policy import family_default_policy

p = family_default_policy("math")
# p.budget_strategy == "dynamic"
# p.budget_params == {"base_budget": 128, "alpha": 3.0,
#                     "minimum_budget": 256, "maximum_budget": 4096}
# p.budget_rule == "dynamic-reference-derived"
```

Backward-compatible: a policy loaded without `budget_strategy` defaults to
`"static"` and uses `StaticBudget`.

---

## 4. Configuration Examples

### Math family (calibrated per Sprint 5A.5)

```json
{
  "family": "math",
  "budget_strategy": "dynamic",
  "budget_params": {
    "base_budget": 128,
    "alpha": 3.0,
    "minimum_budget": 256,
    "maximum_budget": 4096
  }
}
```

### Code family (calibrated per Sprint 5A.5)

```json
{
  "family": "code",
  "budget_strategy": "dynamic",
  "budget_params": {
    "base_budget": 256,
    "alpha": 2.0,
    "minimum_budget": 256,
    "maximum_budget": 4096
  }
}
```

### Semantic family (provisional — same as math per Sprint 5A.5)

```json
{
  "family": "semantic",
  "budget_strategy": "dynamic",
  "budget_params": {
    "base_budget": 128,
    "alpha": 3.0,
    "minimum_budget": 256,
    "maximum_budget": 4096
  }
}
```

### Backward-compatible static policy (pre-5A.6)

```json
{
  "family": "math",
  "budget_strategy": "static"
}
```

---

## 5. Unit Test Summary

Command: `pytest tests/evaluation_v2/test_generation_policy.py -q`

**Result: 96 passed, 0 failed** (full suite: 248 passed).

| Test class | Tests | Coverage |
|------------|------:|----------|
| `TestVersioning` | 5 | version constants, `version_info`, support checks |
| `TestBudgetStrategy` | 12 | StaticBudget formula, cap/floor, fallback, determinism, immutability |
| `TestGenerationPolicy` | 14 | from_family (all families), unknown family, immutability, hashes, dict round-trip, strict loading |
| `TestGenerationConfig` | 8 | defaults, immutability, round-trip, strict loading |
| `TestConfigurationLoading` | 5 | dict + JSON file loading, version rejection |
| `TestGenerationValidation` | 19 | policy/config/pair/budget validation, invalid cases |
| `TestGenerationMetadata` | 8 | block hashes, run block contents, covariates |
| `TestEndToEndDeterminism` | 3 | full chain determinism |
| **`TestDynamicBudgetStrategy`** | **10** | interface, math/code params, rule string, fallback, determinism, immutability, round-trip |
| **`TestStrategySelection`** | **9** | family→dynamic selection, from_dict dynamic/static, unknown strategy rejection, invalid params rejection, missing keys, bad alpha, round-trip |
| **`TestBackwardCompatibility`** | **3** | StaticBudget unaffected, pre-5A.6 policy signature, dynamic with static rule |

### Key new test coverage

- **Math calibrated params**: N=10 → floor 256, N=100 → 428, N=1200 → 3728, N=2000 → cap 4096
- **Code calibrated params**: N=50 → 356, N=10 → 276
- **Family defaults**: all three families (`math`, `code`, `semantic`) select `"dynamic"` with correct params
- **Backward compat**: `from_dict` without `budget_strategy` defaults to `"static"`; pre-5A.6 `GenerationPolicy` construction still valid
- **Validation**: unknown strategy rejected; missing/dynamic-param invalid values rejected

---

## 6. Architecture Compliance Report

### 6.1 Implemented (per spec)

| Requirement | Compliance |
|-------------|-----------|
| `DynamicBudgetStrategy` | Implemented in `budget.py`; frozen dataclass; same `BudgetStrategy` Protocol |
| Integration into `BudgetStrategy` interface | Both strategies share `compute`, `fixed_fallback`, `rule`, `minimum_budget`, `maximum_budget` |
| `GenerationPolicy` strategy selection via config | `budget_strategy` field (`"static"` / `"dynamic"`); no model-name branching |
| Configuration: family, base_budget, alpha, min, max | All four params stored in `budget_params` dict; validated by `GenerationValidation` |
| Validation rejects invalid values | `_validate_dynamic_params` checks type, positivity, min≤max |
| No hardcoded model names | Family-only dispatch via `FAMILY_BUDGET_PARAMS`; no model references |
| Unit tests | 22 new tests; all 96 generation_policy + 248 full suite pass |
| Documentation | Module docstrings updated; this report |

### 6.2 NOT modified (per constraints)

| Exclusion | Verified |
|-----------|----------|
| Inference changes | No model loads, no generation code touched |
| Evaluator changes | `evaluation_engine/v2/*` untouched |
| Prompt changes | `leakage/prompts.py` untouched |
| Dataset changes | No eval-set reads or writes |
| Benchmark changes | No benchmark logic changed |
| Calibration changes | Sprint 5A.5 coefficients applied verbatim (no recalibration) |
| RP-002 changes | Unaffected |

### 6.3 Determinism & immutability

- `DynamicBudgetStrategy` is a frozen dataclass (cannot be edited after construction).
- `compute` is deterministic: same `reference` + `token_counter` → identical `BudgetResult`.
- `rule` is a computed property reflecting the actual constants — no hidden state.
- `GenerationPolicy.from_family` is deterministic: same family → same params.

---

## 7. Dependency Graph (relevant edges)

```
leakage.prompts (UNMODIFIED)
       ↑
versioning.py ← FAMILY_BUDGET_PARAMS, RULE_DYNAMIC_REFERENCE_DERIVED
       ↑
budget.py    ← DynamicBudgetStrategy (uses versioning constants)
       ↑
policy.py    ← GenerationPolicy (imports DynamicBudgetStrategy via versioning)
       ↑
validation.py ← _validate_dynamic_params (imports from budget, versioning)
       ↑
__init__.py  ← re-exports DynamicBudgetStrategy, RULE_DYNAMIC_REFERENCE_DERIVED
```

No cycles. No changes to existing edges. Only additive imports.

---

## 8. SHA-256 Hashes

| File | SHA-256 |
|------|---------|
| `scripts/evaluation_engine/generation_policy/budget.py` | `d676777b…` |
| `scripts/evaluation_engine/generation_policy/versioning.py` | `77760685…` |
| `scripts/evaluation_engine/generation_policy/policy.py` | `a41f3fa8…` |
| `scripts/evaluation_engine/generation_policy/validation.py` | `89ef5703…` |
| `scripts/evaluation_engine/generation_policy/__init__.py` | `a8d73fc0…` |
| `tests/evaluation_v2/test_generation_policy.py` | `8aefc7ee…` |

Full hashes:
- `budget.py`: `d676777bd96d00c830347c7ff496185496d03db587730a3def2f303eece472dd`
- `versioning.py`: `7776068526790aad999be1cfc2925c23c9d70b969c617fc9659c97f0cbbfc71f`
- `policy.py`: `a41f3fa8eb49be8c7b0eb299e12f25d16616a263c75ea6fff29c4f01ee91cd38`
- `validation.py`: `89ef5703c53bb65544173dbe80d364019c1f90153bbee7b2ca10114911cb057f`
- `__init__.py`: `a8d73fc01a74f47297ca82f45bcf7d435f71b7bcbdefe399d2e73b9b81c1157e`
- `test_generation_policy.py`: `8aefc7ee0b9d292dd14133409e25173050f2c827b7a94e729c3e615f54c7045a`

---

## 9. Known Limitations

1. **Semantic family params are provisional.** Same coefficients as math (alpha 3.0)
   used as a conservative placeholder. Actual calibration requires a semantic
   eval set.
2. **`from_dict` does not validate params at construction.** Validation happens
   in `GenerationValidation.validate_policy`. A policy loaded from an untrusted
   dict must be validated before use (fail-closed).
3. **`StaticBudget` and `DynamicBudgetStrategy` share formula but differ in
   parameter source.** A future `HybridBudgetStrategy` (reference + prompt, per
   Sprint 5A.5 F6) would need a third strategy class — not implemented here.
4. **No `get_budget_strategy(policy)` factory exported.** Strategy selection is
   done inline by callers (the runner would check `policy.budget_strategy` and
   instantiate the appropriate class). A factory is a candidate follow-up.
5. **Pre-5A.6 serialized policies** (without `budget_strategy` / `budget_params`
   fields) load as `"static"` with canonical params — backward compatible.

---

## 10. Rules Compliance

- [x] No inference. No model loads, no generation.
- [x] No evaluator changes.
- [x] No RP-002 changes.
- [x] No prompt changes.
- [x] No dataset changes.
- [x] No benchmark changes.
- [x] No calibration performed (calibrated coefficients from 5A.5 applied verbatim).
- [x] No hardcoded model names.
- [x] Stopped after Sprint 5A.6 deliverables. **Waiting for Technical Lead
      review.**

---

*Sprint 5A.6 implementation complete. Awaiting review before any further
scope is executed.*
