# Status Notes and Conventions

This file defines status terminology, cross-references, and conventions used across the Atlas v1.0 specification documents.

#

# 1. Status Terminology

- **Implemented**: Code and workflows shipped and exercised in this codebase.
- **Approved**: Decision or artifact formally accepted but may still require implementation rollout.
- **Planned**: Committed future work with defined scope, awaiting implementation or approval authority.
- **Experimental**: Exploratory work with no stable contract; may change or be removed.

#

# 2. Cross-References in Specs

- All references to JSON schemas point to files under `schemas/`.
- All references to scripts point to `scripts/` under the repository root unless explicitly qualified.
- Cross-spec links must be read as normative unless marked explicitly as informational.

#

# 3. Metadata Routing for Status Screens

The following rules apply when a status system surfaces Atlas information outside docs:

- **Specification freeze status** should display `1.0.0 frozen`.
- **Release readiness** should aggregate gate results from `scripts/acquisition_engine/release.py`.
- **License decision** should reference `metadata/source_registry.json`.
- **Data lineage** should reference the one stable source of data and the chain field path.
- **Review queue state** should map to `metadata/lifecycle_state.json` and review queue materials.

#

# 4. Review and Update Policy

- Global spec wording updates require ADR unless purely editorial.
- Subsystem contract adjustments require both updated subsystem spec file and main spec section write-up.
- When a status field is unambiguous but a user asks for a non-standard presentation, prefer canonical vocabulary with non-normative explanation.

#

# 5. Document Index

| Document | Purpose |
|----------|---------|
| `atlas_v1_spec.md` | Main v1.0 specification |
| `knowledge_object_schema.md` | Knowledge Object field contract |
| `knowledge_pack_spec.md` | Knowledge Pack format and checksum rules |
| `collection_spec.md` | Collection aggregation and integrity rules |
| `training_recipe_spec.md` | Recipe behavior and compatibility rules |
| `release_manifest_spec.md` | Release manifest, gates, diff, rollback |
| `aql_spec.md` | Query grammar, operators, determinism |
| `quality_engine_spec.md` | Scoring, calibration, human review contract |
| `lifecycle_spec.md` | State machine, transitions, audit policy |
