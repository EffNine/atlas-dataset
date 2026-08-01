# ADR-012: Intelligence Layer

**Status:** Accepted
**Date:** 2026-08-01
**Phase:** 4C.4 — Engineering Stabilization

---

## Context

The Atlas dataset needs a per-record difficulty/intelligence signal so that
training views, evaluation sets, and curriculum sampling can distinguish
basic from advanced content. The raw dataset (v1.0, ~9.5M records) carries
content but no difficulty metadata.

Initial attempts were exploratory: `batch_classify.py` handled a small set
of v1.1 sources; difficulty scoring was ad-hoc and not versioned. As the
project moved toward v1.2 full-source classification (all wiki sources +
Stage 2 sources), three requirements emerged:

1. Every record must receive a deterministic difficulty classification
   (level + confidence).
2. Classification must be **reproducible** — same input → same output.
3. Outputs must be **appendable and crash-safe** — partial progress is
   never lost, and a restarted run must not duplicate records.

## Decision

Adopt a **versioned, deterministic, append-per-source intelligence layer**.

- **Classifier**: `scripts/intelligence/difficulty_analyzer.py` +
  `batch_classify_v2.py` (full-source parallel runner).
- **Levels**: L1 (Basic) … L5 (Research), each record gets
  `difficulty.level` + `difficulty.confidence`.
- **Versioning**: intelligence layer version `1.2.0`; outputs named
  `unknown_classified_v1.2.jsonl` with `classification_summary_v1.2.json`
  and `difficulty_distribution_v1.2.json`.
- **Crash safety**: `run_classify_all_v2.py` appends each source's output
  to the unified v1.2 file immediately after the source completes, then
  **deletes** the per-source file — a restart never double-appends and
  never loses completed sources.
- **Skip semantics**: `--skip <labels>` resumes a partially completed run
  without re-classifying finished sources.
- **Parallelism**: shard-level workers per source, counts from
  `config/parallelism.yaml` (stage1=8, stage2=10).

## Rationale

- Deterministic classification is a hard requirement for dataset
  reproducibility and for later training-view eligibility gates.
- Append-per-source + delete gives crash recovery with zero bookkeeping:
  the filesystem itself tracks what is done.
- Shard-level parallelism fully uses dev-pc's 16 cores without the memory
  contention of source-level parallelism.
- Versioned outputs keep v1.1 and v1.2 comparable and let downstream
  consumers pin a classification version.

## Alternatives Considered

1. **LLM-based difficulty scoring** — rejected: non-deterministic, costly
   at 9.5M records, and not reproducible across model versions.
2. **Single monolithic classification pass** — rejected: any crash loses
   everything; no incremental resumption.
3. **Source-level parallelism** — rejected for the default path: 16 workers
   × source-sized memory footprint risks OOM on dev-pc; sequential sources
   with parallel shards is the memory-safe optimum.

## Consequences

- **Positive**: reproducible difficulty signals, crash-safe pipeline,
  incremental resumption, clear per-source accounting.
- **Negative**: sequential-source execution leaves cores idle between
  sources; full 16-core utilization requires future source-level
  parallelism work (tracked, not default).
- **Negative**: a skipped source whose append never completed can silently
  drop records — mitigated by the verification workflow in the runbook.

## Future Revisions

- Add source-level parallelism when memory profiling shows headroom.
- Introduce intelligence v2 with improved confidence calibration (see
  quality-calibration baseline, ADR-008).
- Publish classification summary artifacts as part of release bundles.
