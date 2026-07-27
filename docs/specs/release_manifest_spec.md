# Release Manifest Specification

This document defines the release manifest contract for Atlas v1.0.

#

# 1. Purpose

The release manifest is the frozen contract artifact for a dataset release. It includes release identity, integrity metadata, gate results, and compatibility info. It does not hold actual training data.

#

# 2. Required Fields

| Field | Purpose | Contract |
|------|---------|----------|
| `release_id` | Stable release identity | Readable prefix derived from `chain_hash` |
| `version` | Dataset release version | Semver aligned to dataset spec |
| `release_type` | Release class | patch/minor/major/fix depending on change class |
| `created_at` | Release timestamp | ISO-8601 |
| `total_records` | Included record count | Aligned to release contents |
| `chain_hash` | Chain integrity hash | sha256 of canonical release manifest fields |
| `content_hash` | Dataset content hash at release time | sha256 of deterministic content representation |
| `previous_hash` | Prior release chain hash | Empty string for genesis |
| `gates_passed` | Gate evaluation summary | Boolean; true if required gates passed |
| `release_id_short` | Human-readable reference | Derived from `chain_hash` prefix |

#

# 3. Release Gates

Required validation gates:

- `quality_gate`
- `license_gate`
- `schema_gate`
- `verification_gate`
- `category_balance_gate`
- `no_unknown_license_gate`
- `no_rejected_source_gate`

Release artifacts MUST include pass/fail status for every required gate. Releasable states require all required gates passing.

#

# 4. Verification

- Verify checksums for all release manifest files match registry.
- Verify prior release chain entry exists if `previous_hash` is non-empty.
- Verify content hash matches current release contents via deterministic serialization.
- Verify gate evaluation report matches release artifacts.

#

# 5. Diff Semantics

A release diff must support:
- added records
- removed records
- changed records
- unchanged records
- source and category migrations

#

# 6. Rollback Policy

Superseded versions remain intact for lineage and audit. No release manifest is rewritten after freeze. Reverting operational use is a non-destructive reference decision and does not mutate historical releases.

#

# 7. Compatibility

Releases declare the minimum Atlas spec version they require. Consumers must reject incompatible release versions.

#

# 8. Related Documents

- Release Engineering: main spec Section 13.
- Knowledge Collections: see `collection_spec.md`.
- Lifecycle: see `lifecycle_spec.md`.
- Integrity: see `knowledge_pack_spec.md` and main spec Section 2.4.
