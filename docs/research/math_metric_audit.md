# Atlas Math Metric Audit — the 39 "unparsable" failures

> **Phase:** 8.1 / Protocol v2 T3 follow-up (read-only audit)
> **Status:** COMPLETED — analysis only. **No evaluator patch applied, no
> re-inference, no dataset or Protocol v2 modification.**
> **Date:** 2026-08-06
> **Scope:** the 39 math records from the Protocol v2 baseline
> (`experiments/atlas-mixed-pilot-qwen7b-eval-v2/per_example_math.jsonl`) that
> scored 0.0 via the frozen QEE v2 `unparsable` path.
> **Question:** are these failures caused by a small number of
> normalization/extraction issues, or by genuine model errors?
> **Method:** deterministic, offline, read-only. Uses the frozen evaluator's
> own pure functions (`expressions_equivalent`, `normalize_math`,
> `extract_final_answer`) — nothing is modified.

---

## 1. Executive Summary

**No.** The 39 failures are **not primarily genuine model errors.** Root-cause
clustering of the frozen per-example outputs (including each record's
`stop_reason` and the model's stated final-answer region) gives:

| Cluster | N | % of 39 | Nature |
|---------|---|---------|--------|
| **Truncated / incomplete** | **24** | **61.5%** | Response cut off at `max_length` (per-record budget too small) before a final answer was stated — a **generation-policy (budget) issue**, not a scorer bug or a model error |
| **Syntactic normalization gap** | **6** | **15.4%** | Correct answer is in the extracted candidate, garbled by LaTeX/`$`/`\text`/unit/equation residue — **recoverable by purely syntactic normalization** (proven by re-running the frozen equivalence check) |
| **Extraction-targeting gap** | **6** | **15.4%** | Model produced the correct final answer, but in prose the frozen extractor does not target — an **extraction-semantics limitation** |
| **Genuine wrong answer** | **3** | **7.7%** | Model completed and stated a wrong final answer (`000254`, `000448`, `000602`) |

**Bottom line:** only **3/39 (7.7%)** are genuine completed-wrong answers.
**6/39 (15%)** disappear under purely syntactic normalization. The dominant
cause — **24/39 (61.5%)** — is **generation truncation**, driven by the
per-record token budget `budget_i = min(4096, max(256, 128 + ceil(1.5·N(ref))))`
being smaller than Qwen2.5-7B's long step-by-step math output (the same root
cause as the baseline's 41% math truncation rate).

---

## 2. Method

1. Collect all math records with `correctness < 1.0` from the frozen v2
   baseline (54 total: 39 `unparsable` + 15 parsed-but-wrong).
2. For each of the 39 `unparsable` records, take the frozen
   `extracted_candidate` and apply an ordered cascade of **purely syntactic**
   normalizations (strip `\text{...}` content → strip delimiter/`$`/stray-`\`
   residue → strip trailing unit words → map `\cdot/\times/\div` → expand
   `\dfrac/\tfrac` → unescape braces → split `A = B`). Re-check equivalence
   with the frozen `expressions_equivalent` against the frozen
   `extracted_reference`. First successful transform labels the record.
3. For the rest, run a **final-answer hunter** (brace-balanced `\boxed`,
   `Final Answer:` / `answer:` statements, RHS of last `=`, last number, last
   mathy line) to test whether a better-targeted extraction of the model's
   stated final answer would match the reference.
4. Remaining records classified by `stop_reason`: `max_length` → truncated;
   else → genuine wrong answer. Each cluster was hand-verified against the
   response tail.

Reproducible with `scripts/evaluation_engine/math_metric_audit.py`; full
per-record classification in
`experiments/atlas-mixed-pilot-qwen7b-eval-v2/math_metric_audit.json`.

---

## 3. Root-Cause Table

| # | Cluster | N | % | Root cause | Fix class |
|---|---------|---|----|-----------|-----------|
| C1 | Syntactic normalization gap | 6 | 15.4% | Extracted candidate is the correct value plus LaTeX residue that makes it unparsable | **Robustness (allowed)** |
| C2 | Extraction-targeting gap | 6 | 15.4% | Correct final answer stated in prose; frozen extractor targets mathy lines, not prose statements | Extraction-semantics change (**rejected as patch**) |
| C3 | Truncated / incomplete | 24 | 61.5% | `stop_reason = max_length`; response cut before a final answer | Generation-budget policy (**Protocol v2 change — deferred**) |
| C4 | Genuine wrong answer | 3 | 7.7% | Completed response, stated wrong final value | Model capability |

C1 breakdown by transform (proven with the frozen equivalence check):

| Transform | Records recovered |
|-----------|-------------------|
| Strip `\text{...}`-family content | `000221`, `002131`, `002566` |
| Strip delimiter/`$`/stray-`\` residue | `000021` |
| Strip trailing unit word | `002388` |
| Split `A = B` → RHS | `002426` |

### 3.1 Representative examples

**C1 — syntactic (model correct, garbled):**
| Record | Reference | Frozen extracted candidate | After syntactic cleaning |
|--------|-----------|----------------------------|--------------------------|
| `000021` | `2880` | `\$2880 \]` | `2880` ✓ |
| `000221` | `6` | `6 \text{ hours} \]` | `6` ✓ |
| `002131` | `8` | `8 \text{ hours} \]` | `8` ✓ |
| `002566` | `150` | `150 \text{ pages}` | `150` ✓ |
| `002388` | `64` | `64 \) inches` | `64` ✓ |
| `002426` | `25/4` | `\frac{20}{4} + \frac{5}{4} = \frac{25}{4}` | `25/4` ✓ |

**C2 — extraction targeting (model correct, prose final):**
| Record | Reference | Model's stated final answer (in response) | Frozen candidate captured |
|--------|-----------|------------------------------------------|---------------------------|
| `000764` | `5` | "Max dropped **5** more stones than Maya" | prose line |
| `000989` | `7` | "Benjamin can fill **7** boxes…" | prose line |
| `002074` | `5` | "…the resulting number is **5**" | `from 25:` |
| `002981` | `204` | "…there will be **204** gallons of water left" | prose line |
| `002995` | `22` | "There were **22** people…" | prose line |
| `001907` | `18` | "it will take the snail **18** days" | `17 \text{ days}…)` (mid-reasoning line) |

**C3 — truncated (representative):** `000287`, `000477`, `000512`, `000732`,
`000788`, `000849`, `000900`, `001177`, `001305`, `001600`, `001779`,
`001802`, `001920`, `001951`, `001969`, `001983`, `002179`, `002244`,
`002558`, `002706`, `002722`, `002731`, `002819`, `002942`. E.g. `001177`
(ref `100`) is cut at "…the smallest positive [period]" — the answer is not
stated; `001802` (ref `√3`) is cut at "…is indeed \( \sqrt{3}" — the answer was
just reached when the budget ran out. All 24 have `tokens_generated == budget`.

**C4 — genuine wrong (completed, boxed/statement mismatches):**
| Record | Reference | Model's final answer |
|--------|-----------|----------------------|
| `000254` | `15/13` | boxed `\frac{C}{13}` (symbolic non-answer; the circumference was not used) |
| `000448` | `30` | "add **15** minutes" (one-way only) |
| `000602` | `[-π/2, π/2]` | boxed `[0, π/2]` |

### 3.2 The other 15 math failures (parsed but wrong)

15 further records parsed successfully but with a **genuinely different
value** (methods `number`/`numeric_sampling`, correctness 0 or <0.2):
`000033` (−421200 vs −648), `000046` (0 vs 2), `000328` (−1 vs 8), `000514`
(1320 vs 495), `000706` (1 vs 5), `000708` (0 vs 190), `000831` (3 vs 5/2),
`001000` (1/2 vs 4/5), `001286` (−1 vs 8), `001535` (28 vs 106), `001783`
(2+n vs 2), `002203` (29791 vs 2), `002578` (4 vs 48), `002660` (0 vs √7/2),
`002780` (654 vs 0). These are genuine model errors (not scorer artifacts).
Caveat: `000033`'s reference is suspected of being mis-extracted by the frozen
reference extractor (see §5).

---

## 4. Estimated Impact

### 4.1 Purely syntactic normalization (task 4)

**6 / 39 failures (15.4%) would disappear** under purely syntactic
normalization that does not touch scoring or extraction semantics. This is
proven, not estimated: the frozen `expressions_equivalent` returns True after
cleaning exactly these 6 candidates.

| Scenario | Recovered (of 39) | % |
|----------|-------------------|----|
| **Purely syntactic normalization (RP-002.1–.4)** | **6** | **15.4%** |
| + extraction-targeting robustness (C2) | 12 | 30.8% |
| + generation-budget adjustment (C3) | ~36 | ~92% |
| Genuine wrong answers remain (C4) | 3 | 7.7% |

Notes:
- **C2 (extraction targeting)** would add another 6, but targeting the model's
  stated final answer inside prose **changes which text is scored** — a
  scoring-semantics change → **rejected as a patch** (§5).
- **C3 (truncation)** is not a normalization issue at all. Recovering it
  requires a **larger per-record token budget** — a Generation Policy Lock
  (Protocol v2 §3.6) change, **out of scope** for an evaluator audit and not
  to be made without architecture review.

---

## 5. Proposed Robustness Patches (RP-002 series — NOT applied)

All candidates below are **robustness-only**: they operate only on inputs that
are currently **unparsable** (score 0 via the `unparsable` path) and leave
every currently-parsed input byte-identical in behavior. None changes a
previously-scored value.

| Patch | Change | Recovers | Semantics-safety |
|-------|--------|----------|------------------|
| **RP-002.1** | Strip `\text{...}` / `\mathrm{...}` / `\mathbf{...}` / `\textrm{...}` / `\operatorname{...}` / `\mbox{...}` braced content (human-text scaffolding) | `000221`, `002131`, `002566` | Safe — content was unparsable text |
| **RP-002.2** | Remove inline/display delimiters (`\(` `\)` `\[` `\]`), `$`, and stray `\` before a non-letter (fixes the `\$2880 \]` residue) | `000021` | Safe — delimiter residue only |
| **RP-002.3** | Strip **known** trailing unit words (`hours`, `minutes`, `days`, `pages`, `inches`, `feet`, `gallons`, `people`, `stones`, `meters`, …) after a number — a conservative extension of the frozen `_UNIT_WORDS` list | `002388` | Safe **only** if restricted to full word units; the loose "strip any trailing letter" variant would change `5x`→`5` and is **rejected** |
| **RP-002.4** | If the candidate is an equation `A = B`, compare `B` (the frozen parser cannot evaluate an expression containing `=`) | `002426` | Safe — only affects strings containing `=`, which were unparsable |
| **RP-002.5** | Map `\dfrac/\tfrac/\cfrac` → `\frac`; `\cdot/\times/\ast` → `*`; `\div` → `/` | (none in the 39; parser robustness) | Safe — these tokens always made inputs unparsable |
| **RP-002.6** | Normalize degree notation `^\circ` → strip (affects reference `75^\circ`) | (`002722` reference-side, blocked by truncation) | Safe — degree is a unit, already stripped for `°` |

### Rejected changes (would alter scoring semantics — task 5)

| Change | Why rejected |
|--------|--------------|
| Extract the final answer from prose statements ("…is **204** gallons…") | Changes **which text is scored** → changes scores (0 → 1) for C2 records; an extraction-semantics redesign, not a robustness fix |
| `\pm`/`\mp` → `+-`/`-+` | Multi-valued semantics are not a single numeric equivalent; would silently mis-score |
| Strip any trailing letter after a number (`5x` → `5`) | Value-changing for valid symbolic answers |
| Tuple/list reference handling (e.g. ref `{1, (−1+√5)/2, …}`) | Changes comparison semantics for multi-value references |
| Re-scoring with a different `extract_final_answer` ordering | Ordering is scoring semantics by definition |

---

## 6. Recommendation

1. **Do not conclude "the 39 are model errors."** Only 3/39 (7.7%) are
   completed-wrong; 15% are pure normalization issues, and 62% are budget
   truncation.
2. **Approve RP-002.1–.5** (semantics-preserving normalization robustness) as
   a single scoped patch, following the RP-001 pattern (reproduce → patch →
   regression: before/after byte-identical for all previously-scored inputs,
   only `unparsable`→parsed transitions). Estimated effect: **+6 correct
   (15%)** on the math split.
3. **Flag the generation budget as the dominant math-metric lever.** The
   per-record budget `128 + 1.5·N(ref)` under-budgets Qwen2.5-7B's verbose
   step-by-step output (24/39 truncations). Recommend the architecture review
   consider a **larger math budget multiplier** (e.g. `3.0×`) or a
   higher floor as a **Generation Policy Lock change** — a Protocol v2 policy
   decision, deliberately not made here.
4. **Defer extraction-targeting** (C2) — a scoring-semantics change — to a
   separate design review if the project wants prose-final-answer handling.
5. **Keep the math baseline valid as a same-split protocol reference**; its
   absolute correctness (0.4707) is a **lower bound** under the current budget
   and extractor. Per-example `predicted_response` and `extracted_candidate`
   are recorded, so a future extractor/budget change can re-derive scores
   **without re-inference**.
6. **Human spot-check the reference extraction** of `000033` (suspected
   reference-side mis-extraction: completing the square for `x²+1300x+1300`
   gives `c = −421200`, but the frozen reference extractor captured `−648`).

**Stopped after the audit. No evaluator patch applied, no re-inference, no
dataset or Protocol v2 modification. Waiting for architecture review.**

---

## 7. Versioning

| Version | Date | Change |
|---------|------|--------|
| v1.0 | 2026-08-06 | Initial math metric audit: root-cause clustering of the 39 unparsable failures, syntactic-recovery proof, truncation-dominance finding, RP-002 proposal (not applied), rejected changes, estimated impact. |
