# Robustness Patch RP-001 — `extract_final_answer` bare-`=` crash

> **Phase:** 8.1 / Protocol v2 T3 (canonical baseline) — run blocker fix
> **Classification:** Robustness Patch. **NOT** an evaluation redesign.
> **Date:** 2026-08-06
> **Affected engine:** QEE v2 `scripts/evaluation_engine/v2/math_eval.py`
> **Engine baseline:** frozen at commit `99e88e1` (math_eval.py content hash
> `eff73cb432f56fff654afbf97f8aa3c1acc244b48ee72ca2c27caac598978c02`)
> **Status:** APPLIED + regression-validated. Restores the Protocol v2 clean
> baseline run (T3).

---

## 1. Executive Summary

During the first Protocol v2 clean-baseline inference run
(`experiments/atlas-mixed-pilot-qwen7b-eval-v2`, math family), the frozen QEE
v2 math evaluator raised an unhandled `IndexError: list index out of range` at
`math_eval.py:361` (`extract_final_answer`) and aborted the entire run. The
trigger is a model response whose text **ends in a bare `=`** (the last
character is `=`, so the text after the final `=` is the empty string).

The fix is a one-line defensive guard that treats an empty RHS as "no
extraction from this rule" (falls through to the next extraction rule), which
is exactly the pre-existing behavior for a non-empty-but-blank RHS. **No
scoring logic, normalization, or extraction semantics are changed.** Regression
validation across a 357-case corpus (all 100 `math_eval_v2` canonical answers,
real model smoke outputs, and crafted edge cases) shows **0 output/socre
differences** for every previously non-crashing evaluation, and the 12
previously crashing inputs now evaluate successfully.

---

## 2. Root Cause

`extract_final_answer` extracts a candidate final answer using several
deterministic rules in priority order. Rule 3 takes the RHS of the last `=`
(outside boxed content):

```python
eq_positions = [m.start() for m in re.finditer(r"(?<![<>=!])=(?!=)", text)]
if eq_positions:
    rhs = text[eq_positions[-1] + 1:]            # text AFTER the last '='
    rhs = rhs.splitlines()[0].strip().rstrip(".,;")
    if rhs:
        return rhs
```

When the response's last character is `=`, `rhs == ""`, and
`"".splitlines() == []`, so `rhs.splitlines()[0]` raises `IndexError`. The
response is then lost: the record is neither scored nor fail-closed — the whole
run aborts.

This is a latent robustness bug in the frozen evaluator, triggered by a
malformed-but-permitted model output. The eval engine must **never crash** on
arbitrary candidate text; it must fail closed (return a conservative
un-extractable result) so the record can be scored/held per Protocol v2 §3.10.

Trigger inputs (reproduced on the frozen engine, `commit 99e88e1`):

| Candidate tail | Before patch |
|----------------|--------------|
| `x = y =` | `IndexError` |
| `= =` | `IndexError` |
| `foo\n\nbar =` | `IndexError` |
| `42 =`, `answer =`, `a = b = c =` | `IndexError` |

---

## 3. Patch Rationale

1. **Smallest possible defensive fix.** One line changed, one line of comment.
   Only the empty-RHS branch is guarded.
2. **No scoring change.** For every non-empty `rhs`, the expression evaluates
   identically. The only behavioral change is *crash* → *fall through to the
   next extraction rule* (matching what already happens for `rhs == "   "` or
   `rhs == "\n"`, which produce an empty `splitlines()[0]` and fall through).
3. **No normalization change.** `normalize_math` / `normalize_text` /
   `spoken_to_symbolic` untouched.
4. **No extraction semantics change.** Rule ordering, the `if rhs:` guard, and
   all other rules are byte-identical.
5. **Consistent with fail-closed doctrine.** The engine no longer crashes on
   arbitrary input; a malformed final answer is handled exactly like a blank
   one (extraction rule falls through), and the evaluator subsequently returns
   its normal conservative result (`no_final_answer` → score 0.0 for math,
   or a partial-credit path).
6. **Precedent.** Follows the accepted Phase 5A.4 math-extractor robustness
   patch model (documented, targeted, scoring-preserving).

---

## 4. Affected Function

| Item | Value |
|------|-------|
| Module | `scripts/evaluation_engine/v2/math_eval.py` |
| Function | `extract_final_answer(text: str) -> str` |
| Lines | rule 3 block (previously 358–363; now 358–366) |
| Change | `rhs = rhs.splitlines()[0].strip().rstrip(".,;")` → `rhs = rhs.splitlines()[0].strip().rstrip(".,;") if rhs else ""` (+2 comment lines) |
| Callers | `MathAnswerEvaluator.evaluate` (unchanged) → `QeeV2Engine._type_result` (unchanged) |
| Unaffected | `code_eval.py`, `semantic_eval.py`, `normalize.py`, `engine.py`, all scoring weights/rubrics |

Diff (vs `99e88e1`):

```diff
     eq_positions = [m.start() for m in re.finditer(r"(?<![<>=!])=(?!=)", text)]
     if eq_positions:
         rhs = text[eq_positions[-1] + 1:]
-        rhs = rhs.splitlines()[0].strip().rstrip(".,;")
+        # RP-001: guard empty RHS (text ending in a bare '='); previously this
+        # raised IndexError from splitlines()[0]. Scoring is unchanged for all
+        # non-empty RHS (the ``if rhs`` below now simply falls through).
+        rhs = rhs.splitlines()[0].strip().rstrip(".,;") if rhs else ""
         if rhs:
             return rhs
```

---

## 5. Regression Evidence

Deterministic corpus (`scripts/evaluation_engine/rp001_regression.py`),
357 cases, run identically on the frozen engine (before) and the patched
engine (after), outputs serialized to JSONL and diffed.

Corpus composition:
* 100 `math_eval_v2` canonical answers × (self-eval, self-eval + `" ="`, empty) = 300 cases,
* 9 real Qwen2.5 smoke math candidates, 9 code candidates, 1 code patch pair,
* 20 crafted math edge cases × (reference `"5"`, reference `""`) = 40 cases.

| Metric | Value |
|--------|-------|
| Total cases | 357 |
| Crashes before patch | **12** (all math, bare trailing `=`) |
| Crashes after patch | **0** |
| Previously-working cases with any output/socre diff | **0 / 345** |
| Previously-crashing cases now evaluating successfully | **12 / 12** |
| Code-family cases affected | 0 (code path untouched) |
| **Regression verdict** | **PASS** |

"Identical" means the full serialized evaluator result is byte-equal: `correct`,
`score`, `method`, `extracted_reference`, `extracted_candidate`,
`normalized_reference`, `normalized_candidate`, `reason`, `confidence`, and
(for code) `details`.

Note: the serialized regression corpus and both dumps are reproducible by
re-running:

```
python scripts/evaluation_engine/rp001_regression.py --out <before>.jsonl   # on 99e88e1
python scripts/evaluation_engine/rp001_regression.py --out <after>.jsonl    # on patched
```

---

## 6. Content Hashes

| Artifact | SHA-256 |
|----------|---------|
| `scripts/evaluation_engine/v2/math_eval.py` @ `99e88e1` (frozen) | `eff73cb432f56fff654afbf97f8aa3c1acc244b48ee72ca2c27caac598978c02` |
| `scripts/evaluation_engine/v2/math_eval.py` @ RP-001 (patched) | `27555ec8ea16c777b0ac761b3ddd005574d53b9e6c9093b8fb912cfbbc2928c8` |

The Protocol v2 clean baseline records the patched engine content hash in its
run metadata; the `engine_commit` recorded remains `99e88e1` **plus** the
explicit RP-001 override (see §7), so the exact evaluated engine state is
unambiguous.

---

## 7. Git Commit Recommendation

The frozen-engine commit `99e88e1` is the reproducibility anchor for QEE v2.
RP-001 modifies `math_eval.py`, so the engine is no longer byte-identical to
that commit. To keep future runs reproducible:

1. Commit the patched `math_eval.py` (and the regression harness
   `rp001_regression.py` + this document) as a new engine revision with a
   message in the repo's conventional-commit style, e.g.:
   ```
   fix(evaluation): RP-001 guard extract_final_answer bare '=' crash
   ```
   Reference this document (`docs/research/robustness_patch_rp001.md`) and the
   pre/post content hashes in the commit body.
2. Record the new `engine_commit` + `math_eval.py` content hash in every
   subsequent run's metadata.
3. Do NOT squash with the frozen `99e88e1` QEE v2 commit (audit trail).
4. No commit/push is performed by this task (working-tree change only,
   consistent with the no-commit rule); this is a recommendation for the lead
   agent's next approved commit.

---

## 8. Scope & Rules Compliance

- [x] Robustness patch only — **no evaluation redesign**, no weight/rubric/
      normalization/rule-order change.
- [x] Crash demonstrated before patch (12/357) and absent after (0/357).
- [x] Regression: 0 differences on all 345 previously non-crashing cases.
- [x] `code_eval.py`, `semantic_eval.py`, `normalize.py`, `engine.py` untouched.
- [x] Frozen eval sets / datasets untouched.
- [x] Documented per the mission (root cause, rationale, affected function,
      regression evidence, hashes, commit recommendation).

---

## 9. Versioning

| Version | Date | Change |
|---------|------|--------|
| v1.0 | 2026-08-06 | Initial RP-001 robustness patch (guard empty RHS in `extract_final_answer`). |
