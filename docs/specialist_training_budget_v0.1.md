# Atlas Specialist Training Budget v0.1

## Purpose

Estimate training data requirements for Atlas 300M specialist models.
This document is **strategy documentation only**:

- no ingestion
- no training
- no dataset modification

All token/record/storage figures are **planning estimates** derived from
`docs/specialist_model_data_strategy_v0.1.md` targets and the validated
Phase 0.5 calibration results. They are not measured yields.

## Compatibility

- `docs/specialist_model_data_strategy_v0.1.md`
- `docs/expert_definition_v0.1.md`
- `docs/expert_quality_gate_v0.1.md`
- `docs/expert_gap_report_v0.1.json`
- `configs/training/qlora_qwen3_8b.yaml` (reference template; training paused)

---

## 1. Model Assumptions

| Assumption | Value | Notes |
|------------|-------|-------|
| Parameters | ~300M | small specialist scale |
| Hardware | RTX 5070, 12GB VRAM | single consumer GPU |
| Weight memory (fp16/bf16) | ~0.6GB | 300M × 2 bytes |
| Weight memory (4-bit QLoRA base) | ~0.15–0.2GB | NF4 quantization |
| Training approach | QLoRA or full fine-tune | both feasible on 12GB (below) |
| Context window | up to 4096 tokens | matches existing config reference |

### 1.1 Training feasibility on RTX 5070 12GB

**QLoRA (recommended first path):**

- 4-bit base weights: ~0.2GB
- LoRA adapter trainable params: ~1–5M (~0.01–0.02GB)
- Optimizer (paged AdamW 8-bit, LoRA params only): small
- Activations with gradient checkpointing: a few GB at batch 8–16
- **Verdict: comfortable. Batch 8–16, seq ≤ 4096 fits in 12GB.**

**Full fine-tune (bf16):**

- Weights 0.6GB + gradients 0.6GB + AdamW states ~3.6GB (fp32 moments)
  ≈ 4.8GB before activations
- Activations with gradient checkpointing + small batch: +2–4GB
- **Verdict: feasible. Use batch 2–4, seq ≤ 2048, gradient accumulation.**

Both options fit the reference pipeline in
`configs/training/qlora_qwen3_8b.yaml` (model-agnostic JSONL, chat-template
conversion, LoRA target modules).

### 1.2 Token scaling reference

Chinchilla-optimal for 300M parameters is ~20 tokens/param ≈ **6B tokens**.
The specialist plan intentionally deviates: curated, quality-gated expert
data at 0.1–0.3B tokens/specialist is the target, consistent with the
"quality > quantity" philosophy and with published small-curated-set
training results (e.g., Platypus-class, Orca-Math-class runs). The 6B
Chinchilla point is a reference ceiling, not the plan.

---

## 2. Per-Specialist Budget

Planning assumptions:

- Average tokens per record by domain (planning estimate): Code 1200,
  Math 1000, AI/ML 800, System 1000, Science 900.
- Storage estimate: ~4 chars/token × ~1.1 byte/char (UTF-8 English, code
  denser) ≈ **~4.4 bytes/token raw**, plus ~20% JSONL/metadata overhead
  ≈ **~5.3 bytes/token JSONL**. Zstd compresses roughly 2–2.5×.
- Record counts follow `docs/specialist_model_data_strategy_v0.1.md` §4.1.

| Specialist | Min records | Recommended records | Token target (rec) | Expected storage (JSONL / zstd) | Feasibility |
|------------|------------|---------------------|--------------------|--------------------------------|-------------|
| Code-300M | 100k | 200k | ~120M–240M | ~0.6–1.3GB / ~0.3–0.6GB | HIGH (QLoRA); gold-verified core |
| Math-300M | 100k | 200k | ~100M–200M | ~0.5–1.1GB / ~0.25–0.5GB | HIGH (QLoRA); CC-BY-4.0 source |
| AI-ML-300M | 100k | 150k | ~80M–120M | ~0.4–0.6GB / ~0.2–0.3GB | HIGH (QLoRA) |
| System-300M | 50k | 100k | ~50M–100M | ~0.3–0.5GB / ~0.15–0.25GB | HIGH; doc-derived Q&A |
| Science-300M | 50k | 100k | ~45M–90M | ~0.25–0.5GB / ~0.12–0.25GB | HIGH; paper-derived |

**Notes:**

- Recommended token targets are 20–50× below the Chinchilla 6B ceiling by
  design; if quality gates pass on the pilot, the budget can be raised
  before full training.
- Storage figures are trivial for a 12GB-GPU workstation and well within
   the Atlas storage policy (raw shards on devpc, curated JSONL in repo).
- "Feasibility" assumes the paused-training gate is lifted by a future
  approval; this document does not lift it.

---

## 3. Data Scaling Philosophy

### 3.1 Quality > quantity

- The budget targets are **minimums for capability, not volume targets**.
  A 200k-record, quality-gated set is preferred over a 2M-record unfiltered
  set.
- Every GO calibration (SWE-bench, ArXiv, OpenMathInstruct-2) measured
  schema pass 1.0 and KEEP-rate ≥ 0.99 at the 100-record sample scale;
  the same gate must hold for every promoted record.

### 3.2 Expert records weighted higher

- E2/E3 reasoning records carry more training signal per token than E1
  factual records.
- Sampling weights (planning estimate): E1 × 1.0, E2 × 2.0, E3 × 2.5 in
  the training-view sampler, subject to calibration against eval metrics.
- Verified records (gold patches, expected answers) are weighted above
  unverified content; `verification.status` drives the weight.

### 3.3 E1/E2/E3 mix

| Tier | Share | Role in budget |
|------|-------|----------------|
| E1 | 60% | knowledge anchor; high-volume, low-weight |
| E2 | 30% | reasoning core; medium-volume, mid-weight |
| E3 | 10% | frontier signal; low-volume, high-weight |

Per-specialist mixes may shift (Math leans E2/E3, System leans E1) while
preserving the global 60/30/10 default.

---

## 4. Data Type Split

For each specialist, the training mix separates into four buckets. The
percentages are planning estimates.

| Type | Share | Contents | Example sources |
|------|-------|----------|-----------------|
| Knowledge data | ~40% | factual/professional content, E1 | docs, man-pages, verified Q&A, arXiv abstracts (context) |
| Reasoning data | ~40% | multi-step/problem-solving, E2/E3 | SWE-bench patches, OpenMathInstruct-2 solutions, competition math |
| Instruction data | ~20% | formatting/instruction-following pairs | chat-template conversion of the above; small instruction set |
| Evaluation data | separate (never trained) | held-out eval sets | SWE-bench test, MATH/GSM8K test, held-out arXiv, doc Q&A, science Q&A |

**Rules:**

- Evaluation data is **excluded from training views** (leakage guard).
  Target 5k–10k held-out records per specialist.
- Knowledge and reasoning buckets are not strictly separated in the JSONL
  (schema is uniform); the split is enforced by sampling weights and
  subdomain tags (`metadata.subdomains`).
- Instruction data can be generated from the same records via the
  chat-template converter — no new ingestion required.

---

## 5. First Training Milestone: Small Pilot Model

Before any full specialist training, run a **small pilot model** to validate
the pipeline, hardware budget, and eval harness end-to-end.

### 5.1 Recommended pilot: Math-300M (or Code-300M)

| Item | Value |
|------|-------|
| Pilot scope | 10k records (10% of min budget) |
| Pilot tokens | ~10M–12M |
| Pilot storage | ~60MB JSONL / ~30MB zstd |
| Data source | OpenMathInstruct-2 (CC-BY-4.0, GO) — Math pilot; or SWE-bench Verified (MIT, GO) — Code pilot |
| Split | 9k train / 0.5k eval / 0.5k holdout |
| Training | QLoRA 4-bit, 300M base, batch 8–16, seq ≤ 4096, 3 epochs |
| Expected wall time | ~1–4 hours (planning estimate, GPU-dependent) |
| Success criteria | loss decreases, eval accuracy improves vs untrained base, no schema/provenance regressions |

### 5.2 Pilot deliverables

1. Confirmed end-to-end path: curated JSONL → chat-template → QLoRA → eval.
2. Measured VRAM/throughput on the RTX 5070 (batch, seq length, epochs).
3. First calibration of token-budget-per-capability (does 10k records move
   the eval needle?).
4. A decision gate: GO → scale to recommended budget; HOLD → adjust mix /
   weights / epochs; STOP → revisit data quality or model size.

---

## 6. Constraints

1. **No ingestion** — this budget adds no data.
2. **No training** — the training pause remains in force; pilot and full
   training require explicit future approval.
3. **No dataset modification** — no curated/raw/release artifacts change.
4. **No unverified sources** — only VERIFIED registry sources and GO
   calibration sources are eligible; Open-Platypus stays HOLD until license
   filtering resolves.
5. All figures here are **planning estimates**; measured yields from the
   10K pilot supersede them.

---

## Next Steps (not started; for approval)

1. Approve the small pilot milestone (Math-300M or Code-300M, 10k records).
2. Build the 10K pilot extraction from the three GO sources.
3. Stand up the eval harness (extend `evaluation/`) with holdout sets.
4. Measure pilot VRAM/throughput/quality; then revise this budget with
   measured numbers.
