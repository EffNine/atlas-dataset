# Atlas Quality Calibration Report

- Date: 2026-07-27
- Reviews: 100 (matched: 100, missing candidates: 0)
- Accept threshold: quality_score >= 7

## Global Accuracy

- MAE: **0.18**  RMSE: **0.424**  Mean bias (auto-human): **0.14**
- Exact agreement: 82%   Within-1 agreement: **100%**
- Pearson r: None   Spearman rho: None
- Auto mean: 7.0   Human mean: 6.86
- Hallucination rate (human-flagged): 0%

### Accept/Reject Decision (threshold = 7)
- Confusion: TP=84 FP=16 TN=0 FN=0
- Precision: 0.840  Recall: 1.000  F1: **0.913**  Accuracy: 0.840

## Readiness Verdict

**READY_FOR_CALIBRATED_AUTO_REVIEW** — Auto-score agrees with humans within tolerance; bulk ingestion may proceed with stratum-level corrections + spot-check review.

## Bias by Category

| category | n | auto | human | bias | MAE | within-1 | F1 | conf | gate |
|---|---|---|---|---|---|---|---|---|---|
| 01_foundation | 10 | 7.0 | 7.1 | -0.1 | 0.3 | 1.0 | 0.947 | 0.967 | AUTO_ALLOWED |
| 02_software_engineering | 20 | 7.0 | 6.95 | 0.05 | 0.05 | 1.0 | 0.974 | 0.994 | AUTO_ALLOWED |
| 03_system_engineering | 15 | 7.0 | 7.0 | 0.0 | 0.0 | 1.0 | 1.0 | 1.0 | AUTO_ALLOWED |
| 04_ai_machine_learning | 20 | 7.0 | 6.8 | 0.2 | 0.2 | 1.0 | 0.889 | 0.978 | AUTO_ALLOWED |
| 05_hardware_engineering | 8 | 7.0 | 6.88 | 0.125 | 0.125 | 1.0 | 0.933 | 0.882 | AUTO_ALLOWED |
| 06_science_engineering | 10 | 7.0 | 6.6 | 0.4 | 0.4 | 1.0 | 0.75 | 0.956 | AUTO_ALLOWED |
| 07_business_knowledge | 7 | 7.0 | 6.71 | 0.286 | 0.286 | 1.0 | 0.833 | 0.81 | AUTO_ALLOWED |
| 08_creative_knowledge | 5 | 7.0 | 6.6 | 0.4 | 0.4 | 1.0 | 0.75 | 0.676 | AUTO_ALLOWED |
| 09_personal_assistant | 5 | 7.0 | 6.8 | 0.2 | 0.2 | 1.0 | 0.889 | 0.691 | AUTO_ALLOWED |

## Bias by Source

| source | n | auto | human | bias | MAE | F1 | conf | gate |
|---|---|---|---|---|---|---|---|---|
| b1 | 7 | 7.0 | 6.71 | 0.286 | 0.286 | 0.833 | 0.81 | AUTO_ALLOWED |
| c1 | 2 | 7.0 | 6.5 | 0.5 | 0.5 | 0.667 | 0.422 | MANDATORY_HUMAN_REVIEW |
| c2 | 3 | 7.0 | 6.67 | 0.333 | 0.333 | 0.8 | 0.527 | MANDATORY_HUMAN_REVIEW |
| c3 | 3 | 7.0 | 6.67 | 0.333 | 0.333 | 0.8 | 0.527 | MANDATORY_HUMAN_REVIEW |
| c6 | 2 | 7.0 | 6.5 | 0.5 | 0.5 | 0.667 | 0.422 | MANDATORY_HUMAN_REVIEW |
| f1 | 6 | 7.0 | 7.0 | 0.0 | 0.333 | 0.909 | 0.746 | AUTO_ALLOWED |
| f5 | 3 | 7.0 | 7.33 | -0.333 | 0.333 | 1.0 | 0.527 | MANDATORY_HUMAN_REVIEW |
| f6 | 6 | 7.0 | 6.83 | 0.167 | 0.167 | 0.909 | 0.76 | AUTO_ALLOWED |
| h1 | 4 | 7.0 | 7.0 | 0.0 | 0.0 | 1.0 | 0.632 | AUTO_ALLOWED |
| h2 | 4 | 7.0 | 6.75 | 0.25 | 0.25 | 0.857 | 0.615 | AUTO_ALLOWED |
| m2 | 10 | 7.0 | 6.9 | 0.1 | 0.1 | 0.947 | 0.989 | AUTO_ALLOWED |
| m3 | 10 | 7.0 | 6.7 | 0.3 | 0.3 | 0.824 | 0.967 | AUTO_ALLOWED |
| r1 | 5 | 7.0 | 6.6 | 0.4 | 0.4 | 0.75 | 0.676 | AUTO_ALLOWED |
| s1 | 5 | 7.0 | 6.8 | 0.2 | 0.2 | 0.889 | 0.691 | AUTO_ALLOWED |
| s4 | 5 | 7.0 | 7.0 | 0.0 | 0.0 | 1.0 | 0.707 | AUTO_ALLOWED |
| s5 | 5 | 7.0 | 7.0 | 0.0 | 0.0 | 1.0 | 0.707 | AUTO_ALLOWED |
| s6 | 5 | 7.0 | 7.0 | 0.0 | 0.0 | 1.0 | 0.707 | AUTO_ALLOWED |
| y2 | 5 | 7.0 | 7.0 | 0.0 | 0.0 | 1.0 | 0.707 | AUTO_ALLOWED |
| y3 | 5 | 7.0 | 7.0 | 0.0 | 0.0 | 1.0 | 0.707 | AUTO_ALLOWED |
| y4 | 5 | 7.0 | 7.0 | 0.0 | 0.0 | 1.0 | 0.707 | AUTO_ALLOWED |

## Bias by Dimension

| dimension | n | auto | human | bias | MAE | pearson_r |
|---|---|---|---|---|---|---|
| accuracy | 100 | 7.75 | 7.79 | -0.04 | 0.385 | None |
| completeness | 100 | 5.42 | 5.42 | -0.001 | 0.531 | 0.6 |
| technical_correctness | 100 | 6.49 | 6.55 | -0.06 | 0.496 | 0.702 |
| clarity | 100 | 9.08 | 8.96 | 0.117 | 0.262 | 0.585 |
| usefulness | 100 | 6.69 | 6.72 | -0.027 | 0.369 | 0.76 |
| originality | 100 | 8.05 | 8.11 | -0.059 | 0.491 | 0.93 |
| relevance | 100 | 6.73 | 6.78 | -0.047 | 0.494 | 0.958 |

## Recommendations

- **[MONITOR]** `category=01_foundation` correction=0.0 — bias=-0.1, confidence=0.967 within tolerance
- **[MONITOR]** `category=02_software_engineering` correction=0.0 — bias=0.05, confidence=0.994 within tolerance
- **[MONITOR]** `category=03_system_engineering` correction=0.0 — bias=0.0, confidence=1.0 within tolerance
- **[MONITOR]** `category=04_ai_machine_learning` correction=0.0 — bias=0.2, confidence=0.978 within tolerance
- **[MONITOR]** `category=05_hardware_engineering` correction=0.0 — bias=0.125, confidence=0.882 within tolerance
- **[MONITOR]** `category=06_science_engineering` correction=0.0 — bias=0.4, confidence=0.956 within tolerance
- **[MONITOR]** `category=07_business_knowledge` correction=0.0 — bias=0.286, confidence=0.81 within tolerance
- **[MONITOR]** `category=08_creative_knowledge` correction=0.0 — bias=0.4, confidence=0.676 within tolerance
- **[MONITOR]** `category=09_personal_assistant` correction=0.0 — bias=0.2, confidence=0.691 within tolerance
- **[MONITOR]** `source=b1` correction=0.0 — bias=0.286, confidence=0.81 within tolerance
- **[MANDATORY_HUMAN_REVIEW]** `source=c1` — confidence=0.422 (<0.6) or |bias|=0.5 or threshold_f1=0.667 < 0.70
- **[MANDATORY_HUMAN_REVIEW]** `source=c2` — confidence=0.527 (<0.6) or |bias|=0.333 or threshold_f1=0.8 < 0.70
- **[MANDATORY_HUMAN_REVIEW]** `source=c3` — confidence=0.527 (<0.6) or |bias|=0.333 or threshold_f1=0.8 < 0.70
- **[MANDATORY_HUMAN_REVIEW]** `source=c6` — confidence=0.422 (<0.6) or |bias|=0.5 or threshold_f1=0.667 < 0.70
- **[MONITOR]** `source=f1` correction=0.0 — bias=0.0, confidence=0.746 within tolerance
- **[MANDATORY_HUMAN_REVIEW]** `source=f5` — confidence=0.527 (<0.6) or |bias|=0.333 or threshold_f1=1.0 < 0.70
- **[MONITOR]** `source=f6` correction=0.0 — bias=0.167, confidence=0.76 within tolerance
- **[MONITOR]** `source=h1` correction=0.0 — bias=0.0, confidence=0.632 within tolerance
- **[MONITOR]** `source=h2` correction=0.0 — bias=0.25, confidence=0.615 within tolerance
- **[MONITOR]** `source=m2` correction=0.0 — bias=0.1, confidence=0.989 within tolerance
- **[MONITOR]** `source=m3` correction=0.0 — bias=0.3, confidence=0.967 within tolerance
- **[MONITOR]** `source=r1` correction=0.0 — bias=0.4, confidence=0.676 within tolerance
- **[MONITOR]** `source=s1` correction=0.0 — bias=0.2, confidence=0.691 within tolerance
- **[MONITOR]** `source=s4` correction=0.0 — bias=0.0, confidence=0.707 within tolerance
- **[MONITOR]** `source=s5` correction=0.0 — bias=0.0, confidence=0.707 within tolerance
- **[MONITOR]** `source=s6` correction=0.0 — bias=0.0, confidence=0.707 within tolerance
- **[MONITOR]** `source=y2` correction=0.0 — bias=0.0, confidence=0.707 within tolerance
- **[MONITOR]** `source=y3` correction=0.0 — bias=0.0, confidence=0.707 within tolerance
- **[MONITOR]** `source=y4` correction=0.0 — bias=0.0, confidence=0.707 within tolerance

## Top Disagreements (review-priority)

| record_id | category | source | auto | human | diff | verdict |
|---|---|---|---|---|---|---|
| 01_foundation_general-reasoning_0001 | 01_foundation | f6 | 7 | 6 | +1 | needs_revision |
| 01_foundation_problem-solving_0003 | 01_foundation | f1 | 7 | 8 | -1 | approve |
| 01_foundation_instruction-following_0008 | 01_foundation | f5 | 7 | 8 | -1 | approve |
| 02_software_engineering_software-architecture_0012 | 02_software_engineering | s1 | 7 | 6 | +1 | needs_revision |
| 04_ai_machine_learning_transformers_0045 | 04_ai_machine_learning | m3 | 7 | 6 | +1 | needs_revision |
| 04_ai_machine_learning_transformers_0051 | 04_ai_machine_learning | m3 | 7 | 6 | +1 | needs_revision |
| 04_ai_machine_learning_deep-learning_0056 | 04_ai_machine_learning | m2 | 7 | 6 | +1 | needs_revision |
| 04_ai_machine_learning_transformers_0061 | 04_ai_machine_learning | m3 | 7 | 6 | +1 | needs_revision |
| 06_science_engineering_electronics_0067 | 06_science_engineering | c6 | 7 | 6 | +1 | needs_revision |
| 06_science_engineering_engineering-concepts_0068 | 06_science_engineering | c1 | 7 | 6 | +1 | needs_revision |
| 06_science_engineering_mathematics_0069 | 06_science_engineering | c2 | 7 | 6 | +1 | needs_revision |
| 06_science_engineering_physics_0074 | 06_science_engineering | c3 | 7 | 6 | +1 | needs_revision |
| 05_hardware_engineering_embedded-systems_0082 | 05_hardware_engineering | h2 | 7 | 6 | +1 | needs_revision |
| 07_business_knowledge_strategy_0085 | 07_business_knowledge | b1 | 7 | 6 | +1 | needs_revision |
| 07_business_knowledge_strategy_0089 | 07_business_knowledge | b1 | 7 | 6 | +1 | needs_revision |
