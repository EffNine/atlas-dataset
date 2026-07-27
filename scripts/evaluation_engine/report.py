"""
report.py — Evaluation report generator.

Produces structured evaluation reports that conform to the
evaluation report specification (docs/specs/evaluation_report_spec.md).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class EvaluationReport:
    """Structured evaluation report builder.

    Generates reports conforming to the evaluation_report_spec.
    Reports are stored as JSON with an optional markdown summary.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()
        self._reports_dir = self._root / "docs" / "evaluation"
        self._reports_dir.mkdir(parents=True, exist_ok=True)

    def create_report(
        self,
        evaluation_id: str,
        model_id: str,
        dataset_version: str,
        benchmark_version: str,
        metrics: list[dict[str, Any]],
        failures: list[dict[str, Any]] | None = None,
        recommendations: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new evaluation report.

        Args:
            evaluation_id: Unique identifier for this evaluation run.
            model_id: Identifier for the model under evaluation (or 'none').
            dataset_version: Dataset version being evaluated.
            benchmark_version: Benchmark version used.
            metrics: List of metric results.
            failures: Optional list of failures encountered.
            recommendations: Optional list of recommendations.

        Returns:
            The complete report dict.
        """
        report: dict[str, Any] = {
            "evaluation_id": evaluation_id,
            "model_id": model_id,
            "dataset_version": dataset_version,
            "benchmark_version": benchmark_version,
            "metrics": metrics,
            "failures": failures or [],
            "recommendations": recommendations or [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reproducibility_hash": self._compute_hash(
                model_id, dataset_version, benchmark_version, metrics
            ),
        }
        return report

    def write_report(
        self, report: dict[str, Any], report_name: str | None = None
    ) -> Path:
        """Write an evaluation report to disk.

        Args:
            report: The report dict (from create_report).
            report_name: Optional filename stem (default: evaluation_id).

        Returns:
            The path to the written report file.
        """
        eid = report.get("evaluation_id", "unknown")
        name = report_name or eid
        path = self._reports_dir / f"{name}.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return path

    def render_markdown(self, report: dict[str, Any]) -> str:
        """Render an evaluation report as human-readable markdown.

        Args:
            report: The report dict.

        Returns:
            A markdown string.
        """
        lines = [
            f"# Evaluation Report: {report.get('evaluation_id', 'unknown')}",
            "",
            "## Metadata",
            "",
            "| Field | Value |",
            "|-------|-------|",
            f"| **Evaluation ID** | {report.get('evaluation_id', '?')} |",
            f"| **Model ID** | {report.get('model_id', '?')} |",
            f"| **Dataset Version** | {report.get('dataset_version', '?')} |",
            f"| **Benchmark Version** | {report.get('benchmark_version', '?')} |",
            f"| **Timestamp** | {report.get('timestamp', '?')} |",
            f"| **Reproducibility Hash** | `{report.get('reproducibility_hash', '?')[:16]}...` |",
            "",
            "## Metrics",
            "",
            "| Metric | Value | Status |",
            "|--------|-------|--------|",
        ]
        for m in report.get("metrics", []):
            val = m.get("value", "?")
            status = m.get("status", "?")
            mid = m.get("metric_id", "?")
            lines.append(f"| {mid} | {val} | {status} |")

        failures = report.get("failures", [])
        if failures:
            lines.extend(["", "## Failures", ""])
            for f in failures:
                lines.append(f"- {f.get('message', str(f))}")

        recs = report.get("recommendations", [])
        if recs:
            lines.extend(["", "## Recommendations", ""])
            for r in recs:
                lines.append(f"- {r}")

        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _compute_hash(
        model_id: str,
        dataset_version: str,
        benchmark_version: str,
        metrics: list[dict[str, Any]],
    ) -> str:
        payload = {
            "model_id": model_id,
            "dataset_version": dataset_version,
            "benchmark_version": benchmark_version,
            "metrics": metrics,
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
