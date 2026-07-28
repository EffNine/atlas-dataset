#!/usr/bin/env python3
"""Quality agent — production implementation (v1.2).

Delegates to the existing ``quality_score.py`` evaluation engine for
deterministic, explainable, multi-dimensional quality assessment:

  -  ``quality_score.evaluate_record()`` — per-record 7-dimension scoring
  -  ``quality_score.score_record()`` — backward-compatible (int + dims)

Each record is evaluated on 7 dimensions (accuracy, completeness,
technical_correctness, clarity, usefulness, originality, relevance) and
receives a 1-10 quality score, a confidence level (1-5), and a set of
issue flags.

The agent aggregates per-record results across the dataset, reports
score distribution, and returns PASS/FAIL based on a configurable
threshold.  No dataset files are modified.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from .base_agent import BaseAgent, AgentResult, AgentStatus


# ---------------------------------------------------------------------------
# Lazy import for the production quality engine
# ---------------------------------------------------------------------------

def _import(target: str):
    """Lazy-import a module from the scripts directory."""
    return __import__(target)


class QualityAgent(BaseAgent):
    """Production quality evaluation agent (v1.2).

    Evaluates every record in a curated dataset using the existing
    ``quality_score.py`` engine.  Produces:

      - Per-record quality score (1-10)
      - Per-dimension breakdown (7 dimensions, 0-1 each)
      - Confidence score (0-1) and confidence level (1-5)
      - Issue flags (boilerplate_opener, very_short_answer, etc.)
      - Aggregate statistics across all records
      - PASS / FAIL based on configurable threshold

    Config keys:
        curated_path:  Override default dataset path.
        min_score:     Minimum acceptable mean quality score
                       (default 7).  Pipeline FAILS when mean < min_score.
        min_confidence: Minimum acceptable mean confidence
                       (default 0.0 — no confidence floor by default).
        fail_on_any_below: If ``True`` (default ``False``), fail when
                       ANY record scores below ``min_score`` instead of
                       checking the mean.
        fail_on_flags: Issue flag names that cause pipeline failure.
                       Default ``["very_short_answer", "unclosed_code_fence",
                       "boilerplate_opener"]``.

    Args:
        root:   Path to the atlas-dataset repository root.
        config: Optional configuration dict (see above).
    """

    name: str = "quality_agent"
    description: str = (
        "Production quality evaluation — 7-dimension deterministic scoring, "
        "confidence, issue detection"
    )

    def __init__(
        self,
        root: str | Path,
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(root, config)
        cfg = config or {}
        self.min_score = cfg.get("min_score", 7)
        self.min_confidence = cfg.get("min_confidence", 0.0)
        self.fail_on_any_below = cfg.get("fail_on_any_below", False)
        self.fail_on_flags = cfg.get(
            "fail_on_flags",
            ["very_short_answer", "unclosed_code_fence", "boilerplate_opener"],
        )

        # Ensure scripts/ is on sys.path for the quality engine import
        scripts = str(self.root / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)

    # ── Agent execution ──────────────────────────────────────────────────

    def execute(self, context: dict[str, Any] | None = None) -> AgentResult:
        """Run quality evaluation against a curated dataset file.

        Args:
            context: Optional dict (unused in v1.2 — path comes from config).

        Returns:
            ``AgentResult`` with per-record dimension scores, aggregate
            statistics, issue flags, and PASS/FAIL status.
        """
        path = self._resolve_path()
        if path is None:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SKIPPED,
                summary="No dataset file found to evaluate",
                data={"searched": self._list_curated_files()},
            )

        # ── 1. Load records ──────────────────────────────────────────────
        records, parse_errors = self._parse_jsonl(path)
        if not records and parse_errors:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILED,
                summary=f"All lines failed JSON parsing at {path}",
                data={
                    "checked_path": str(path),
                    "parse_errors": parse_errors,
                },
                errors=parse_errors,
            )

        # ── 2. Import production quality engine ──────────────────────────
        try:
            qee = _import("quality_score")
        except ImportError as exc:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILED,
                summary=f"Cannot import quality_score engine: {exc}",
                errors=[str(exc)],
            )

        # ── 3. Evaluate every record ─────────────────────────────────────
        per_record: list[dict[str, Any]] = []
        all_scores: list[int] = []
        all_confs: list[float] = []
        issue_counter: Counter[str] = Counter()
        dimension_sums: dict[str, float] = {}
        total_records = len(records)

        for rec in records:
            rid = rec.get("id", "<no-id>")
            ev = qee.evaluate_record(rec)
            qs = ev["quality_score"]
            conf = ev["confidence"]
            flags = ev.get("flags", [])

            all_scores.append(qs)
            all_confs.append(conf)

            # Track issue flags
            for flag in flags:
                issue_counter[flag] += 1

            # Accumulate dimension scores for averaging
            for dim_name, dim_score in ev.get("dimensions", {}).items():
                dimension_sums[dim_name] = dimension_sums.get(dim_name, 0.0) + dim_score

            per_record.append({
                "id": rid,
                "quality_score": qs,
                "confidence": conf,
                "confidence_level": ev.get("confidence_level", 1),
                "dimensions": ev.get("dimensions", {}),
                "flags": flags,
                "explanation": ev.get("explanation", ""),
                "rationale": ev.get("rationale", []),
            })

        # ── 4. Aggregate statistics ──────────────────────────────────────
        mean_score = round(sum(all_scores) / total_records, 2) if total_records else 0.0
        mean_conf = round(sum(all_confs) / total_records, 2) if total_records else 0.0

        score_distribution = {
            str(k): v for k, v in sorted(Counter(all_scores).items())
        }

        # Compute per-dimension means
        dim_averages: dict[str, float] = {}
        for dim_name in sorted(dimension_sums):
            dim_averages[dim_name] = round(
                dimension_sums[dim_name] / total_records, 3
            ) if total_records else 0.0

        records_below = [
            r["id"] for r in per_record if r["quality_score"] < self.min_score
        ]

        data: dict[str, Any] = {
            "checked_path": str(path),
            "total_records": total_records,
            "parse_errors": parse_errors,
            "quality_engine": "quality_score.py",
            "threshold": {
                "min_score": self.min_score,
                "min_confidence": self.min_confidence,
                "fail_on_any_below": self.fail_on_any_below,
                "fail_on_flags": self.fail_on_flags,
            },
            "aggregate": {
                "mean_score": mean_score,
                "mean_confidence": mean_conf,
                "min_score_observed": min(all_scores) if all_scores else None,
                "max_score_observed": max(all_scores) if all_scores else None,
                "score_distribution": score_distribution,
                "total_below_threshold": len(records_below),
                "records_below_threshold": records_below,
            },
            "dimension_averages": dim_averages,
            "issue_flags": dict(issue_counter.most_common()),
            "records": per_record,
        }

        # ── 5. Determine status ──────────────────────────────────────────
        errors: list[str] = []
        warnings: list[str] = []

        if parse_errors:
            errors.append(f"{len(parse_errors)} line(s) failed JSON parsing")

        # Check mean score threshold
        if mean_score < self.min_score:
            errors.append(
                f"Mean quality score {mean_score} < minimum {self.min_score}"
            )

        # Check individual records (fail_on_any_below)
        if self.fail_on_any_below and records_below:
            errors.append(
                f"{len(records_below)} record(s) below threshold {self.min_score}"
            )

        # Check mean confidence
        if mean_conf < self.min_confidence:
            errors.append(
                f"Mean confidence {mean_conf} < minimum {self.min_confidence}"
            )

        # Check for critical issue flags
        for flag in self.fail_on_flags:
            count = issue_counter.get(flag, 0)
            if count > 0:
                warnings.append(
                    f"Flag '{flag}': {count} record(s)"
                )
                if self.fail_on_any_below:
                    errors.append(
                        f"Flag '{flag}' present on {count} record(s)"
                    )

        if errors:
            status = AgentStatus.FAILED
            summary = f"Quality evaluation FAILED: {'; '.join(errors)}"
        else:
            status = AgentStatus.PASSED
            summary = (
                f"Quality evaluation PASSED: {total_records} records, "
                f"mean score {mean_score}, mean confidence {mean_conf}, "
                f"score range [{min(all_scores)}-{max(all_scores)}]"
            )

        return AgentResult(
            agent_name=self.name,
            status=status,
            summary=summary,
            data=data,
            errors=errors,
            warnings=warnings,
        )

    # ── Path resolution ──────────────────────────────────────────────────

    def _resolve_path(self) -> Path | None:
        """Resolve the dataset path from config or discover it."""
        curated_path = self.config.get("curated_path")
        if curated_path:
            p = Path(curated_path)
            return p if p.exists() else None

        candidates = [
            self.root / "curated" / "v0.1" / "pilot_candidates.jsonl",
            self.root / "curated" / "v0.1" / "atlas_synthetic_test_v0.1.jsonl",
            self.root / "curated" / "v0.1" / "atlas_v0.1.jsonl",
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def _list_curated_files(self) -> list[str]:
        """List available curated files for diagnostic messaging."""
        curated = self.root / "curated"
        if not curated.exists():
            return []
        return sorted(
            str(p.relative_to(self.root))
            for p in curated.rglob("*.jsonl")
            if p.is_file()
        )

    # ── Parsing ──────────────────────────────────────────────────────────

    @staticmethod
    def _parse_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
        """Parse a JSONL file. Returns (records, parse_error_messages)."""
        records: list[dict[str, Any]] = []
        parse_errors: list[str] = []
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as e:
                parse_errors.append(f"Line {line_no}: {e}")
        return records, parse_errors
