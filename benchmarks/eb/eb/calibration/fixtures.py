#!/usr/bin/env python3
"""
fixtures.py — Calibration fixture loading and reference label management.

Manages the 12 calibration fixtures defined in:
  metadata/calibration/long_judge_calibration_v1.json
and the on-disk fixture JSON files under:
  repositories/fixtures/long-calibration/{fixture_id}/fixture.json

Reference types:
  - deterministic_reference: derived from deterministic gates (PASS/FAIL/PARTIAL)
  - expert_review_required: needs human/expert label before calibration can proceed
  - provisional: temporary reference pending expert review
  - judge_output: recorded judge score (not a ground-truth reference)
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_REFERENCE_STATUSES = frozenset({
    "deterministic_reference",
    "expert_review_required",
    "provisional",
    "judge_output",
})

LONG_DIMENSIONS = (
    "correctness",
    "completeness",
    "requirement_adherence",
    "implementation_quality",
    "test_quality",
    "regression_safety",
    "adaptation_quality",
    "final_delivery_quality",
)

CALIBRATION_META_PATH = Path(__file__).resolve().parent.parent.parent.parent.parent / "metadata" / "calibration" / "long_judge_calibration_v1.json"
FIXTURES_ROOT = Path(__file__).resolve().parent.parent.parent / "repositories" / "fixtures" / "long-calibration"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DimensionReference:
    """A single dimension reference label with status and optional value."""

    dimension: str
    value: float | None
    status: str
    rationale: str

    @classmethod
    def from_dict(cls, dimension: str, d: dict[str, Any]) -> "DimensionReference":
        return cls(
            dimension=dimension,
            value=d.get("value"),
            status=d.get("status", "expert_review_required"),
            rationale=d.get("rationale", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "value": self.value,
            "status": self.status,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class CalibrationFixture:
    """A single calibration fixture with its reference labels and metadata."""

    fixture_id: str
    scenario: str
    description: str
    reference_status: str
    reference_rationale: str
    expected_outcome: str
    expected_quality: str
    judge_eligible: bool
    dimension_references: dict[str, DimensionReference] = field(default_factory=dict)
    judge_model: str | None = None
    judge_output: dict[str, Any] | None = None
    fixture_hash: str = ""
    fixture_path: str = ""

    @classmethod
    def from_meta_entry(cls, entry: dict[str, Any], fixture_path: str = "") -> "CalibrationFixture":
        dim_refs: dict[str, DimensionReference] = {}
        for dim_name, dim_data in entry.get("dimension_references", {}).items():
            dim_refs[dim_name] = DimensionReference.from_dict(dim_name, dim_data)

        fixture_hash = ""
        if fixture_path:
            p = Path(fixture_path)
            if p.exists():
                fixture_hash = hashlib.sha256(p.read_bytes()).hexdigest()[:16]

        return cls(
            fixture_id=entry["fixture_id"],
            scenario=entry["scenario"],
            description=entry.get("description", ""),
            reference_status=entry.get("reference_status", "expert_review_required"),
            reference_rationale=entry.get("reference_rationale", ""),
            expected_outcome=entry.get("expected_outcome", "PASS"),
            expected_quality=entry.get("expected_quality", "medium"),
            judge_eligible=entry.get("judge_eligible", False),
            dimension_references=dim_refs,
            judge_model=entry.get("judge_model"),
            judge_output=entry.get("judge_output"),
            fixture_hash=fixture_hash,
            fixture_path=fixture_path,
        )

    def has_deterministic_reference_for(self, dimension: str) -> bool:
        """Check if a dimension has a deterministic (non-null) reference value."""
        ref = self.dimension_references.get(dimension)
        if ref is None:
            return False
        return ref.value is not None and ref.status == "deterministic_reference"

    def has_expert_reference_for(self, dimension: str) -> bool:
        """Check if a dimension has an expert-derived reference value."""
        ref = self.dimension_references.get(dimension)
        if ref is None:
            return False
        return ref.value is not None and ref.status in ("expert_review_required", "provisional")

    def has_reference_for(self, dimension: str) -> bool:
        """Check if any reference value exists for a dimension."""
        ref = self.dimension_references.get(dimension)
        return ref is not None and ref.value is not None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "fixture_id": self.fixture_id,
            "scenario": self.scenario,
            "description": self.description,
            "reference_status": self.reference_status,
            "reference_rationale": self.reference_rationale,
            "expected_outcome": self.expected_outcome,
            "expected_quality": self.expected_quality,
            "judge_eligible": self.judge_eligible,
            "dimension_references": {k: v.to_dict() for k, v in self.dimension_references.items()},
            "fixture_hash": self.fixture_hash,
            "fixture_path": self.fixture_path,
        }
        if self.judge_model is not None:
            d["judge_model"] = self.judge_model
        if self.judge_output is not None:
            d["judge_output"] = self.judge_output
        return d


# ---------------------------------------------------------------------------
# Fixture set
# ---------------------------------------------------------------------------

class CalibrationFixtureSet:
    """Collection of all calibration fixtures loaded from metadata + disk."""

    def __init__(self, meta_path: Path | None = None, fixtures_root: Path | None = None):
        self._meta_path = meta_path or CALIBRATION_META_PATH
        self._fixtures_root = fixtures_root or FIXTURES_ROOT
        self._fixtures: dict[str, CalibrationFixture] = {}
        self._load()

    def _load(self) -> None:
        """Load all fixtures from the calibration metadata file."""
        if not self._meta_path.exists():
            return

        with self._meta_path.open() as f:
            meta = json.load(f)

        for entry in meta.get("fixtures", []):
            fid = entry["fixture_id"]
            fixture_path = str(self._fixtures_root / fid / "fixture.json")
            self._fixtures[fid] = CalibrationFixture.from_meta_entry(entry, fixture_path)

    @property
    def fixtures(self) -> dict[str, CalibrationFixture]:
        return dict(self._fixtures)

    @property
    def fixture_ids(self) -> list[str]:
        return list(self._fixtures.keys())

    def get(self, fixture_id: str) -> CalibrationFixture | None:
        return self._fixtures.get(fixture_id)

    def judge_eligible_fixtures(self) -> list[CalibrationFixture]:
        """Return fixtures where judge should be invoked (PASS/PARTIAL)."""
        return [f for f in self._fixtures.values() if f.judge_eligible]

    def deterministic_reference_fixtures(self) -> list[CalibrationFixture]:
        """Return fixtures whose overall reference is deterministic."""
        return [
            f for f in self._fixtures.values()
            if f.reference_status == "deterministic_reference"
        ]

    def expert_reference_fixtures(self) -> list[CalibrationFixture]:
        """Return fixtures requiring expert review."""
        return [
            f for f in self._fixtures.values()
            if f.reference_status == "expert_review_required"
        ]

    def fixtures_with_dimension_reference(self, dimension: str) -> list[CalibrationFixture]:
        """Return fixtures that have any reference value for the given dimension."""
        return [
            f for f in self._fixtures.values()
            if f.has_reference_for(dimension)
        ]

    def count(self) -> int:
        return len(self._fixtures)

    def validate(self) -> list[str]:
        """Validate fixture set consistency. Returns list of issues."""
        issues: list[str] = []
        for fid, f in self._fixtures.items():
            if f.reference_status not in VALID_REFERENCE_STATUSES:
                issues.append(f"{fid}: invalid reference_status={f.reference_status!r}")
            for dim, ref in f.dimension_references.items():
                if ref.status not in VALID_REFERENCE_STATUSES:
                    issues.append(f"{fid}.{dim}: invalid status={ref.status!r}")
                if ref.value is not None and not (0.0 <= ref.value <= 1.0):
                    issues.append(f"{fid}.{dim}: value {ref.value} out of [0,1] range")
        return issues