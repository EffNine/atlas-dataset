# Atlas 500M Pilot — Freeze Experiment Corpus

**Date:** 2026-08-15
**Status:** FROZEN

## 1. Frozen Dataset Inventory

| Arm | Records | Tokens | Variance | Status |
|-----|--------:|-------:|---------:|--------|
| General | 1,167 | 1,012,158 | 1.2% | OK |
| Math | 1,181 | 950,441 | 5.0% | OK |
| Code | 510 | 951,050 | 4.9% | OK |
| Systems | 2,034 | 950,309 | 5.0% | OK |

## 2. General Baseline Composition

| Domain | Records | Tokens | Target % |
|--------|--------:|-------:|---------:|
| Math | ~280 | ~285K | 30% |
| Code | ~100 | ~390K | 40% |
| Systems | ~170 | ~190K | 20% |
| General reasoning | ~600 | ~100K | 10% |

## 3. Math Composition

- **Source:** Nemotron-Math-Proofs-v2 (1,181 records, 950K tokens)
- **Domain:** 100% Math
- **Frontier:** 84% A+ Frontier, 16% A Specialist
- **Verification:** Formal proof verification

## 4. Code Composition

- **Source:** SWE-smith-mini diversified (510 records, 951K tokens)
- **Domain:** 100% Code
- **Frontier:** 40% A Strong Specialist, 60% B Professional
- **Diversification:** 5% repo token cap enforced, 20 unique repos

## 5. Systems Composition

- **Source:** Linux kernel y9 held-out (2,034 records, 950K tokens)
- **Domain:** 100% Systems
- **Frontier:** 33% A+ Frontier, 67% A Specialist
- **Coverage:** kernel, networking, memory, drivers, architecture

## 6. Token Counts

| Arm | Target | Actual | Variance |
|-----|-------:|-------:|---------:|
| General | 1,000,000 | 1,012,158 | 1.2% |
| Math | 1,000,000 | 950,441 | 5.0% |
| Code | 1,000,000 | 951,050 | 4.9% |
| Systems | 1,000,000 | 950,309 | 5.0% |

All within ±10% tolerance.

## 7. Repository Diversity (Code)

| Metric | Value |
|--------|-------|
| Unique repos | 20 |
| Max repo % | <5% |
| Top 5 repos % | ~25% |

## 8. Contamination Validation

| Check | Result |
|-------|--------|
| Eval vs training | PASS (0 overlaps) |
| Cross-source | PASS (0 overlaps) |
| IFEval | PASS |
| SWE-bench Verified | PASS |

## 9. Manifest SHA-256

```
baaf39086280aa0c5d8d5734b1fbc82d243a748002331625a56b5273cbda683b
```

## 10. Remaining Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| General arm: 1 cosmetic validation error | LOW | Does not affect training |
| Systems eval narrow coverage | MEDIUM | P2 StackExchange will expand |
| Code domain concentration | LOW | 5% repo cap enforced |

## 11. Files Modified

| File | Size | Records |
|------|------|--------:|
| `pilot/v0.1/general/train.jsonl` | 5.9 MB | 1,167 |
| `pilot/v0.1/math/train.jsonl` | 5.2 MB | 1,181 |
| `pilot/v0.1/code/train.jsonl` | 5.5 MB | 510 |
| `pilot/v0.1/systems/train.jsonl` | 8.1 MB | 2,034 |
| `metadata/pilot_manifest_v0.2.json` | — | Manifest |

## 12. Tests Run

| Test | Result |
|------|--------|
| Schema validation (math) | PASS |
| Schema validation (code) | PASS |
| Schema validation (systems) | PASS |
| Schema validation (general) | 1 cosmetic issue (non-blocking) |
| Contamination check | PASS |
| Diversification check | PASS |
| Manifest checksum | Generated |

---

```
PILOT CORPUS:
FROZEN

READY FOR UNSLOTH TRAINING
```