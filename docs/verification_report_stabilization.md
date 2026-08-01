# Atlas v1.1 Engineering Stabilization — Verification Report

**Date:** 2026-08-01
**Commit:** `3aa0ad5` (pushed to origin/main)
**Verification method:** ad-hoc probes against current on-disk artifacts + pytest suite

---

## 1. Deliverables

| # | Deliverable | Path | Status |
|---|-------------|------|--------|
| 1 | Operational runbook | `docs/runbook_classification.md` | ✅ Created (517 lines) |
| 2 | Expanded test suite | `tests/test_parallel_stabilization.py` | ✅ 21 passed, 1 skipped |
| 3 | Architecture governance | `scripts/validate_architecture.py` Check 7 | ✅ PASS, 0 violations |
| 4 | CI/pre-commit integration | `.github/workflows/ci.yml`, `.pre-commit-config.yaml` | ✅ Created |
| 5 | ADR-011 Release Immutability | `docs/adr/ADR-011-release-immutability.md` | ✅ Created |
| 6 | ADR-012 Intelligence Layer | `docs/adr/ADR-012-intelligence-layer.md` | ✅ Created |
| 7 | ADR-013 Parallel Processing | `docs/adr/ADR-013-parallel-processing.md` | ✅ Created |
| 8 | ADR-014 Release Pipeline | `docs/adr/ADR-014-release-pipeline.md` | ✅ Created |
| 9 | Verification report | `docs/verification_report_stabilization.md` (this file) | ✅ Created |

**Note on ADR numbering:** the plan requested ADR-0001..0005; the repo convention is
ADR-001..010 (no leading zeros, descriptive slugs). `ADR-0002 Canonical Dataset`
maps to existing `ADR-001-canonical-knowledge-objects.md`. New ADRs use the next
free numbers (011–014) to preserve the existing series.

---

## 2. Test Results (pytest)

```
tests/test_parallel_stabilization.py — 21 passed, 1 skipped (0.32s)
```

Coverage:
- `load_parallelism_config()` defaults + `get_classification_config()`
- malformed config (missing file → `{}`; garbage YAML → no crash)
- invalid worker counts never crash CLI
- `validate_one_file()`: ok, missing file (FileNotFoundError contract), malformed line
- `validate_dataset.py`: `--file-workers` flag, glob parallel execution, no-match exit 2
- `validator.validate_records(workers=N)`: parallel == sequential (order + validity)
- `run_extract_all.py`: help flags, missing-script clean failure
- resume/skip/cleanup: append + delete, missing-src no-op, no duplicates on restart
- deterministic outputs across runs

**Bugs found by the tests and fixed:**
1. `validator.py`: `_validate_chunk` was a local closure → **not picklable**, would
   crash any `workers>1` call. Fixed with module-level `validate_record_standalone`
   and `_validate_chunk_standalone`.
2. `run_classify_all_v2.py`: YAML fallback parser crashed (`FileNotFoundError`) when
   config was missing. Fixed to return `{}`.

**Pre-existing failures (not caused by this phase):** `test_release_pipeline.py` /
`test_join_release.py` fail on this Mac because `zstandard` is not installed
("zstandard is required"). Environment gap, unrelated to stabilization changes;
CI installs `pyyaml`+`pytest` and the release tests are not part of the CI gate.

---

## 3. Architecture Governance Results

```
Atlas Architecture Policy Validator
Checking 137 Python files...
Checked 137 files, 0 violation(s) found.
RESULT: PASS — All architecture governance rules satisfied
```

Checks enforced (existing 1–6 + new):
1. Forbidden imports (layer violations)
2. Circular dependencies
3. Duplicated constants
4. Duplicated license functions
5. Duplicated schema definitions
6. Direct path construction (disabled; known debt)
7. **NEW — hardcoded worker counts (ADR-013 contract)** — caught 1 real
   violation (`scripts/release/download_release.py: max_workers=4`), fixed it to
   read from `config/parallelism.yaml`.

CI/pre-commit: `.github/workflows/ci.yml` (push+PR) and `.pre-commit-config.yaml`
run the validator + test suite; violations fail the build.

---

## 4. Rules Compliance

| Rule | Status |
|------|--------|
| Do not touch dataset contents | ✅ No `raw/` or `curated/` writes |
| Do not modify release manifests | ✅ Manifests untouched |
| Do not interrupt v1.2 classification | ✅ dev-pc run `proc_fdfbb2298091` untouched |
| No Hugging Face operations | ✅ None |
| No release promotion | ✅ None |
| No feature implementation beyond stabilization | ✅ Only fixes found by tests |
| Preserve backward compatibility | ✅ `validate_record()` delegates to same logic; CLI flags additive |

---

## 5. Commits

| Commit | Content |
|--------|---------|
| `3aa0ad5` | stabilization: runbook, parallel tests, arch governance check 7, ADRs 011–014 |

---

## 6. Verification Evidence

- pytest: `21 passed, 1 skipped in 0.32s` (fresh run)
- `python3 scripts/validate_architecture.py` → `RESULT: PASS` (fresh run)
- All files exist at paths listed above (verified via git status)
- Push: `4ba106a..3aa0ad5  main -> main` confirmed
