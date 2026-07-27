# Knowledge Pack Specification

This document freezes the Knowledge Pack contract for Atlas v1.0. Knowledge Packs are compact, portable, independently verifiable subsets of the Atlas dataset.

#

# 1. Invariants

- Pack contents are derived from canonical dataset artifacts only.
- Pack generation is deterministic given identical inputs and filter criteria.
- Pack manifests must be present and internally consistent.
- Pack checksums must be computed after persistent data files are finalized.

#

# 2. Required Artifacts

| Artifact | Purpose |
|----------|---------|
| `{name}.jsonl.gz` or `{name}.jsonl` | Pack data |
| `{name}_manifest.json` | Pack metadata and statistics |
| `{name}_checksums.json` | Detached integrity metadata |

#

# 3. Manifest Contract

| Field | Purpose | Constraints |
|------|---------|------------|
| `pack_name` | Stable identifier | Unique within pack namespace |
| `pack_version` | Pack version | Semver |
| `generated` | Generation timestamp | ISO-8601 |
| `description` | Human description | Optional but recommended |
| `total_records` | Record count after filtering | Integer |
| `filter_criteria` | Applied inclusion rules | Object including categories and min_quality |
| `statistics` | Aggregation metadata | `by_category`, `by_license`, `avg_quality`, `quality_min`, `quality_max` |
| `files` | File entries | filename → sha256 |
| `metadata` | Optional metadata | source_version, engine_version, generated_by |

#

# 4. Checksum Contract

`{name}_checksums.json` must include:
- sha256 for every listed data file relative to pack directory
- sha256 for the manifest file itself
- `algorithm: "sha256"`

#

# 5. Integrity Rules

- Pack verification recomputes filesystem hashes and compares them to stored checksums.
- Any mismatch invalidates the pack.
- Missing files invalidate the pack.
- Manifest checksum mismatch invalidates the pack.

#

# 6. Compatibility

- Pack consumers must treat packs as read-only.
- Repack or regeneration must produce a new pack name or version.
- Checklist for using packs in collections, recipes, releases, or outside Atlas depends only on public pack metadata.

#

# 7. Related Documents

- Collections: see `collection_spec.md`.
- Integrity Engine: see main spec Sections 2 and 13.
