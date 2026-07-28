#!/usr/bin/env python3
"""Quality agent — placeholder for automated quality assessment integration.

In future phases, this agent will integrate with:
  - quality_score.py (existing heuristic scorer)
  - calibrate_quality.py (calibration against human review)
  - Quality calibration baselines (frozen calibration data)

For v1, the agent validates that quality scores are present and within range,
and reports summary statistics.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base_agent import BaseAgent, AgentResult, AgentStatus


class QualityAgent(BaseAgent):
    """Placeholder quality assessment agent for v1.

    Checks that quality scores exist and are within the valid range (0-10).
    In future versions, this agent will run the full quality scoring pipeline.

    Args:
        root: Path to the atlas-dataset repository root.
        config: Optional dict with keys:
            - curated_path: Path to curated dataset JSONL.
            - min_score: Minimum acceptable quality score (default: 7).
            - check_pilot: If True, check pilot_candidates (default: True).
    """

    name: str = "quality_agent"
    description: str = "Validates quality scores on curated records"

    def __init__(
        self,
        root: str | Path,
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(root, config)
        self.min_score = (config or {}).get("min_score", 7)

    def execute(self, context: dict[str, Any] | None = None) -> AgentResult:
        """Run quality assessment on the curated dataset.

        Args:
            context: Optional pipeline context (unused in v1 placeholder).

        Returns:
            AgentResult with quality score statistics.
        """
        curated_path = self.config.get("curated_path")
        if curated_path:
            path = Path(curated_path).resolve()
        else:
            # Default: check pilot candidates
            if self.config.get("check_pilot", True):
                path = self.root / "curated" / "v0.1" / "pilot_candidates.jsonl"
            else:
                path = self.root / "curated" / "v0.1" / "atlas_synthetic_test_v0.1.jsonl"

        if not path.exists():
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SKIPPED,
                summary=f"Curated dataset not found at {path}",
                data={"checked_path": str(path)},
            )

        # Load records and validate quality scores
        records = self._load_jsonl(path)
        if not records:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILED,
                summary=f"No records loaded from {path}",
                errors=[f"Empty or invalid file: {path}"],
            )

        scores = []
        missing = []
        below_threshold = []

        for rec in records:
            qs = rec.get("quality_score")
            if qs is None:
                missing.append(rec.get("id", "unknown"))
                continue
            try:
                score = int(qs)
                scores.append(score)
                if score < self.min_score:
                    below_threshold.append(rec.get("id", "unknown"))
            except (TypeError, ValueError):
                missing.append(rec.get("id", "unknown"))

        # Summary statistics
        data = {
            "checked_path": str(path),
            "total_records": len(records),
            "scores_found": len(scores),
            "scores_missing": len(missing),
            "below_threshold": len(below_threshold),
            "min_score": min(scores) if scores else None,
            "max_score": max(scores) if scores else None,
            "mean_score": round(sum(scores) / len(scores), 2) if scores else None,
            "threshold": self.min_score,
            "missing_ids": sorted(missing),
            "below_threshold_ids": sorted(below_threshold),
        }

        if missing:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILED,
                summary=(
                    f"Quality check: {data['scores_found']}/{data['total_records']} "
                    f"scored, {len(missing)} missing, "
                    f"{len(below_threshold)} below threshold {self.min_score}"
                ),
                data=data,
                errors=[f"{len(missing)} records missing quality_score"],
                warnings=[f"{len(below_threshold)} records below threshold {self.min_score}"],
            )

        if below_threshold:
            status = AgentStatus.FAILED
            summary = (
                f"Quality check: {len(below_threshold)} record(s) below threshold {self.min_score}"
            )
        else:
            status = AgentStatus.PASSED
            summary = (
                f"Quality check passed: {data['total_records']} records, "
                f"mean score {data['mean_score']}"
            )

        return AgentResult(
            agent_name=self.name,
            status=status,
            summary=summary,
            data=data,
            warnings=[f"{len(below_threshold)} below threshold"] if below_threshold else [],
        )

    @staticmethod
    def _load_jsonl(path: Path) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if not path.exists():
            return records
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return records
