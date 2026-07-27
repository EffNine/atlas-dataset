# Training Recipe Specification

This document defines the stable Training Recipe contract for Atlas v1.0. A recipe is a declarative description of how to derive a training dataset slice or view from canonical Atlas data. A recipe never contains training data.

#

# 1. Invariants

- Recipes are generated from stable inputs: canonical objects, pack/collection manifests, templates, and deterministic metadata.
- Identical inputs plus identical recipe definitions MUST yield identical outputs.
- Recipes are reusable across training runs as long as their input artifacts are unchanged.

#

# 2. Required Fields

| Field | Purpose | Data Type | Constraints |
|------|---------|-----------|------------|
| `recipe_id` | Stable recipe identity | String | Must be unique within Atlas namespace |
| `recipe_version` | Recipe compatibly version | Semver | Matches recipe schema compatibility |
| `collections` | Source collection list | Array of collection identifiers | Must resolve to existing collections or registered pack groups |
| `filters` | Inclusion rules | Object | AQL-compatible filter specification |
| `quality_thresholds` | Minimum quality rule | Object | Minimum quality score and any category/source thresholds |
| `confidence_thresholds` | Confidence rules | Object | Optional minimum confidence weights for generated outputs |
| `sampling_strategy` | Subset selection method | String + parameters | Deterministic unless explicitly randomized with seed recorded |
| `deduplication_strategy` | Dedup policy | String + parameters | Deterministic selection policy |
| `output_target` | Generated artifact target | Object | Output path template; format spec |
| `supported_models` | Eligible model targets | Array of strings | Must match declared supported model contracts |
| `min_atlas_version` | Minimum dataset version | Semver | Prevents recipes from running against incompatible Atlas versions |

#

# 3. Behavioral Contracts

- A recipe must be replayable from canonical data plus declared inputs and config only.
- Changing `filters`, `sampling_strategy`, or `deduplication_strategy` semantically requires a new `recipe_version`.
- Recipes must avoid embedding actual training data; they describe selection, formatting, and delivery process only.
- Recipes may reference templates but must not hardcode model-specific prompting logic that belongs to model-specific template config.

#

# 4. Determinism Requirements

- Random sampling must be seed-recorded in generated artifacts if allowed.
- Sorting and tie-breaking must be deterministic.
- Equivalent queries using AQL tag-style and SQL-style must yield the same selection set.

#

# 5. Compatibility

- Recipe versions declare the minimum required Atlas data schema version.
- Breaking recipe changes require a new `recipe_id` or explicitly named major version change documented in ADR and dataset release notes.

#

# 6. Future Extensions

- recipe metadata blocks
- budget constraints
- time-to-generate limits
- provider/tool usage restrictions

Any extension must remain additive or declared breaking with explicit compatibility policy.

#

# 7. Related Contracts

- Training Views: see main spec Section 11.
- AQL: see main spec Section 12.
- Collections: see `collection_spec.md`.
- Packs: see `knowledge_pack_spec.md`.
