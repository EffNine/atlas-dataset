# ADR-009: Adoption of Atlas v1.0 Specification

**Status:** Accepted
**Date:** 2026-07-27

## Context

Atlas has progressed from prototype to platform. Multiple subsystems now exist:
licensing, lineage, quality scoring, knowledge packs, collections, AQL, release
engineering, training recipes, training views, versioning, migration, and the
acquisition engine. Each subsystem exposes a durable contract surface.

Future work can no longer proceed without a single, authoritative architecture
contract. Ad-hoc changes risk breaking reproducibility, explainability,
commercial safety, migration fidelity, and release determinism.

## Decision

Declare the frozen specification at `docs/specs/atlas_v1_spec.md` as the
authoritative Atlas v1.0 architecture specification.

All future contract-level changes must follow the governance path:

Specification → ADR → Migration → Implementation

Implementation must never lead.

## Scope

The adopted specification covers:
- Knowledge Objects
- Lifecycle
- Licensing
- Quality Engine
- Knowledge Packs
- Knowledge Collections
- AQL
- Release Engineering
- Training Recipes
- Training Views
- Security
- Versioning

## Non-Negotiable Principles

Atlas Constitution:

1. Atlas is the source of truth.
2. Training views are generated artifacts.
3. Released knowledge objects are immutable.
4. Every object requires lineage.
5. Every release requires verification.
6. Commercial safety is mandatory.
7. Human review remains authoritative.
8. Every quality score must be explainable.

## Consequences

### Positive
- Stable architecture
- Reproducible development
- Controlled evolution
- Easier onboarding

### Negative
- Future changes require discipline
- More migration work
- Less ad-hoc modification

## Version Policy

`Atlas v1.x` means backward-compatible additive evolution; implementation is
always preceded by an accepted ADR and, when needed, a migration.

`Atlas v2.0` requires architectural redesign and a new specification adoption
ADR.
