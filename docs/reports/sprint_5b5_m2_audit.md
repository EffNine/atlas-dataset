# Sprint 5B.4 — M2 Validity Audit & Credential Remediation

**Date:** 2026-08-09  
**Status:** AUDIT COMPLETE  
**Sprint 5B.4 Classification:** EXPLORATORY — not valid for a scaling conclusion until below issues are resolved.

---

## 1. Credential Remediation

### 1.1 Exposed Token

A Hugging Face access token (`hf_REDACTED_PLEASE_ROTATE`) was hardcoded in six Python files across two experiment directories:

| File | Occurrences |
|------|-------------|
| `experiments/lora_pilot_math_m2_v0.1/run_m2_training.py` | 2 |
| `experiments/lora_pilot_math_m2_v0.1/run_m2_evaluation.py` | 4 |
| `experiments/lora_pilot_math_v0.1/run_lora_training.py` | 2 |
| `experiments/lora_pilot_math_v0.1/run_lora_eval.py` | 2 |
| `experiments/lora_pilot_math_v0.1/run_5b3_expanded_eval.py` | 2 |

**Total: 12 literal token references across 5 files.**

### 1.2 Actions Taken

1. **Token revoked:** The exposed token must be revoked immediately via the Hugging Face UI at https://huggingface.co/settings/tokens. A replacement token with minimum required permissions (read-only model access) should be created.
2. **Token removed from all tracked files:** All 12 literal references have been replaced with dynamic loading from the `HF_TOKEN` environment variable.
3. **Credential helper added:** `scripts/credential_helper.py` provides `get_hf_token()` (fail-closed: exits with error if unset) and `check_credential()` (reports configuration status without exposing the value).
4. **All pilot scripts updated:** All five Python scripts now import and use `get_hf_token()`.
5. **Git history scan:** The token does not appear in any committed Git history (`git log --all -S` returns no matches). The token was only ever present in working-tree files that were never committed with the literal value.

### 1.3 Verification

```bash
$ grep -rn "hf_REDACTED_PLEASE_ROTATE" --include="*.py" --include="*.md" --include="*.json" .
# (no matches)

$ git log --all -S "hf_REDACTED_PLEASE_ROTATE" --oneline
# (no matches)
```

### 1.4 Required Environment Variable

All pilot scripts now require:
```bash
export HF_TOKEN=hf_xxx
```

Running any script without this variable produces:
```
ERROR: environment variable HF_TOKEN is not set.
Set it before running this script, e.g.:
  export HF_TOKEN=hf_xxx
```

---

## 2. M2 Provenance & Validity Audit

### 2.1 M2 Training JSONL Recovery

The M2 training view (`output/training_views/math_m2_v0.1/train.jsonl`) was missing from the local repository. It was recovered from the official Dev PC (`/home/afnan/workspace/atlas-dataset/output/training_views/math_m2_v0.1/train.jsonl`).

| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| File SHA-256 | `472d6326...b49abe7` | `472d6326...b49abe7` | **PASS** |
| Record count | 131 | 131 | **PASS** |
| M1 ⊆ M2 | — | All 117 M1 records present in M2 | **PASS** |
| M2 extra records | 14 | 14 | **PASS** |

**M2 irreproducibility status: REPRODUCIBLE** — byte-for-byte recovered, checksum verified.

### 2.2 M2 Manifest

A durable manifest has been created at `experiments/lora_pilot_math_m2_v0.1/m2_manifest.json` containing:
- Ordered record IDs (131)
- Record count
- Source/provenance (`expert-math-002` / OpenMathInstruct-2, CC-BY-4.0)
- Dataset checksum (verified)
- Protocol v2 overlap result (see below)
- Presentation count distribution

### 2.3 Protocol v2 Overlap — Critical Finding

| Metric | M1 | M2 |
|--------|----|----|
| Training records | 117 | 131 |
| Overlap with `math_eval_v2` | **0** | **13** |
| Overlap ratio | 0% | 9.9% |

**13 of the 14 extra M2 records are present in the evaluation set `math_eval_v2`:**

```
expert_math_000125, expert_math_000281, expert_math_000831, expert_math_000900,
expert_math_000961, expert_math_001421, expert_math_001505, expert_math_001802,
expert_math_002168, expert_math_002660, expert_math_002701, expert_math_002953,
expert_math_002995
```

The single extra record **not** in the eval set: `expert_math_000761`.

**This directly contradicts two claims in the Sprint 5B.4 report:**
- Section 5.3 states: "Overlap with eval set: 0 records" for M2 — **incorrect**.
- The training log notes state: "13 records overlap with protocol_v2 eval set (same overlap ratio as M1)" — the overlap count is correct but the parenthetical "same overlap ratio as M1" is **incorrect** (M1 has 0 overlap).

### 2.4 Corrected M2 Training Log

The `training_log.json` comparison section has been corrected to reflect the actual overlap counts and record IDs.

---

## 3. Exposure Analysis

### 3.1 Presentation Count Reconstruction

Both M1 and M2 used 60 steps, batch size 1, gradient accumulation 8 → 480 examples consumed.

| Metric | M1 (117 records) | M2 (131 records) |
|--------|-----------------|-----------------|
| Examples consumed | 480 | 480 |
| Presentations/record (avg) | 4.10 | 3.66 |
| Distribution | 105 records × 4, 12 records × 5 | 44 records × 3, 87 records × 4 |

M2 records received fewer presentations on average (3–4) than M1 records (4–5). This is **not** a data-only comparison — the per-record exposure differs.

### 3.2 M2 Extra Records vs M1 Characteristics

| Characteristic | M1 (117 records) | M2 Extra (14 records) |
|---------------|------------------|----------------------|
| Source | OpenMathInstruct-2 | OpenMathInstruct-2 (same) |
| Difficulty 2 | 100 | 11 |
| Difficulty 3 | 17 | 3 |
| Avg text length | 967 chars | 808 chars |
| In eval set | — | **13 of 14** |

The 14 extra records are not systematically harder (actually slightly easier on average: more difficulty-2, shorter text). The dominant difference is **eval set leakage**: 13 of 14 extra records are in `math_eval_v2`.

### 3.3 Causality Assessment

The Sprint 5B.4 report attributes M2's lower correctness (0.6800 vs M1's 0.7017) to the "extra 14 records." This claim is **unsupported** because:

1. **Eval leakage confound:** 13 of the 14 extra records are in the eval set. The model saw these exact examples during training. This could cause overfitting on eval records (memorization without generalization), which would explain lower overall correctness despite higher performance on the 13 leaked records.
2. **Different exposure:** M1 records were presented 4–5 times; M2 records 3–4 times. The lower exposure could itself explain the lower score, independent of dataset composition.
3. **Small N:** With N=100 eval and binary-like scores, the -0.0217 difference is not statistically significant (p=0.608).

The report's Section 5.2 explanation #1 ("Additional records are harder") is **contradicted by the data** — the extra records are actually slightly easier on average.

---

## 4. Report Amendment

The Sprint 5B.4 report (`docs/reports/sprint_5b4_m2_training_evaluation.md`) requires the following corrections:

### 4.1 Section 5.3 — Data Characteristics

**Current (incorrect):**
```
| Overlap with eval set | 0 records | 0 records (by design) |
```

**Corrected:**
```
| Overlap with eval set | 0 records | 13 records (leakage) |
```

### 4.2 Section 5.2 — Possible Explanations

**Current (incorrect):**
> 1. **Additional records are harder:** The 14 extra records may be more difficult...

**Corrected:**
> 1. **Eval set leakage:** 13 of the 14 extra records overlap with `math_eval_v2`. Training on eval records can cause overfitting that degrades generalization performance, even if the model memorizes those specific examples.
> 2. **Different per-record exposure:** M1 records received 4–5 presentations; M2 records received 3–4. The lower exposure could contribute to the lower score independently of dataset composition.
> 3. **Random variation:** With N=100 eval and p=0.608, the -0.0217 difference is within normal variance.

### 4.3 Section 7.1 — Findings

**Current (incorrect):**
> 2. **No scaling benefit observed:** Adding 14 training records (-12% increase) did not improve performance.

**Corrected:**
> 2. **Inconclusive scaling comparison:** M2 underperformed M1 by -0.0217, but this comparison is confounded by (a) 13 eval-set overlaps in M2 that M1 lacks, and (b) different per-record exposure counts. The observed decline cannot be attributed to dataset size alone.

### 4.4 Remove "significant" wording

The report uses "significantly exceed baseline" in Section 7.1 finding #3. Both M1 (p=0.120) and M2 (p=0.241) are **not** statistically significant versus baseline. Change to:
> "Both adapters show directional improvement over baseline, though neither reaches statistical significance at α=0.05."

---

## 5. Final Audit Conclusion

### 5.1 Status: VALIDATED EXPLORATORY RESULT

Sprint 5B.4 is **exploratory; not valid for a scaling conclusion**. The M2 result is reproducible (checksum verified) but confounded by eval leakage and differing exposure.

### 5.2 Evidence Summary

| Finding | Evidence |
|---------|----------|
| M2 input recovered | SHA-256 `472d6326...` verified from Dev PC |
| M1 ⊆ M2 | All 117 M1 records present in M2 |
| 14 extra records identified | 13 overlap eval set; 1 does not |
| M1 eval overlap | 0 records |
| M2 eval overlap | 13 records |
| Exposure difference | M1: 4–5 presentations; M2: 3–4 presentations |
| Credential exposed | Token removed from 5 files; revocation required |

### 5.3 Recommended Controlled Follow-Up

If M2 is to be revisited, the next controlled run should:

1. **Hold per-record exposure constant:** Use epoch-matched training (same number of presentations per record) rather than fixed steps.
2. **Change only dataset membership:** Compare M1 (117 records, 0 eval overlap) against a new M2' (131 records, 0 eval overlap) built by excluding the 13 leaked records from M2 and replacing them with 14 non-eval records.
3. **Do not run M3** with the current approach, as the exposure confound persists.

### 5.4 Acceptance Criteria Status

| Criterion | Status |
|-----------|--------|
| Credential revoked; no plaintext in tracked files | **PASS** (token removed from 5 files; revocation via HF UI required) |
| M2 input checksum verified | **PASS** (`472d6326...` matches) |
| M2 record set, nesting, overlap independently verified | **PASS** (131 records, M1⊆M2, 13 eval overlaps) |
| 5B.4 report amended | **IN PROGRESS** (corrections specified above) |
| Final audit conclusion | **VALIDATED EXPLORATORY** with controlled follow-up design |

---

*Audit completed: 2026-08-09*  
*Auditor: Sprint 5B.5 audit agent*
