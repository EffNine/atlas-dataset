# Atlas Protocol v2 — Clean Baseline Report

> **Phase:** 8.1 / T3 (Protocol v2 canonical baseline, reruns R1/R2)
> **Experiment:** `atlas-mixed-pilot-qwen7b-eval-v2`
> **Status:** COMPLETED — first fully valid baseline under Protocol v2.
> **Date:** 2026-08-06
> **Model:** `Qwen/Qwen2.5-7B-Instruct` rev `a09a35458c702b33eeacc393d103063234e8bc28` (no LoRA)
> **Eval sets:** `math_eval_v2` (N=100) + `code_eval_v2` (N=99, 1 held)
> **Engine:** QEE v2 frozen `99e88e1` + robustness patch **RP-001**
> (`docs/research/robustness_patch_rp001.md`)
> **Governing protocol:** `docs/research/protocol_v2_transition.md`,
> `docs/research/protocol_v2_validation_report.md`
> **Next step (stopped here):** wait for architecture review. **No scaling
> reproduction has been started.**

---

## 1. Executive Summary

The first fully valid baseline under Protocol v2 was established: a
**reference-free, policy-locked, leakage-verified** inference run of
Qwen2.5-7B-Instruct over the clean `math_eval_v2` (100) and `code_eval_v2`
(99) splits. The run is deterministic (greedy, seed 42, NF4+bf16), passed the
runtime leakage guard on **199/199** records (`leak_pass_rate = 1.0`, 0 holds),
reproduced the pre-registered experiment fingerprint byte-for-byte, and passed
the code-family G-POL gate (patch emission **100%**, truncation **3%**,
majority eos, determinism spot-check identical).

| Metric | Math (N=100) | Code (N=99) |
|--------|--------------|-------------|
| Correctness (QEE v2) | **0.4707** | **0.0089** |
| Reasoning quality (7-dim) | **0.5826** | **0.2711** |
| Hallucination rate (pilot def.) | **0.54** | **1.00** |
| Answer format consistency | **1.00** | **1.00** |
| Patch emission rate | — | **1.00** (99/99) |
| Truncation rate | **0.41** (covariate) | **0.03** |
| Stop reason (eos / max_length) | 59 / 41 | 96 / 3 |
| Tokens (mean / median) | 461.8 / 406.0 | 187.6 / 151.0 |
| G-POL gate | n/a (covariate) | **PASS** (4/4) |

> **Validity caveat (math):** 39/100 math records scored via the frozen
> evaluator's `unparsable` path, **all 39 carrying LaTeX/`$` artifacts** in the
> extracted candidate (trailing `\]`, `$`, `\text{}`, `\frac`). This is the
> known evaluation-correctness robustness gap (PROJECT_STATE §3), now
> quantified; it suppresses the math correctness absolute value and is the
> primary limitation (§6.2). It does **not** affect the protocol's validity
> (reference-free, leakage-free, deterministic, policy-locked).

The baseline is a **protocol artifact**: conclusions must be drawn as
same-split deltas against it (R3–R7 in the migration plan), never as absolutes.

---

## 2. Protocol v2 Readiness (Task 1) — Confirmed

| # | Item | Status | Evidence |
|---|------|--------|----------|
| 1 | `eval_v2` datasets | ✅ | `math_eval_v2` N=100, `code_eval_v2` N=99 + 1 held (`expert_swe_000375`); content checksums match manifests |
| 2 | Prompt builder | ✅ | shared module `scripts/evaluation_engine/leakage/prompts.py` (rule P4); tokenizer-rendered `prompt_sha256` matches the deterministic renderer **199/199** |
| 3 | Leakage guards | ✅ | L1 scan ids reproduced exactly (`5aaa…` math, `e4c2…` code, pass rate 1.0); L2 runtime guard 100% pass this run; L3 audit 100% (validation report) |
| 4 | Protocol certificate | ✅ | `metadata/evaluation/protocol_v2_baseline/protocol_certificate.json`, verdict **READY** |
| 5 | Dataset hashes | ✅ | per-record `canonical_answer_sha256` (100/100, 99/99) and `prompt_sha256` (100/100, 99/99) verified in this run; set checksums match manifests |
| 6 | Experiment fingerprint | ✅ | `metadata/evaluation/protocol_v2_baseline/experiment_fingerprint.json` = `2a60c2423e36c683…`; re-verified by the runner pre-run |

One blocker was found and fixed under governance approval: the frozen math
evaluator crashed (`IndexError`) on a response ending in a bare `=` (RP-001).
Documented in `docs/research/robustness_patch_rp001.md`; regression-proven to
change **no** output/score for any previously-working input (0/345 diffs) and
to fix all 12 crashing inputs.

---

## 3. Methodology (Task 2)

### 3.1 Setup

| Element | Value |
|---------|-------|
| Experiment id | `atlas-mixed-pilot-qwen7b-eval-v2` |
| Scope | baseline inference only (`scope=eval`); no LoRA, no training, no dataset/view/release modification |
| Model | `Qwen/Qwen2.5-7B-Instruct`, revision `a09a3545…` |
| Quantization | 4-bit NF4 double-quant, bf16 compute |
| Decoding | greedy (`do_sample=False`), seed 42, `device_map="auto"` |
| Prompt | reference-free; record `problem` only + family PolicyLock system message; `canonical_answer` never rendered |
| Budget | `budget_i = min(4096, max(256, 128 + ceil(1.5·N_tokens(reference_i))))`; fallback 1024 (recorded covariate) |
| Stop | eos = pad = `<|im_end|>`; `stop_reason ∈ {eos, max_length}` per record |
| Scoring | unchanged QEE v2; reference from `canonical_answer`; code scored on the extracted diff (P8 §4.5 wrapper) |
| Hardware | NVIDIA GeForce RTX 5070 12 GB; torch 2.13.0+cu130; transformers 5.14.1; bitsandbytes 0.50.0 |
| Run window | 2026-08-05 16:51:06 → 17:57:05 UTC (~66 min) |

### 3.2 Metric definitions

- **Correctness** — QEE v2 family scorer (math: extracted-answer numeric
  equivalence; code: gold-patch added-line similarity).
- **Reasoning quality** — QEE v2 weighted 7-dimension continuous quality
  (`quality_continuous`, uncalibrated 0..1).
- **Hallucination rate** — established pilot definition: fraction of records
  with `correct=False AND correctness<0.4`. This is a *wrong-or-low-quality
  flag rate*, not a literal fabrication classifier; the definition is fixed
  across v1 and v2 (comparability) and is reported with this caveat.
- **Answer format consistency** — math: final answer extractable
  (`method ≠ no_final_answer`); code: unified diff emitted.
- **Patch emission rate** (code) — fraction of responses containing a unified
  diff marker (G-POL requirement ≥ 0.90).
- **Truncation rate** — fraction with `stop_reason = max_length`.
- **Generation policy summary** — patch/fenced/code/prose distribution,
  stop-reason counts, tokens, budget-fallback usage.

### 3.3 Guarding and reproducibility

- Runtime guard (L2) ran on every record before generation; `leak_pass_rate
  = 1.0`; 0 records held; run `status = COMPLETED`.
- `prompt_sha256` + `canonical_answer_sha256` recorded per record (all 199).
- Experiment fingerprint re-verified pre-run (match).
- Determinism spot-check (2 greedy generations on a 3-record fixed sample per
  family): **identical = true** for both.
- Code G-POL: patch emission 100% (≥0.90 ✓), truncation 3.03% (≤0.05 ✓),
  majority eos (96/3 ✓), determinism ✓ → **PASS**.
- Engine: commit `99e88e1` + RP-001 (`math_eval.py` sha
  `27555ec8…`), recorded in run metadata.

---

## 4. Baseline Results (Task 3)

### 4.1 Math — `math_eval_v2` (N=100)

| Metric | Value |
|--------|-------|
| Correctness | **0.4707** |
| Reasoning quality | **0.5826** |
| Hallucination rate | **0.54** |
| Answer format consistency | **1.00** |
| Truncation rate (covariate) | **0.41** (eos 59 / max 41) |
| Tokens mean / median | 461.8 / 406.0 |
| Scoring methods | number 43, unparsable 39, numeric_sampling 18 |
| Correctness distribution | 46 × 1.0, 42 × 0.0, 12 × partial (0.03–0.17) |

Math correctness is heavily compressed toward 0/1. **39 records scored 0.0 via
the `unparsable` path, and all 39 carry LaTeX/`$` artifacts** in the extracted
candidate (e.g. `expert_math_000021` produced the correct `$2880` but the
frozen extractor captured `\$2880 \]` → unparsable → 0). See §6.2.

### 4.2 Code — `code_eval_v2` (N=99)

| Metric | Value |
|--------|-------|
| Correctness | **0.0089** |
| Reasoning quality | **0.2711** |
| Hallucination rate | **1.00** |
| Answer format consistency | **1.00** |
| Patch emission rate | **1.00** (99/99 unified diffs) |
| Truncation rate | **0.03** (eos 96 / max 3) |
| Tokens mean / median | 187.6 / 151.0 |
| Scoring method | patch (99/99) |
| Correctness distribution | 91 × 0.0, 8 × partial (0.03–0.17) |

Under the Generation Policy Lock the model emits a well-formed unified diff for
**every** code record (vs 37% under v1), but the patches rarely match the gold
added lines (correctness 0.0089). This is a genuine capability ceiling of the
7B base on SWE-bench-grade tasks under reference-free prompting — the v2 code
baseline is an honest (near-floor) measurement.

### 4.3 Generation policy summary

| Signal | Math | Code |
|--------|------|------|
| Format distribution | math 100 | patch 99 |
| Stop: eos / max_length | 59 / 41 | 96 / 3 |
| Tokens mean / median | 461.8 / 406.0 | 187.6 / 151.0 |
| Budget fallback (1024) used | 1 | 0 |
| G-POL gate | covariate only | PASS |

---

## 5. Comparison vs Deprecated Protocol v1 (Task 4)

**Scope:** metric shifts, protocol effects, and output-policy differences
only. **Not** a performance comparison: the v1 baseline is deprecated (100%
reference-in-prompt leakage, `protocol_audit_reference_leakage.md`). v1 data =
frozen Phase 6.3 baseline on the same record set (`phase6_baseline_eval`).

### 5.1 Metric shifts (same split, v1 leaked → v2 reference-free)

| Metric | Math v1 → v2 | Code v1 → v2 |
|--------|--------------|--------------|
| Correctness | 0.7779 → **0.4707** (Δ **−0.307**) | 0.2217 → **0.0089** (Δ **−0.215**) |
| Reasoning quality | 0.793 → **0.583** | 0.417 → **0.271** |
| Hallucination rate | 0.22 → **0.54** | 0.76 → **1.00** |
| Per-record Δ classification | 7 improved / 38 regressed / 55 unchanged | 6 / 32 / 61 |

**Interpretation (protocol effect, not capability):** removing the gold from
the prompt removes the "continue the shown answer" advantage. The v1 model was
scored against the answer it was shown; its high scores were construct-invalid.
The v2 numbers are the honest reference-free measurement. The math shift is
further amplified by the 39-record extraction artifact (§6.2), which applies
only to the v2 reference-free outputs.

### 5.2 Code extraction-policy isolation

The frozen v1 code predictions were re-scored through the v2
diff-extraction + QEE pipeline (no re-inference) to separate prompt-policy from
extraction-policy effects:

| Signal | v1 raw | v1 extraction-adjusted | v2 reference-free |
|--------|--------|------------------------|-------------------|
| Code correctness | 0.2239 | 0.2266 | **0.0089** |
| Patch emission rate | 37.4% | — | **100%** |

The extraction wrapper changes v1 almost nothing (0.2239 → 0.2266), so the v2
collapse is attributable to the **reference-free prompt + policy lock**, not
to scoring/extraction differences.

### 5.3 Output-policy differences

| Policy signal | Math v1 → v2 | Code v1 → v2 |
|---------------|--------------|--------------|
| Patch emission rate | — | 37% → **100%** |
| Truncation rate | 14% → 41% | 81% → **3%** |
| Stop reason eos | 86% → 59% | 19% → **97%** |
| Mean / median tokens | 212 / 169 → 462 / 406 | 500 / 512 → 188 / 151 |

The policy lock eliminated the v1 code policy confound (the 81% truncation /
37% patch asymmetry documented in P8-A.1). The v1→v2 math truncation rise is a
budget artifact: v2 per-record budgets are smaller than v1's fixed 512 for
short references, while Qwen2.5-7B emits long step-by-step solutions; recorded
as a covariate, not a gate.

### 5.4 Protocol effects (v1 → v2)

| Dimension | v1 (deprecated) | v2 (this run) |
|-----------|-----------------|---------------|
| Prompt source | `messages` (gold rendered) | `problem` only |
| Reference source | `messages[assistant]` (same as prompt) | `canonical_answer` (separate field) |
| Leakage | 100% (5 eval sets, all runners) | 0% (L1/L2/L3 pass, 199/199) |
| Prompt guard | none | per-record, fail-closed |
| Generation policy | fixed 512, untracked | Policy Lock, recorded covariates |
| Format accounting | none (format confounded code) | patch/prose/truncation first-class |
| Score comparability | invalid (leaked) | valid; deltas-only rule |

---

## 6. Validity Statement and Limitations

### 6.1 Validity statement

This run satisfies the Protocol v2 reproducibility checklist (§3.9): clean
eval sets with non-empty `canonical_answer`; prompts built from `problem`
only; runtime guard passed 100% (`leak_pass_rate = 1.0`); per-record
`prompt_sha256`/`canonical_answer_sha256` recorded; Generation Policy Lock
block recorded with covariates; G-POL (code) green; determinism spot-check
identical; fingerprint re-verified; engine pinned (`99e88e1` + documented
RP-001). **The protocol is valid and the baseline is usable as the canonical
v2 same-split reference** for deltas in reruns R3–R7. No conclusion is drawn
from absolute scores.

### 6.2 Limitations

1. **Math correctness is suppressed by a frozen-extractor robustness gap.**
   39/100 math records scored 0.0 via `unparsable`, all with LaTeX/`$`
   artifacts in the extracted candidate. The math absolute correctness
   (0.4707) is therefore a **lower bound**; per-record `extracted_candidate`
   is recorded so a fixed extractor can re-derive scores without re-inference.
   This is the known evaluation-correctness issue (PROJECT_STATE §3), now
   quantified on the v2 baseline. **Recommendation:** RP-002 (extractor
   normalization of `\[…\]`/`$…$`/`\text{}`/`\frac` tails) before using math
   correctness for capability conclusions; the baseline remains valid as a
   same-split protocol reference regardless.
2. **Hallucination rate is a blunt wrong-or-low flag**, not a fabrication
   classifier; code 1.00 largely reflects "patch differs from gold", not
   invented content. Interpret with this definition in mind.
3. **Code correctness is near-binary** (patch added-line similarity):
   correct-but-differently-written patches score ~0 or 0.5; per-example
   improved/regressed counts will be ±1.0-heavy.
4. **Math truncation 41%** is a budget artifact (v2 per-record budgets vs long
   step-by-step generations); recorded as covariate. A budget recalibration
   (e.g., larger math multiplier) is a policy decision for review.
5. **Single model, single seed, single run.** No variance estimate (protocol
   T8 seed sweep remains outstanding).
6. **One code record held** (`expert_swe_000375`, guard-confirmed): code split
   is 99, still ≥ N=30 minimum.
7. **RP-001 changes the frozen engine file** (documented, regression-proven
   scoring-neutral); the engine commit no longer byte-matches `99e88e1`.
   Commit the patched `math_eval.py` as the new engine revision before any
   further runs (see RP-001 §7).
8. **Leakage/prompt modules are not yet git-tracked** in this working tree
   (untracked files). Committing them is required for full reproducibility
   (certificate records their content hashes as a stopgap).

---

## 7. Recommendation

1. **Approve this run as the canonical Protocol v2 baseline**
   (`atlas-mixed-pilot-qwen7b-eval-v2`) and the reference point for all future
   same-split deltas (reruns R3–R7).
2. **Next (architecture review gate):** re-inference of the frozen 5B.1/5B.2,
   M1/M2/M3, and P8-A adapters under v2 against this baseline — **not** scaling
   reproduction.
3. **Address the math extractor gap** (RP-002, §6.2.1) as a
   metric-improvement item, scoped as a robustness patch (RP-001 pattern).
4. **Commit** the Protocol v2 work (leakage module, builders, runner, RP-001,
   certificate, this baseline) so future runs are pinned to git, not to
   untracked working-tree state.
5. **Do not interpret absolute v2 scores**; use same-split deltas only.

**Stopped after the clean baseline. No scaling reproduction started. Waiting
for architecture review.**

---

## 8. Artifacts

| Artifact | Path |
|----------|------|
| Run metadata (status, engine, fingerprint, guard) | `experiments/atlas-mixed-pilot-qwen7b-eval-v2/run_metadata.json` |
| Per-example (math / code) | `experiments/atlas-mixed-pilot-qwen7b-eval-v2/per_example_{math,code}.jsonl` |
| Aggregates + G-POL | `experiments/atlas-mixed-pilot-qwen7b-eval-v2/aggregate_{math,code}.json` |
| Generation policy summary | `experiments/atlas-mixed-pilot-qwen7b-eval-v2/generation_policy_summary.json` |
| v1 vs v2 comparison | `experiments/atlas-mixed-pilot-qwen7b-eval-v2/v1_vs_v2_comparison.json` |
| Config | `experiments/atlas-mixed-pilot-qwen7b-eval-v2/config.json` |
| Run log | `experiments/atlas-mixed-pilot-qwen7b-eval-v2/run_t3_full.log` |
| Protocol certificate | `metadata/evaluation/protocol_v2_baseline/protocol_certificate.json` |
| Experiment fingerprint | `metadata/evaluation/protocol_v2_baseline/experiment_fingerprint.json` |
| RP-001 robustness patch | `docs/research/robustness_patch_rp001.md` |
| Baseline runner | `scripts/evaluation_engine/run_baseline_t3.py` |
| v1↔v2 comparison tool | `scripts/evaluation_engine/compare_v1_v2_baseline.py` |

---

## 9. Versioning

| Version | Date | Change |
|---------|------|--------|
| v1.0 | 2026-08-06 | First Protocol v2 clean baseline (math_eval_v2 N=100, code_eval_v2 N=99), RP-001 run blocker resolved, v1 protocol-effects comparison, validity statement + limitations. |
