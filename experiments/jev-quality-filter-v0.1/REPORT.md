# Quality-Filter Prototype — Report (`jev-quality-filter-v0.1`)

**Workflow evaluation only. No accuracy / precision / recall claims — there is no
independent ground truth in this experiment and Phase-2 human labels were never
used (not read, not referenced).** All thresholds are experimental operating
points, not calibrated cutoffs.

## 1. What ran

- **Sample:** 500 JEV-pilot records (math 150, code 100, general 150, systems 100).
- **JEV first pass:** REUSED stored `jev_results.jsonl` (model `jev-1.13.0`). Zero
  JEV reruns, zero new JEV cost.
- **Deterministic validation:** 500/500 VALID (pilot data is already well-formed;
  the stage is implemented and would route INVALID → REJECT without AI).
- **Bands:** 3 experimental configs (A-balanced / B-strict-accept / C-lenient-accept).
- **AI-2:** blind independent review (`agnes-2.5-flash`, temperature 0, own
  rubric/prompt) on the **union-ambiguous set = 359 records** (one call each,
  reused across configs). AI-2 never received JEV scores, bands, or reasoning.
- **Atlas source data:** untouched (all reads; `git status` shows only this new
  directory).

## 2. Answers to the six questions

### (1) Records JEV handled without AI-2

| config | auto-ACCEPT (HIGH) | auto-REJECT (LOW) | handled w/o AI-2 |
|--------|-------------------|-------------------|------------------|
| A-balanced | 157 (31.4%) | 89 (17.8%) | **246 (49.2%)** |
| B-strict-accept | 105 (21.0%) | 118 (23.6%) | **223 (44.6%)** |
| C-lenient-accept | 256 (51.2%) | 36 (7.2%) | **292 (58.4%)** |

### (2) Records requiring AI-2 (escalated)

A: 254 (50.8%) · B: 277 (55.4%) · C: 208 (41.6%). Union over configs: 359
records received exactly one AI-2 call each.

### (3) AI-2 agreement vs JEV-lean (heuristic, NOT ground truth)

JEV-lean = ACCEPT-lean unless `correct<0.6 or quality<2.5 or problematic≥0.30`
(analysis convenience only). Over the 359 AI-2 calls: **322 ACCEPT, 34 REJECT,
2 AMBIGUOUS, 1 ERROR**.

| config | agree | disagree | AI-2 AMB/ERR |
|--------|-------|----------|--------------|
| A-balanced | 152 | 99 | 3 |
| B-strict-accept | 201 | 74 | 2 |
| C-lenient-accept | 74 | 131 | 3 |

Direction of disagreement is systematic: AI-2 ACCEPTs most escalated records
(e.g. config A: 234 accept vs 17 reject from 254 escalated). The JEV-lean rule
labels most of the middle band REJECT-lean, so "disagreement" here mostly means
*AI-2 accepted where JEV's continuous signal pointed down* — consistent with
either a conservative JEV middle band or a lenient AI-2. **This experiment
cannot distinguish those; do not read it as either model being right.**

The operationally valuable disagreements are the reverse direction — records
JEV scored mid-to-high that AI-2 REJECTed with specific refutations (8 under
config A). Examples:

- `v2-code-cdad48241a0e8b53` (JEV correct 0.74 / quality 2.88 — would pass most
  single-threshold gates): AI-2 REJECT 0.85 — patch adds `params={'value':
  value}` without the matching `%(value)s` placeholder, so the param is dead.
- `v2-general-02a2c81f7f5c8bb6` (JEV 0.70/2.57): AI-2 REJECT 0.95 — assistant
  validates x=0 where (-1)^(-1)=-1≠1; reasoning self-contradictory.
- `v2-math-26b2177ef3a859f0` (JEV 0.76/2.84): AI-2 REJECT 0.92 — misses n=0 as
  a valid solution; count is 7, not 6.

Reverse examples (JEV-low, AI-2 ACCEPT — 91 under config A), e.g.
`v2-math-44a53543d48fba20` (JEV problematic 0.50 / correct 0.32): AI-2 ACCEPT
0.65 — final answer x=54 verified correct, though the shown reasoning is
flawed ("multiple of 4 or 6" step unjustified). Whether flawed-reasoning /
right-answer records belong in SFT data is a **policy decision**, not something
this experiment resolves.

### (4) Cost / latency overhead

| signal | JEV (reused, not respent) | AI-2 (new spend, 359 calls) |
|--------|---------------------------|-----------------------------|
| input tokens | 758,606 total (~1,517/rec) | 575,718 total (~1,608/escalated rec) |
| output tokens | 50,000 total (100/rec) | 164,994 total (~461/escalated rec) |
| mean latency | 0.322 s/rec | 3.763 s/call (~12× JEV) |
| wall (8 workers) | ~20 s (historical pilot log) | ~8 min for 359 calls |

AI-2 adds roughly **+76% input tokens and +330% output tokens** relative to the
JEV first pass, concentrated on the ~42–55% escalated subset. No USD figures:
apply the operator's provider price card to the token counts in
`config_summary.json`. (AI-2 output tokens are ~4.6× JEV's per record — the
model emits longer rationales/reasoning; a production prompt could cap this.)

### (5) Unresolved (final AMBIGUOUS)

A: 3 · B: 2 · C: 3 of 500 (≤0.6%) — `v2-code-cf555ce9bf97ce80`,
`v2-systems-p1-y9-linux-kernel_6cc4c3aa…` (AI-2 AMBIGUOUS) and
`v2-general-3e45850c4a6d5c35` (AI-2 transport-level ERROR: no JSON object in
output → fail-safe, never accepted). In any real deployment these route to
human review; this prototype performs none.

### (6) Final distributions + practicality judgment

| config | ACCEPT | REJECT (incl. quarantine) | AMBIGUOUS |
|--------|--------|---------------------------|-----------|
| A-balanced | 391 (78.2%) | 106 (21.2%) | 3 (0.6%) |
| B-strict-accept | 366 (73.2%) | 132 (26.4%) | 2 (0.4%) |
| C-lenient-accept | 431 (86.2%) | 66 (13.2%) | 3 (0.6%) |

**Practicality (workflow only):** the architecture *runs* acceptably at this
scale — JEV auto-handles ~45–58% with zero marginal cost (reused), one AI-2
call resolves all but ≤0.6% of escalations, and all required provenance fields
(record_id, content SHA-256, JEV signals, band, AI-2 verdict, final, latency,
tokens) are captured in `filter_results.jsonl` + `config_summary.json`.
Caveats before any larger subset: (a) thresholds are uncalibrated guesses —
escalation rate swings 42→55% across three "reasonable" configs, so operating
cost is threshold-dominated; (b) AI-2 is ~12× slower per call and token-heavy
on outputs — fine at 42–55% escalation on hundreds of records, needs a cost
model at thousands+; (c) nothing here says the ACCEPTs are *correct* — the
next step is calibration against human labels (out of scope for this
prototype), not a bigger uncalibrated run. **Recommendation: calibrate bands
against a small human-labeled subset before trying a larger Atlas subset.**

## 3. Files (all inside this directory; Atlas untouched)

- `filter_results.jsonl` — 500 lines, full per-record trace
- `config_summary.json` — per-config metrics incl. token counts
- `ai2_results.jsonl` — 359 blind AI-2 verdicts (no JEV data in, none out)
- `run_filter.py`, `ai2_reviewer.py`, `README.md` — rerunnable tooling + design
