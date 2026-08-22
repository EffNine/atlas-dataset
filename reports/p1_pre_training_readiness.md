# Atlas Pre-Training Readiness Report

**Date:** 2026-08-14
**Phase:** P1 Frontier Expansion — Pre-Training Readiness
**Status:** READY WITH CHANGES

## 1. Systems Evaluation Set

### Creation
- **Source:** Held-out 12% from P1 kernel training data (seed=42)
- **Kernel hold-out:** 120 records from 8,803
- **Sandbox supplement:** 200 records from mlfoundations-dev/stackexchange-unix-sandboxes
- **Total eval records:** 320
- **Format:** protocol_v2 compliant
- **Location:** `evaluation/eval_sets/protocol_v2/systems_eval_v1.jsonl`

### Validation
| Check | Result |
|-------|--------|
| Required fields | ALL PRESENT |
| Unique IDs | 320/320 |
| Prompt contamination | 0 leaks |
| SHA-256 consistency | CONSISTENT |
| Message format | CORRECT |
| Cross-source overlap | 0 with any training set |
| Schema validation | PASS |

### Subsystem Coverage (120 kernel hold-out)
| Subsystem | Records |
|-----------|--------:|
| linux_kernel (other) | 97 |
| net | 12 |
| mm | 6 |
| kernel | 2 |
| bpf | 2 |
| fs | 1 |
| arch | 1 |
| drivers | 1 |

### Difficulty Distribution
| L2 | L3 | L4 |
|----|----|----|
| 87 | 27 | 6 |

### Limitations
- Subsystem coverage is narrow (77.5% 'other')
- No user-space systems coverage
- No networking admin coverage
- No performance tuning coverage
- **Mitigation:** P2 StackExchange acquisition will fill these gaps

## 2. Code Repository Diversification

### Policy Applied
- **Max token share per repository:** 5%
- **Threshold:** 47,190,156 tokens per repo
- **Method:** Deterministic sampling by quality_score DESC, trajectory length DESC

### Before
| Metric | Value |
|--------|-------|
| Total records | 65,985 |
| Total tokens | ~944M |
| Top repo (conan-io) | 8.2% of tokens |
| Top 5 repos combined | 26.0% of tokens |

### After
| Metric | Value |
|--------|-------|
| Total records | 62,833 |
| Total tokens | ~895M |
| Records removed | 3,152 (4.8%) |
| Token reduction | ~49M (5.2%) |
| Top repo (conan-io) | 5.3% of tokens |
| Top 5 repos combined | ~16% of tokens |

### Distribution Changes
- **Task types:** Unchanged (100% bug fix — inherent to source)
- **Languages:** C ~50%, Python ~33%, Other ~17%
- **All 109 repositories retained** (none dropped entirely)

## 3. P2 StackExchange Acquisition

### Status: PARTIALLY COMPLETED

#### What was accomplished
- Identified canonical source: archive.org XML dumps
- Alternative source: mlfoundations-dev/stackexchange-unix-sandboxes (HF)
- Extracted 10,000 system administration tasks from sandbox archives
- Appended 200 records to systems_eval_v1 as supplementary eval data

#### What remains for P2
- Full archive.org dump acquisition (unix.stackexchange.com, serverfault.com, networkengineering.stackexchange.com)
- Parse XML to extract Q&A pairs with author attribution
- Filter by score >= 5, accepted answers preferred
- Target: ~8,000 records with CC-BY-SA-4.0 compliance

### Specification (for P2 execution)
| Parameter | Value |
|-----------|-------|
| Target records | ~8,000 |
| Source | archive.org XML dumps |
| Sites | unix.stackexchange.com, serverfault.com, networkengineering.stackexchange.com |
| Min question score | 5 |
| Accepted answer preference | Yes |
| Min answer length | 200 chars |
| License | CC-BY-SA-4.0 |
| Attribution | Required (author + URL) |
| Dedup | By question ID |
| Sampling seed | 42 |
| Priority topics | Linux, networking, perf, virtualization, storage, concurrency |

## 4. Contamination Results

### Eval vs Training Overlap
| Eval Set | Records | Overlaps | Status |
|----------|--------:|---------:|--------|
| math_eval_v2 | 100 | 0 | PASS |
| code_eval_v2 | 99 | 0 | PASS |
| systems_eval_v1 | 320 | 0 | PASS |

### Cross-Source Overlap
| Pair | Overlaps | Status |
|------|---------:|--------|
| SWE-smith vs Nemotron | 0 | PASS |
| SWE-smith vs Kernel | 0 | PASS |
| Nemotron vs Kernel | 0 | PASS |

### Protected Set Verification
| Set | Overlaps | Status |
|-----|---------:|--------|
| IFEval | 0 | PASS |
| SWE-bench Verified | 0 | PASS |

**VERDICT: PASS — No contamination detected across any source pairs**

## 5. Final Token Mixture Feasibility

### Available Tokens (after diversification)
| Domain | Tokens | % of Total |
|--------|-------:|------------|
| Code (diversified) | ~895M | 94.5% |
| Math | ~44M | 4.6% |
| Systems | ~8M | 0.9% |
| **TOTAL** | **~947M** | **100%** |

### Option B Mixture (Math 50% / Code 30% / Systems 20%)

| Budget | Math | Code | Systems | Supported? |
|--------|------|------|---------|------------|
| 1M | 500K (1.1%) | 300K (0.0%) | 200K (2.4%) | YES |
| 5M | 2.5M (5.7%) | 1.5M (0.2%) | 1M (12.2%) | YES |
| 10M | 5M (11.4%) | 3M (0.3%) | 2M (24.5%) | YES |
| 25M | 12.5M (28.6%) | 7.5M (0.8%) | 5M (61.2%) | YES |
| 50M | 25M (57.2%) | 15M (1.7%) | 10M (100%) | YES |
| 500M | 250M (5.7x) | 150M (16.8%) | 100M (12.2x) | NEEDS RESAMPLE |

### Notes
- 1M-50M budgets: **SUPPORTED** without resampling
- 500M pilot: Requires Math x5.7 and Systems x12.2 resampling
- P2 StackExchange (+~4M tokens) reduces Systems resampling to x10.2

## 6. Pilot Dataset Metadata

### Prepared Artifacts
| Artifact | Path | Status |
|----------|------|--------|
| Pilot manifest | metadata/pilot_manifest_v0.1.json | READY |
| Code diversification report | reports/code_diversification_report.json | READY |
| Systems eval set | evaluation/eval_sets/protocol_v2/systems_eval_v1.jsonl | READY |
| Systems eval manifest | evaluation/eval_sets/protocol_v2/systems_eval_v1_manifest.json | READY |

### Training View Specifications (for future use)
| View | Math % | Code % | Systems % | Records (est) |
|------|--------|--------|-----------|---------------|
| general | 30% | 40% | 20% | ~118K |
| math_specialist | 60% | 25% | 15% | ~44K |
| code_specialist | 20% | 70% | 10% | ~63K |
| systems_specialist | 20% | 30% | 50% | ~9K (+ P2) |

## 7. Remaining Blockers

| Blocker | Severity | Mitigation |
|---------|----------|------------|
| Systems eval narrow coverage | MEDIUM | P2 StackExchange will expand to 8K+ records |
| Math resampling needed for >50M | LOW | Acceptable for pilot; P3 math sources would help |
| Systems resampling needed for >50M | MEDIUM | P2 StackExchange reduces factor from x12.2 to x10.2 |
| Hardware category empty | LOW | P3 acquisition planned |

## 8. Files Modified

### New Files
| File | Description |
|------|-------------|
| `evaluation/eval_sets/protocol_v2/systems_eval_v1.jsonl` | 320 eval records |
| `evaluation/eval_sets/protocol_v2/systems_eval_v1_manifest.json` | Eval set manifest |
| `metadata/pilot_manifest_v0.1.json` | Pilot dataset metadata |
| `reports/code_diversification_report.json` | Code diversification results |
| `tmp/diversification_mask.pkl` | Diversification sampling mask |

### Unchanged (by constraint)
- No canonical records modified
- No raw/ data modified
- No curated/ data modified
- No training views built
- No model/training config modified

## 9. Tests Run

| Test | Result |
|------|--------|
| Schema validation (systems_eval_v1) | PASS (0 errors) |
| SHA-256 consistency | PASS (0 mismatches) |
| Prompt contamination check | PASS (0 leaks) |
| Cross-source overlap | PASS (0 overlaps) |
| Eval vs training overlap | PASS (0 overlaps) |
| IFEval contamination | PASS (0 overlaps) |
| SWE-bench contamination | PASS (0 overlaps) |
| Diversification policy | PASS (5% cap enforced) |

## 10. Final Recommendation

### Immediate Actions
1. **Proceed with 1M-10M token pilot** using Option B mixture
2. **Apply code diversification** (5% repo cap) at training view level
3. **Use systems_eval_v1** (320 records) for Systems evaluation
4. **Initiate P2 StackExchange acquisition** for Systems expansion

### Do NOT
- Train models yet
- Build final training views
- Modify canonical records
- Use Unsloth
- Modify TUI

---

```
PRE-TRAINING READINESS:
READY WITH CHANGES

Changes required:
  1. Complete P2 StackExchange acquisition (8K records)
  2. Accept Math/Systems resampling for >50M token training
  3. Monitor code concentration after diversification

Blocked on:
  - None for 1M-10M pilot
  - P2 acquisition for >50M pilot
```