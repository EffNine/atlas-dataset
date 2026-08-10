# Baseline Comparison Report — v0.1 (QEE v1) vs v0.2 (QEE v2)

> **Experiment:** `baseline_eval_v0.2` · **Phase:** 5A.3 · **Date:** 2026-08-03
> **Model:** `Qwen/Qwen2.5-7B-Instruct` · 4-bit NF4 double-quant · bf16 · greedy · max_new_tokens=256 · seed=42 config
> **Hardware:** NVIDIA GeForce RTX 5070 (12227 MiB), torch 2.13.0+cu130, CUDA 13.0
> **Samples:** 29 (code 2 · math 13 · aiml 14) — identical views, identical prompts, identical generation config as v0.1.

## 1. Determinism check

- Predicted responses reproduced exactly vs the v0.1 run: **29/29** (100%).
- The same inference outputs are therefore scored under both metric engines — differences below are attributable to the scoring engine, not the model.

## 2. What changed between v0.1 and v0.2 scoring

| Metric | v0.1 (QEE v1) | v0.2 (QEE v2) |
|---|---|---|
| correctness | strict verbatim substring match against reference | verifiable per answer type: math = numeric equivalence, code = syntax + structural/patch similarity, semantic = rubric + reference overlap |
| reasoning_quality | `1.0` if response length > 30 chars | v2 7-dimension weighted quality (0..1) |
| hallucination_rate | hardcoded `0.0` (never measured) | fraction of answers that are definitively wrong AND low-quality (correct=False, correctness<0.4) |
| answer_format_consistency | `1.0` if non-empty | type-specific structural expectation |

The v0.1 `correctness=0.0` everywhere is an artifact of substring matching — semantically correct math answers that do not reproduce the reference text verbatim were all scored 0. The v0.2 engine was built to fix exactly this (see `docs/evaluation/qee_v2_design.md`).

## 3. Aggregate comparison

| Metric | v0.1 | v0.2 | Delta |
|---|---|---|---|
| correctness | 0.0000 | 0.6112 | +0.6112 |
| reasoning_quality | 1.0000 | 0.6911 | -0.3089 |
| hallucination_rate | 0.0000 | 0.2949 | +0.2949 |
| answer_format_consistency | 1.0000 | 1.0000 | +0.0000 |
| latency (s/ex) | not recorded in v0.1 | 12.65 | — |
| tokens/sec | not recorded in v0.1 | 17.0 | — |

> Latency/tokens-sec were not recorded by the v0.1 runner. Because v0.2 used the identical model, views, prompts, generation config and GPU, and reproduced the v0.1 responses exactly (29/29), the v0.2 timing is representative of both runs.

## 4. Domain breakdown

| Domain | n | correctness v1→v2 | reasoning v1→v2 | hallucination v1→v2 | format v1→v2 |
|---|---|---|---|---|---|
| code | 2 | 0.000 → 0.500 | 1.000 → 0.608 | 0.000 → 0.500 | 1.000 → 1.000 |
| math | 13 | 0.000 → 0.611 | 1.000 → 0.680 | 0.000 → 0.385 | 1.000 → 1.000 |
| aiml | 14 | 0.000 → 0.723 | 1.000 → 0.786 | 0.000 → 0.000 | 1.000 → 1.000 |

## 5. What v2 actually measures per domain

### code (n=2)
- `expert_swe_000366` — reproduced the reference patch exactly → correctness **1.0**, patch method.
- `expert_swe_000299` — produced prose describing the fix but not the diff patch → correctness **0.0**. This is a real (honest) miss: the model did not emit the patch the reference expects.

### math (n=13)
- 7/13 final answers verifiably equivalent to the reference (numeric/equivalence check), 6/13 wrong or unparsable → correctness **0.611**.
- hallucination_rate 0.385: 5 answers are definitively wrong AND low-quality (e.g. wrong radius `√7/2` vs reference; wrong ratio `4/9`; Lagrange answer that missed the `√3` bound).

### aiml (n=14)
- All 14 scored via the semantic rubric; correctness **0.723**, hallucination **0.0** (no answer was both wrong and low-quality; rubric grades coverage/specificity/novelty/grounding/structure/clarity, not keyword presence).

## 6. Reading the numbers honestly

- **v0.1 correctness was meaningless** (all 0.0 by substring match). v0.2's 0.61 overall is the first *verifiable* correctness figure for this baseline.
- **v0.1 hallucination was hardcoded 0.0**; v0.2's 0.29 is a real, conservative estimate (only definitively-wrong + low-quality answers count).
- The metric definitions changed between v0.1 and v0.2, so **absolute values are not directly comparable as trends** — v0.2 is the new baseline reference, and Phase 5B LoRA deltas must be computed against v0.2, not v0.1.

## 7. Artifacts

| Artifact | Path |
|---|---|
| config | `experiments/baseline_eval_v0.2/config.json` |
| baseline v2 | `experiments/baseline_eval_v0.2/baseline_v2.json` |
| per-example | `experiments/baseline_eval_v0.2/per_example_results.jsonl` |
| hardware info | `experiments/baseline_eval_v0.2/hardware_info.json` |
| comparison report | `experiments/baseline_eval_v0.2/comparison_report.md` (this file) |
| runner | `experiments/baseline_eval_v0.2/run_baseline_v2.py` |
| v0.1 baseline | `experiments/baseline_eval_v0.1/evaluation/baseline.json` |
| QEE v2 design | `docs/evaluation/qee_v2_design.md` |

## 8. GO / HOLD recommendation for Phase 5B

**Recommendation: GO — proceed to Phase 5B (LoRA pilot) with QEE v2 as the scorer.**

Rationale:
- Baseline is now reproducibly measured with a verifiable correctness engine (`baseline_v2.json`, 29 samples, deterministic 29/29 vs v0.1).
- The scorer is no longer a ceiling artifact: math/code correctness is reference-verifiable, semantic is rubric-based with anti-stuffing.
- Latency/tokens-per-sec are captured for the first time (12.6 s/ex, 17 tok/s).

Caveats (do not skip):
- Phase 5B LoRA **training** still requires the CUDA box (available here) and must be separately authorized; this report authorizes the *baseline*, not training.
- Re-score the LoRA post-training output with **the same QEE v2 engine** so deltas are apples-to-apples.
- v2 correctness remains uncalibrated against a larger human-review sample (Phase 5C); do **not** use it as an unsupervised approval gate yet.
