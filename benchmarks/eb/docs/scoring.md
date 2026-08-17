# EB Scoring

## Stage 3: Raw Score Foundation

Stage 3 implements the **raw evaluation layer** — deterministic scoring of individual task outputs. This is NOT the final benchmark score.

### Evaluator Hierarchy

For each task, evaluations are applied in this authority order:

1. **Deterministic evidence** (authority level 1) — exact match, syntax validation, evidence claims
2. **Reference/rubric evaluation** (authority level 2) — structured rubric with deterministic checks
3. **Cloud AI judge** (authority level 3) — provider-agnostic, multi-judge consensus (Stage 4+)
4. **AI opinion** (authority level 4) — not used in production benchmarks

A code solution that does not compile must not receive a high score merely because an AI judge likes its explanation.

### Evaluator Statuses

| Status | Meaning |
|--------|---------|
| `PASS` | Deterministic criteria satisfied |
| `FAIL` | Deterministic criteria not satisfied |
| `PARTIAL` | Meaningful progress but gate failed (LONG tasks only) |
| `NOT_APPLICABLE` | No configured evaluation target (e.g. no expected answer for exact) |
| `UNSUPPORTED` | Requires infrastructure not available (e.g. Docker sandbox) |
| `ERROR` | Evaluator crashed unexpectedly |
| `PENDING` | Partial result, some criteria incomplete |
| `PENDING_JUDGE` | Requires cloud judge model (Stage 4+) |

Non-PASS states are NOT collapsed into failure. Each is distinct and preserved in artifacts.

### LONG-Specific: SCORE vs OUTCOME vs QUALITY

For LONG tasks, the evaluator produces three distinct outputs:

| Concept | Source | Range | Role |
|---------|--------|-------|------|
| **SCORE** | `LongHorizonEvaluator` | [0.0, 1.0] | Authoritative benchmark score |
| **OUTCOME** | Gate rules on stage results | PASS/PARTIAL/FAIL/NOT_APPLICABLE | Terminal gate decision |
| **QUALITY** | `JudgeEvaluator` (cloud AI) | [0.0, 1.0] | Supplemental quality assessment |

**Authority hierarchy for LONG:**
1. `SCORE` is deterministic — computed from progress × 0.7 + terminal × 0.3 with modifiers
2. `OUTCOME` is gate-based — FAIL on terminal stage or adapter error; PASS only if all gates pass
3. `QUALITY` is model-judged — invoked only when OUTCOME is PASS or PARTIAL; skipped for FAIL/NOT_APPLICABLE
4. `LOW_AGREEMENT` is diagnostic — flagged when judge agreement is low, but never overrides SCORE

**Critical invariants:**
- Judge cannot downgrade PASS to FAIL on deterministic grounds
- `quality_score` never modifies `raw_task_score`
- `quality_score` never modifies `long_outcome`
- QUALITY is absent from details when OUTCOME is FAIL or NOT_APPLICABLE

### Raw Score vs EB Score

**Raw score** is the output of Stage 3:
- Computed per task from evaluator results
- Aggregated across repeats (mean, median, stddev, min, max, error %)
- Aggregated by capability (primary capability policy)
- Uses terminology: `raw_mean`, `raw_median`, `raw_stddev`, `raw_error_percent`
- Range: 0.0 to 1.0 per evaluator, aggregated by strategy

**EB Score** is computed in Stage 5+:
- Normalized so base model = 1000
- Formula: `round(1000 * model_raw_mean / base_model_raw_mean)`
- NOT implemented in Stage 3

Do NOT display raw scores as EB Scores. They are fundamentally different metrics.

### Aggregation Strategies

Multiple evaluator results per task combine via configurable strategy:

| Strategy | Behavior |
|----------|----------|
| `single_authoritative` | Use highest-authority applicable result |
| `weighted` | Weighted average by authority level |
| `all_required` | Minimum score across all evaluators (all must pass) |
| `any_required` | Maximum score across all evaluators (one pass is enough) |

Configured in `task.evaluation.aggregation.strategy`.

### Repeated Run Aggregation

```
task A
  repeat 1 → raw_score=0.8, status=PASS
  repeat 2 → raw_score=1.0, status=PASS
  repeat 3 → raw_score=0.9, status=PASS
  ↓
task-level aggregate:
  raw_mean = 0.9
  raw_median = 0.9
  raw_stddev = 0.1
  raw_error_percent = 11.1%
```

Repeat-level data is preserved in artifacts. Aggregation never overwrites individual repeats.

### Capability Aggregation

Tasks are attributed to capabilities via **primary capability** (first element of `task.capabilities`). Each capability aggregates its assigned tasks independently. A task with `capabilities: [ARCH, PLAN]` counts only under ARCH for aggregation purposes. This avoids double-counting.

### Artifact Structure (Stage 3)

```
outputs/runs/<run-id>/
  manifest.json        # Benchmark run manifest
  results.jsonl        # Per-task×repeat results with evaluator_results[] and raw_task_score
  raw_scores.json      # Aggregated raw scores (task-level + capability-level)
  run.json             # Run summary metadata
```

Each `results.jsonl` record contains:
- `task_id`, `run_id`, `raw_response`
- `evaluator_results[]` — all evaluator outputs preserved
- `raw_task_score` — aggregated score (or None if no applicable evaluators)
- `execution_metadata` — latency, tokens, settings, timestamps
- `flags` — diagnostic flags from evaluators
