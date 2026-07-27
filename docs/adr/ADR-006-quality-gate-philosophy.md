# ADR-006: Quality Gate Philosophy

**Status:** Accepted
**Date:** 2026-07-27

## Context
Quality — not quantity — is Atlas's differentiator. A pilot of 100 objects exists
to build *confidence* in the pipeline, not to maximize volume. The quality bar
must be explicit, enforced, and human-in-the-loop.

## Decision
- **Minimum quality score: 8.5** for promotion to `curated/`. Below threshold, a
  record routes to `needs_revision`, never silently dropped or silently promoted.
- Required gates before `curated/`: schema-complete, license-valid, verified
  (human `verified == true`), no-duplicate, metadata-complete.
- **No automatic promotion.** Every object enters `review_queue/` as `pending`.
  Statuses: `pending`, `approved`, `rejected`, `needs_revision`. Only a human sets
  `approved`.
- The heuristic `quality_score.py` (7-dimension weighted) is a *triage* signal, not
  a substitute for human review.
- Duplicate rate must stay **below 1%** (exact + near-dup via MinHash/LSH).

## Alternatives
- Auto-promote high-scoring records. Rejected: removes the human safety check the
  whole foundation depends on; hallucination/licensing risks slip through.
- Lower the bar to 7.0 (the v0.1 curated threshold). Rejected for the pilot: the
  pilot's purpose is to prove the *high* bar is achievable end-to-end.

## Consequences
- The pilot proves the pipeline can reliably produce ≥8.5 objects with full
  metadata and lineage.
- Human reviewers have a clear, bounded queue (100 items) and a defined workflow.
- Promotion is a deliberate, recorded decision — aligned with the "stop and wait
  for approval" cadence of every phase.
