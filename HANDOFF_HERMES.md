# HANDOFF_HERMES.md — Hermes to Next Agent

> **Purpose:** Transfer document so the next engineering agent can continue Atlas development without Hermes memory access.
> **Date:** 2026-08-03
> **Previous lead agent:** Hermes

---

## 1. What Has Been Built

Atlas is a model-agnostic, long-term knowledge foundation for 8B-class LLM training and evaluation. The repository contains:

- A deterministic, versioned dataset pipeline: `raw/` → `processing/` → `curated/` → `training_views/`.
- An automation layer with a 7-state state machine, mandatory human approval gate, and governance agents.
- Evaluation infrastructure under `scripts/evaluation_engine/` and `docs/evaluation/`.
- A controlled LoRA validation pilot under `experiments/lora_pilot_math_v0.1/`.
- Extensive documentation: ADRs, engineering handbook, project context, specs, governance docs, phase reports, and evaluation reports.

Dataset v1.0 is frozen. Release, automation, intelligence, and baseline evaluation workstreams are complete.

---

## 2. Why Current Architecture Exists

The architecture was designed to avoid common dataset failure modes:
- Model coupling is avoided by storing canonical JSONL and generating model-specific formats downstream.
- Non-reproducibility is avoided by making every stage deterministic, scripted, and checksummed.
- License risk is avoided by enforcing denied-license gates and complete provenance on every record.
- Manual governance risk is avoided by automating quality, provenance, revision, validation, and approval checks while preserving human authority over releases.
- Pipeline fragility is avoided by persisting state to disk and allowing independent retry of failed stages.

---

## 3. What Decisions Were Made

- Canonical format is JSONL; model formats are config-driven conversions, not source artifacts.
- Raw sources are immutable. Corrections create new versions, not in-place edits.
- Human approval is mandatory before release.
- Evaluation is read-only, deterministic, and network-isolated during execution.
- External dependencies are minimized and wrapped behind interfaces.
- The QEE calibration gap was identified and documented as a known issue requiring recalibration before unsupervised approval use.

---

## 4. What Should Not Be Restarted

Do not restart:
- Dataset v1.0 freeze or release pipeline.
- Automation layer implementation.
- Existing training view generation without explicit authorization.
- Governance rules, schema contracts, or state machine transitions without an ADR and approval.

Reuse existing subsystems:
- Scheduler / orchestrator / state machine
- Provenance and validation agents
- Metadata sync and registry utilities
- Training view engine and manifest system

---

## 5. What the Next Agent Should Do First

1. Read `AGENTS.md`, `PROJECT_STATE.md`, and the latest docs under `docs/reports/` and `docs/evaluation/`.
2. Confirm current phase and whether any release/review gates are blocked.
3. Identify whether the next task is:
   - documentation / reporting,
   - evaluation metric improvement (Phase 5A.2),
   - QEE recalibration follow-up (Phase 5C),
   - training experiment execution on CUDA hardware, or
   - dataset expansion under existing governance rules.
4. If evaluation correctness work is chosen, start with `docs/evaluation/atlas_evaluation_framework.md` and `docs/evaluation/qee_human_alignment_report.md`.
5. If CUDA-dependent work is needed, validate hardware/runtime availability first; otherwise create explicit HOLD artifacts.

---

## 6. Potential Risks

- Modifying frozen assets or bypassing approval gates can invalidate provenance and release integrity.
- Inventing metrics or evaluation results undermines governance and training safety.
- Non-deterministic changes break reproducibility guarantees.
- QEE over-scoring can cause false approvals if used without recalibration.
- Missing CUDA runtime will block LoRA inference and training; do not claim execution without real tool output.

---

## 7. Recommended Workflow

1. Inspect before changing: read code, tests, metadata contracts, state machine rules, and invariants.
2. Explain needed changes, affected files, risks, and rollback plan before modifying files.
3. Implement incrementally and test.
4. Verify with real tool output.
5. Document decisions in `docs/` and update handoff/snapshot files when phase state changes.
6. Preserve knowledge: successful approaches become docs, reusable modules, or skills.

---

*This document is the ownership transfer from Hermes. Treat it as the starting truth until you verify current repo state independently.*
