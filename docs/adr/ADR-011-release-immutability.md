# ADR-011: Release Immutability

**Status:** Accepted
**Date:** 2026-08-01
**Phase:** 4C.4 — Engineering Stabilization

---

## Context

Atlas publishes dataset releases (v1.0, v1.1, v1.2 classification outputs,
knowledge packs) that are consumed downstream by training pipelines, query
engines, and model evaluation. Earlier in the project, a curated release file
was modified in place after publication (a bad record was edited rather than
re-released), which caused:

1. Downstream consumers silently depending on different bytes than the
   manifest recorded.
2. Release manifest checksums (SHA-256) no longer matching on-disk content.
3. Reproducibility loss — a later regeneration of the same release tag
   produced different artifacts.
4. Trust erosion — consumers could no longer assume a release tag was
   stable.

A release is a contract. Once published, its content must never change.

## Decision

**Once a release is published (manifest written + bundle promoted), its
content is immutable.**

- Every curated file is tracked with its own baseline SHA-256; verification
  compares each file against **its own** baseline, never a shared or
  re-hashed baseline.
- Any correction requires a **new release** (v1.0 → v1.0.1 or v1.1),
  never in-place edits to a published file.
- Release manifests record expected file lists and checksums and are
  themselves immutable after promotion.
- Pipeline stages (validation, classification, training views) always
  **read** published releases; they never write into a published bundle.

## Rationale

- Immutability is the prerequisite for reproducibility: the same release tag
  must produce the same artifacts forever.
- Manifest-based verification is only meaningful against frozen bytes.
- Downstream training runs and evaluation harnesses need a stable
  provenance anchor.
- Corrections become additive (new release), which preserves audit history.

## Alternatives Considered

1. **Mutable releases with edit logs** — allowed in-place fixes if logged.
   Rejected: log-based trust is weaker than byte-level immutability; too
   easy to silently break checksum integrity.
2. **Re-publish the same tag** — regenerate and overwrite. Rejected:
   defeats provenance; consumers cannot distinguish pre/post-fix bytes.
3. **Hash-agnostic releases** (no checksums). Rejected: no verification
   story; unacceptable for dataset governance.

## Consequences

- **Positive**: reproducible artifacts, meaningful manifest verification,
  clear provenance, safe downstream consumption.
- **Negative**: fixes require a new release cycle; small typos cannot be
  patched in place.
- **Mitigation**: release cadence supports patch-level bumps; validation
  catches issues before promotion so post-publish corrections are rare.

## Future Revisions

- Revisit if a correction protocol with signed edit records and full
  consumer opt-in is ever desired.
- Extend to cover classification summary artifacts and training view
  metadata when those become published outputs.
