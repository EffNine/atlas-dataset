# Knowledge Object Specification

This document freezes the canonical Knowledge Object contract for Atlas v1.0. All fields, stability rules, and extension constraints are defined here. The actual machine-readable schema is `schemas/knowledge_object_schema.json`; this file explains intent and operational constraints.

#

# 1. Scope

A Knowledge Object is the full operational record written by the ingestion pipeline and validated by `scripts/validate_knowledge_object.py`. It is a strict superset of the strict curated gate schema `schemas/dataset_schema.json`.

A Knowledge Object is always valid against the base schema, plus the additional fields defined below.

#

# 2. Field Contract

| Field | Purpose | Data Type | Constraints | Validation Rules | Migration Rules | Deprecation Strategy |
|------|---------|-----------|------------|------------------|-----------------|----------------------|
| `id` | Stable unique key | String | 3-128 chars; `^[a-z0-9_-]+$` | Uniqueness within dataset; stable forever | New naming patterns via migration; preserve historical IDs | Stable for released objects |
| `category` | Top taxonomy bucket | Enum, string | One of nine Atlas categories | Exact enum match | Only additive enum changes via migration + index update | Frozen per release |
| `subcategory` | Local taxonomy bucket | String | 1-64 chars | Aligned to category/subcategory index | Add valid subcategories via metadata/index update | Additive only |
| `knowledge_type` | Knowledge kind | Enum, string | fact/procedure/concept/reasoning/code/reference/creative | Exact enum match | Add via migration | Additive only |
| `canonical_answer` | Authoritative answer text | String | Non-empty | Must be present in full object | Cannot remove | Stable |
| `metadata` | Structured metadata | Object | Free-form properties allowed | Verify optional expected keys when present | Additive only | No breaking removals |
| `source_attribution` | Provenance/compliance object Required `source_id`, `name`, `url`, `license`, `attribution_text` `share_alike` must match license if true Must resolve to `metadata/source_registry.json` id; attribution text required for CC-BY-SA | Extend only with additive fields | Preserve existing attribution |
| `license` | Resolved SPDX/human-readable license | String | 1-64 chars | Never `unknown` at curated stage; denied-license gate enforced | Reclassification requires source evidence and ADR | Reclassification is exceptional |
| `tags` | Retrieval/balancing keywords | String array | Lowercased; hyphenated; unique; max 20 | Schema uniqueness and pattern | Edit taxonomy via metadata index | Additive only |
| `quality_score` | Heuristic/human score | Integer | 0-10 | Strict 0-10 integer range | Same scale forever; recalibrate via release if model changes | Scale freeze |
| `verification_status` | Human workflow state | Enum, string | pending/approved/rejected/needs_revision | Valid lifecycle transition required to change state | Widen enum only with ADR | Preserve legacy mappings |
| `lineage` | Traceability chain object | Object | Required keys: `source`, `transformations`, `knowledge_object`, `curated_dataset`, `training_view`, `future_model` | Structural required keys; transformations ordered | Additive chain fields via migration | Breaking chain requires regeneration |
| `training_view_eligibility` | Eligibility flags object Required booleans: `qwen`, `llama`, `deepseek` Must align with model support declarations Add model flags via migration/config | Additive only | Backward-compatible additions only \
| `messages` | Conversation turns array | Array | minItems 2; each turn must include `role`/`content`; 1-64000 chars | Base schema plus chat schema; must include user and assistant turns | Extend message metadata via additive migration | Non-breaking additions only \
| `verified` | Reviewer approval mirror | Boolean | true iff `verification_status == approved` | Cross-field invariant during validation | Do not decouple without ADR | Do not decouple without ADR \
| `notes` | Audit/review notes | String | max 2000 | Empty string if none | No breaking change planned | None |

#

# 3. Cross-Cutting Stability Rules

- Curated records are immutable.
- Raw records are never modified.
- Processing outputs may be regenerated.
- Schema migrations are additive unless explicitly declared breaking in an approved ADR.
- Behavioral contracts must remain compatible with prior releases across minor version boundaries.

#

# 4. Validation Entrypoints

- `schemas/dataset_schema.json` — strict curated gate.
- `schemas/knowledge_object_schema.json` — operational superset gate.
- `scripts/validate_knowledge_object.py` — implementation validator.

#

# 5. Complementary Documents

- Knowledge Lineage: see main spec Section 4.
- Lifecycle: see main spec Section 5.
- Licensing: see main spec Section 7.
