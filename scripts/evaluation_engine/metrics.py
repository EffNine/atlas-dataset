"""
metrics.py — Metric definitions for Atlas evaluation.

Extends the Phase 5A base with concrete metric implementations for:
  - Quality: mean_score, score_distribution, category_average
  - Review alignment: agreement_rate, disagreement_count, approval_prediction_accuracy
  - Provenance: valid_source_rate, license_pass_rate

All metrics are deterministic, read-only, and stateless.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


class BaseMetric(ABC):
    """Abstract base for all evaluation metrics."""

    def __init__(self, metric_id: str, name: str, description: str) -> None:
        self.metric_id = metric_id
        self.name = name
        self.description = description

    @abstractmethod
    def compute(self, **kwargs: Any) -> dict[str, Any]:
        """Compute the metric value.

        Returns:
            A dict with at minimum {'metric_id', 'value', 'status'}.
            Additional fields depend on the specific metric.
        """
        ...

    def __repr__(self) -> str:
        return f"<{type(self).__name__} id={self.metric_id}>"


# ---------------------------------------------------------------------------
# Quality Metrics
# ---------------------------------------------------------------------------

class QualityScoreAgreement(BaseMetric):
    """Measure agreement between quality scores and expected baselines."""

    def __init__(self) -> None:
        super().__init__(
            metric_id="quality_score_agreement",
            name="Quality Score Agreement",
            description="Measure agreement between computed quality scores and baseline expectations.",
        )

    def compute(self, **kwargs: Any) -> dict[str, Any]:
        records = kwargs.get("records")
        if not records:
            return {
                "metric_id": self.metric_id,
                "value": 0.0,
                "status": "not_implemented",
                "message": "No records provided for quality score agreement evaluation.",
            }

        quality_scores = [r.get("quality_score", 0) for r in records]
        valid_scores = [s for s in quality_scores if isinstance(s, (int, float))]

        if not valid_scores:
            return {
                "metric_id": self.metric_id,
                "value": 0.0,
                "status": "not_implemented",
                "message": "No valid quality_scores found in records.",
            }

        # Baseline: score >= 7 is the accept threshold
        threshold = 7
        above = sum(1 for s in valid_scores if s >= threshold)
        agreement_rate = round(above / len(valid_scores), 4)

        return {
            "metric_id": self.metric_id,
            "value": agreement_rate,
            "status": "computed",
            "message": (
                f"Quality score agreement (threshold >= {threshold}): "
                f"{above}/{len(valid_scores)} = {agreement_rate:.2%}"
            ),
            "threshold": threshold,
            "above_threshold": above,
            "total_valid": len(valid_scores),
        }


class QualityMeanScore(BaseMetric):
    """Compute the mean quality score across records."""

    def __init__(self) -> None:
        super().__init__(
            metric_id="quality_mean_score",
            name="Quality Mean Score",
            description="Mean quality_score across all evaluated records.",
        )

    def compute(self, **kwargs: Any) -> dict[str, Any]:
        records = kwargs.get("records")
        if not records:
            return {"metric_id": self.metric_id, "value": 0.0, "status": "not_available", "message": "No records."}

        scores = [r.get("quality_score", 0) for r in records if isinstance(r.get("quality_score"), (int, float))]
        if not scores:
            return {"metric_id": self.metric_id, "value": 0.0, "status": "not_available", "message": "No valid scores."}

        mean = round(sum(scores) / len(scores), 2)
        return {
            "metric_id": self.metric_id,
            "value": mean,
            "status": "computed",
            "message": f"Mean quality_score: {mean} (n={len(scores)})",
            "record_count": len(scores),
        }


class QualityScoreDistribution(BaseMetric):
    """Compute the distribution of quality scores."""

    def __init__(self) -> None:
        super().__init__(
            metric_id="quality_score_distribution",
            name="Quality Score Distribution",
            description="Distribution of quality scores across evaluated records.",
        )

    def compute(self, **kwargs: Any) -> dict[str, Any]:
        records = kwargs.get("records")
        if not records:
            return {"metric_id": self.metric_id, "value": {}, "status": "not_available", "message": "No records."}

        scores = [r.get("quality_score", 0) for r in records if isinstance(r.get("quality_score"), (int, float))]
        dist = dict(sorted(Counter(scores).items()))

        return {
            "metric_id": self.metric_id,
            "value": dist,
            "status": "computed",
            "message": f"Distribution: {dist}",
            "record_count": len(scores),
        }


class QualityCategoryAverage(BaseMetric):
    """Compute average quality score per category."""

    def __init__(self) -> None:
        super().__init__(
            metric_id="quality_category_average",
            name="Quality Category Average",
            description="Average quality_score per category.",
        )

    def compute(self, **kwargs: Any) -> dict[str, Any]:
        records = kwargs.get("records")
        if not records:
            return {"metric_id": self.metric_id, "value": {}, "status": "not_available", "message": "No records."}

        cat_scores: dict[str, list[int]] = defaultdict(list)
        for r in records:
            cat = r.get("category", "unknown")
            qs = r.get("quality_score")
            if isinstance(qs, (int, float)):
                cat_scores[cat].append(int(qs))

        avgs = {}
        for cat, scores in sorted(cat_scores.items()):
            avgs[cat] = round(sum(scores) / len(scores), 2) if scores else 0.0

        return {
            "metric_id": self.metric_id,
            "value": avgs,
            "status": "computed",
            "message": f"Category averages computed for {len(avgs)} categories",
        }


# ---------------------------------------------------------------------------
# Review Alignment Metrics
# ---------------------------------------------------------------------------

class ReviewAgreementRate(BaseMetric):
    """Measure agreement rate between QEE scores and human review scores."""

    def __init__(self) -> None:
        super().__init__(
            metric_id="review_agreement_rate",
            name="Review Agreement Rate",
            description="Fraction of reviews where QEE score agrees with human score (within 1 point).",
        )

    def compute(self, **kwargs: Any) -> dict[str, Any]:
        reviews = kwargs.get("reviews", [])
        curated = kwargs.get("curated_records", {})

        if not reviews or not curated:
            return {
                "metric_id": self.metric_id,
                "value": 0.0,
                "status": "not_available",
                "message": "Review data or curated records not provided.",
            }

        matched = []
        for rev in reviews:
            rid = rev.get("record_id", "")
            if rid in curated:
                qee = curated[rid].get("quality_score")
                human = int(rev.get("human_score", 0))
                if isinstance(qee, (int, float)):
                    matched.append((qee, human, rev.get("verdict", "")))

        if not matched:
            return {"metric_id": self.metric_id, "value": 0.0, "status": "computed", "message": "No matched records."}

        agreements = sum(1 for q, h, v in matched if abs(q - h) <= 1)
        rate = round(agreements / len(matched), 4)

        return {
            "metric_id": self.metric_id,
            "value": rate,
            "status": "computed",
            "message": f"Agreement (within 1 point): {agreements}/{len(matched)} = {rate:.2%}",
            "agreed": agreements,
            "total": len(matched),
        }


class ReviewDisagreementCount(BaseMetric):
    """Count disagreements between QEE and human scores."""

    def __init__(self) -> None:
        super().__init__(
            metric_id="review_disagreement_count",
            name="Review Disagreement Count",
            description="Number of records where QEE score differs from human score by more than 1 point.",
        )

    def compute(self, **kwargs: Any) -> dict[str, Any]:
        reviews = kwargs.get("reviews", [])
        curated = kwargs.get("curated_records", {})

        if not reviews or not curated:
            return {
                "metric_id": self.metric_id,
                "value": 0,
                "status": "not_available",
                "message": "Review data or curated records not provided.",
            }

        disagreements = []
        for rev in reviews:
            rid = rev.get("record_id", "")
            if rid in curated:
                qee = curated[rid].get("quality_score")
                human = int(rev.get("human_score", 0))
                if isinstance(qee, (int, float)) and abs(qee - human) > 1:
                    disagreements.append({
                        "record_id": rid,
                        "qee_score": qee,
                        "human_score": human,
                        "verdict": rev.get("verdict", ""),
                        "diff": qee - human,
                    })

        return {
            "metric_id": self.metric_id,
            "value": len(disagreements),
            "status": "computed",
            "message": f"Disagreements (>1 point): {len(disagreements)}",
            "disagreements": disagreements,
        }


class ReviewApprovalPredictionAccuracy(BaseMetric):
    """Measure how accurately QEE scores predict human approval decisions."""

    def __init__(self) -> None:
        super().__init__(
            metric_id="review_approval_prediction_accuracy",
            name="Review Approval Prediction Accuracy",
            description="Fraction of approvals correctly predicted (QEE >= 7 predicting verdict='approve').",
        )

    def compute(self, **kwargs: Any) -> dict[str, Any]:
        reviews = kwargs.get("reviews", [])
        curated = kwargs.get("curated_records", {})

        if not reviews or not curated:
            return {
                "metric_id": self.metric_id,
                "value": 0.0,
                "status": "not_available",
                "message": "Review data or curated records not provided.",
            }

        matched = []
        for rev in reviews:
            rid = rev.get("record_id", "")
            if rid in curated:
                qee = curated[rid].get("quality_score")
                human = int(rev.get("human_score", 0))
                if isinstance(qee, (int, float)):
                    matched.append((qee, rev.get("verdict", "")))

        if not matched:
            return {"metric_id": self.metric_id, "value": 0.0, "status": "computed", "message": "No matched records."}

        threshold = 7
        approvals = [(q, v) for q, v in matched if v == "approve"]
        correct = sum(1 for q, v in approvals if q >= threshold)
        accuracy = round(correct / len(approvals), 4) if approvals else 0.0

        # Also compute false positives (QEE >= 7 but not approved)
        false_positives = [(q, v) for q, v in matched if q >= threshold and v != "approve"]

        return {
            "metric_id": self.metric_id,
            "value": accuracy,
            "status": "computed",
            "message": f"Approval prediction accuracy: {correct}/{len(approvals)} = {accuracy:.2%}",
            "correct_predictions": correct,
            "total_approvals": len(approvals),
            "false_positives": len(false_positives),
            "threshold": threshold,
        }


# ---------------------------------------------------------------------------
# Provenance Metrics
# ---------------------------------------------------------------------------

class ProvenanceValidSourceRate(BaseMetric):
    """Measure the fraction of records with valid source attribution."""

    def __init__(self) -> None:
        super().__init__(
            metric_id="provenance_valid_source_rate",
            name="Valid Source Rate",
            description="Fraction of records with valid source_attribution and source_id.",
        )

    def compute(self, **kwargs: Any) -> dict[str, Any]:
        records = kwargs.get("records")
        if not records:
            return {"metric_id": self.metric_id, "value": 0.0, "status": "not_available", "message": "No records."}

        valid = sum(
            1 for r in records
            if r.get("source_attribution") and r["source_attribution"].get("source_id")
        )
        rate = round(valid / len(records), 4) if records else 0.0

        return {
            "metric_id": self.metric_id,
            "value": rate,
            "status": "computed",
            "message": f"Valid source: {valid}/{len(records)} = {rate:.2%}",
            "valid_count": valid,
            "total": len(records),
        }


class ProvenanceLicensePassRate(BaseMetric):
    """Measure the fraction of records passing license policy."""

    def __init__(self) -> None:
        super().__init__(
            metric_id="provenance_license_pass_rate",
            name="License Pass Rate",
            description="Fraction of records with licenses passing the Atlas commercial-safety gate.",
        )

    def compute(self, **kwargs: Any) -> dict[str, Any]:
        records = kwargs.get("records")
        if not records:
            return {"metric_id": self.metric_id, "value": 0.0, "status": "not_available", "message": "No records."}

        try:
            from atlas_constants import is_denied_license
        except ImportError:
            # Fallback if atlas_constants not importable
            from ..atlas_constants import is_denied_license  # type: ignore[import]

        passing = sum(1 for r in records if not is_denied_license(r.get("license", "")))
        rate = round(passing / len(records), 4) if records else 0.0

        return {
            "metric_id": self.metric_id,
            "value": rate,
            "status": "computed",
            "message": f"License pass rate: {passing}/{len(records)} = {rate:.2%}",
            "pass_count": passing,
            "total": len(records),
        }


class ProvenanceAccuracy(BaseMetric):
    """Verify source attribution integrity and completeness."""

    def __init__(self) -> None:
        super().__init__(
            metric_id="provenance_accuracy",
            name="Provenance Accuracy",
            description="Verify source attribution integrity and provenance chain completeness.",
        )

    def compute(self, **kwargs: Any) -> dict[str, Any]:
        records = kwargs.get("records")
        if not records:
            return {"metric_id": self.metric_id, "value": 0.0, "status": "not_available", "message": "No records."}

        # Check: has source_attribution with source_id, license, and name
        complete = 0
        for r in records:
            sa = r.get("source_attribution", {})
            if (
                sa.get("source_id")
                and sa.get("license")
                and sa.get("name")
                and r.get("license")
            ):
                complete += 1

        accuracy = round(complete / len(records), 4) if records else 0.0

        return {
            "metric_id": self.metric_id,
            "value": accuracy,
            "status": "computed",
            "message": (
                f"Provenance accuracy: {complete}/{len(records)} = {accuracy:.2%} "
                f"records with complete source attribution"
            ),
            "complete_count": complete,
            "total": len(records),
        }


# ---------------------------------------------------------------------------
# Schema & Safety Metrics
# ---------------------------------------------------------------------------

class SchemaPassRate(BaseMetric):
    """Measure schema compliance of knowledge objects."""

    def __init__(self) -> None:
        super().__init__(
            metric_id="schema_pass_rate",
            name="Schema Pass Rate",
            description="Fraction of knowledge objects that pass canonical schema validation.",
        )

    def compute(self, **kwargs: Any) -> dict[str, Any]:
        records = kwargs.get("records")
        if not records:
            return {"metric_id": self.metric_id, "value": 0.0, "status": "not_available", "message": "No records."}

        required = {
            "id", "category", "subcategory", "difficulty", "knowledge_type",
            "canonical_answer", "metadata", "source_attribution", "license",
            "quality_score", "verification_status", "messages", "lineage",
        }

        passed = sum(1 for r in records if required.issubset(r.keys()))
        rate = round(passed / len(records), 4) if records else 0.0

        return {
            "metric_id": self.metric_id,
            "value": rate,
            "status": "computed",
            "message": f"Schema pass rate: {passed}/{len(records)} = {rate:.2%}",
            "passed": passed,
            "total": len(records),
        }


class ContentSafetyRate(BaseMetric):
    """Measure content safety compliance."""

    def __init__(self) -> None:
        super().__init__(
            metric_id="content_safety_rate",
            name="Content Safety Rate",
            description="Fraction of objects passing content safety checks.",
        )

    def compute(self, **kwargs: Any) -> dict[str, Any]:
        records = kwargs.get("records")
        if not records:
            return {"metric_id": self.metric_id, "value": 0.0, "status": "not_available", "message": "No records."}

        # Content safety pass criteria: verification_status != 'rejected',
        # no known hallucination markers, license is not denied.
        try:
            from atlas_constants import is_denied_license
        except ImportError:
            from ..atlas_constants import is_denied_license  # type: ignore[import]

        safe = 0
        for r in records:
            vs = r.get("verification_status", "pending")
            lic = r.get("license", "")
            if vs != "rejected" and not is_denied_license(lic):
                safe += 1

        rate = round(safe / len(records), 4) if records else 0.0

        return {
            "metric_id": self.metric_id,
            "value": rate,
            "status": "computed",
            "message": f"Content safety rate: {safe}/{len(records)} = {rate:.2%}",
            "safe": safe,
            "total": len(records),
        }


class HallucinationRiskScore(BaseMetric):
    """Assess hallucination risk based on source attribution."""

    def __init__(self) -> None:
        super().__init__(
            metric_id="hallucination_risk_score",
            name="Hallucination Risk Score",
            description="Fraction of records lacking verifiable source attribution (higher = riskier).",
        )

    def compute(self, **kwargs: Any) -> dict[str, Any]:
        records = kwargs.get("records")
        if not records:
            return {"metric_id": self.metric_id, "value": 0.0, "status": "not_available", "message": "No records."}

        # Risk if no source_attribution with a URL or named source
        risky = 0
        for r in records:
            sa = r.get("source_attribution", {})
            if not sa.get("source_id") or (not sa.get("url") and not sa.get("name")):
                risky += 1

        risk = round(risky / len(records), 4) if records else 0.0

        return {
            "metric_id": self.metric_id,
            "value": risk,
            "status": "computed",
            "message": f"Hallucination risk: {risky}/{len(records)} = {risk:.2%}",
            "risky_count": risky,
            "total": len(records),
        }


# ---------------------------------------------------------------------------
# Engineering Metrics
# ---------------------------------------------------------------------------

class DeterminismScore(BaseMetric):
    """Verify that evaluation produces identical results given identical inputs."""

    def __init__(self) -> None:
        super().__init__(
            metric_id="determinism_score",
            name="Determinism Score",
            description="Verify evaluation determinism across identical runs.",
        )

    def compute(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "value": 1.0,
            "status": "not_implemented",
            "message": "Determinism evaluation requires running the same evaluation twice.",
        }


class ReproducibilityHash(BaseMetric):
    """Compute a hash over evaluation inputs for reproducibility verification."""

    def __init__(self) -> None:
        super().__init__(
            metric_id="reproducibility_hash",
            name="Reproducibility Hash",
            description="Hash of evaluation configuration and inputs for run matching.",
        )

    def compute(self, **metadata: Any) -> dict[str, Any]:
        sorted_json = json.dumps(metadata, sort_keys=True, ensure_ascii=False)
        h = hashlib.sha256(sorted_json.encode("utf-8")).hexdigest()
        return {
            "metric_id": self.metric_id,
            "value": h,
            "status": "computed",
            "message": f"Reproducibility hash: {h[:16]}...",
        }


# ---------------------------------------------------------------------------
# Metric Registry
# ---------------------------------------------------------------------------


class MetricRegistry:
    """Registry of available evaluation metrics.

    Provides lookup and instantiation of metric implementations.
    Metrics are stateless singletons managed by the registry.
    """

    def __init__(self) -> None:
        self._metrics: dict[str, BaseMetric] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        defaults: list[BaseMetric] = [
            # Phase 5A base metrics
            QualityScoreAgreement(),
            ProvenanceAccuracy(),
            SchemaPassRate(),
            ContentSafetyRate(),
            DeterminismScore(),
            ReproducibilityHash(),
            # Phase 5B quality metrics
            QualityMeanScore(),
            QualityScoreDistribution(),
            QualityCategoryAverage(),
            # Phase 5B review alignment metrics
            ReviewAgreementRate(),
            ReviewDisagreementCount(),
            ReviewApprovalPredictionAccuracy(),
            # Phase 5B provenance metrics
            ProvenanceValidSourceRate(),
            ProvenanceLicensePassRate(),
            # Safety extensions
            HallucinationRiskScore(),
        ]
        for m in defaults:
            self._metrics[m.metric_id] = m

    def register(self, metric: BaseMetric) -> None:
        """Register a custom metric.

        Args:
            metric: A BaseMetric instance.
        """
        self._metrics[metric.metric_id] = metric

    def get(self, metric_id: str) -> BaseMetric | None:
        """Retrieve a metric by ID.

        Args:
            metric_id: The metric identifier.

        Returns:
            The metric instance, or None if not found.
        """
        return self._metrics.get(metric_id)

    def list_metrics(self) -> list[dict[str, str]]:
        """List all registered metrics.

        Returns:
            A list of metric metadata dicts.
        """
        return [
            {
                "metric_id": m.metric_id,
                "name": m.name,
                "description": m.description,
            }
            for m in self._metrics.values()
        ]
