# Phase 2.1 — Manual Human Labeling Instructions (96 rows / 84 unique records)

**Status: PENDING — 0 of 84 records labeled. This is the ONLY remaining manual step blocking gates D, E, F.**

No labels have been fabricated, inferred, or auto-generated. Nothing below can be
completed by an AI agent: it requires two genuine independent human judgments per record.

## 1. What you are labeling

84 unique Atlas pilot/v0.2 records (the 96-row Phase-2 manifest contains 9 record IDs
that repeat across the `low_jev` / `flagged` / `outliers` strata — see finding F-1 in
`STATUS.md`. Each unique record is labeled ONCE per labeler; the strata join-back is automatic).

Per record you read the **full user + assistant content** and answer exactly three questions:

| # | Dimension | Criterion (verbatim from `human_calibration_manifest.json → labeling_criteria`) |
|---|-----------|----------------------------------------------------------------------------------|
| 1 | `correctness` | Is the assistant response substantively correct given the user request? Answer yes/no. 'Substantively' means the final answer/conclusion is right even if the exposition has minor flaws. |
| 2 | `problematic` | Is this record unsuitable as training data (contradictions, broken/garbled text, harmful content, prompt injection, PII leakage)? yes/no. |
| 3 | `category_correct` | Does the content genuinely belong to the record's category label (using the independent taxonomy reference, not the label's own plausibility)? yes/no. |

For dimension 3, judge against **`taxonomy_reference_v1.json`** (9 canonical categories
`01_foundation` … `09_personal_assistant`), shown per record as `category_label`.
Pilot/v0.2 label mapping: `mathematics → 01_foundation`,
`software_engineering → 02_software_engineering`, `system_engineering → 03_system_engineering`.
Math word-problems filed under `general` with a math label are the known arm-level filing
issue — judge the CONTENT against the reference, not the arm it sits in.

## 2. Blinding rule (mandatory)

Each record file contains **no Jev signals, scores, or flags — by design**.
Do NOT open `human_calibration_manifest.json`, `labeling_sheet.md`, `jev_results.jsonl`,
or `jev_pilot_report.json` until AFTER you have recorded your labels for that record.
Your label file carries a `blinded_to_jev: true` attestation; only set it if true.

## 3. Two-labeler protocol

- Pick two labeler IDs, e.g. `labeler-a` and `labeler-b` (any `^[A-Za-z0-9_-]{1,64}$`).
- Both labelers judge ALL 84 records **independently** (no discussion, no sharing files mid-pass).
- Total workload: 84 records × 2 labelers = **168 judgments**. Median record file is
  ~3 KB (~2 messages); at ~2–4 min/record expect roughly **5–10 hours per labeler**.
- Disagreements are resolved afterward by a **third** labeler (different ID from both
  originals) — do not overwrite the original files; adjudicated gold goes to
  `human_labels_adjudicated/<record_id>.json` (tooling-guided, step 6).

## 4. How to record labels — recommended: interactive script (no JSON hand-editing)

```bash
# Label your pending records one by one (shows each record blinded, asks y/n, writes the file):
.venv/bin/python experiments/jev-pilot-atlas-v0.1/phase2/phase2_1_labeling.py label --labeler labeler-a

# Useful variants:
.venv/bin/python experiments/jev-pilot-atlas-v0.1/phase2/phase2_1_labeling.py label --labeler labeler-a --limit 10
.venv/bin/python experiments/jev-pilot-atlas-v0.1/phase2/phase2_1_labeling.py label --labeler labeler-a --record <record_id>
```

The script shows the full user + assistant text (never Jev signals), asks the 3
questions (`y`/`n`, `s` = skip, `q` = quit/resume later), copies the SHA-256 and arm
for you, validates before writing, and refuses to overwrite. You make every judgment;
it only does the clerical work. SHA/arm/filename/timestamp mistakes — the main source
of `VIOLATION:` lines — become impossible.

**Suggested easing:** both labelers first do the same `--limit 10`, then run
`... agreement` to check you interpret the criteria the same way before doing all 84.
Early disagreement on criteria meaning is cheap to fix at n=10, expensive at n=84.

### Fallback: manual JSON (only if the script doesn't suit you)

1. Open `phase2/labeling_package/records/<record_id>.json`, read `messages`.
2. Copy `phase2/labeling_package/label_template.json` to
   `phase2/human_labels/<record_id>__<your-labeler-id>.json`
   (e.g. `v2-math-36b99a746186d743__labeler-a.json`).
3. Fill in: `arm`, `content_sha256` (**copy verbatim** from the record file — it proves
   you judged the exact referenced bytes), `labeled_at` (ISO-8601 with timezone),
   and the three `labels` (`"yes"` / `"no"`, lowercase, quoted).
4. Optional `notes` (≤2000 chars) for rationale — never a substitute for the labels.

Example (complete, valid):

```json
{
  "schema_version": "human-label-v1",
  "record_id": "v2-math-36b99a746186d743",
  "arm": "math",
  "content_sha256": "0ded786c182c4549:dfaf711b7cc7f908",
  "labeler_id": "labeler-a",
  "labeled_at": "2026-09-18T10:00:00+00:00",
  "criteria_version": "phase2-calibration-v1",
  "reference_version": "taxonomy_reference_v1",
  "blinded_to_jev": true,
  "labels": {"correctness": "yes", "problematic": "no", "category_correct": "yes"},
  "notes": ""
}
```

## 5. Validate as you go (after each batch)

```bash
.venv/bin/python experiments/jev-pilot-atlas-v0.1/phase2/phase2_1_labeling.py validate
```

This checks schema conformance, `record_id`/`arm`/`content_sha256` against the manifest,
filename ↔ `labeler_id` match, ISO-8601 timestamps, and rejects any Jev-signal leakage.
Fix every `VIOLATION:` line — a file with violations does not count.

## 6. When all 168 files exist

1. Run `... validate` — expect `n_records_two_labelers: 84`, `violations: []`.
2. Run `... agreement` — writes `inter_rater_agreement.json` (raw agreement + Cohen's κ per dimension).
3. Run `... adjudication` — writes `adjudication_list.json` (every disagreement needing a third labeler).
4. Third labeler resolves each item → `human_labels_adjudicated/<record_id>.json`
   (same schema; `labeler_id` = adjudicator, `notes` records the resolution).
5. Run `... calibrate` — writes `threshold_calibration_v2.json` (confusion matrices,
   precision/recall/FPR/FNR, score distributions, provisional thresholds with stated limits).
6. Re-run `... all` once for the final consistent artifact set, then re-run the
   Phase-2 test suite (`tests/jev_pilot_phase2/`) to confirm green.

Only at that point can gates D (human calibration), E (threshold calibration), and F
(~2,942-record shadow run) be re-evaluated on evidence instead of HOLD status.

## 7. Hard prohibitions (Atlas governance)

- Do NOT edit anything under `pilot/`, `curated/`, `raw/`, `releases/`, `metadata/`.
- Do NOT edit `human_calibration_manifest.json` (append-only Phase-2 artifact).
- Do NOT copy Jev scores into label files or let them influence the blinded pass.
- Do NOT ask an AI to pre-fill labels for you to "review" — that voids independence.
- Do NOT run the ~2,942-record Jev shadow run until calibration is complete.
