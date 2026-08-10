# PROJECT_STATE.md — Atlas Project Snapshot

> **Purpose:** Exact current project state for handoff and audit.
> **Date:** 2026-08-07
> **Branch:** main
> **HEAD:** d1fb931

---

## 1. Current Phase

- **Current phase:** Phase 6.1 completed (Atlas Research Protocol v1.0)
- **Status:** GO
- **Next recommended step:** Research protocol execution (benchmark_plan.md)

---

## 2. Completed Milestones

- Dataset v1.0 frozen
- Release pipeline completed
- Automation layer completed
- Intelligence layer completed
- Baseline evaluation completed
- RTX 5070 inference verified
- Phase 5A.4 math evaluator robustness patch (nested-brace extraction)
- Phase 5B.1 math LoRA pilot (QEE v2 + analysis)
- Phase 5B.2 code LoRA pilot
- Phase 6.1 Atlas Research Protocol v1.0 (docs/research/)

---

## 3. Current Issue

- **Evaluation correctness metric requires improvement.**
- Math/code eval splits (N=13 / N=2) are below the research-protocol minimum
  (N ≥ 30); view expansion is the first benchmark gate.

---

## 4. Model Information

| Item | Value |
|------|-------|
| Current model | Qwen/Qwen2.5-7B-Instruct |
| Quantization | 4-bit NF4 |
| Compute dtype | bfloat16 |
| Hardware | NVIDIA GeForce RTX 5070 12GB |
| VRAM usage | [HUMAN MUST SUPPLY] |
| Seed | 42 |

---

## 5. Baseline Results

| Metric | Value |
|--------|-------|
| Evaluation samples | 29 |
| Inference status | completed successfully |
| Scoring caveat | [HUMAN MUST SUPPLY] |

> **Note:** The exact scoring caveat text should be confirmed from the latest evaluation report before publication.

---

## 6. Known Limitations

- QEE shows systematic positive bias versus human reviewers (+2.14 points documented in `docs/evaluation/qee_human_alignment_report.md`).
- QEE exact agreement with human review is 0% in the latest analyzed sample.
- Math LoRA pilot delta was evaluator-artifact-driven; corrected re-score (Phase 5A.4) shows no reasoning gain, only answer-format consistency.
- Code LoRA pilot is inconclusive (N=2 eval).
- No model training has been authorized beyond controlled pilot scope.

---

## 7. Repository State

| Check | Value |
|-------|-------|
| Working tree | Clean |
| Uncommitted changes | None |
| Untracked files | `AGENTS.md` |
| Last commit | `d1fb931 docs(report): add Phase 4A repository freeze verification` |

---

## 8. Next Actions

1. Execute the Atlas Research Protocol v1.0 (`docs/research/experiment_protocol_v1.md`) for all future experiments.
2. Expand math/code eval splits to N ≥ 30 (first benchmark gate).
3. Run aiml baseline eval (pending).
4. Validate any new evaluation metrics against human review signals before automated approval use.
5. Confirm missing numeric fields above (VRAM usage, scoring caveat) from the latest phase report.

---

*This snapshot reflects repository state as of 2026-08-04.*
