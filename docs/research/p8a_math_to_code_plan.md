# P8-A Experiment Plan — Math → Code Cross-Domain Transfer

> **Phase:** 8 (Experiment A)
> **Status:** PREPARATION — documentation and deterministic subset staged.
> **NO training is authorized by this document. Training starts only after all
> gates pass and explicit human approval is given.**
> **Date:** 2026-08-05
> **Experiment ID:** `atlas-math-small-qwen7b-lora-transfer-v1`
> **Scope:** First cross-domain transfer experiment of Phase 8: train a QLoRA
> adapter on the Atlas **math** domain and evaluate cross-domain transfer on
> the **code** domain (`code_eval_v1`, N=100). This plan is the P8-A execution
> and gating spec; it extends `docs/research/phase8_transfer_plan.md` (cell T1).

---

## 1. Objective

Prepare and gate the P8-A run: train a QLoRA adapter on a deterministic math
training subset and measure whether the trained adapter transfers capability to
the code domain, relative to the frozen same-split code baseline.

The preparation deliverable (this phase, already produced):

| # | Deliverable | Location | Status |
|---|-------------|----------|--------|
| 1 | Renamed experiment identifiers `Sprint 4A–4D` → `P8-A–P8-D` across the research protocol, Phase 8 plan, experiment matrix, and risk register | `docs/research/` | DONE |
| 2 | This P8-A plan (objective, hypothesis, outcomes, criteria, threats, artifacts) | `docs/research/p8a_math_to_code_plan.md` | DONE |
| 3 | Deterministic math training subset (N=400) + manifest + leakage audit | `experiments/phase8_transfer/subsets/` | DONE |
| 4 | Evaluation plan (below §6) | this document | DONE |
| 5 | Implementation checklist (§8) | this document | DONE |

No model training, no dataset modification, and no QEE engine modification
have been performed during preparation.

---

## 2. Hypothesis

**H1 (direction):** QLoRA training on the Atlas math domain yields positive
cross-domain transfer to the code domain, i.e. `Δ_cross^{M→C} ≥ +τ`
(`τ = 0.05`, protocol §8.3) **and** the per-example improved count exceeds the
regressed count on `code_eval_v1`.

**H2 (strength):** the Transfer Ratio is positive, `TR_{M→C} > 0`, when
defined (`Δ_in^M > 0`); a strength tier (strong / weak / neutral) is assigned
per protocol §8.2. If `Δ_in^M ≤ 0`, `TR_{M→C}` is recorded `N/A` (HOLD) and
never fabricated.

**H3 (mechanism guard):** math-style reasoning (planning, stepwise derivation,
answer extraction) transfers at least in part to code-patch reasoning. The
effect must be visible as a delta versus the same-split baseline, not as
absolute score (guards against the QEE +2.14 bias, threat T5).

Claims are scoped to **math → code capability only** (protocol §5). No
general-intelligence claim is made.

---

## 3. Expected Outcomes

The run must produce one of the following, decided by the rules in
`phase8_transfer_plan.md` §3.3 / protocol §8.3:

| Outcome | Condition | Conclusion |
|---------|-----------|------------|
| Positive transfer | `Δ_cross ≥ +τ` AND improved > regressed | Training on math helps code |
| Neutral transfer | `\|Δ_cross\| < τ` (claimable at N ≥ 30) | No measurable cross-domain effect |
| Negative transfer | `Δ_cross ≤ −τ` AND regressed > improved | Training on math harms code |
| UNDETERMINED | `N < 30` or effect not distinguishable | HOLD for the conclusion |

Additional expected reporting: `Δ_cross^{M→C}`, `Δ_in^M` (source-domain
in-domain gain on `math_eval_v1`), `TR_{M→C}` (or `N/A`), and the per-example
improved / regressed / unchanged counts on `code_eval_v1`.

The result feeds P8-D (symmetry analysis) once P8-B (Code → Math) completes.

---

## 4. Locked Configuration (P8-A)

Identical to the validated Phase 5B.1 / Phase 7.2 configuration
(`phase8_transfer_plan.md` §4), with P8-A-specific values:

| Variable | P8-A value |
|----------|-----------|
| Experiment ID | `atlas-math-small-qwen7b-lora-transfer-v1` |
| Training subset | `experiments/phase8_transfer/subsets/P8A_math_train.jsonl` (N=400) |
| Subset raw-file SHA-256 | `55e15fda53c16a9c10dc6de23e5ead069c97bbb730fb5a43b55bf1c453b6bbc0` |
| Subset records SHA-256 | `d31af8214f0573dc8183e173d0379e835bf40a0ab6d0702a7a1d047a647ee9af` |
| Selection seed | `phase8-transfer-v1` (order = ascending `sha256(seed:record_id)`, first 400) |
| Base model | `Qwen/Qwen2.5-7B-Instruct` (revision `a09a35458c702b33eeacc393d103063234e8bc28`) |
| Quantization | NF4 4-bit + double quant, bf16 compute |
| LoRA | r=8, alpha=16, dropout=0.05, bias=none, targets `q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj` |
| Optimizer / schedule | `paged_adamw_8bit`, lr 2e-4, cosine, warmup 0.03 |
| Batch | batch=1, grad accum=8 (effective 8) |
| Weight decay / grad norm | 0.01 / 1.0 |
| Max seq length | 1024 |
| Steps | per protocol; max_steps recorded pre-run |
| Seed | 42 |
| Evaluator | QEE v2 (`scripts/evaluation_engine/v2`), frozen |
| Target eval split | `evaluation/eval_sets/phase6_expansion_v1/code_eval_v1.jsonl` (N=100) |
| Code baseline (same split) | `experiments/phase6_baseline_eval/baseline.json` → code domain (correctness 0.2217, N=100, QEE v2) |
| Hardware | NVIDIA RTX 5070 12 GB (devpc) |

### 4.1 Dataset gate inputs (pinned)

- Source pool: `tmp/expert_pilot_6500_records_v0.1.jsonl` (release
  `expert-pilot-6500-v0.1`), math records `expert-math-002` (pool N=3000).
- Eligibility exclusions applied: 18 REJECT-reviewed, 100 `math_eval_v1`,
  13 training-view eval (`math_300m_v0.1/eval.jsonl`), 0 `code_eval_v1`.
  Eligible pool = 2882; first 400 selected.
- Train/eval disjointness verified (leakage audit: clean, no overlaps against
  `math_eval_v1`, `code_eval_v1`, or the frozen training-view eval split).

---

## 5. Threats to Validity (P8-A focus)

Mapped to `phase8_transfer_plan.md` §6 (T1–T10) and the risk register
(R22–R28):

| ID | Threat | P8-A mitigation | Status |
|----|--------|-----------------|--------|
| T1 | Train/eval overlap → memorization as transfer | Leakage audit passed (no shared IDs with `code_eval_v1` / `math_eval_v1`); verified in manifest | MET |
| T2 | Incommensurable metrics (math correctness vs code patch-similarity) | Deltas vs same-split baseline only; per-metric reporting; cross-direction TR comparison is directional | Active |
| T3 | Underpowered target eval | `code_eval_v1` = N=100 (Phase 6.2 expansion) → power rule satisfied | MET |
| T4 | Evaluator extraction artifacts (nested braces, format collapse) | QEE v2 frozen with Phase 5A.4/6.4 patches; format-consistency reported; per-example review | Active |
| T5 | QEE +2.14 bias inflates absolute scores | Conclusions on deltas vs baseline, not absolute | Active |
| T6 | Mixed-domain composition confound | Not applicable to P8-A (single-domain run); relevant for P8-C | N/A |
| T7 | Train-size mismatch vs P8-B biases symmetry | N locked at 400; P8-B must match (single-variable rule) | Active |
| T8 | Single seed / single model → no variance estimate | Effect sizes + per-example distributions mandatory; seed sweep optional before robust claim | Active |
| T9 | Baseline drift / engine change | QEE v2 frozen; engine commit recorded per run; same-split baseline | Active |
| T10 | Source-pool heterogeneity (OpenMathInstruct-2 derived) | Single source (`expert-math-002`) recorded; composition in manifest | MET |
| R23 | Code eval underpowered | Mitigated — `code_eval_v1` = N=100 | MET |
| R24 | Train-size mismatch | N=400 locked for P8-A (and P8-B) | Active |

---

## 6. Evaluation Plan

**Scope:** P8-A evaluates **only** on the code domain target split. No other
eval split is used for the P8-A transfer conclusion.

| Parameter | Value |
|-----------|-------|
| Eval split | `evaluation/eval_sets/phase6_expansion_v1/code_eval_v1.jsonl` |
| Eval set size | N = **100** (records checksum `8ff09120446b5c87f94b2acde6aefb29255015be0bb8c3d23c05e900457c4c67`; file SHA-256 `37b9c42a9b6aa514f602ad0d90e1d4c9ec243625d6f34774c41066de6fdf6b1b`) |
| Evaluator | **QEE v2** — `scripts/evaluation_engine/v2/`, frozen (Phase 5A.4 nested-brace + Phase 6.4 percentage/unit/format patches) |
| Baseline (same split) | `experiments/phase6_baseline_eval/` code domain — correctness **0.2217**, reasoning_quality 0.4169, hallucination_rate 0.76, format_consistency 1.0, evaluated N=100 |
| Inference config | greedy decoding, max_new_tokens recorded, NF4 4-bit + bf16 (baseline-compatible) |
| Source-domain eval (supporting only) | `math_eval_v1` (N=100) to compute `Δ_in^M` for the Transfer Ratio |

Primary metric: **code patch added-line similarity** (QEE v2 `code_eval`).
Secondary reported metrics: reasoning_quality, hallucination_rate,
answer_format_consistency — per example and aggregate, per protocol §7.

Deliverables: per-example QEE v2 scores on `code_eval_v1`, aggregate metrics,
same-split baseline comparison with per-example deltas, and the transfer record
(`Δ_cross^{M→C}`, `Δ_in^M`, `TR_{M→C}` or `N/A`, transfer type).

---

## 7. Success and Failure Criteria

### 7.1 Success criteria (ALL must hold)

1. **Reproducibility gate green** — protocol §4 checklist complete; no HOLD on
   inputs; git commit + clean status recorded at run start.
2. **Dataset gate green** — subset N=400; raw-file and records checksums match
   the manifest values above; leakage audit clean.
3. **Baseline-first** — code baseline recorded on the exact same
   `code_eval_v1` split with the same inference config.
4. **Evaluation completed** — QEE v2 produced per-example and aggregate scores
   on all N=100 target records, with recorded inference config.
5. **Deltas reported** — `Δ_in^M`, `Δ_cross^{M→C}`, per-example
   improved/regressed/unchanged counts, transfer type (or UNDETERMINED).
6. **TR or N/A** — Transfer Ratio reported when `Δ_in^M > 0`; `N/A` (HOLD for
   the ratio) otherwise. No fabricated ratios.
7. **Claims scoped** — math → code capability only; no general-intelligence
   claim.

### 7.2 Failure criteria (ANY ⇒ run is failed/HOLD)

1. **Dataset gate fails** — checksum mismatch, wrong N, or any overlap with an
   eval split.
2. **Reproducibility broken** — unverifiable input, dirty/unrecorded git state,
   unrecorded engine/commit, seed not applied.
3. **Immutable-data violation** — any frozen dataset, training view, or QEE
   file modified during the run.
4. **Underpowered** — target eval N < 30 for a conclusion (N=100 planned).
5. **Evaluation invalid** — QEE v2 modified mid-run or version not recorded.
6. **Metrics fabricated** — any number not measured (e.g., claiming eval ran
   without CUDA). Record `HOLD` with null metrics instead.

---

## 8. Implementation Checklist

### 8.1 Dataset gate

- [x] `P8A_math_train.jsonl` staged with N=400 from `expert-math-002` pool.
- [x] Deterministic ordering `sha256("phase8-transfer-v1:{record_id}")`.
- [x] Eligibility: REJECT + `math_eval_v1` + tv-eval + `code_eval_v1` excluded.
- [x] Leakage audit clean (no overlap with any eval split).
- [x] Provenance complete: 400/400 `original_id` present; single source/license.
- [ ] **Re-verify on the training machine (Ubuntu-24.04)** — rebuild subset and confirm
      checksums match before run start (protocol §4.2).

### 8.2 Checksum gate

- [x] Subset raw-file SHA-256: `55e15fda53c16a9c10dc6de23e5ead069c97bbb730fb5a43b55bf1c453b6bbc0`.
- [x] Subset records SHA-256: `d31af8214f0573dc8183e173d0379e835bf40a0ab6d0702a7a1d047a647ee9af`.
- [x] Target eval records checksum pinned (`code_eval_v1` = `8ff09120…`).
- [x] Manifest written with all checksums; determinism spot-check passed
      (re-run → identical hashes).
- [ ] Verify subset + eval hashes on the execution host before model loading.

### 8.3 Reproducibility gate (protocol §4)

- [ ] `metadata.json` pre-run block: experiment_id, phase, git_commit +
      git_status_clean, training_view/subset id, subset + eval checksums,
      base model + revision, QEE v2 version + commit, seed, hardware, full
      training config.
- [ ] **QEE v2 pinned in git** — `scripts/evaluation_engine/v2/` is currently
      **untracked**; it must be committed and its commit recorded before
      training (fail-closed blocker for engine pinning).
- [ ] Seed 42 applied before any randomness.
- [ ] Determinism spot-check (same config twice → same aggregate).
- [ ] Outputs written under `experiments/atlas-math-small-qwen7b-lora-transfer-v1/`
      only; no dataset/view/release artifact modified.

### 8.4 Evaluation gate

- [x] Target eval split locked: `code_eval_v1` (N=100).
- [x] Same-split code baseline exists (`phase6_baseline_eval`, correctness 0.2217, QEE v2).
- [ ] Post-training QEE v2 run on all 100 target records with baseline-compatible
      inference config; per-example + aggregate output.
- [ ] `Δ_cross^{M→C}`, `Δ_in^M`, `TR_{M→C}` (or `N/A`), transfer type, and
      improved/regressed/unchanged counts recorded.
- [ ] Result usable for a conclusion only if target eval N ≥ 30 and all gates
      green; otherwise `UNDETERMINED`/HOLD.

### 8.5 Artifact checklist

| Artifact | Path (relative to repo) | Status |
|----------|--------------------------|--------|
| Subset | `experiments/phase8_transfer/subsets/P8A_math_train.jsonl` | READY |
| Subset manifest + audit | `experiments/phase8_transfer/subsets/P8A_math_train_manifest.json` | READY |
| Subset builder | `scripts/evaluation_engine/build_p8a_subset.py` | READY |
| Training config | `experiments/{experiment_id}/config.json` | AFTER APPROVAL |
| Hardware info | `experiments/{experiment_id}/hardware_info.json` | AFTER APPROVAL |
| Training log + step metrics | `experiments/{experiment_id}/training_log.json`, `step_metrics.csv` | AFTER APPROVAL |
| Adapter checksum | `adapter_model.safetensors` SHA-256 | AFTER APPROVAL |
| QEE v2 eval report | per-example + aggregate on `code_eval_v1` | AFTER APPROVAL |
| Baseline comparison | same-split deltas | AFTER APPROVAL |
| Transfer record | `Δ_in^M`, `Δ_cross^{M→C}`, `TR_{M→C}`/`N/A`, type | AFTER APPROVAL |

---

## 9. What This Document Does NOT Authorize

- **No training.** This is preparation. Training begins only after all §8 gates
  pass and explicit human approval is granted.
- **No modification** of frozen datasets (`curated/`, `raw/`, `review_queue/`,
  `training_views/`) or the QEE engine.
- **No P8-B/C/D execution** — those are separate experiments with their own
  preparation and approval.
- **No commit / push** — docs and staged preparation artifacts are left in the
  working tree for review.

---

## 10. Versioning

| Version | Date | Change |
|---------|------|--------|
| v1.0 | 2026-08-05 | Initial P8-A preparation lock (subset staged, plan written, gates defined). |

---

## 11. References

- Phase 8 cross-domain transfer plan — `docs/research/phase8_transfer_plan.md`
- Research Protocol v1.1 (§8 transfer measurement) — `docs/research/experiment_protocol_v1.md`
- Experiment matrix (cell T1) — `docs/research/experiment_matrix.md`
- Risk register (R22–R28) — `docs/research/risk_register.md`
- Benchmark plan — `docs/research/benchmark_plan.md`
- Evaluation set expansion report — `docs/evaluation/eval_set_expansion_report.md`
- Phase 6.3 baseline evaluation — `experiments/phase6_baseline_eval/`
