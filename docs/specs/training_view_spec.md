# Training View Specification

**Status:** Draft — Phase 5C
**Project:** Atlas Dataset Foundation
**Version:** 1.0

---

## 1. Purpose

A Training View is a generated, reproducible, disposable model-specific rendering of canonical curated records for model training. Training Views are derived from canonical Atlas data and templates. The canonical dataset remains the immutable source of truth.

This specification defines the structure, generation principles, and validation requirements for Training Views in the Atlas ecosystem.

---

## 2. Training View Principles

### 2.1 Immutable Source Reference

Every Training View must reference an immutable source release (curated dataset version). The view declares its `source_release` — the exact release version from which it was generated. A view may not reference a mutable or in-progress dataset state.

### 2.2 Reproducible Generation

Given the same source release, recipe configuration, and template, Training View generation must be fully deterministic. The same inputs must produce identical output every time. Non-determinism (e.g., random sampling) must be explicitly declared in the recipe.

### 2.3 Lineage Preservation

Every record in a Training View must carry lineage information tracing it back to its source knowledge object, curated dataset, and original source attribution. The lineage chain `Source → Transformations → Knowledge Object → Curated Dataset → Training View → Future Model Training` must be preserved without breaks.

### 2.4 License Inheritance

All license obligations from source records are inherited by the Training View. The view must include license metadata per record and aggregate license statistics. Records with unknown, denied, or unresolved licenses must be excluded.

### 2.5 Quality Filtering

Training Views apply a quality threshold filter. Records below the recipe's quality threshold are excluded. The threshold is declared in the recipe and enforced by the generator. No record may bypass the quality gate.

### 2.6 Version Tracking

Every Training View is versioned. The view identifier encodes the recipe, source release, and generation timestamp in a composite key. Version history is recorded in the view manifest.

---

## 3. Required Fields

Every Training View manifests (both per-view and per-record) must include the following fields:

### 3.1 View-Level Manifest Fields

```
{
  "training_view_id":       // string — unique identifier (recipe + source + timestamp hash)
  "source_release":         // string — release version (e.g., "v0.2")
  "source_records":         // int — total source records available for view generation
  "generation_policy": {    // object — describes the filtering + selection strategy
    "quality_threshold":    // int — minimum quality score
    "license_filter":       // string — license filter applied
    "lifecycle_filter":     // string — lifecycle states included
    "eligibility_filter":   // object — model eligibility flags required
    "sampling_strategy":    // string — sampling strategy (deterministic/random/none)
    "max_records":          // int or null — maximum records limit
  }
  "filters": {              // object — actual filters that were applied
    "quality_below":        // int — count excluded by quality
    "license_denied":       // int — count excluded by license
    "lifecycle_invalid":    // int — count excluded by lifecycle
    "eligibility_missing":  // int — count excluded by eligibility
    "pending_review":       // int — count excluded by pending review status
    "rejected":             // int — count excluded by rejected status
  }
  "created_at":             // string — ISO-8601 generation timestamp
  "checksum": {             // object — integrity checksums
    "manifest":             // string — SHA-256 of the manifest JSON
    "records":              // string — SHA-256 of all generated records concatenated
    "algorithm":            // string — checksum algorithm (e.g., "SHA-256")
  }
}
```

### 3.2 Per-Record Fields in Generated View

Each generated record in a Training View must include:

```
{
  "view_id":                // string — training view ID
  "record_id":              // string — original knowledge object ID
  "source":                 // string — original source name
  "license":                // string — resolved license
  "quality_score":          // int — quality score
  "category":               // string — category
  "subcategory":            // string — subcategory
  "difficulty":             // int — difficulty level
  "knowledge_type":         // string — knowledge type
  "lineage": {              // object — trimmed lineage chain
    "source_attribution":   // string — original source attribution ID
    "knowledge_object":     // string — knowledge object ID
    "curated_release":      // string — curated dataset release version
    "training_view":        // string — training view ID
  }
  "messages":               // array — conversation turns (canonical format)
  "eligibility": {          // object — model eligibility flags
    "qwen":                 // bool
    "llama":                // bool
    "deepseek":             // bool
  }
}
```

---

## 4. Generation Lifecycle

```
Recipe Specification
    │
    ▼
Source Release Selected
    │
    ▼
Filter: approved records only
    │
    ▼
Filter: released packs only
    │
    ▼
Filter: valid lifecycle states only
    │
    ▼
Filter: quality threshold ≥ recipe.min_quality
    │
    ▼
Filter: license not denied, not unknown
    │
    ▼
Filter: training_view_eligibility[model] == true
    │
    ▼
Generate view metadata + records
    │
    ▼
Compute checksums
    │
    ▼
Write view manifest + record file
    │
    ▼
Verify view integrity
```

---

## 5. Validation Rules

### 5.1 Input Validation

| Rule | Description |
|------|-------------|
| source_release exists | The referenced release must have a valid manifest in `metadata/releases/` |
| source_records > 0 | There must be at least one source record available |
| recipe exists | The recipe must be registered in `metadata/training_recipe_registry.json` |
| quality_threshold valid | Must be an integer in [0, 10] |
| model target valid | Must be one of `qwen`, `llama`, `deepseek` |

### 5.2 Content Validation

| Rule | Description |
|------|-------------|
| no pending records | Every included record must have `verification_status == "approved"` |
| no rejected records | No record may have `verification_status == "rejected"` |
| no unknown licenses | No record may have `license == "unknown"` |
| complete lineage | Every record must have `lineage` with required fields |
| quality threshold compliance | Every record must have `quality_score >= recipe.quality_threshold` |

### 5.3 Output Validation

| Rule | Description |
|------|-------------|
| manifest structure | Manifest matches the schema defined in Section 3.1 |
| checksums match | Computed checksums match declared checksums |
| records loadable | All records parse as valid JSON |
| deterministic | Rerun produces identical output (subject to recipe determinism) |

---

## 6. Safety Guarantees

1. **No mutation** — Training View generation is **read-only** on curated records, review decisions, and release metadata.
2. **No network access** — Generation is fully offline.
3. **No model execution** — Generation does not invoke any model training, inference, or evaluation.
4. **No auto-approval** — Views are generated from already-approved records only.
5. **No data promotion** — Views do not modify the canonical dataset lifecycle state.

---

## 7. Related Documents

| Document | Location |
|----------|----------|
| Training View Generator | `scripts/training_view_engine/` |
| Training Recipe Registry | `metadata/training_recipe_registry.json` |
| Dataset v1.0 Spec | `docs/specs/atlas_v1_spec.md` |
| Architecture Governance | `docs/governance/atlas_architecture_governance.md` |
| Knowledge Object Schema | `schemas/knowledge_object_schema.json` |
