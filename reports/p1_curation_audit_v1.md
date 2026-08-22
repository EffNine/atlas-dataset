# Atlas Frontier Corpus Curation Audit v1

**Date:** 2026-08-14
**Status:** COMPLETE

## 1. Corpus Inventory

| Source | Records | Est. Tokens | Domain |
|--------|---------|-------------|--------|
| SWE-smith-mini | 65,985 | ~885M | Code |
| Nemotron-Math-Proofs-v2 | 43,779 | ~40M | Math |
| Linux kernel (y9) | 8,803 | ~8M | Systems |
| **TOTAL** | **118,567** | **~933M** | |

## 2. Key Findings

### Code Corpus (SWE-smith-mini)
- 109 unique repositories, but HIGH concentration risk (top 5 = 26%)
- 84.6% bug-fix tasks, limited implementation/architecture diversity
- C (51%) and Python (32%) dominate; other languages minimal
- Tool use minimal in current staging (0 tool messages)
- Value: HIGH for code agent training despite concentration

### Math Corpus (Nemotron-Math-Proofs-v2)
- 5,752 unique competition-level problems, 14.4x redundant variants
- 84% A+ Frontier — highest quality density of all sources
- Geometry (33%) and Number Theory (19%) dominate
- Formal proof verification provides strong signal
- Value: VERY HIGH for reasoning training

### Systems Corpus (Linux Kernel y9)
- 8,803 unique kernel commits across 15 subsystems
- 95% bug fixes, kernel-only (no user-space)
- C language exclusively
- Value: MODERATE — good for kernel internals, narrow for systems broadly

## 3. Cross-Domain Balance

| Domain | Records | % Records | % Tokens |
|--------|---------|-----------|----------|
| Code | 65,985 | 55.7% | 95.5% |
| Math | 43,779 | 36.9% | 4.2% |
| Systems | 8,803 | 7.4% | 0.9% |

**CRITICAL IMBALANCE:** Code dominates at 95.5% of tokens despite being 55.7% of records.

## 4. Frontier Distribution

| Domain | A+ Frontier | A Strong Specialist | B Professional |
|--------|-------------|---------------------|----------------|
| Code | 0 (0.0%) | 26,454 (40.1%) | 39,531 (59.9%) |
| Math | 36,820 (84.1%) | 6,959 (15.9%) | 0 (0.0%) |
| Systems | 2,916 (33.1%) | 5,857 (66.5%) | 30 (0.3%) |

## 5. Data Gaps

### Code
- Architecture/design decisions
- Long-horizon coding tasks
- Agentic planning with tool use
- Non-Python/C languages (Rust, Go, JS)

### Math
- Competition beyond AoPS (IMO, Putnam)
- Undergraduate math (calculus, linear algebra)
- Applied math (optimization, statistics)

### Systems
- User-space systems programming
- CPU/GPU architecture
- Virtualization (KVM, QEMU)
- Storage systems
- Performance engineering

### Hardware
- Severely underrepresented (401 records)
- Missing: CPU arch, GPU, embedded, firmware

## 6. Mixture Options

### Option A — Balanced Specialists
- Equal domain representation (33% each)
- Requires Systems expansion (y5 StackExchange)
- Risk: Systems too small currently

### Option B — Frontier Weighted (RECOMMENDED)
- Higher proportion of A+/A records
- Code: top 20K by quality+depth
- Math: all 43,779 (84% A+)
- Systems: all 8,803 (100% A+/A)
- Weights: Code 30%, Math 50%, Systems 20%

### Option C — Volume Weighted
- Maximize total tokens with quality filtering
- Code 55%, Math 35%, Systems 10%
- Risk: Code dominance, domain collapse

## 7. StackExchange (y5) Recommendation

- **Priority:** P2 (next phase)
- **Rationale:** Fills critical Systems gap (user-space, networking, perf)
- **Source:** archive.org XML dumps (unix.SE, ServerFault, NetworkEngineering)
- **Target:** 8,000 records with score>=5 filter

## 8. Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Code concentration | HIGH | Monitor repo diversity during training |
| Math redundancy | MEDIUM | Keep one proof/problem for training |
| Systems narrowness | HIGH | Acquire y5 StackExchange in P2 |
| Domain imbalance | HIGH | Use Option B weighting |

---

```
CURATION AUDIT:
COMPLETE

DATASET STATUS:
READY FOR MIXTURE DESIGN
```