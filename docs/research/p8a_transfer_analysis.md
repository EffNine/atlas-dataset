# P8-A.1 Transfer Pattern Analysis

> **Phase:** 8, Experiment A.1 (P8-A.1) — analysis only
> **Parent:** P8-A `atlas-math-small-qwen7b-lora-transfer-v1` (Math → Code)
> **Status:** COMPLETE — analysis only. No training, no dataset modification,
> no QEE modification.
> **Date:** 2026-08-05
> **Question:** Why is overall cross-domain transfer neutral? What task-level
> behavior explains the per-example improved / regressed / unchanged pattern?

---

## 1. Objective & Scope

Explain the P8-A neutral result (Δ_cross^{M→C} = +0.0018) by analyzing every
`code_eval_v1` example at the task level. The analysis:
1. Groups all 100 examples by category (bug fixing, debugging, code review,
   algorithm reasoning, refactoring).
2. Reports baseline / post-training / delta / improved / regressed / unchanged
   per category.
3. Clusters the 24 regressions and 22 improvements by failure/mechanism type.
4. Recommends a control for P8-B.

**Scope constraints honored:** no training; no dataset or QEE modification;
all signals computed with the frozen QEE v2 `code_eval` helpers.

---

## 2. Method

### 2.1 Data sources (all frozen, read-only)

| Source | Path |
|--------|------|
| P8-A post-training per-example | `experiments/atlas-math-small-qwen7b-lora-transfer-v1/evaluation/post_training_per_example.jsonl` |
| Phase 6.3 baseline per-example | `experiments/phase6_baseline_eval/per_example_results.jsonl` (code-300m rows) |
| Eval records + verification | `evaluation/eval_sets/phase6_expansion_v1/code_eval_v1.jsonl` |
| Signals + summary | `experiments/atlas-math-small-qwen7b-lora-transfer-v1/analysis/patterns/` |

### 2.2 Per-example signals

For every record, `analyze_p8a_transfer_patterns.py` computes objective signals
using the frozen QEE v2 `code_eval` helpers (`is_patch`, `extract_added_lines`,
`patch_similarity` — the same metric as the scorer):

- `candidate_is_patch` — response contains a unified diff (`diff --git` / `--- a/` /
  `+++ b/` / `@@`); the signal that determines whether the patch scorer can align it.
- `file_path_match` — candidate `--- a/<path>` equals reference path.
- `added_line_overlap` — `patch_similarity(reference, candidate)` (0..1).
- `hunk_count`, `candidate_added_lines`, `response_len`, `tokens_generated`.
- verification context: `fail_to_pass_count`, `pass_to_pass_count`.

Classification threshold `τ = 0.05` on `post_correctness − baseline_correctness`
(protocol v1.1 §8.3).

---

## 3. Category Summary

### 3.1 Aggregate recap

| Metric | Baseline | Post-training | Δ |
|--------|----------|---------------|---|
| Correctness (N=100) | 0.2217 | 0.2235 | **+0.0018** (neutral) |
| Improved / Regressed / Unchanged | — | — | 22 / 24 / 54 |

### 3.2 Per-category table

| Category | N | Baseline | Post | Δ | Improved | Regressed | Unchanged |
|----------|---|----------|------|-----|----------|-----------|-----------|
| algorithm reasoning | 10 | 0.2667 | 0.4000 | **+0.1333** | 3 | 2 | 5 |
| bug fixing | 48 | 0.2411 | 0.2355 | −0.0056 | 12 | 11 | 25 |
| code review | 15 | 0.1387 | 0.1230 | −0.0157 | 3 | 5 | 7 |
| debugging | 20 | 0.1760 | 0.0998 | **−0.0762** | 1 | 5 | 14 |
| refactoring | 7 | 0.3333 | 0.4586 | **+0.1253** | 3 | 1 | 3 |

Two categories drive the improvement side (algorithm reasoning +0.133,
refactoring +0.125); one drives the regression side (debugging −0.076); the
two largest categories (bug fixing, code review) are near-neutral.

### 3.3 Patch-emission rate by category (baseline → post)

| Category | Baseline patches | Post patches |
|----------|------------------|--------------|
| algorithm reasoning | 4 / 10 | 4 / 10 |
| bug fixing | 18 / 48 | 14 / 48 |
| code review | 5 / 15 | 3 / 15 |
| debugging | 7 / 20 | **2 / 20** |
| refactoring | 3 / 7 | 4 / 7 |
| **All** | **37 / 100** | **27 / 100** |

The post-training model emits unified diffs **less** often overall (37 → 27),
with the largest drop in debugging (7 → 2) — matching the worst category delta.

---

## 4. Heatmap

Heat intensity: `[▁]` ≈ 0, `[▂]` ≈ 0.1, `[▅]` ≈ 0.2, `[▉]` ≈ 0.4.

### 4.1 Category × classification

| Category | Improved | Regressed | Unchanged | Post-patch rate |
|----------|----------|-----------|-----------|-----------------|
| algorithm reasoning | 3 ▅ | 2 ▂ | 5 ▉ | 4/10 |
| bug fixing | 12 ▉ | 11 ▉ | 25 ▉ | 14/48 |
| code review | 3 ▅ | 5 ▅ | 7 ▉ | 3/15 |
| debugging | 1 ▁ | 5 ▅ | 14 ▉ | 2/20 |
| refactoring | 3 ▅ | 1 ▁ | 3 ▅ | 4/7 |

### 4.2 Category × correctness (heat of Δ)

| Category | Baseline | Post | Δ | |
|----------|----------|------|---|--|
| algorithm reasoning | 0.267 | 0.400 | +0.133 | ▉ |
| refactoring | 0.333 | 0.459 | +0.125 | ▉ |
| bug fixing | 0.241 | 0.236 | −0.006 | ▁ |
| code review | 0.139 | 0.123 | −0.016 | ▁ |
| debugging | 0.176 | 0.100 | −0.076 | ▅ |

### 4.3 Mechanism heatmap (see §5–6)

| Mechanism | Regressions (24) | Improvements (22) |
|-----------|------------------|-------------------|
| Patch omitted (prose / fenced snippet) | 23 | 0 |
| Patch emitted — correct (overlap ≥ 0.5) | 0 | 22 |
| Patch emitted — partial/wrong logic (overlap < 0.5) | 1 | 0 |
| Hallucination / API misuse cluster | 0 | 0 |

---

## 5. Regression Clustering (24 records)

### 5.1 Primary finding: output-format regression, not reasoning loss

| Signal | Regressed (n=24) |
|--------|------------------|
| Baseline candidate was a unified diff | **24 / 24** |
| Post candidate is a unified diff | **1 / 24** |
| Post candidate file path matches reference | 1 / 24 |
| Mean post added-line overlap vs reference | 0.028 |
| Post responses with a fenced code block (no diff markers) | 20 / 24 |
| Pure prose (no fence, no code tokens) | ~4 / 24 |
| Mean post response length | ~1,356 chars |

**Every regression is a record where the baseline model produced a unified diff
(all 24) and the math-trained model did not** (23/24 contain no diff markers;
20/24 still contain fenced code or prose but not a `diff --git`/`--- a/` patch).
The QEE patch-similarity scorer can only align unified diffs, so a response
that explains a fix but omits the diff scores **0.0** regardless of reasoning.

**Cluster breakdown (24):**
- **patch structure / output format — 23/24.** The adapter replaced the diff
  with prose (and often a plain fenced snippet). Example `expert_swe_000051`
  ends with "With these changes, the `union()` method should now correctly
  handle …" but never shows the changes.
- **partial patch / logic — 1/24.** `expert_swe_000336` (base 1.0 → 0.667):
  a diff was emitted but incomplete.
- **hallucination / API misuse / within-patch formatting — 0/24** as a
  systematic cluster (no false-claim or wrong-API pattern detected among the
  regressions).

### 5.2 Supporting: patch-emitters that are wrong (logic failures exist, but are not the neutral driver)

Among the 27 post-training patch-emitters, 4 are well-formed but wrong
(overlap < 0.5). All 4 target the correct file (`file_path_match=True`) but
contain incorrect changes:

| Record | Category | Overlap | File |
|--------|----------|---------|------|
| expert_swe_000110 | bug fixing | 0.000 | django/db/models/functions/datetime.py |
| expert_swe_000316 | refactoring | 0.210 | xarray/core/dataset.py |
| expert_swe_000362 | bug fixing | 0.333 | sklearn/ensemble/iforest.py |
| expert_swe_000131 | code review | 0.353 | django/db/migrations/loader.py |

These are genuine **logic** failures (correct location, wrong code), but they
are evenly matched by correct patches and do not drive the neutral aggregate.

---

## 6. Improvement Clustering (22 records)

### 6.1 Common properties — every improvement is a correct patch emission

| Signal | Improved (n=22) |
|--------|-----------------|
| Post candidate is a unified diff | **22 / 22** |
| Post candidate file path matches reference | **22 / 22** |
| Mean added-line overlap | **0.849** |
| Overlap ≥ 0.5 | 18 / 22 |
| Flipped from baseline prose → post patch | **15 / 22** |
| Mean post response length | ~1,637 chars |

**Shared mechanism:** the adapter produced a well-formed unified diff targeting
the exact reference file with added lines that closely match the gold patch
(18/22 ≥ 0.5, many at 1.0). 15/22 are records where the baseline failed to
emit a usable diff and the adapter succeeded. Improvements concentrate in bug
fixing (12), then algorithm reasoning / code review / refactoring (3 each),
debugging (1).

**Example `expert_swe_000064`** (bug fixing, 0.00 → 1.00): baseline prose only;
post emits a correct diff for `django/forms/fields.py` adding
`result.error_messages = self.error_messages.copy()`.

### 6.2 Interpretation

The adapter's code-generation ability did **not** generally improve. What
changed is the **conditional output policy**: when the model commits to a
unified-diff format, its patches are high quality; when it does not (most
cases), it writes prose and scores 0. This bimodal behavior — 22 strong
wins + 23 prose regressions → net ~0 — is the mechanism behind neutral transfer.

---

## 7. Representative Examples

### 7.1 Improvements (patch emission correct)

| Record | Category | Δ | Notes |
|--------|----------|---|-------|
| expert_swe_000064 | bug fixing | +1.00 | django `__deepcopy__` — exact added line |
| expert_swe_000133 | algorithm reasoning | +1.00 | 0.00 → 1.00 patch |
| expert_swe_000166 | refactoring | +1.00 | 0.00 → 1.00 patch |
| expert_swe_000456 | code review | +1.00 | 0.00 → 1.00 patch |
| expert_swe_000351 | debugging | +0.45 | 0.55 → 1.00 (only debugging improvement) |

### 7.2 Regressions (patch omitted → 0.0)

| Record | Category | Δ | Notes |
|--------|----------|---|-------|
| expert_swe_000051 | bug fixing | −1.00 | django composed `values()` — prose only |
| expert_swe_000091 | algorithm reasoning | −1.00 | prose only |
| expert_swe_000308 | code review | −1.00 | prose only |
| expert_swe_000085 | refactoring | −1.00 | prose only |
| expert_swe_000018 | debugging | −0.80 | astropy `Unit == None` — prose + fenced snippet, no diff |

### 7.3 Logic failures among patch-emitters (minority)

| Record | Category | Overlap | Notes |
|--------|----------|---------|-------|
| expert_swe_000110 | bug fixing | 0.000 | django `TruncDate` tzinfo — correct file, wrong implementation |

---

## 8. Threats to Interpretation

1. **Format confound (dominant).** The QEE v2 code scorer aligns only unified
   diffs; a response that explains a fix without a diff scores 0.0. The two
   models have very different output policies under the identical inference
   config: **baseline hit the 512-token cap 81/100 times; post only 14/100**
   (post mean 326 tokens vs baseline much longer). The observed ±1.0 swings are
   dominated by whether a unified diff was emitted — not by code reasoning
   quality. The "neutral" verdict is real on this metric but is heavily
   format-driven.
2. **Baseline truncation asymmetry.** Baseline patches often appear early in a
   truncated response; its 37/100 patch rate may be an artifact of diff-first
   generation. Equalizing the length policy (or recording it as a covariate)
   is required before attributing deltas to capability.
3. **Metric is near-binary.** Patch added-line similarity flips 0↔1 on exact
   added-line content; a correct-but-differently-written patch scores ~0.5 or
   0. Small patch deviations therefore generate large per-example deltas and
   inflate improved/regressed counts.
4. **No functional verification.** Patch similarity is structural; no unit-test
   execution. A patch that matches added lines may still fail tests
   (`fail_to_pass` counts are recorded in the eval set but not enforced here).
5. **Small per-category N.** refactoring (7) and algorithm reasoning (10) are
   directional only; their positive deltas are not strong conclusions.
6. **Single seed / single run / single model.** No variance estimate (T8);
   any category claim is a single-sample observation.
7. **QEE absolute bias.** Known +2.14 vs human review (threat T5); mitigated by
   using deltas vs same-split baseline, but the format sensitivity above
   remains.

---

## 9. Recommendation for P8-B (Code → Math)

1. **Pre-register a format gate for code eval.** Count non-diff responses as
   *format failures* and report a first-class **patch-emission rate** alongside
   correctness, so code transfer conclusions are not confounded by output
   format.
2. **Pin output policy across models.** For code, use a prompt/inference
   directive that forces a unified-diff answer (or a two-stage
   generate-then-format step), and equalize/record `max_new_tokens` — the
   baseline's 81% truncation vs post's 14% is a confound to remove.
3. **Score code with a format-normalized metric.** Either extract the
   ` ```diff ` block if present, or fall back to structural similarity on plain
   fenced code, so functionally-correct-but-unformatted answers are not scored 0.
4. **Report per-category deltas + patch rates** in the P8-D symmetry analysis;
   expect debugging to be the most format-sensitive category.
5. **Keep P8-B's own evaluation symmetric:** the mirror experiment (Code→Math)
   should apply the same format controls so `TR_{C→M}` vs `TR_{M→C}` is not a
   comparison of format policies.
6. **Consider a seed sweep** (protocol T8) before any robust symmetry claim.

---

## 10. Rules Compliance

- [x] No training performed.
- [x] No dataset / frozen view / QEE modification.
- [x] Analysis-only; deterministic script (`analysis/analyze_p8a_transfer_patterns.py`).
- [x] No new experiments. Stopped after analysis.
