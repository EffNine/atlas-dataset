# Sprint 5A.4 — Generation Policy Infrastructure Report

> **Sprint:** 5A.4 — Protocol v2 Generation Policy (implementation)
> **Status:** COMPLETE — ready for Technical Lead review. Stopped; no further
> scope implemented.
> **Date:** 2026-08-06
> **Base commit:** `99e88e1` (feat(evaluation): freeze QEE v2 engine for Phase 8 experiments)
> **Scope:** reusable infrastructure only. No dynamic budget tuning, no
> evaluator/inference/prompt/dataset/training/LoRA/benchmark changes.

---

## 1. Implementation Summary

Implemented a new, self-contained, stdlib-only subpackage
`scripts/evaluation_engine/generation_policy/` that declares, loads, validates,
and records the **Generation Policy Lock** (Protocol v2
`docs/research/protocol_v2_transition.md` §3.6, generalized from
`docs/research/p8_generation_policy.md` §4).

Deliverables mapped to the sprint:

| Sprint item | Delivered as |
|-------------|--------------|
| `GenerationPolicy` | `GenerationPolicy` frozen dataclass (`policy.py`) |
| `GenerationConfig` | `GenerationConfig` frozen dataclass (`config.py`) |
| `GenerationValidation` | `GenerationValidation` deterministic gate + `ValidationResult` (`validation.py`) |
| `GenerationMetadata` | `GenerationMetadata` metadata-block builders (`metadata.py`) |
| `BudgetStrategy` interface | `BudgetStrategy` Protocol + `TokenCounter` Protocol (`budget.py`) |
| `StaticBudget` implementation | `StaticBudget` reference-derived budget (`budget.py`) |
| Configuration loading | strict dict + JSON-file loaders (`schema.py`) |
| Version support | version registry + support checks (`versioning.py`) |

The package is a pure library: it never loads a model, never runs inference,
never scores, and never reads or writes dataset / eval-set / config artifacts.
All prompt constants continue to come from the canonical shared module
`evaluation_engine.leakage.prompts` (rule P4) — the new package only references
them; no prompt text was changed. `PolicyLock` in `leakage/prompts.py` was not
modified.

---

## 2. Files Changed

All changes are **additions**; no existing file was modified.

| File | Role |
|------|------|
| `scripts/evaluation_engine/generation_policy/__init__.py` | Public API exports + `__all__` |
| `scripts/evaluation_engine/generation_policy/versioning.py` | Version registry, support checks, protocol constants |
| `scripts/evaluation_engine/generation_policy/budget.py` | `BudgetStrategy`, `TokenCounter`, `StaticBudget`, `BudgetResult` |
| `scripts/evaluation_engine/generation_policy/policy.py` | `GenerationPolicy`, family defaults, extraction/format accounting |
| `scripts/evaluation_engine/generation_policy/config.py` | `GenerationConfig`, strict loading, self-hash |
| `scripts/evaluation_engine/generation_policy/validation.py` | `GenerationValidation`, `ValidationResult` |
| `scripts/evaluation_engine/generation_policy/metadata.py` | `GenerationMetadata`, `generation_policy_lock` block, covariates |
| `scripts/evaluation_engine/generation_policy/schema.py` | Configuration loading (dict / JSON file) |
| `tests/evaluation_v2/test_generation_policy.py` | Unit test suite (74 tests) |
| `docs/evaluation/generation_policy_sprint_5A4_report.md` | This report |

No file under `curated/`, `raw/`, `review_queue/`, `training_views/`,
`configs/`, `config/`, `evaluation/eval_sets/`, or any frozen eval asset was
created, modified, or deleted.

---

## 3. Public API

Exported from `evaluation_engine.generation_policy`:

| Symbol | Kind | Purpose |
|--------|------|---------|
| `GenerationPolicy` | frozen dataclass | Immutable per-family generation policy; `from_family`, `from_dict`, `to_dict`, `sha256`, `to_block` |
| `GenerationConfig` | frozen dataclass | Immutable locked inference config; `from_dict`, `to_dict`, `sha256`, `to_block` |
| `GenerationValidation` | class (static methods) | `validate_policy`, `validate_config`, `validate_pair`, `validate_budget_result` |
| `ValidationResult` | frozen dataclass | `valid`, `issues`, `policy_sha256`, `config_sha256`, `to_dict` |
| `GenerationMetadata` | class (static methods) | `policy_block`, `config_block`, `run_policy_lock_block`, `per_record_metadata`, `covariates`, `generation_policy_summary` |
| `BudgetStrategy` | Protocol | `compute(reference, *, token_counter=None) -> BudgetResult` |
| `TokenCounter` | Protocol | `(text: str) -> int` |
| `StaticBudget` | frozen dataclass | Reference-derived budget; `compute`, `fixed_fallback`, `rule` |
| `BudgetResult` | frozen dataclass | `budget`, `rule`, `reference_tokens`, `fallback_used`, `capped`, `floor_applied`, `to_dict` |
| `DEFAULT_STATIC_BUDGET` | `StaticBudget` | Canonical budget (protocol defaults) |
| `load_policy` / `load_config` | functions | Strict dict loading, version-aware |
| `load_policy_file` / `load_config_file` | functions | JSON file loading, version-aware |
| `family_default_policy` / `default_generation_config` | functions | Canonical family policy / canonical config |
| `write_policy_file` / `write_config_file` | functions | Deterministic JSON serialization |
| `run_policy_validation` / `run_config_validation` | functions | Module-level validation conveniences |
| `version_info` | function | Declarative version snapshot |
| `assert_family_supported`, `assert_policy_version_supported`, `assert_schema_version_supported` | functions | Fail-closed support checks |
| `GENERATION_POLICY_VERSION`, `POLICY_SCHEMA_VERSION`, `CONFIG_SCHEMA_VERSION`, `SUPPORTED_FAMILIES`, `SUPPORTED_POLICY_VERSIONS`, `SUPPORTED_SCHEMA_VERSIONS`, `SUPPORTED_BUDGET_RULES`, `SUPPORTED_SAMPLING` | constants | Version / support registry |

### Canonical budget rule (unchanged from Protocol v2 §3.6)

```
budget_i = min(4096, max(256, 128 + ceil(1.5 * N_tokens(reference_i))))
```

`StaticBudget.compute` implements this exactly (verified against the formula in
`TestBudgetStrategy.test_formula_matches_protocol`), with cap 4096, floor 256,
and the 1024 fallback recorded as `fallback_used=True`. No-counter or
counter-failure paths return the fallback budget deterministically — never a
fabricated value.

---

## 4. Unit Test Report

Command (hermetic venv, offline, stdlib-only):

```
pytest tests/evaluation_v2/test_generation_policy.py -q
```

**Result: 74 passed, 0 failed** (also confirmed the full existing suite still
passes: `pytest tests/evaluation_v2/ -q` → **226 passed**).

| Test class | Tests | Coverage |
|------------|------:|----------|
| `TestVersioning` | 5 | version constants, `version_info`, support-check pass/raise, family registration |
| `TestBudgetStrategy` | 12 | interface conformance, canonical rule equality, formula vs protocol, cap/floor, fallback (no-counter and counter-failure), determinism, custom constants, fixed-fallback mode, `BudgetResult` immutability + `to_dict` |
| `TestGenerationPolicy` | 14 | `from_family` math/code/semantic, unknown family, immutability, stable/change-detecting hashes, dict round-trip, unknown-key/version/schema/family/non-dict rejection, `to_block` self-hash |
| `TestGenerationConfig` | 8 | protocol defaults, immutability, stable hash, round-trip, partial load, unknown-key/schema/non-dict rejection |
| `TestConfigurationLoading` | 5 | dict + JSON-file policy/config loading, non-object rejection, unsupported-version rejection |
| `TestGenerationValidation` | 19 | valid policy/config/pair/budget; invalid family, version, budget rule, extraction; sampling/`do_sample`/temperature/top_p determinism gates; budget-fallback bounds; pad==eos; pair stop mismatch; budget-result consistency; result immutability |
| `TestGenerationMetadata` | 8 | block self-hashes, run-block determinism + contents, covariates (incl. empty = not fabricated), per-record metadata, policy summary |
| `TestEndToEndDeterminism` | 3 | full policy→config→validation→metadata chain per family; repeat-build identical hashes; supported budget rules |

---

## 5. Architecture Compliance Report

### 5.1 Implemented (per spec)

| Requirement | Compliance |
|-------------|-----------|
| Strong typing | All public symbols fully annotated (`Protocol`, `dataclass`, `tuple[str, ...]`, `dict[str, Any]`, `str \| Path`); mypy-style errors clean in authored files |
| Immutable configuration | `GenerationPolicy`, `GenerationConfig`, `StaticBudget`, `BudgetResult`, `ValidationResult` are frozen dataclasses; immutability asserted by tests |
| Deterministic behaviour | Hashing over canonical sorted JSON; budget formula closed-form; metadata blocks order-insensitive; repeat-build tests pass |
| Modular architecture | One concern per module (versioning / budget / policy / config / validation / metadata / schema); public API isolated in `__init__` |
| Unit tests | 74 tests, hermetic/offline, stdlib-only |
| Documentation | Module docstrings + this report |

### 5.2 NOT implemented (per spec — verified absent)

| Exclusion | Verified |
|-----------|----------|
| Dynamic budget tuning | No such code path exists; `StaticBudget` is closed-form and frozen. `"dynamic-tuning"` is explicitly rejected by validation and is not in `SUPPORTED_BUDGET_RULES` |
| Evaluator changes | `evaluation_engine/v2/*` untouched (pre-existing working-tree edits were not made by this sprint) |
| Inference changes | No `model.generate`, no model imports; `eos/pad` ids left as `None` for the runner to resolve |
| Prompt changes | `leakage/prompts.py` untouched; new code only *reads* prompt constants (rule P4) |
| Dataset changes | No dataset / eval-set reads or writes |
| Training / LoRA | None |
| Benchmark modifications | No benchmark or runner behavior changed |

### 5.3 Project-rules compliance

- **Fail closed:** unknown keys, unsupported schema/version/family, and
  non-deterministic configs are rejected rather than inferred.
- **No fabricated data:** covariates on empty input are `None`/`0.0`, never
  invented; budget fallback is explicit (`fallback_used`).
- **Frozen assets untouched:** no edits under `curated/`, `raw/`,
  `review_queue/`, `training_views/`, `configs/`, or frozen eval sets.
- **Deterministic:** same inputs → same objects, hashes, blocks.
- **Provenance:** policy blocks carry `policy_lock_sha256`, `policy_sha256`,
  `config_sha256` so a run records exactly which policy/config produced it.

---

## 6. Dependency Graph

```
            evaluation_engine.leakage.prompts   (stdlib only; UNMODIFIED)
                       ^  ^  ^
                       |  |  |
   versioning.py ──────┘  |  └────────────── policy.py
      ^  ^  ^             |
      |  |  |             |
      |  +--+-----------> budget.py ────┐
      |  |                                |
      |  +-----------> config.py          │
      |                                   │
      |             +---------------------┘
      |             v
      |      validation.py   (budget, config, policy, versioning)
      |             ^
      |             |
      +-----------> metadata.py   (budget, config, policy, versioning)
      |             ^
      |             |
      +-----------> schema.py     (config, policy, versioning)
      |
      v
  __init__.py  (re-exports the public API from all of the above)
      ^
      |
  tests/evaluation_v2/test_generation_policy.py
      (public API + policy + versioning + leakage.prompts)
```

Edges (import direction, `A → B` means A imports B):

- `versioning.py → leakage.prompts`
- `policy.py → leakage.prompts, versioning`
- `budget.py → versioning`
- `config.py → versioning`
- `validation.py → budget, config, policy, versioning`
- `metadata.py → budget, config, policy, versioning`
- `schema.py → config, policy, versioning`
- `__init__.py → budget, config, metadata, policy, schema, validation, versioning`
- `test_generation_policy.py → generation_policy.*, leakage.prompts`

**External dependencies:** none (Python standard library only). The only
intra-repo coupling is the read-only reference to `leakage.prompts`, which
keeps prompt constants canonical (rule P4). No cycles exist.

---

## 7. SHA-256 Hashes

Computed with `shasum -a 256` on 2026-08-06.

| File | SHA-256 |
|------|---------|
| `scripts/evaluation_engine/generation_policy/__init__.py` | `9468971f111daebcdcd03734f1256c0fa4850e8a3807726839fad5e07531c859` |
| `scripts/evaluation_engine/generation_policy/versioning.py` | `92f91dc89bad6af6980bb50b1c429b566c18ea6b6a2cdb122e9c1bdcf5f8eef2` |
| `scripts/evaluation_engine/generation_policy/budget.py` | `72e8f0cf82e534ca704c1cbbedf64db2ed98ea1a5e23f09fc849455de6ee85e9` |
| `scripts/evaluation_engine/generation_policy/policy.py` | `c8c88067f50eaf9dcaa87a6d07037b1823520a69b0f49fd840f95a6a57c303b7` |
| `scripts/evaluation_engine/generation_policy/config.py` | `50948dec1a60a6571bc323c57969414a53e3bb502a7358980d37ee1176d45585` |
| `scripts/evaluation_engine/generation_policy/validation.py` | `e008946f947b5495d6eb667597a08d406c30fff59d8cf7ff738c09c486fbaffb` |
| `scripts/evaluation_engine/generation_policy/metadata.py` | `c861ca44c431bb67515a6924863639b7a62f8cd0bd15b77054956d34a67b9fe3` |
| `scripts/evaluation_engine/generation_policy/schema.py` | `2da2c58ff01fd70fae28700c67c8367b0b98eedcbe9d6df888d067b0a2a9207e` |
| `tests/evaluation_v2/test_generation_policy.py` | `da9c9e8dae62c81240304a1c965d6784eb5e8052b3e00c18a78495230ca7a6c4` |
| `docs/evaluation/generation_policy_sprint_5A4_report.md` | see git after writing (self-referential; re-hash on read) |

---

## 8. Known Limitations

1. **Not yet wired into a runner.** This sprint ships reusable infrastructure
   only. `run_baseline_t3.py`, `protocol_v2_certificate.py`, and
   `leakage/prompts.py` still carry their own inline budget/policy constants;
   a follow-up sprint should migrate them onto this package. Deferred by scope
   (no inference changes).
2. **`semantic` family budget/stop defaults.** Protocol v2 documents math and
   code locks explicitly; the semantic family inherits the same budget rule and
   stop sequence by convention (`SUPPORTED_FAMILIES` includes it). No semantic
   eval set exists yet to lock its policy against.
3. **Token counting is injected.** `StaticBudget` has no tokenizer dependency;
   callers supply a `TokenCounter`. Without one, the deterministic 1024
   fallback is used (recorded as a covariate), matching the existing runner's
   fail-soft behaviour.
4. **Single supported sampling mode.** Only `greedy` is accepted
   (`SUPPORTED_SAMPLING`); a future non-deterministic arm would require a new
   versioned sampling entry and a determinism statement, both fail-closed.
5. **`eos/pad` ids are caller-resolved.** The config leaves them `None`; the
   runner must populate and re-validate them at generation time (validation
   already enforces `pad == eos` when both are set).
6. **No JSON schema (JSON Schema) artifacts.** Loading is implemented in Python
   (`schema.py`) with strict key/version checks; no standalone
   `.schema.json` files are emitted. Not required by the sprint, but a
   candidate follow-up.
7. **Covariates rounded to 4 dp / 2 dp.** Aggregates are rounded for stable,
   compact recording; this is bookkeeping, not a measurement, so rounding is
   documented rather than treated as precision.

---

## 9. Rules Compliance

- [x] No training / retraining.
- [x] No inference runs — no model loads, no generation.
- [x] No evaluator, prompt, dataset, config, or benchmark modification.
- [x] No dynamic budget tuning.
- [x] No frozen asset edited (`curated/`, `raw/`, `review_queue/`,
      `training_views/`, eval sets, `configs/`).
- [x] No fabricated numbers; fallbacks and empty aggregates are explicit.
- [x] Stopped after Sprint 5A.4 deliverables. **Waiting for Technical Lead
      review.**

---

*Sprint 5A.4 implementation complete. Awaiting review before any further
scope is executed.*
