# Atlas Quality Calibration Report

- Date: 2026-07-27
- Reviews: 30 (matched: 30, missing candidates: 0)
- Accept threshold: quality_score >= 7

## Global Accuracy

- MAE: **0.7**  RMSE: **1.049**  Mean bias (auto-human): **-0.1**
- Exact agreement: 47%   Within-1 agreement: **87%**
- Pearson r: None   Spearman rho: None
- Auto mean: 7.0   Human mean: 7.1
- Hallucination rate (human-flagged): 13%

### Accept/Reject Decision (threshold = 7)
- Confusion: TP=22 FP=8 TN=0 FN=0
- Precision: 0.733  Recall: 1.000  F1: **0.846**  Accuracy: 0.733

## Readiness Verdict

**REQUIRES_HUMAN_REVIEW** — Moderate agreement: auto-score usable for triage only; every promotion to curated/ needs human review. Do NOT bulk-ingest on auto-score alone.

## Bias by Category

| category | n | auto | human | bias | MAE | within-1 | F1 | conf | gate |
|---|---|---|---|---|---|---|---|---|---|
| 01_foundation | 3 | 7.0 | 6.67 | 0.333 | 0.333 | 1.0 | 0.8 | 0.527 | MANDATORY_HUMAN_REVIEW |
| 02_software_engineering | 6 | 7.0 | 7.0 | 0.0 | 0.0 | 1.0 | 1.0 | 0.775 | AUTO_ALLOWED |
| 03_system_engineering | 4 | 7.0 | 7.5 | -0.5 | 1.0 | 0.75 | 0.857 | 0.562 | MANDATORY_HUMAN_REVIEW |
| 04_ai_machine_learning | 6 | 7.0 | 7.0 | 0.0 | 0.667 | 1.0 | 0.8 | 0.717 | AUTO_ALLOWED |
| 05_hardware_engineering | 2 | 7.0 | 7.0 | 0.0 | 1.0 | 1.0 | 0.667 | 0.398 | MANDATORY_HUMAN_REVIEW |
| 06_science_engineering | 3 | 7.0 | 6.33 | 0.667 | 0.667 | 1.0 | 0.5 | 0.507 | MANDATORY_HUMAN_REVIEW |
| 07_business_knowledge | 2 | 7.0 | 6.0 | 1.0 | 1.0 | 0.5 | 0.667 | 0.398 | MANDATORY_HUMAN_REVIEW |
| 08_creative_knowledge | 2 | 7.0 | 9.5 | -2.5 | 2.5 | 0.0 | 1.0 | 0.323 | MANDATORY_HUMAN_REVIEW |
| 09_personal_assistant | 2 | 7.0 | 7.5 | -0.5 | 0.5 | 1.0 | 1.0 | 0.422 | MANDATORY_HUMAN_REVIEW |

## Bias by Source

| source | n | auto | human | bias | MAE | F1 | conf | gate |
|---|---|---|---|---|---|---|---|---|
| b1 | 2 | 7.0 | 6.0 | 1.0 | 1.0 | 0.667 | 0.398 | MANDATORY_HUMAN_REVIEW |
| c1 | 1 | 7.0 | 7.0 | 0.0 | 0.0 | 1.0 | 0.316 | MANDATORY_HUMAN_REVIEW |
| c2 | 1 | 7.0 | 6.0 | 1.0 | 1.0 | 0.0 | 0.281 | MANDATORY_HUMAN_REVIEW |
| c6 | 1 | 7.0 | 6.0 | 1.0 | 1.0 | 0.0 | 0.281 | MANDATORY_HUMAN_REVIEW |
| f1 | 2 | 7.0 | 7.0 | 0.0 | 0.0 | 1.0 | 0.447 | MANDATORY_HUMAN_REVIEW |
| f5 | 1 | 7.0 | 6.0 | 1.0 | 1.0 | 0.0 | 0.281 | MANDATORY_HUMAN_REVIEW |
| f6 | 2 | 7.0 | 7.5 | -0.5 | 0.5 | 1.0 | 0.422 | MANDATORY_HUMAN_REVIEW |
| h1 | 1 | 7.0 | 6.0 | 1.0 | 1.0 | 0.0 | 0.281 | MANDATORY_HUMAN_REVIEW |
| h2 | 1 | 7.0 | 8.0 | -1.0 | 1.0 | 1.0 | 0.281 | MANDATORY_HUMAN_REVIEW |
| m2 | 1 | 7.0 | 7.0 | 0.0 | 0.0 | 1.0 | 0.316 | MANDATORY_HUMAN_REVIEW |
| m3 | 5 | 7.0 | 7.0 | 0.0 | 0.8 | 0.75 | 0.644 | AUTO_ALLOWED |
| r1 | 2 | 7.0 | 9.5 | -2.5 | 2.5 | 1.0 | 0.323 | MANDATORY_HUMAN_REVIEW |
| s1 | 1 | 7.0 | 7.0 | 0.0 | 0.0 | 1.0 | 0.316 | MANDATORY_HUMAN_REVIEW |
| s4 | 1 | 7.0 | 7.0 | 0.0 | 0.0 | 1.0 | 0.316 | MANDATORY_HUMAN_REVIEW |
| s5 | 2 | 7.0 | 7.0 | 0.0 | 0.0 | 1.0 | 0.447 | MANDATORY_HUMAN_REVIEW |
| s6 | 2 | 7.0 | 7.0 | 0.0 | 0.0 | 1.0 | 0.447 | MANDATORY_HUMAN_REVIEW |
| y3 | 3 | 7.0 | 7.0 | 0.0 | 0.667 | 0.8 | 0.507 | MANDATORY_HUMAN_REVIEW |
| y4 | 1 | 7.0 | 9.0 | -2.0 | 2.0 | 1.0 | 0.246 | MANDATORY_HUMAN_REVIEW |

## Bias by Dimension

| dimension | n | auto | human | bias | MAE | pearson_r |
|---|---|---|---|---|---|---|
| accuracy | 30 | 7.75 | 8.0 | -0.25 | 0.733 | None |
| completeness | 30 | 5.5 | 5.97 | -0.467 | 0.833 | None |
| technical_correctness | 30 | 6.48 | 6.27 | 0.208 | 0.765 | 0.509 |
| clarity | 30 | 9.1 | 8.73 | 0.367 | 0.667 | 0.0 |
| usefulness | 30 | 6.7 | 7.03 | -0.333 | 0.617 | 0.49 |
| originality | 30 | 8.13 | 8.8 | -0.675 | 0.762 | 0.859 |
| relevance | 30 | 7.23 | 6.93 | 0.292 | 0.675 | 0.884 |

## Recommendations

- **[MANDATORY_HUMAN_REVIEW]** `category=01_foundation` — confidence=0.527 (<0.6) or |bias|=0.333 or threshold_f1=0.8 < 0.70
- **[MONITOR]** `category=02_software_engineering` correction=0.0 — bias=0.0, confidence=0.775 within tolerance
- **[MANDATORY_HUMAN_REVIEW]** `category=03_system_engineering` — confidence=0.562 (<0.6) or |bias|=0.5 or threshold_f1=0.857 < 0.70
- **[MONITOR]** `category=04_ai_machine_learning` correction=0.0 — bias=0.0, confidence=0.717 within tolerance
- **[MANDATORY_HUMAN_REVIEW]** `category=05_hardware_engineering` — confidence=0.398 (<0.6) or |bias|=0.0 or threshold_f1=0.667 < 0.70
- **[MANDATORY_HUMAN_REVIEW]** `category=06_science_engineering` — confidence=0.507 (<0.6) or |bias|=0.667 or threshold_f1=0.5 < 0.70
- **[MANDATORY_HUMAN_REVIEW]** `category=07_business_knowledge` — confidence=0.398 (<0.6) or |bias|=1.0 or threshold_f1=0.667 < 0.70
- **[MANDATORY_HUMAN_REVIEW]** `category=08_creative_knowledge` — confidence=0.323 (<0.6) or |bias|=2.5 or threshold_f1=1.0 < 0.70
- **[MANDATORY_HUMAN_REVIEW]** `category=09_personal_assistant` — confidence=0.422 (<0.6) or |bias|=0.5 or threshold_f1=1.0 < 0.70
- **[MANDATORY_HUMAN_REVIEW]** `source=b1` — confidence=0.398 (<0.6) or |bias|=1.0 or threshold_f1=0.667 < 0.70
- **[MANDATORY_HUMAN_REVIEW]** `source=c1` — confidence=0.316 (<0.6) or |bias|=0.0 or threshold_f1=1.0 < 0.70
- **[MANDATORY_HUMAN_REVIEW]** `source=c2` — confidence=0.281 (<0.6) or |bias|=1.0 or threshold_f1=0.0 < 0.70
- **[MANDATORY_HUMAN_REVIEW]** `source=c6` — confidence=0.281 (<0.6) or |bias|=1.0 or threshold_f1=0.0 < 0.70
- **[MANDATORY_HUMAN_REVIEW]** `source=f1` — confidence=0.447 (<0.6) or |bias|=0.0 or threshold_f1=1.0 < 0.70
- **[MANDATORY_HUMAN_REVIEW]** `source=f5` — confidence=0.281 (<0.6) or |bias|=1.0 or threshold_f1=0.0 < 0.70
- **[MANDATORY_HUMAN_REVIEW]** `source=f6` — confidence=0.422 (<0.6) or |bias|=0.5 or threshold_f1=1.0 < 0.70
- **[MANDATORY_HUMAN_REVIEW]** `source=h1` — confidence=0.281 (<0.6) or |bias|=1.0 or threshold_f1=0.0 < 0.70
- **[MANDATORY_HUMAN_REVIEW]** `source=h2` — confidence=0.281 (<0.6) or |bias|=1.0 or threshold_f1=1.0 < 0.70
- **[MANDATORY_HUMAN_REVIEW]** `source=m2` — confidence=0.316 (<0.6) or |bias|=0.0 or threshold_f1=1.0 < 0.70
- **[MONITOR]** `source=m3` correction=0.0 — bias=0.0, confidence=0.644 within tolerance
- **[MANDATORY_HUMAN_REVIEW]** `source=r1` — confidence=0.323 (<0.6) or |bias|=2.5 or threshold_f1=1.0 < 0.70
- **[MANDATORY_HUMAN_REVIEW]** `source=s1` — confidence=0.316 (<0.6) or |bias|=0.0 or threshold_f1=1.0 < 0.70
- **[MANDATORY_HUMAN_REVIEW]** `source=s4` — confidence=0.316 (<0.6) or |bias|=0.0 or threshold_f1=1.0 < 0.70
- **[MANDATORY_HUMAN_REVIEW]** `source=s5` — confidence=0.447 (<0.6) or |bias|=0.0 or threshold_f1=1.0 < 0.70
- **[MANDATORY_HUMAN_REVIEW]** `source=s6` — confidence=0.447 (<0.6) or |bias|=0.0 or threshold_f1=1.0 < 0.70
- **[MANDATORY_HUMAN_REVIEW]** `source=y3` — confidence=0.507 (<0.6) or |bias|=0.0 or threshold_f1=0.8 < 0.70
- **[MANDATORY_HUMAN_REVIEW]** `source=y4` — confidence=0.246 (<0.6) or |bias|=2.0 or threshold_f1=1.0 < 0.70

## Top Disagreements (review-priority)

| record_id | category | source | auto | human | diff | verdict |
|---|---|---|---|---|---|---|
| 08_creative_knowledge_storytelling_0091 | 08_creative_knowledge | r1 | 7 | 10 | -3 | accept |
| 03_system_engineering_performance-tuning_0035 | 03_system_engineering | y4 | 7 | 9 | -2 | accept |
| 07_business_knowledge_strategy_0089 | 07_business_knowledge | b1 | 7 | 5 | +2 | revise |
| 08_creative_knowledge_design_0092 | 08_creative_knowledge | r1 | 7 | 9 | -2 | accept |
| 01_foundation_instruction-following_0008 | 01_foundation | f5 | 7 | 6 | +1 | revise |
| 03_system_engineering_docker_0037 | 03_system_engineering | y3 | 7 | 8 | -1 | accept |
| 03_system_engineering_docker_0043 | 03_system_engineering | y3 | 7 | 6 | +1 | revise |
| 04_ai_machine_learning_llm_0059 | 04_ai_machine_learning | m3 | 7 | 8 | -1 | accept |
| 04_ai_machine_learning_mlops_0055 | 04_ai_machine_learning | m3 | 7 | 6 | +1 | revise |
| 04_ai_machine_learning_mlops_0057 | 04_ai_machine_learning | m3 | 7 | 6 | +1 | revise |
| 04_ai_machine_learning_rag_0047 | 04_ai_machine_learning | m3 | 7 | 8 | -1 | accept |
| 05_hardware_engineering_cpu_0075 | 05_hardware_engineering | h1 | 7 | 6 | +1 | revise |
| 05_hardware_engineering_gpu_0076 | 05_hardware_engineering | h2 | 7 | 8 | -1 | accept |
| 06_science_engineering_electronics_0067 | 06_science_engineering | c6 | 7 | 6 | +1 | revise |
| 06_science_engineering_engineering-concepts_0073 | 06_science_engineering | c2 | 7 | 6 | +1 | revise |
