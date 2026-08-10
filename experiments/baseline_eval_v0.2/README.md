# Phase 5A.3 — Pre-LoRA Baseline Re-evaluation (QEE v2)

## Purpose
Produce the official pre-LoRA baseline for the math/code/aiml training-view pilot,
re-scoring the **exact same** inference run as baseline_eval_v0.1 (Phase 5A.1) with the
QEE v2 correctness engine instead of the v1 lexical/substring heuristics.

## Exactly the same as v0.1
- Base model: `Qwen/Qwen2.5-7B-Instruct`
- Inference: 4-bit NF4 double quant, bf16, greedy, `max_new_tokens=256`
- Evaluation samples: 29 (code 2 · math 13 · aiml 14)
- Dataset views: `output/training_views/{code,math,aiml}_300m_v0.1/eval.jsonl` (read-only)
- Hardware: NVIDIA GeForce RTX 5070 12GB (devpc Ubuntu-24.04), `.venv-eval`

## Changed vs v0.1
- Scoring engine: `scripts/evaluation_engine/v2/` (QEE v2) replaces
  `quality_score.py` substring heuristics.
- Answer-type dispatch is the authoritative training-view category
  (math / code / semantic) to avoid regex false-positives on math-heavy prose.
- Per-example `latency_s` and `tokens_per_sec` are now recorded.

## Determinism
Predicted responses reproduced the v0.1 run exactly: **29/29 (100%)**. The same
inference outputs are scored by both engines, so v0.1→v0.2 deltas reflect the
scoring engine change only.

## Results (overall, 29 samples)
| Metric | v0.1 | v0.2 |
|---|---|---|
| correctness | 0.0000 | **0.6112** |
| reasoning_quality | 1.0000 | 0.6911 |
| hallucination_rate | 0.0000 | **0.2949** |
| answer_format_consistency | 1.0000 | 1.0000 |
| latency (s/ex) | not recorded | 12.65 |
| tokens/sec | not recorded | 17.0 |

> v0.1 `correctness=0.0` was a substring-match artifact; v0.1 `hallucination=0.0` was a
> hardcoded default. **v0.2 is the new baseline reference** for Phase 5B LoRA deltas.

## Layout
```
experiments/baseline_eval_v0.2/
├── config.json
├── baseline_v2.json
├── per_example_results.jsonl
├── hardware_info.json
├── comparison_report.md
└── run_baseline_v2.py           # --rescore-only re-scores cached predictions
```

## GO / HOLD for Phase 5B
**GO to proceed to Phase 5B (LoRA pilot) using QEE v2 as the scorer**, with caveats:
- Re-score LoRA post-training output with the same v2 engine (apples-to-apples deltas).
- v2 correctness is **not** calibrated against a large human-review sample (Phase 5C) —
  it is not approved as an unsupervised release/approval gate.
- LoRA training itself remains a separate authorization; this report only establishes
  the baseline.

## Reproducibility
```bash
# full run (CUDA box):
.venv-eval/bin/python experiments/baseline_eval_v0.2/run_baseline_v2.py
# re-score cached predictions only (fast, no model load):
.venv-eval/bin/python experiments/baseline_eval_v0.2/run_baseline_v2.py --rescore-only
```