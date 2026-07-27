# ADR-001: Canonical Knowledge Objects

**Status:** Accepted
**Date:** 2026-07-27

## Context
Atlas needs a single, model-agnostic record shape that carries everything a
downstream training view and a human reviewer require: the conversation, the
authoritative answer, provenance, license, verification state, lineage, and
training-view eligibility. The Phase 1 base schema (`dataset_schema.json`) covers
only `id/category/subcategory/type/source/messages/...` and forbids extra fields
(`additionalProperties: false`) so it can act as a strict curated gate. It does
not carry lineage, attribution text, or verification status.

## Decision
Define a **Canonical Knowledge Object** as a *superset* of the base record in
`schemas/knowledge_object_schema.json`. The base schema remains the strict
curated gate; the Knowledge Object schema is the full operational record written
by the ingestion pipeline and validated by `scripts/validate_knowledge_object.py`.
Every Knowledge Object includes: `id, category, subcategory, difficulty,
knowledge_type, canonical_answer, metadata, source_attribution, license, tags,
quality_score, verification_status, lineage, training_view_eligibility, messages`.
A Knowledge Object is always valid against the base schema *plus* these additions.

## Alternatives
- (A) Cram everything into the base schema. Rejected: the base schema's
  `additionalProperties: false` is a deliberate safety gate; widening it weakens
  the curated-stage contract and the denied-license gate.
- (B) Use separate sidecar files per record (lineage.json, attribution.json).
  Rejected: splits provenance from data, complicates transport and auditing.

## Consequences
- Records are self-describing and portable; one file carries full provenance.
- Two validators exist (base + KO); pipelines must use the right one at the right
  stage. The KO validator is dependency-light (structural fallback) so it runs
  anywhere.
- Migrations add new KO fields without touching the base schema; historical raw
  data stays immutable (ADR-005, ADR-006).
