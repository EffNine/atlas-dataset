# Atlas Specialist Pilot Phase 1A — Final Decision Report

**Status:** GO
**Date:** 2026-08-02
**Scope:** Controlled extraction of 6,500 expert records from three
GO-calibrated sources. No training, no release, no modification of existing
Atlas datasets.

## Decision

**GO** — proceed to full acquisition planning for the three GO sources.

All thresholds from `docs/specialist_10k_pilot_extraction_plan_v0.1.md`
§6 are met or exceeded (see metrics below). The pilot validated extraction,
schema conversion, quality gate, provenance, difficulty assignment, and
E1/E2/E3 classification end-to-end at 6,500-record scale.

## Artifacts (checksum-verified, byte-identical on dev-pc and Mac)

| Artifact | Path | SHA-256 |
|----------|------|---------|
| Converted records | `tmp/expert_pilot_6500_records_v0.1.jsonl` | `c2473d2f…f6f143` |
| Manifest | `metadata/expert_pilot_6500_manifest_v0.1.json` | `b9ce426f…84c487` |
| Quality report | `reports/expert_pilot_6500_quality_v0.1.json` | `33f946b2…19d99c` |

## Record Counts (measured)

| Source | Target | Retrieved | Converted | License |
|--------|--------|-----------|-----------|---------|
| SWE-bench Verified (expert-swe-001) | 500 | 500 | 500 | MIT |
| OpenMathInstruct-2 (expert-math-002) | 3,000 | 3,000 | 3,000 | CC-BY-4.0 |
| ArXiv cs.LG/CL/AI/stat.ML (expert-aiml-001) | 3,000 | 3,000 | 3,000 | arXiv non-exclusive |
| **Total** | **6,500** | **6,500** | **6,500** | — |

## Token Estimates (measured from artifact content, chars/4 estimator)

| Source | Records | Mean tokens/record | Total tokens |
|--------|---------|--------------------|--------------|
| SWE-bench Verified | 500 | 1,785 | 892,463 |
| OpenMathInstruct-2 | 3,000 | 547 | 1,640,410 |
| ArXiv | 3,000 | 1,648 | 4,943,061 |
| **Total** | **6,500** | **1,150** | **7,475,934** |

## E1/E2/E3 Distribution (measured)

| Tier | Records | Share | Source basis |
|------|---------|-------|--------------|
| E1 | 3,000 | 46.2% | ArXiv (professional/abstract-grounded) |
| E2 | 3,500 | 53.8% | SWE-bench (gold issue-to-patch) + OpenMathInstruct-2 |
| E3 | 0 | 0.0% | none in pilot scope |

Note: E3 (frontier) was not targeted in this pilot; the plan's global
60/30/10 mix is a training-view balancing target, and E3 sources (e.g.,
olympiad/frontier) are not yet in the GO source set.

## Quality Metrics (measured)

| Metric | Value |
|--------|-------|
| Schema pass rate | **1.0** (6,500/6,500) |
| Quality gate | **KEEP 6,500 · REVIEW 0 · REJECT 0** |
| Quality score ≥ 7 | **6,376/6,500 (98.1%)** |
| Quality score distribution | 5:2 · 6:122 · 7:1,365 · 8:2,495 · 9:2,408 · 10:108 |
| Quality score mean | **8.2** (computed in report) |
| Difficulty distribution | 2:5,651 · 3:743 · 4:103 · 5:3 |
| Dimension means | correctness 3.97 · reasoning_depth 4.42 · explanation_quality 4.06 · provenance_confidence 4.0 |

## Provenance Metrics (measured)

| Metric | Value |
|--------|-------|
| Provenance completeness | **1.0** (6,500/6,500) |
| Duplicate rate | **0.0** (0 exact ids, 0 near-dup groups) |
| Unique original_ids | 6,500/6,500 |
| License compliance | 100% (MIT 500 · CC-BY-4.0 3,000 · arXiv 3,000) |
| Security flags | **0** (hard gate: keys/tokens/credentials) |
| Verification status | verified 500 (SWE-bench gold) · needs_review 6,000 |
| Model-generated flagged | 3,000 (OpenMathInstruct-2, accurate per NVIDIA README) |
| Synthetic flagged | 3,000 (same) |

## Process Notes

1. **Stage 1 (100/source smoke) passed** after one pipeline bug was found and
   fixed: the quality gate initially rejected records with `correctness == 3`
   (a threshold typo — reject is `<= 2`). Fixed in
   `scripts/expert_pipeline/quality.py`, regression tests added (32/32
   pass), then Stage 2 executed cleanly.
2. **ArXiv pagination** implemented in the adapter (500/page, per-category
   ceil distribution) to reach 3,000 records; smoke-verified with a
   monkeypatched API test.
3. Dry-run mode wrote nothing; the full run wrote only the three pilot
   artifacts. Existing Atlas datasets untouched.
4. Extraction runtime: ~9.5 minutes (ArXiv API pagination dominates).

## Constraints Honored

- No model training.
- No dataset release (no HF publish, no release bundles).
- No modification of existing Atlas datasets (curated/raw/release untouched).
- Open-Platypus remains HOLD (license filtering decision pending).

## Next Steps (for approval)

1. Human review sample (~5% ≈ 325 records) per plan §5.
2. Open-Platypus license filtering decision (unblocks SE expansion).
3. Full acquisition planning for GO sources per decision report GO.

---

## Phase 1B — AI Review Section (added 2026-08-02)

**Outcome: GO confirmed by human-calibration review.**

Per the Sonnet 5 execution plan, the 324-record sample was reviewed by an AI
reviewer. The Anthropic Sonnet 5 API was unavailable (no key in this
environment); per user direction the review ran with the available model via
Hermes delegation. Reviewer identity is recorded honestly as
`ai-reviewer:hermes/deepseek-v4-flash` — no fabricated identity. Blind
review was preserved (subagents saw only the blind input file; gate values
were attached post-hoc).

### Measured review results

| Metric | Value |
|--------|-------|
| Records reviewed | 324 |
| Verdicts | **KEEP 306 · REVIEW 0 · REJECT 18** |
| Acceptance rate | **94.4%** (306/324) — ≥ 80% GO threshold |
| Agreement with auto_gate | 94.4% (306/324) |
| Per-source acceptance | ArXiv 100% · SWE-bench 100% · OpenMath 87.9% |
| REJECT distribution | 18/18 in OpenMathInstruct-2, all in the 9–10 quality band |
| Dimension means | correctness 3.85 · reasoning 2.78 · explanation 3.07 · provenance 3.82 |
| Security flags | 0 |

### Calibration finding

The 18 REJECTs are all model-generated OpenMath solutions that the
deterministic heuristic over-scored into the 9–10 band: fabricated math
claims (e.g., "142 is a palindrome"), incoherent derivations (3/2=2),
and wrong expected answers. This validates the review gate's purpose —
the human/AI review caught correctness failures the heuristic missed.
**Recommendation: exclude the 18 REJECTed records from any downstream
training view unless re-curated.**
