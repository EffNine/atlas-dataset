# Protocol v2 Validation Report

> **Phase:** 8.1 (Protocol v2 validation)
> **Status:** COMPLETED — validation only. No training, no inference, no LoRA
> evaluation, no scaling reruns. Stopped for architecture review before the
> first clean baseline.
> **Date:** 2026-08-05
> **Supersedes for evaluation methodology:** Research Protocol v1.0/v1.1
> evaluation methodology (per `docs/research/protocol_v2_transition.md`).
> **Driving evidence:** `docs/research/protocol_audit_reference_leakage.md`
> (reference leakage confirmed, severity HIGH, 100% of eval records);
> `docs/research/protocol_v2_transition.md` (Protocol v2 spec, tasks T1/T2).

---

## 1. Executive Summary

Protocol v2 (reference-free evaluation) was implemented and validated
end-to-end **without loading a model**. The two frozen v1 eval sets were
rebuilt into new v2 assets with a separate `canonical_answer`, the shared
reference-free prompt module with per-record prompt hashing was implemented,
and the three leakage-detection layers (L1 static scan, L2 runtime guard,
L3 post-hoc audit) were run across every record.

**Verdict: READY for architecture review.** All leakage checks passed for the
clean evaluable sets, the guard correctly caught and held the one code record
whose issue text shares a reference line, and every artifact reproduced
byte-identically.

| Eval set | Evaluable N | Clean | Held | L1 pass | L2 guard | L3 audit | Reproducible |
|----------|-------------|-------|------|---------|----------|----------|--------------|
| `math_eval_v2` | 100 | 100 | 0 | 1.0000 | 100% | 100% | yes |
| `code_eval_v2` | 99 | 99 | 1 | 1.0000 | 100% | 100% | yes |

**Overall validation: PASS (status COMPLETED).** One code record
(`expert_swe_000375`) was held under the fail-closed rule because its GitHub
issue body quotes a library source line that is also the gold patch's final
added line; it was moved to a `*_held.jsonl` sidecar rather than silently
evaluated.

---

## 2. Validation Methodology

The validation suite (`scripts/evaluation_engine/validate_protocol_v2.py`)
ran per family, and independently exercised all three detection layers plus
guard calibration and reproducibility controls. Everything is deterministic,
offline, and stdlib-only (the deterministic ChatML renderer requires no
tokenizer).

### 2.1 Scope

| Layer | Tool | What it verified |
|-------|------|------------------|
| **L1 static scan** (pre-flight) | `leakage/scan.py` | Per record: `canonical_answer` present/non-empty; `canonical_answer_sha256` reproducible; prompt built from `problem` only; canonical answer absent from rendered prompt; `messages` carry no reference; recorded `prompt_sha256` matches recomputed value. Produces `leak_scan_id`. |
| **L2 runtime guard** | `leakage/prompts.guard_reference_free` | Every record's prompt passes the reference-absence guard before it can be used; any violation raises `ReferenceLeakError` (record → HOLD, run aborted). |
| **L3 post-hoc audit** | `leakage/audit.py` | Re-derives each prompt from the frozen record, verifies `prompt_sha256` and `canonical_answer_sha256` match the recorded per-example values, re-runs the guard, and checks the policy-lock block hash. |
| **Guard calibration** | suite controls | Positive control: a reconstructed v1-style leaked prompt (full `messages` incl. gold, rendered + generation turn) MUST trip the guard. Negative control: the clean reference-free prompt MUST pass. |
| **Artifact reproducibility** | suite + `build_eval_v2.py` | Eval-set content checksum matches the manifest; a full rebuild reproduces byte-identical files; `canonical_answer` verified byte-equal to the frozen v1 `solution`. |

### 2.2 Per-record checks (task 4)

For every record in each v2 set the suite verified:

1. **No canonical answer in prompt** — `build_reference_free_prompt` +
   explicit reference-absence assertion.
2. **Prompt hash reproducible** — the prompt built twice produces the same
   `prompt_sha256`; the L3 audit re-derives it a third time and matches it to
   the recorded value.
3. **Leakage guard passes** — L2 guard passes for 100% of evaluable records.
4. **Evaluation artifacts reproducible** — `canonical_answer_sha256`
   recomputed from the stored value; eval-set content checksum vs manifest;
   rebuild byte-identical.

### 2.3 Fail-closed handling

- A missing/empty `canonical_answer` → `ReferenceLeakError` (record invalid).
- Any guard hit → record HOLD + run aborted (validation suite exits non-zero).
- Guard-hitting records are excluded from the evaluable set at build time and
  written to a `*_held.jsonl` sidecar with the guard reason recorded; the
  validation suite re-confirms each held record trips the guard.

---

## 3. Pass/Fail Summary

Overall: **PASS** (exit code 0, `validation_summary.json` status `COMPLETED`).

| Check | `math_eval_v2` | `code_eval_v2` |
|-------|----------------|----------------|
| Records evaluated | 100 | 99 |
| Pass / fail | 100 / 0 | 99 / 0 |
| L1 leak scan id | `5aaa2681d48c432e…` | `e4c23d578af7505e…` |
| L1 leak pass rate | 1.0 | 1.0 |
| L2 guard pass (evaluable) | 100% | 100% |
| L3 audit pass | 100% | 100% |
| Prompt hash reproducible | yes | yes |
| Guard positive control (leaked trips) | 3/3 | 3/3 |
| Guard negative control (clean passes) | 3/3 | 3/3 |
| Held records (fail-closed) | 0 | 1 (`expert_swe_000375`) |
| Content checksum == manifest | yes | yes |
| Rebuild byte-identical | yes | yes |

The L1 scan was also run on the held file as a negative control and correctly
failed closed (exit 1, 0/1 pass).

---

## 4. Leakage Audit Results

### 4.1 No reference in v2 prompts

Every rendered prompt was verified free of its record's `canonical_answer`
via (a) full normalized-reference containment, (b) prefix/line fingerprints,
and (c) token-window containment (first-32 / last-16 reference tokens). Zero
hits across 199 evaluable records (100 math + 99 code).

### 4.2 The guard works — and it caught a real, subtle case

`expert_swe_000375` (scikit-learn, `FeatureUnion` + pandas transform output)
was flagged by the L2 guard at build time:

```
[guard] expert_swe_000375: reference fingerprint 'return pd.DataFrame(data'
        found in prompt
```

Root cause: the GitHub issue body contains a full library stack trace that
quotes `sklearn/utils/_set_output.py`, including the line
`return pd.DataFrame(data_to_wrap, index=index, columns=columns)`. The gold
patch's final added line is that same line. The prompt therefore shares a
reference line with the issue, even though the prompt is built from `problem`
only.

Handling (fail-closed): the record was excluded from the evaluable set and
written to `code_eval_v2_held.jsonl` with `leak_guard_verdict=fail` and the
reason recorded. The validation suite re-confirmed the guard trips on it
(`guard_confirmed_hold=true`). The guard was **not** weakened — this is the
protocol detecting a genuine partial reference overlap that would otherwise
silently contaminate a code correctness measurement.

### 4.3 `messages` are reference-free

All v2 records carry a single user turn only (`messages_user_only` = 100/100
math, 99/99 code). The L1 scan enforces that `messages` contain no assistant
turn and no canonical-answer content.

### 4.4 V1 leak pattern still trips

The positive control reconstructs the historical v1 builder output (full
`messages` incl. gold rendered with the ChatML template + empty generation
turn). The guard raised `ReferenceLeakError` on all control records in both
families — i.e. the exact Phase 5–8 failure mode is still detected.

---

## 5. Reproducibility Results

| Artifact | Result |
|----------|--------|
| `canonical_answer` derivation | byte-equal to frozen v1 `solution` for 200/200 records |
| `canonical_answer_sha256` per record | reproducible from stored value, 200/200 |
| `prompt_sha256` per record | recorded at build; matches recomputed value (L1) and re-derived value (L3), 199/199 |
| Eval-set content checksum vs manifest | matches for both sets |
| Rebuild determinism | full `build_eval_v2.py` re-run produced byte-identical files (`code_eval_v2.jsonl`, `code_eval_v2_held.jsonl`, `math_eval_v2.jsonl`) |
| Frozen v1 untouched | SHA-256 of `phase6_expansion_v1/*` unchanged after all builds |

Template version pinned: `qwen2.5-chatml-deterministic-v1` (policy-lock block
recorded per run; tokenizer-bound hashes are a T3+ inference-time concern and
will be recorded from the pinned tokenizer per Protocol v2 §3.3).

### 5.1 Unit tests

`tests/evaluation_v2/test_leakage.py` (repo pytest convention) covers the
guard pass/fail cases, prompt-hash reproducibility, the renderer format, and
L1 scan verdicts — 16 tests. Run with pytest on the WSL dev box
(`python -m pytest tests/evaluation_v2/test_leakage.py`).

---

## 6. Readiness Assessment

Protocol v2 validation is **complete and PASSING**. The following is now in
place and verified:

1. **eval_v2 datasets** (`evaluation/eval_sets/protocol_v2/`) — `math_eval_v2`
   (N=100) and `code_eval_v2` (N=99 evaluable + 1 held) with `canonical_answer`
   separate from `messages`, deterministic regeneration, provenance preserved,
   frozen v1 untouched.
2. **Reference-free prompt builder** — shared `leakage/prompts.py`, prompt
   hash + fingerprint per record.
3. **Leakage verification** — L1 scan, L2 runtime guard, L3 audit all pass;
   fail-closed confirmed on the held record and on the reconstructed v1 leak.
4. **Validation suite** — `validate_protocol_v2.py` green.

**Not done (by design / per mission):** no baseline inference, no LoRA
evaluation, no scaling reruns, no QEE scoring change, no training. Re-measurement
tasks R1–R7 of `protocol_v2_transition.md` remain **blocked** pending
architecture review of this report.

### 6.1 Recommendations for architecture review

- **Approve T3** (canonical baseline re-measurement) on `math_eval_v2` /
  `code_eval_v2` using the shared prompt module, the Generation Policy Lock,
  and unchanged QEE v2.
- **Decide the `expert_swe_000375` hold.** Options: (a) keep it held (99-record
  code set; still ≥ the N≥30 minimum), or (b) redact the overlapping stack-trace
  line from the issue text and re-derive as a v3 candidate. Recommendation:
  keep held — 99 is a valid, clean code split and redaction alters the authentic
  task text.
- **Extend to `aiml_eval_v2`** once an aiml source split is available (the
  semantic family uses the same shared module; `semantic` policy lock exists).
- Add the L1/L2/L3 gates and the guard unit tests to CI per Protocol v2 §3.5.

### 6.2 Rules compliance

- [x] No training, no inference, no LoRA evaluation, no scaling reruns.
- [x] No QEE scoring logic modified (`scripts/evaluation_engine/v2/*` untouched).
- [x] Frozen v1 eval sets untouched (checksums verified unchanged).
- [x] All numbers measured by the validation suite — nothing fabricated.
- [x] Held record handled fail-closed and documented; guard not weakened.
- [x] Stopped after validation. **Waiting for architecture review.**

---

## 7. Artifacts

| Artifact | Path |
|----------|------|
| Protocol v2 spec / transition plan | `docs/research/protocol_v2_transition.md` |
| Reference-leakage audit (v1) | `docs/research/protocol_audit_reference_leakage.md` |
| **This report** | `docs/research/protocol_v2_validation_report.md` |
| Shared prompt module + guard | `scripts/evaluation_engine/leakage/prompts.py` |
| L1 static scan | `scripts/evaluation_engine/leakage/scan.py` |
| L3 post-hoc audit | `scripts/evaluation_engine/leakage/audit.py` |
| eval_v2 builder (T2) | `scripts/evaluation_engine/build_eval_v2.py` |
| Validation suite (task 4) | `scripts/evaluation_engine/validate_protocol_v2.py` |
| Unit tests | `tests/evaluation_v2/test_leakage.py` |
| `math_eval_v2` / manifest | `evaluation/eval_sets/protocol_v2/math_eval_v2.{jsonl,manifest.json}` |
| `code_eval_v2` / manifest | `evaluation/eval_sets/protocol_v2/code_eval_v2.{jsonl,manifest.json}` |
| Held records | `evaluation/eval_sets/protocol_v2/code_eval_v2_held.jsonl` |
| Build summary | `evaluation/eval_sets/protocol_v2/build_summary.json` |
| L1 scan reports | `metadata/evaluation/protocol_v2_validation/leak_scan_*_eval_v2.json` |
| Per-example validation | `metadata/evaluation/protocol_v2_validation/per_example_*_eval_v2.jsonl` |
| L3 audit reports | `metadata/evaluation/protocol_v2_validation/audit_*_eval_v2.json` |
| Validation summary | `metadata/evaluation/protocol_v2_validation/validation_summary.json` |

---

## 8. Versioning

| Version | Date | Change |
|---------|------|--------|
| v1.0 | 2026-08-05 | Initial Protocol v2 validation: eval_v2 rebuild, shared prompt module, L1/L2/L3 leakage verification, validation suite, readiness assessment. |
