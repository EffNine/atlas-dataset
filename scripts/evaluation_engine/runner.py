"""
runner.py — Evaluation Runner for Atlas Evaluation Engine.

Provides top-level evaluation job execution:
  - load benchmark registry
  - execute deterministic evaluation jobs
  - generate evaluation_result objects
  - produce reproducibility hash

Supports modes:
  atlas evaluate run --benchmark <id> --dry-run

All evaluation is read-only and network-free.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .metrics import MetricRegistry
from .registry import BenchmarkRegistry
from .report import EvaluationReport


# ---------------------------------------------------------------------------
# Evaluation result type
# ---------------------------------------------------------------------------

class EvaluationResult:
    """Canonical evaluation result object.

    Encapsulates the output of a single evaluation job with full
    provenance and reproducibility metadata.
    """

    def __init__(
        self,
        evaluation_id: str,
        benchmark_id: str,
        mode: str,
        dataset_version: str,
        records_evaluated: int,
        metrics: list[dict[str, Any]],
        failures: list[dict[str, Any]] | None = None,
        recommendations: list[str] | None = None,
    ) -> None:
        self.evaluation_id = evaluation_id
        self.benchmark_id = benchmark_id
        self.mode = mode
        self.dataset_version = dataset_version
        self.records_evaluated = records_evaluated
        self.metrics = metrics
        self.failures = failures or []
        self.recommendations = recommendations or []
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.reproducibility_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """Deterministic hash of evaluation configuration and results."""
        payload = {
            "evaluation_id": self.evaluation_id,
            "benchmark_id": self.benchmark_id,
            "mode": self.mode,
            "dataset_version": self.dataset_version,
            "records_evaluated": self.records_evaluated,
            "metrics": self.metrics,
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Convert to serializable dict for reporting."""
        return {
            "evaluation_id": self.evaluation_id,
            "benchmark_id": self.benchmark_id,
            "mode": self.mode,
            "dataset_version": self.dataset_version,
            "records_evaluated": self.records_evaluated,
            "metrics": self.metrics,
            "failures": self.failures,
            "recommendations": self.recommendations,
            "timestamp": self.timestamp,
            "reproducibility_hash": self.reproducibility_hash,
        }


# ---------------------------------------------------------------------------
# Evaluation Runner
# ---------------------------------------------------------------------------

class EvaluationRunner:
    """Deterministic evaluation job executor.

    Loads benchmark definitions, evaluates them against curated data
    using registered metrics, and produces evaluation_result objects.

    All operations are read-only. Network access is blocked.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        self._benchmark_registry = BenchmarkRegistry(self._root)
        self._metric_registry = MetricRegistry()
        self._report = EvaluationReport(self._root)

        # Ensure the evaluation reports directory exists
        self._reports_dir = self._root / "metadata" / "evaluation" / "reports"
        self._reports_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Benchmark operations
    # ------------------------------------------------------------------

    def list_benchmarks(self) -> list[dict[str, Any]]:
        """List all registered benchmarks."""
        return self._benchmark_registry.list_benchmarks()

    def get_benchmark(self, benchmark_id: str) -> dict[str, Any] | None:
        """Look up a benchmark by ID."""
        return self._benchmark_registry.get_benchmark(benchmark_id)

    # ------------------------------------------------------------------
    # Evaluation job execution
    # ------------------------------------------------------------------

    def run(
        self,
        benchmark_id: str,
        mode: str = "dry-run",
        dataset_version: str = "v0.2",
    ) -> EvaluationResult:
        """Execute an evaluation job.

        Args:
            benchmark_id: The benchmark to evaluate against.
            mode: 'dry-run' (no actual data scoring) or 'full' (execute).
            dataset_version: Dataset version to evaluate.

        Returns:
            An EvaluationResult with metrics, failures, and recommendations.
        """
        benchmark = self.get_benchmark(benchmark_id)
        if benchmark is None:
            raise ValueError(f"Unknown benchmark: {benchmark_id}")

        if mode not in ("dry-run", "full"):
            raise ValueError(f"Unknown mode: {mode}. Use 'dry-run' or 'full'.")

        # Load the curated dataset snapshot (read-only reference)
        dataset_records = self._load_curated_records(dataset_version)

        # Generate a deterministic evaluation ID
        eval_id = f"eval_{benchmark_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        # Execute metrics based on benchmark type
        if mode == "dry-run":
            metrics = self._execute_dry_run(benchmark, dataset_records)
            failures: list[dict[str, Any]] = []
            recommendations = ["Dry-run mode — no actual evaluation executed."]
        else:
            metrics = self._execute_full(benchmark, dataset_records)
            failures = self._collect_failures(metrics)
            recommendations = self._generate_recommendations(metrics)

        result = EvaluationResult(
            evaluation_id=eval_id,
            benchmark_id=benchmark_id,
            mode=mode,
            dataset_version=dataset_version,
            records_evaluated=len(dataset_records),
            metrics=metrics,
            failures=failures,
            recommendations=recommendations,
        )

        return result

    # ------------------------------------------------------------------
    # Dry-run execution (no actual scoring)
    # ------------------------------------------------------------------

    def _execute_dry_run(
        self,
        benchmark: dict[str, Any],
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Execute a dry-run: list available metrics without scoring.

        Returns metric stubs showing which metrics WOULD be computed.
        """
        benchmark_id = benchmark.get("benchmark_id", "unknown")
        metrics_list = self._metric_registry.list_metrics()

        dry_metrics = []
        for m in metrics_list:
            dry_metrics.append({
                "metric_id": m["metric_id"],
                "name": m["name"],
                "value": None,
                "status": "dry-run",
                "message": f"Dry-run — not executed for benchmark '{benchmark_id}'.",
            })

        return dry_metrics

    # ------------------------------------------------------------------
    # Full execution (actual metric computation)
    # ------------------------------------------------------------------

    def _execute_full(
        self,
        benchmark: dict[str, Any],
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Execute full evaluation: compute all applicable metrics."""
        benchmark_id = benchmark.get("benchmark_id", "unknown")
        metric_name = benchmark.get("metric", "unknown")

        results = []

        # Load the quality scores metric instance
        quality_metric = self._metric_registry.get("quality_score_agreement")
        if quality_metric:
            qs_result = quality_metric.compute(records=records)
            results.append(qs_result)

        # Provenance accuracy
        provenance_metric = self._metric_registry.get("provenance_accuracy")
        if provenance_metric:
            p_result = provenance_metric.compute(records=records)
            results.append(p_result)

        # Schema pass rate
        schema_metric = self._metric_registry.get("schema_pass_rate")
        if schema_metric:
            sp_result = schema_metric.compute(records=records)
            results.append(sp_result)

        # Content safety rate
        safety_metric = self._metric_registry.get("content_safety_rate")
        if safety_metric:
            cs_result = safety_metric.compute(records=records)
            results.append(cs_result)

        # Determinism score
        det_metric = self._metric_registry.get("determinism_score")
        if det_metric:
            det_result = det_metric.compute(records=records)
            results.append(det_result)

        # Reproducibility hash
        repro_metric = self._metric_registry.get("reproducibility_hash")
        if repro_metric:
            hash_input = {
                "benchmark_id": benchmark_id,
                "dataset_version": "v0.2",
                "record_count": len(records),
                "metric_name": metric_name,
            }
            repro_result = repro_metric.compute(**hash_input)
            results.append(repro_result)

        # Quality distribution metrics (mean, distribution, category averages)
        quality_results = self._compute_quality_metrics(records)
        results.extend(quality_results)

        # Review alignment metrics (agreement, disagreement, accuracy)
        review_results = self._compute_review_alignment_metrics()
        results.extend(review_results)

        # Provenance metrics (source validity, license pass rate)
        prov_results = self._compute_provenance_metrics(records)
        results.extend(prov_results)

        return results

    # ------------------------------------------------------------------
    # Quality metrics computation
    # ------------------------------------------------------------------

    def _compute_quality_metrics(
        self, records: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Compute quality score distribution metrics."""
        if not records:
            return []

        quality_scores = [r.get("quality_score", 0) for r in records]
        valid_scores = [s for s in quality_scores if isinstance(s, (int, float))]

        if not valid_scores:
            return []

        mean_score = sum(valid_scores) / len(valid_scores)

        # Score distribution
        from collections import Counter
        dist = Counter(valid_scores)
        score_dist = {str(k): v for k, v in sorted(dist.items())}

        # Category averages
        from collections import defaultdict
        cat_scores: dict[str, list[int]] = defaultdict(list)
        for r in records:
            cat = r.get("category", "unknown")
            qs = r.get("quality_score")
            if isinstance(qs, (int, float)):
                cat_scores[cat].append(int(qs))

        cat_avgs = {}
        for cat, scores in sorted(cat_scores.items()):
            cat_avgs[cat] = round(sum(scores) / len(scores), 2) if scores else 0.0

        return [
            {
                "metric_id": "quality_mean_score",
                "name": "Quality Mean Score",
                "value": round(mean_score, 2),
                "status": "computed",
                "detail": f"Mean quality_score across {len(valid_scores)} records: {mean_score:.2f}",
            },
            {
                "metric_id": "quality_score_distribution",
                "name": "Quality Score Distribution",
                "value": score_dist,
                "status": "computed",
                "detail": f"Distribution across {len(score_dist)} distinct scores",
            },
            {
                "metric_id": "quality_category_average",
                "name": "Quality Category Average",
                "value": cat_avgs,
                "status": "computed",
                "detail": f"Averages across {len(cat_avgs)} categories",
            },
        ]

    # ------------------------------------------------------------------
    # Review alignment metrics
    # ------------------------------------------------------------------

    def _compute_review_alignment_metrics(self) -> list[dict[str, Any]]:
        """Compute agreement between QEE scores and human scores."""
        # Load quality reviews
        reviews_path = self._root / "review" / "quality_reviews.jsonl"
        if not reviews_path.exists():
            return [
                {
                    "metric_id": "review_agreement_rate",
                    "name": "Review Agreement Rate",
                    "value": None,
                    "status": "not_available",
                    "detail": "Review data not found",
                },
                {
                    "metric_id": "review_disagreement_count",
                    "name": "Review Disagreement Count",
                    "value": None,
                    "status": "not_available",
                    "detail": "Review data not found",
                },
                {
                    "metric_id": "review_approval_prediction_accuracy",
                    "name": "Review Approval Prediction Accuracy",
                    "value": None,
                    "status": "not_available",
                    "detail": "Review data not found",
                },
            ]

        reviews = []
        with open(reviews_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    import json
                    reviews.append(json.loads(line))

        # Load curated records for QEE scores
        curated_path = self._root / "curated" / "v0.2" / "data" / "v0.2_full.jsonl"
        curated_records = {}
        if curated_path.exists():
            with open(curated_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        import json
                        r = json.loads(line)
                        curated_records[r["id"]] = r

        # Match reviews to curated records
        matched = []
        for rev in reviews:
            rid = rev.get("record_id", "")
            if rid in curated_records:
                qee_score = curated_records[rid].get("quality_score")
                human_score = int(rev.get("human_score", 0))
                if isinstance(qee_score, (int, float)):
                    matched.append({
                        "qee_score": qee_score,
                        "human_score": human_score,
                        "verdict": rev.get("verdict", ""),
                    })

        if not matched:
            return [
                {
                    "metric_id": "review_agreement_rate",
                    "name": "Review Agreement Rate",
                    "value": 0.0,
                    "status": "computed",
                    "detail": "No matched records found for alignment analysis",
                },
                {
                    "metric_id": "review_disagreement_count",
                    "name": "Review Disagreement Count",
                    "value": 0,
                    "status": "computed",
                    "detail": "No matched records found for alignment analysis",
                },
                {
                    "metric_id": "review_approval_prediction_accuracy",
                    "name": "Review Approval Prediction Accuracy",
                    "value": 0.0,
                    "status": "computed",
                    "detail": "No matched records found for alignment analysis",
                },
            ]

        # Compute agreement: within 1 point = agreement
        agreements = sum(1 for m in matched if abs(m["qee_score"] - m["human_score"]) <= 1)
        agreement_rate = round(agreements / len(matched), 4)

        disagreements = sum(1 for m in matched if abs(m["qee_score"] - m["human_score"]) > 1)
        disagreement_count = disagreements

        # Approval prediction: QEE >= 7 predicts approval
        approvals_predicted = sum(
            1 for m in matched
            if m["qee_score"] >= 7 and m["verdict"] == "approve"
        )
        approvals_total = sum(1 for m in matched if m["verdict"] == "approve")
        approval_prediction_accuracy = round(
            approvals_predicted / approvals_total, 4
        ) if approvals_total > 0 else 0.0

        return [
            {
                "metric_id": "review_agreement_rate",
                "name": "Review Agreement Rate",
                "value": agreement_rate,
                "status": "computed",
                "detail": f"Agreement (within 1 point): {agreements}/{len(matched)} = {agreement_rate:.2%}",
            },
            {
                "metric_id": "review_disagreement_count",
                "name": "Review Disagreement Count",
                "value": disagreement_count,
                "status": "computed",
                "detail": f"Disagreements (>1 point): {disagreement_count}/{len(matched)}",
            },
            {
                "metric_id": "review_approval_prediction_accuracy",
                "name": "Review Approval Prediction Accuracy",
                "value": approval_prediction_accuracy,
                "status": "computed",
                "detail": f"Approvals correctly predicted: {approvals_predicted}/{approvals_total} = {approval_prediction_accuracy:.2%}",
            },
        ]

    # ------------------------------------------------------------------
    # Provenance metrics
    # ------------------------------------------------------------------

    def _compute_provenance_metrics(
        self, records: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Compute provenance-related metrics."""
        if not records:
            return [
                {
                    "metric_id": "provenance_valid_source_rate",
                    "name": "Valid Source Rate",
                    "value": 0.0,
                    "status": "computed",
                    "detail": "No records available",
                },
                {
                    "metric_id": "provenance_license_pass_rate",
                    "name": "License Pass Rate",
                    "value": 0.0,
                    "status": "computed",
                    "detail": "No records available",
                },
            ]

        from atlas_constants import is_denied_license

        # Valid source: record has source_attribution with source_id
        source_count = sum(
            1 for r in records
            if r.get("source_attribution") and r["source_attribution"].get("source_id")
        )
        valid_source_rate = round(source_count / len(records), 4)

        # License pass: not a denied license
        license_pass_count = sum(
            1 for r in records
            if not is_denied_license(r.get("license", ""))
        )
        license_pass_rate = round(license_pass_count / len(records), 4)

        return [
            {
                "metric_id": "provenance_valid_source_rate",
                "name": "Valid Source Rate",
                "value": valid_source_rate,
                "status": "computed",
                "detail": f"Records with source_attribution: {source_count}/{len(records)} = {valid_source_rate:.2%}",
            },
            {
                "metric_id": "provenance_license_pass_rate",
                "name": "License Pass Rate",
                "value": license_pass_rate,
                "status": "computed",
                "detail": f"Records with passing license: {license_pass_count}/{len(records)} = {license_pass_rate:.2%}",
            },
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_curated_records(
        self, dataset_version: str = "v0.2"
    ) -> list[dict[str, Any]]:
        """Load curated records for the given version (read-only)."""
        curated_dir = self._root / "curated" / dataset_version / "data"
        if not curated_dir.exists():
            return []

        records: list[dict[str, Any]] = []
        for jsonl_file in sorted(curated_dir.glob("*.jsonl")):
            with open(jsonl_file) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        import json
                        records.append(json.loads(line))

        return records

    def _collect_failures(
        self, metrics: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Collect metrics with non-passing status as failures."""
        failures = []
        for m in metrics:
            status = m.get("status", "")
            if status in ("not_available", "error", "failed"):
                failures.append({
                    "metric_id": m.get("metric_id", "unknown"),
                    "status": status,
                    "message": m.get("detail", "Unknown failure"),
                })
        return failures

    def _generate_recommendations(
        self, metrics: list[dict[str, Any]]
    ) -> list[str]:
        """Generate recommendations based on metric results."""
        recs = []
        for m in metrics:
            mid = m.get("metric_id", "")
            status = m.get("status", "")
            if status == "not_available":
                recs.append(f"Missing data for metric '{mid}': provide required input data.")
            elif status == "error":
                recs.append(f"Metric '{mid}' encountered an error during computation.")
        if not recs:
            recs.append("All metrics computed successfully. No issues detected.")
        return recs

    # ------------------------------------------------------------------
    # Report operations
    # ------------------------------------------------------------------

    def write_report(self, result: EvaluationResult) -> Path:
        """Write an evaluation result as a report file."""
        report_path = self._reports_dir / f"evaluation_{result.evaluation_id}.json"
        report_path.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return report_path

    def get_report_path(self, evaluation_id: str) -> Path | None:
        """Resolve a report path by evaluation ID."""
        candidate = self._reports_dir / f"evaluation_{evaluation_id}.json"
        if candidate.exists():
            return candidate
        # Try glob for partial match
        for fp in sorted(self._reports_dir.glob("*.json")):
            if evaluation_id in fp.name:
                return fp
        return None

    def list_reports(self) -> list[dict[str, Any]]:
        """List all completed evaluation reports."""
        reports = []
        for fp in sorted(self._reports_dir.glob("*.json")):
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
                reports.append({
                    "evaluation_id": data.get("evaluation_id", fp.stem),
                    "benchmark_id": data.get("benchmark_id", "?"),
                    "mode": data.get("mode", "?"),
                    "dataset_version": data.get("dataset_version", "?"),
                    "records_evaluated": data.get("records_evaluated", 0),
                    "hash": data.get("reproducibility_hash", "")[:16],
                    "timestamp": data.get("timestamp", "?"),
                    "path": str(fp.relative_to(self._root)),
                })
            except (json.JSONDecodeError, KeyError):
                reports.append({
                    "evaluation_id": fp.stem,
                    "error": "unparseable",
                    "path": str(fp.relative_to(self._root)),
                })
        return reports

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify_artifact(self, evaluation_id: str) -> dict[str, Any]:
        """Verify the integrity of an evaluation artifact.

        Checks:
          - Report file exists
          - JSON is parseable
          - Reproducibility hash matches recomputed value
          - Required fields present
        """
        from .report import EvaluationReport

        path = self.get_report_path(evaluation_id)
        if path is None:
            return {
                "evaluation_id": evaluation_id,
                "exists": False,
                "valid": False,
                "errors": ["Report file not found"],
            }

        try:
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return {
                "evaluation_id": evaluation_id,
                "exists": True,
                "valid": False,
                "errors": [f"JSON parse error: {e}"],
            }

        # Check required fields
        required_fields = {
            "evaluation_id", "benchmark_id", "mode", "dataset_version",
            "records_evaluated", "metrics", "reproducibility_hash", "timestamp",
        }
        missing = required_fields - set(data.keys())
        if missing:
            return {
                "evaluation_id": evaluation_id,
                "exists": True,
                "valid": False,
                "errors": [f"Missing fields: {missing}"],
            }

        # Recompute hash
        payload = {
            "evaluation_id": data.get("evaluation_id"),
            "benchmark_id": data.get("benchmark_id"),
            "mode": data.get("mode"),
            "dataset_version": data.get("dataset_version"),
            "records_evaluated": data.get("records_evaluated"),
            "metrics": data.get("metrics"),
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        expected_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        actual_hash = data.get("reproducibility_hash", "")

        hash_match = expected_hash == actual_hash

        return {
            "evaluation_id": evaluation_id,
            "exists": True,
            "valid": hash_match,
            "hash_expected": expected_hash[:16],
            "hash_actual": actual_hash[:16],
            "hash_match": hash_match,
            "errors": [] if hash_match else ["Reproducibility hash mismatch"],
        }
