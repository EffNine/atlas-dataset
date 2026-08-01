# ADR-013: Parallel Processing

**Status:** Accepted
**Date:** 2026-08-01
**Phase:** 4C.4 — Engineering Stabilization

---

## Context

Atlas pipeline stages (acquisition, extraction, classification, validation,
training views) operate on large JSONL corpora (millions of records). Early
stages were single-threaded:

- Extraction ran one shard at a time per source.
- Validation loaded and checked one file fully before the next.
- Classification used only `--workers` (source-level), which under-used the
  machine when a single source dominated the work.
- Worker counts were hardcoded per script, drifting between stages.

Measured on dev-pc: single-worker classification ran ~120–150 records/sec;
4 workers ~430–500; 8 workers ~600–700. Hardcoded counts meant tuning one
stage did not propagate anywhere else.

## Decision

Adopt a **unified parallelism configuration** plus **stage-appropriate
parallel execution models**:

1. **Single source of truth**: `config/parallelism.yaml` defines worker
   counts for every stage:
   - classification: stage1=8, stage2=10
   - validation: file_workers=8
   - acquisition: file_workers=4
   - extraction: shard_workers=8, shards_per_source=41
   - training_views: workers=8

2. **Consumers read the config**: `run_classify_all_v2.py`,
   `scripts/validate_dataset.py`, `scripts/acquisition_engine/engine.py`,
   `scripts/training_view_engine/generator.py` / `validator.py`, and
   `scripts/run_extract_all.py` all load worker counts from the YAML with
   sane fallbacks (no hardcoded worker counts in pipeline code).

3. **Execution models**:
   - Classification: sequential sources, parallel shards within a source
     (`ProcessPoolExecutor`, `--shard-workers`).
   - Validation: file-level parallelism (`ProcessPoolExecutor` over input
     files, glob input supported).
   - Acquisition / training views: parallel file loading + per-record
     validation workers.
   - Extraction: `run_extract_all.py` fans out per-shard subprocess calls
     across workers.

4. **Determinism preserved**: parallel paths chunk work but never reorder
   final outputs; per-file results are concatenated in input order.

## Rationale

- A single config makes tuning repeatable and auditable — one file answers
  "how many workers does stage X use?"
- Stage-appropriate models avoid the memory blow-up of applying one model
  everywhere (e.g. 16 concurrent source-sized loads would OOM).
- Parallel workers give measured 3–5x throughput on classification; the
  same pattern applies to validation and view generation.
- Determinism keeps parallel outputs comparable to sequential ones for
  verification and reproducibility.

## Alternatives Considered

1. **Global CPU-count auto-tuning** — rejected: no per-stage control, and
  hard to predict memory per stage.
2. **ThreadPoolExecutor everywhere** — rejected for CPU-bound Python
  (GIL); ProcessPool is required for real speedup on classification and
  validation.
3. **Env-var configuration** — rejected: less discoverable, no single
  audit point, awkward defaults.
4. **Source-level parallelism as default** — rejected (see ADR-012):
  memory contention on 16 cores × source-sized workloads.

## Consequences

- **Positive**: one config governs all stages; measured 3–5x throughput;
  parallel behavior is opt-in per stage and deterministic.
- **Negative**: every new stage must remember to read the config, or it
  silently runs sequentially — governance rule added to architecture
  validation.
- **Negative**: ProcessPool workers spawn per invocation, adding startup
  cost on small runs (negligible at millions of records).

## Future Revisions

- Revisit auto-scaling based on live memory/cpu telemetry.
- Add a `--workers 0` sentinel meaning "auto from config".
- Extend to release build/packaging stages when they become CPU-bound.
