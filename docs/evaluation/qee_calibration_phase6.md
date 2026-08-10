# QEE v2 Calibration Report — Phase 6.3

> **Phase:** 6.3
> **Status:** COMPLETE
> **Date:** 2026-08-04
> **Objective:** Validate that the Phase 6.2 expanded evaluation sets and QEE v2
> scores align with human judgement.
> **Constraints honored:** No model training. No dataset/training-view
> modification. No QEE scoring-logic change.

---

## 1. Methodology

### 1.1 Baseline evaluation

- **Model:** Qwen2.5-7B-Instruct (NF4 4-bit + double quant, bf16 compute,
  greedy decoding, max_new_tokens=512)
- **Sets:** `math_eval_v1` (N=100), `code_eval_v1` (N=100) — Phase 6.2 expansion
- **Engine:** QEE v2 (`scripts/evaluation_engine/v2/`), authoritative `view_id`
  dispatch (math-300m → math, code-300m → code)
- **Outputs:** `experiments/phase6_baseline_eval/` (`baseline.json`,
  `per_example_results.jsonl`, `config.json`, `hardware_info.json`)

### 1.2 Human calibration set

- **Size:** 60 samples (30 math + 30 code)
- **Selection:** deterministic random shuffle, seeded (`20260804`); provenance
  preserved (record_id, original_id, source, difficulty, category); asserted
  **no training-view overlap** (eval sets are train-disjoint by construction,
  re-verified at build time).
- **File:** `experiments/phase6_baseline_eval/human_review_calibration_set.json`
- **Label source:** AI-reviewer proxy
  (`ai-reviewer:hermes/deepseek-v4-flash`), reviewing the model's predicted
  response against the reference answer on a 0-10 correctness scale with an
  approve/reject verdict (≥ 7 = approve). **This is a proxy for human
  judgement, not human review itself** — see §5 limitations.

### 1.3 Comparison

Per family and combined: Pearson correlation, MAE, bias (QEE − human), and
threshold agreement at approve/reject (≥ 7), plus disagreement-case listing.

---

## 2. Baseline Results (QEE v2, N=200)

| Family | Correctness | Reasoning quality | Hallucination rate | N |
|--------|-------------|-------------------|--------------------|---|
| Math | 0.7629 | 0.7828 | 0.23 | 100 |
| Code | 0.2217 | 0.4169 | 0.76 | 100 |
| **Overall** | **0.4923** | **0.5998** | **0.495** | **200** |

---

## 3. QEE v2 vs Human (proxy) Labels — Results

### 3.1 Combined (N=60)

| Metric | Value |
|--------|-------|
| QEE mean | 6.82 |
| Human mean | 6.35 |
| **Bias (QEE − human)** | **+0.47** |
| **MAE** | **1.00** |
| **Pearson correlation** | **0.929** |
| Threshold agreement (≥ 7) | 96.7% |
| False approvals | 0 |
| False rejections | 2 |

### 3.2 By family

| Family | N | Pearson | MAE | Bias | Agreement | False appr. | False rej. |
|--------|---|---------|-----|------|-----------|-------------|-----------|
| Math | 30 | 0.710 | 1.47 | +0.87 | 93.3% | 0 | 2 |
| Code | 30 | 0.949 | 0.53 | +0.07 | 100.0% | 0 | 0 |

### 3.3 Reading of the numbers

- **Code alignment is excellent** (ρ=0.95, MAE=0.53, bias≈0, 100% threshold
  agreement). QEE v2 code scoring tracks reviewer judgement closely.
- **Math alignment is good but imperfect** (ρ=0.71, MAE=1.47, +0.87 bias).
  The positive bias is driven by QEE assigning 10/10 to 26/30 samples while
  reviewers scored 8–9; the two false rejections are extraction failures (see
  §4).
- **Overall**, QEE v2 shows a small positive bias (+0.47) and near-zero false
  approvals — it does **not** under-block correct answers, but it does
  occasionally under-score a correct math answer.

---

## 4. Disagreement Cases (abs diff ≥ 4)

Both disagreements are **math false rejections** where the model's answer is
correct but QEE could not parse it:

| record_id | QEE quality | Human score | Cause |
|-----------|-------------|-------------|-------|
| `expert_math_001478` | 3 | 9 | Model answered `49` (correct); QEE `method=unparsable` — no boxed/parseable form extracted |
| `expert_math_002244` | 6 | 8 | Model answered `36%` (correct); QEE `method=unparsable` — `%` in `\boxed{36\%}` not parsed |

**Root cause:** QEE v2's math extractor still fails on a small class of final
answers (e.g. percentages, certain formatting). These are correct answers that
would be wrongly blocked at a ≥ 7 gate. **No false approvals occurred**, so QEE
does not over-approve wrong answers in this sample.

---

## 5. Limitations

1. **Proxy labels, not true human review.** Labels were assigned by an
   AI-reviewer (`ai-reviewer:hermes/deepseek-v4-flash`) approximating human
   judgement, consistent with the project's prior expert-pilot review pattern.
   Real human reviewers may differ; a formal human review pass on the 60-sample
   set is required before the calibration numbers are treated as definitive.
2. **Sample size is small** (30/family). Correlations carry wide confidence
   intervals; code's 100% agreement is partly because most code samples score
   low in both QEE and human (low-variance region).
3. **Baseline model only.** Alignment was measured on a single model
   (Qwen2.5-7B-Instruct, no adapter). LoRA post-training scores are not part of
   this calibration.
4. **Threshold at 7 is arbitrary** and was not tuned; it is the project's
   existing quality threshold.
5. **Math extraction edge-cases persist** (§4) and should be addressed in the
   evaluator before the gate is used to block answers.
6. **No QEE scoring logic was changed** during this phase; all calibration is
   measurement, not re-scoring.

---

## 6. Recommendation

**Do not authorize automated gating.** Human approval remains mandatory for any
release or training decision. Specifically:

1. **QEE v2 is ready for assisted (human-in-the-loop) screening**, not
   unsupervised approval: strong correlation (ρ=0.93) and near-zero false
   approvals make it a good *prioritization* signal, but the two math false
   rejections show it can still wrongly block correct answers.
2. **Fix the math extractor edge-cases** (percentages `%`, non-`\boxed`
   answers) — the exact pattern from Phase 5A.4's nested-brace fix, now for
   `%`/units formatting — before any ≥ 7 automated gate on math.
3. **Conduct a formal human review** of the 60-sample calibration set to replace
   the proxy labels and confirm the calibration statistics.
4. **Maintain human approval** for all release/training gates (per Atlas
   governance); QEE v2 informs, it does not decide.
5. **Extend calibration** to the other 140 non-calibration eval records and to
   LoRA post-training outputs once the extractor edge-cases are resolved.

---

## 7. Artifacts

| Artifact | Path |
|----------|------|
| Baseline JSON | `experiments/phase6_baseline_eval/baseline.json` |
| Per-example results | `experiments/phase6_baseline_eval/per_example_results.jsonl` |
| Human calibration set | `experiments/phase6_baseline_eval/human_review_calibration_set.json` |
| QEE-vs-human analysis | `experiments/phase6_baseline_eval/qee_vs_human.json` |
| Baseline runner | `experiments/phase6_baseline_eval/run_phase6_baseline_eval.py` |
| Calibration-set builder | `scripts/evaluation_engine/build_human_calibration_set.py` |
| Comparison script | `scripts/evaluation_engine/qee_vs_human_phase6.py` |
