# Atlas Data Recovery Forensic Report

**Date:** 2026-08-19  
**Investigator:** Agnes (Forensic Agent)  
**Status:** Phase 1 — Investigation Complete  
**Classification:** FORENSIC — DO NOT MODIFY CANONICAL ARTIFACTS

---

## 1. Executive Verdict

**THE 9.5M RECORD RELEASE CLAIM IS NOT CURRENTLY PROVEN.**

The v1.0 release claims 9,515,938 records, but zero bytes of the actual dataset exist in the repository. The claimed record count originates from a locally-generated `review_queue/approved.jsonl` (9,893,844 lines) that was gitignored and never committed. The only surviving evidence of the dataset is:

- Manifest metadata (git-tracked, internally consistent)
- Join/dedup reports (git-tracked, describe expected behavior)
- HuggingFace Hub private repo (requires authentication token for access)
- ~475K auxiliary records (pilot, eval, benchmark — not the release dataset)

**Recovery classification: PARTIALLY RECONSTRUCTABLE.** The dataset can be recovered from HuggingFace Hub if the `HF_TOKEN` credential is available. Without it, reconstruction is impossible from repository evidence alone.

---

## 2. Current Ground Truth

| Artifact | Claimed Count | Actual Count | Hash (SHA-256) | Location | Confidence |
|----------|--------------|--------------|----------------|----------|------------|
| v1.0 manifest | 9,515,938 | N/A (metadata only) | `ed43824c...` (content_hash) | `metadata/releases/v1.0_release.json` | CONFIRMED |
| v1.0-RC2 manifest | 9,515,938 | N/A (metadata only) | `dce4b773...` (content_hash) | `metadata/releases/v1.0-RC2_release.json` | CONFIRMED |
| v1.0-RC1 manifest | 9,893,844 | N/A (metadata only) | `c2e117b9...` (content_hash) | `metadata/releases/v1.0-RC1_release.json` | CONFIRMED |
| v1.0 dataset | 9,515,938 | **0** | UNKNOWN | `releases/v1.0/` (does not exist) | CONTRADICTED |
| v1.0-RC2 dataset | 9,515,938 | **0** | UNKNOWN | `releases/v1.0-RC2/` (does not exist) | CONTRADICTED |
| v1.0-RC1 dataset | 9,893,844 | **0** | UNKNOWN | `releases/v1.0-RC1/dataset/` (.gitkeep only) | CONTRADICTED |
| approved.jsonl | 9,893,844 | **0** (deleted) | `faa333bd...` (55MB, historical blob) | `review_queue/approved.jsonl` (gitignored) | PROBABLE |
| raw/generated/ shards | ~9.2M | **0** (empty dir) | N/A | `raw/generated/` (gitignored, .gitkeep only) | PROBABLE |
| HF Hub v1.0-RC2 | 9,515,938 | Unknown (private repo) | `693f33b6...` (dataset commit) | `EffNine/atlas-dataset` (private) | UNKNOWN |
| HF Hub v1.0 final | 9,515,938 | Unknown (private repo) | `1370ac42...` (commit) | `EffNine/atlas-dataset` (private) | UNKNOWN |
| Currently discoverable JSONL | — | **~475,494** | varies | Multiple locations | CONFIRMED |
| Review queue approved | 0 | **0** | — | `review_queue/approved.jsonl` | CONFIRMED |
| Review queue pending | — | **0** | — | `review_queue/pending.jsonl` | CONFIRMED |
| Review queue rejected | — | **11** | — | `review_queue/rejected.jsonl` | CONFIRMED |

---

## 3. Record Lineage

```
SOURCE (external datasets)
  ↓
RAW (`raw/generated/`) — ~9.2M records across 311 shards
  |  Status: GITIGNORED, DELETED, NEVER COMMITTED
  |  Evidence: join_report.json claims 311 shards existed
  ↓
APPROVED (`review_queue/approved.jsonl`) — 9,893,844 records
  |  Status: GITIGNORED, DELETED, NEVER COMMITTED
  |  Git history max: 231,707 lines (commit 3975ec2)
  |  Jump to 9.89M occurred locally between 817350e and a8d26c2
  |  Evidence: join_report.json, investigation doc
  ↓
JOIN (`releases/v1.0-RC1/dataset/`) — 9,893,844 canonical records
  |  Status: GITIGNORED (*.jsonl, *.jsonl.zst), NEVER COMMITTED
  |  Output: 9 category dirs, .gitkeep only
  |  Evidence: join_report.json (13,302s runtime, zst format)
  ↓
DEDUP (`releases/v1.0-RC2/dataset/`) — 9,515,938 unique records
  |  Status: GITIGNORED, NEVER COMMITTED
  |  Input: RC1 dataset (now missing)
  |  Output: 377,906 duplicates removed (all wiki_sw, 02_software_engineering)
  |  Evidence: dedup_report.json (2,691s runtime)
  ↓
UPLOAD (HF Hub) — 15 files, 4.8 GB
  |  Status: Uploaded to private repo
  |  Commit: 693f33b6 (dataset section)
  |  Verification: local 31/31 PASS, remote sample SHA-256 MATCH
  |  Evidence: final_release_report.md
  ↓
RC2 Manifest — signed, chain-linked to RC1
  |  Status: GIT-Tracked, UNMODIFIED since commit e55e1e6
  ↓
v1.0 Manifest — promoted from RC2
  |  Status: GIT-Tracked, UNMODIFIED since commit fccb04d
```

---

## 4. Missing Record Analysis

### 4.1 Where the ~9M Records Are Unaccounted For

The 9,515,938 claimed records are **entirely absent** from the repository. The breakdown:

| Component | Claimed | Found | Gap |
|-----------|---------|-------|-----|
| `review_queue/approved.jsonl` | 9,893,844 | 0 (deleted) | 9,893,844 |
| `raw/generated/*_atlas.jsonl` shards | ~9,185,508 | 0 (empty dir) | ~9,185,508 |
| `releases/v1.0-RC1/dataset/*.jsonl.zst` | 9,893,844 | 0 (.gitkeep only) | 9,893,844 |
| `releases/v1.0-RC2/dataset/*.jsonl.zst` | 9,515,938 | 0 (dir missing) | 9,515,938 |
| HF Hub private repo | 9,515,938 | Unknown (401 Unauthorized) | UNKNOWN |

### 4.2 Root Cause of Disappearance

1. **Git ignore rules** explicitly exclude all dataset artifacts:
   - `raw/generated/*` (source shards)
   - `releases/*/dataset/**/*.jsonl` and `**.jsonl.zst` (release datasets)
   - `review_queue/approved.jsonl` (approved record index)

2. **No Git LFS** is configured (`.gitattributes` empty, `git lfs ls-files` returns nothing)

3. **No large dataset blobs** exist in git object history (verified via `git rev-list --all --objects`)

4. **The approved.jsonl was deleted** in commit 817350e when it was moved to `.gitignore`

5. **The raw/generated/ shards were never committed** — they were generated locally by Wikipedia/arXiv/C4/OpenWebMath extraction scripts

6. **The release datasets were generated locally** by `join_release.py` and `dedup_release.py`, then uploaded to HF Hub

### 4.3 What Actually Exists Today

**Currently discoverable records (non-release):**
- Pilot data: ~4,499 records (`pilot/v0.2/`)
- Raw staging: ~436K records (`raw/p0/`, `raw/p1/`)
- Eval sets: ~2,000 records (`evaluation/eval_sets/`)
- Experiment subsets: ~15,000 records (`experiments/phase*/`)
- Benchmark results: ~500 records (`benchmarks/eb/`)
- Review artifacts: ~7,000 records (`review/`, `review_queue/rejected.jsonl`)
- **Total: ~475,494 records**

**None of these are part of the v1.0 release.**

---

## 5. RC1 → RC2 Investigation

### 5.1 Count Change

| Metric | RC1 | RC2 | Delta |
|--------|-----|-----|-------|
| Total records | 9,893,844 | 9,515,938 | -377,906 |
| Duplicates removed | — | 377,906 | All from `wikimedia/wikipedia`, category `02_software_engineering` |
| Conflicts | — | 0 | None |

### 5.2 License Collapse (CRITICAL FINDING)

| License | RC1 | RC2 | Delta |
|---------|-----|-----|-------|
| CC-BY-SA-3.0 | 6,471,355 | 112,901 | **-6,358,454** |
| unknown | 1,543,548 | 7,972,390 | +6,428,842 |
| MIT | 1,007,774 | 205,243 | -802,531 |
| ODC-BY | 869,441 | 1,166,924 | +297,483 |
| Apache-2.0 | 1,726 | 43,844 | +42,118 |
| Other (detailed) | 0 | 113,436 | +113,436 |

**This cannot be explained by deduplication alone.** Removing 377,906 wiki_sw duplicates would change CC-BY-SA-3.0 by at most ±377,906. The actual change is -6,358,454.

### 5.3 Explanation

The RC2 manifest was built by `dedup_release.py` → `compute_statistics()` which reads license metadata from the actual dataset records. The RC1 dataset records must have had proper license attribution (6.47M CC-BY-SA-3.0). The RC2 manifest's license distribution (112K CC-BY-SA-3.0, 7.97M unknown) indicates that either:

**A.** The RC1 dataset files that were read during dedup had lost their license metadata (records had `license: null` or missing `license` field, falling back to `"unknown"`), OR

**B.** The RC2 manifest was manually constructed with incorrect license statistics, OR

**C.** A different dataset (without Wikipedia license attribution) was used for the RC2 build.

**Evidence favoring (A):** The `compute_statistics()` function reads `rec.get("license") or "unknown"`. If the RC1 dataset records had collapsed license fields, the RC2 stats would show this pattern.

**Evidence favoring (B):** The RC2 manifest's detailed license distribution (dozens of specific license strings like "CC-BY-4.0 (generated; human-review)") suggests manual curation rather than automated computation from records.

**Verdict: UNKNOWN without access to the RC1 dataset files.** The license collapse is a critical integrity issue.

### 5.4 Hash Verdict

**RC1 manifest hash: CONSISTENT.** The committed RC1 manifest (commit a8d26c2) is byte-identical to the current file. No post-signing modification detected.

**RC2 manifest hash: CONSISTENT.** The committed RC2 manifest (commit e55e1e6) is byte-identical to the current file.

**The "hash mismatch" reported by the Red Team likely refers to the DATASET hash, not the manifest hash.** The dataset was never committed, so there is no on-dataset hash to verify against. The manifest's `content_hash` field represents the hash of the dataset at signing time, but the dataset is no longer available to verify.

---

## 6. Hash Investigation

### 6.1 Manifest Hash Chain

| Version | content_hash | chain_hash | previous_hash | release_id |
|---------|-------------|------------|---------------|------------|
| v0.1 | `fc711fe6...` | `34e190d3...` | (none) | `34e190d3...` |
| v0.2 | `60b99368...` | `2931c7c4...` | `34e190d3...` | `2931c7c4...` |
| v0.3 | `1e75d0d4...` | `009285f2...` | `2931c7c4...` | `009285f2...` |
| v1.0-RC1 | `c2e117b9...` | `e66408aa...` | `009285f2...` | `e66408aa...` |
| v1.0-RC2 | `dce4b773...` | `d7cab614...` | `e66408aa...` | `d7cab614...` |
| v1.0 | `ed43824c...` | `4dcfd43e...` | `d7cab614...` | `4dcfd43e...` |

**Chain integrity: VERIFIED** (each `previous_hash` matches the prior release's `chain_hash`)

### 6.2 RC1 Manifest Modification Check

```
Committed (a8d26c2): md5=c97b271f...  ← wait, this was RC2
Committed RC1 (a8d26c2): md5=30343807...
Current RC1:            md5=30343807...
IDENTICAL — no post-signing modification
```

**The RC1 manifest was NOT modified after signing.** The Red Team's "hash mismatch" finding appears to be a misinterpretation. The manifest hashes are consistent.

### 6.3 What the Hash Mismatch Actually Refers To

The remediation report states: "v1.0-RC1 hash mismatch — Manifest was modified after signing." However:

1. The RC1 manifest in git is byte-identical to the current file
2. The `content_hash` in the manifest does NOT equal the SHA-256 of the manifest file itself (by design — `content_hash` is the hash of the dataset, not the manifest)
3. The dataset is missing, so the `content_hash` cannot be verified

**The "mismatch" is that the dataset referenced by `content_hash` no longer exists.** This is a data availability issue, not a manifest tampering issue.

---

## 7. License Investigation

### 7.1 Tracing License Through the Pipeline

The `join_release.py` script merges approved stub metadata (including `license`) into shard content:

```python
STUB_AUTHORITY_FIELDS = (
    "category", "subcategory", "quality_score", "license",
    "verification_status", "verification_date", "reviewer",
)
```

The `merge_record()` function overrides shard content with approved stub fields. So the license in the release should come from `approved.jsonl`.

### 7.2 Where License Was Lost

**RC1 manifest** shows correct license distribution:
- CC-BY-SA-3.0: 6,471,355 (Wikipedia)
- MIT: 1,007,774
- ODC-BY: 869,441
- unknown: 1,543,548

**RC2 manifest** shows collapsed license distribution:
- unknown: 7,972,390 (83.8%)
- ODC-BY: 1,166,924
- MIT: 205,243
- CC-BY-SA-3.0: 112,901 (1.2%)

### 7.3 Quantification

| Category | Affected | Recoverable | Unrecoverable |
|----------|----------|-------------|---------------|
| CC-BY-SA-3.0 (Wikipedia) | ~6,358,454 | **PARTIALLY** — source is wikimedia/wikipedia on HF Hub; can re-extract with license | ~112,901 properly attributed remaining |
| MIT (dropped from 1M to 205K) | ~802,531 | **LIKELY** — sources include GitHub repos, can re-attribute | UNKNOWN |
| unknown (increased from 1.5M to 8M) | ~6,428,842 | **PARTIALLY** — can be resolved from source metadata | Portion from synthetic/personal-assistant (legitimately unknown) |

### 7.4 Root Cause

The RC2 license collapse occurred during the `compute_statistics()` phase of `dedup_release.py`. The most likely cause:

1. RC1 dataset was generated with proper license from `approved.jsonl` stubs
2. During dedup, the RC1 zst files may have been regenerated or re-read from a source that lost license metadata
3. Alternatively, the RC2 manifest's `by_license` was manually constructed rather than computed from actual records

**The RC1 dataset files are the only authoritative source for license metadata.** They are missing from the repository but should exist on HF Hub.

---

## 8. Human Review Investigation

### 8.1 The False Approval Claim

All v1.x manifests claim `human_review_gate.passed = true` with `approved: 9,515,938`. However:

- `review_queue/approved.jsonl` **does not exist** (deleted, gitignored)
- Current review queue: 0 approved, 0 pending, 11 rejected

### 8.2 How the Old System Claimed Approval

The pre-remediation `dedup_release.py` had this code:

```python
review_gate = {"passed": False, "approved": 0, "rejected": 0, "checked_at": now, "error": "No evidence found"}
if root:
    review_check = verify_human_review_gate(root)
    if review_check["passed"]:
        review_gate = {"passed": True, "approved": review_check["approved_count"], ...}
```

But `verify_human_review_gate()` checks for `approved.jsonl` existence. Since the file was gitignored and presumably existed locally during the original run, the gate passed. After the file was gitignored and the repo was cloned elsewhere, the file is absent.

### 8.3 Historical Approved Count

The git-tracked history of `approved.jsonl` shows:

| Commit | Count | Description |
|--------|-------|-------------|
| 965abc5 | 45 | v0.2 expansion |
| 14193e7 | 250 | v0.2 pending |
| 5db4672 | 17,288 | CodeAlpaca |
| 9ed0399 | 190,949 | Batch 173k |
| ef63d3b | 209,488 | SWE-bench |
| d701c5e | 212,328 | ArXiv/SO/GitHub |
| 0e9e3d7 | 222,284 | GSM8K + Finance-Alpaca |
| 3975ec2 | 231,707 | Capybara |
| 817350e | 0 (deleted) | Tulu-3 731k; gitignored |

**The git-tracked approved.jsonl never exceeded 231,707 records.** The jump to 9,893,844 occurred in the locally-generated file that was deleted when gitignored.

### 8.4 Join Report Evidence

The join report (`reports/releases/v1.0-RC1_join_report.json`) states:

```json
"approved_records": 9893844,
"full_records_inline": 8350296,
"stub_records": 1543548,
"joined_from_shards": 1543298,
"joined_from_pilot": 250
```

This confirms the 9.89M figure came from a local `approved.jsonl` that contained:
- 8,350,296 full records (with messages inline)
- 1,543,548 stubs (ID + review metadata only)

**These 9.89M records were never committed to git.** They existed only locally and on HF Hub.

---

## 9. External Artifact Investigation

### 9.1 HuggingFace Hub

| Property | Value |
|----------|-------|
| Repo ID | `EffNine/atlas-dataset` |
| Repo type | Dataset (private) |
| RC2 commit | `693f33b6082d46b0854cb495e001cfaa6e30b1bc` |
| v1.0 commit | `1370ac420b55fd9d2f7f7b0d26971beafed8ba80` |
| Files uploaded | 15 (9 dataset zst + 4 metadata + 2 docs) |
| Total size | 4.8 GB |
| Access | **PRIVATE** — requires `HF_TOKEN` |
| Verification | Local 31/31 PASS, remote sample SHA-256 MATCH at upload time |

### 9.2 Recovery Command

```bash
export HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxx
python scripts/release/download_release.py \
    --repo-id EffNine/atlas-dataset \
    --release v1.0-RC2 \
    --output releases/restored/v1.0-RC2 \
    --verify
```

### 9.3 Other External References

| Source | Status |
|--------|--------|
| `wikimedia/wikipedia` (HF dataset) | Public — can re-extract |
| `allenai/c4` (HF dataset) | Public — can re-extract |
| `open-web-math/open-web-math` (HF dataset) | Public — can re-extract |
| `ai2-adapt-dev/tulu_v3.9_*` (HF datasets) | Public — can re-extract |
| `CShorten/ML-ArXiv-Papers` (HF dataset) | Public — can re-extract |
| `princeton-nlp/SWE-bench` (HF dataset) | Public — can re-extract |
| Various arXiv subsets | Public — can re-extract |

---

## 10. Recovery Classification

### **PARTIALLY RECONSTRUCTABLE**

**Rationale:**

1. **Dataset recovery path exists** via HuggingFace Hub download (`download_release.py`) IF `HF_TOKEN` is available
2. **Source data is recoverable** — all upstream sources (Wikipedia, C4, OpenWebMath, arXiv, Tulu-3, etc.) are publicly available on HF Hub
3. **License attribution can be restored** — Wikipedia records can be re-attributed CC-BY-SA-3.0 from source metadata
4. **The join/dedup pipeline is reproducible** — `join_release.py` and `dedup_release.py` are deterministic given the same inputs
5. **The approved.jsonl cannot be recovered** — it was a local file that was deleted and never committed; however, it can be regenerated by re-running the review pipeline on recovered source data

**What prevents FULL reconstruction:**
- The exact `approved.jsonl` (9.89M records with review metadata) is unrecoverable from git
- The exact HF Hub dataset state is inaccessible without `HF_TOKEN`
- Some license metadata in RC2 is corrupted/lost

**Classification: PARTIALLY RECONSTRUCTABLE** — Recovery is possible with HF_TOKEN; without it, reconstruction from scratch is feasible but produces a different approved.jsonl (different review decisions, potentially different IDs).

---

## 11. Evidence Index

### 11.1 Key Files

| File | Evidence |
|------|----------|
| `metadata/releases/v1.0_release.json` | v1.0 manifest (9,515,938 records, status=final) |
| `metadata/releases/v1.0-RC2_release.json` | RC2 manifest (9,515,938 records, status=release_candidate) |
| `metadata/releases/v1.0-RC1_release.json` | RC1 manifest (9,893,844 records, status=release_candidate) |
| `metadata/release_index.json` | Release chain with HF commit references |
| `reports/releases/v1.0-RC1_join_report.json` | Join pipeline evidence (9,893,844 approved records) |
| `reports/releases/v1.0-RC2_dedup_report.json` | Dedup evidence (377,906 duplicates removed) |
| `reports/releases/v1.0-RC1_duplicate_audit.json` | Duplicate audit (all wiki_sw, byte-identical) |
| `reports/releases/v1.0-RC2_final_release_report.md` | Upload evidence (15 files, 4.8GB, SHA-256 verified) |
| `docs/v1.0-RC1_release_input_investigation.md` | Investigation documenting approved.jsonl as authoritative |
| `docs/release_join_stage.md` | Join pipeline documentation |
| `review_queue/approved.jsonl` | MISSING — was 9.89M records, now deleted/gitignored |
| `raw/generated/` | MISSING — was ~9.2M records across 311 shards, now empty |
| `releases/v1.0-RC1/dataset/` | MISSING — .gitkeep only, no actual data |

### 11.2 Key Commits

| Commit | Date | Significance |
|--------|------|---------------|
| `817350e` | 2026-07-29 | Last approved.jsonl commit (231,707 records); then gitignored |
| `a8d26c2` | 2026-07-30 | RC1 manifest committed (9,893,844 records) |
| `171a87b` | 2026-08-01 | RC1 skeleton committed (.gitkeep only, no data) |
| `e55e1e6` | 2026-08-01 | RC2 manifest committed (9,515,938 records) |
| `81dc9e7` | 2026-08-01 | HF Hub upload (15 files, 4.8GB) |
| `fccb04d` | 2026-08-01 | v1.0 promotion from RC2 |

### 11.3 Key Commands

```bash
# Verify manifest hash consistency
git show a8d26c2:metadata/releases/v1.0-RC1_release.json | md5sum
cat metadata/releases/v1.0-RC1_release.json | md5sum
# Result: IDENTICAL

# Check approved.jsonl history
git log --all --oneline -- review_queue/approved.jsonl
git show 3975ec2:review_queue/approved.jsonl | wc -l
# Result: 231,707 (max historical count)

# Check gitignored paths
grep -E "(jsonl|zst|generated|approved)" .gitignore
# Result: raw/generated/*, releases/*/dataset/**/*.jsonl*, review_queue/approved.jsonl

# Count currently available records
find . -path "./.git" -prune -o -name "*.jsonl" -type f -print | xargs wc -l
# Result: ~475,494 total (pilot, eval, benchmark — not release data)
```

---

## 12. Recommended Recovery Plan (Phase 2)

### Step 1: Obtain HF_TOKEN
- Locate the `HF_TOKEN` used for the original upload (check credential store, `.env` backup, or ask the original operator)
- Without this, the HF Hub dataset is inaccessible

### Step 2: Download RC2 from HF Hub
```bash
export HF_TOKEN=hf_xxx
python scripts/release/download_release.py \
    --repo-id EffNine/atlas-dataset \
    --release v1.0-RC2 \
    --output releases/restored/v1.0-RC2 \
    --verify
```

### Step 3: Verify Downloaded Dataset
```bash
python scripts/release/verify_release.py --release v1.0-RC2
# Expected: 31/31 checks pass
```

### Step 4: Restore License Attribution
For Wikipedia records (CC-BY-SA-3.0), re-attach license from source:
```python
# Pseudocode for license restoration
for rec in dataset:
    if rec.get("source") == "wikimedia/wikipedia":
        rec["license"] = "CC-BY-SA-3.0"
```

### Step 5: Regenerate approved.jsonl (Optional)
If the exact approved.jsonl is needed:
- Extract record IDs from the restored dataset
- Cross-reference with `review_queue/rejected.jsonl` (11 records, git-tracked)
- Reconstruct the approval state from manifest + rejected list

### Step 6: Update v1.0 Manifest
Once RC2 is restored and verified:
- The v1.0 manifest is already correct (promoted from RC2)
- No manifest regeneration needed

### What Cannot Be Recovered
- The exact `approved.jsonl` file (9.89M records with review metadata)
- The exact `raw/generated/` shards (pre-join source data)
- Any review decisions that were not captured in the manifest

---

## Appendix A: Current Repository State Summary

| Directory | Status | Records | Notes |
|-----------|--------|---------|-------|
| `raw/generated/` | Empty (.gitkeep) | 0 | Gitignored, never committed |
| `raw/p0/` | Partial | ~350K | Source seeds, not release data |
| `raw/p1/` | Partial | ~86K | Pilot sources |
| `curated/v0.1/` | Skeleton | 0 | .gitkeep only |
| `curated/v1.0/` | Skeleton | 0 | .gitkeep only |
| `releases/v1.0-RC1/dataset/` | Skeleton | 0 | .gitkeep only |
| `releases/v1.0-RC2/` | Missing | 0 | Never committed |
| `releases/restored/` | Empty | 0 | Awaiting download |
| `review_queue/approved.jsonl` | Deleted | 0 | Gitignored, was 9.89M |
| `review_queue/rejected.jsonl` | Present | 11 | Git-tracked |
| `metadata/releases/` | Complete | — | All manifests present |

---

*Report generated: 2026-08-19*  
*Forensic investigation phase complete. No artifacts modified.*
