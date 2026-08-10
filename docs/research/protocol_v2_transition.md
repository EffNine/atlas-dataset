# Atlas Protocol v2 — Clean Evaluation Protocol & Transition Plan

> **Phase:** 8.1 (Protocol v2 transition)
> **Status:** PROPOSAL — documentation only. **No training, no evaluation runs,
> no dataset modification. Stopped for architecture review.**
> **Date:** 2026-08-05
> **Supersedes for evaluation:** Research Protocol v1.0/v1.1 **evaluation
> methodology** (§§5–8). Naming, metadata, provenance, and power rules are
> inherited and extended, not replaced.
> **Driving evidence:** `docs/research/protocol_audit_reference_leakage.md`
> (reference leakage confirmed, severity HIGH, 100% of eval records).

---

## 0. Mission Compliance Map

| # | Task | Addressed in |
|---|------|--------------|
| 1 | Create Protocol v2 | §3 |
| 2 | Implement leakage prevention | §3.4 |
| 3 | Implement automatic leakage detection | §3.5 |
| 4 | Introduce `canonical_answer` separate from `messages` | §3.2 |
| 5 | Require prompt guard, fail closed | §3.3, §3.10 |
| 6 | Migration plan: Phase 5 → 6 → 7 → 8 → Protocol v2 | §5 |
| 7 | Classify every previous experiment | §6 |
| 8 | Produce `docs/research/protocol_v2_transition.md` | this document |

This document is the single reviewable artifact. It defines Protocol v2 in full
(§3), the migration plan and timeline (§5), the experiment classification (§6),
and the mandatory reruns (§7). Upon architecture review approval, Protocol v2
would be promoted to a standalone `docs/research/experiment_protocol_v2.md`
and v1's evaluation sections formally superseded.

---

## 1. Executive Summary

Every Atlas evaluation measurement from Phase 5 through Phase 8 was collected
with the **gold reference rendered into the generation prompt**. The audit
(`protocol_audit_reference_leakage.md`) verified a **100% leak rate** across all
five eval sets (`code_eval_v1`, `math_eval_v1`, `math_300m_v0.1/eval.jsonl`,
`code_300m_v0.1/eval.jsonl`, `aiml_300m_v0.1/eval.jsonl`) in every eval runner
(Phase 5A baseline v2, Phase 5B.1, Phase 6.3, P8-A). The model was scored
against the answer it was shown; the direction of the resulting bias is **not
monotonic**, so no post-hoc correction is possible. **Re-measurement is
required.**

Protocol v2 replaces the deprecated evaluation methodology with a clean,
fail-closed measurement protocol:

1. **`canonical_answer`** becomes a required, explicit field — the sole scoring
   reference, **separate from `messages`** and never rendered into a prompt.
2. **Reference-free prompting** — generation prompts are built from the
   `problem` field only.
3. **Prompt guard** — a mandatory per-record pre-flight assertion that the
   reference is absent from the rendered prompt; any violation **fails closed**
   (record → HOLD, run aborted).
4. **Automatic leakage detection** — static schema scan, runtime guard, and a
   post-hoc audit tool that re-derives prompts and verifies recorded prompt
   hashes.
5. **Generation Policy Lock** — per-family inference policy (code = unified-diff
   forcing, per-record reference-derived token budget, stop-sequence and
   truncation bookkeeping, deterministic extraction, format-failure
   accounting), eliminating the output-policy confound documented in P8-A.1.
6. **Deltas, not absolutes** — every conclusion is a same-split delta against a
   canonical v2 baseline (QEE's documented +2.14 / +0.47 absolute bias is thus
   neutralized).

**Migration is evaluation-only.** The training data is unaffected (the assistant
message is the correct SFT label). Every "needs rerun" item is a **re-inference
of a frozen adapter** under Protocol v2 — no retraining is required or
authorized.

---

## 2. Root Cause Analysis

### 2.1 Primary defect — reference-in-prompt leakage

Full trace in `protocol_audit_reference_leakage.md` §2. Summarized:

```
eval record
  messages: [ {user: <problem>}, {assistant: <GOLD patch/solution>} ]
      │
      ▼
build_prompt() → tokenizer.apply_chat_template(messages, add_generation_prompt=True)
      │
      ▼
serialized prompt ends with  ...<|im_start|>assistant
                              {GOLD}<|im_end|>        ← reference visible
                              <|im_start|>assistant   ← empty generation target
      │
      ▼
scoring reference (get_reference_answer) = the same assistant content
```

Verified leak rate (frozen tokenizer, all runners):

| Eval set | N | Reference in prompt |
|----------|---|---------------------|
| `code_eval_v1` | 100 | **100 / 100** |
| `math_eval_v1` | 100 | **100 / 100** |
| `math_300m_v0.1/eval.jsonl` | 13 | 13 / 13 |
| `code_300m_v0.1/eval.jsonl` | 2 | 2 / 2 |
| `aiml_300m_v0.1/eval.jsonl` | 14 | 14 / 14 |

**Why this invalidates the measurements:**

- **Scoring circularity.** The scoring reference equals the assistant content
  that was in-context; the model is scored against what it was shown.
- **Construct invalidity.** The task actually measured was "continue a
  conversation that already contains the answer," not "solve / fix."
- **Non-monotonic bias.** A model may copy, paraphrase, or ignore the in-context
  answer; absolute scores and deltas cannot be corrected post-hoc.
- **Both arms contaminated.** Baseline and adapter used byte-identical leaked
  prompts, so absolute scores *and* transfer deltas are invalid measurements of
  capability.

### 2.2 Contributing defects

| # | Defect | Evidence | Consequence |
|---|--------|----------|-------------|
| D1 | No `canonical_answer` in eval records; gold lives only in `messages[assistant]`/`solution` | `protocol_audit_reference_leakage.md` §2.1, §3.3 | The runner has no reference-free input; leakage is structurally unavoidable |
| D2 | No prompt guard | no pre-flight assertion exists in any runner | A future builder regression would silently re-leak |
| D3 | No automatic leakage detection | no scan/CI exists | Leakage was discovered by manual audit |
| D4 | Output-policy confound (code) | `p8_generation_policy.md` §2 (patch rate 37%→27%; truncation 81%→14%; `Δ_cross^{M→C}=+0.0018` dominated by format) | Code correctness scores are partly a measure of "did the model emit a unified diff" |
| D5 | QEE absolute bias | `docs/evaluation/qee_human_alignment_report.md` (+2.14); `qee_calibration_phase6.md` (+0.47 proxy) | Absolute scores are inflated; only same-split deltas are usable |
| D6 | Underpowered splits | `PROJECT_STATE.md` §3 (math N=13, code N=2) | Phase 5 pilot conclusions were directional at best |

### 2.3 What is NOT affected

| Area | Reason |
|------|--------|
| Training pipelines | Assistant message is the supervised SFT label — correct usage |
| QEE v2 scoring functions (`scripts/evaluation_engine/v2/`) | Pure, reference/candidate string functions; unchanged by the prompt defect |
| Dataset construction / eval-set selection | Data substrate is valid; needs schema enrichment (`canonical_answer`), not re-selection |
| Static knowledge-quality evaluation (QEE on curated records, no model) | No generation prompt involved |
| Experiment training subsets (Phase 7 M1/M2/M3, P8-A math) | ID-level leakage audit was clean; training data correct |

---

## 3. Protocol v2 — Clean Evaluation Protocol

### 3.1 Scope and governing invariants

Protocol v2 governs **model evaluation** (generation → scoring) for all
training/transfer experiments. It inherits the Atlas evaluation framework
invariants (`docs/evaluation/atlas_evaluation_framework.md`) and adds:

1. **Reference-free prompting is mandatory.** No eval runner may render the
   gold (or any part of it) into a generation prompt.
2. **`canonical_answer` is the sole scoring reference** and is never in the
   prompt.
3. **Prompt guard is mandatory and fail-closed.** Every record must pass a
   reference-absence assertion before `generate()` is called.
4. **Automatic leakage detection is mandatory.** Static scan before runs, and a
   post-hoc audit path for stored artifacts.
5. **Determinism, read-only, network-isolated** (unchanged from v1).
6. **Baseline-first, same-split, minimum-N** (unchanged from v1; default N ≥ 30).
7. **Deltas only.** Conclusions are same-split deltas vs a canonical v2
   baseline, never absolute scores.
8. **Generation Policy Lock applies.** Per-family inference policy recorded and
   identical for every arm of a comparison.

### 3.2 Field contract — `canonical_answer` separate from `messages`

Every Protocol v2 eval record MUST carry:

| Field | Type | Role | Allowed use | Forbidden use |
|-------|------|------|-------------|---------------|
| `problem` | string | Task text | Sole content source for the generation prompt | — |
| `canonical_answer` | string (non-empty) | Gold reference | Scoring only (QEE reference argument) | Prompt rendering |
| `messages` | array | Human continuity / dataset provenance only | None in the eval runner | Prompt rendering (absolute prohibition) |

- **Derivation rule.** `canonical_answer` is derived deterministically at
  eval-set build time: for math = expected solution / final answer; for code =
  gold patch (unified diff); for semantic = reference explanation. A derivation
  script records `canonical_answer_sha256` per record and a per-record human
  spot-check of a derivation sample before the set is locked.
- **Schema.** New eval-set version (e.g. `math_eval_v2`, `code_eval_v2`) written
  under `evaluation/eval_sets/` as new versioned assets. Frozen v1 eval sets are
  **never edited** (immutability rule).
- **Validity rule.** A record without a non-empty `canonical_answer` is
  **invalid for evaluation** (fail-closed: record → HOLD, not scored).
- **Migration source.** `canonical_answer` is derived from the existing
  `solution` / `messages[assistant]` fields of the frozen records; the derived
  value is verified equal (normalized) to the source gold before locking.

> Rationale for the separation: keeping the gold in `messages` invites the
> `apply_chat_template(messages, ...)` failure mode that produced the leak. The
> schema makes the split explicit and checkable by a static scanner.

### 3.3 Reference-free prompt construction and the prompt guard

**Prompt builder (mandatory contract).**

```python
def build_reference_free_prompt(record: dict, tokenizer, policy: PolicyLock) -> str:
    if not (record.get("canonical_answer") or "").strip():
        raise ReferenceLeakError(f"missing canonical_answer: {record['record_id']}")
    # System instruction comes ONLY from the family PolicyLock; never from record.
    system_msg = policy.system_message(record)      # e.g. code diff-forcing template
    user_msg = {"role": "user", "content": record["problem"]}
    prompt = tokenizer.apply_chat_template(
        [system_msg, user_msg], tokenize=False, add_generation_prompt=True)
    guard_reference_free(prompt, record["canonical_answer"], tokenizer, record["record_id"])
    return prompt
```

**Prompt guard (fail-closed).**

```python
def guard_reference_free(prompt, reference, tokenizer, record_id) -> None:
    # 1. Reference fingerprint substrings (first 60 chars, first line, last line)
    #    normalized (whitespace-collapsed) — must NOT appear in normalized prompt.
    # 2. Tokenized containment: first K=32 reference tokens (special-token-stripped)
    #    must NOT be a contiguous subsequence of the prompt token stream.
    # Any positive hit -> ReferenceLeakError -> record HOLD + run aborted.
```

- The guard runs **before** `generate()` for **every record**.
- On violation the runner (a) marks the record `leak=FAILED`, score `null`,
  (b) writes a leak-report line, and (c) **aborts the run** with a non-zero exit
  (fail closed). A run is not "COMPLETED" unless 100% of records passed the
  guard.
- `prompt_sha256` is recorded per record so stored artifacts can be re-audited.

### 3.4 Leakage prevention (design rules)

| Rule | Requirement | Verified by |
|------|-------------|-------------|
| P1 | The eval runner reads only `problem` (+ PolicyLock system message) for prompt text | static scan: `messages` never passed to `apply_chat_template` |
| P2 | `canonical_answer` is stored and read as a separate field; never joined into the prompt | static scan + runtime guard |
| P3 | `messages` array is forbidden input to the prompt builder | static scan on runner source; code-review gate |
| P4 | The prompt builder lives in one shared module (`scripts/evaluation_engine/leakage/prompts.py`) reused by all runners; no per-runner re-implementations | repo-wide grep + CI |
| P5 | Per-record `prompt_sha256` + `canonical_answer_sha256` recorded in per-example output | artifact schema check |
| P6 | Tokenizer template changes are pinned (tokenizer + template version recorded per run) | metadata block |

### 3.5 Automatic leakage detection

Three layers, all deterministic and offline.

**L1 — Static schema scan (pre-flight, per eval set).**
```
scripts/evaluation_engine/leakage/scan.py --eval-file <eval.jsonl> --report <out.json>
```
Per record: `has_canonical_answer`, `non_empty`, `canonical_answer_sha256`,
`prompt_source=problem`, `leak_verdict∈{pass,fail}`. Exit non-zero if any record
fails. Produces a `leak_scan_id` recorded in the run metadata.

**L2 — Runtime prompt guard (during the run).**
Per-record `guard_reference_free` (see §3.3). Fail-closed semantics; 100% pass
is required for a `COMPLETED` status.

**L3 — Post-hoc audit (CI / periodic).**
```
scripts/evaluation_engine/leakage/audit.py --per-example <per_example.jsonl> --eval-file <eval.jsonl>
```
Re-derives the prompt from the frozen record, verifies it matches the recorded
`prompt_sha256`, and re-runs the reference-absence check. Detects builder or
data drift after the fact, including for historical artifacts.

**CI gate.** Any L1/L2/L3 finding blocks the run/report (fail closed). Leak
scans are part of the evaluation pipeline gate, alongside the reproducibility
checklist.

### 3.6 Generation Policy Lock (per family)

Applied **identically** to every arm of a comparison (baseline and adapter),
and recorded as a `generation_policy_lock` metadata block. Inherits and
generalizes `docs/research/p8_generation_policy.md` §4.

| Element | math | code | semantic (aiml) |
|---------|------|------|-----------------|
| System instruction | solve + state final answer explicitly | unified-diff-only (P8-A.2 template §4.1) | answer the AI/ML concept question |
| Token budget | `budget_i = min(4096, max(256, 128 + ceil(1.5 * N_tokens(reference_i))))` | same budget rule | same budget rule |
| Fallback | fixed 1024 (recorded as covariate) | fixed 1024 | fixed 1024 |
| Stop | eos (`<|im_end|>`), pad = eos; `stop_reason∈{eos,max_length}` recorded | same | same |
| Extraction | unchanged QEE v2 math extractor (Phase 5A.4 + 6.4 patches) | deterministic diff extraction wrapper (§4.5 of the lock) | unchanged QEE v2 semantic rubric |
| Format accounting | `no_final_answer` counted as format failure | `patch_emission_rate`, `prose_rate`, `fenced_rate` first-class metrics | `empty` counted as format failure |
| Determinism | greedy, fixed seed, NF4+bf16, engine commit recorded | same | same |

**Gate G-POL** (for code family): patch-emission rate ≥ 0.90, truncation rate
≤ 0.05, majority stop reason = eos, determinism spot-check (two runs → identical
outputs). A run that fails G-POL reports `HOLD` for capability conclusions and
treats residual policy differences as covariates.

### 3.7 Scoring contract

- QEE v2 (`scripts/evaluation_engine/v2/`) is used **unchanged**; the reference
  argument is supplied from `canonical_answer`.
- Per-example + aggregate scores on the full eval split, plus per-example
  improved/regressed/unchanged counts vs the same-split baseline.
- Reported metrics include the policy covariates of §3.6 (patch rate,
  truncation rate, stop-reason counts, mean/median tokens).
- **No conclusion is drawn from absolute scores.** Deltas only.

### 3.8 Metadata additions (v2 run block)

Every v2 run records:

| Field | Required | Notes |
|-------|----------|-------|
| `reference_free` | yes | `true` |
| `leak_scan_id` | yes | L1 scan that cleared the eval set |
| `leak_pass_rate` | yes | must be `1.0` |
| `canonical_answer_sha256` | per record | in per-example output |
| `prompt_sha256` | per record | in per-example output |
| `generation_policy_lock` | yes | template hash, eos/pad ids, budget rule + per-record budgets, extraction rule version |
| `policy_covariates` | yes | per example + aggregate |
| `engine_commit` | yes | QEE v2 committed in git and its commit recorded (P8-A checklist §8.3 blocker) |

### 3.9 Reproducibility checklist v2 (additive to v1 §4)

Items 1–15 of the v1 checklist remain. New items:

| # | Check | Verification |
|---|-------|--------------|
| 16 | Every eval record has non-empty `canonical_answer` | L1 scan `leak_verdict=pass` for 100% |
| 17 | Prompt built from `problem` only; `messages` never rendered | L1 scan + runner source check |
| 18 | Prompt guard passed for 100% of records | `leak_pass_rate=1.0`, `reference_free=true` |
| 19 | `prompt_sha256` + `canonical_answer_sha256` recorded per record | per-example artifact schema |
| 20 | Generation Policy Lock block recorded; policy covariates reported | metadata + aggregate |
| 21 | Baseline is a canonical v2 baseline on the exact same split/config | baseline metadata |
| 22 | Conclusions use same-split deltas, never absolutes | report gate |

**Fail-closed:** any item unverifiable → `HOLD` with null metrics and an
explicit blocker note (v1 §4 fail-closed rule, unchanged).

### 3.10 Fail-closed rules (v2)

1. Missing/empty `canonical_answer` → record HOLD, run not COMPLETED.
2. Any prompt-guard hit → record HOLD, run aborted.
3. `leak_pass_rate < 1.0` → run status `FAILED`/`HOLD`, results unusable.
4. G-POL gate failure → capability conclusions `HOLD`; policy covariates
   reported, never interpreted as capability.
5. Engine commit unrecorded or engine modified mid-run → run invalid (v1 §6.5).
6. Any number not measured → `null` / `[HUMAN MUST SUPPLY]`, never fabricated.

---

## 4. Protocol Comparison — v1 vs v2

| Dimension | v1 (deprecated) | v2 (clean) |
|-----------|-----------------|------------|
| Prompt source | record `messages` (gold assistant turn rendered) | record `problem` only |
| Reference source | `messages[assistant]` / `solution` (same text as prompt) | `canonical_answer` (separate field) |
| Prompt guard | none | mandatory, per-record, fail-closed (§3.3) |
| Leakage detection | none (manual audit) | L1 static scan + L2 runtime guard + L3 post-hoc audit (§3.5) |
| Generation policy | fixed `max_new_tokens=512`, untracked | Generation Policy Lock per family, recorded (§3.6) |
| Format accounting | none (format collapse confounded code scores) | patch-emission / prose / truncation covariates first-class |
| Scoring | QEE v2 (unchanged) | QEE v2 (unchanged), reference from `canonical_answer` |
| Bias handling | absolute scores reported | same-split deltas only |
| Conclusion validity | **invalid** (leaked, 100%) | valid under the clean protocol |
| Naming / metadata / power rules | v1 | inherited + extended (§3.8–3.9) |

---

## 5. Migration Plan — Phase 5 → 6 → 7 → 8 to Protocol v2

### 5.1 Phase mapping

```
Phase 5  (baseline 5A, QEE v2, math pilot 5B.1, code pilot 5B.2)
   │   v1: N=29 / N=13 / N=2  (leaked, underpowered)
   ▼
   v2: canonical baseline refresh (math ≥30, code ≥30)  →  re-measure frozen
       5B.1/5B.2 adapters under v2  →  pilot conclusions re-derived
   Gate: T2 (baselines), T3 (pilots)

Phase 6  (eval expansion 6.2, baseline 6.3, calibration 6.3)
   │   v1: math_eval_v1 / code_eval_v1 (N=100) as data; 6.3 baseline N=200
   │        (leaked); calibration on leaked predictions
   ▼
   v2: eval_v2 rebuild with canonical_answer (T1/T2)  →  Phase 6.3-equivalent
       baseline re-run under v2 = canonical baseline  →  calibration re-run on
       v2 outputs
   Gate: T2 (baseline), T7 (calibration)

Phase 7  (scaling M1/M2/M3)
   │   v1: adapters trained (valid); evals on leaked math_eval_v1
   ▼
   v2: re-inference of frozen M1/M2/M3 adapters on math_eval_v2 under v2  →
       scaling conclusions re-derived. No retraining.
   Gate: T4

Phase 8  (transfer P8-A → P8-D)
   │   v1: P8-A trained + evaluated (leaked); P8-B/C/D pending
   ▼
   v2: P8-A re-measured under Generation Policy Lock + reference-free prompt  →
       P8-B/C/D run under v2 against canonical v2 baselines
   Gate: T5
```

### 5.2 Migration timeline

| Step | Scope | Actions | Gate |
|------|-------|---------|------|
| **T0** | Design (this doc) | Protocol v2 spec + transition plan; classification; rerun registry | **architecture review approval** |
| **T1** | Implementation | Add `scripts/evaluation_engine/leakage/` (prompts.py, scan.py, audit.py, guard); enforce P1–P6; commit QEE v2; unit tests for the guard (pass + fail cases) | unit tests green; runner source check P4 clean |
| **T2** | Eval-set rebuild | Build `math_eval_v2`, `code_eval_v2`, `aiml_eval_v2` (new versioned assets) with derived `canonical_answer`; human spot-check of a derivation sample; L1 scan on each set | L1 `leak_verdict=pass` 100%; spot-check approved |
| **T3** | Baseline re-measurement | Re-run math + code baseline under v2 on the v2 splits (reference-free, Policy Lock) → **canonical baselines** | checklist v2 green; G-POL (code) green |
| **T4** | Phase 5 re-measurement | Re-inference of frozen 5B.1 math adapter (math_eval_v2 ≥30) and 5B.2 code adapter (code_eval_v2 ≥30) | v2 deltas vs canonical baseline |
| **T5** | Phase 7 re-measurement | Re-inference of frozen M1/M2/M3 adapters on `math_eval_v2` | v2 scaling curve; per-example counts |
| **T6** | Phase 8 re-measurement | P8-A adapter re-measured under Policy Lock + reference-free; then P8-B/C/D proceed per v2 | P8-A transfer record under v2; P8-B/C/D gated on v2 baselines |
| **T7** | Calibration + closure | QEE-vs-human calibration re-run on v2 baseline outputs; apply `DEPRECATED`/`RERUN_OK` flags across the §6 ledger; publish v2 as governing protocol | calibration report; ledger closed |

### 5.3 Migration rules

- **No retraining anywhere.** Reruns are inference-only over frozen adapters
  (`scope=eval` / `scope=base`), re-scored with unchanged QEE v2.
- **No frozen asset edited.** New eval sets, new baseline runs, new reports —
  all new versioned artifacts.
- **Sequencing is dependency-ordered** (T3 before T4/T5/T6; T4 pilots before
  any scaling/transfer conclusion).
- Each step requires the prior step's gate to be green and explicit human
  approval before execution.

---

## 6. Classification of Previous Experiments

Legend:

| Class | Meaning |
|-------|---------|
| **Valid** | Measurement/artifact stands and may be used for its intended purpose. |
| **Deprecated** | Conclusion no longer valid; artifacts retained (never deleted) with a `DEPRECATED` flag; not usable for research conclusions. |
| **Needs rerun** | A measurement whose result is invalid and must be re-measured under Protocol v2 (re-inference of a frozen artifact; no retraining). |
| **Unaffected** | Not an affected measurement (training data, plans, infra, static scoring); usable as-is. Migrations required are noted in rationale. |

### 6.1 Phase 5

| Artifact | Class | Rationale / action |
|----------|-------|--------------------|
| `experiments/baseline_eval_v0.2` (5A baseline, N=29) | **Needs rerun** | Leaked builder (`run_baseline_v2.py:96`); underpowered. Re-inference under v2 → part of T3 canonical baseline. |
| `docs/reports/phase_5A_baseline.md`, `phase_5A1_final.md` | **Deprecated** | Baseline conclusions invalid; retained for history. |
| `experiments/lora_pilot_math_v0.1` (5B.1, N=13) | **Needs rerun** | Leaked prompt (`run_lora_eval.py:50`) + N=13. Frozen adapter valid artifact; eval re-measured on `math_eval_v2` ≥30 (T4). |
| `experiments/lora_pilot_code_v0.1` (5B.2, N=2) | **Needs rerun** | Same leaked pattern; N=2 underpowered; dir not on current disk (verify if restored). Re-measure on `code_eval_v2` ≥30 (T4). |
| `docs/reports/lora_math_pilot_analysis.md`, `code_lora_pilot_report.md` | **Deprecated** | Conclusions invalid; mechanism notes retained. |
| QEE v2 engine (`scripts/evaluation_engine/v2/`) | **Unaffected / Valid** | Pure scoring functions; the reference arg will now come from `canonical_answer`. Requires commit (currently untracked) for reproducibility (P8-A §8.3 blocker). |
| Phase 5A.4 math-extractor patch; Phase 6.4 patch | **Unaffected / Valid** | Scoring robustness, not prompt logic. |
| QEE v1–v2 comparison + calibration fit (static scoring of curated records) | **Unaffected** | No model generation prompt involved. |
| `experiments/lora_environment_check` | **Unaffected / Valid** | Infrastructure probe, not a capability measurement. |

### 6.2 Phase 6

| Artifact | Class | Rationale / action |
|----------|-------|--------------------|
| `evaluation/eval_sets/phase6_expansion_v1/math_eval_v1.jsonl`, `code_eval_v1.jsonl` (+ manifests) | **Unaffected** (data) | Valid data substrate; not a measurement. Requires **canonical_answer enrichment** → rebuilt as `*_eval_v2` (T2). Frozen v1 kept, never edited. |
| `experiments/phase6_baseline_eval/` (6.3 baseline, N=200) | **Needs rerun** | Leaked prompts (`run_phase6_baseline_eval.py:86`) on both families. Re-measured under v2 → the canonical baseline (T3). |
| `human_review_calibration_set.json` | **Deprecated** (for calibration) | Labels scored leaked predictions. Reviewer *methodology* retained; labels re-derived on v2 outputs (T7). |
| `docs/evaluation/qee_calibration_phase6.md` | **Deprecated** (calibration numbers) | Calibration on leaked predictions; re-run under v2 (T7). |
| `docs/evaluation/eval_set_expansion_report.md` | **Unaffected** | Data gate (size/provenance/disjointness) conclusions stand. |
| `docs/evaluation/math_extractor_patch_v2.md` | **Unaffected / Valid** | Scoring robustness documentation. |

### 6.3 Phase 7

| Artifact | Class | Rationale / action |
|----------|-------|--------------------|
| `experiments/phase7_scale/subsets/` (M1/M2/M3 training subsets) + audit | **Unaffected / Valid** | Training data; ID-level leakage audit clean. |
| M1/M2/M3 adapters (trained) | **Valid** (artifacts) | Training correct (SFT labels). Eval of these adapters is invalid → see next row. |
| M1/M2/M3 **evaluations** on `math_eval_v1` | **Needs rerun** | Leaked prompt on the eval side. Re-inference of frozen adapters on `math_eval_v2` under v2 (T5). |
| `docs/reports/phase7_m{1,2,3}_report.md`, `phase7_scaling_final_report.md` | **Deprecated** | Scaling conclusions invalid; retained. Re-derived after T5. |
| `docs/research/phase7_scaling_plan.md`, `phase7_dataset_scaling_audit.md` | **Unaffected / Valid** | Design + data audit; no eval conclusion. Plan text to reference Protocol v2 at next revision. |

### 6.4 Phase 8

| Artifact | Class | Rationale / action |
|----------|-------|--------------------|
| `experiments/phase8_transfer/subsets/P8A_math_train.jsonl` + manifest | **Unaffected / Valid** | Training subset; leakage audit (ID-level) clean. |
| `atlas-math-small-qwen7b-lora-transfer-v1` adapter (trained) | **Valid** (artifact) | Training correct. Eval invalid → next row. |
| P8-A **evaluation** on `code_eval_v1` | **Needs rerun** | Leaked prompt (`run_p8a_eval.py:66`) + format confound. Re-measured under Generation Policy Lock + reference-free (T6). |
| `docs/research/p8a_transfer_analysis.md` (P8-A.1) | **Deprecated** (as measurement) | Numbers invalid; the mechanistic finding (format-driven neutral delta) is **retained as design input** — it is the basis of the Generation Policy Lock. |
| `docs/research/p8_generation_policy.md` (P8-A.2) | **Valid / Adopted** | Design input; generalized into Protocol v2 §3.6. |
| `docs/research/p8a_math_to_code_plan.md`, `phase8_transfer_plan.md` | **Unaffected** (plans) | Design docs; to be revised to reference Protocol v2 baselines and gates. P8-B/C/D execution blocked pending T6. |
| Phase 8 gates G1 (eval N=100 expansion) | **Unaffected** | Data gate; met and stands. |

### 6.5 Cross-cutting / infrastructure

| Artifact | Class | Rationale / action |
|----------|-------|--------------------|
| Dataset v1.0 / v0.2 curated assets, training views, release pipeline, automation layer | **Unaffected** | No model-eval measurement involved. |
| `docs/research/experiment_protocol_v1.md` | **Valid** (naming/metadata/power) | §5–8 evaluation methodology superseded by v2; naming/metadata/provenance/power rules inherited. |
| `docs/evaluation/qee_human_alignment_report.md` | **Unaffected** | Static knowledge-quality alignment (QEE vs human on curated records); not a model-eval measurement. |
| `docs/evaluation/qee_v2_design.md` | **Unaffected** | Scoring design doc. |

---

## 7. Mandatory Reruns

All reruns are **inference-only** on frozen adapters/models, under Protocol v2,
scored with unchanged QEE v2. No retraining.

| # | Rerun | Frozen artifacts | Eval set | Gate | Produces |
|---|-------|------------------|----------|------|----------|
| R1 | Math canonical baseline | `Qwen/Qwen2.5-7B-Instruct` rev `a09a3545…` | `math_eval_v2` (N≥30, from `math_eval_v1`) | T3 | canonical math baseline + per-example |
| R2 | Code canonical baseline | same base model | `code_eval_v2` (N≥30, from `code_eval_v1`) | T3 (G-POL) | canonical code baseline + per-example |
| R3 | 5B.1 math pilot re-measure | frozen math LoRA adapter | `math_eval_v2` | T4 | pilot delta vs R1 |
| R4 | 5B.2 code pilot re-measure | frozen code LoRA adapter (restore/verify) | `code_eval_v2` | T4 (G-POL) | pilot delta vs R2 |
| R5 | Phase 7 scaling re-measure | frozen M1/M2/M3 adapters | `math_eval_v2` | T5 | scaling curve + per-example counts |
| R6 | P8-A transfer re-measure | frozen P8-A math adapter | `code_eval_v2` | T6 (G-POL) | `Δ_cross^{M→C}`, `TR_{M→C}` (or N/A), transfer type |
| R7 | Calibration re-run | v2 baseline per-example outputs | human/proxy labels on v2 outputs | T7 | QEE-vs-human calibration on clean data |

**Sequencing:** R1/R2 → R3/R4 → R5 → R6. R7 runs on R1/R2 outputs. Each rerun is
a new experiment ID under Protocol v2 naming (e.g. `atlas-mixed-pilot-qwen7b-eval-v2`
for R1/R2) and passes checklist v2 (§3.9) before any conclusion is drawn.

**Not rerun:** training (valid), dataset construction (valid), static
knowledge-quality scoring (unaffected).

---

## 8. Risks & Mitigations (v2-specific)

| ID | Risk | Severity | Mitigation |
|----|------|----------|------------|
| R29 | `canonical_answer` derivation error during eval_v2 build (truncated/wrong gold) | High | Deterministic derivation script + `canonical_answer_sha256` per record + human spot-check of a derivation sample before set lock |
| R30 | Prompt guard false negative/positive (n-gram containment) | Medium | Tokenized first-K fingerprint (K=32) + normalized substring checks; guard unit tests on frozen leaked prompts (must trip) and clean prompts (must pass); K validated on frozen sets |
| R31 | Format confound persists if Policy Lock not applied | High | G-POL gate mandatory (patch rate ≥0.90, truncation ≤0.05); format covariates reported first-class |
| R32 | QEE absolute bias leaks into conclusions | Medium | Deltas-only rule; no absolute-score gating |
| R33 | Baseline drift / engine change between reruns | Medium | Frozen engine + commit recorded; same-split canonical baseline per family |
| R34 | `messages`-based builder re-introduced by a future runner | High | L1 runner-source scan + P4 shared-module rule + CI gate |
| R35 | Retraining implied by "rerun" misinterpretation | Low | Rerun registry explicitly inference-only; `scope=eval` naming |

---

## 9. What This Document Does NOT Authorize

- **No training or retraining** of any kind.
- **No evaluation runs** — no model loads, no inference, no scoring, until
  architecture review approves Protocol v2 and T1/T2 are implemented and gated.
- **No dataset modification** — the eval_v2 rebuild (T2) is a *proposal* for
  new versioned assets; no frozen file is edited by this document.
- **No automated gating** — human approval remains mandatory for every release,
  training, or gating decision (governance unchanged).
- **No commit/push** — this is a docs-only working-tree change for review.

---

## 10. Rules Compliance

- [x] No training. No evaluation runs. No dataset modification. (docs-only)
- [x] All cited numbers are from frozen project artifacts (audit, reports,
      manifests) — no fabricated metrics.
- [x] Missing/unverifiable items are marked `[HUMAN MUST SUPPLY]` or gated,
      never invented.
- [x] Frozen assets (`curated/`, `raw/`, `review_queue/`, `training_views/`,
      frozen eval sets) are not touched.
- [x] Stopped after producing the transition document. **Waiting for
      architecture review.**

---

## 11. Versioning

| Version | Date | Change |
|---------|------|--------|
| v1.0 | 2026-08-05 | Initial Protocol v2 transition proposal: clean evaluation protocol, leakage prevention/detection, `canonical_answer` contract, Phase 5→8 migration plan, experiment classification, rerun registry. |

---

## 12. References

- Protocol audit (reference leakage, severity HIGH) — `docs/research/protocol_audit_reference_leakage.md`
- Research Protocol v1.0/v1.1 — `docs/research/experiment_protocol_v1.md`
- Generation Policy Lock (P8-A.2) — `docs/research/p8_generation_policy.md`
- P8-A.1 pattern analysis — `docs/research/p8a_transfer_analysis.md`
- P8-A plan — `docs/research/p8a_math_to_code_plan.md`; Phase 8 plan — `docs/research/phase8_transfer_plan.md`
- Phase 7 plan + audit + final report — `docs/research/phase7_scaling_plan.md`,
  `docs/research/phase7_dataset_scaling_audit.md`, `docs/reports/phase7_scaling_final_report.md`
- Eval set expansion — `docs/evaluation/eval_set_expansion_report.md`
- Phase 6.3 baseline + calibration — `experiments/phase6_baseline_eval/`,
  `docs/evaluation/qee_calibration_phase6.md`
- QEE v2 design — `docs/evaluation/qee_v2_design.md`; alignment — `docs/evaluation/qee_human_alignment_report.md`
- Eval runners (leaked builders) — `experiments/baseline_eval_v0.2/run_baseline_v2.py`,
  `experiments/lora_pilot_math_v0.1/run_lora_eval.py`,
  `experiments/phase6_baseline_eval/run_phase6_baseline_eval.py`,
  `experiments/atlas-math-small-qwen7b-lora-transfer-v1/run_p8a_eval.py`
