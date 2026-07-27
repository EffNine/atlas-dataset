# Atlas Developer Extension Guide

**Version:** 1.0
**Date:** 2026-07-28

---

## Overview

This guide explains how to extend the Atlas codebase while respecting the
architecture governance rules defined in
`docs/governance/atlas_architecture_governance.md`.

Every extension must:
1. **Belong in the correct layer** — see the dependency layering rules
2. **Respect ownership boundaries** — don't redefine canonical constants
3. **Pass the architecture validator** — run `python scripts/validate_architecture.py`
4. **Not modify datasets, reviews, or release artifacts directly**

---

## Table of Contents

- [Adding a New Validator](#adding-a-new-validator)
- [Adding a New Dataset Source](#adding-a-new-dataset-source)
- [Adding a New Knowledge Category](#adding-a-new-knowledge-category)
- [Adding a New Release Gate](#adding-a-new-release-gate)
- [Adding a New CLI Command](#adding-a-new-cli-command)
- [General Rules](#general-rules)
- [Required Validation Steps](#required-validation-steps)

---

## Adding a New Validator

### Where the code belongs

| Layer | Location | Example |
|-------|----------|---------|
| **Validation logic** (Layer 2) | `scripts/` | `scripts/validate_new_format.py` |
| **Registry/constants** (Layer 1) | `scripts/atlas_*.py` (amend existing) | Add constants to `atlas_constants.py` |

### Steps

1. **Create the validator module** in `scripts/` (Layer 2):
   - Must import canonical enums from `atlas_constants`
   - Must import schema definitions from `atlas_schema`
   - Must import paths from `atlas_paths` (never hardcode paths)
   - Must expose a public function (e.g., `structural_errors(records)`)
   - Should return `list[dict]` with `{id, errors}` structure

2. **Register any new constants** in `atlas_constants.py`:
   - New enum values? Add to existing `frozenset` or create a new one
   - New license patterns? Add to the appropriate pattern tuple

3. **Register any new schema fields** in `atlas_schema.py`:
   - New required fields? Add to `BASE_REQUIRED_FIELDS` or `KNOWLEDGE_OBJECT_REQUIRED_FIELDS`
   - New ranges? Add `MIN`/`MAX` constants
   - New patterns? Add `re.Pattern` constants

4. **Integrate with the CLI** (Layer 4) in `scripts/atlas.py`:
   - CLI must only parse args and call the validator — no business logic
   - Add a `--validate-new` subcommand or flag

5. **Add tests** in `tests/` (Layer 5)

### What cannot be modified

- `atlas_constants.py` — but you may add new constants to it
- `atlas_schema.py` — but you may add new field definitions to it
- `atlas_paths.py` — but you may add new path factories to it
- You must not redefine existing constants, enums, or patterns

### Example

```python
# scripts/validate_new_format.py
from atlas_constants import VALID_CATEGORIES
from atlas_schema import QUALITY_SCORE_MIN, QUALITY_SCORE_MAX
from atlas_paths import curated_dir

def structural_errors(records: list[dict]) -> list[dict]:
    errors = []
    for rec in records:
        rid = rec.get("id", "unknown")
        errs = []
        # ... validation logic ...
        if errs:
            errors.append({"id": rid, "errors": errs})
    return errors
```

---

## Adding a New Dataset Source

### Where the code belongs

| Component | Location |
|-----------|----------|
| **Source discovery/ingestion logic** | `scripts/` (Layer 3 — engine) or `scripts/acquisition_engine/` |
| **Source metadata** | `metadata/source_registry.json` |
| **Acquisition manifest** | `metadata/acquisition_manifest_v0.1.json` |

### Steps

1. **Register the source** in `metadata/source_registry.json`:
   ```json
   {
     "name": "new_source_name",
     "license": "cc-by-4.0",
     "commercial_safe": true,
     "status": "candidate",
     "date_discovered": "2026-07-28"
   }
   ```

2. **Assess license** using `atlas_constants` utilities:
   ```python
   from atlas_constants import is_denied_license, requires_attribution
   if is_denied_license(source_license):
       # Reject — non-commercial or prohibited
   if requires_attribution(source_license):
       # Must track attribution in source_attribution field
   ```

3. **Create ingestion logic** (Layer 3 script):
   - Fetch/download source data
   - Convert to Atlas JSONL format (use `atlas_schema` field definitions)
   - Validate with `validate_dataset.py` or `validate_knowledge_object.py`
   - Write to `curated/` via `atlas_paths.curated_dir()` — never hardcode paths

4. **Update manifest** in `metadata/acquisition_manifest_v0.1.json`

### What cannot be modified

- Existing source entries in `source_registry.json` without a new discovery date
- Existing `source_attribution` records in already-curated datasets
- Any `review_queue/` content — new sources go through the review pipeline

### Rules

- All new sources must pass the `is_denied_license()` gate
- NC/ND/proprietary/unknown licenses are rejected at the source level
- CC-BY-SA sources require attribution tracking documentation
- The source_id must be unique and descriptive

---

## Adding a New Knowledge Category

### Where the code belongs

| Component | Location |
|-----------|----------|
| **Category enum** | `atlas_constants.py` — `VALID_CATEGORIES` frozenset |
| **Category balance targets** | `metadata/config_policy_v1.json` — `category_balance_targets_v01` |
| **Category metadata** | `metadata/categories.json` |

### Steps

1. **Add the category code** to `atlas_constants.VALID_CATEGORIES`:
   ```python
   VALID_CATEGORIES: frozenset[str] = frozenset({
       "01_foundation",
       "02_software_engineering",
       # ... existing ...
       "10_new_category",  # ADD — keep 2-digit prefix ordering
   })
   ```

2. **Add balance target** in `metadata/config_policy_v1.json` (if applicable):
   ```json
   "10_new_category": 0.05,
   ```
   Ensure all targets still sum to 1.0 (adjust others if needed).

3. **Add description** in `metadata/categories.json`:
   ```json
   {
     "id": "10_new_category",
     "name": "New Knowledge Category",
     "description": "Description of the new category",
     "subcategories": ["subcat_1", "subcat_2"]
   }
   ```

4. **Update schemas** if the category affects field validation (unusual — most
   categories are validated by membership in `VALID_CATEGORIES` only).

### What cannot be modified

- Category IDs of existing curated records
- The `VALID_TYPES` or `VALID_KNOWLEDGE_TYPES` frozensets (unless you're also
  adding a new type)
- Release manifests that already reference category distribution targets
  (these are frozen snapshots)

### Validation steps

1. Run `python scripts/validate_dataset.py --check` on curated files
2. Run `python scripts/validate_architecture.py` — no new violations
3. Run `python scripts/atlas.py self-test` — all pass

---

## Adding a New Release Gate

### Where the code belongs

| Component | Location |
|-----------|----------|
| **Gate logic** | `scripts/acquisition_engine/release.py` (Layer 3) |
| **Gate registration** | `release.py` — add to `_GATE_CHECKS` or gate runner |
| **Gate config thresholds** | `metadata/config_policy_v1.json` — under `release_gates` |

### Steps

1. **Add the gate function** in `release.py` (Layer 3):
   ```python
   def check_new_gate(records: list[dict]) -> ReleaseGateResult:
       \"\"\"Check compliance with the new rule.\"\"\"
       errors = []
       for rec in records:
           # ... gate logic ...
           pass
       return ReleaseGateResult(passed=len(errors) == 0, errors=errors)
   ```

2. **Register the gate** in the gate runner (e.g., add to `_GATE_CHECKS` list):
   ```python
   _GATE_CHECKS: list[GateCheck] = [
       # ... existing gates ...
       GateCheck("new_gate", check_new_gate),
   ]
   ```

3. **Add config threshold** in `metadata/config_policy_v1.json`:
   ```json
   "new_gate_threshold": 0.8
   ```

4. **Document the gate** in `docs/specs/release_manifest_spec.md`
5. **Add test** in `tests/probe_acquisition_engine.py`

### What cannot be modified

- Existing gate signatures (function names, return types)
- Existing gate config keys in `config_policy_v1.json` (add, don't rename)
- Release manifests already published in `metadata/releases/` — they are
  frozen

### Rules

- Gate logic must **not** duplicate structural validation (that belongs in
  `validate_dataset.py`). Use `validate_dataset.structural_errors()` if
  you need per-field checks.
- Gate config values belong in `config_policy_v1.json`, not hardcoded in
  `release.py`.
- `is_denied_license()` and friends must come from `atlas_constants` —
  never re-implemented.

---

## Adding a New CLI Command

### Where the code belongs

| Component | Location |
|-----------|----------|
| **CLI command definition** | `scripts/atlas.py` (Layer 4) |
| **Business logic** | A Layer 3 module in `scripts/` or `scripts/acquisition_engine/` |
| **Argument parsing** | `scripts/atlas.py` — subparser setup |

### Steps

1. **Add business logic** as a Layer 3 function first (e.g., `scripts/my_command.py`):
   ```python
   # scripts/my_command.py  (Layer 3)
   def execute(args: dict) -> dict:
       \"\"\"Perform the operation. No CLI formatting here.\"\"\"
       result = ...
       return result
   ```

2. **Create CLI command** in `scripts/atlas.py`:
   ```python
   def cmd_my_command(args: argparse.Namespace) -> None:
       \"\"\"CLI wrapper — parse args, call business logic, format output.\"\"\"
       from my_command import execute
       result = execute(vars(args))
       # Format and print — NO business logic in this function
       if result.get("success"):
           print(f"Operation completed: {result['message']}")
       else:
           print(f"Operation failed: {result['error']}")
           sys.exit(1)
   ```

3. **Register the subparser** in `main()`:
   ```python
   parser_my = subparsers.add_parser("my-command", help="Description")
   parser_my.add_argument("--flag", action="store_true")
   parser_my.set_defaults(func=cmd_my_command)
   ```

4. **Add test** in `tests/` (Layer 5)

### What cannot be modified

- CLI commands must not contain business logic (validation, scoring, path
  construction, dataset transformation)
- CLI commands must not modify datasets, reviews, or release metadata
- The `main()` function must remain minimal (dispatch only)

### Rules

- CLI commands are Layer 4 — they may import from Layers 1, 2, and 3
- CLI commands must use `atlas_paths` for path resolution
- CLI commands must not redefine canonical constants or functions
- Error messages should be user-friendly but the logic behind them lives
  in Layer 2/3 modules

---

## General Rules

### Code Placement Decision Table

| What you're adding | Layer | Directory | Example |
|-------------------|-------|-----------|---------|
| New enum, constant, or license utility | 1 | `scripts/` | Add to `atlas_constants.py` |
| New schema field, pattern, or range | 1 | `scripts/` | Add to `atlas_schema.py` |
| New path factory or root discovery | 1 | `scripts/` | Add to `atlas_paths.py` |
| New validation function | 2 | `scripts/` | New file or add to existing validator |
| New lifecycle state | 2 | `scripts/acquisition_engine/` | Add to `lifecycle.py` |
| New quality dimension or scorer | 2 | `scripts/` | Amend `quality_score.py` |
| New engine component | 3 | `scripts/acquisition_engine/` | New file in `acquisition_engine/` |
| New release gate | 3 | `scripts/acquisition_engine/` | Add to `release.py` |
| New CLI command | 4 | `scripts/` | Add subparser to `atlas.py` |
| New standalone script | 4 | `scripts/` | New file, import from lower layers |
| New test | 5 | `tests/` | New file in `tests/` |

### What Must Never Be Done

| Action | Why |
|--------|-----|
| Import from `atlas.py` in a Layer 2 or 3 module | CLI is above engine; creates circular risk |
| Redefine `VALID_CATEGORIES`, `is_denied_license`, or other canonical API | Duplication defeats the purpose of centralization |
| Hardcode `Path("curated/...")` outside `atlas_paths.py` | Path drift makes the codebase fragile |
| Write scoring logic outside `quality_score.py` | Scoring must be deterministic and auditable via one engine |
| Create or modify release artifacts outside `release.py` | Releases must be signed, chained, and auditable |
| Modify curated dataset files outside the acquisition pipeline | Dataset integrity depends on strict write control |
| Hardcode config thresholds instead of reading `config_policy_v1.json` | Centralized config is the single source of truth |

---

## Required Validation Steps

Before submitting any change:

```bash
# 1. Architecture governance
python scripts/validate_architecture.py

# 2. Self-test
python scripts/atlas.py self-test

# 3. Acquisition engine probe
python tests/probe_acquisition_engine.py

# 4. Release chain verification (if release-related)
python scripts/atlas.py release --chain-verify

# 5. Specific module tests
python tests/probe_architecture_hardening_4c2.py

# 6. Dataset validation (if modifying validation logic)
python scripts/validate_dataset.py --input curated/v0.1/pilot_candidates.jsonl
python scripts/validate_knowledge_object.py --input ...

# 7. Quality engine (if modifying scoring)
python tests/verify_quality_engine.py
```

### CI Pipeline Requirements

The CI pipeline must include:

```yaml
# Pseudo-config
steps:
  - name: Architecture Governance
    run: python scripts/validate_architecture.py
  - name: Self-Test
    run: python scripts/atlas.py self-test
  - name: Acquisition Probe
    run: python tests/probe_acquisition_engine.py
  - name: Release Chain
    run: python scripts/atlas.py release --chain-verify
```

---

## References

- `docs/governance/atlas_architecture_governance.md` — Full governance contract
- `docs/architecture_dependency_audit_v0.2.md` — Current dependency graph
- `docs/canonical_services.md` — Canonical service registry
- `docs/architecture_health_report.md` — Architecture health scorecard
- `scripts/validate_architecture.py` — Automated governance validator
