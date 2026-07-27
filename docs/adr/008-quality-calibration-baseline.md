# ADR-008: Quality Calibration Baseline (Frozen v0.1)

**Status:** Accepted
**Date:** 2026-07-27
**Supersedes / Related:** ADR-006 (quality gate philosophy), ADR-007 (review queue design); Phase 3A pilot, Phase 3B calibration framework, Phase 3C human review.

## Context

Phase 3A (pilot ingestion of 100 knowledge objects), Phase 3B (the
`scripts/calibrate_quality.py` framework), and Phase 3C (100 human reviews in
`review/quality_reviews.jsonl`) are complete. The calibration report
(`metadata/calibration_report.json`) shows a `READY_FOR_CALIBRATED_AUTO_REVIEW`
verdict, but the agreement is structurally skewed: the auto-scorer assigns
**7.0 to every one of the 100 objects**, so correlation is undefined and
"100% within-1 agreement" is an artifact of score compression.

We need a **stable, immutable reference point** before any future re-calibration
or any decision to relax human oversight. Without a frozen baseline, later
changes to the heuristic, the corpus, or the review data cannot be measured
against a known-good state, and accidental modification of the reviewed
inputs would go undetected.

## Decision

1. **Freeze the calibration baseline as v0.1.** Capture it in
   `metadata/calibration_baseline_v0.1.json` with: timestamp, dataset version,
   reviewed record count, human + AI score distributions, correlation metrics,
   bias metrics, confidence metrics, approval rate, and rejection rate.
2. **Register checksums for all frozen inputs** in
   `metadata/checksums_v0.1.json` (sha256 of the reviewed knowledge objects,
   the review file, all four schemas, and all manifests). The registry is the
   tamper-evidence layer for the baseline.
3. **Generate both artifacts read-only.** A single idempotent script,
   `scripts/freeze_calibration_baseline.py`, recomputes the baseline from the
   live inputs via the canonical calibration framework. It never writes dataset
   records, the review file, schemas, or manifests — only the two artifact
   files. Its `--verify` mode recomputes the checksums and fails on any drift.
4. **Document the baseline and its weaknesses** in
   `docs/calibration_baseline_report.md`, including a future-comparison metrics
   table.
5. **Do not modify** knowledge objects, dataset size, or review decisions as
   part of this freeze.

## Why the baseline is frozen

- The current auto-scorer is **degenerate** (zero variance). Freezing now
  preserves an honest record of that state rather than letting later "improvements"
  erase the reference point we would need to prove we actually improved.
- The verdict is `READY_FOR_CALIBRATED_AUTO_REVIEW`, which *permits* bulk
  ingestion with stratum corrections and spot-checks — but the permissive verdict
  rests on a compressed distribution. A frozen baseline forces any future
  relaxation of human review to be justified by a measured delta, not by
  re-interpretation of the same numbers.
- The reviewed inputs (knowledge objects, reviews, schemas, manifests) are the
  evidence base for every future quality claim. Checksums make silent
  corruption or well-meaning edits visible in CI.

## Future usage

- **Comparison:** When re-calibrating (e.g. after widening the heuristic's range
  per ADR-008 improvement #1), recompute the baseline and diff against
  v0.1 using the metrics table in `docs/calibration_baseline_report.md`. A
  successful re-calibration must show non-degenerate AI-score variance and
  Pearson r > 0.6 before human review can be reduced.
- **Drift guard:** Run
  `python scripts/freeze_calibration_baseline.py --verify` in CI on every change
  touching reviewed objects, the review file, schemas, or manifests. Any
  checksum mismatch must block the change until the baseline is deliberately
  regenerated and a new ADR is filed.
- **New baseline:** A material re-calibration produces v0.2, referencing this
  ADR and documenting the delta. v0.1 remains in the repo as historical
  reference.
- **Do NOT begin bulk ingestion** on the strength of v0.1 alone beyond what the
  `READY_FOR_CALIBRATED_AUTO_REVIEW` verdict with stratum corrections already
  permits; the known weaknesses (§3 of the report) must be addressed first.

## Alternatives

- *Freeze by hand / copy the report.* Rejected: a hand-copied snapshot drifts
  from the real inputs and cannot be re-verified. The script guarantees the
  baseline always matches the on-disk truth.
- *Skip the baseline and re-calibrate immediately.* Rejected: without a reference
  point there is no way to demonstrate improvement, and the degenerate current
  state would be overwritten and lost.
- *Checksum only the review file.* Rejected: schemas and manifests also feed
  calibration; tampering with them silently changes results.

## Consequences

- Atlas now has a tamper-evident, reproducible calibration reference.
- CI can detect accidental modification of reviewed inputs.
- Future quality claims are measured against a known baseline, raising the bar
  for claiming "the auto-scorer is good enough."
- The honesty cost: v0.1 openly records that the auto-scorer has zero variance
  and that "ready" is conditional, not absolute.
