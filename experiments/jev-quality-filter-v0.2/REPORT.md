# JEV Quality Filter v0.2 — Report: adaptive automated quality router

**Workflow evaluation only. No precision / recall / accuracy claims: there is
no independent ground truth in this experiment, Phase-2 human labels were
never read, JEV outputs are not ground truth, and the old human-calibration
results were not used to choose anything.** All policies are uncalibrated
operating points. "Most practical" below means the measured cost/coverage
tradeoff only.

## 0. What ran

- **Records:** the same 500 JEV-pilot records as v0.1 (math 150, code 100,
  general 150, systems 100). **JEV was not rerun** (zero new JEV cost);
  all routing used the stored `jev_results.jsonl` (`jev-1.13.0`).
- **Deterministic validation:** 500/500 VALID (same well-formed pilot data as
  v0.1; the INVALID→REJECT gate is implemented and unit-tested but untriggered
  in-sample).
- **JEV errors / degraded signals in-sample:** 0. All 500 records carry the
  complete signal set; the degraded-signal and JEV-error paths are
  implemented and unit-tested but untriggered in-sample.
- **Router:** `v0.2-router-v1` (exact formula in README.md and `router.py`
  docstring), three policies on the same 500 records.
- **AI-2:** blind independent review, same provider/model/prompt/rubric as
  v0.1 (`agnes-2.5-flash`, temperature 0). 297 verdicts reused by reference
  from v0.1 (identical blind prompt input); **7 new top-up calls** for records
  the adaptive router newly escalated (4.2 s wall, all 7 verdicts ACCEPT —
  small-n observation, not a finding). AI-2 never received JEV scores,
  confidence, bands, decisions, or reasoning (asserted by tests).
- **Effective AI-2 coverage:** 304 unique records (297 stored + 7 new);
  verdict split ACCEPT 329 / REJECT 34 / AMBIGUOUS 2 / ERROR 1.
- **Atlas source data:** untouched (reads only; new directory only —
  verified §8).

## 1. What signals does the adaptive router use?

Six stored-JEV signal families plus the deterministic check (weights are
documented judgment, not fitted values):

| signal | role in C | weight/penalty |
|--------|-----------|----------------|
| correctness `c` | positive support (0.40) + disagreement anchor | largest support term |
| quality `q/4` | positive support (0.25) + disagreement term | second support term |
| problematic `p` | direct penalty (0.50) + disagreement term + `p>=0.80` hard rail | largest single term |
| adherence `a` | positive support (0.15) + disagreement term | stabiliser |
| category consistency `k` | positive support (0.10) + disagreement term | stabiliser |
| training value `t/4` | positive support (0.10) | stabiliser |
| quality / training-value probability spreads `qs`, `ts` | uncertainty `U=(qs+ts)/2`, penalty 0.25 | doubt, not danger |
| cross-dimension disagreement `D` (mean of 4 absolute gaps vs `c`) | penalty 0.25 | doubt, not danger |
| deterministic VALID/INVALID | INVALID→REJECT rail; missing/malformed/JEV-error → escalate, never auto-route | hard rails |

`C = clip(S − 0.50·p − 0.25·U − 0.25·D, 0, 1)`, rounded to 4 decimals.
Observed C range on the 500: 0.0–0.858, median 0.582.

## 2. How does each policy differ?

Identical C function; only the band thresholds differ (fixed before the run,
never tuned against labels or outcomes):

| policy | tau_lo (≤ → LOW) | tau_hi (≥ → HIGH) | operating intent |
|--------|------------------|-------------------|------------------|
| conservative | 0.45 | 0.75 | widest escalation band; hardest auto-accept |
| balanced | 0.35 | 0.65 | middle operating point |
| aggressive | 0.25 | 0.55 | narrowest escalation band; most auto-routing |

Boundary semantics: equality routes outward (`>=` HIGH, `<=` LOW).
The `p>=0.80` rail is identical across policies; in-sample it never fired
independently (the 6 records with `p>=0.80` all score C=0.0 and route LOW via
confidence — the rail is defense-in-depth, exercised only by unit tests).

## 3. What percentage is handled without AI-2?

| policy | auto-ACCEPT (HIGH) | auto-REJECT (LOW) | handled w/o AI-2 (JEV-only) |
|--------|-------------------|-------------------|------------------------------|
| conservative | 109 (21.8%) | 164 (32.8%) | **273 (54.6%)** |
| balanced | 198 (39.6%) | 123 (24.6%) | **321 (64.2%)** |
| aggressive | 271 (54.2%) | 87 (17.4%) | **358 (71.6%)** |

## 4. What percentage requires AI-2?

conservative **227 (45.4%)** · balanced **179 (35.8%)** · aggressive
**142 (28.4%)**. Union over policies: 304 unique records (297 reused stored
verdicts + 7 new calls). Final distributions:

| policy | final ACCEPT | final REJECT (incl. quarantine) | unresolved AMBIGUOUS |
|--------|--------------|---------------------------------|----------------------|
| conservative | 324 (64.8%) | 176 (35.2%) | 0 |
| balanced | 363 (72.6%) | 135 (27.0%) | 2 (0.4%) |
| aggressive | 400 (80.0%) | 98 (19.6%) | 2 (0.4%) |

Unresolved are the known AI-2 AMBIGUOUS/transport-ERROR records, which fall
inside the balanced/aggressive bands but outside conservative's; they would
route to human review in any real deployment (none performed here).

## 5. How much additional token/latency cost does escalation create?

JEV first pass (reused, not respent): 758,606 in / 50,000 out tokens
(~1,517/~100 per record), mean latency 0.322 s/rec. AI-2 is ~11–14× slower
per call with ~4.6× the output tokens per record (longer rationales).

| policy | AI-2 in/out tokens (attributed) | AI-2 total | combined total | vs JEV-only (+%) | AI-2 mean latency |
|--------|---------------------------------|------------|----------------|------------------|-------------------|
| conservative (227 esc.) | 355,258 / 92,603 | 447,861 | 1,256,467 | **+55%** | 3.41 s |
| balanced (179 esc.) | 291,423 / 81,990 | 373,413 | 1,182,019 | **+46%** | 4.13 s |
| aggressive (142 esc.) | 244,368 / 71,761 | 316,129 | 1,124,735 | **+39%** | 4.55 s |

Marginal cash-equivalent spend for v0.2 itself was 7 calls in 4.2 s; the
rest is attributed reuse. No USD figures: apply the operator's price card.
A production prompt could cap AI-2's long rationales (the dominant output
cost), same observation as v0.1.

## 6. How often do JEV and AI-2 disagree?

"Disagreement" = AI-2 verdict vs the documented JEV-lean heuristic
(`REJECT-lean` if `correct<0.6 or quality<2.5 or problematic>=0.30`, else
`ACCEPT-lean`; heuristic only, NOT ground truth), over escalated records
with an ACCEPT/REJECT verdict:

| policy | agree | disagree (rate) | direction: AI-2 ACCEPT where lean REJECT | direction: AI-2 REJECT where lean ACCEPT |
|--------|-------|-----------------|------------------------------------------|------------------------------------------|
| conservative | 191 | 36 (**15.9%**) | 28 | 8 |
| balanced | 110 | 67 (**37.9%**) | 61 | 6 |
| aggressive | 49 | 91 (**65.0%**) | 89 | 2 |

Disagreement is overwhelmingly one-directional: AI-2 ACCEPTs where the JEV
lean points REJECT. The reverse (AI-2 refuting a lean-ACCEPT record: 8 / 6 /
2 cases) is rare but operationally the most interesting — v0.1 documented
examples (dead-code params, self-contradictory reasoning, missed solutions).
This experiment cannot say whether the pattern means a conservative JEV
middle band or a lenient AI-2. Do not read it as either model being right.

Disagreement direction by signal region (escalated records only):

- **By confidence:** disagreements concentrate below C≈0.60. Conservative
  (band 0.45–0.75): 31/36 disagreements in C 0.40–0.60, 5 above 0.60.
  Balanced: 61/67 below 0.60 (16 of 19 records under C 0.40). Aggressive:
  89/91 below 0.60 (49 of 55 records under C 0.40). The C≥0.60 slice agrees
  120/125, 33/36, and is empty (fully auto-accepted) respectively.
- **By problematic:** the `p 0.15–0.30` slice carries most disagreements
  (16/36, 46/67, 65/91); `p<0.15` disagreements are symmetric enough to
  include nearly all reverse-direction cases (8/6/2); `p>=0.30` escalated
  records are few (2/5/20) and AI-2 accepts almost all of them.
- **By correctness:** the `c 0.60–0.85` middle slice carries most volume and
  most disagreements (34/47/46); `c<0.60` escalated records are nearly all
  AI-2-accepted lean-REJECTs (19/19, 45/45 under balanced/aggressive);
  `c>=0.85` escalated records are few and mostly agree (78/80, 13/14, 1/1).

## 7. How many cases remain unresolved?

Primary rule: conservative **0**, balanced **2**, aggressive **2** of 500
(≤0.4%) — AI-2 AMBIGUOUS/ERROR verdicts, fail-safe quarantined, never
accepted. Second (disagreement) experiment, which quarantines every
lean-vs-verdict conflict without picking a winner: conservative would
quarantine **36** (7.2%), balanced **67** (13.4%), aggressive **91**
(18.2%) — every one of them a primary ACCEPT/REJECT overturned into
quarantine (details + record ids in `disagreement_summary.json`). The
no-winner rule's quarantine cost grows steeply as the escalation band
narrows, because narrower bands escalate exactly the records where the two
reviewers conflict most.

## 8. Does adaptive routing reduce unnecessary AI-2 calls vs v0.1 fixed bands?

Yes, on this sample — measured as escalation share and as concrete calls:

| comparison | v0.1 escalated | v0.2 escalated | saved (v0.1-AMB → auto) | newly escalated |
|------------|----------------|----------------|-------------------------|-----------------|
| v0.2-conservative vs v0.1-A-balanced | 254 (50.8%) | 227 (45.4%) | 76 | 49 |
| v0.2-balanced vs v0.1-A-balanced | 254 (50.8%) | 179 (35.8%) | **75** | **0** |
| v0.2-aggressive vs v0.1-A-balanced | 254 (50.8%) | 142 (28.4%) | 124 | 12 |
| v0.2-conservative vs v0.1-B-strict | 277 (55.4%) | 227 (45.4%) | 57 | 7 |
| v0.2-balanced vs v0.1-B-strict | 277 (55.4%) | 179 (35.8%) | 99 | 1 |
| v0.2-aggressive vs v0.1-B-strict | 277 (55.4%) | 142 (28.4%) | 166 | 31 |
| v0.2-conservative vs v0.1-C-lenient | 208 (41.6%) | 227 (45.4%) | 128 | 147 |
| v0.2-balanced vs v0.1-C-lenient | 208 (41.6%) | 179 (35.8%) | 89 | 60 |
| v0.2-aggressive vs v0.1-C-lenient | 208 (41.6%) | 142 (28.4%) | 70 | 4 |

Union view: three v0.1 configs jointly needed 359 unique AI-2 calls; three
v0.2 policies jointly need **304** (297 reused + 7 new) — **55 fewer
(−15%)**. 62 records v0.1 escalated are auto-routed under *every* v0.2
policy. Balanced-vs-A is the cleanest pairwise result: 75 escalations saved
with zero newly-escalated records (its 179 are a strict subset of A's 254).
Caveat: "saved" means not-escalated, not correctly-decided — correctness is
unmeasured here by design.

## 9. Obvious weaknesses / failure modes

1. **Uncalibrated throughout.** Thresholds are round-number operating points
   and C-weights are judgment (correctness 0.40, quality 0.25, …). Escalation
   still swings 28→45% across three "reasonable" policies — operating cost
   remains threshold-dominated, as in v0.1.
2. **Two signals are near-dead in practice.** `consistent_category` sits at
   0.90+ for ~90% of records (min 0.74) and `training_value` is bunched at
   2.7–3.0 — they barely move C. The router is effectively a 4-signal router
   (correct, quality, problematic, adherence) plus spreads.
3. **Rail and degraded paths untested by data.** Deterministic INVALID (0),
   JEV error (0), degraded signals (0), and independent rail firing (0) never
   occur in-sample; they are covered only by unit tests with synthetic inputs.
4. **One-sided disagreement.** AI-2 accepts ~90% of escalated records, so
   escalation usually ends in ACCEPT whenever the lean pointed REJECT. If
   AI-2 is lenient rather than JEV conservative, every policy over-accepts —
   and nothing in this experiment can distinguish the two.
5. **Single-sample AI-2.** One temperature-0 generation per record, no
   self-consistency; the transport ERROR case shows a single failure mode
   already (no-JSON-output → fail-safe, correct behavior, but n=1 evidence).
6. **The 7 newly-escalated records all returned ACCEPT** — consistent with
   either "adaptive catches subtle cases AI-2 then clears" or "adaptive
   escalates records that could have been auto-accepted". n=7 settles nothing.
7. **No-winner quarantine scales badly.** Under aggressive + disagreement
   matrix, 18.2% of all records end quarantined — the "safe" rule can cost
   more human review than the AI-2 calls it supervises.
8. **Coverage stats are not quality stats.** Every rate above describes
   routing behavior, not decision correctness.

## 10. Most practical operating configuration (cost/coverage tradeoff only)

| | conservative | balanced | aggressive |
|---|---|---|---|
| JEV-only (no AI-2 cost) | 54.6% | **64.2%** | 71.6% |
| Escalation (AI-2 cost) | 45.4% | **35.8%** | 28.4% |
| Token overhead vs JEV-only | +55% | **+46%** | +39% |
| Lean-vs-verdict conflict rate | 15.9% | **37.9%** | 65.0% |
| No-winner quarantines | 36 (7.2%) | **67 (13.4%)** | 91 (18.2%) |
| Unresolved | 0 | 2 | 2 |

**Balanced** is the most practical operating configuration *on measured
tradeoff alone*: it handles nearly two-thirds of records with zero marginal
AI-2 cost (64.2% JEV-only vs 54.6% conservative), cuts escalation to 35.8%
(15 points below v0.1-A with zero newly-escalated records against it), and
keeps the conflict/quarantine load in the middle (37.9% / 67 records vs
15.9%/36 and 65.0%/91). Conservative pays the most AI-2 for the least
auto-routing while resolving conflicts least often because its wide band
includes high-agreement records. Aggressive auto-routes most but escalates
precisely the records where the reviewers conflict most (65%), so its
apparent savings convert substantially into no-winner quarantines. **This is
a cost/coverage statement only — without independent ground truth no policy
is claimed more accurate or objectively better.**

## Files (all inside this directory; Atlas untouched)

- `filter_results.jsonl` — 500 lines, full per-record trace (ids, hashes,
  deterministic verdict, JEV signals, C components, per-policy band + final,
  AI-2 verdict + source, latency/tokens)
- `config_summary.json` — per-policy metrics incl. token counts, disagreement
  by C/problematic/correctness region, input provenance hashes
- `disagreement_summary.json` — no-winner matrix per policy + overturned ids
- `ai2_results.jsonl` — 7 v0.2-made blind verdicts (stored v0.1 verdicts
  reused by reference from `../jev-quality-filter-v0.1/ai2_results.jsonl`)
- `router.py`, `run_filter.py`, `ai2_reviewer.py`, `README.md`, `tests/` —
  rerunnable tooling + design + 30 tests

## Verification performed

- 30/30 new tests pass (deterministic routing, worked-example formula guard,
  boundaries, missing/malformed/out-of-range signals, AI-2 blindness incl.
  payload-key and no-JEV-argument structural checks, fail-closed incl.
  transport/config/parse failures, provenance preservation, disagreement
  matrix, no-human-label reference).
- `run_filter.py verify`: read-only input hashes match recorded provenance.
- `git status`: only pre-existing worktree entries plus the new
  `experiments/jev-quality-filter-v0.2/` directory; no Atlas source,
  release, curated, raw, review-queue, training-view, or config file written
  by this experiment (all writes are confined to the experiment directory by
  construction — every output path is anchored at `HERE`).
- Stopped after the v0.2 experiment: no Atlas modification, no relabeling,
  no deletion, no training, no release-gate or production integration, no
  large-scale run.
