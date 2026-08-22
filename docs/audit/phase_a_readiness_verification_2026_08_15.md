# Phase A Readiness Verification Report
**Date:** 2026-08-15  
**Verifier:** Agnes (Claude-opus)  
**Scope:** Final gate before any model training

---

## 1. Training Entry Point Trace

| Script | Path Used | Status |
|--------|-----------|--------|
| `run_atan_v1_train.sh` | `datasets/sft/phase_a_train.jsonl` | ✅ VERIFIED |
| `train_atan_v1.py` | `datasets/sft/phase_a_train.jsonl` | ✅ VERIFIED |
| `train_atan_v1_unsloth.py` | `datasets/sft/phase_a_train.jsonl` | ✅ VERIFIED |
| `lora_qwen25_05b_atan_v1_4bit.yaml` | `./datasets/sft/phase_a_train.jsonl` | ✅ VERIFIED |
| `lora_qwen3_8b_agentic_4bit.yaml` | `./datasets/sft/phase_a_train.jsonl` | ✅ VERIFIED |
| `lora_qwen3_8b_atlas_code_4bit.yaml` | `./datasets/sft/phase_a_train.jsonl` | ✅ VERIFIED |

**Critical fix applied during verification:** All 6 training entry points were previously pointing to the legacy `atan_v1_train.jsonl` (4,050 old pilot records). Updated to `phase_a_train.jsonl` (13,500 Phase A records).

---

## 2. Manifest Consumption

| Check | Result |
|-------|--------|
| `phase_a_manifest.json` exists | ✅ VERIFIED |
| `build_phase_a_dataset.py` reads manifest | ✅ VERIFIED |
| Included datasets match manifest `included: true` | ✅ VERIFIED |
| Excluded datasets absent from merged output | ✅ VERIFIED |
| No directory auto-discovery in build script | ✅ VERIFIED |

---

## 3. No Fallback Auto-Discovery

| Script | Glob/Directory Discovery? | Verdict |
|--------|--------------------------|---------|
| `train_atan_v1.py` | Hardcoded `--dataset` arg | ✅ No fallback |
| `train_lora.py` | Reads YAML `data.train_file` | ✅ No fallback |
| `run_atan_v1_train.sh` | Hardcoded paths | ✅ No fallback |
| `build_phase_a_dataset.py` | Manifest-driven only | ✅ No fallback |
| `phase_a_dataset_manifest.py` | Manifest validation only | ✅ No fallback |

**No `glob()`, `rglob()`, `os.listdir()`, or wildcard path resolution found in any training path.**

---

## 4. Excluded Dataset Contamination Check

| Excluded Dataset | Records | In Phase A? | Verdict |
|-----------------|---------|-------------|---------|
| v0.1_architecture_template | 30,000 | 0 | ✅ EXCLUDED |
| v0.1_debugging_template | 30,000 | 0 | ✅ EXCLUDED |
| malay_dialogue_v0.1 | 5,000 | 0 | ✅ EXCLUDED |
| pilot_v0.2 | 4,499 | 0 | ✅ EXCLUDED |
| swe_smith_trajectories | 2,700 | 0 | ✅ EXCLUDED (Phase D only) |

**Source tag verification:** Only `_source` values `v0.2_single_turn` and `v0.3_multi_session_fixed` present in Phase A data.

---

## 5. SWE-Smith Exclusion from Phase A

| Check | Result |
|-------|--------|
| SWE-smith in manifest `included` | ❌ `false` |
| SWE-smith in Phase A train file | 0 records |
| SWE-smith tag includes `EXCLUDED_FROM_PHASE_A` | ✅ Yes |
| Reason documented | "EN-only (0.29 Malay ratio), no difficulty labels. Reserved for Phase D." |

**VERIFIED: SWE-smith cannot enter Phase A through any path.**

---

## 6. Record Count Verification

| Source | Expected | Actual | Match? |
|--------|----------|--------|--------|
| v0.2_single_turn | 9,000 | 9,000 | ✅ |
| v0.3_multi_session_fixed | 4,500 | 4,500 | ✅ |
| **Total train** | **13,500** | **13,500** | ✅ **EXACT** |
| **Total val** | **1,500** | **1,500** | ✅ **EXACT** |

---

## 7. Final Validation (13,500 Records)

| Metric | Value | Threshold | Verdict |
|--------|-------|-----------|---------|
| Exact uniqueness | 100.0% (13,500/13,500) | ≥95% | ✅ PASS |
| Template concentration | 0.03% (top: 4 records) | <10% | ✅ PASS |
| Malay ratio (overall) | 0.41 | ≥0.30 | ✅ PASS |
| Malay ratio (user turns) | 1.4 words/turn | — | ✅ PASS |
| Malay ratio (agent turns) | 0.7 words/turn | — | ✅ PASS |
| L3-L5 coverage | 86.1% | ≥70% | ✅ PASS |
| Dialogues conversational | 68.5% | ≥50% | ✅ PASS |
| Rebuttal chains | 1,233/1,800 | — | ✅ PASS |
| Resolution diversity | 4 types balanced | — | ✅ PASS |
| Security capability | 1,952 records | ≥100 | ✅ PASS |
| All 12 capabilities | ≥1,882 each | ≥100 | ✅ PASS |
| Excluded dataset leakage | 0 | 0 | ✅ PASS |
| JSON parse errors | 0 | 0 | ✅ PASS |

---

## 8. Failing Tests Analysis

**Tests:** `tests/test_tui.py::TestCurrentRepoState::test_current_state_shows_cancelled_pipeline` and `test_current_state_does_not_falsely_mark_complete`

**Failure:** Both assert `WorkflowStage.ETL == "cancelled"` but get `"done"`.

**Root cause:** Pipeline state machine has ETL marked as "done" (historical artifacts exist), but tests expect "cancelled" based on pipeline cancellation at INGESTED stage.

**Relation to dataset changes:** None. These tests exercise `tui_backend.WorkflowDetector` which reads pipeline state from `metadata/pipeline_state/`. No dataset files are involved.

**Verdict:** ⚪ PRE-EXISTING, UNRELATED to Phase A dataset work.

---

## 9. Files Changed

| File | Change Type | Description |
|------|------------|-------------|
| `scripts/phase_a_dataset_manifest.py` | NEW | Manifest reader/validator CLI |
| `scripts/build_phase_a_dataset.py` | NEW | Merges manifest-included datasets into Phase A training file |
| `datasets/sft/phase_a_manifest.json` | NEW | Canonical inclusion/exclusion list |
| `datasets/sft/phase_a_train.jsonl` | NEW | 13,500 merged Phase A records |
| `datasets/sft/phase_a_val.jsonl` | NEW | 1,500 merged validation records |
| `datasets/sft/phase_a_metadata.json` | NEW | Merge report with distributions |
| `scripts/multi_session_generator_v0.3.py` | MODIFIED | Malay injection + dialogue rebuttal chains |
| `configs/lora_qwen25_05b_atan_v1_4bit.yaml` | MODIFIED | Updated train/eval paths |
| `configs/lora_qwen3_8b_agentic_4bit.yaml` | MODIFIED | Updated train/eval paths |
| `configs/lora_qwen3_8b_atlas_code_4bit.yaml` | MODIFIED | Updated train/eval paths |
| `scripts/run_atan_v1_train.sh` | MODIFIED | Updated train/eval paths |
| `scripts/train_atan_v1.py` | MODIFIED | Updated default --dataset paths |
| `scripts/train_atan_v1_unsloth.py` | MODIFIED | Updated default --dataset paths |

**Not modified:** v0.1 templates (excluded), SWE-smith (excluded from Phase A), pilot data (excluded), existing source datasets.

---

## 10. Remaining Risks

| Risk | Severity | Status |
|------|----------|--------|
| Security capability (1,952 records) is weakest | LOW | ≥100 threshold met |
| 15.3% of v0.3 dialogues still templated | LOW | Acceptable — majority genuine |
| SWE-smith not in Phase A (EN-only) | INFO | Intentional — reserved for Phase D |
| No incident response / ADR-writing data | MEDIUM | Documented in audit report |
| Malay ratio 0.41 vs v0.2 target 0.46 | LOW | Within acceptable range |

---

## FINAL VERDICT

### **READY FOR PHASE A SMOKE TRAINING**

All critical gates pass:
- ✅ 13,500 unique records from 2 vetted sources
- ✅ 0 excluded dataset contamination
- ✅ 86.1% L3-L5 difficulty
- ✅ 0.41 Malay ratio (target ≥0.30)
- ✅ 68.5% conversational dialogues
- ✅ All 12 capabilities covered (≥1,882 records each)
- ✅ All training entry points updated to Phase A paths
- ✅ No auto-discovery fallback possible
- ✅ 2 failing tests are pre-existing TUI issues, unrelated

**No model training has been started.** This is a verification gate — await approval before proceeding.

---

*Verification completed: 2026-08-15*  
*Manifest: datasets/sft/phase_a_manifest.json*  
*Training data: datasets/sft/phase_a_train.jsonl (13,500 records)*  
*Audit reference: docs/audit/atan_v1_synthetic_dataset_audit_2026_08_15.md*
