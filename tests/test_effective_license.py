"""Licence resolution and the release gate it feeds.

Regression for the v1.0 statistics defect (2026-10-28): canonical records carry
``source.license`` and only 8 % carry a top-level ``license``. A top-level-only
reader reported 7,972,390 records (83.76 %) as ``unknown`` and the release
manifest wrote ``license_gate: {"passed": true}`` as a literal. The gate now
reads the effective licence and fails closed.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

# dedup_release imports its sibling ``common`` by module name.
sys.path.insert(0, str(SCRIPTS / "release"))

from atlas_constants import effective_license, is_denied_license  # noqa: E402


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        ({"license": "MIT"}, "MIT"),
        ({"source": {"license": "ODC-BY"}}, "ODC-BY"),
        ({"license": "unknown", "source": {"license": "MIT"}}, "MIT"),
        ({"license": "", "source": {"license": "CC-BY-SA-3.0"}}, "CC-BY-SA-3.0"),
        ({"license": None, "source": {"license": "Apache-2.0"}}, "Apache-2.0"),
        ({}, "unknown"),
        ({"source": {}}, "unknown"),
        ({"license": "unknown"}, "unknown"),
        ({"license": "  ", "source": {"license": "  "}}, "unknown"),
    ],
)
def test_effective_license(record, expected):
    assert effective_license(record) == expected


def test_canonical_v1_record_is_licensed_by_the_source_field():
    """The v1.0 shape: no top-level licence, a real source licence."""
    record = {
        "id": "s6_tulu3_541288",
        "category": "01_foundation",
        "source": {"name": "tulu", "url": "https://example.invalid", "license": "ODC-BY"},
        "messages": [{"role": "user", "content": "..."}],
    }
    assert effective_license(record) == "ODC-BY"
    assert not is_denied_license(effective_license(record))


def _load_dedup_release():
    spec = importlib.util.spec_from_file_location(
        "dedup_release", SCRIPTS / "release" / "dedup_release.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _stats(by_license: dict[str, int]) -> dict:
    total = sum(by_license.values())
    return {
        "by_category": {"01_foundation": total},
        "by_license": by_license,
        "by_difficulty": {"1": total},
        "quality": {"avg": 8.0, "min": 8, "max": 8, "distribution": {"8": total}},
        "sources": {"s": total},
        "total_records": total,
    }


def _build(mod, stats, root=None):
    return mod.build_manifest(
        release_version="v1.0-RC2",
        previous_manifest={"release_signature": {"chain_hash": "0" * 64}},
        stats=stats,
        total_records=stats["total_records"],
        root=root,
    )


def test_release_gate_fails_on_unknown_licence():
    mod = _load_dedup_release()
    manifest = _build(mod, _stats({"unknown": 2}))
    gate = manifest["gates"]["license_gate"]
    assert gate["passed"] is False
    assert gate["denied_count"] == 2
    assert gate["denied_by_license"] == {"unknown": 2}
    assert manifest["gates_passed"] is False
    assert manifest["status"] == "gate_failed"


def test_release_gate_fails_on_nc_licence():
    mod = _load_dedup_release()
    manifest = _build(mod, _stats({"CC-BY-NC-4.0": 3, "ODC-BY": 1}))
    gate = manifest["gates"]["license_gate"]
    assert gate["passed"] is False
    assert gate["denied_count"] == 3


def test_release_gate_passes_on_licensed_corpus(tmp_path: Path):
    mod = _load_dedup_release()
    (tmp_path / "review_queue").mkdir()
    (tmp_path / "review_queue" / "approved.jsonl").write_text(
        '{"id": 1}\n{"id": 2}\n', encoding="utf-8"
    )
    manifest = _build(mod, _stats({"ODC-BY": 1, "MIT": 1}), root=tmp_path)
    gate = manifest["gates"]["license_gate"]
    assert gate["passed"] is True
    assert gate["denied_count"] == 0
    assert manifest["gates_passed"] is True
