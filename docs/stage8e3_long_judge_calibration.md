# Stage 8E.3 — LONG Judge Agreement, Calibration & Reporting

**Status:** Complete  
**Date:** 2026-08-16  
**Related:** Stage 8E.1 (Judge Criteria & Gated Invocation), Stage 8E.2 (Calibration Fixtures & Reference Labels)

---

## 1. Reference Hierarchy

Calibration analysis respects a strict authority hierarchy:

```
deterministic_reference          (authoritative — derived from deterministic gates)
        │
        ├── SCORE / OUTCOME
        │
        ▼
expert_review_required           (supplemental — needs human/expert label)
        │
        ▼
provisional                      (temporary — pending expert review)
        │
        ▼
judge_output                     (recorded — not ground truth)
```

**Rules:**
- Only compare judge outputs against reference labels that actually exist.
- If a reference is unavailable: `comparison_status = "NOT_AVAILABLE"`.
- Do NOT fabricate human/expert labels. Missing references are explicitly marked.

---

## 2. Agreement Metrics

### 2.1 Absolute Score Error

For each comparable fixture-dimension pair:

```
absolute_error = |judge_score - reference_score|
```

### 2.2 Mean Absolute Error (MAE)

```
MAE = mean(absolute_errors)
```

Computed at three levels:
- **Overall MAE**: across all comparable fixtures
- **Per-dimension MAE**: across all fixtures with reference for that dimension
- **Per-fixture MAE**: implicit in the fixture report

### 2.3 Categorical Agreement

Scores are mapped to categorical labels:

| Score Range | Category |
|-------------|----------|
| >= 0.8      | high     |
| >= 0.5      | medium   |
| > 0.0       | low      |
| == 0.0      | none     |

Categorical agreement = `True` if reference and judge categories match.

### 2.4 Dimension-Level Agreement

For each of the 8 LONG dimensions:

| Metric | Description |
|--------|-------------|
| `sample_count` | Number of fixtures with both reference and judge scores |
| `mae` | Mean absolute error across samples |
| `agreement_count` | Number of categorical matches |
| `agreement_rate` | `agreement_count / sample_count` |

---

## 3. LOW_AGREEMENT Threshold

**Threshold:** `|judge_score - reference_score| > 0.3`

When this threshold is exceeded:
- A `LOW_AGREEMENT` flag is set on the fixture report.
- The flag is **diagnostic only**.
- It does NOT modify:
  - `raw_task_score`
  - `long_outcome`
  - Any benchmark SCORE

**Rationale:** A 0.3 absolute difference represents a substantial deviation between judge assessment and reference expectation, warranting human review but not automated correction.

---

## 4. Missing Reference Semantics

| Scenario | `comparison_status` | Effect |
|----------|---------------------|--------|
| No reference value exists | `NOT_AVAILABLE` | Excluded from MAE/agreement computation |
| Reference is `expert_review_required` with null value | `NOT_AVAILABLE` | Same as above |
| Reference is `deterministic_reference` with value | `AVAILABLE` | Included in computation |
| Judge output missing | `NO_JUDGE_OUTPUT` | Excluded from comparison |
| Both reference and judge present | `AVAILABLE` | Included in computation |

Missing data is never silently treated as agreement.

---

## 5. Confidence Availability

- If the judge response includes a `confidence` field: it is preserved in the report.
- If the judge response does NOT include confidence: `confidence = null` (reported as unavailable).
- No fake confidence values are invented.

---

## 6. Reproducibility

Calibration reports are deterministic given the same inputs:
- Fixture set (from `metadata/calibration/long_judge_calibration_v1.json`)
- Judge outputs (recorded via `AgreementAnalyzer.record_judge_output()`)
- Configuration (calibration_version, rubric_version, judge_model, etc.)

The report includes a `report_hash` (SHA-256 of the serialized report, excluding the mutable `evaluation_timestamp`).

---

## 7. Limitations

1. **No live judge validation:** Judge outputs must be recorded externally. The `live_judge` status is `NOT_AVAILABLE` unless explicitly configured.
2. **Single-judge analysis:** This stage analyzes agreement between one judge and reference labels. Multi-judge consensus is handled separately.
3. **No automatic correction:** LOW_AGREEMENT flags are diagnostic. They do not trigger score adjustment.
4. **Expert references required:** Many fixtures have `expert_review_required` references with null values. Agreement metrics are computed only where reference values exist.
5. **C7 remains deterministic FAIL:** No partial-adaptation fixture was added. Adaptation quality is calibrated through C6 (successful adaptation) and judge evidence.

---

## 8. Files Changed

| File | Change |
|------|--------|
| `eb/calibration/__init__.py` | New package init |
| `eb/calibration/fixtures.py` | New — Calibration fixture loading and reference label management |
| `eb/calibration/agreement.py` | New — Agreement analysis engine (MAE, categorical, dimension-level) |
| `eb/calibration/report.py` | New — Report generation and serialization |
| `tests/test_long_horizon_calibration_8e3.py` | New — 55 tests covering all 14 required scenarios |
| `docs/stage8e3_long_judge_calibration.md` | New — This documentation |

---

## 9. Test Coverage

55 tests in `tests/test_long_horizon_calibration_8e3.py`:

| Test Class | Tests | Coverage |
|-----------|-------|----------|
| `TestAgreementCalculation` | 4 | Absolute error, symmetry, zero-error, overall MAE |
| `TestMAE` | 4 | Empty list, single value, multiple values, dimension MAE |
| `TestCategoricalAgreement` | 4 | Same category, different category, None score, boundaries |
| `TestDimensionLevelAgreement` | 3 | All 8 dimensions present, MAE computed, agreement rate |
| `TestMissingReference` | 3 | NOT_AVAILABLE status, no fabricated labels, partial references |
| `TestDeterministicReference` | 2 | Used in computation, FAIL fixtures skipped |
| `TestExpertReference` | 2 | With value included, without value excluded |
| `TestLowAgreement` | 4 | Threshold value, flag set, flag not set, diagnostic-only |
| `TestNoScoreModification` | 2 | raw_task_score untouched, long_outcome untouched |
| `TestNoOutcomeModification` | 2 | PARTIAL preserved, PASS preserved with LOW_AGREEMENT |
| `TestMetadataPreservation` | 3 | Fixture metadata, report-level metadata, hash stability |
| `TestReproducibility` | 2 | Same inputs same report, JSON serializable |
| `TestMockJudgeCalibration` | 2 | Mock outputs recorded, deterministic unaffected |
| `TestNoLiveAPI` | 4 | Default NOT_AVAILABLE, report marked, analysis runs, convenience function |
| `TestIntegrationWithExistingFixtures` | 7 | 12 fixtures load, 9 eligible, deterministic/eligible counts, dimension coverage, full report, JSON serializable |
| `TestC7AdaptationDecision` | 3 | C7 is deterministic FAIL, judge skipped, C6 provides calibration |
| `TestNonLongUnaffected` | 2 | SINGLE mode unaffected, architecture criteria unchanged |
| `TestReportGeneration` | 2 | File written, structure valid |

---

## 10. C7 / Adaptation Gap Decision

**Decision: Retain C7 as deterministic FAIL.**

Rationale:
- C7 tests the case where a requirement change is present but not adapted, causing terminal stage failure.
- Adding a C7b partial-adaptation fixture would weaken a deterministic gate to manufacture a calibration case.
- The existing LONG semantics allow successful adaptation (C6) to calibrate `adaptation_quality`.
- Judge evidence from C6 (and other PASS/PARTIAL fixtures) provides the adaptation quality calibration signal.
- C7 remains a hard FAIL because non-adaptation after a requirement change is a genuine failure mode.

---

## 11. Human Review Support

The schema supports future expert label addition without breaking changes:

```json
{
  "fixture_id": "C3-partial-impl",
  "reference_status": "expert_review_required",
  "dimension_references": {
    "correctness": {
      "value": null,
      "status": "expert_review_required",
      "rationale": "Expert verifies correctness of partial implementation"
    }
  }
}
```

When an expert provides a label, the `value` field is populated and the `status` can be updated to `expert_reference` (or kept as `expert_review_required` with a non-null value). The calibration system will automatically include the new value in agreement computations.

---

## 12. Final Verdict

**READY FOR DEVELOPMENT USE**

Stage 8E.3 implements:
- Complete agreement analysis infrastructure for LONG judge outputs
- MAE, categorical agreement, and dimension-level metrics
- LOW_AGREEMENT diagnostic flag with documented threshold (0.3)
- Proper handling of missing references (NOT_AVAILABLE, no fabrication)
- Full metadata preservation (fixture_id, hash, calibration version, rubric version, judge model, provider, etc.)
- Human-review-ready schema for future expert label injection
- 55 focused tests covering all 14 required scenarios
- Zero regressions in 8E.1 (24 tests), 8E.2 (67 tests), or non-LONG evaluators (86 tests)

**NOT YET READY FOR BENCHMARK CALIBRATION** pending:
- Expert review of C3-C6, C8, C10-C12 dimension references (currently null)
- Live judge evaluation to populate judge_output comparisons
- Expansion to N>=30 per family for statistical conclusions

**DO NOT proceed to Stage 8F automatically.**
