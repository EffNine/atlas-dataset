# Training View Architecture v0.1

## 1. Purpose

Provide a deterministic, read-only framework for transforming approved
Atlas expert records into specialist training views. The framework
creates no training artifacts itself; it produces validated view
blueprints and manifest records.

## 2. Architecture

```text
Source Records
   ↓
Filters
   ↓
Splitter
   ↓
Formatter
   ↓
Manifest
   ↓
Validator
   ↓
Writer (safe mode by default)
```

## 3. Modules

- `filters.py`: license, quality, difficulty, domain, provenance filters
- `splitter.py`: deterministic train/validation/eval split by stable id hash
- `formatter.py`: Atlas schema -> training view record conversion
- `manifest.py`: manifest construction + checksum verification
- `validator.py`: schema, duplicates, licenses, split leakage, provenance
- `writer.py`: JSONL writer with explicit write mode and no-overwrite safety
- `builder.py`: orchestrator wiring configs, modules, and validation

## 4. Determinism

Determinism is enforced by:
- stable hashed split keyed on record id + fixed seed
- sorted JSON checksum computation
- explicit config inputs without runtime randomness
- writer refusing overwrite by default

## 5. Reproducibility

Re-running the builder with identical inputs/config produces identical
records, splits, manifests, and validation results. Verification probes
in the test suite assert this contract.

## 6. Future Extensibility

New specialists require only a new config entry in
`metadata/training_views_v0.1.json`. Existing module behavior remains
unchanged.
