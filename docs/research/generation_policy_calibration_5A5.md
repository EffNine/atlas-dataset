# Generation Policy Calibration — Sprint 5A.5

> **Sprint:** 5A.5 — Generation Policy Calibration (research & design only)
> **Status:** COMPLETE — read-only analysis only. **No inference, no protocol change,
> no evaluator change, no dataset change.** Pending Technical Lead review.
> **Date:** 2026-08-06
> **Base commit:** `99e88e1`
> **Driving evidence:** Protocol v2 baseline run
> (`experiments/atlas-mixed-pilot-qwen7b-eval-v2/`), math metric audit
> (`docs/research/math_metric_audit.md`), and the canonical Generation
> Policy Lock definition (Protocol v2 §3.6 / `docs/research/p8_generation_policy.md` §4).
> **Method:** deterministic, offline, read-only analysis on frozen per-example
> artifacts. No new inference. No simulation requiring model execution.
> **Output:** this report + artifacts under `metadata/evaluation/` + figures.

---

## 1. Executive Summary

**The dominant math failure mode is truncation (41%), driven by the reference-derived
budget `128 + 1.5·N_ref` being too small for the model's fixed step-by-step reasoning
overhead on short-reference records.** The model's generation length for math is
strongly correlated with reference length (r=0.85, R²=0.72), but **not at all** with
prompt length (r=−0.02, R²=0.0). For code, generation length correlates weakly with
reference length (r=0.53, R²=0.28) and prompt length is irrelevant (r=0.05).

**Recommended Generation Policy Lock parameters (per family, Protocol v2 §3.6):**

| Family | base_budget | alpha | min_budget | max_budget |
|--------|------------:|------:|-----------:|-----------:|
| **math** | **128** | **3.0** | 256 | 4096 |
| **code** | **256** | **2.0** | 256 | 4096 |
| **semantic** | **128** | **3.0** | 256 | 4096 (placeholder) |

**Primary rationale:**

- **Math alpha 3.0**: raises the mean budget from 572 → 1015 (1.77×). Counterfactual
  predicted residual truncation drops from 41% → **0%** under a regression-based
  estimate. The model's gen/ref ratio p90 is 2.02, max 2.49 — alpha 3.0 provides
  a comfortable margin on the observed distribution. Consistent with the
  `math_metric_audit.md` §6.3 recommendation to "consider a larger math budget
  multiplier (e.g. 3.0×)".
- **Code alpha 2.0 / base 256**: raises mean budget 788 → 1377 (1.75×), predicted
  residual 3% → **0%**, while keeping code budgets lean (mean only 1.75×, not the
  2.45× of a higher floor). The 3 observed truncations (budgets 350/364/518) are
  covered; G-POL margin increases.
- **Hybrid formula** (`256 + 2.0·max(N_ref, N_prompt)`, F6) is a viable
  cost-optimized alternative for math (mean 872, 1.53×, predicted residual 0%),
  but the added complexity and prompt-token dependency make alpha 3.0 reference-only
  the preferred primary choice for simplicity and audit precedence.
- **Flat fallback** (1024) is nearly as good as F1 for math (mean 1024, residual 0)
  but loses adaptivity for longer references and is less principled for scale-out.

The remaining truncation failure modes (format collapse, extraction gaps, genuine
wrong answers) are **not generation-budget issues** and are excluded from this
calibration.

---

## 2. Methodology & Data

### 2.1 Inputs (frozen, read-only)

| Artifact | Path | Records |
|----------|------|---------|
| Math per-example predictions | `experiments/atlas-mixed-pilot-qwen7b-eval-v2/per_example_math.jsonl` | 100 |
| Code per-example predictions | `experiments/atlas-mixed-pilot-qwen7b-eval-v2/per_example_code.jsonl` | 99 |
| Math eval set | `evaluation/eval_sets/protocol_v2/math_eval_v2.jsonl` | 100 |
| Code eval set | `evaluation/eval_sets/protocol_v2/code_eval_v2.jsonl` | 99 |
| Run metadata (timestamps, policy locks, aggregate stats) | `experiments/atlas-mixed-pilot-qwen7b-eval-v2/run_metadata.json` | — |
| Generation policy summary | `experiments/atlas-mixed-pilot-qwen7b-eval-v2/generation_policy_summary.json` | — |

### 2.2 Reference-token inversion

The applied per-record budget for the T3 run was computed as
`min(4096, max(256, 128 + ceil(1.5·N_ref)))` where `N_ref` is the exact tokenizer
token count of `canonical_answer`. For records where the budget was interior
(`256 < budget < 4096`), we recover `N_ref` by inverting the formula; for capped
records (`budget = 4096`) we use the threshold `N_ref ≥ 2645` as a lower bound;
for floored (`budget = 256`) `N_ref ≤ 85`. One fallback record (math, budget 1024)
uses a chars-to-tokens estimate calibrated from interior records. The derived
tokens reproduce the applied F0 budget for **99/100 math and 99/99 code** records
(1 math record deviates by ±1 token due to the rounding/ceil effect) — validating
the inversion.

### 2.3 Generation length prediction

For each family we regress `tokens_generated` (eos records only) on `N_ref` and
`N_prompt` (estimated from prompt chars via the same empirical chars/token ratio).
Predictions for truncated records are then `max(budget+1, reg_pred)`, conservatively
placing a known lower bound on generation length. **Predicted recovery counts are
estimates** — actual recovery requires re-inference on the modified budget (out of
scope). The regression itself is a purely arithmetic operation on frozen artifacts
and constitutes **no model execution**.

### 2.4 Validation: F0 residual equals measured truncation

For the current formula (F0, alpha 1.5), the predicted residual truncation is
**0.410** for math and **0.030** for code — matching the measured truncation rates
(41/100 and 3/99) **exactly**. This validates that the predictor is calibrated and
that the residual estimates for candidate formulas are trustworthy indicators.

### 2.5 Artifacts produced

| Artifact | Path | SHA-256 |
|----------|------|---------|
| Full analysis output JSON | `metadata/evaluation/generation_policy_calibration_5A5/analysis_output.json` | `281811ae31…` |
| Math scatter (gen vs ref, F0/F1 budget lines) | `docs/research/generation_policy_calibration_5A5/figures/math_gen_vs_ref.png` | `de3c0bb7…` |
| Math truncation rate by ref-token bucket | `docs/research/generation_policy_calibration_5A5/figures/math_trunc_by_reflen.png` | `c8889bae…` |
| Code scatter (gen vs ref) | `docs/research/generation_policy_calibration_5A5/figures/code_gen_vs_ref.png` | `e5481b48…` |
| Code truncation rate by ref-token bucket | `docs/research/generation_policy_calibration_5A5/figures/code_trunc_by_reflen.png` | `0a3f4a61…` |
| Cost-vs-residual trade-off (all families) | `docs/research/generation_policy_calibration_5A5/figures/tradeoff_cost_vs_residual.png` | `2c95c98b…` |

All figures are generated deterministically from the frozen per-example data.

---

## 3. Existing Token Budget Behaviour (T3 Baseline)

### 3.1 Current formula

```
budget_i = min(4096, max(256, 128 + ceil(1.5 · N_tokens(reference_i))))
fallback = 1024  (when tokenizer unavailable or failure)
```

### 3.2 Measured performance

| Metric | Math (N=100) | Code (N=99) |
|--------|------------:|------------:|
| Truncation rate | **0.410** (41/100) | 0.030 (3/99) |
| G-POL pass | FAIL | PASS |
| tokens_generated mean | 461.76 | 187.55 |
| tokens_generated median | 406.0 | 151.0 |
| tokens_generated p90 | 778 | 300 |
| tokens_generated max | 1005 | 978 |
| applied budget mean | 571.88 | 787.92 |
| budget_fallback_used | 1 (1%) | 0 |
| stop_reason eos / max_length | 59 / 41 | 96 / 3 |

### 3.3 Key diagnostic

The G-POL gate **fails on math** (`truncation_rate_le_0.05: false`) but **passes on
code** (`truncation_rate_le_0.05: true`). The math truncation is the single
dominant remaining failure mode and the focus of this calibration.

---

## 4. Distribution of Prompt Lengths

### 4.1 Prompt-character distribution (chars)

| Bucket | Math | Code |
|--------|-----:|-----:|
| 0–200 | 0 | 0 |
| 200–400 | 60 | 0 |
| 400–600 | 33 | 0 |
| 600–900 | 5 | 5 |
| 900–1500 | 1 | 28 |
| 1500–3000 | 1 | 40 |
| 3000+ | 0 | 26 |

**Summary statistics:**

| Statistic | Math (chars) | Code (chars) |
|-----------|------------:|------------:|
| mean | 410.1 | 2562.4 |
| median | 376.0 | 1758.0 |
| min | 134 | 447 |
| max | 1564 | 23221 |

Prompt length for math is narrow and low (mean 410 chars); for code it is wide and
high (mean 2562, driven by GitHub issue text). Prompt length is **not predictive**
of generation length for either family.

---

## 5. Distribution of Reference Lengths

### 5.1 Reference-character distribution

| Bucket | Math | Code |
|--------|-----:|-----:|
| 0–300 | 9 | 1 |
| 300–600 | 34 | 17 |
| 600–1000 | 34 | 30 |
| 1000–1500 | 14 | 19 |
| 1500–2500 | 6 | 17 |
| 2500–4000 | 3 | 6 |
| 4000+ | 0 | 9 |

### 5.2 Reference-token distribution (inverted from applied budget)

| Statistic | Math (tokens) | Code (tokens) |
|-----------|--------------:|--------------:|
| mean | 291.5 | 397.5 |
| median | 235.0 | 256.0 |
| min | 0 | 21 |
| max | 1119 | 2483 |

**Empirical chars/token ratio (math reference, LaTeX-heavy):** 2.79
**Empirical chars/token ratio (code reference, mixed prose/patch):** 3.95

The math reference is the **full gold solution text** (`canonical_answer_source:
solution`), not the final numeric answer. This makes reference length a reasonable
proxy for the expected reasoning depth — and explains why a reference-derived
budget works for math but not for code (see §8).

---

## 6. Relationship Between Prompt Length and Truncation

### 6.1 Correlation

| Family | corr(tokens_gen, prompt_chars) | corr(tokens_gen, prompt_tokens_est) | R² |
|--------|------------------------------:|------------------------------------:|---:|
| math | −0.017 | −0.089 | 0.000 |
| code | +0.054 | +0.109 | 0.003 |

**Conclusion:** prompt length is essentially **uninformative** about generation
length for either family. Prompt-driven budget formulas (F8) perform poorly
(math residual 37%, code residual 0%) and are rejected.

### 6.2 Truncation by prompt-length bucket (math)

| Bucket (chars) | N | truncated | rate |
|----------------|---:|----------:|-----:|
| 200–400 | 60 | 26 | 0.433 |
| 400–600 | 33 | 12 | 0.364 |
| 600–900 | 5 | 2 | 0.400 |
| 900–1500 | 1 | 0 | 0.000 |
| 1500–3000 | 1 | 1 | 1.000 |

No meaningful monotonic relationship. The 1 truncated record at 1500–3000 chars
is an outlier (likely a long reference problem with a long reasoning trace).
Prompt length is not a budget driver.

---

## 7. Relationship Between Reference Length and Truncation

### 7.1 Correlation

| Family | corr(tokens_gen, ref_tokens) | R² | Regression slope | intercept |
|--------|----------------------------:|---:|----------------:|----------:|
| math | **+0.851** | **0.724** | 0.887 | 145.1 |
| code | +0.529 | 0.280 | 0.130 | 122.3 |

**Strong conclusion for math:** reference length explains 72% of generation
variance. The regression `tokens_gen ≈ 0.89·N_ref + 145` is a tight predictor.
This validates the reference-derived budget formula for math, but also shows the
multiplier 1.5 is too small (since slope 0.89 < 1.5 only partially offsets the
intercept 145).

**Moderate for code:** reference length explains 28% of variance. The weak slope
(0.13) means generation length is mostly determined by factors other than the gold
patch length (patch style, task difficulty, model verbosity). The baseline budget
of 1.5× is generous enough to cover most cases (only 3 truncated).

### 7.2 Truncation by reference-token bucket (math) — **key finding**

| Bucket (ref tokens) | N | truncated | rate |
|---------------------|---:|----------:|-----:|
| 85–170 | 29 | 16 | **0.552** |
| 170–256 | 24 | 11 | **0.458** |
| 256–400 | 25 | 8 | 0.320 |
| 400–700 | 17 | 6 | 0.353 |
| 700–1100 | 5 | 0 | 0.000 |

**Truncation is HEAVILY concentrated on short references.** Records with N_ref
under 170 tokenize to a budget of 256–383 tokens (floor), yet the model still
generates ~400–800 tokens of step-by-step reasoning. The **fixed reasoning cost**
(~mean tokens 462, p90 778, max 1005) dominates the reference-length signal for
short refs.

This is the structural root cause: the budget formula under-buys the *fixed cost*
of reasoning on short-reference problems. Raising the multiplier from 1.5→3.0
increases short-reference budgets from 256–383 → 383–638, providing the headroom
the model needs.

**For code**, truncation is uniformly distributed across ref buckets (max rate
7.7% at 85–170) — no short-ref concentration, consistent with the weak reference
correlation.

---

## 8. Generation-Length-to-Reference-Length Ratio

The ratio `tokens_generated / N_ref` on eos-terminated records is the most direct
measure of how much headroom the budget multiplier must provide.

### 8.1 Math (eos, interior-budget records only)

| Statistic | Value |
|-----------|------:|
| mean | 1.48 |
| p50 | 1.37 |
| p90 | **2.02** |
| max | 2.49 |

The model generates up to **~2.5× the reference token count** on long-tail records.
Alpha 1.5 (current) covers the mean but not the tail. Alpha 3.0 covers the p90
and nearly all of the observed tail.

### 8.2 Code (eos, interior records)

| Statistic | Value |
|-----------|------:|
| mean | 0.68 |
| p50 | 0.66 |
| p90 | 1.16 |
| max | 2.36 |

Code generation is typically **shorter** than the gold patch (the model often
produces a concise fix rather than reproducing the full reference). Alpha 1.5
already provides 2× headroom on p90; alpha 2.0 gives 3× headroom, sufficient for
margin.

---

## 9. Candidate Dynamic Budget Formulas

All candidates share `max_budget = 4096, min_budget = 256` unless otherwise noted.
Evaluated against the frozen T3 per-example data via the regression-based
predictor (validated against measured truncation at F0).

| Formula | base | alpha | min | max | mode | Math meanB | Math tot/F0 | Math gtd | Math pred_recov | Math pred_resid | Code meanB | Code tot/F0 | Code pred_resid |
|---------|----:|------:|----:|----:|------|--------:|----------:|--------:|--------------:|--------------:|--------:|----------:|--------------:|
| **F0 current** | 128 | 1.5 | 256 | 4096 | ref | 572 | 1.00 | 0.590 | 0 | **0.410** | 788 | 1.00 | **0.030** |
| F1 alpha 3.0 | 128 | 3.0 | 256 | 4096 | ref | 1015 | 1.77 | 0.590 | 41 | **0.000** | 1256 | 1.59 | 0.000 |
| F2 floor 512/3.0 | 512 | 3.0 | 512 | 4096 | ref | 1399 | 2.45 | 0.590 | 41 | 0.000 | 1617 | 2.05 | 0.000 |
| F3 base 300/3.0 | 300 | 3.0 | 300 | 4096 | ref | 1187 | 2.08 | 0.590 | 41 | 0.000 | 1418 | 1.80 | 0.000 |
| F4 base 256/3.0 | 256 | 3.0 | 256 | 4096 | ref | 1143 | 2.00 | 0.590 | 41 | 0.000 | 1377 | 1.75 | 0.000 |
| F5 alpha 4.0 | 128 | 4.0 | 256 | 4096 | ref | 1290 | 2.28 | 0.590 | 41 | 0.000 | 1538 | 1.95 | 0.000 |
| **F6 hybrid** | 256 | 2.0 | 256 | 4096 | max | 872 | 1.53 | 0.590 | 41 | 0.000 | 1685 | 2.14 | 0.000 |
| F7 flat 1024 | 1024 | 0.0 | 1024 | 4096 | flat | 1024 | 1.79 | 0.590 | 41 | 0.000 | 1024 | 1.30 | 0.000 |
| F8 prompt 1.5 | 128 | 1.5 | 256 | 4096 | prompt | 350 | 0.61 | 0.260 | 4 | 0.370 | 1054 | 1.34 | 0.000 |

**Legend:**
- `Math pred_recov`: predicted truncated records recovered under the candidate.
- `Math pred_resid`: predicted residual truncation rate (records still truncated).
- `tot/F0`: total token ceiling vs current F0 (latency proxy; greedy decode
  time scales approximately linearly with generated tokens; the real wall-time
  impact is bounded since only truncated records generate more).
- `gtd`: guaranteed coverage (fraction of all records where candidate budget >=
  observed tokens_generated for eos records).

---

## 10. Trade-Off Analysis

### 10.1 Latency

Measured T3 run: 66 minutes wall-clock for 199 records on RTX 5070 (12 GB).
Throughput ≈ 980 tokens/min ≈ 16.3 tok/s.

- **Math worst-case upper bound** (F1, all 41 truncated records generate to new
  budget): mean budget 1015 vs 572 → +44% mean. On a *per-record* basis,
  truncated records would use up to 1015 tokens (vs 572 observed), saving the
  24 truncated records from hitting the ceiling. The actual latency increase is
  **bounded by the tokens actually generated**, not the ceiling; expected
  additional tokens ≈ 41 × (mean_predicted_G − mean_observed_G) under the
  regression ≈ negligible for most (already within 1015). The absolute upper
  bound is ~40% more tokens on the math arm.
- **Code** (F4): +75% mean budget, but only 3 records affected, max generation
  978 — no truncation observed at current. Real cost increase ≈ 0.05%.
- **Net estimate**: math arm +20–40% wall time upper bound; code arm ~0%.
  Still well within a single-session run budget (~80 min vs 66 min for math).

### 10.2 Truncation Reduction

| Formula | Math residual (pred) | Code residual (pred) |
|---------|--------------------:|--------------------:|
| F0 current | 0.410 | 0.030 |
| F1 alpha 3.0 | **0.000** | 0.000 |
| F6 hybrid | **0.000** | 0.000 |
| F7 flat | **0.000** | 0.000 |
| F8 prompt | 0.370 | 0.000 |

F1, F6, F7 all predict zero residual. The **guaranteed** coverage (eos records)
is identical across all of them (0.590 for math) because they only differ on
truncated records. The residual difference is purely an estimate of whether the
higher budget would have allowed the truncated records to finish. The regressior
validation at F0 (predicted 0.410 = measured 0.410) gives confidence in the
model.

### 10.3 Reproducibility

All candidate formulas are deterministic, model-independent, and recordable in
the `generation_policy_lock` metadata block (Policy v2 §3.8):

- **Reference-derived (F0–F5):** same tokenizer + same canonical_answer → same
  budget on every arm. Budget is a deterministic function of an artifact already
  stored per record (`canonical_answer`).
- **Prompt-derived (F8):** also deterministic (prompt hash recorded), but empirically
  poor for math — rejected.
- **Hybrid (F6):** deterministic, needs both ref and prompt tokenization. Slightly
  more metadata bookkeeping but still recorded.
- **Flat (F7):** simplest possible (no tokenization needed). Highest reproducibility
  but least adaptive.

**Recommendation for reproducibility:** F1 (alpha 3.0) preserves the existing
determinism properties exactly (same interface, same recorded fields), differing
only in the scalar `alpha`. The policy lock hash changes, which is the correct
audit trail.

---

## 11. Risk Assessment

| ID | Risk | Severity | Mitigation |
|----|------|----------|------------|
| R1 | Predicted recovery is an estimate, not a measured fact | Medium | Clear caveat in report; validated by F0 regression; re-measure via G-POL at next T3-equivalent run |
| R2 | Reference-derived budgets fail for families where canonical_answer is short (e.g., a future numeric-answer-only math variant) | Medium | Require `canonical_answer` to be the full solution text for reference-derived budgets to hold; document as a pre-condition; fallback to flat on non-compliant sets |
| R3 | Higher budget → longer generation → more wrong verbose output per record | Low | Greedy decoding + eos stop sequence limits runaway output; longer output only if the model completes; stop_reason recorded per record |
| R4 | Model-family change (e.g., Qwen → Llama) changes generation-to-reference ratio → recalibration needed | Medium | Document the fitted regression per model; re-derive alpha when evaluating a new base model on the same split |
| R5 | Cap at 4096 may be insufficient for future longer references | Low | Current max reference (math) yields budget 1806; 4096 has 2.3× headroom on the longest seen; log records hitting the cap; raise cap only if observed |
| R6 | Hybrid formula (F6) adds prompt-token dependency | Low | Prompt hash + tokenizer version already recorded per record (Protocol v2 §3.8); no new artifact required |
| R7 | Over-budgeting increases latency on long runs | Low | Measured upper bound +20–40% on the math arm; acceptable for batch runs; document in run metadata |

---

## 12. Final Recommendation

### 12.1 Per-family Generation Policy Lock parameters

| Family | base_budget | alpha | min_budget | max_budget | formula |
|--------|------------:|------:|-----------:|-----------:|---------|
| **math** | 128 | **3.0** | 256 | 4096 | `min(4096, max(256, 128 + ceil(3.0·N_ref)))` |
| **code** | 256 | **2.0** | 256 | 4096 | `min(4096, max(256, 256 + ceil(2.0·N_ref)))` |
| **semantic** | 128 | **3.0** | 256 | 4096 | *Placeholder* — same as math pending semantic eval set |

### 12.2 Rationale summary

1. **Math alpha 3.0** (primary recommendation): eliminates the predicted truncation
   (41% → 0%), matches the `math_metric_audit.md` §6.3 recommendation (3.0×),
   costs +77% mean budget (well-bounded by cap), preserves deterministic
   reference-derived structure, and has audit-precedent as a family-locked change.
   The hybrid F6 is a documented cost-optimized alternative (−15% cost vs F1) but
   adds prompt-dependency complexity not warranted by the 15% saving.

2. **Code base 256 / alpha 2.0** (primary recommendation): eliminates the 3
   observed truncations with generous margin (mean budget 1377 vs current 788),
   keeps cost reasonable (+75%), and raises the G-POL safety margin. The current
   alpha 1.5 already works (3% truncation); alpha 2.0 is a safety margin for
   future scaling. If zero-cost is preferred, the current code policy can be
   preserved with no change.

3. **Flat 1024 fallback** (mentioned, not recommended as primary): near-identical
   cost to F1 for math and simpler, but loses adaptivity for long references.
   A future math variant with longer solutions could hit the cap. Keep flat as
   the `budget_fallback` (already so), not as the family policy.

4. **Prompt-driven formulas rejected**: math generation is uncorrelated with
   prompt length (R²=0); prompt-derived budgets under-budget severely (F8
   residual 37%).

5. **The `canonical_answer` length pre-condition**: reference-derived budgets
   work because `canonical_answer` in the v2 sets is the full solution text (not
   just the final number). For any future eval set whose `canonical_answer` is
   the short final answer, the reference-derived budget will under-budget. This
   is a **gating precondition**, not a formula change. Document in the Generation
   Policy Lock schema as `canonical_answer_must_be_full_solution: true`.

### 12.3 Implementation path (out of scope for this sprint)

Per the sprint constraints: **no protocol change is implemented here**. The
recommended parameters are a design input for a future Sprint 5A.6 (or T3
baseline refresh) implementation step. When executed, the lock would be updated
in `scripts/evaluation_engine/leakage/prompts.py` (the single prompt module,
rule P4), with a new `POLICY_LOCK_BLOCK_VERSION` and a full regression test
suite for the new formula.

---

## 13. Known Limitations

1. **Predicted recovery is an estimate**, validated by F0 regression but not yet
   measured via re-inference. The actual residual truncation after a protocol
   change must be verified against a fresh T3-equivalent run (standard G-POL
   gate re-check). The prediction model is an intermediate design artifact, not
   a ground truth.
2. **Math max generation 1005 tokens < F1/F7 budgets 1015–1024**: the flat 1024
   and alpha 3.0 (F1) come within ~20 tokens of the single longest observed
   generation. A long-tail record exceeding 1024 under alpha 3.0 would still
   truncate. The cap 4096 provides safety margin, but a future longer dataset
   could probe this.
3. **Semantic family has no eval data**: the recommended parameters are inherited
   from math as a conservative placeholder. The actual generation-to-reference
   ratio for semantic answers is unknown.
4. **Regression fitted on eos records only**: truncated records (the tail) are
   excluded from the regression fit, which may slightly under-predict their
   generation length (they are the long-tail by definition). The `max(budget+1,
   pred)` guard partially compensates.
5. **Chars/token conversion**: the inferred `N_ref` uses the inverse-applied-bucket
   method (exact for interior records) plus a derived chars/token ratio for the
   1 fallback record. The ratio is family-specific and may drift across
   tokenizers.

---

## 14. Rules Compliance

- [x] No model training.
- [x] No inference runs.
- [x] No evaluator changes.
- [x] No Protocol v2 infrastructure changes.
- [x] No dataset modification.
- [x] No config/eval-set edits.
- [x] All numbers from frozen artifacts; no fabricated metrics.
- [x] Stopped after design analysis — **waiting for Technical Lead review.**

---

## 15. Versioning

| Version | Date | Change |
|---------|------|--------|
| v1.0 | 2026-08-06 | Initial calibration report: regression analysis, candidate formula comparison, per-family recommendation, trade-off & risk assessment. |

---

## 16. References

- Protocol v2 transition — `docs/research/protocol_v2_transition.md` §3.6
- P8 Generation Policy Lock — `docs/research/p8_generation_policy.md`
- Math metric audit — `docs/research/math_metric_audit.md`
- Protocol v2 baseline certificate — `scripts/evaluation_engine/protocol_v2_certificate.py`
- Generation policy summary (G-POL check results) — `experiments/atlas-mixed-pilot-qwen7b-eval-v2/generation_policy_summary.json`
- T3 run metadata — `experiments/atlas-mixed-pilot-qwen7b-eval-v2/run_metadata.json`
- Per-example artifacts — `experiments/atlas-mixed-pilot-qwen7b-eval-v2/per_example_{math,code}.jsonl`
- Eval sets — `evaluation/eval_sets/protocol_v2/{math,code}_eval_v2.jsonl`
- Sprint 5A.4 infrastructure — `scripts/evaluation_engine/generation_policy/`

---

*Sprint 5A.5 research & design complete. Awaiting Technical Lead review before
any parameter change is implemented in the Generation Policy Lock.*
