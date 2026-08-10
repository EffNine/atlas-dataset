# Protocol Audit — Reference Leakage in Evaluation Prompts

> **Phase:** 7.3 / Phase 8 protocol verification audit
> **Status:** COMPLETE — audit only. No training, no dataset modification,
> no QEE modification, no model re-runs.
> **Date:** 2026-08-05
> **Verdict:** **CONFIRMED — evaluation prompts exposed reference answers to
> the model in 100% of evaluated records, across every eval runner.**

---

## 1. Executive Summary

A full trace of the prompt pipeline (dataset → message builder → tokenizer →
serialized prompt → model input) shows that every Atlas evaluation runner
constructs the generation prompt from the record's `messages` field, which
contains **both** the user problem **and** the gold reference answer as an
assistant message. With `add_generation_prompt=True`, the serialized prompt
renders the gold patch / expected solution into context and then opens a fresh
assistant turn. The model therefore saw the answer it was being scored against.

Leak rate (verified on the box with the frozen tokenizer):

| Eval set | N | Reference in prompt |
|----------|---|---------------------|
| `code_eval_v1` | 100 | **100 / 100** |
| `math_eval_v1` | 100 | **100 / 100** |
| `math_300m_v0.1/eval.jsonl` | 13 | 13 / 13 |
| `code_300m_v0.1/eval.jsonl` | 2 | 2 / 2 |
| `aiml_300m_v0.1/eval.jsonl` | 14 | 14 / 14 |

The leak is identical for the **baseline and the math-trained adapter**: both
used the same `build_prompt` and the same records, so the serialized prompt
strings sent to `generate()` are byte-identical; only the model weights differ.

---

## 2. Pipeline Trace (Task 1)

### 2.1 Dataset

Eval records (e.g. `code_eval_v1.jsonl`, `math_eval_v1.jsonl`,
`*_300m_v0.1/eval.jsonl`) store the task **and** the answer together:

```json
"messages": [
  {"role": "user",      "content": "<problem / issue text>"},
  {"role": "assistant", "content": "<gold patch / expected solution>"}
],
"problem":  "<problem / issue text>",
"solution": "<gold patch / expected solution>"
```

No `canonical_answer` field exists in these files; the equivalent content lives
in the `messages[assistant]` (and `solution`) fields.

### 2.2 Message builder

Every eval runner uses the same builder (verified in source):

| Runner | Location |
|--------|----------|
| Phase 5A baseline v2 | `experiments/baseline_eval_v0.2/run_baseline_v2.py:96` |
| Phase 5B.1 math pilot | `experiments/lora_pilot_math_v0.1/run_lora_eval.py:50` |
| Phase 6.3 baseline | `experiments/phase6_baseline_eval/run_phase6_baseline_eval.py:86` |
| P8-A adapter | `experiments/atlas-math-small-qwen7b-lora-transfer-v1/run_p8a_eval.py:66` |

```python
def build_prompt(record, tokenizer):
    messages = record.get("messages") or []
    if messages:
        return tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True)
    return f"user: {record.get('problem', '')}\nassistant: "
```

`messages` includes the assistant gold message, so the gold is rendered.

### 2.3 Tokenizer

Qwen2.5 ChatML template: prepends the default system message and renders every
message as `<|im_start|>{role}\n{content}<|im_end|>\n`, then appends
`<|im_start|>assistant\n` (generation prompt).

### 2.4 Serialized prompt → model input

```
<|im_start|>system
You are Qwen, created by Alibaba Cloud. You are a helpful assistant.<|im_end|>
<|im_start|>user
{problem}<|im_end|>
<|im_start|>assistant
{gold patch / expected solution}<|im_end|>      <-- REFERENCE VISIBLE
<|im_start|>assistant                            <-- empty generation target
```

`input_ids = tokenizer(prompt)`, so the reference tokens are part of the model
input. The scoring reference (`get_reference_answer`) returns the **same**
assistant content that was rendered into the prompt.

---

## 3. Captured Prompt Strings (Tasks 2 & 3)

Captured with the frozen `Qwen/Qwen2.5-7B-Instruct` tokenizer (transformers
5.14.1) on the training box. **Baseline and adapter share these exact strings**
(identical records + identical builder).

### 3.1 Code — `code_eval_v1` / `expert_swe_000003`

Serialized prompt, tail (the gold patch is the assistant turn before the empty
generation turn):

```
<|im_start|>user
A direct approach to ITRS to Observed transformations that stays within the ITRS.
...<issue text>...
<|im_end|>
<|im_start|>assistant
diff --git a/astropy/coordinates/builtin_frames/__init__.py b/astropy/...
...
+def itrs_to_observed(itrs_coo, observed_frame):
+    if (np.any(itrs_coo.location != observed_frame.location) or
+            np.any(itrs_coo.obstime != observed_frame.obstime)):
+        ...
+    return itrs_at_obs_time.transform_to(itrs_frame)
<|im_end|>
<|im_start|>assistant
```

**Reference present:** gold patch (unified diff with `+`/`-` lines). ✓

### 3.2 Math — `math_eval_v1` / `expert_math_000021`

```
<|im_start|>user
At a popular restaurant, 8 large pizzas are sold per hour during weekends, ...
(I'll stop here as per your request)<|im_end|>
<|im_start|>assistant
I'll solve the new question.
...
The difference in money made between a weekend day and a weekday is 7680 - 4800 = 2880 dollars.
So the restaurant makes \boxed{2880} dollars more on a weekend day than on a weekday.<|im_end|>
<|im_start|>assistant
```

**Reference present:** expected solution with the final answer `\boxed{2880}`. ✓

### 3.3 Verification results (Task 3)

| Content type | `canonical_answer` | gold patch | expected solution | reference explanation |
|--------------|--------------------|------------|-------------------|-----------------------|
| Field exists in datasets | No (not present) | `solution` / `messages[assistant]` | `solution` / `messages[assistant]` | `messages[assistant]` |
| Rendered into prompt | n/a | **Yes** | **Yes** | **Yes** |

---

## 4. Annotated Transcript (Task 4)

```
<|im_start|>system      # role=SYSTEM (default Qwen system message)
You are Qwen, created by Alibaba Cloud. You are a helpful assistant.
<|im_end|>
<|im_start|>user        # role=USER (the problem / issue)
{problem}
<|im_end|>
<|im_start|>assistant   # role=ASSISTANT — GOLD/REFERENCE (LEAKED)
{gold patch or expected solution}
<|im_end|>
<|im_start|>assistant   # role=ASSISTANT-PROMPT — empty generation target
```

The model is asked to continue after the answer. Every message role is
serialized; the assistant gold is indistinguishable from a legitimate prior
turn from the model's perspective.

---

## 5. Classification (Task 5)

### 5.1 Reference visible

**Yes.** The serialized prompt sent to `generate()` contains the gold patch
(code) and the expected solution (math), as well as the reference explanation,
for 100% of records in every eval set. Verified by (a) direct rendering and (b)
a programmatic leak-rate check on all records.

### 5.2 Severity: **HIGH**

- **Construct validity:** the task actually measured was "continue a
  conversation that already contains the answer," not "generate a fix/solution."
- **Scoring circularity:** the QEE scoring reference equals the assistant
  content that was in-context; the model is scored against what it was shown.
- **Baseline & adapter both contaminated** (identical prompts) — absolute
  scores and transfer deltas are not valid measurements of capability.
- Direction of bias is **not monotonic** (a model may copy, paraphrase, or
  ignore the in-context answer), so scores cannot be trivially corrected
  post-hoc; re-measurement is required.
- **Downstream contamination:** P8-A's neutral Δ_cross, per-example analysis,
  and the P8-A.1/P8-A.2 pattern findings inherit the flaw.

### 5.3 Affected experiments

| Experiment | Runner | Eval split | Status |
|------------|--------|------------|--------|
| Phase 5A baseline v2 | `baseline_eval_v0.2/run_baseline_v2.py` | `*_300m_v0.1/eval.jsonl` (math/code/aiml) | AFFECTED |
| Phase 5B.1 math LoRA pilot | `lora_pilot_math_v0.1/run_lora_eval.py` | `math_300m_v0.1/eval.jsonl` | AFFECTED |
| Phase 5B.2 code LoRA pilot | same lineage (dir not on current disk) | `code_300m_v0.1/eval.jsonl` | AFFECTED (same pattern; verification pending if restored) |
| Phase 6.3 baseline | `phase6_baseline_eval/run_phase6_baseline_eval.py` | `math_eval_v1`, `code_eval_v1` | AFFECTED |
| Phase 7 scale (M1/M2/M3) | same-split evals on leaked splits | `math_eval_v1` | AFFECTED |
| **P8-A** | `atlas-math-small-qwen7b-lora-transfer-v1/run_p8a_eval.py` | `code_eval_v1` | AFFECTED |

**Not affected:** training pipelines (assistant message is the supervised
label — correct SFT usage); QEE v2 scoring functions (pure, unchanged); dataset
construction; the Generation Policy Lock doc (already reference-free).

### 5.4 Recommended remediation (see plan)

Reference-free prompting + automated leakage guard + re-measurement under the
Generation Policy Lock (`docs/research/p8_generation_policy.md`).

---

## 6. Remediation Plan

| # | Action | Where | Gate |
|---|--------|-------|------|
| R1 | Build eval prompts from `problem` (+ optional system instruction) only; **never** render `messages[assistant]` into the prompt. Use `solution`/`canonical_answer` only for scoring. | all eval runners (`build_prompt`) | review |
| R2 | Add a **leakage guard**: pre-flight assertion `reference[:60] not in rendered_prompt` for every record, fail-closed if violated. | eval runner pre-check + CI | review |
| R3 | Adopt the P8-A.2 **Generation Policy Lock** (reference-free template, patch requirement, per-record budget, deterministic extraction, stop/truncation bookkeeping). | `docs/research/p8_generation_policy.md` | review |
| R4 | Re-run **baseline + P8-A** (optionally 5B.1) on the frozen splits under the lock; produce new per-example + aggregate scores. | box (`.venv-eval`) | after approval |
| R5 | **Deprecate** all affected scores (5A, 5B.1, 6.3, Phase 7, P8-A) for research conclusions; retain artifacts with a `REFERENCE_LEAKED` flag. | metadata | review |
| R6 | Add `canonical_answer` as an explicit schema field; document that eval-record `messages` is for human continuity, not prompting. | schemas | review |

---

## 7. Evidence Index

| Evidence | Location |
|----------|----------|
| Serialized code prompt (full, with gold patch) | box `/tmp/prompt_dump.txt` (excerpts in §3) |
| Serialized math prompt (full, with `\boxed{2880}`) | box `/tmp/dump_math_prompt.py` output (§3.2) |
| Leak-rate check (all 5 eval sets, 100%) | box `/tmp/leak_rate.py` |
| Builder source | 4 runner files (§2.2) |
| Dataset schema (messages contain gold) | eval JSONL files (§2.1) |

---

## 8. Rules Compliance

- [x] No training. No dataset modification. No QEE modification.
- [x] No model re-runs — all evidence from frozen artifacts and a prompt-only
  render with the frozen tokenizer.
- [x] Stopped after audit. Waiting for architecture review.
