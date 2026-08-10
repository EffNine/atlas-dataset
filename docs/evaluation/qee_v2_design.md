# QEE v2 Design — Evaluation Framework v2

- **Phase:** 5A.2 Evaluation Framework v2
- **Date:** 2026-08-03
- **Status:** implemented, tested, measured (GO for metric improvement; calibration gating NOT yet authorized)
- **Scope:** correctness-metric improvement only. No dataset changes, no training-view changes, no release changes, no removal of human approval gates.
- **Related:** `docs/evaluation/atlas_evaluation_framework.md`, `docs/evaluation/qee_human_alignment_report.md`, `docs/specs/quality_engine_spec.md`

---

## 1. Current Problems (Audit of the Quality Evaluation Engine v1)

QEE v1 (`scripts/quality_score.py`) scored every record with the same lexical
heuristics: sentence/word counts, category-keyword hits, digit counts, and
code-fence detection. The Phase 5B QEE-Human Alignment Report documented the
result on 100 human-reviewed records:

| Metric (Phase 5B) | Value |
|---|---|
| QEE mean vs human mean | 9.00 vs 6.86 |
| Mean bias | **+2.14** |
| Exact agreement | **0.0%** |
| Within-1 agreement | **2.0%** |
| RMSE | 2.177 |
| False approvals (QEE ≥ 7, human < 7) | 16 |

### Root causes (verified against the current code)

1. **Ceiling effect — all scores collapse to the top.** Every dimension
   (accuracy, completeness, technical_correctness, clarity, usefulness,
   originality, relevance) saturates near 0.8–1.0 for short, well-structured,
   keyword-dense answers. The weighted sum therefore lands in a narrow band
   and the output map produces a near-constant score.
2. **No verifiable correctness.** `accuracy` is a lexical proxy (length > 30,
   has a URL, has digits). `technical_correctness` is keyword + digit presence.
   A wrong number surrounded by the right keywords scores the same as the
   right answer.
3. **Keyword matching is gameable.** `relevance` and `technical_correctness`
   reward the presence of category keywords in the answer — so an answer that
   merely restates the question's terms scores well. There is no anti-stuffing
   signal.
4. **Completeness uses raw word count only.** A 2-word answer can receive
   "elaboration credit" relative to a 1-word question; brevity is never
   penalized. Humans penalize exactly this.
5. **"clarity: short = clear".** The v1 clarity heuristic treats short
   sentences as maximally clear, inflating concise-but-incomplete answers.
6. **No reference-aware checking.** v1 never compares the assistant answer to
   the record's `canonical_answer`, so it cannot detect wrong or partially
   correct answers.

### Reproducible "before" (current engine on the same 100 records)

| Metric | v1 (reproducible) |
|---|---|
| Mean bias | +0.83 |
| MAE / RMSE | 0.83 / 0.975 |
| Exact / within-1 | 23% / 94% |
| False approvals / rejections | 16 / 0 |
| Score distribution | {7:32, 8:67, 9:1} |

---

## 2. New Scoring Methodology (QEE v2)

QEE v2 is a new, additive evaluation package under
`scripts/evaluation_engine/v2/`. It keeps the v1 public contract
(`evaluate_record`, `score_record`, same 7 dimension keys and weights) so
existing calibration/reporting consumers keep working, but replaces the
lexical signals with **verifiable correctness by answer type**.

### 2.1 Answer-type dispatch

`engine.detect_type(rec, question, answer)` classifies each record as
`math`, `code`, or `semantic`:

- **code** when the answer contains code/patch artifacts (fenced block,
  `diff --git`, `def f(`, `function f(`, `class C:`), or the question
  unambiguously requests code ("implement f", "write a function",
  "fix this bug", "compile", "stack trace", "regression test"). Process
  questions that merely mention debugging stay semantic.
- **math** for science/hardware categories (or both question+answer) carrying
  strong math signals (solve/compute/evaluate/simplify/integrate, `$`,
  `\boxed`, `\frac`, `x^`, equations with digits and operators, integral /
  derivative / equation / polynomial / quadratic). Loose words like "factor"
  or "sum" alone do **not** trigger math typing.
- **semantic** otherwise (the general rubric path).

### 2.2 Math correctness — `v2/math_eval.py`

- **Extract final answer** (`extract_final_answer`): last `\boxed{...}`,
  an "answer"/"result" label, the RHS of the last `=`, the last mathy line,
  or a bare number-word/expression. Prose without a math result fails closed.
- **Normalize notation** (`v2/normalize.py`): Unicode math → ASCII
  (`−`→`-`, `²`→`^2`), LaTeX noise removal, `\frac{a}{b}`→`(a)/(b)`,
  `\sqrt{a}`→`sqrt(a)`, spoken operators ("minus"→"-", "squared"→"^2")
  and number words ("seven"→"7"), whitespace collapse.
- **Equivalent-expression checking** (`expressions_equivalent`): both sides
  are parsed into a whitelisted AST (arithmetic + a fixed function set) and
  evaluated at deterministic sample points; equality uses a relative
  tolerance. This supports algebraically-equivalent forms
  (`(x+1)^2` ≡ `x^2+2x+1`) with **no strict substring matching**.
- **Fail closed:** no extractable final answer → score 0; missing reference →
  score 0.5 "unverifiable" (never a correctness claim).

### 2.3 Code correctness — `v2/code_eval.py`

- **Syntax validation** (`validate_python_syntax` via `compile`/`ast.parse`);
  broken code is penalized instead of rewarded for containing keywords.
- **Functional-structural comparison** (`structural_similarity`): a canonical
  AST-token stream blended 50/50 with an **operator signature** so that
  renaming/formatting/comments don't hide a wrong body, and a single
  operator swap (`+`→`*`) is decisively caught.
- **Patch/diff comparison** (`patch_similarity`): added-lines alignment of
  candidate vs reference unified diffs (SWE-style answers).
- **Unit tests** (`run_function_tests`): optional `(name, args, expected)`
  test specs run in an isolated namespace with restricted builtins; the pass
  rate drives the final score.
- **Fail closed:** uninterpretable code → score 0; no reference → 0.5
  "unverifiable".

### 2.4 Semantic / AI-ML — `v2/semantic_eval.py`

Replaces text/keyword matching with an explainable **rubric**:

| Criterion | Weight | What it measures |
|---|---|---|
| `coverage` | 0.36 | addresses the question's demand + **substance** (informative-token volume), soft penalties for off-topic and very short answers |
| `specificity` | 0.16 | concrete detail (numbers, technical terms) vs vague hedging ("maybe", "not sure") |
| `novelty` | 0.20 | **anti-keyword-stuffing** — new informational content vs verbatim re-use of question terms |
| `structure` | 0.10 | organization appropriate to the question (list/steps/code fences) |
| `grounding` | 0.08 | citations/URLs when the question is factual; neutral for conceptual questions |
| `clarity` | 0.10 | readable prose; penalizes ALLCAPS and extreme sentence lengths |

Each criterion returns `(score 0..1, reason)`, so every verdict is auditable.
A pluggable `JudgeBackend` provides the semantic layer: the default
`RubricJudge` is deterministic and offline; `LLMJudge` is a documented
interface for a CUDA-bound runtime that is **not** executed inside Atlas
evaluation (read-only, network-isolated). The rubric deliberately does **not**
reward keyword presence: `novelty` subtracts credit when the answer merely
echoes the question, which is exactly the vulnerability that let wrong
keyword-heavy answers score at ceiling under v1.

### 2.5 Dimension assembly and calibration

`engine.QeeV2Engine` maps the type-specific correctness result onto the
schema-stable 7 dimensions (same keys and weights as v1), computes
`raw_continuous` as the weighted sum, and maps it to `quality_score` 1..10.
Uncalibrated mapping is the v1-linear convention (`1 + 9·x`) so raw signals
are directly comparable. A fitted affine calibration
(`raw·slope + intercept`) is supported via `calibration.py`; see §5 for why
it is **not** enabled for gating yet.

---

## 3. Metric Definitions

All metrics are deterministic and stdlib-only.

| Metric | Definition |
|---|---|
| `math.correct` | boolean — reference and candidate expressions numerically equivalent |
| `math.score` | 1.0 if equivalent; 0 if not; partial via structural similarity; 0.5 unverifiable |
| `code.score` | blend of syntax (0.2–0.3), structural similarity, and test pass-rate |
| `code.patch_similarity` | `SequenceMatcher` ratio over added (`+`) lines of unified diffs |
| `semantic.rubric` | per-criterion 0..1 scores + reasons |
| `semantic.score` | `0.9·weighted_rubric + 0.1·reference_agreement` |
| `raw_continuous` | weighted sum of the 7 v2 dimensions (0..1) |
| `quality_score` | `round(1 + 9·mapped_continuous)`, clamped 1..10 |
| `correct` | True / False / None(unverifiable), per answer type |
| Calibration alignment | `mean_bias`, `mae`, `rmse`, `exact_agree`, `within1_agree`, `pearson_r`, `spearman_rho`, confusion (`false_approvals`, `false_rejections`) |

---

## 4. Tests

`tests/evaluation_v2/` (76 tests, hermetic, offline):

- `test_math_eval.py` — extraction, Unicode/LaTeX/spoken normalization,
  equivalence of factored/expanded/commutative forms, plus adversarial cases:
  - correct answer with different wording (`"four x squared minus three x
    minus seven"` ≡ `"4x^2-3x-7"`),
  - wrong answer with matching keywords (keyword soup scores < 0.5),
  - partial correctness (missing term gets partial, not full, credit).
- `test_code_eval.py` — syntax validation, structural/patch comparison, unit
  tests, plus adversarial: renamed-var rewrite is correct; same-signature
  wrong operator is incorrect; syntax-error penalty; partial (happy path
  passes, edge case fails) gets partial credit.
- `test_semantic_eval.py` — rubric criteria, anti-stuffing, paraphrase
  robustness, partial credit, vague-answer penalty, explainability, and the
  offline `LLMJudge` guard.
- `test_qee_v2_engine.py` — schema contract, determinism, read-only guarantee,
  answer-type dispatch, keyword-stuffed integration cases, calibration tools.

### Existing evaluation cases

No pre-existing QEE tests were modified; the v2 package is additive. The full
repository suite was re-run — see the Phase 5A.2 verification report for
counts (pre-existing failures are unrelated dependency issues: `zstandard`,
`huggingface_hub`, `parallel` import path).

---

## 5. Before vs After

Measured on the same 100 human-reviewed v0.2 records
(`scripts/evaluation_engine/v2/compare_v1_v2.py`; report artifact
`metadata/evaluation/qee_v1_v2_comparison.json`).

| Metric | Documented Phase 5B | Before (v1) | After (v2 raw) |
|---|---|---|---|
| Auto mean | 9.00 | 7.69 | 7.07 |
| Human mean | 6.86 | 6.86 | 6.86 |
| **Mean bias** | **+2.14** | +0.83 | **+0.21** |
| MAE | — | 0.83 | **0.33** |
| RMSE | 2.177 | 0.975 | **0.592** |
| Exact agreement | 0% | 23% | **68%** |
| Within-1 agreement | 2% | 94% | **99%** |
| False approvals | 16 | 16 | **12** |
| False rejections | — | 0 | 4 |
| Score distribution | {9:100} | {7:32, 8:67, 9:1} | {6:8, 7:77, 8:15} |

v2 raw removes the ceiling effect (scores now live in 6–8, the human range),
halves the bias, and cuts MAE/RMSE by ~60%. False approvals drop 16 → 12.

### Calibration readiness (honest negative result)

A leave-one-out affine calibration was fit to test whether a calibrated v2
mapping could be trusted for automated gating. The fitted slope is
**0.125 — near-flat** — meaning the 100-record review sample is too small and
too noisy to support a reliable linear calibration. It collapses toward the
modal score and would re-create the constant-7 artifact that the project
already rejected. **Conclusion: do not enable calibrated automated gating on
this sample.** Re-fit on a larger, less noisy human-review set (Phase 5C) and
re-validate before any automated gate uses a calibrated mapping.

---

## 6. Migration Plan

1. **Now (Phase 5A.2, done):** v2 package added under
   `scripts/evaluation_engine/v2/`; v1 remains untouched; adversarial tests
   added; comparison tooling added; design doc published. Outputs are additive
   and read-only.
2. **Next (Phase 5B readiness):** decide whether to route record scoring
   through `QeeV2Engine` for new records while keeping `quality_score.py` for
   frozen/reviewed artifacts. No dataset or review files are rewritten by any
   v2 code.
3. **Phase 5C (recalibration):** gather a larger human-review sample; fit the
   calibration mapping; validate out-of-sample agreement and preserve score
   variance before any automated approval use.
4. **Optional:** wrap `QeeV2Engine` as a registered metric in
   `evaluation_engine.metrics.MetricRegistry` so standard evaluation reports
   can emit v2 correctness metrics.
5. **Training (blocked until authorized):** the LoRA pilot
   (`experiments/lora_pilot_math_v0.1/`) remains HOLD pending a CUDA runtime;
   when it runs, v2 math/code correctness should be the primary scorer.
   No training is started by this phase.

### Compatibility and safety guarantees

- v2 never writes to `curated/`, `raw/`, `review_queue/`, `training_views/`.
- v2 is deterministic, stdlib-only, read-only, network-isolated.
- Human approval gates are unchanged; the calibration readiness probe
  explicitly recommends against automated gating.

---

## 7. Files Changed (Phase 5A.2)

**New — v2 package:**
- `scripts/evaluation_engine/v2/__init__.py`
- `scripts/evaluation_engine/v2/normalize.py`
- `scripts/evaluation_engine/v2/math_eval.py`
- `scripts/evaluation_engine/v2/code_eval.py`
- `scripts/evaluation_engine/v2/semantic_eval.py`
- `scripts/evaluation_engine/v2/engine.py`
- `scripts/evaluation_engine/v2/calibration.py`
- `scripts/evaluation_engine/v2/compare_v1_v2.py`

**New — tests:**
- `tests/evaluation_v2/conftest.py`
- `tests/evaluation_v2/test_math_eval.py`
- `tests/evaluation_v2/test_code_eval.py`
- `tests/evaluation_v2/test_semantic_eval.py`
- `tests/evaluation_v2/test_qee_v2_engine.py`

**New — artifacts / docs:**
- `metadata/evaluation/qee_v1_v2_comparison.json`
- `docs/evaluation/qee_v2_design.md` (this document)

---

*This document reflects the Phase 5A.2 implementation state. No dataset,
training-view, release, or governance changes were made.*
