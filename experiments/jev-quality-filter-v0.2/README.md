# JEV Quality Filter v0.2 — adaptive automated quality router

**Experiment only. Not a gate. Not calibrated. Does not modify Atlas data.
No accuracy / correctness claims: there is no independent ground truth.**

## Question

v0.1 showed fixed two-dimensional bands escalate ~42–55% of records to a
blind second reviewer (AI-2). Can an *adaptive* router built from JEV's full
signal set route more records automatically while keeping every uncertain
case escalated — and what does each operating policy cost?

## Pipeline

```
stored JEV results, 500 records (REUSED from jev-pilot-atlas-v0.1; JEV NOT rerun)
  → deterministic validation (local, no AI; INVALID → REJECT, no AI involved)
  → adaptive confidence C from all JEV signals (router.py, pure function)
  → per-policy routing (conservative / balanced / aggressive)
      ├── HIGH → ACCEPT (no AI-2)
      ├── LOW  → REJECT / QUARANTINE (no AI-2)
      └── AMBIGUOUS → blind AI-2 review → ACCEPT / REJECT / AMBIGUOUS
  → disagreement-handling experiment (conservative no-winner matrix)
```

## What this directory contains

| file | purpose |
|------|---------|
| `router.py` | Adaptive confidence + routing + disagreement matrix. Pure, deterministic, no I/O. Exact formula in its module docstring. |
| `ai2_reviewer.py` | Blind second reviewer, REUSED UNCHANGED from v0.1 (same provider/model resolution, prompt, rubric, fail-safe transport). |
| `run_filter.py` | Pipeline: validate → route → top-up AI-2 on newly-escalated records → results + summaries + v0.1 comparison. |
| `ai2_results.jsonl` | v0.2-made AI-2 calls ONLY (top-up for records the adaptive router newly escalates). Stored v0.1 verdicts are reused by reference, never copied. |
| `filter_results.jsonl` | One line per record: ids, hashes, deterministic verdict, JEV signals, confidence components, per-policy band + final, AI-2 verdict + source, latency/tokens. |
| `config_summary.json` | Machine-readable per-policy metrics + input provenance hashes. |
| `disagreement_summary.json` | Second-experiment output: conservative disagreement matrix per policy. |
| `tests/` | Deterministic-routing, boundary, malformed-signal, AI-2-blindness, fail-closed, provenance, and disagreement-matrix tests. |
| `REPORT.md` | Workflow evaluation answering the ten required questions (no accuracy claims). |

## Read-only inputs (never written, never relabeled)

- `../jev-pilot-atlas-v0.1/jev_results.jsonl` — reused JEV first-pass (no rerun)
- `../jev-pilot-atlas-v0.1/sample_content_index.json` — record text for validation + AI-2
- `../jev-pilot-atlas-v0.1/sample_manifest.json` — arm/category metadata
- `../jev-quality-filter-v0.1/ai2_results.jsonl` — reused blind AI-2 verdicts
- `../jev-quality-filter-v0.1/filter_results.jsonl` — v0.1 bands, fixed-vs-adaptive comparison only

Phase-2 human labels are **never read** and are **not ground truth** here.
Old human-calibration results were **not used** to choose anything below.

## Adaptive confidence function (exact; v0.2-router-v1)

From each record's stored JEV answers:

```
c  = correct.noul                 [0,1]
qn = quality.score / 4            [0,1]
p  = problematic.noul             [0,1]
a  = adherence.noul               [0,1]
k  = consistent_category.noul     [0,1]
tn = training_value.score / 4     [0,1]
qs = 1 - max(quality.probabilities)
ts = 1 - max(training_value.probabilities)

S = 0.40*c + 0.25*qn + 0.15*a + 0.10*k + 0.10*tn   (positive support)
U = (qs + ts) / 2                                   (distributional uncertainty)
D = (|c-qn| + |c-(1-p)| + |c-a| + |c-k|) / 4        (cross-dimension disagreement)
C = clip(S - 0.50*p - 0.25*U - 0.25*D, 0, 1)        (rounded to 4 decimals)
```

Routing rails (same for all policies): deterministic INVALID → REJECT;
JEV error → AMBIGUOUS-unresolved; missing/malformed/out-of-range signal →
AMBIGUOUS (`jev_signal_degraded`, C withheld — incomplete evidence is never
auto-routed); `p >= 0.80` → LOW quarantine regardless of C.

Weight rationale (documented judgment, not fitted): correctness dominates
because it is JEV's primary verdict-like signal; quality is second;
adherence/consistency/training-value are small stabilisers. The problematic
penalty (0.50) is the largest single term so high-risk records cannot score
high. Uncertainty/disagreement penalties (0.25) express doubt, not danger.

## Policies — operating intents only

Same C function; only the band thresholds differ. Thresholds are
uncalibrated round numbers fixed BEFORE the v0.2 run to span operating
points. They are not "accurate", "optimal", or "correct".

| policy | tau_lo (≤ → LOW) | tau_hi (≥ → HIGH) | intent |
|--------|------------------|-------------------|--------|
| conservative | 0.45 | 0.75 | widest escalation band; hardest auto-accept; most AI-2 spend |
| balanced | 0.35 | 0.65 | middle operating point |
| aggressive | 0.25 | 0.55 | narrowest escalation band; most auto-routing; least AI-2 spend |

Boundary semantics: equality routes outward (`>=` HIGH, `<=` LOW).

## Primary final-decision rule (fail-closed)

- HIGH → `ACCEPT`; LOW → `REJECT` (+ `quarantine=true`).
- AMBIGUOUS → AI-2 verdict: `ACCEPT`→accept, `REJECT`→reject,
  `AMBIGUOUS`/`ERROR`/missing→`AMBIGUOUS` quarantine/unresolved (human
  review in any real deployment — **this experiment performs none**).
- An AI-2 failure can never become an acceptance.

## Second experiment: disagreement handling (no winner selected)

For escalated records, JEV's continuous signal is reduced to a stance with
the v0.1 heuristic reused verbatim (`REJECT-lean` if
`correct<0.6 or quality<2.5 or problematic>=0.30`, else `ACCEPT-lean` —
analysis convenience only, NOT ground truth, NOT a decision):

- lean ACCEPT + AI-2 ACCEPT → ACCEPT · lean REJECT + AI-2 REJECT → REJECT
- lean ACCEPT + AI-2 REJECT → AMBIGUOUS quarantine (no winner)
- lean REJECT + AI-2 ACCEPT → AMBIGUOUS quarantine (no winner)
- AI-2 AMBIGUOUS / ERROR / missing → AMBIGUOUS fail-safe

This matrix is reported in `disagreement_summary.json`, including how many
primary finals it would overturn into quarantine. It does not rewrite the
primary results.

## AI-2 independence

AI-2 receives ONLY the record's user/assistant text + claimed
category/subcategory (record metadata, not JEV output). It never receives
JEV scores, bands, confidence, decisions, or reasoning. Its prompt, rubric,
and model family (`agnes-2.5-flash` via OpenAI-compatible API, temperature
0) are identical to v0.1. Tests assert the message payload carries exactly
the keys `{claimed_category, claimed_subcategory, user, assistant}` and that
`review_record` accepts no JEV arguments.

## Explicit non-goals / non-claims

- No precision/recall/accuracy: no independent ground truth exists here.
- "Disagreement" is a *workflow* measure (AI-2 verdict vs the documented
  JEV-lean heuristic), not a quality judgment about either reviewer.
- AI-2 cost is reported as **tokens + latency**. No USD figures are invented.
- AI-2 verdicts are single-sample, temperature-0 generations — a second
  opinion, not an oracle. "Most practical" in the report means the measured
  cost/coverage tradeoff only.

## Reproduce

```bash
.venv/bin/python experiments/jev-quality-filter-v0.2/run_filter.py route           # no network
.venv/bin/python experiments/jev-quality-filter-v0.2/run_filter.py run [--limit N] # top-up AI-2 only
.venv/bin/python experiments/jev-quality-filter-v0.2/run_filter.py report          # rebuild outputs
.venv/bin/python experiments/jev-quality-filter-v0.2/run_filter.py verify          # input-hash check
.venv/bin/python -m pytest experiments/jev-quality-filter-v0.2/tests/ -q           # tests
```
