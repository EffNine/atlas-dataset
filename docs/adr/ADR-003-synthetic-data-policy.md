# ADR-003: Synthetic Data Policy

**Status:** Accepted
**Date:** 2026-07-27

## Context
Synthetic (model-generated) data is cheap and plentiful, and some categories
(hardware, business, creative, personal-assistant) are sparse in clean licensed
corpora. But unbounded synthetic data turns Atlas into an echo of existing
models, defeating the "knowledge foundation" goal and risking factual drift.

## Decision
- Synthetic data is a **minority bridge**, never the majority. Model-generated
  synthetic is capped at **5%** of any release (v0.1 target: 37/1000 = 3.7%).
- Synthetic is permitted **only** as `doc2qa` style transformation of *licensed*
  source text (e.g. hardware docs → Q&A), never bulk model-dreaming.
- Every synthetic-derived record is flagged (`metadata.synthetic = true`) and
  **human-reviewed before `curated/`**.
- Per-category caps apply (hardware ≤15%, business ≤15%, creative ≤20%,
  personal-assistant ≤20%) — well under the global 5% model-generated ceiling
  because most "synthetic" here is doc-derived (not model-generated) and excluded
  from the cap.
- Doc-derived instruction (Linux/K8s/Arch/arXiv/Wikipedia → Q&A) is **not counted
  as synthetic** — it is a transform of licensed text.

## Alternatives
- Allow large synthetic volumes to fill sparse categories. Rejected: degrades
  quality, factual reliability, and the long-term-value thesis.
- Ban synthetic entirely. Rejected: makes sparse categories impossible to cover.

## Consequences
- Sparse categories are coverable without compromising the knowledge foundation.
- The pipeline must distinguish model-generated vs doc-derived synthetic in
  metadata, and the cap is checked by the dry-run plan and pilot manifest.
- Human review load is bounded and focused on synthetic bridges.
