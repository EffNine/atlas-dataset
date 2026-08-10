"""Tests for evaluation_engine.v2.code_eval — functional correctness, syntax
validation, structural similarity, patch/diff comparison.

Adversarial cases required by Phase 5A.2:
  * correct answer with different wording (renamed vars, formatting, comments),
  * wrong answer with matching keywords/function names (wrong operator/body),
  * partial correctness (correct approach, failing edge case).
"""

from __future__ import annotations

import pytest

from evaluation_engine.v2.code_eval import (
    CodeAnswerEvaluator,
    compare,
    extract_code_blocks,
    extract_added_lines,
    is_patch,
    patch_similarity,
    run_function_tests,
    structural_similarity,
    validate_python_syntax,
)

REF_ADD = "def add(a, b):\n    return a + b\n"


# --------------------------------------------------------------------------- #
# Syntax validation
# --------------------------------------------------------------------------- #
class TestSyntax:
    def test_valid(self):
        ok, err = validate_python_syntax("def f(x):\n    return x\n")
        assert ok is True
        assert err == ""

    def test_invalid(self):
        ok, err = validate_python_syntax("def f(x:\n    return x\n")
        assert ok is False
        assert "SyntaxError" in err

    def test_empty(self):
        assert validate_python_syntax("")[0] is False


# --------------------------------------------------------------------------- #
# Structural / patch comparison
# --------------------------------------------------------------------------- #
class TestStructural:
    def test_same_logic_renamed(self):
        cand = "def add(x, y):\n    # sum two numbers\n    return x + y\n"
        assert structural_similarity(REF_ADD, cand) >= 0.85

    def test_wrong_operator_punished(self):
        cand = "def add(a, b):\n    return a * b\n"
        assert structural_similarity(REF_ADD, cand) < 0.6

    def test_patch_detection(self):
        patch = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -1,3 +1,3 @@\n"
        assert is_patch(patch) is True
        assert is_patch("def f():\n    return 1\n") is False

    def test_patch_added_lines(self):
        p = "+one\n+++ header\n-two\n+three\n"
        assert extract_added_lines(p) == ["one", "three"]

    def test_patch_similarity(self):
        a = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@\n-    return x - 1\n+    return x + 1\n"
        b = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@\n-    return x - 1\n+    return x + 1\n"
        c = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@\n-    return x - 1\n+    return x * 100\n"
        assert patch_similarity(a, b) == 1.0
        assert patch_similarity(a, c) < 0.5

    def test_run_function_tests(self):
        res = run_function_tests(REF_ADD, [{"name": "add", "args": [2, 3], "expected": 5}])
        assert res["passed"] == 1
        assert res["failed"] == 0

    def test_run_function_tests_missing(self):
        res = run_function_tests("def other():\n    return 0\n",
                                 [{"name": "add", "args": [1, 1], "expected": 2}])
        assert res["passed"] == 0
        assert res["cases"][0]["status"] == "error"


# --------------------------------------------------------------------------- #
# Adversarial
# --------------------------------------------------------------------------- #
class TestAdversarialCode:
    def test_correct_answer_different_wording(self):
        """Same logic, renamed variables + comment + formatting == correct."""
        cand = "def add(x, y):\n    # sum two numbers\n    return x + y\n"
        r = compare(REF_ADD, cand, tests=[{"name": "add", "args": [2, 3], "expected": 5}])
        assert r["correct"] is True
        assert r["score"] >= 0.85

    def test_wrong_answer_with_matching_keywords(self):
        """Right signature and names, wrong operator body == incorrect."""
        cand = "def add(a, b):\n    return a * b\n"
        r = compare(REF_ADD, cand, tests=[{"name": "add", "args": [2, 3], "expected": 5}])
        assert r["correct"] is False
        assert r["score"] < 0.85

    def test_syntax_error_penalized(self):
        cand = "def add(a, b:\n    return a + b\n"
        r = compare(REF_ADD, cand, tests=[{"name": "add", "args": [2, 3], "expected": 5}])
        assert r["correct"] is False
        assert r["method"] == "syntax"

    def test_partial_correctness(self):
        """Happy path works, edge case fails -> partial credit, not full."""
        cand = "def add(a, b):\n    if a == 0:\n        return b\n    return 0\n"
        r = compare(REF_ADD, cand, tests=[
            {"name": "add", "args": [0, 5], "expected": 5},
            {"name": "add", "args": [2, 3], "expected": 5},
        ])
        assert r["correct"] is False
        assert 0.0 < r["score"] < 1.0

    def test_patch_answers(self):
        ref = ("diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n"
               "@@ -1,3 +1,3 @@\n def f(x):\n-    return x - 1\n+    return x + 1\n")
        same = ("diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n"
                "@@ -1,3 +1,3 @@\n def f(x):\n-    return x - 1\n+    return x + 1\n")
        other = ("diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n"
                 "@@ -1,3 +1,3 @@\n def f(x):\n-    return x - 1\n+    return x * 100\n")
        assert compare(ref, same)["correct"] is True
        assert compare(ref, other)["correct"] is False

    def test_unverifiable_no_reference(self):
        r = CodeAnswerEvaluator().evaluate(reference="", candidate="def f(x):\n    return x\n")
        assert r.correct is None
        assert r.score == 0.5

    def test_code_block_extraction(self):
        blocks = extract_code_blocks("```python\ndef f():\n    pass\n```")
        assert blocks == [("python", "def f():\n    pass\n")]
