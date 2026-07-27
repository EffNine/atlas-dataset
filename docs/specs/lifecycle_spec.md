# Lifecycle Specification

This document freezes the Atlas lifecycle state machine for Atlas v1.0.

#

# 1. States

- `raw`
- `processing`
- `curated`
- `review`
- `approved`
- `released`
- `archived`
- `rejected`

#

# 2. State Semantics

- `raw`: original source artifacts
- `processing`: cleaning, deduplication, scoring, transformation active
- `curated`: pipeline gates passed; not yet human-approved
- `review`: in explicit human review queue
- `approved`: human-approved for release
- `released`: included in frozen release artifact
- `archived`: superseded or deprecated; retained for lineage
- `rejected`: did not pass gates or review; may re-enter pipeline only with recorded rationale

#

# 3. Valid Transitions

| From | To |
|------|----|
| raw | processing, rejected |
| processing | curated, rejected, raw |
| curated | review, processing, rejected |
| review | approved, rejected, needs_revision |
| needs_revision | review, rejected, curated |
| approved | released, review |
| released | archived |
| archived | — |
| rejected | raw |

Any transition outside this set is invalid and must fail validation.

#

# 4. Registry and Audit Requirements

- Lifecycle registry: `metadata/lifecycle_state.json`
- Each transition record includes: `from`, `to`, `timestamp`, `source`, `reason`
- Registry is integrity-protected by checksum registry
- Historical records must not manually set state outside approved migration programs

#

# 5. Behavioral Rules

- Raw records cannot be mutated; they may transition to processing or rejected.
- Records in `approved` may be returned to `review` if review policy requires re-review.
- Released records cannot return to active use datasets; they may be archived only.
- Rejected records may re-enter pipeline only with recorded state transition and explicit rationale.

#

# 6. Integration

- Lifecycle state is used by review queue, release gates, and archive tools.
- Training view generation only consumes approved/released records by default unless an authorized override is declared in a recipe.

#

# 7. Related Documents

- Main spec Sections 2.2, 2.7, 5, and 13.
- `scripts/acquisition_engine/lifecycle.py` is the canonical implementation reference.
