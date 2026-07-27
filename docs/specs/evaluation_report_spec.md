# Evaluation Report Specification

This document defines the schema for Atlas evaluation reports. All evaluation
runs produce reports conforming to this specification.

## 1. Invariants

- Reports are **immutable** once written.
- Report fields must match the schema exactly; no extra top-level fields.
- The `reproducibility_hash` must be deterministic given the same inputs.
- Reports are written as JSON to `docs/evaluation/{evaluation_id}.json`.
- Markdown renderings are for human consumption only — the JSON is the source of truth.

## 2. Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `evaluation_id` | string | Unique identifier for this evaluation run. Format: `eval_{date}_{sequence}`. |
| `model_id` | string | Identifier for the model under evaluation. Use `"none"` for infrastructure-only evaluations. |
| `dataset_version` | string | Dataset version tag being evaluated (e.g. `"v0.1"`, `"v0.2"`). |
| `benchmark_version` | string | Benchmark version tag (e.g. `"1.0"`). |
| `metrics` | array | Array of metric result objects (see §3). |
| `failures` | array | Array of failure objects (see §4). May be empty. |
| `recommendations` | array | Array of recommendation strings. May be empty. |
| `timestamp` | string | ISO-8601 UTC timestamp of evaluation completion. |
| `reproducibility_hash` | string | SHA-256 hex digest over evaluation inputs and configuration. |

## 3. Metric Result Object

Each element in the `metrics` array has:

| Field | Type | Description |
|-------|------|-------------|
| `metric_id` | string | Unique metric identifier from the metric registry. |
| `name` | string | Human-readable metric name (optional). |
| `value` | number / string / null | The computed metric value. `null` if not yet computed. |
| `status` | string | One of: `"pass"`, `"fail"`, `"error"`, `"dry-run"`, `"not_implemented"`, `"computed"`. |
| `message` | string | Human-readable description or detail about the result. |

## 4. Failure Object

Each element in the `failures` array has:

| Field | Type | Description |
|-------|------|-------------|
| `stage` | string | Stage where the failure occurred (e.g. `"metric_evaluation"`, `"schema_validation"`). |
| `metric_id` | string | Metric being evaluated (or `"infrastructure"`). |
| `message` | string | Description of the failure. |
| `detail` | string | Optional detailed diagnostic information. |

## 5. Reproducibility Hash

The `reproducibility_hash` is computed as:

```
SHA-256(json.dumps({
    "model_id": ...,
    "dataset_version": ...,
    "benchmark_version": ...,
    "metrics": [sorted metric results],
}, sort_keys=True, ensure_ascii=False))
```

This ensures that identical inputs always produce identical hashes.

## 6. Report Storage

- JSON reports go to: `docs/evaluation/{evaluation_id}.json`
- Temporary evaluation state goes to: `tmp/eval_{session_id}/`
- Reports are never stored in `metadata/`, `curated/`, or `review_queue/`.

## 7. Related Documents

- Evaluation Framework: `docs/evaluation/atlas_evaluation_framework.md`
- Benchmark Registry: `metadata/benchmark_registry.json`
