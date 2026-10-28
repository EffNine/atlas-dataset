# Jev Shadow Evaluation Pilot — Status

**Run:** 2026-09-17 · **Status:** COMPLETE — 500/500 records evaluated via Jev, 0 errors
**See `REPORT.md` for full findings, measurements, limitations, and recommendation.**
Atlas data: UNCHANGED. All artifacts under this directory only.

## TL;DR

| metric | value |
|--------|-------|
| records evaluated | 500 / 500 (math 150, code 100, general 150, systems 100) |
| Jev ok / errors | 500 / 0 |
| model | jev-1.13.0 (jev-latest) |
| latency mean / p50 / p90 / max | 0.322 / 0.301 / 0.376 / 0.870 s |
| wall time (8 workers) | ~20 s |
| total tokens | 808,606 (in 758,606 / out 50,000) ≈ 1,617/record |
| flagged records (any of 4 signals) | 61 (12.2%) |
| outliers (quality<1.5 or correct<0.25) | 46 (9.2%) |
| near-dup candidate pairs in sample (J≥0.25) | 21 |
| cross-arm exact-dup pairs in full pilot/v0.2 | 822 |

Signal summary: `correct` mean 0.719, `quality` mean 2.63/4, `problematic` mean
0.204, `consistent_category` mean 0.954. corr(correct,quality)=0.945,
0 low-correct/high-quality contradictions. Manual inspection of low/high cases
confirmed Jev flags correspond to genuinely truncated or wrong math responses,
concentrated in `expert-math-002` (OpenMathInstruct-2) math records.

## Known limitation of the Jev question set

`consistent_category` sees the record's own category/subcategory labels inside
the state it judges, so it confirms label plausibility (0 mismatches found)
rather than detecting arm-level misfiling. The real taxonomy problem in
pilot/v0.2 (`general` arm carrying `03_system_engineering` over mirrored
math/code content) was found offline via SHA-256 + source analysis, not via Jev.
A larger run should cross-check against an out-of-state category list instead.

## Recommendation

**Proceed to a larger run with two preconditions:**
1. Deduplicate pilot/v0.2 first (822 cross-arm exact-dup pairs; ~33% of the
   pilot is mirrored into the `general` arm).
2. Point the Jev run at the deduplicated set (~2,900 unique records, ≈4.7M
   tokens, ~15–20 min) as a **shadow layer feeding the review queue** — not a
   release gate. Calibrate `correct`/`problematic` thresholds against a small
   human-labeled subset before any automation.

## Files

- `run_jev_pilot.py` — resumable tooling (`sample` / `run` / `report`), 8-worker parallel
- `jev_results.jsonl` — 500 per-record results (answers, latency, tokens, request_id, content SHA-256)
- `jev_pilot_report.json` — machine-readable analysis (distributions, per-arm means, 61 flagged records, 21 near-dup pairs)
- `jev_run_log.json` — run summary
- `sample_manifest.json`, `sample_records.jsonl`, `sample_content_index.json` — sample + traceability
- `REPORT.md` — full report
- `README.md` — Jev question design + how to re-run
