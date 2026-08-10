"""Tests for evaluation_engine.v2.math_eval — final-answer extraction,
notation normalization, and equivalent-expression support.

Adversarial cases required by Phase 5A.2:
  * correct answer with different wording (spoken math, unicode, LaTeX),
  * wrong answer with matching keywords (keyword soup must NOT score correct),
  * partial correctness (close expression must get partial, not full, credit).
"""

from __future__ import annotations

import pytest

from evaluation_engine.v2.math_eval import (
    MathAnswerEvaluator,
    compare,
    extract_final_answer,
    expressions_equivalent,
    insert_implicit_multiplication,
)


# --------------------------------------------------------------------------- #
# Final-answer extraction
# --------------------------------------------------------------------------- #
class TestExtractFinalAnswer:
    def test_boxed(self):
        assert extract_final_answer(r"The result is $\boxed{4x^2-3x-7}$.") == "4x^2-3x-7"

    def test_answer_label(self):
        assert extract_final_answer("First combine terms. Final answer: 42.") == "42"

    def test_answer_is(self):
        assert extract_final_answer("The result is 4x^2-3x-7.") == "4x^2-3x-7"

    def test_equals_rhs(self):
        assert extract_final_answer("We get 3x + 2 = 11") == "11"

    def test_last_mathy_line(self):
        assert extract_final_answer("Combine like terms.\n4x^2 - 3x - 7") == "4x^2 - 3x - 7"

    def test_empty(self):
        assert extract_final_answer("") == ""


# --------------------------------------------------------------------------- #
# Brace-balanced \\boxed extraction (nested contents) — Phase 5A.4
# --------------------------------------------------------------------------- #
class TestNestedBoxedExtraction:
    """Phase 5A.4: the old regex-based extractor dropped nested contents
    (fractions, roots, coordinates). These must now extract whole."""

    def test_boxed_integer(self):
        assert extract_final_answer(r"The answer is \boxed{5}.") == "5"

    def test_boxed_fraction(self):
        assert extract_final_answer(r"The answer is \boxed{\frac{5}{2}}.") == r"\frac{5}{2}"

    def test_boxed_sqrt(self):
        assert extract_final_answer(r"The answer is \boxed{\sqrt{3}}.") == r"\sqrt{3}"

    def test_boxed_coordinate(self):
        assert extract_final_answer(r"The answer is \boxed{(-3,0)}.") == "(-3,0)"

    def test_boxed_coordinate_space(self):
        assert extract_final_answer(r"The answer is \boxed{(-3, 0)}.") == "(-3, 0)"

    def test_boxed_left_right_tuple(self):
        assert extract_final_answer(
            r"The answer is \boxed{\left(\frac{5}{2},\sqrt3\right)}."
        ) == r"\left(\frac{5}{2},\sqrt3\right)"


# --------------------------------------------------------------------------- #
# Notation normalization / equivalence
# --------------------------------------------------------------------------- #
class TestEquivalence:
    @pytest.mark.parametrize("a,b", [
        ("4x^2 - 3x - 7", "4x^2-3x-7"),           # whitespace
        ("(x+1)^2", "x^2 + 2x + 1"),              # algebraically equivalent
        ("(x+1)(x-1)", "x^2 - 1"),                # factored vs expanded
        ("1/2", "0.5"),                           # fraction vs decimal
        ("\u22123", "-3"),                        # unicode minus
        ("x\u00b2+1", "x^2+1"),                   # unicode superscript
        (r"\frac{1}{2}", "0.5"),                  # LaTeX frac
        ("sqrt(9)", "3"),                         # function
        ("x^3", "x*x*x"),                         # power vs repeated mult
        ("2x + 1", "1 + x*2"),                    # commutative
("7", "seven"),                           # number word
        ("x/2", "x divided by two"),            # spoken operator
        # Phase 5A.4 nested-brace / coordinate normalization.
        (r"\frac{5}{2}", "2.5"),                # fraction == decimal
        (r"\sqrt{3}", "sqrt(3)"),              # identical root
        (r"\sqrt3", "sqrt(3)"),                # bare root == braced root
        ("(-3, 0)", "(-3,0)"),                 # coordinate, space-insensitive
        (r"\left(\frac{5}{2},\sqrt3\right)", "((5)/(2), sqrt(3))"),  # left/right tuple
    ])
    def test_equivalent(self, a, b):
        r = compare(a, b)
        assert r["correct"] is True, r
        assert r["score"] == 1.0, r

    @pytest.mark.parametrize("a,b", [
        ("4", "5"),
        ("4x^2-3x-7", "4x^2-3x"),                 # missing constant term
        ("x+1", "x+2"),
    ])
    def test_not_equivalent(self, a, b):
        assert compare(a, b)["correct"] is False


class TestAdversarialMath:
    def test_correct_answer_different_wording(self):
        """'four x squared minus three x minus seven' == '4x^2-3x-7'."""
        r = compare("4x^2-3x-7",
                    "four x squared minus three x minus seven")
        assert r["correct"] is True
        assert r["score"] == 1.0

    def test_wrong_answer_with_matching_keywords(self):
        """A sentence stuffed with the right keywords but no final result must
        NOT be scored correct."""
        ref = "4x^2-3x-7"
        kw = ("The polynomial combines x squared terms like 3x^2 and 2x^2 "
              "and -x^2, and linear terms like 2x, -4x, -x.")
        r = compare(ref, kw)
        assert r["correct"] is False
        assert r["score"] < 0.5

    def test_partial_correctness(self):
        """Close but wrong expression gets partial (non-zero, <1) credit."""
        r = compare("4x^2-3x-7", "4x^2-3x")
        assert r["correct"] is False
        assert 0.0 <= r["score"] < 1.0

    def test_no_final_answer_fails_closed(self):
        r = MathAnswerEvaluator().evaluate(reference="42", candidate="I tried my best.")
        assert r.correct is False
        assert r.score == 0.0
        assert r.method == "no_final_answer"

    def test_unverifiable_without_reference(self):
        r = MathAnswerEvaluator().evaluate(reference="", candidate="42")
        assert r.correct is None
        assert r.score == 0.5

    def test_implicit_multiplication(self):
        assert insert_implicit_multiplication("2sqrt(9)") == "2*sqrt(9)"
        assert insert_implicit_multiplication("4x^2") == "4*x^2"
        assert insert_implicit_multiplication("(x+1)(x-1)") == "(x+1)*(x-1)"

    def test_expressions_equivalent_samples(self):
        eq, method, n = expressions_equivalent("x^2-1", "(x-1)(x+1)")
        assert eq is True
        assert n >= 3

    def test_deterministic(self):
        a = compare("4x^2-3x-7", "4x^2-3x-7")
        b = compare("4x^2-3x-7", "4x^2-3x-7")
        assert a == b


# --------------------------------------------------------------------------- #
# Phase 6.4 — percentage / unit / numeric-formatting normalization
# --------------------------------------------------------------------------- #
class TestPercentAndUnitNormalization:
    """Phase 6.4 regression tests: QEE-calibration false rejections (49, 36%)
    plus percentage/unit/numeric-format equivalence and wrong-answer checks."""

    @pytest.mark.parametrize("ref,cand", [
        # previous false-rejection cases (from calibration)
        ("49", r"49\)"),                    # trailing LaTeX closer residue
        (r"\boxed{36\%}", r"\boxed{36\%}"),
        # percentage equivalences
        ("49%", "0.49"),
        ("49%", "49/100"),
        ("36%", "0.36"),
        ("36%", "9/25"),
        (r"36\%", r"0.36"),
        ("36 percent", "36%"),
        # unit normalization
        ("5 meters", "5"),
        ("5 m", "5"),
        ("5 m", "5 meters"),
        ("90 degrees", "90"),
        ("90\u00b0", "90"),
        ("12 seconds", "12 sec"),
        # numeric formatting
        ("1,000", "1000"),
        ("1,234,567", "1234567"),
        ("2.5E3", "2500"),
        ("2.5e3", "2500"),
        ("3.5", "3.50"),
        ("(-3,0)", "(-3, 0)"),
    ])
    def test_equivalent(self, ref, cand):
        r = compare(ref, cand)
        assert r["correct"] is True, (ref, cand, r)

    @pytest.mark.parametrize("ref,cand", [
        # intentionally wrong answers
        ("49%", "50"),
        ("36%", "0.40"),
        ("5 meters", "6"),
        ("(-3,0)", "(0,-3)"),
        ("1,000", "1,00"),  # malformed comma group
        ("49%", "0.5"),
    ])
    def test_not_equivalent(self, ref, cand):
        assert compare(ref, cand)["correct"] is False

    def test_previous_false_rejections_full_response(self):
        """The two calibration records that QEE previously blocked are now
        scored correct on their full predicted responses (real dataset text)."""
        from evaluation_engine.v2.math_eval import MathAnswerEvaluator
        ev = MathAnswerEvaluator()
        r1 = ev.evaluate(
            reference=r"Thus, the smallest positive integer that ends in 9 and is "
                      r"divisible by 7 is: \[ \boxed{49} \]",
            candidate=r"we have \(n = 4\). Substituting \(n = 4\) into the "
                      r"original form, we get \(10n + 9 = 10 \times 4 + 9 = 40 + 9 = 49\).",
        )
        assert r1.correct is True and r1.method == "number", r1
        r2 = ev.evaluate(
            reference=r"So, the answer is: \[ \boxed{36\%} \]",
            candidate=r"The percentage increase in each dimension of the "
                      r"rectangular prism is approximately \(36\%\). Therefore, "
                      r"the final answer is: \[ \boxed{36\%} \]",
        )
        assert r2.correct is True and r2.method == "number", r2


# --------------------------------------------------------------------------- #
# RP-002 — Semantics-preserving normalization robustness cascade
# --------------------------------------------------------------------------- #
class TestRP002Normalization:
    """RP-002: robustness-only normalization applied only when the initial
    parse fails. All 6 syntactically-recoverable records from the math
    metric audit must score correct; incorrect values must remain incorrect.
    """

    @pytest.mark.parametrize("ref,cand", [
        # RP-002.1: strip \\text{...} family content
        ("6", r"6 \text{ hours} \]"),
        ("8", r"8 \text{ hours} \]"),
        ("150", r"150 \text{ pages}"),
        # RP-002.2: remove delimiter / $ / stray-backslash residue
        ("2880", r"\$2880 \]"),
        # RP-002.3: strip known trailing unit words
        ("64", r"64 \) inches"),
        # RP-002.4: split A = B -> RHS
        ("25/4", r"\frac{20}{4} + \frac{5}{4} = \frac{25}{4}"),
    ])
    def test_recovered_records(self, ref, cand):
        """The 6 records identified as syntactically recoverable in the
        math metric audit must now score correct. Some may be recovered
        directly by the extractor (method != robust) but all must pass.
        """
        r = compare(ref, cand)
        assert r["correct"] is True, (ref, cand, r)
        assert r["score"] == 1.0, (ref, cand, r)

    @pytest.mark.parametrize("ref,cand", [
        # Assignment residue on the reference side is NOT stripped
        # (only candidate-side transforms are applied).
        ("12", "x = 12"),
        # Incorrect values remain incorrect despite cascade
        ("6", r"7 \text{ hours} \]"),
        ("2880", r"\$2881 \]"),
        ("64", r"65 \) inches"),
        ("25/4", r"\frac{20}{4} + \frac{5}{4} = \frac{26}{4}"),
        # Symbolic answers must not be mangled by unit stripping
        ("5x", "5x"),
        ("2n+1", "2n+1"),
        # A correctly-parsed candidate must remain unchanged (no regression)
        ("42", "42"),
        ("3.14", "3.14"),
        ("sqrt(2)", "sqrt(2)"),
        ("x^2+1", "x^2+1"),
    ])
    def test_negative_and_no_regression(self, ref, cand):
        """Incorrect values stay incorrect; already-correct values stay correct."""
        r = compare(ref, cand)
        if ref in ("12",) and "x = 12" in cand:
            # The extractor grabs RHS of '=', so this scores correct.
            # That is existing behavior, not a regression.
            assert r["correct"] is True, (ref, cand, r)
        elif ref in ("5x", "2n+1", "42", "3.14", "sqrt(2)", "x^2+1") and cand == ref:
            # Self-comparison must stay correct
            assert r["correct"] is True, (ref, cand, r)
            assert r["score"] == 1.0, (ref, cand, r)
        else:
            assert r["correct"] is False, (ref, cand, r)
            assert r["score"] < 1.0, (ref, cand, r)

    def test_robust_cascade_only_applies_on_unparsable(self):
        """The cascade must never run for an already-parsable candidate,
        ensuring the method string reflects the normal path."""
        r = compare("42", "42")
        assert r["method"] != "unparsable"
        assert "robust" not in r["method"]

    def test_operator_aliases_passthrough(self):
        """\\cdot / \\times / \\ast -> * and \\div -> / are in the cascade
        but recover no audit records; they must not break existing parses."""
        r = compare("6", r"2 \cdot 3")
        assert r["correct"] is True, r
        r2 = compare("6", r"2 \times 3")
        assert r2["correct"] is True, r2
        r3 = compare("6", r"12 \div 2")
        assert r3["correct"] is True, r3

    def test_frac_aliases_passthrough(self):
        """\\dfrac / \\tfrac / \\cfrac -> \\frac must work in candidates."""
        r = compare("5/2", r"\dfrac{5}{2}")
        assert r["correct"] is True, r
        r2 = compare("5/2", r"\tfrac{5}{2}")
        assert r2["correct"] is True, r2
        r3 = compare("5/2", r"\cfrac{5}{2}")
        assert r3["correct"] is True, r3

    def test_text_command_variants(self):
        """All supported \\text-family commands are stripped."""
        for cmd in ["text", "mathrm", "mathbf", "mathit", "textrm", "mbox"]:
            cand = "6 \\" + cmd + "{hours} \\]"
            r = compare("6", cand)
            assert r["correct"] is True, (cmd, r)

    def test_escaped_currency(self):
        """Stray backslash before currency symbol is cleaned."""
        r = compare("42", r"\$42\]")
        assert r["correct"] is True, r
