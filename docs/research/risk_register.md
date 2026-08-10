# Atlas Research Risk Register

> **Phase:** 6.1
> **Status:** Adopted
> **Date:** 2026-08-04
> **Scope:** Risk register for Atlas as a reproducible LLM research platform.
> Risks are scored Likelihood × Impact (1–5 each). Mitigations are mandatory for
> any risk with score ≥ 9.

---

## 1. Scoring

| Score | Likelihood | Impact |
|-------|------------|--------|
| 1 | Rare | Negligible |
| 2 | Unlikely | Minor |
| 3 | Possible | Moderate |
| 4 | Likely | Major |
| 5 | Almost certain | Severe |

**Severity = Likelihood × Impact.** Thresholds: ≥ 9 high (must mitigate),
4–8 medium (monitor), ≤ 3 low (accept).

---

## 2. Reproducibility & Provenance Risks

| ID | Risk | L | I | Severity | Mitigation | Status |
|----|------|---|---|----------|------------|--------|
| R1 | Experiment inputs not pinned (commit/checksum/model/config/seed missing) | 3 | 5 | 15 | Protocol §3 pre-run metadata block; §4 checklist gate | Adopted |
| R2 | Dataset/view drift between approval and run | 2 | 5 | 10 | Manifest records checksum verification before training; fail-closed | Adopted |
| R3 | Evaluation engine changed mid-experiment | 3 | 4 | 12 | Record engine version + commit; freeze engine during run | Adopted |
| R4 | Model revision drift (base model updated) | 2 | 4 | 8 | Record HF revision SHA; pin revision | Monitor |
| R5 | Hardware/driver differences alter results | 2 | 3 | 6 | Record GPU, driver, CUDA, torch/transformers/peft/bnb versions | Monitor |
| R6 | Non-determinism in training run | 3 | 4 | 12 | Fixed seed; batch=1; determinism spot-check re-run | Adopted |
| R7 | Fabricated/placeholder metrics recorded as real | 2 | 5 | 10 | HOLD artifact rule; null metrics when unverifiable; audits | Adopted |

---

## 3. Dataset & Evaluation Risks

| ID | Risk | L | I | Severity | Mitigation | Status |
|----|------|---|---|----------|------------|--------|
| R8 | Eval split too small for conclusions | 5 | 3 | 15 | Minimum-N rule (N≥30 default); pilot vs conclusion labeling | Adopted |
| R9 | Train/eval overlap (memorization) | 2 | 5 | 10 | Enforce disjoint splits; verify no shared record_ids | Adopted |
| R10 | Evaluator extraction artifacts bias scores | 3 | 4 | 12 | Phase 5A.4 nested-brace fix; per-example review; regression tests | Fixed |
| R11 | Baseline not evaluated on same split/config | 3 | 4 | 12 | Baseline-first gate; same eval JSONL and inference config | Adopted |
| R12 | External benchmark placeholder treated as available | 2 | 3 | 6 | External benchmarks flagged `placeholder` until approved | Monitor |

---

## 4. Training & Compute Risks

| ID | Risk | L | I | Severity | Mitigation | Status |
|----|------|---|---|----------|------------|--------|
| R13 | VRAM OOM on 12 GB GPU | 3 | 3 | 9 | Validated NF4+double-quant+bf16+checkpointing config; peak-VRAM monitoring | Adopted |
| R14 | Overfitting on small views (e.g. 22-code set) | 5 | 3 | 15 | Document epoch inflation; scale/view expansion gate; watch train vs eval gap | Active |
| R15 | Training run interrupted (SSH/time) | 3 | 3 | 9 | nohup/setsid; step-metrics CSV flush; resume capability | Adopted |
| R16 | Config deviation from validated setup | 2 | 4 | 8 | Single-variable rule; config JSON frozen per experiment | Adopted |
| R17 | CUDA runtime unavailable during evaluation | 3 | 4 | 12 | HOLD artifacts with null metrics; never claim evaluation ran | Adopted |

---

## 5. Governance & Scope Risks

| ID | Risk | L | I | Severity | Mitigation | Status |
|----|------|---|---|----------|------------|--------|
| R18 | General-intelligence claim from single-domain pilot | 4 | 4 | 16 | Claims scoped to trained family only; mixed-domain required for cross-domain claims | Adopted |
| R19 | Release gating without human approval | 2 | 5 | 10 | `WAITING_HUMAN_APPROVAL` mandatory before any release | Adopted |
| R20 | Immutable data modified during experiment | 2 | 5 | 10 | Read-only access; checksum diff checks; outputs under experiments/ only | Adopted |
| R21 | Protocol not followed by future agents | 3 | 4 | 12 | Protocol + checklist referenced in AGENTS.md; review gate for results | Adopted |

---

## 6. High-severity mitigation summary (≥ 12)

| ID | Severity | Primary mitigation |
|----|----------|--------------------|
| R1 | 15 | Pre-run metadata block; reproducibility checklist gate |
| R8 | 15 | Minimum-N rule; scoped pilot vs conclusion distinction |
| R14 | 15 | View-expansion gate; overfit monitoring |
| R22 | 16 | Report per-metric deltas; normalize ratios; document scale limits |
| R23 | 20 | Code eval expansion to N ≥ 30 gate (G1) before Sprint P8-A |
| R3 | 12 | Engine version freeze + record |
| R6 | 12 | Seed + batch-1 determinism + spot-check |
| R7 | 10 | HOLD/null-metric rule; no fabrication |
| R10 | 12 | Evaluator fixes + per-example review + regression tests |
| R11 | 12 | Baseline-first gate on identical split/config |
| R17 | 12 | HOLD artifacts when CUDA unavailable |
| R18 | 16 | Domain-scoped claims only |
| R21 | 12 | Protocol referenced in AGENTS.md |

---

## 7. Register maintenance

- Register is reviewed whenever protocol, matrix, or benchmark plan changes.
- New risks are added with a severity score and a mitigation or explicit
  acceptance rationale.
- A risk whose mitigation fails during an experiment blocks the result
  (fail-closed, per protocol §6).

---

## 8. Cross-Domain Transfer Risks (Phase 8.0)

Added with Phase 8 transfer cells (matrix T1–T4; `docs/research/phase8_transfer_plan.md`,
threats T1–T10).

| ID | Risk | L | I | Severity | Mitigation | Status |
|----|------|---|---|----------|------------|--------|
| R22 | Incommensurable metrics (math correctness vs code patch-similarity) bias Transfer Ratio comparisons across directions | 4 | 4 | 16 | Report per-metric deltas separately; normalize ratios; document scale limits; cross-direction comparison treated as directional, not hard equality | Adopted |
| R23 | Underpowered target eval (code N=2) invalidates code transfer conclusions | 5 | 4 | 20 | Expand `code_eval_v1` to N ≥ 30 (gate G1) before Sprint P8-A — **met: `code_eval_v1` = N=100 (Phase 6.2)**; below N=30, results are pilot/directional or UNDETERMINED | Mitigated |
| R24 | Train-size mismatch between transfer directions confounds the symmetry verdict | 3 | 4 | 12 | Lock equal N across Sprint P8-A/P8-B (single-variable rule; P8-A locks N=400) | Adopted |
| R25 | Single seed (42) / single model class gives no variance estimate for symmetry | 3 | 3 | 9 | Effect sizes + per-example distributions mandatory; optional seed sweep before robust symmetry claim | Monitor |
| R26 | Evaluator extraction artifacts (format collapse, nested braces) masquerade as transfer | 3 | 4 | 12 | Phase 5A.4/6.4 patches frozen; format-consistency metric reported; per-example review | Adopted |
| R27 | Mixed-domain run confounds composition vs total record count (2N vs N) | 3 | 3 | 9 | Document as the mixed treatment; per-domain breakdown; optional equal-total-count ablation | Monitor |
| R28 | Baseline drift or QEE version change between transfer directions | 2 | 4 | 8 | Freeze QEE v2; record engine commit per run; same-split baselines (protocol §4) | Monitor |
