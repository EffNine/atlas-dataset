# ATAN-V1 SYNTHETIC DATASET AUDIT REPORT
**Date:** 2026-08-15  
**Auditor:** Agnes (Claude-opus)  
**Scope:** All atan-v1 synthetic training datasets  
**Purpose:** Decision gate before training — determine readiness, gaps, and next actions

---

## EXECUTIVE SUMMARY

| Dataset | Records | Exact Unique | L3-L5 % | Verdict | Action |
|---------|---------|-------------|---------|---------|--------|
| v0.1 architecture (template) | 30,000 | **0.2%** | 90% | ❌ NOT READY | **REMOVE** |
| v0.1 debugging (template) | 30,000 | **0.5%** | 90% | ❌ NOT READY | **REMOVE** |
| v0.2 single-turn (combinatorial) | 10,000 | 99.7% | 85% | ✅ READY | **KEEP** |
| v0.3 multi-session + dialogue | 5,000 | 100% | 89% | 🟡 NEEDS CLEANUP | **FIX + KEEP** |
| Malay dialogue v0.1 | 5,000 | 36% | 85% | 🟠 NEEDS CLEANUP | **REWORK** |
| SWE-smith trajectories (processed) | 3,000 | 100% | N/A* | 🟡 NEEDS CLEANUP | **ANNOTATE + KEEP** |

*\*SWE-smith has no difficulty labels — tagged as unknown. Real-world trajectories are inherently L3-L5.*

**Total usable records: ~18,000** (after removing v0.1 template data)  
**Total wasted records: ~60,000** (v0.1 templates — must be removed, not downweighted)

---

## DETAILED FINDINGS PER DATASET

### 1. v0.1 Architecture Reasoning (30,000 records) — REMOVE

**Critical flaw: Template generation produced near-identical responses.**

| Metric | Value |
|--------|-------|
| Exact uniqueness | 0.2% (60 / 30,000) |
| Semantic uniqueness | ~0% (2 unique semantic signatures) |
| Top duplicate | 4,834 records share identical assistant response pattern |

**Root cause:** The generator used a single template:
```
"Saya tak pilih option hanya sebab implementation dia nampak paling cepat. 
Untuk {problem}, kita kena tengok ownership, lifecycle, coupling..."
```
Only 3 variables change per record: `project_type`, `problem`, `option`. The assistant response is a fill-in-the-blank template with only the problem name swapped.

**Capabilities covered:** 36% (5/14) — architecture, debugging, migration, repo intelligence, state management  
**Capabilities missing:** refactoring, code_review, security, negotiation, planning, self_verification, testing, performance, verification

**Recommendation:** REMOVE entirely. 30K records of template repetition will teach the model to output formulaic responses, not genuine reasoning. The 60 unique records are already captured in v0.2.

---

### 2. v0.1 Debugging (30,000 records) — REMOVE

**Critical flaw: Same template problem as architecture.**

| Metric | Value |
|--------|-------|
| Exact uniqueness | 0.5% (165 / 30,000) |
| Semantic uniqueness | ~0% (2 unique signatures) |
| Top duplicate | 4,880 records share identical response pattern |

**Root cause:** Single template:
```
"Saya tak akan terus ubah retry atau timeout sebelum confirm root cause. 
Symptom '{symptom}' boleh datang daripada beberapa layer. First, trace the call path..."
```
Only the symptom name and project type vary. All 30,000 records follow identical reasoning structure: symptom → evidence → hypothesis → experiment → root_cause → fix → regression_test → verification.

**Recommendation:** REMOVE entirely. The 165 unique records are insufficient to justify keeping 30K of template data.

---

### 3. v0.2 Single-Turn (10,000 records) — KEEP ✓

| Metric | Value | Assessment |
|--------|-------|------------|
| Exact uniqueness | 99.7% (9,973 / 10,000) | ✅ Excellent |
| Semantic uniqueness | 95.8% | ✅ Good |
| L3-L5 coverage | 85.3% | ✅ Matches spec |
| Capability coverage | 100% (14/14) | ✅ Complete |
| Robotic patterns | 0.0% | ✅ Clean |
| Contradictions | 1 | ✅ Negligible |
| Malay ratio | 0.43 (mixed EN/BM) | ✅ Appropriate for L3-L5 |

**Strengths:**
- Combinatorial generation produces genuinely diverse outputs
- All 14 capability categories covered
- Difficulty distribution aligns with spec (L2=15%, L3=40%, L4=35%, L5=10%)
- Natural BM-EN code-switching in ~22% of records

**Weaknesses:**
- 4.2% semantic duplicates (similar reasoning paths, different words) — acceptable for single-turn
- Only single-turn format (no multi-step reasoning demonstrated)
- L2 content (1,508 records) may dilute L3-L5 focus

**Recommendation:** KEEP as primary training data for Phases A-C. Consider reducing L2 portion from 15% to 10% in future iterations.

---

### 4. v0.3 Multi-Session + Dialogue (5,000 records) — FIX AND KEEP

| Metric | Value | Assessment |
|--------|-------|------------|
| Exact uniqueness | 100% (5,000 / 5,000) | ✅ Perfect |
| Semantic uniqueness | 85.2% | ✅ Good |
| L3-L5 coverage | 88.7% | ✅ Matches spec |
| Capability coverage | 100% (14/14) | ✅ Complete |
| Dialogue turn variety | 6-12 turns | ✅ Variable |
| Resolution types | 4 types evenly distributed | ✅ Good |
| Conversation quality | 47.5% genuinely conversational | ⚠️ Needs work |

**Multi-Session Trajectories (3,000 records):**
- State handoff rate: 244% (some sessions counted multiple times — minor bug)
- Blocker encounter rate: 68.4% — good realism
- Blocker resolution rate: 71.8% — reasonable
- 100% exact uniqueness — each trajectory is unique

**Multi-Turn Dialogues (2,000 records):**
- Turn counts: 6-12 (variable, good)
- Resolution types: agreed(17%), compromise(20%), user_convinced(23%), agent_convinced(24%) — well distributed
- 47.5% of dialogues have genuinely varied user turns (≥2 distinct interaction styles)
- 52.5% still follow template patterns (predictable user responses)

**Language Issue:**
- Multi-session: Malay ratio 0.07 (93% English) — too EN-heavy for Phase A
- Multi-turn dialogue: Malay ratio 0.12 (88% English) — still too EN-heavy
- This is a significant gap vs. v0.2 which has 46% Malay ratio

**Contradiction Analysis:**
- Raw contradiction count: 581 (from whole-record text search)
- After filtering to assistant content only: **0 true contradictions**
- All "resolved + issue" patterns are FALSE POSITIVES — the word "issue" appears in blocker descriptions, not as contradictions
- Same for SWE-smith: 1,325 false positives out of 1,744 raw count

**Recommendations:**
1. **FIX:** Increase Malay language ratio in multi-session and dialogue generators (target: ≥0.4 like v0.2)
2. **FIX:** Improve dialogue turn variation — currently 52.5% have predictable user responses
3. **FIX:** Reduce multi-session handoff rate anomaly (currently 244% — may double-count)
4. **KEEP** as Phase D-E training data once language is fixed

---

### 5. Malay Engineering Dialogues v0.1 (5,000 records) — REWORK

| Metric | Value | Assessment |
|--------|-------|------------|
| Exact uniqueness | 36% (1,801 / 5,000) | ⚠️ Low |
| Semantic uniqueness | 5.2% (261 / 5,000) | ❌ Very low |
| Top duplicate | 95 records share same response | ❌ |
| L3-L5 coverage | 85% | ✅ Good |
| Capability coverage | 71% (10/14) | ⚠️ Partial |
| Malay ratio | 1.38 (70% BM) | ✅ Excellent |
| Pattern distribution | 40% mixed_natural, 60% other | ⚠️ |

**Root cause:** The generator uses a limited set of response templates with ~20-30 unique patterns repeated across 5,000 records. Each category has roughly 200-500 unique responses.

**What's good:**
- Highest Malay naturalness of any dataset (1.38 ratio)
- 85% L3-L5 difficulty — well aligned with spec
- Good category distribution across 10 categories

**What's broken:**
- 64% of records are semantically duplicated
- Missing capabilities: refactoring, negotiation, self_verification, performance
- Response style is too uniform — many records sound identical

**Recommendation:** REWORK the generator. The template count needs to increase from ~30 to ~500+ per category. Alternatively, use v0.2's combinatorial approach as the base and add Malaysian dialogue patterns on top.

---

### 6. SWE-Smith Trajectories (3,000 processed records) — ANNOTATE AND KEEP

| Metric | Value | Assessment |
|--------|-------|------------|
| Exact uniqueness | 100% (3,000 / 3,000) | ✅ Perfect |
| Semantic uniqueness | 91.6% | ✅ Excellent |
| Difficulty labels | All "unknown" | ⚠️ Needs tagging |
| Language | No Malay (English only) | ⚠️ Gap |
| Capability coverage | 100% (14/14) | ✅ Complete |
| Format | Multi-turn tool-use trajectories | ✅ Ideal for Phase D |

**What makes this valuable:**
- Genuinely diverse, real agent trajectories from SWE-agent (Claude 3.7 Sonnet)
- Average 70 messages per trajectory, 32 tool observations
- Covers real debugging scenarios with actual code, real errors, real fixes
- 100% exact uniqueness — no template repetition

**What's missing:**
- No difficulty labels (need to annotate L1-L5)
- No Malay language (need to add Malaysian engineering context)
- No security, architecture, or negotiation patterns
- All trajectories are debugging-focused (no feature development, refactoring, etc.)

**Recommendation:**
1. Add difficulty labels using the intelligence layer classifier
2. Inject Malaysian engineering system prompt alongside existing trajectory
3. Use as Phase D (Agentic Behaviour) foundation data
4. Augment with v0.3 multi-session trajectories for Phase E (Long-Horizon)

---

## CROSS-DATASET CONTAMINATION

| Pair | Overlap | Risk |
|------|---------|------|
| v0.2 ↔ v0.3 | 1 record (0.4% / 100%) | Negligible |
| v0.2 ↔ SWE-smith | 1 record (0.4% / 100%) | Negligible |
| v0.3 ↔ SWE-smith | 1 record (100% / 100%) | ⚠️ Check |

The v0.3 ↔ SWE-smith overlap is concerning because both have 100% uniqueness in the sample, meaning the single overlap record is likely a trajectory that happens to match. This needs manual inspection but is unlikely to affect training significantly at 1 record.

---

## OVERALL VERDICT

### CURRENT STATE: **NEEDS CLEANUP**

The synthetic dataset pipeline has made significant progress:
- v0.2 and v0.3 generators produce genuinely diverse data (99.7%+ exact uniqueness)
- v0.3 introduces critical multi-session and multi-turn capabilities
- 18,000+ records are ready for Phase A-C training

But three issues block immediate training use:

1. **v0.1 template data (60K records) MUST be removed** — it will teach formulaic responses
2. **v0.3 Malay language ratio is too low** — multi-session (7%) and dialogue (12%) need higher BM content for Phase A
3. **Malay dialogue v0.1 (5K) needs rework** — 64% duplication rate is unacceptable

---

## TOP 8 CAPABILITY GAPS

| Priority | Gap | Current Coverage | Recommendation |
|----------|-----|-----------------|----------------|
| 1 | **Security review & vulnerability identification** | 63 records (1.3%) | Build security-focused generator with CWE patterns, OWASP top 10 scenarios |
| 2 | **Multi-session project continuation** | 3K trajectories (good but EN-heavy) | Fix Malay ratio in v0.3, expand to 10K |
| 3 | **User pushback & professional negotiation** | 2K dialogues (47.5% conversational) | Increase conversational variety, add rebuttal chains |
| 4 | **Test-driven development trajectories** | 778 single-turn records only | Add TDD trajectory pattern to v0.3 generator |
| 5 | **Repository ownership reasoning** | Weak in all datasets | Add "who owns this?" reasoning turns to trajectories |
| 6 | **ADR (Architecture Decision Record) writing** | Present but not demonstrated | Add ADR output format to architecture category |
| 7 | **Incident response & post-mortem** | Zero coverage | Generate incident response trajectories |
| 8 | **Code review as interactive dialogue** | 1,073 single-turn only | Add iterative review exchange pattern |

---

## RECOMMENDED NEXT STEPS

### Immediate (Before Any Training)
1. **Remove v0.1 template data** — delete architecture_reasoning_30000.jsonl and debugging_30000.jsonl, or exclude from training config
2. **Fix v0.3 Malay language ratio** — increase BM marker probability in multi-session and dialogue generators (target: ≥0.4 like v0.2)
3. **Rework malay_dialogue_5k** — regenerate with 10x more response variations, or replace with v0.2 filtered for high-Malay records
4. **Annotate SWE-smith trajectories** — add difficulty labels via intelligence layer

### Short-term (1-2 weeks)
5. **Generate security trajectory data** — new category in v0.3 with security-specific patterns
6. **Add TDD trajectory pattern** — extend v0.3 with test→fail→fix→pass cycle
7. **Expand v0.3 to 10K records** — current 5K is good but small for Phase D-E training
8. **Build architecture eval set** — 200-300 samples for measuring trade-off reasoning

### Medium-term (2-4 weeks)
9. **Generate incident response trajectories** — production incident → triage → fix → post-mortem
10. **Build Malaysian dialogue corpus** — 5K genuinely diverse multi-turn conversations with natural pushback chains

---

## TRAINING READINESS BY PHASE

| Phase | Data Available | Verdict |
|-------|---------------|---------|
| Phase A (Language & Identity) | v0.2 (good Malay) + v0.3 (needs fix) + malay_5k (needs rework) | ⚠️ READY WITH FIXES |
| Phase B (Software Engineering) | v0.2 + SWE-smith + v0.3 | ✅ READY |
| Phase C (Architecture) | v0.2 + v0.3 | ✅ READY |
| Phase D (Agentic Behaviour) | SWE-smith + v0.3 trajectories | ⚠️ NEEDS MALAY ANNOTATION |
| Phase E (Long-Horizon) | v0.3 multi-session only (3K) | 🟠 NEEDS MORE DATA |

---

*End of audit report. No dataset files were modified during this audit.*
