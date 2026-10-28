# Phase 2.2 — Targeted Defect Review Instructions

**Status: PENDING — 0 of 28 batch items reviewed. Nothing here can be completed by an
AI agent: it requires two genuinely independent DIRECT human reviews per item
(each reviewer works from the blinded files themselves — no relaying).**

## Why this exists

Phase 2.1 produced unanimous human-clean gold (0 positives), so JEV thresholds cannot be
calibrated. Either (A) JEV over-flags, or (B) the coarse yes/no protocol missed genuine
defects. This package re-tests 28 targeted records with a sharper instrument: 8 defect
dimensions + mandatory evidence for every finding.

## What you review

28 opaque batch items in `phase2.2/review_package/records/P22-001.json … P22-028.json`
(12 JEV-flagged retests, 12 JEV-flagged fresh records, 4 JEV-clean controls — you are
NOT told which is which). Each file has the full user + assistant content, the category
label, and the defect criteria. No JEV signals, no strata, no prior labels.

## The 8 dimensions (finding direction in brackets)

| dimension | finding |
|---|---|
| `correctness` | `no` = substantively wrong final answer/conclusion |
| `problematic` | `yes` = unsuitable as training data |
| `category_correct` | `no` = content doesn't belong to its category label (vs `taxonomy_reference_v1.json` in `phase2/`) |
| `truncation_incomplete` | `yes` = cut off, missing conclusion/boxed answer |
| `factual_technical_error` | `yes` = concrete wrong fact/step, or code that cannot work as claimed |
| `instruction_violation` | `yes` = answers a different question / wrong output contract |
| `malformed_output` | `yes` = garbled, broken encoding, unusable structure |
| `other_defect` | `yes` = concrete defect not covered above (describe it) |

**Evidence rule (enforced by the validator):** every finding-direction verdict REQUIRES an
`evidence` string (≥10 non-space chars) that pinpoints the defect — quote the step,
name the line, show the counterexample. A bare restatement ("it is wrong") will be
rejected. Run the reasoning yourself; for code, trace the diff against the issue text.

## Blinding rules (mandatory)

1. Work ONLY from `review_package/records/P22-XXX.json`. Do NOT open
   `record_map.sealed.json`, `selection_manifest.sealed.json`, `jev_results.jsonl`,
   `jev_pilot_report.json`, `phase2/human_labels/`, or any threshold/error report mid-pass.
2. Your file carries `blinded_to_jev: true` + `blinded_to_prior_labels: true` — attest
   only if true.
3. If you reviewed Phase-2.1 items: judge the CONTENT fresh against the defect criteria.
   Do not try to reproduce your earlier answers from memory — the evidence requirement
   forces a fresh pass anyway.

## Two-reviewer protocol

- Reviewer IDs: fresh anonymous IDs, e.g. `r1`, `r2` (must differ from each other).
- Both reviewers judge ALL 28 items independently. **Direct only: each reviewer reads the
  files and records their own verdicts. Do not relay one person's judgments through another —
  relayed reviews will be marked as such and cannot support agreement claims.**
- Workload: 28 items × 2 reviewers = 56 reviews (~3–6 min/item with evidence → ~2–4 h per reviewer).

## How to record one review

1. Read `review_package/records/P22-XXX.json`.
2. Copy `review_package/review_template.json` to `reviews/P22-XXX__<your-id>.json`.
3. Fill `reviewed_at` (ISO-8601), all 8 `labels`, and `evidence` (mandatory for findings).
4. Validate as you go:
```bash
.venv/bin/python experiments/jev-pilot-atlas-v0.1/phase2.2/phase2_2_review.py validate
```
Fix every `VIOLATION:` — invalid files do not count.

## When all 56 files exist

1. `... validate` → expect 28/28 paired, 0 violations.
2. `... agreement` → per-dimension raw agreement + Cohen's κ.
3. `... adjudication` → every disagreement needs a **third** reviewer (different ID);
   resolved gold goes to `reviews_adjudicated/P22-XXX.json` (same labels+evidence schema
   plus `adjudicator_id`; raw reviews never touched).
4. `... error-analysis` → 2×2 matrix (JEV flagged/clean × human defect/clean) with
   precision/recall/FPR/FNR + per-disagreement evidence bundles. Disagreement reasons are
   NEVER auto-assigned — an analyst selects from the candidate list with the evidence.
5. `... assess` → recalculated gates D/E/F.
6. `... all` once for the final consistent set.

## Hard prohibitions

- Do NOT edit `pilot/`, `curated/`, `raw/`, `releases/`, `metadata/`, `phase2/` (Phase-2 artifacts are frozen).
- Do NOT open sealed files mid-pass. Do NOT copy JEV scores into reviews.
- Do NOT run the ~2,942-record JEV shadow run.
