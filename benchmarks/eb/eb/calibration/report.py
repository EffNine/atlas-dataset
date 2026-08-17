#!/usr/bin/env python3
"""
report.py — Calibration report generation and serialization.

Produces structured JSON reports containing:
  - Overall: reference samples, judge samples, comparable samples, MAE, agreement rate
  - Per dimension: sample count, MAE, agreement rate
  - Per fixture: fixture ID, outcome, judge eligibility, reference availability,
                 judge quality, reference quality, disagreement, flags
  - Metadata: fixture ID, fixture hash, calibration version, rubric version,
              judge model, provider, model version, prompt version, temperature,
              evaluation timestamp, evidence hash/version where available
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agreement import CalibrationReport
from .fixtures import CalibrationFixtureSet


REPORT_FILENAME = "long_judge_calibration_report.json"


def generate_report(
    fixture_set: CalibrationFixtureSet | None = None,
    output_path: Path | None = None,
    **analyzer_kwargs,
) -> CalibrationReport:
    """
    Generate a calibration report and optionally write it to disk.

    Args:
        fixture_set: Pre-loaded fixture set. If None, loads from defaults.
        output_path: Where to write the JSON report. If None, uses default path.
        **analyzer_kwargs: Passed to AgreementAnalyzer constructor.

    Returns:
        The generated CalibrationReport.
    """
    from .agreement import AgreementAnalyzer
    analyzer = AgreementAnalyzer(fixture_set=fixture_set, **analyzer_kwargs)
    report = analyzer.analyze()

    if output_path is None:
        output_path = (
            Path(__file__).resolve().parent.parent.parent.parent
            / "metadata" / "calibration" / REPORT_FILENAME
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

    return report


def load_report(report_path: Path) -> CalibrationReport:
    """Load a previously generated calibration report from disk."""
    with report_path.open() as f:
        data = json.load(f)

    from .agreement import CalibrationReport as ReportCls

    # Reconstruct dimension analysis
    dim_analysis = {}
    from .agreement import DimensionAgreement
    for dim_name, dim_data in data.get("dimension_analysis", {}).items():
        da = DimensionAgreement(dimension=dim_name)
        if "reference_scores" in dim_data:
            da.reference_scores = dim_data["reference_scores"]
        if "judge_scores" in dim_data:
            da.judge_scores = dim_data["judge_scores"]
        if "absolute_errors" in dim_data:
            da.absolute_errors = dim_data["absolute_errors"]
        if "categorical_agreements" in dim_data:
            da.categorical_agreements = dim_data["categorical_agreements"]
        dim_analysis[dim_name] = da

    return ReportCls(
        calibration_version=data["calibration_version"],
        rubric_version=data["rubric_version"],
        judge_model=data.get("judge_model"),
        provider=data.get("provider"),
        model_version=data.get("model_version"),
        prompt_version=data.get("prompt_version"),
        temperature=data.get("temperature", 0.0),
        evaluation_timestamp=data["evaluation_timestamp"],
        live_judge=data["live_judge"],
        reference_samples=data["overall"]["reference_samples"],
        judge_samples=data["overall"]["judge_samples"],
        comparable_samples=data["overall"]["comparable_samples"],
        overall_mae=data["overall"].get("mae"),
        overall_agreement_rate=data["overall"].get("agreement_rate"),
        low_agreement_count=data["overall"]["low_agreement_count"],
        dimension_analysis=dim_analysis,
        report_hash=data.get("report_hash", ""),
    )