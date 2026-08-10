# M2' Provenance Report

**Sprint:** 5B.6  
**Date:** 2026-08-09  
**Status:** DESIGNED — no training executed

---

## 1. Source Provenance

### 1.1 Parent View: math_m2_v0.1

| Field | Value |
|-------|-------|
| Source | `expert-math-002` (OpenMathInstruct-2) |
| License | CC-BY-4.0 |
| Category | mathematics |
| Total records | 131 |
| File SHA-256 | `472d632614d97a3d5fc2d36b005ae1d434a6a0ebdefd271ed1b77b1e8b49abe7` |
| Recovery source | Dev PC: `/home/afnan/workspace/atlas-dataset/output/training_views/math_m2_v0.1/train.jsonl` |
| Checksum verified | ✅ PASS |

### 1.2 Exclusion Rationale

13 records were excluded from M2' because they overlap with `math_eval_v2`:

| # | Record ID | Difficulty |
|---|-----------|------------|
| 1 | expert_math_000125 | 2 |
| 2 | expert_math_000281 | 2 |
| 3 | expert_math_000831 | 2 |
| 4 | expert_math_000900 | 2 |
| 5 | expert_math_000961 | 2 |
| 6 | expert_math_001421 | 2 |
| 7 | expert_math_001505 | 2 |
| 8 | expert_math_001802 | 2 |
| 9 | expert_math_002168 | 3 |
| 10 | expert_math_002660 | 2 |
| 11 | expert_math_002701 | 3 |
| 12 | expert_math_002953 | 2 |
| 13 | expert_math_002995 | 3 |

The remaining 1 extra record from M2 (`expert_math_000761`, difficulty 2) was retained in M2'.

---

## 2. M1 Provenance

| Field | Value |
|-------|-------|
| Source | `expert-math-002` (OpenMathInstruct-2) |
| License | CC-BY-4.0 |
| Category | mathematics |
| Total records | 117 |
| File SHA-256 | `6aecc2a754c1a4aec941a9dbb59136445cf04175a0ae02c158e86acd4e4a4572` |
| Eval overlap | 0 records |
| Duplicates | None |
| Training view ID | `math_300m_v0.1` |

---

## 3. M2' Provenance

| Field | Value |
|-------|-------|
| Source | `expert-math-002` (OpenMathInstruct-2) |
| License | CC-BY-4.0 |
| Category | mathematics |
| Total records | 118 |
| File SHA-256 | `7dfa81114f4096286415a672830f6ff334cc95066080fd9f5267e86d0e413dda` |
| Records SHA-256 | `734e71f45f7c33e672dc977e5d0e71d57cec40dfbf36f0667c03513cd8de435e` |
| Eval overlap | **0 records** |
| Duplicates | None |
| Staged path | `experiments/lora_pilot_math_m2prime_v0.1/staged_train.jsonl` |

---

## 4. Subset Relationship

```
M1 (117 records) ⊂ M2' (118 records)
M2' \ M1 = {expert_math_000761} (1 record)
```

M2' adds exactly 1 record to M1, compared to M2 which added 14 records (13 of which were eval-leaked).

---

## 5. Construction Method

1. Start with M2 training view (`math_m2_v0.1`, 131 records)
2. Load `math_eval_v2` eval set (100 records)
3. Compute set intersection: M2 ∩ eval = 13 records
4. Exclude overlapping records from M2
5. Result: M2' with 118 records, 0 eval overlap
6. Sort by `record_id` for deterministic ordering
7. Compute SHA-256 checksums

---

## 6. Provenance Chain

```
OpenMathInstruct-2 (CC-BY-4.0)
  └─ expert-math-002 (Atlas source registry)
      └─ math_m2_v0.1 (131 records, SHA-256: 472d6326...)
          └─ math_m2prime_v0.1 (118 records, SHA-256: 7dfa8111...)
              ├─ M1 (117 records) ⊂ M2'
              └─ M2' \ M1 = {expert_math_000761}
```

---

*Report generated: 2026-08-09*
