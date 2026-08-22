#!/usr/bin/env python3
"""Shared fixtures for expert pipeline tests (synthetic, offline)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))


def score_record(rec):
    """Mirror the runner's scoring step: fill metadata.quality_score."""
    from expert_pipeline.quality import compute_dimensions, compute_quality_score

    dims = compute_dimensions(rec)
    rec["metadata"]["quality_score"] = compute_quality_score(dims)
    rec["_dims"] = dims
    return rec


def swe_instance(instance_id: str = "django__django-11099", patch: str | None = None,
                 ftp: str | None = None, ptp: str | None = None,
                 difficulty: str | None = "15 min - 1 hour") -> dict:
    return {
        "instance_id": instance_id,
        "repo": "django/django",
        "base_commit": "abc123",
        "problem_statement": "Fix the bug where the ORM returns wrong results when filtering on a joined table with a null value.",
        "patch": DEFAULT_SWE_PATCH if patch is None else patch,
        "test_patch": "diff --git a/tests/test_orm.py b/tests/test_orm.py\n--- a/tests/test_orm.py\n+++ b/tests/test_orm.py\n@@ -1,3 +1,4 @@\n+def test_null_join_filter():\n+    pass\n",
        "FAIL_TO_PASS": DEFAULT_FTP if ftp is None else ftp,
        "PASS_TO_PASS": DEFAULT_PTP if ptp is None else ptp,
        "difficulty": difficulty,
        "hints_text": "",
        "created_at": "2024-01-01T00:00:00Z",
        "version": "1.0",
        "environment_setup_commit": "def456",
    }


DEFAULT_SWE_PATCH = (
    "diff --git a/django/db/models/query.py b/django/db/models/query.py\n"
    "--- a/django/db/models/query.py\n+++ b/django/db/models/query.py\n"
    "@@ -123,7 +123,8 @@ def _filter_or_exclude(self):\n"
    "     if self.query.is_nullable():\n"
    "-        return self\n"
    "+        return self._filter_or_exclude_inner(negate)\n"
)
DEFAULT_FTP = '["tests/test_orm.py::test_null_join_filter"]'
DEFAULT_PTP = '["tests/test_orm.py::test_basic", "tests/test_orm.py::test_chain"]'


def openmath_row(problem: str | None = None, solution: str | None = None,
                 expected_answer: str = "45", problem_source: str = "augmented_math") -> dict:
    return {
        "problem": problem or (
            "Ava is planning a camping trip with her friends. She wants to make sure "
            "they have enough granola bars for everyone. There are 5 people total and "
            "each person needs 2 granola bars for breakfast and 1 for a snack. How many "
            "granola bars do they need in total?"
        ),
        "generated_solution": solution or (
            "There will be a total of 5 people.\n"
            "Each person needs 2 granola bars for breakfast and 1 for a snack.\n"
            "So each person needs 2 + 1 = 3 granola bars.\n"
            "For 5 people, that is 5 * 3 = 15 granola bars.\n"
            "Therefore, they need \\boxed{15} granola bars in total."
        ),
        "expected_answer": expected_answer,
        "problem_source": problem_source,
    }


def arxiv_paper(arxiv_id: str = "2607.28608v1", title: str = "A Test Paper on Transformers",
                abstract: str | None = None) -> dict:
    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "abstract": abstract or (
            "We propose a new method for efficient transformer training. Our approach "
            "introduces a novel attention mechanism that reduces memory usage while "
            "maintaining accuracy. We demonstrate results on several benchmarks showing "
            "improvements over strong baselines. Our method is simple and effective."
        ),
        "published": "2026-07-30T17:59:56Z",
        "updated": "2026-07-30T18:00:00Z",
        "primary_category": "cs.LG",
        "categories": ["cs.LG", "stat.ML"],
        "authors": ["Jane Doe", "John Smith"],
        "comment": "",
        "doi": "",
        "journal_ref": "",
    }


def kep_readme(with_alternatives: bool = True) -> str:
    """Synthetic KEP README in the canonical template shape."""
    alts = (
        "## Alternatives\n\n"
        "We considered keeping the old label semantics, but that would "
        "require every consumer to handle both cases indefinitely.\n\n"
        if with_alternatives else ""
    )
    return (
        "# KEP-1659: Standard Topology Labels\n"
        "\n"
        "<!-- toc -->\n"
        "- [Summary](#summary)\n"
        "- [Motivation](#motivation)\n"
        "<!-- /toc -->\n"
        "\n"
        "## Release Signoff Checklist\n"
        "\n"
        "- [x] KEP approvers have approved the KEP status as `implementable`\n"
        "\n"
        "## Summary\n"
        "\n"
        "Kubernetes currently assumes topology labels are arbitrary. This KEP "
        "standardizes two well-known topology labels so components can depend "
        "on them.\n"
        "\n"
        "## Motivation\n"
        "\n"
        "Components hard-code region and zone label keys today, which prevents "
        "alternative topologies from working.\n"
        "\n"
        "### Goals\n"
        "\n"
        "Define standard label keys with documented failure-domain semantics.\n"
        "\n"
        "### Non-Goals\n"
        "\n"
        "Changing kubelet provider integration.\n"
        "\n"
        "## Proposal\n"
        "\n"
        "Reserve the well-known label prefix and document the semantics of "
        "each standard key.\n"
        "\n"
        "## Design Details\n"
        "\n"
        "The kubelet applies the standard labels at registration time. "
        "Existing clusters keep working because consumers fall back to the "
        "legacy keys when the new ones are absent.\n"
        "\n"
        "### Test Plan\n"
        "\n"
        "Unit tests for label application plus an e2e conformance test.\n"
        "\n"
        + alts +
        "## Implementation History\n"
        "\n"
        "2026-08-22: KEP drafted.\n"
    )


def kep_raw_row(markdown: str | None = None,
                path: str = "keps/sig-architecture/1659-standard-topology-labels/README.md") -> dict:
    from expert_pipeline.adapters.architecture import parse_kep_slug, parse_sections, \
        parse_title, build_problem_solution

    md = markdown if markdown is not None else kep_readme()
    sig, kep_dir = parse_kep_slug(path)
    sections = parse_sections(md)
    problem, solution = build_problem_solution(sections)
    return {
        "path": path,
        "sig": sig,
        "kep_dir": kep_dir,
        "title": parse_title(md, kep_dir),
        "markdown": md,
        "sections": sections,
        "problem": problem,
        "solution": solution,
    }
