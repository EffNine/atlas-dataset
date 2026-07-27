# Knowledge Collection Specification

This document freezes the Knowledge Collection contract for Atlas v1.0. Collections aggregate multiple packs into higher-level bundles for organized distribution and inspection.

#

# 1. Hierarchy

Dataset → Releases → Knowledge Collections → Knowledge Packs → Records

#

# 2. Invariants

- All member packs referenced by a collection must exist and be individually verifiable.
- Collection statistics are derived from member pack manifest statistics; raw data files are not re-aggregated directly.
- Collection checksum is computed from deterministic canonical collection identity.
- Collection index remains the authoritative registry of available collections.

#

# 3. Required Artifacts

| Artifact | Purpose |
|----------|---------|
| `knowledge_packs/collections/<name>/<name>_collection.json` | Collection manifest |
| `metadata/collection_index.json` | Global collection registry |

#

# 4. Collection Manifest Contract

| Field | Purpose |
|------|---------|
| `collection_name` | Stable lowercase collection identity |
| `collection_version` | Collection version |
| `generated` | Generation timestamp |
| `description` | Human-readable description |
| `total_packs` | Count of member packs |
| `total_records` | Total records across member packs |
| `pack_names` | Ordered member pack names |
| `packs` | Resolved pack metadata list |
| `statistics` | Aggregated by category, license, average quality |
| `collection_checksum` | Deterministic integrity value |
| `metadata` | Optional metadata |

#

# 5. Collection Index Contract

| Field | Purpose |
|------|---------|
| `generated` | Index timestamp |
| `collections` | Array of collection entries |
| Collection entry fields | `name`, `description`, `total_packs`, `total_records`, `generated`, `collection_checksum` |

#

# 6. Aggregation Rules

- Aggregate `total_records` by summation of member pack `total_records`.
- Aggregate category/license counts by summing member pack manifest statistics.
- Average quality is the arithmetic mean of member pack averages weighted by pack record counts or unweighted average of pack averages depending on declared policy; Atlas v1.0 uses unweighted average of pack averages unless explicitly overridden in collection metadata.

#

# 7. Compatibility Rules

- Collections may reference packs whose schema has not changed in breaking ways.
- Collections must not silently tolerate missing packs.
- Collection version should advance if pack contracts break compatibility or statistics semantics change.

#

# 8. Integrity Rules

- Collection verification recomputes canonical identity hash and compares it to `collection_checksum`.
- Mismatch indicates invalid collection.
- Collection index must not contain duplicate `name` entries.

#

# 9. Related Documents

- Knowledge Packs: see `knowledge_pack_spec.md`.
- Integrity: see main spec Section 2.4.
- Release Engineering: see `release_manifest_spec.md`.
