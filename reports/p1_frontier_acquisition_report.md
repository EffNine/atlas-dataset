# P1 Frontier Acquisition Report

**Date:** 2026-08-14
**Phase:** P1 Frontier Expansion
**Status:** COMPLETE (3/4 sources)

## 1. Acquisition Summary

| Metric | Value |
|--------|-------|
| Total Sources | 4 |
| Completed | 3 |
| Blocked | 1 |
| Total Raw Records | 292,820 |
| Total Valid Records | 118,567 |
| Total Duplicates Removed | 40,164 |
| Total Eligible | 118,567 |
| Total Staging Size | 3731.9 MB |

## 2. SWE-smith-mini Results

- **Source:** Kwai-Klear/SWE-smith-mini_swe_agent_plus-trajectories-66k
- **License:** MIT (verified compatible)
- **Raw records:** 65,994 (47 parquet shards)
- **Valid records:** 65,985
- **Duplicates removed:** 9
- **Unique repositories:** 109
- **Trajectory length:** min=5, max=315, avg=69.6 messages
- **Tool messages:** 0 total
- **Observation tags:** 6 total
- **Contamination risk:** LOW (0 overlaps with SWE-bench Verified)
- **Frontier distribution:** A+=0, A=65833, B=152

## 3. Nemotron-Math-Proofs-v2 Results

- **Source:** nvidia/Nemotron-Math-Proofs-v2
- **License:** CC-BY-4.0 (attribution required)
- **Raw records:** 82,737
- **Valid records:** 43,779
- **Duplicates removed:** 38,958 (same problem, different proof/verification subsets)
- **Unique problems:** 5,752
- **Samples per problem avg:** 14.38
- **Proof length:** min=338, max=21909, avg=2681.5 chars
- **Domain distribution:** {'geometry': 25229, 'other': 36286, 'algebra': 2841, 'number-theory': 16494, 'analysis': 1619, 'combinatorics': 268}
- **Subset distribution:** {'proof': 24696, 'meta-verification': 29176, 'verification': 28865}
- **Contamination risk:** LOW (0 overlaps with math_eval_v2)
- **Frontier distribution:** A+=43736, A=43

## 4. Linux Kernel Commits (y9) Results

- **Source:** ewedubs/linux-kernel-commits-aireason-instruct
- **License:** Apache-2.0
- **Available records:** 144,089 (5 variants)
- **Sampled:** 10000 (deterministic stratified, seed=42)
- **Valid records:** 8,803
- **Duplicates removed:** 1,197
- **Variant distribution:** {'high_score': 3500, 'premium_score': 3500, 'high_reasoning': 1500, 'premium_reasoning': 1500, 'super_ultra': 500}
- **Subsystem distribution:** {'other': 8106, 'net': 294, 'drivers': 159, 'mm': 152, 'arch': 26, 'kernel': 23, 'fs': 20, 'include': 19, 'security': 3, 'init': 1}
- **Contamination risk:** LOW (0 overlaps with SWE-bench Verified)
- **Frontier distribution:** A+=7003, A=1797, B=3

## 5. StackExchange Systems (y5) Results

- **Status:** BLOCKED
- **Reason:** No suitable HuggingFace dataset with raw Q&A content found. Canonical source is archive.org XML dumps (unix.stackexchange.com, serverfault.com, networkengineering.stackexchange.com). The HF datasets found (mlfoundations-dev/stackexchange-unix-sandboxes, laion/stackexchange-unix-sandboxes-verified) contain compressed task archives, not extractable Q&A text.
- **Target:** 8,000 records
- **Actual:** 0
- **License:** CC-BY-SA-4.0 (attribution + share-alike required)
- **Attempted sources:
  - mlfoundations-dev/stackexchange-unix-sandboxes (10K rows, binary task archives)
  - laion/stackexchange-unix-sandboxes-verified (10K rows, binary task archives)
  - flax-sentence-embeddings/stackexchange_xml (361 7z archives, hundreds of GB)

## 6. License / Attribution

| Source | License | Class | Attribution Required | Share-Alike |
|--------|---------|-------|---------------------|-------------|
| SWE-smith-mini | MIT | VERIFIED COMPATIBLE | No | No |
| Nemotron-Math-Proofs-v2 | CC-BY-4.0 | VERIFIED COMPATIBLE | Yes | No |
| Linux kernel (y9) | Apache-2.0 | VERIFIED COMPATIBLE | Yes | No |
| StackExchange (y5) | CC-BY-SA-4.0 | BLOCKED | Yes | Yes |

## 7. Provenance

All records include complete provenance:
- `source.name`, `source.url`, `source.license`, `source.date` in every record
- `id` field includes source prefix (e.g., `p1-swe-smith-mini_...`)
- `notes` field documents acquisition phase and review status
- `tags` include source ID for traceability
- No `specialist_id` added to canonical records (policy-level mapping only)

## 8. Deduplication

### Within-Source Dedup
- SWE-smith-mini: 65,994 → 65,985 (9 exact content duplicates)
- Nemotron-Math-Proofs-v2: 82,737 → 43,779 (38,958 duplicates — same problem, different proof/verification subsets)
- Linux kernel (y9): 10,000 → 8,803 (1,197 duplicates — same commit across variants)

### Cross-Source Dedup
- Cross-source duplicates: 0

## 9. Quality

### Schema Validation
| Source | Records | Validation | Errors |
|--------|---------|------------|--------|
| SWE-smith-mini | 65,985 | PASS | 0 |
| Nemotron-Math-Proofs-v2 | 43,779 | PASS | 0 |
| Linux kernel (y9) | 8,803 | PASS | 0 |

### Quality Score Distribution
- SWE-smith-mini: uniformly 7 (source default)
- Nemotron-Math-Proofs-v2: uniformly 8 (formally verified)
- Linux kernel (y9): uniformly 8 (AI-scored quality)

## 10. Contamination

### Protected Eval Sets Checked
- math_eval_v2: No overlap with Nemotron (AoPS subset)
- code_eval_v2: No overlap
- general_eval_v1: No overlap
- IFEval: No overlap
- SWE-bench Verified (test): 0 overlaps with SWE-smith-mini

### Contamination Risk Assessment
| Source | Risk | Notes |
|--------|------|-------|
| SWE-smith-mini | MEDIUM | widely-used benchmarks; verified no overlap with SWE-bench Verified test split |
| Nemotron-Math-Proofs-v2 | MEDIUM | AoPS subset unlikely in eval sets; verified no overlap |
| Linux kernel (y9) | LOW | Kernel commits not in eval sets |
| StackExchange (y5) | N/A | Blocked — not acquired |

## 11. Frontier Tier Distribution

| Tier | Count |
|------|-------|
| A+ Frontier | 50,739 |
| A Strong Specialist | 67,673 |
| B Professional | 155 |
| C General | 0 |
| D Reject | 0 |

## 12. Specialist Inventory

### Domain Allocation
| Domain | Eligible Records |
|--------|-----------------|
| Code | 65,985 |
| Math | 43,779 |
| Systems | 8,803 |

## 13. Files Modified

### Staging Files
| File | Size |
|------|------|
| raw/p1/staging/p1-swe-smith-mini.jsonl | 3492.8 MB |
| raw/p1/staging/p1-nemotron-math-proofs-v2.jsonl | 198.3 MB |
| raw/p1/staging/p1-y9-linux-kernel.jsonl | 40.8 MB |

### Source Data
| Directory | Size |
|-----------|------|
| raw/p1/p1-swe-smith-mini/src/ | ~1.5 GB (47 parquet shards) |
| raw/p1/p1-nemotron-math-proofs-v2/src/ | ~17 GB (1 JSONL file) |
| raw/p1/p1-y9-linux-kernel/src/ | ~630 MB (5 JSONL variant files) |

## 14. Tests / Validation

- Schema validation: ALL PASS (0 errors)
- License validation: ALL VERIFIED COMPATIBLE
- Provenance validation: COMPLETE (source.name, source.url, source.license, source.date)
- Contamination check: NO OVERLAPS with protected eval sets
- Cross-source dedup: 0 duplicates

## 15. Remaining Gaps

### y5 StackExchange Systems
- **Status:** BLOCKED
- **Blocker:** No suitable HuggingFace dataset with raw Q&A content
- **Canonical source:** archive.org XML dumps (unix.stackexchange.com, serverfault.com, networkengineering.stackexchange.com)
- **Action required:** Manual acquisition from archive.org or find alternative HF-hosted source

### Additional Math Sources (recommended for future)
- kevin009/olympiad-math-stepwise-solutions-llama3-20k (~20K, unverified license)
- LinhIcey/mathematics_competition (~3K, Apache-2.0)

### Additional Code Sources (recommended for future)
- SWE-smith-trajectories full (5,017 trajectories, Claude 3.7 Sonnet teacher)

---

```
P1 ACQUISITION:
COMPLETE

Math:      0 → 43,779 (Nemotron full, 82,737 raw → 43,779 after dedup)
Code:      2,500 → 65,985 (SWE-smith-mini full)
Systems:   112 → 8,803 (y9 kernel sampled)
Hardware:  401 → 401 (unchanged)
General:   100 → 100 (unchanged)
Blocked:   y5 StackExchange (no suitable HF source)
```