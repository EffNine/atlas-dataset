# Atlas v0.2 Reviewer Calibration Report

**Phase:** 4B.4 — Reviewer Calibration Round  
**Datasets:** `curated/v0.2/data/phase4b_expansion.jsonl`  
**Calibration file:** `review/calibration/v0.2/calibration_samples.jsonl`  
**Reviewer guidance:** `review/calibration/v0.2/reviewer_guidelines.md`  
**Checklist:** `review/calibration/v0.2/checklist.md`  
**Status:** calibration artifacts created; human review **not started**; **v0.2 release remains blocked**

---

## 1. Purpose

This document defines the calibration process for Atlas v0.2 human review consistency.
It does **not** contain production approval decisions, dataset modifications, or release
authorization.

Calibration is a pre-review alignment step to ensure reviewer scoring is consistent
before full human review execution begins.

---

## 2. Calibration Sample Summary

**Total records assigned to review:** 150  
**Calibration sample size:** 20  
**Selection method:** stratified representative sample from `curated/v0.2/data/phase4b_expansion.jsonl`

### 2.1 Category Coverage

| Category | Count in Sample |
|---|---|
| 01_foundation | 3 |
| 02_software_engineering | 4 |
| 03_system_engineering | 3 |
| 04_ai_machine_learning | 4 |
| 05_hardware_engineering | 3 |
| 06_science_engineering | 1 |
| 07_business_knowledge | 1 |
| 08_creative_knowledge | 1 |

**Total:** 8 of 8 major categories represented.

### 2.2 Quality Score Distribution

| Score | Count |
|---|---|
| 7 | 18 |
| 8 | 2 |
| 9 | 0 |

All samples are above the Atlas v0.2 acceptance threshold.

### 2.3 Difficulty Mix

| Difficulty | Count | Purpose |
|---|---|---|
| 0 | 1 | Baseline agreement check |
| 1 | 8 | Standard training examples |
| 2 | 6 | Moderate ambiguity / wording judgment |
| 3 | 5 | Edge cases for calibration |

### 2.4 Source License Diversity

Samples include sources with licenses:
- Apache-2.0
- MIT
- CC-BY-4.0
- CC-BY-SA-4.0 (some GFDL)
- ODC-BY
- BigCode Open RAIL-M

This exposes reviewers to both permissive and restrictive source contexts.

---

## 3. Calibration Methodology

### 3.1 Review Execution

1. Reviewers complete all 20 calibration samples using `reviewer_guidelines.md`.
2. Each review produces one structured record with:
   - `reviewer_decision`
   - `reason`
   - `confidence`
   - `comments`

### 3.2 Agreement Measurement

Once reviews are complete, agreement will be computed as:

- **Exact agreement rate:** fraction of samples where all reviewers chose the same decision.
- **Within-1 quality agreement:** fraction of pairs where numeric quality scores differ by at most 1.
- **Cohen/Fleiss-style consistency:** categorical agreement on `approve` / `needs_revision` / `reject` / `ambiguous`.
- **Confidence calibration:** correlation between reviewer confidence and later observed stability.

Target thresholds:
- Exact agreement: **≥ 0.80**
- Within-1 agreement: **≥ 0.85**
- Decision-level F1-style consistency: **≥ 0.80**

If thresholds are not met, checklist wording will be revised and calibration rerun.

### 3.3 Disagreement Taxonomy

Disagreements will be tagged by theme:
1. **Completeness vs brevity** — short but correct answers.
2. **Clarity for training** — technically valid but ambiguous for SFT.
3. **Source trust / license flagging** — CC-BY-SA or RAIL-M source caution.
4. **Edge-case domain knowledge** — reviewers with different expertise diverge.
5. **Terminology** — acceptable shorthand vs imprecise wording.

---

## 4. Common Disagreement Patterns — Anticipated

Based on the selected samples, the following patterns are likely:

### 4.1 Short Prescriptive Answers
Several samples provide compact definitions like:
- "Stack: LIFO. Queue: FIFO."
- "Kubernetes: virtual clusters for isolation."

**Risk:** reviewers may mark `needs_revision` for brevity even when training-relevant.

**Guidance:** brevity alone is not grounds for rejection if the answer is technically correct and unambiguous.

### 4.2 License and Source Contextual Caution
Samples include:
- CC-BY-SA-4.0 (some GFDL)
- BigCode Open RAIL-M
- Research-only / verify licenses

**Risk:** reviewers may over-reject due to perceived provenance risk.

**Guidance:** flag for `needs_investigation` rather than reject unless a hard policy violation is confirmed.

### 4.3 Difficulty-3 Edge Cases
Difficulty 3 samples test judgment boundaries:
- Self-attention mechanism explanation
- QLoRA configuration statement
- Bare-metal vs RTOS distinction

**Risk:** higher disagreement due to implicit assumptions or audience level.

**Guidance:** reviewers should separate “answer is correct” from “answer is complete for all target audiences.”

### 4.4 QA Score vs Human Judgment
Automated `quality_score` is 7 for most samples, with one score 8.

**Risk:** reviewers may anchor on automated score or disagree with implied quality boundaries.

**Guidance:** judge content directly; avoid treating `quality_score` as ground truth.

---

## 5. Checklist Improvements (Pre-Review)

Before full review begins, the checklist should be updated to clarify:

1. **Brevity policy:** When is a short answer acceptable for Atlas training data?
2. **Ambiguity threshold:** What wording triggers `ambiguous` instead of `approve` or `needs_revision`?
3. **License handling:** When should `comments` reference `needs_investigation` versus changing decision?
4. **Confidence guidance:** What activates confidence `1-2` versus `3-5`?
5. **Edge-case documentation:** Should `difficulty >= 3` automatically require expanded notes?

These improvements will be incorporated into `review/v0.2/checklist.md` after calibration review results are available.

---

## 6. Review Guidance for Human Review Execution

### 6.1 Scope and Limitations
- Do not treat this calibration pass as production review.
- Do not modify `curated/v0.2/data/phase4b_expansion.jsonl` or review queues.
- Do not promote or reject Atlas v0.2 records during calibration.
- Release remains blocked until calibration is reviewed, guidance finalized, and a human owner authorizes release.

### 6.2 Calibration Review Sequence
1. All reviewers complete the 20 calibration samples independently.
2. Responses are collected under `review/calibration/v0.2/`.
3. Agreement metrics are computed.
4. Disagreements are classified by pattern.
5. Reviewer guidance and checklist are updated.
6. Calibration is declared **passed** or **needs rerun** before v0.2 review execution begins.

### 6.3 Escalation Criteria
Escalate to Atlas lead if:
- Exact agreement < 0.70 after calibration round.
- More than 25% of samples require re-review due to ambiguous guidance.
- Any disagreement uncovers a policy issue affecting release approval.

---

## 7. Verification Status

| Check | Status |
|---|---|
| Calibration samples are copies/references only | **PASS** |
| Original dataset unchanged | **PASS** |
| No approval decisions generated | **PASS** |
| v0.2 release remains blocked | **PASS** |

No human decisions exist in this calibration phase.
No production records were promoted, approved, or rejected.

---

## 8. Next Actions

1. Execute reviewer calibration using `review/calibration/v0.2/calibration_samples.jsonl`.
2. Collect structured reviews.
3. Compute agreement metrics.
4. Update `review/calibration/v0.2/calibration_report.md` with real results.
5. Finalize `review/v0.2/checklist.md` improvements.
6. Only after successful calibration, authorize v0.2 full human review.
