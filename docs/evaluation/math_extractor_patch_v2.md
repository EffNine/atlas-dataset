# Math Evaluator Edge-Case Patch — v2 (Phase 6.4)

> **Phase:** 6.4
> **Status:** COMPLETE
> **Date:** 2026-08-04
> **Objective:** Fix remaining math evaluation extraction/normalization gaps
> identified during Phase 6.3 QEE calibration.
> **Constraints honored:** No model training. No dataset/training-view
> modification. No change to evaluation philosophy (extraction + normalization
> only; numeric-equivalence scoring logic untouched).

---

## 1. Root cause

Phase 6.3 calibration found **2 false rejections** — correct math answers that
QEE v2 scored as unparsable and would wrongly block at a ≥ 7 gate:

| record_id | Model answer | QEE before | Cause |
|-----------|--------------|-----------|-------|
| `expert_math_001478` | `49` | 0.0 / quality 3 | Candidate had **no `\boxed{}`**; the "last `=` RHS" extractor returned `49\)` with a trailing LaTeX inline-math closer `\)`, which failed to parse |
| `expert_math_002244` | `36%` | 0.5 / quality 6 | `\boxed{36\%}` extracted to `36\%`; the LaTeX `\%` was never normalized, so parsing failed |

Both are **normalization** gaps, not scoring-philosophy gaps. The numeric
equivalence engine already works; the inputs it received were malformed.

---

## 2. Changes (`scripts/evaluation_engine/v2/normalize.py`)

No change to `math_eval.py` scoring logic. All fixes are in normalization.

### 2.1 LaTeX delimiter residue (`strip_latex_noise`)
- Inline math delimiters `\(` / `\)` and display `\[` / `\]` are now **removed
  entirely** (they are delimiters, not grouping). Previously `\)` became `)`,
  producing unbalanced `49)` → unparsable.
- `\%` → `%` so percentage answers parse.

### 2.2 Percentage answers (`normalize_numeric`)
- `%` attached to a number → `/100`: `36%` ≡ `0.36` ≡ `36/100` ≡ `9/25`.
- Spoken `"percent"` / `"per cent"` → `/100` (via `spoken_to_symbolic`), so
  `36 percent` ≡ `36%`.

### 2.3 Unit normalization (`normalize_numeric`)
- Unit words stripped for dimensionless numeric comparison: `seconds`, `sec`,
  `meters`, `metres`, `m`, `km`, `cm`, `mm`, `degrees`, `deg`, `radians`, `rad`.
- Degree/prime symbols `° ˚ º` removed → `90°` ≡ `90`.
- `m` is only stripped as a standalone word token (word-boundary), so `2m+3`
  (variable) is untouched.

### 2.4 Numeric formatting (`normalize_numeric`)
- Thousands separators removed (`1,000` → `1000`, `1,234,567` → `1234567`),
  **preserving coordinate tuples** `(-3,0)` (comma must be followed by exactly
  3 digits to be treated as a separator).
- Scientific notation case normalized (`2.5E3` → `2.5e3`).
- Trailing zeros preserved for decimal equivalence (`3.5` ≡ `3.50`).

---

## 3. Regression tests added

`tests/evaluation_v2/test_math_eval.py` — new class
`TestPercentAndUnitNormalization` (27 new assertions):

- **Previous false rejections:** `("49", r"49\)")`, `\boxed{36\%}` equivalence,
  plus the two full real predicted/reference response pairs → now `correct=True`.
- **Equivalent answers (parametrized):** percentages (`49%`/`0.49`/`49/100`,
  `36%`/`9/25`, `36 percent`/`36%`), units (`5 meters`/`5`, `5 m`/`5 meters`,
  `90°`/`90`, `12 seconds`/`12 sec`), numeric formatting (`1,000`/`1000`,
  `2.5E3`/`2500`, `3.5`/`3.50`, `(-3,0)`/`(-3, 0)`).
- **Intentionally wrong answers (parametrized):** `49%`/`50`, `36%`/`0.40`,
  `5 meters`/`6`, `(-3,0)`/`(0,-3)`, `1,000`/`1,00`, `49%`/`0.5` → all
  `correct=False`.

Full QEE v2 suite: **114 passed** (87 prior + 27 new), no warnings.

---

## 4. Re-score (affected samples only — no retraining)

Re-ran `run_phase6_baseline_eval.py --rescore-only` (pure re-computation of
cached predictions; no model load, no training).

### 4.1 Previously-false-rejected records

| record_id | correctness before | correctness after | method |
|-----------|--------------------|-------------------|--------|
| `expert_math_001478` | 0.0 | **1.0** | number |
| `expert_math_002244` | 0.5 | **1.0** | number |

### 4.2 Math aggregate (N=100)

| Metric | Before patch | After patch |
|--------|--------------|-------------|
| Correctness | 0.7629 | **0.7779** (+0.015) |
| Reasoning quality | 0.7828 | 0.7930 |
| Hallucination rate | 0.23 | 0.22 |
| Unparsable count | (more) | 19 |

Code unchanged (0.2217) as expected — the patch only touches math normalization.

---

## 5. Effect on QEE calibration statistics (Phase 6.3 → 6.4)

Re-ran `qee_vs_human_phase6.py` against the re-scored predictions (same 60
proxy-labeled calibration samples).

| Metric | Math (N=30) before→after | Combined (N=60) before→after |
|--------|---------------------------|------------------------------|
| Pearson correlation | 0.710 → **0.936** | 0.929 → **0.973** |
| MAE | 1.47 → 1.30 | 1.00 → **0.92** |
| Bias (QEE − human) | +0.87 → +1.23 | +0.47 → +0.65 |
| Threshold agreement (≥7) | 93.3% → **100%** | 96.7% → **100%** |
| False approvals | 0 → 0 | 0 → 0 |
| False rejections | **2 → 0** | **2 → 0** |

### Do the statistics change materially? **Yes.**

1. **False rejections eliminated** (2 → 0). The evaluator no longer blocks
   correct percentage/plain-number answers — the direct Phase 6.3 concern.
2. **Correlation and agreement improved** (math ρ 0.71→0.94; combined 100%
   threshold agreement).
3. **Math bias rose (+0.87 → +1.23).** This is expected and benign: the two
   previously-rejected *correct* answers now score 10/10, while the proxy human
   reviewer gave 8–9. The bias now reflects QEE's tendency to award top scores
   to correct answers (a leniency on the 8→10 range), not a blocking bug.
4. **Zero false approvals** throughout — QEE still never over-approves wrong
   answers.

---

## 6. Recommendation

1. **Keep the patch.** It removes real false rejections and improves
   calibration without changing scoring philosophy.
2. **Monitor the math bias.** The +1.23 bias is leniency-driven; if human
   review later confirms QEE 10/10s are often 8-9s, a score-mapping calibration
   (not extraction) is the appropriate follow-up — still gated by human
   approval, never unsupervised.
3. **Do not authorize automated gating** — human approval remains mandatory.
4. Remaining `unparsable` math records (19/100) are distinct cases (coordinate/
   complex answers) already handled elsewhere; they can be reviewed in a future
   pass if calibration data suggests.

---

## 7. Artifacts

| Artifact | Path |
|----------|------|
| Patched normalizer | `scripts/evaluation_engine/v2/normalize.py` |
| Regression tests | `tests/evaluation_v2/test_math_eval.py` |
| Re-scored baseline | `experiments/phase6_baseline_eval/per_example_results.jsonl` / `baseline.json` |
| Re-scored calibration stats | `experiments/phase6_baseline_eval/qee_vs_human.json` |
