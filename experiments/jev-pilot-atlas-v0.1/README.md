# Jev Shadow Evaluation Pilot on Atlas Data

Status: **RUNNING — waiting for working TypeSafe/Jev API key** (2026-09-17)

## Purpose

Evaluate whether Jev (TypeSafe System One) is a useful low-cost shadow evaluator
of Atlas training data quality. Shadow-only: no changes to Atlas data, releases,
training, or release gates.

## Data sampled

Pilot/v0.2 training sets, 500 records total, deterministic seed 20260917:

| arm | source file | n |
|-----|-------------|---|
| math | pilot/v0.2/math/train.jsonl | 150 |
| code | pilot/v0.2/code/train.jsonl | 100 |
| general | pilot/v0.2/general/train.jsonl | 150 |
| systems | pilot/v0.2/systems/train.jsonl | 100 |

## Jev question design (one request per record, 6 questions)

| id | type | dimension |
|----|------|-----------|
| correct | Noul | response factually/technically correct vs request |
| quality | Score 0-4 | response quality as training data |
| adherence | Noul | response follows instructions/constraints |
| consistent_category | Noul | content matches record's category/subcategory |
| problematic | Noul | clear problem making record unsuitable |
| training_value | Score 0-4 | overall usefulness for 8B-class LLM training |

All 6 questions batch into a single Jev request per record (per TypeSafe guidance:
independent questions over the same state run in parallel and are cheap to add).

## Artifacts

- `sample_manifest.json` — record ids, categories, difficulty, source, content SHA-256
- `sample_content_index.json` — user/assistant content for sampled records
- `jev_results.jsonl` — per-record Jev answers + latency + token usage + request id
- `jev_run_log.json` — run summary (ok/errors/latency/tokens)
- `jev_pilot_report.json` — analysis: distributions, category breakdown, flagged
  records, near-duplicate candidates (via existing `scripts/dedup_dataset.py`
  shingle+minhash primitives, Jaccard >= 0.25)

## How to run (with working key)

```bash
export TYPESAFE_API_KEY=...
cd /home/afnan/projects/active/atlas-dataset
.venv/bin/python experiments/jev-pilot-atlas-v0.1/run_jev_pilot.py sample
.venv/bin/python experiments/jev-pilot-atlas-v0.1/run_jev_pilot.py run    # resumable
.venv/bin/python experiments/jev-pilot-atlas-v0.1/run_jev_pilot.py report
```

## Blocker

The `TYPESAFE_API_KEY` present in this environment (107 chars,
`apikey_236bf...`) returns **401** on every call to `api.typesafe.ai/v1/systemone`
and `/v1/models`, tested via the installed `typesafe-sdk` and raw HTTP. No other
TypeSafe credential exists in this environment. Until a valid key is supplied,
every Jev call will fail; results will show `status: error` per record.

## Pre-Jev data-quality findings (offline, no API needed)

From the sample/analysis pass over the pilot/v0.2 data:

1. **Massive cross-arm duplication in pilot/v0.2.** The `general` arm is a
   verbatim mirror of 100-200 records from the other three arms
   (OpenMathInstruct-2 x366, SWE-smith x366, linux-kernel x366 — exact-dup user
   content confirmed via SHA-256). 822 cross-arm user-content duplicate pairs
   exist in the full pilot/v0.2 data. 40 of the 500 sampled records are exact
   duplicates of a record in another arm.
2. **Category inconsistency in the `general` arm.** Its records carry
   `category: 03_system_engineering` (kernel-ish) while containing
   math/code/general content from the mirrored sources. Jev's
   `consistent_category` question was designed to detect exactly this.
3. The near-dup check in `jev_pilot_report.json` (existing
   `scripts/dedup_dataset.py` shingle+minhash primitives, Jaccard >= 0.25) found
   21 candidate pairs among the 500 sampled records; all correspond to the
   cross-arm mirroring above, including same-arm pairs from `p1-y9-linux-kernel`.

These findings do not depend on Jev and are recorded here because they affect
the interpretation of any later Jev results.
