# Phase 7.1 — Dataset Scaling Pre-flight Audit

> **Phase:** 7.1 (original audit + correction)
> **Status:** COMPLETE — audit only. **No training, no dataset modification.**
> **Date:** 2026-08-04
> **Substrates audited:** M1 (117), M2 (500), M3 (1000) math training subsets.
> **Source:** `expert-pilot-6500-v0.1` math pool (`expert-math-002`, N=3000).
> **Revision:** v2 — M1 rebuilt so subsets are nested (see §5–6).

---

## 1. Selection method (locked)

Per Phase 7.0 plan (§4.2), **all three subsets now use the same ordering**:

- **M1** = first **117** records of the eligible pool ordered by
  `sha256("phase7-scale-v1:{record_id}")`.
- **M2** = first **500** records of the same ordering.
- **M3** = first **1000** records of the same ordering.
- Eligible pool = `expert-pilot-6500` math records excluding `math_eval_v1`
  (100) and training-view eval (13) record IDs and REJECT-reviewed records.
  Net eligible: **2882**.
- **M1 rebuild (Phase 7.1 correction):** M1 previously used the materialized
  `math_300m_v0.1/train.jsonl` (117 records, `phase2b-materialization-v0.1`
  ordering), which was NOT a subset of M2/M3. It is now drawn from the
  `phase7-scale-v1` ordering so that **M1 ⊂ M2 ⊂ M3**. The frozen
  `math_300m_v0.1/train.jsonl` and Phase 5B.1 adapter are untouched.

---

## 2. Comparison table — M1 / M2 / M3 (post-correction)

| Check | M1 (117) | M2 (500) | M3 (1000) | Status |
|-------|----------|----------|-----------|--------|
| **Category** | mathematics: 117 | mathematics: 500 | mathematics: 1000 | ✅ uniform |
| **Difficulty (2/3/4)** | 98 / 16 / 3 | 407 / 85 / 8 | 816 / 164 / 20 | ✅ present |
| **Expert tier** | E2: 117 | E2: 500 | E2: 1000 | ✅ uniform |
| **Source** | expert-math-002: 117 | expert-math-002: 500 | expert-math-002: 1000 | ✅ uniform |
| **License** | CC-BY-4.0: 117 | CC-BY-4.0: 500 | CC-BY-4.0: 1000 | ✅ uniform |
| **Original ID present** | 117/117 | 500/500 | 1000/1000 | ✅ |
| **Duplicate record IDs** | 0 | 0 | 0 | ✅ |
| **Duplicate original IDs** | 0 | 0 | 0 | ✅ |
| **Leakage vs math_eval_v1** | 0 | 0 | 0 | ✅ |
| **Leakage vs tv_eval (13)** | 0 | 0 | 0 | ✅ |
| **Records SHA-256** | `219dbaf2…` | `24b5f1e0…` | `a1b54810…` | ✅ |
| **Raw file SHA-256** | `2dad9e24…` | `ba0f1c84…` | `c1bddd4c…` | ✅ |

Raw file hashes match the staged subset files written under
`experiments/phase7_scale/subsets/` (audit artifacts, **not** frozen views).
M2/M3 checksums are unchanged from the original audit; only M1 changed
(rebuilt from the `phase7-scale-v1` ordering).

---

## 3. Distribution drift

### 3.1 Difficulty drift (post-correction)

| Difficulty | M1 | M2 | M3 | Δ (M1→M3 share) |
|-----------|-----|-----|------|-----------------|
| 2 | 83.8% | 81.4% | 81.6% | −2.2 pts |
| 3 | 13.7% | 17.0% | 16.4% | +2.7 pts |
| 4 | 2.6% | 1.6% | 2.0% | −0.6 pts |

**Drift:** minor and non-monotone — M1 (98/16/3) and M2 (407/85/8) and M3
(816/164/20) differ by at most ~2.7 points in any difficulty share. This is the
expected effect of adding more of the harder tail. Not a control breaker; the
mix change is small and documented.

### 3.2 Category / provenance drift

None. All subsets are 100% mathematics, expert-math-002, CC-BY-4.0, E2. No
source or license drift.

---

## 4. Checksum manifest

Each subset produced both a **records checksum** (SHA-256 over canonical sorted
JSON) and a **raw-file SHA-256** (the staged `.jsonl`). These are recorded in
`experiments/phase7_scale/audit/phase7_subset_audit.json` and can be re-derived
deterministically from the fixed selection method + seed.

---

## 5. Subset NESTING — previous issue → correction

### 5.1 Previous issue (original audit)

For a controlled scaling study, subsets should be **nested** so that only *size*
varies: M1 ⊂ M2 ⊂ M3. The original audit found M1 was **not** nested:

- Only **3 / 117** of M1's records appeared in the phase7-order first-117.
- **98 / 117** of M1's records were absent from M2 entirely.
- Cause: M1 used the materialized-view ordering
  (`phase2b-materialization-v0.1`, from the KEEP-reviewed 131-record pool),
  while M2/M3 used the `phase7-scale-v1` ordering.

**Consequence:** comparing M1 vs M2 was NOT a pure size comparison — it also
changed which records were trained on.

### 5.2 Correction (this revision)

M1 was rebuilt from the **same `phase7-scale-v1` ordering** as M2/M3 (first 117
of the eligible pool). The frozen `math_300m_v0.1/train.jsonl` and Phase 5B.1
adapter were **not modified** (checksums verified unchanged). Re-audit result:

| Nesting relation | Holds? |
|------------------|--------|
| M1 ⊂ M2 | ✅ **yes** (0 records missing) |
| M1 ⊂ M3 | ✅ **yes** (0 records missing) |
| M2 ⊂ M3 | ✅ **yes** (0 records missing) |

`M1_not_in_M2_count = 0`, `M2_not_in_M3_count = 0`. Subsets are now properly
nested; only dataset size varies across the M1→M2→M3 comparison.

---

## 6. Final approval status

**Is the scaling experiment controlled? — YES.**

All gates now pass:

1. ✅ **Nesting:** M1 ⊂ M2 ⊂ M3 (verified, 0 missing records each).
2. ✅ **Category:** 100% mathematics in all subsets.
3. ✅ **Difficulty:** present and near-constant mix (≤ 2.7 pts drift).
4. ✅ **Provenance:** 100% expert-math-002 / CC-BY-4.0 / original_id present.
5. ✅ **Duplicates:** 0 duplicate record IDs and 0 duplicate original IDs.
6. ✅ **Leakage:** 0 overlap with `math_eval_v1` (100) and tv_eval (13).
7. ✅ **Checksums:** records + raw-file SHA-256 recorded and reproducible from
   the fixed seed (`phase7-scale-v1`); M2/M3 unchanged, M1 rehashed.
8. ✅ **Frozen assets untouched:** `math_300m_v0.1/train.jsonl`,
   `eval.jsonl`, `manifest.json` and Phase 5B.1 adapter checksums unchanged.

**Recommendation:** the scaling experiment is approved to proceed **pending the
separate human approval gate** (per Atlas governance). No training starts until
that explicit approval is granted. If training proceeds, M1/M2/M3 must be the
staged `experiments/phase7_scale/subsets/*` files (not the frozen view) and
their checksums recorded in each run's training log.

---

## 7. Artifacts

| Artifact | Path |
|----------|------|
| Audit JSON | `experiments/phase7_scale/audit/phase7_subset_audit.json` |
| Staged M1 subset | `experiments/phase7_scale/subsets/M1_math_train.jsonl` |
| Staged M2 subset | `experiments/phase7_scale/subsets/M2_math_train.jsonl` |
| Staged M3 subset | `experiments/phase7_scale/subsets/M3_math_train.jsonl` |
| Audit script (reproducible) | `scripts/evaluation_engine/audit_phase7_subsets.py` |
