# Training Readiness Report — v0.2 (Regenerated)

**Generated:** 2026-07-27T23:24:18.268352+00:00
**Phase:** Phase 5E.2.5 — Governance Metadata Synchronization
**Dataset:** Atlas Dataset Foundation — curated v0.2
**TRAINING = BLOCKED** — No training, no fine-tuning, no model execution, no v0.2 release, no automatic approvals.

---

## 1. Dataset Overview

| Metric | Value |
|--------|-------|
| **Total curated records** | 663 (100 v0.1 pilot + 152 phase4b expansion + 411 v0.1 synthetic) |
| **Review manifest records** | 150 (phase4b expansion cohort) |
| **Dataset version** | v0.2 |
| **Training recipes registered** | 4 |
| **Benchmarks registered** | 7 (3 internal + 4 external) |

---

## 2. Review Status (Synchronized from Decisions)

| Status | Count | Target |
|--------|-------|--------|
| **Approved** | 38 | ≥ 120 (80%) ❌ |
| **Pending** | 100 | 0 ❌ |
| **Rejected** | 6 | 0 ✅ |
| **Needs Revision** | 6 | 0 ❌ |

**Approval rate:** 25.3% (38 / 150)

**Review Gate Status:** ❌ **BLOCKED**

---

## 3. Quality Distribution

| Measure | Value |
|---------|-------|
| **Mean quality score** | 7.0 |
| **Score range** | 5 — 9 |
| **Below threshold (< 7)** | 34 |
| **Missing quality_score (v0.1)** | 158 |

---

## 4. Lineage & Provenance

| Check | Status | Count |
|-------|--------|-------|
| **Complete lineage** | ⚠️ Partial | 505 / 663 |
| **Provenance resolved** | ⚠️ Partial | 505 / 663 |
| **Missing lineage** | ❌ | 158 |
| **Attribution complete** | ✅ | 435 |

---

## 5. License Status

| License Check | Status | Detail |
|---------------|--------|--------|
| **Denied licenses** | ❌ | 164 records (158 unknown + 6 rejected sources) |
| **Unknown licenses** | ❌ | 158 records |
| **Attribution required** | ✅ | 435 records — all complete |

---

## 6. Evaluation Status

| Check | Status | Detail |
|-------|--------|--------|
| **Internal benchmarks** | ✅ | atlas_quality, provenance, review_agreement |
| **External benchmarks** | ✅ | MMLU, GSM8K, HumanEval, ARC |
| **Evaluation reports** | ⚠️ | 0 reports generated |
| **Reproducibility** | ⚠️ | No benchmarks in verified/reproducible status |

---

## 7. Gate Summary

| Gate | Status |
|------|--------|
| **Review gate** | ❌ BLOCKED — 100 pending, 6 needs_revision |
| **Lineage gate** | ❌ BLOCKED — 158 missing lineage |
| **Provenance gate** | ❌ BLOCKED — 158 missing provenance |
| **License gate** | ❌ BLOCKED — 164 denied/unknown |
| **Quality gate** | ❌ BLOCKED — 158 failing schema compliance |
| **Evaluation gate** | ⚠️ CONDITIONAL — benchmarks exist but no reports |

---

## 8. Final Verdict

> ## ❌ **TRAINING = BLOCKED**

**Primary blockers:**

| # | Blocker | Resolution |
|---|---------|------------|
| 1 | **Pending human review** | 100 records still pending |
| 2 | **Needs revision** | 6 records need content/provenance revision |
| 3 | **Missing lineage** | 158 records lack lineage |
| 4 | **Unknown licenses** | 158 records have unknown license |
| 5 | **Schema compliance** | 158 records fail v0.2 schema |

---

## 9. Governance Checklist

| Requirement | Met? |
|-------------|------|
| No model training started | ✅ |
| No fine-tuning performed | ✅ |
| No checkpoint created | ✅ |
| No v0.2 release made | ✅ |
| No training dataset generated | ✅ |
| Readiness assessment automated | ✅ |
| Governance enforced | ✅ TRAINING = BLOCKED |

---

*This report was regenerated during Phase 5E.2.5 metadata synchronization.*
*No training dataset generation, model training, fine-tuning, or v0.2 release has occurred.*
