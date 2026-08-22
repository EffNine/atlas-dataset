# Atlas Frontier Mixture v1 — Design & P2 Acquisition Specification

**Date:** 2026-08-14
**Phase:** P1 Frontier Expansion — Mixture Design
**Status:** DESIGN COMPLETE

## 1. Current Corpus Statistics

| Source | Records | Est. Tokens | Domain | % Tokens |
|--------|--------:|------------:|--------|----------|
| SWE-smith-mini | 65,985 | ~944M | Code | 94.8% |
| Nemotron-Math-Proofs-v2 | 43,779 | ~44M | Math | 4.4% |
| Linux kernel (y9) | 8,803 | ~8M | Systems | 0.8% |
| **TOTAL** | **118,567** | **~996M** | | **100%** |

**Critical Finding:** Code dominates at 94.8% of tokens despite being 55.7% of records.

## 2. Token-Based Mixture Calculation

| Domain | Available Tokens | Option A (40/30/30) | Option B (50/30/20) | Option C (40/25/35) |
|--------|----------------:|---------------------:|---------------------:|---------------------:|
| Math | ~44M | Target 40% = 398M ⚠ RESAMPLE | Target 50% = 498M ⚠ RESAMPLE | Target 40% = 398M ⚠ RESAMPLE |
| Code | ~944M | Target 30% = 299M ✓ Sample 32% | Target 30% = 299M ✓ Sample 32% | Target 25% = 249M ✓ Sample 26% |
| Systems | ~8M | Target 30% = 299M ⚠ RESAMPLE x37x | Target 20% = 199M ⚠ RESAMPLE x24x | Target 35% = 348M ⚠ RESAMPLE x43x |

**Note:** Math and Systems require resampling for all options at typical training budgets due to limited availability.

## 3. Frontier Tier Mixture

### Current Distribution

| Domain | A+ Frontier | A Specialist | B Professional |
|--------|------------:|-------------:|---------------:|
| Code | 0 (0.0%) | 26,454 (40.1%) | 39,531 (59.9%) |
| Math | 36,820 (84.1%) | 6,959 (15.9%) | 0 (0.0%) |
| Systems | 2,916 (33.1%) | 5,857 (66.5%) | 30 (0.3%) |

### Proposed Internal Mix (within each domain)

| Tier | Target % | Rationale |
|------|----------|-----------|
| A+ Frontier | 40% | Highest-quality reasoning signals |
| A Strong Specialist | 40% | Breadth + grounding |
| B Professional | 15% | Additional coverage |
| C General | 5% | Minimal, only if available |
| D Reject | 0% | Excluded |

**Implementation:**
- Math: Select top 40% A+, then 40% A, then 20% B/C (already 100% A+/A)
- Code: Select all A (40%), then 40% B, drop rest
- Systems: Select all A+ and A (100%), minimal B

## 4. Code Concentration & Diversification Policy

### Problem
- Top 5 repos = 26% of Code data
- C (51%) and Python (32%) dominate; other languages <1%
- 84.6% bug-fix tasks; minimal implementation/architecture

### Controls

| Control | Threshold | Rationale |
|---------|-----------|-----------|
| Max token share per repo | 5% | Prevent single-repo dominance |
| Max record share per repo | 3% | Prevent over-representation |
| Language: Python | 30-40% | Maintain current level |
| Language: C | 30-40% | Reduce from 51% |
| Language: JS/TS | 10-15% | Increase from <1% |
| Language: Go | 5-10% | Increase from 0.5% |
| Language: Rust | 5-10% | Acquire new |
| Task: Bug fix | <70% | Reduce from 84.6% |
| Task: Implementation | 20% | Increase from 12.3% |
| Task: Testing | 5% | Increase from 1.4% |

### Sampling Method
- Within each repo: sort by quality_score DESC, trajectory length DESC
- Apply hard caps per repo after sorting
- Deterministic with seed=42

## 5. Math Multiple-Proof Policy

### Current State
- 43,779 records after dedup
- 5,752 unique problems
- Each problem has exactly 1 proof record (meta-verification and verification subsets removed)

### Recommendation: OPTION A — One Proof Per Problem

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| A. One proof/problem | Eliminates redundancy; preserves unique problems | Loses proof diversity | ✓ RECOMMENDED |
| B. Multiple proofs | Maximum diversity | High redundancy; same problem repeatedly | Reject |
| C. Capped proofs | Some diversity | Complex; arbitrary cap | Hold |
| D. Difficulty-aware | Smart selection | Requires difficulty labels | Future |

**Rationale:** The 38,958 removed records were verification/meta-verification variants of the same proof, not alternative proof approaches. For training, one high-quality proof per problem is sufficient. If proof diversity is needed, acquire additional math sources (olympiad math, competition math).

## 6. Systems Coverage Matrix

### Current Coverage

| Capability | Existing Records | Covered? | Notes |
|------------|----------------:|----------|-------|
| Kernel core | ~1,000 | YES | Scheduler, syscalls |
| Memory management | ~315 | YES | Page tables, slab |
| Filesystem | ~145 | YES | VFS, ext4 |
| Networking (kernel) | ~541 | YES | TCP/IP stack |
| Drivers | ~341 | YES | Kernel drivers |
| Architecture ports | ~59 | YES | x86, ARM, RISC-V |
| User-space | 0 | NO | CRITICAL GAP |
| CPU/GPU architecture | 0 | NO | CRITICAL GAP |
| Performance tuning | 0 | NO | CRITICAL GAP |
| Virtualization | 4 | NO | CRITICALLY LOW |
| Security | 8 | NO | CRITICALLY LOW |
| Storage admin | ~18 | PARTIAL | Block layer only |

### What StackExchange Fills
- User-space systems programming (POSIX, syscalls)
- Network administration and troubleshooting
- Performance tuning and debugging
- Virtualization management (KVM, Docker)
- Storage administration (LVM, ZFS)
- Shell scripting and automation

### What StackExchange Cannot Fill
- CPU/GPU microarchitecture
- Hardware design/validation
- Firmware/BIOS development

## 7. P2 StackExchange Acquisition Specification

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
| Stratification | By site, topic, score tier |
| Priority topics | Linux, networking, perf, virtualization, storage, concurrency |
| Exclude | End-user software, consumer HW, general computing |

## 8. Hardware Gap Capability Matrix

| Capability | Existing | Needed | Priority | Source Type |
|------------|----------|--------|----------|-------------|
| CPU architecture | 0 | YES | HIGH | Textbooks, whitepapers |
| GPU architecture | 0 | YES | HIGH | NVIDIA/AMD docs |
| Memory/cache | 0 | YES | HIGH | Computer architecture |
| OS | 8,803 | PARTIAL | MEDIUM | Kernel data (existing) |
| Networking | 541 | YES | HIGH | SE, RFCs, docs |
| Virtualization | 4 | YES | HIGH | KVM/QEMU docs, SE |
| Drivers | 341 | PARTIAL | MEDIUM | Kernel drivers |
| Firmware | 0 | YES | MEDIUM | UEFI, coreboot |
| Validation | 0 | YES | MEDIUM | Benchmark suites |
| Performance | 0 | YES | HIGH | Perf tuning |
| Embedded | 0 | YES | LOW | Arduino, Pi |
| Assembly/ISA | 0 | YES | MEDIUM | x86, ARM, RISC-V |

## 9. Mixture A/B/C Comparison

| Criteria | A: Balanced (40/30/30) | B: Frontier (50/30/20) | C: Systems Heavy (40/25/35) |
|----------|------------------------|------------------------|------------------------------|
| Data availability | ✓ All supported | ✓ All supported | ✓ All supported |
| Redundancy | Low | Low | Low |
| Specialist identity | Generalist | Math-focused | Systems-focused |
| Overfitting risk | LOW | MEDIUM | LOW |
| Domain collapse | LOW | MEDIUM (code 70%) | LOW |
| Frontier density | 83% | 83% | 85% |
| Code dominance | Reduced to 70% | Reduced to 70% | Reduced to 65% |
| Systems representation | 30% (best) | 20% | 35% (best) |
| RECOMMENDATION | Good generalist | **Best for reasoning** | Good for systems |

**RECOMMENDED: Option B (Frontier Weighted)**
- Highest frontier density while maintaining balance
- Math's 84% A+ justifies 50% weight
- Reduces code from 95% to ~70% of tokens
- Systems gets meaningful 20% representation

## 10. Training Budget Feasibility (Option B)

| Budget | Math | Code | Systems | Supported? | Notes |
|--------|------|------|---------|------------|-------|
| 1M | 500K | 300K | 200K | ✓ YES | Trivial |
| 5M | 2.5M | 1.5M | 1M | ✓ YES | Trivial |
| 10M | 5M | 3M | 2M | ✓ YES | Systems at 24% |
| 25M | 12.5M | 7.5M | 5M | ✓ YES | Systems at 61% |
| 50M | 25M | 15M | 10M | ⚠ PARTIAL | Systems needs x1.2 resample |
| 500M | 250M | 150M | 100M | ⚠ NEEDS RESAMPLE | Math x5.7, Systems x12.2 |

**Recommendation:** Start with 1M-10M token pilots. Scale to 50M+ after P2 acquisition adds Systems capacity.

## 11. Specialist vs General View Architecture

### View Definitions

| View | Math | Code | Systems | Frontier Filter | Description |
|------|------|------|---------|-----------------|-------------|
| general | 30% | 40% | 20% | None | Default, balanced |
| math_specialist | 60% | 25% | 15% | A+/A prioritized | Reasoning-focused |
| code_specialist | 20% | 70% | 10% | Trajectory depth | Agent-focused |
| systems_specialist | 20% | 30% | 50% | A+/A prioritized | Kernel + SE |

### Key Principles
1. No view modifies canonical records
2. Each view has independent sampling policy
3. Views are deterministic (seed=42)
4. Specialist views can draw from multiple domains
5. General view is the fallback/default

## 12. Evaluation Coverage

| Domain | Adequate? | Gaps | Action Needed |
|--------|-----------|------|---------------|
| Math | Partial | No undergrad/applied math; limited difficulty | Acquire olympiad math for eval |
| Code | Partial | No generation eval; only debugging | Create code gen eval set |
| Systems | NO | No eval set exists | CREATE systems eval set |
| General | Adequate | Small samples | Expand general_eval_v1 |

**Critical:** Systems has NO evaluation set. Must create one before training systems-specialist view.

## 13. Recommended Next Step

1. **Approve Option B mixture** (Math 50% / Code 30% / Systems 20%)
2. **Initiate P2 StackExchange acquisition** (8K records, archive.org)
3. **Create Systems evaluation set** from held-out kernel data
4. **Plan P3 hardware acquisition** (CPU/GPU architecture)
5. **Run 1M-10M token pilot** to validate mixture before scaling

---

```
MIXTURE DESIGN:
READY

RECOMMENDED MIXTURE:
Math    50%
Code    30%
Systems 20%
```