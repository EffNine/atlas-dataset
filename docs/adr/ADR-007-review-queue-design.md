# ADR-007: Review Queue Design

**Status:** Accepted
**Date:** 2026-07-27

## Context
Pilot ingestion produces candidate objects, but promotion to `curated/` requires
human judgment (ADR-006). There must be an explicit, inspectable buffer between
"ingested candidate" and "approved knowledge," with a clear state machine.

## Decision
- Every ingested object enters `review_queue/` in a per-state JSONL file
  (`pending.jsonl`, `approved.jsonl`, `rejected.jsonl`, `needs_revision.jsonl`).
  Each line is a lightweight pointer: `{id, category, subcategory, quality_score,
  license, verification_status}`.
- States form a closed set: `pending → {approved | rejected | needs_revision}`.
  `needs_revision` may return to `pending` after edit.
- The queue is **cleared at the start of each pilot run** so re-runs do not
  accumulate stale entries; the canonical objects live in `curated/v0.1/`, the
  queue is a working buffer.
- The full object (with lineage/attribution) stays in `curated/v0.1/
  pilot_candidates.jsonl`; the queue references it by `id`.
- Promotion = moving the line from `pending.jsonl` to `approved.jsonl` and setting
  the object's `verification_status = approved` / `verified = true`. This is a
  human action, never performed by the ingestion engine.

## Alternatives
- Promote directly in the ingestion engine. Rejected: violates ADR-006 (no auto-
  promotion) and removes the audit buffer.
- Keep review state only inside the canonical file. Rejected: harder to triage
  100 items; a separate queue is the operational unit of review.

## Consequences
- Reviewers get a bounded, inspectable queue with a defined workflow.
- The queue is reproducible and re-runnable without duplicating full records.
- At pilot completion, all 100 objects are `pending` — i.e. the dataset is NOT
  promoted; it awaits human approval before any training use.
