# Training View Eligibility Policy v0.1

## 1. Purpose

Training views are derived artifacts produced from already-curated Atlas
expert records. Source datasets remain immutable; training views do not
write back into `curated/`, `raw/`, `releases/`, or `knowledge_packs/`.

This policy defines the eligibility boundary for those derived artifacts.
It guarantees that every record entering a specialist training view:

- has verifiable provenance,
- satisfies the quality gate,
- carries an allowed license,
- has no unresolved security or governance flags,
- and, when applicable, respects the calibrated exclusions learned from
  human review.

## 2. Record Lifecycle

```text
Extraction
    |
    v
Schema validation
    |
    v
License validation
    |
    v
Quality gate
    |
    +--> REJECT -> excluded
    |
    +--> KEEP -> eligible candidate
    |
    v
Training view generation
```

`REVIEW` is an intermediate gate label. A `REVIEW` record is not
auto-promoted to a training view; it remains excluded unless a later
governance action explicitly resolves it.

## 3. Eligibility Rules

A record is eligible for a specialist training view only when ALL of the
following are true:

- schema validation returns no errors
- license is verified and permitted
- provenance completeness = full / required fields present
- security flags = 0
- quality gate label = `KEEP`

A record is excluded when ANY of the following is true:

- human review verdict = `REJECT`
- license is unresolved or non-permissive
- security violation is detected
- provenance failure is detected
- duplicate conflict is detected

## 4. Human Review Role

Human review is a calibration mechanism, not a mandatory approval gate
for every record.

Human review is used to:

- validate automated gate boundaries,
- detect false positives,
- inform exclusion rules for future materialization.

Human review is NOT used to manually bless individual records in normal
operation.

Evidence from Phase 1B calibration:

- reviewed records: 324
- human `KEEP`: 306
- human `REJECT`: 18
- acceptance rate: 94.4%
- agreement with automated gate: 94.4%

Finding: all 18 human rejects were OpenMathInstruct-2 synthetic math
records. Failure modes included fabricated claims, invalid derivations,
and incorrect expected answers. These records remain excluded from
training views.

## 5. Synthetic Data Policy

Synthetic records are allowed only when ALL of the following are true:

- `model_generated = true`
- source license permits usage
- quality gate returns `KEEP`
- verification evidence exists

OpenMathInstruct-2 example:

- allowed source license: `CC-BY-4.0`
- `model_generated = true`
- synthetic policy: allowed with flag

Outcome: the source category remains eligible, but records failing the
quality gate or human calibration exclusions are excluded from training
views.

## 6. Specialist View Mapping

- `code_300m`: SWE-bench Verified
- `math_300m`: OpenMathInstruct-2
- `aiml_300m`: ArXiv `cs.LG` / `cs.CL` / `cs.AI` / `stat.ML`

## 7. Decision Record

See `metadata/training_view_policy_decision_v0.1.json`.

## 8. Validation

Policy validation must confirm:

- decision JSON matches the required schema,
- required fields exist,
- reject rules are present,
- OpenMath rejected records remain excluded from training views,
- no training execution is performed by validation code,
- no Atlas dataset artifacts under `curated/`, `raw/`, `releases/`,
  or `knowledge_packs/` are modified.

## 9. Scope Boundaries

This phase is policy/documentation and validation only.

Explicitly excluded from this phase:

- model training
- model downloads
- dataset expansion
- modifications to curated data artifacts
- rewriting existing pilot artifacts
