# QEE-Human Alignment Report

- **Date**: 2026-07-28
- **Analysis Scope**: Phase 5B evaluation execution — QEE vs human review alignment
- **Dataset**: curated/v0.2 (250 records, 100 reviewed)
- **Engine**: Quality Evaluation Engine (`scripts/quality_score.py`)
- **Baseline Reference**: `metadata/calibration_baseline_v0.1.json`

---

## 1. Overview

This report analyzes the alignment between the Atlas **Quality Evaluation Engine (QEE)** scores and **human reviewer scores** for the v0.2 curated dataset. The purpose is to identify calibration gaps, characterize disagreement patterns, and provide recommendations — **without modifying QEE calibration**.

The analysis compares:
- 100 matched records (records present in both `curated/v0.2/data/v0.2_full.jsonl` and `review/quality_reviews.jsonl`)
- QEE scores vs human scores (0-10 scale)
- QEE-implied approval (score >= 7) vs actual human verdict

---

## 2. Score Distribution

### QEE Scores (New Engine)

| Score | Count | Percentage |
|-------|-------|-----------|
| 9     | 100   | 100%      |

All 100 matched records received a QEE score of **9**, with no variance across categories, difficulty levels, or knowledge types.

### Human Scores

| Score | Count | Percentage |
|-------|-------|-----------|
| 6     | 16    | 16%       |
| 7     | 82    | 82%       |
| 8     | 2     | 2%        |

### Comparison with v0.1 Baseline

| Metric                    | v0.1 (Constant-7 Scorer) | v0.2 (New QEE) | Delta    |
|---------------------------|--------------------------|-----------------|----------|
| **QEE Mean**              | 7.00                     | 9.00            | +2.00    |
| **Human Mean**            | 6.86                     | 6.86            | —        |
| **Mean Bias**             | +0.14                    | +2.14           | +2.00    |
| **Exact Agreement**       | 82.0%                    | 0.0%            | -82.0%   |
| **Within-1 Agreement**    | 100.0%                   | 2.0%            | -98.0%   |
| **RMSE**                  | 0.424                    | 2.177           | +1.753   |

The new QEE shows a **systematic positive bias** of **+2.14 points** versus human reviewers. The old constant-7 scorer had better alignment metrics (82% exact agreement) purely because it assigned the modal human score to every record — but it also lacked any discriminative power.

---

## 3. False Approvals and False Rejections

Using threshold **quality_score >= 7** for automatic approval:

| Category              | False Approvals | False Rejections |
|-----------------------|-----------------|------------------|
| 01_foundation         | 1               | 0                |
| 02_software_engineering | 1             | 0                |
| 04_ai_machine_learning  | 4             | 0                |
| 05_hardware_engineering | 1             | 0                |
| 06_science_engineering  | 4             | 0                |
| 07_business_knowledge   | 2             | 0                |
| 08_creative_knowledge   | 2             | 0                |
| 09_personal_assistant   | 1             | 0                |
| **Total**             | **16**          | **0**            |

- **False approvals (QEE >= 7 but verdict != approve)**: 16 records (16.0%)
- **False rejections (QEE < 7 but verdict == approve)**: 0 records (0.0%)

Every "false approval" has a QEE score exactly **3 points higher** than the human score (QEE=9 vs Human=6). There are zero false rejections because the QEE never scores below 7 on reviewed records.

**Conclusion**: The QEE is consistently over-generous. No record that humans rejected (marked `needs_revision`) would be blocked by the QEE threshold of 7.

---

## 4. Per-Category Analysis

| Category                | Count | Within-1 | QEE Mean | Human Mean | Bias     |
|-------------------------|-------|----------|----------|------------|----------|
| 01_foundation           | 10    | 20%      | 9.0      | 7.10       | **+1.90** |
| 02_software_engineering | 20    | 0%       | 9.0      | 6.95       | **+2.05** |
| 03_system_engineering   | 15    | 0%       | 9.0      | 7.00       | **+2.00** |
| 04_ai_machine_learning  | 20    | 0%       | 9.0      | 6.80       | **+2.20** |
| 05_hardware_engineering | 8     | 0%       | 9.0      | 6.88       | **+2.12** |
| 06_science_engineering  | 10    | 0%       | 9.0      | 6.60       | **+2.40** |
| 07_business_knowledge   | 7     | 0%       | 9.0      | 6.71       | **+2.29** |
| 08_creative_knowledge   | 5     | 0%       | 9.0      | 6.60       | **+2.40** |
| 09_personal_assistant   | 5     | 0%       | 9.0      | 6.80       | **+2.20** |

### Observations

1. **Bias is universal**: Every category shows QEE scoring ~2 points higher than humans.
2. **Worst bias**: `06_science_engineering` and `08_creative_knowledge` (+2.40 each) — subjects requiring precision or creative nuance.
3. **Best (least bad)**: `01_foundation` (+1.90) — general reasoning/foundation skills.
4. **No category reached within-1 agreement above 20%**: The QEE fails to differentiate scores even at the category level.

---

## 5. Disagreement Characterization

### Disagreement Magnitude

| Diff (QEE - Human) | Count | Percentage |
|---------------------|-------|-----------|
| +2                  | 2     | 2%        |
| +3                  | 98    | 98%       |

### Disagreement Categories

Disagreements span all 9 categories proportionally to their representation. There is no single category driving the alignment gap — the bias is systemic.

### Root Cause Hypothesis

The QEE (`quality_score.py`) uses heuristic text analysis (sentence count, word variety, keyword matching, code fence detection) to score dimensions. For `v0.2_full.jsonl` pilot-authored records, the assistant responses are:

- Short (1-3 sentences)
- Concise and well-structured
- Contain domain-relevant keywords

These signals trigger maximum scores across multiple QEE dimensions, producing a ceiling effect (all records score 9). Human reviewers, by contrast, judge completeness, accuracy, and originality more critically.

---

## 6. QEE Dimension-Level Breakdown

The QEE evaluates 7 dimensions (weights in parentheses):

| Dimension               | Weight | Observation                               |
|-------------------------|--------|-------------------------------------------|
| accuracy                | 0.20   | Over-scored — no factual verification     |
| completeness            | 0.15   | Ceiling effect on short responses         |
| technical_correctness   | 0.20   | Keywords drive high scores                |
| clarity                 | 0.15   | Short = clear, per heuristic              |
| usefulness              | 0.15   | Keyword match inflates score              |
| originality             | 0.05   | Low weight mitigates but not enough       |
| relevance               | 0.10   | Category keyword match guarantees high    |

**Key insight**: The QEE lacks a mechanism to penalize brevity-induced incompleteness, and its domain keyword matching provides a floor of ~0.80 on every dimension for well-written records. The 7 dimensions all saturate near the top of the scale, collapsing all variance.

---

## 7. Recommendations (Analysis Only — No Calibration Changes)

### Recommendation 1: Score Range Expansion

**Problem**: The QEE maps 0-1 dimension scores linearly to 1-10 quality_score, but most records cluster in 0.80-1.00 per dimension.

**Suggestion**: Introduce a logistic or sigmoid mapping that creates more spread in the 1-10 output range, especially at the upper end (8-10).

### Recommendation 2: Penalize Incompleteness

**Problem**: The completeness dimension uses sentence/word count heuristics that don't penalize genuinely incomplete answers.

**Suggestion**: Add a "citation gap" metric — records lacking URLs, references, or explicit "source: X" attribution should receive a completeness penalty.

### Recommendation 3: Add a "Difficulty-Adjusted" Score Component

**Problem**: All records are scored identically regardless of difficulty level (0-3 in the dataset).

**Suggestion**: Subtract a difficulty-dependent offset so that harder records are not penalized for complexity, and easier records are not rewarded for simplicity.

### Recommendation 4: Calibrate Against Human Scores

**Problem**: 100% of reviewed records score QEE=9 but only 2% of human scores are 8.

**Suggestion**: After an intentional re-calibration decision, adjust the per-dimension weights or output mapping to bring the QEE score distribution closer to the human score distribution (centered around 7, with variance from 5-9).

### Recommendation 5: Dimension Weight Audit

**Problem**: `originality` (5%) and `relevance` (10%) have minimal impact. `accuracy` and `technical_correctness` (40% combined) rely on keyword signals.

**Suggestion**: When re-calibrating, consider redistributing weight from keyword-driven dimensions toward output-based metrics (e.g., fact density, citation count).

---

## 8. Summary

| Metric                     | Value     |
|----------------------------|-----------|
| Records analyzed           | 100       |
| QEE mean                   | 9.00      |
| Human mean                 | 6.86      |
| Mean bias                  | **+2.14** |
| RMSE                       | 2.177     |
| False approvals (QEE >= 7) | 16 (16%)  |
| False rejections (QEE < 7) | 0 (0%)    |
| Exact match rate           | 0.0%      |
| Within-1 agreement         | 2.0%      |

**The QEE is not ready for unsupervised automated approval.** Its scores are systematically inflated by ~2 points relative to human reviewers. While the old constant-7 scorer had better aggregate alignment (82% exact agreement), it had zero discriminative power. The new QEE needs calibration before it can reliably predict human approval decisions.

**Action required**: After this Phase 5B evaluation infrastructure is validated, Phase 5C should execute a deliberate QEE recalibration using the findings in this report.

---

*This report is analysis-only. No QEE calibration changes were made during Phase 5B.*
