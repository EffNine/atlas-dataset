# ADR-004: Training Views

**Status:** Accepted
**Date:** 2026-07-27

## Context
Atlas is model-agnostic. Downstream consumers need Qwen, Llama, DeepSeek (and
future) formats, but the canonical dataset must never be duplicated per model,
and the canonical record is the single source of truth.

## Decision
- The canonical record is the **only** stored artifact. Model-specific training
  data is *generated on demand* by `scripts/convert_format.py` (Qwen ChatML,
  Llama, ShareGPT, Alpaca) from the canonical form.
- Each Knowledge Object carries `training_view_eligibility` flags
  (`qwen/llama/deepseek`). These are eligibility markers **only**; eligibility is
  derived from category/subcategory suitability, not from generating data.
- During pilot, `training_views/{qwen,llama,deepseek}/` contain **placeholder
  README files only** — no training data is generated. Real view generation is a
  separate, authorized `atlas build-views` step after human review approves
  records.

## Alternatives
- Store one file per model format. Rejected: data drift, storage blow-up, and
  schema-change pain.
- Generate all views at ingest. Rejected: violates the "placeholders only" pilot
  constraint and couples promotion to format concerns.

## Consequences
- Adding a new model is a config edit in `configs/formatting/templates.json`, not
  a migration or re-ingestion.
- Training views are reproducible from canonical + templates at any time.
- The pilot explicitly proves "training views generated as placeholders only"
  as a success criterion.
