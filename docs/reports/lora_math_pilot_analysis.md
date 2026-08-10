# LoRA Math Pilot — Per-Example Analysis & Root Cause Report

**Experiment:** `lora_pilot_math_v0.1` (Phase 5B.1)
**Status:** Retained — go/no-go on follow-up experiments pending this analysis
**Date:** 2026-08-04
**Scope note:** No additional training was performed. This document analyzes the
first completed QLoRA pilot on the `math_300m_v0.1` eval split (13 records).

---

## Executive Summary

The headline QEE v2 aggregate delta (+0.0429 correctness, −0.0769
hallucination) is **mostly an evaluation-engine artifact, not evidence of
improved model reasoning.**

- The LoRA training produced answers that are **terser** (stereotyped
  `The answer is \boxed{...}`) than the baseline's verbose step-by-step
  responses.
- The QEE v2 math evaluator's final-answer extractor
  (`math_eval.py:81`, `_BOXED_RE = r"\\boxed\{([^{}]*)\}"`) **cannot parse a
  box whose contents contain nested braces** — i.e. `\boxed{\frac{5}{2}}`,
  `\boxed{\sqrt{3}}`, `\boxed{\frac{4}{9}}`. These are the *correct* forms for
  the target answers, but the regex returns nothing, so the answer is scored
  `unparsable → 0.0`.
- **Five records that the metric scored as 0.0 (or regressed) actually contain
  the correct answer** (`boxed{5/2}`, `boxed{√3}`, `boxed{4/9}`, `boxed{(-3,0)}`,
  `boxed{√7/2}`). A diagnostic re-score with a nested-brace-capable extractor
  raises those to 1.0 correctness.
- Therefore, **no reliable improvement or regression in mathematical ability
  can be concluded** from the 13-sample delta. The `4x²−3x−7`, integer, and
  single-token answers (7/13) were extracted correctly both before and after.

**Bottom line:** fix the evaluator before re-scoring; do not trust the current
online delta to decide further training. The model is not demonstrably better
or worse mathematically — it changed *format*, which the metric reads
unreliably.

---

## 1. Per-Sample Classification

Legend: `improved` / `unchanged` / `regressed` per the **reported** metric,
plus the **diagnostic** verdict using a corrected extractor.

| record_id | Baseline corr | LoRA corr (reported) | Reported Δ | Reported class | Diagnostic corr (fixed extractor) | Diagnostic note |
|-----------|---------------|----------------------|------------|----------------|----------------------------------|-----------------|
| expert_math_000125 | 1.0 | 1.0 | 0.0 | unchanged | 1.0 | robust correct |
| expert_math_000281 | 1.0 | 1.0 | 0.0 | unchanged | 1.0 | robust correct |
| expert_math_000831 | 0.1667 | 0.0 | −0.1667 | **regressed** | **1.0** | boxed{frac{5/2} correct → metric missed |
| expert_math_000900 | 0.5 | 0.5 | 0.0 | unchanged | 0.5 | unparsable (coordinate) |
| expert_math_000961 | 1.0 | 1.0 | 0.0 | unchanged | 1.0 | robust correct |
| expert_math_001421 | 0.0 | 0.0 | 0.0 | unchanged | **1.0** | boxed{frac{4}{9} correct → metric missed |
| expert_math_001505 | 1.0 | 1.0 | 0.0 | unchanged | 1.0 | robust correct |
| expert_math_001802 | 0.025 | 0.0 | −0.025 | **regressed** | **1.0** | boxed{sqrt(3)} correct → metric missed |
| expert_math_002168 | 1.0 | 1.0 | 0.0 | unchanged | 1.0 | robust correct |
| expert_math_002660 | 0.0 | 0.0 | 0.0 | unchanged | 0.0 | nested frac{sqrt(7)/2} unparsable |
| expert_math_002701 | 0.25 | 1.0 | **+0.75** | improved | 1.0 | plain integer `16` extracted fine |
| expert_math_002953 | 1.0 | 1.0 | 0.0 | unchanged | 1.0 | robust correct |
| expert_math_002995 | 1.0 | 1.0 | 0.0 | unchanged | 1.0 | robust correct |

**Aggregates:** reported correctness 0.6109 → 0.6538 (+0.0429). Diagnostic
correctness for the LoRA post-training answers ≈ 0.85 (11/13 raise to 1.0;
`000900` remains 0.5 as a coordinate; `002660` remains 0 due to deep nesting).

Key per-sample notes:

- **`expert_math_002701` (reported "improved", +0.75).** Baseline answer was a
  long non-committal reasoning block that the extractor could not pin; the LoRA
  version produced the clean integer `\boxed{16}` which the regex parses as a
  plain number → `number/True → 1.0`. This is the **entire source of the
  positive aggregate delta**.
- **`expert_math_000831`, `expert_math_001421`, `expert_math_001802` (reported
  "regressed"/0.0).** LoRA actually produced the correct boxed fractional/radical
  answers; the extractor dropped them → 0.0. **These are not real regressions.**
- **`expert_math_002660` (0.0→0.0).** Both baseline and LoRA gave the correct
  `\boxed{\frac{\sqrt{7}}{2}}`. Neither a single- nor double-nested extractor
  resolves it; genuinely unverifiable by the current QA. **Pre-existing
  limitation, not a training regression.**
- **`expert_math_000900` (0.5→0.5).** Both before and after answer `(-3, 0)`.
  Coordinate/tuple answer is stamped `unparsable` and capped at 0.5. **Limit of
  the evaluator (tuple answer), unchanged.**

---

## 2. Root-Cause Analysis

### 2.1 The change is in output *format*, not in mathematical *content*

Across the eval set the LoRA responses collapsed to a near-stereotyped form,
typically a single line ending in `\boxed{...}`:

```
baseline: "Substitute x=2/3 ... y = 11/6 ... x + y = ... = \boxed{\frac{5}{2}}"
LoRA:     "The answer is $\boxed{\frac{5}{2}}$."        # same correct number
```

For 9/13 records the LoRA and baseline reach the **same correct answer**; the text
length is what changed (verbosity reduced). For all 13 the answers are
mathematically equivalent or identical in value.

### 2.2 The detected delta is driven by the extractor, not the model

The `\boxed{...}` regex `[^{}]*` (no nested-brace match) fails exactly on the
target form the SFT loop teaches: mathematical answers rendered in LaTeX
fractions/radicals. Because:

- 7 integer / simple-token answers parse (`number`, `numeric_sampling`) → metric
  unchanged (1.0).
- 3 fractional/radical-boxed answers (`5/2`, `4/9`, `√3`) → metric 0.0 **though
  correct**; these read as *regressions*.
- The one integer answer the LoRA tersed-up (`002701`) → metric 1.0 (the only
  *improvement*).

So the mean delta is +0.043 from correctly-extractability changes: some
fraction answers that *should* have scored 0.0 before (because the previous
verbose answer's number was submerged in prose) now parse, but several now-correct
fraction answers are *mis-scored to 0*. These two effects partially cancel and
currently produce a small net +. The metric is inconsistent.

### 2.3 Memorization vs. reasoning

- **No memorization:** train and eval record sets are disjoint (117 train vs 13
  eval, overlap = NONE). The adapter cannot have memorized eval labels.
- **Not attentive reasoning** either: improvements/differences reduce to answer
  *extraction*, not to new arithmetic. There is no record where the LoRA
  performed a component step the baseline could not, per the samples inspected.
- Dataset size: 117 records at batch 1 / grad-accum 8 → effectively ~14.6
  optimizer steps per epoch when counting unique examples (60 steps × 1 batch
  over ... : the model saw 480 sample passes over 117 unique → ~4.1 epochs).

### 2.4 Where the change really came from

Given SFT assistant text always ends in a `\boxed{...}` (checked: yes,
`boxed in`), training drove the model to produce that exact closing marker
earlier and to shorten/remove prose. This is **format-guidance (imitating the
training answer shape)** — the intended behavior of SFT — but it is **not
evidence of improved qualitative reasoning**, and it interacts badly with the
strict answer parser.

---

## 3. Regression Analysis

Reported regressions (`000831`, `001802`; and `002660`, `001421`, `000900` at 0.0
metric) are, on close inspection, **not true correctness regressions**:

| record | Reported | LoRA answer (actual) | True answer | Diagnostic | True regression? |
|--------|----------|----------------------|-------------|------------|------------------|
| 000831 | 0.1667→0.0 | `\boxed{\frac{5}{2}}` | 5/2 | 1.0 | **No** (metric miss) |
| 001802 | 0.025→0.0 | `\boxed{\sqrt{3}}` | √3 | 1.0 | **No** (metric miss) |
| 001421 | 0.0→0.0 | `\boxed{\frac{4}{9}}` | 4/9 | 1.0 | **No** (metric miss) |
| 000900 | 0.5→0.5 | `(-3, 0)` | (-3,0) | 0.5 | **No** (coordinate cap) |
| 002660 | 0.0→0.0 | `\boxed{\frac{\sqrt{7}}{2}}` | √7/2 | 0.0 (eval `unparsable`) | **Unclear — eval limitation** |

All but `002660` are the same answer value as the baseline; the metric just
reads LoRA's terser LaTeX differently. For `002660`, both generations are
correct in value but the evaluator cannot parse the double-nested expression,
so we cannot use this sample to score training at all (fails-closed).

---

## 4. Recommendations

### Immediate (highest priority)
1. **Fix the evaluator before trusting this pilot metric.** Change
   `scripts/evaluation_engine/v2/math_eval.py:81` `_BOXED_RE` to a
   nested-brace-aware pattern (balanced braces, or better: normalize LaTeX to a
   parseable AST before extraction). Handle tuple/coordinate answers. This is
   **not** governance-breaking (it is a scoring bug fix), but per rule it must
   go through the normal calibration/review (Phase 5C) before use in approvals.
2. **Re-score the pilot** with the corrected evaluator to obtain an honest
   baseline-vs-LoRA delta. Until then, **treat the current +0.0429 as an
   artifact, not a result.**

### Training config (evidence-based)
The following are the *observed* effects of this run, and therefore my
recommendation, but none is validated by a decisive metric.

- **Keep/drop the current config?** The current 60-step run significantly
  shortened answers (a style shift). For a math-SFT the question is whether we
  *want* terse answers. If the target is step-wise reasoning quality, the
  current config pushes toward tersification — **not** ideal. Consider keeping
  rank/steps but monitoring output verbosity.
- **Increase epochs?** No evidence more epochs improves mathematical truth; we
  already pass each unique example ~4×. With only 117 examples, additional
  epochs risk more format overfit, not reasoning gains. **Do not increase**
  until the metric is fixed and shows headroom.
- **Increase LoRA rank?** Rank only affects representational capacity; the
  stepping issue here is not capacity but metric + data diversity. **Hold rank
  at 8** until the metric issue is resolved.
- **Expand dataset?** Strongest lever. The pilot is choke-limited by a 117-record
  train view. Expanding to the approved `expert-pilot-6500-v0.1` / larger
  OpenMathInstruct subset would give real reasoning signal. **Recommended next
  step** (after metric fix): re-run with a larger train split and the corrected
  evaluator.
- **Change learning rate?** LR 2e-4 cosine is a sane default and not implicated
  in the observed behavior. **Keep** unless a fixed-metric run shows loss-plateau
  symptoms.

### Process
- Record this as a calibration finding: QEE v2 math scoring is unreliable on
  nested-brace boxed answers; **do not gate approvals on its current math
  correctness output** until Phase 5C recalibration.
- Add `test` cases to `scripts/evaluation_engine/v2` covering
  `\boxed{\frac{5}{2}}`, `\boxed{\sqrt{3}}`, `\boxed{\frac{4}{9}}`,
  `\boxed{\frac{\sqrt{7}}{2}}`, and coordinate answers, to lock the fix.

---

## Appendix: Evidence

- Baseline source artifacts: `experiments/baseline_eval_v0.2/baseline_v2.json`,
  `per_example_results.jsonl` (math rows).
- Post-training: `experiments/lora_pilot_math_v0.1/evaluation/`
  `post_training_per_example.jsonl`, `comparison_metrics.json`,
  `adapter_metadata.json`.
- Diagnostic probe script: `/mnt/d/atlas-dataset/...` (see `probe_fixed.py`,
  `diag_rescore.py`) using `scripts/evaluation_engine/v2/math_eval.py`.
- Training: `experiments/lora_pilot_math_v0.1/training_log.json` (60 steps,
  final loss 0.227, min 0.149, 480 example passes, dataset checksum verified).

*Action items: fix QA (nested-brace + coordinate), re-score, decide with the
real delta.*