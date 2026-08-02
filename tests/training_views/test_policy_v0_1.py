"""Validation tests for training view eligibility policy v0.1.

This module asserts governance invariants only. It must not:
- execute model training
- download datasets
- modify Atlas curated/, raw/, releases/, or knowledge_packs/
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

ROOT = pytest.importorskip("pathlib").Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "docs" / "training_view_eligibility_policy_v0.1.md"
DECISION_PATH = ROOT / "metadata" / "training_view_policy_decision_v0.1.json"
SELF_PATH = Path(__file__).resolve()

FORBIDDEN_TRAINING_NAMES = {"train", "fit", "compile", "predict", "generate"}
FORBIDDEN_DATASET_DIRS = {"curated", "raw", "releases", "knowledge_packs"}
ALLOWED_DATASET_STRINGS = {
    "curated",
    "raw",
    "releases",
    "knowledge_packs",
    "curated/, raw/, releases/, or knowledge_packs/",
    "curated/,\n    raw/,\n    releases/,\n    or knowledge_packs/",
    "curated/,\nraw/,\nreleases/,\nknowledge_packs/",
}


def _is_allowed_dataset_string(value: str) -> bool:
    return value in ALLOWED_DATASET_STRINGS


REQUIRED_SECTIONS = [
    "## 1. Purpose",
    "## 2. Record Lifecycle",
    "## 3. Eligibility Rules",
    "## 4. Human Review Role",
    "## 5. Synthetic Data Policy",
    "## 6. Specialist View Mapping",
    "## 7. Decision Record",
    "## 8. Validation",
    "## 9. Scope Boundaries",
]

REQUIRED_DECISION_FIELDS = {
    "decision": "APPROVED",
    "policy_version": "v0.1",
    "human_review_role": "calibration",
    "training_eligibility": "automated_gate_plus_exclusions",
}

EXCLUDED_CATEGORIES = [
    "human_reject",
    "license_failure",
    "security_failure",
    "provenance_failure",
]

VIEW_MAPPING = {
    "code_300m": "SWE-bench Verified",
    "math_300m": "OpenMathInstruct-2",
    "aiml_300m": "ArXiv cs.LG/cs.CL/cs.AI/stat.ML",
}


def test_policy_document_exists() -> None:
    assert POLICY_PATH.exists(), "policy document missing"


def test_policy_required_sections_present() -> None:
    text = POLICY_PATH.read_text()
    for section in REQUIRED_SECTIONS:
        assert section in text, f"missing policy section: {section}"


def test_decision_document_exists() -> None:
    assert DECISION_PATH.exists(), "policy decision JSON missing"


def test_decision_required_fields_and_values() -> None:
    data = json.loads(DECISION_PATH.read_text())
    for field, expected in REQUIRED_DECISION_FIELDS.items():
        assert field in data, f"missing decision field: {field}"
        assert data[field] == expected, f"decision field mismatch: {field}"


def test_decision_excluded_categories_present() -> None:
    data = json.loads(DECISION_PATH.read_text())
    categories = data.get("excluded_categories", [])
    for category in EXCLUDED_CATEGORIES:
        assert category in categories, f"missing excluded category: {category}"


def test_decision_view_mapping_present() -> None:
    data = json.loads(DECISION_PATH.read_text())
    mapping = data.get("specialist_view_mapping", {})
    assert mapping == VIEW_MAPPING


def test_openmath_rejected_records_remain_excluded() -> None:
    sample_path = ROOT / "tmp" / "expert_pilot_sample_openmath_records_v0.1.jsonl"
    if not sample_path.exists():
        text = POLICY_PATH.read_text()
        assert "OpenMathInstruct-2" in text
        assert "excluded from training views" in text
        return

    records = [
        json.loads(line)
        for line in sample_path.read_text().splitlines()
        if line.strip()
    ]
    assert records, "OpenMath sample file is empty"
    for record in records:
        review = record.get("review") if isinstance(record.get("review"), dict) else {}
        if review.get("verdict") == "reject":
            assert record.get("training_eligibility") != "eligible"


def test_no_training_execution_in_policy_tests() -> None:
    tree = ast.parse(SELF_PATH.read_text())
    matched = [
        node.func.id for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in FORBIDDEN_TRAINING_NAMES
    ]
    assert not matched, (
        "policy tests must not invoke training: "
        + ", ".join(f"{name}()" for name in matched)
    )


def test_no_dataset_artifact_modification_by_policy_tests() -> None:
    tree = ast.parse(SELF_PATH.read_text())
    matched_dirs = {
        part
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and not _is_allowed_dataset_string(node.value)
        for part in node.value.replace("\\", "/").split("/")
        if part in FORBIDDEN_DATASET_DIRS
    }
    assert not matched_dirs, (
        "policy tests must not modify dataset artifacts: "
        + ", ".join(sorted(matched_dirs))
    )
