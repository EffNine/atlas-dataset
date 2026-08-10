# P8 Generation Policy Normalization Protocol

> **Phase:** 8, Experiment A.2 (P8-A.2) — output-policy normalization study
> **Status:** PROTOCOL DESIGN — documentation only. No training, no dataset
> modification, no QEE scoring change. No P8-B execution.
> **Date:** 2026-08-05
> **Purpose:** Determine whether the P8-A neutral transfer result is confounded
> by generation policy, and specify a deterministic **Generation Policy Lock**
> that minimizes output-policy differences between the baseline and the
> math-trained adapter under identical evaluation conditions.
> **Next step:** architecture review, then (if approved) a policy-calibration
> inference run on the same frozen `code_eval_v1` — no retraining.

---

## 1. Executive Summary

P8-A.1 showed that the neutral Δ_cross^{M→C} = +0.0018 is dominated by an
**output-format policy shift**, not by code capability. This study quantifies
that shift (Table 1) and specifies a normalization protocol. It also surfaces a
second, more serious evaluation flaw: **the reference answer was rendered into
the generation prompt** (the record `messages` include the gold assistant
solution; the eval prompt rendered them and appended an empty assistant turn).
Both the baseline and adapter were therefore evaluated on a task where the gold
diff was already visible in context.

The Generation Policy Lock (§5) fixes both problems: reference-free prompt,
diff-only instruction, reference-derived token budget, deterministic diff
extraction, and explicit stop-sequence/truncation bookkeeping — all identical
for baseline and adapter.

---

## 2. Generation Policy Characterization (Task 1)

Method: `analysis/characterize_generation_policy.py` (deterministic, stdlib +
frozen QEE helpers) classifies every frozen per-example prediction on
`code_eval_v1` (N=100) into `patch` / `fenced_code` / `code_tokens` /
`pure_prose`, and measures token length, truncation, and inferred stop reason.
Both runs used greedy decoding, `max_new_tokens=512`, NF4+bf16, and the same
prompt template.

### Table 1 — Baseline vs Math-trained adapter

| Policy signal | Baseline (base) | Math-trained adapter | Δ |
|---------------|-----------------|----------------------|---|
| Patch emission rate | 37.0% (37/100) | 27.0% (27/100) | **−10 pts** |
| Fenced-code rate (fence, no diff) | 62.0% (62/100) | 53.0% (53/100) | −9 pts |
| Pure-prose rate | 0.0% | 9.0% (9/100) | **+9 pts** |
| Code-tokens, no fence | 1.0% | 11.0% | +10 pts |
| Mean token length | 499.9 | 326.2 | −174 |
| Median token length | 512 | 308 | −204 |
| **Truncation rate (≥512)** | **81% (81/100)** | **14% (14/100)** | **−67 pts** |
| Stop reason: eos / max_length | 19 / 81 | 86 / 14 | — |

### 2.1 Interpretation (Task 2)

The two models implement radically different output policies under identical
inference settings:

- **Baseline** is a *long, truncated, code-always* generator: 81% of responses
  are cut off at the 512-token cap, 0% are pure prose, 37% are unified diffs.
  Its correct patches are often the diff appearing early in a truncated
  response.
- **Adapter** is a *concise, EOS-terminating* generator: 86% stop naturally at
  `<|im_end|>`, mean length 326 tokens, and it omits the unified-diff format
  more often (27% patches) while producing pure prose 9% of the time.

Because the QEE v2 code scorer aligns only unified diffs, the measured
correctness is largely a function of **whether a unified diff was emitted**.
The neutral transfer result is therefore confounded by policy, not evidence of
equal code capability.

### 2.2 Reference-in-prompt flaw (verified)

The eval prompt was built with `apply_chat_template(record["messages"],
add_generation_prompt=True)`. The code records' `messages` contain
`[{"role":"user",...},{"role":"assistant",...gold diff...}]`. Rendered output
ends with the gold diff, `<|im_end|>`, then an empty `<|im_start|>assistant`
turn (verified on the box). The scoring reference is the same gold diff.
Consequences:

1. Both baseline and adapter saw the answer in context; scores are partly
   "copy / continue" measurements, not clean generation measurements.
2. All existing code **and math** eval numbers (Phase 6.3 baseline, P8-A) share
   this prompt and are not directly comparable to normalized results.
3. This strengthens the case that format/policy — not reasoning — drove the
   P8-A deltas.

---

## 3. Normalization Protocol (Task 3)

**Goal.** Produce a deterministic inference configuration that (a) removes the
reference from the prompt, (b) forces a single response format (unified diff),
(c) eliminates truncation as a policy lever, and (d) is applied **identically**
to the baseline and the adapter on the same split with the same engine, so any
residual difference is attributable to model capability, not format.

**Protocol steps (execution happens only after architecture review):**

1. **Policy-calibration inference (validation, no retraining).** Run the locked
   generator (§5) on the same frozen `code_eval_v1` (N=100) for both the base
   model and the P8-A adapter. Verify gate G-POL:
   - patch emission rate ≥ 0.90 for both models,
   - truncation rate ≤ 0.05 for both models (or all truncations recorded as
     covariates),
   - stop reason majority = `eos`,
   - determinism spot-check: same config twice → identical outputs.
2. **Score with unchanged QEE v2.** Apply the extraction wrapper (§5.5) to the
   frozen responses, then score with the byte-identical QEE v2
   `CodeAnswerEvaluator`. No QEE code is modified.
3. **Recompute the transfer record** under the normalized protocol:
   baseline aggregate, post aggregate, Δ_cross^{M→C}, per-example
   improved/regressed/unchanged, patch-emission rates. Re-classify
   positive/neutral/negative per protocol v1.1 §8.3.
4. **Report policy covariates** for every run: patch rate, prose rate, fenced
   rate, mean/median tokens, truncation count, stop-reason counts.

### 3.1 Why this minimizes output-policy differences

| Confound in P8-A | Normalization control |
|------------------|------------------------|
| Reference in prompt | Reference-free prompt (§5.1) |
| Diff vs prose vs fenced choice | Patch requirement instruction + format-failure accounting (§5.4) |
| Truncation asymmetry (81% vs 14%) | Reference-derived per-record token budget, identical across models (§5.3) |
| Undefined stop behavior | Explicit eos/pad tokens + stop-reason recording (§5.2) |
| Prose/noise around the diff | Deterministic diff extraction before scoring (§5.5) |

---

## 4. Generation Policy Lock (Task 4)

The lock is the exact inference configuration to be applied to **both** the
base model and the adapter. It is a response-generation + response-preparation
spec; it does **not** modify QEE scoring.

### 4.1 Prompt template

Reference-free, patch-forcing, Qwen ChatML:

```
<|im_start|>system
You are an expert software engineer. Given the code issue, produce ONLY a
unified diff (git patch) that fixes it. Your entire response must be a single
unified diff beginning with "diff --git". Include the file headers
("--- a/", "+++ b/"), the hunk header ("@@ ... @@"), and the changed "+"/"-"
lines. Do not write prose, explanations, summaries, or code fences.
<|im_end|>
<|im_start|>user
{problem_text}
<|im_end|>
<|im_start|>assistant
```

- `{problem_text}` = the record `problem` field (the GitHub issue). The
  assistant gold solution is **excluded** from the prompt.
- Built via `tokenizer.apply_chat_template([system_msg, user_msg],
  tokenize=False, add_generation_prompt=True)`.
- Identical for baseline and adapter. Record the rendered template in the run
  metadata.

### 4.2 Stop sequence

- `eos_token_id = tokenizer.convert_tokens_to_ids("<|im_end|>")` (Qwen2.5 eos).
- `pad_token_id = eos_token_id`.
- Pass both explicitly to `model.generate(...)`; greedy `do_sample=False`.
- No additional stop strings. Each response records `stop_reason ∈ {eos,
  max_length}` from `tokens_generated < max_new_tokens_i`.

### 4.3 Max tokens (per-record, reference-derived)

- `budget_i = min(4096, max(256, 128 + ceil(1.5 * N_tokens(tokenize(reference_i)))))`
  where `N_tokens` counts the gold diff tokens without special tokens.
- `budget_i` is identical for baseline and adapter on record `i` (model-
  independent), so evaluation conditions are equal across models.
- Rationale: a perfect response is never truncated → eliminates the 81%/14%
  truncation asymmetry. Fallback (if per-record budgets are rejected): fixed
  `max_new_tokens = 1024` for all records, with truncation recorded per record.

### 4.4 Patch requirement

- Task-level: the system prompt (§4.1) mandates unified-diff output.
- Measurement-level: responses without a unified-diff marker are flagged
  `format_failure`; the **patch-emission rate** is reported as a first-class
  metric alongside correctness. A format failure scores 0 under the unchanged
  QEE (reference is a patch) but is counted separately — it is not reported as
  a capability loss.

### 4.5 Response extraction (pre-scoring wrapper)

Deterministic extraction of the diff from the generated text:

1. Strip a leading fenced block if the whole response is ```` ```diff ... ``` ````.
2. Locate the first line starting with `diff --git` (or `--- a/`).
3. Emit the substring from that marker to the end of the response (diff
   content only; leading prose dropped).
4. If no diff marker exists → `format_failure` (score 0, counted separately).
5. Feed the extracted diff to the **unchanged** QEE v2
   `CodeAnswerEvaluator().evaluate(reference=gold, candidate=extracted)`.

This is response preparation, not a scoring change: `scripts/evaluation_engine/v2/*`
remain byte-identical.

### 4.6 Inference determinism & bookkeeping

- Greedy decoding, fixed seed, NF4 4-bit + double quant + bf16 compute, same
  base model + adapter load path, `device_map="auto"`.
- Record a `generation_policy_lock` block in the run metadata: rendered prompt
  template hash, eos/pad ids, budget rule + per-record budgets, extraction
  rule version, and the §3 policy covariates.
- Determinism spot-check (two identical runs → identical outputs) is part of
  gate G-POL.

---

## 5. Threats to Interpretation (of the normalized protocol)

1. **Instruction-following asymmetry.** The diff-only instruction may be
   followed differently by the base and the adapter (the adapter was tuned on
   math-style instructions). A residual patch-rate gap would itself indicate a
   policy effect; treat it as a covariate, not capability.
2. **Prompt change is a treatment, not pure measurement.** The normalized
   protocol measures a different task than P8-A. Normalized scores are
   **not comparable** to the original baseline/adapter numbers; only the
   normalized Δ_cross is interpretable, and only within the new protocol.
3. **Reference-derived budget proxies size.** The budget is generous (1.5× gold
   + 128) and model-independent, but a per-record budget loosely reveals
   expected patch size. Use the fixed-1024 fallback if this is judged a leak.
4. **Extraction wrapper risk.** Aggressive extraction could drop a valid
   candidate diff (e.g., multi-hunk patches whose trailing hunks are
   mis-detected). Validate the wrapper on the frozen 100 predictions before
   use; the rule (§5.5) is conservative (diffs run to end-of-response).
5. **Residual metric sensitivity.** Patch added-line similarity remains
   near-binary; the improved/regressed counts will shrink but ±1.0 flips can
   persist for truly-correct-but-differently-written patches.
6. **Single seed / single model.** No variance estimate (T8); a seed sweep is
   still required before a robust symmetry (RQ5) claim.
7. **Prior numbers contaminated.** All Phase 6.3 / P8-A code and math scores
   carry the reference-in-prompt flaw; normalized results must not be averaged
   with them.

---

## 6. Expected Effect

| Metric | P8-A (observed) | Normalized (expected) |
|--------|-----------------|-----------------------|
| Patch emission rate (baseline / adapter) | 0.37 / 0.27 | ≥ 0.90 / ≥ 0.90 (gate G-POL) |
| Pure-prose rate | 0% / 9% | ~0% / ~0% |
| Truncation rate | 81% / 14% | ≤ 5% / ≤ 5% |
| Stop reason | 19 eos / 81 max | majority eos both |
| Δ_cross^{M→C} | +0.0018 (format-dominated) | re-estimated, format-controlled |

**Direction of the re-estimated Δ_cross is not guaranteed.** If the adapter's
23 prose-regressions were omitted diffs it can produce correctly when forced,
Δ_cross could move positive. If the omissions reflect genuinely weaker code
generation, Δ_cross stays ~0 or moves negative. The value of the protocol is
that the estimate becomes **interpretable** — the residual delta reflects
code-reasoning transfer rather than output-format choice.

---

## 7. Scope & Rules Compliance

- [x] No model training. No retraining.
- [x] No dataset modification.
- [x] No QEE scoring modification.
- [x] No P8-B execution.
- [x] Stopped after protocol design — waiting for architecture review.
- [ ] Policy-calibration inference run (G-POL) — **deferred pending approval**.

---

## 8. References

- P8-A evaluation report — `experiments/atlas-math-small-qwen7b-lora-transfer-v1/evaluation_report.md`
- P8-A.1 pattern analysis — `docs/research/p8a_transfer_analysis.md`
- Policy characterization script + JSON — `analysis/characterize_generation_policy.py`,
  `analysis/patterns/generation_policy.json`
- Phase 8 transfer plan — `docs/research/phase8_transfer_plan.md`
- Research Protocol v1.1 — `docs/research/experiment_protocol_v1.md`
