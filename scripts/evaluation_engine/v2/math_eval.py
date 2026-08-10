"""math_eval.py — QEE v2 mathematical correctness evaluator.

Problem addressed
-----------------
QEE v1 scored math-adjacent answers with keyword hits and digit counts:
* any answer containing domain words + a number scored near-maximum,
* "correct" was a strict substring check, so equivalent expressions and
  paraphrased results were misjudged,
* a wrong number surrounded by the right keywords scored as correct.

Design
------
The v2 math evaluator:
1. **Extracts the final answer** from both reference and candidate text
   (``\\boxed{...}``, "answer:", last equation, trailing number/expression),
   so irrelevant prose does not affect the verdict.
2. **Normalizes notation** (Unicode, LaTeX, spacing, spoken operators) so
   ``x²`` and ``x^2`` and "x squared" compare identically.
3. **Checks expression equivalence numerically**: both expressions are parsed
   into a safe AST and evaluated at deterministic sample points, supporting
   algebraically-equivalent forms (``(x+1)^2`` == ``x^2+2x+1``) with a
   relative tolerance. No substring matching is used.
4. **Fails closed**: if no final answer can be extracted or expressions cannot
   be compared, the record is scored ``0.5`` with low confidence rather than
   guessing a correctness verdict.

Determinism / safety
--------------------
* Stdlib-only. The AST evaluator whitelists arithmetic + a fixed function set.
* Seeded deterministic sampling (no ``random`` at runtime unless needed, and
  then with a fixed seed).
* Pure functions; no mutation of inputs; no network.
"""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass, field
from fractions import Fraction

from .normalize import (
    NUMBER_WORDS,
    normalize_math,
    normalize_text,
    robust_normalize_cascade,
    spoken_to_symbolic,
    token_set_similarity,
)

# Relative tolerance used by numeric equivalence checks.
REL_TOL = 1e-6
ABS_TOL = 1e-9

# Deterministic sample points for expression equivalence.
_BASE_SAMPLES = [0.0, 1.0, -1.0, 2.0, -2.0, 0.5, 1.5, -0.5, 3.0, -3.0]

# Allowed AST node types for safe math evaluation.
_ALLOWED_NODES = {
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult,
    ast.Div, ast.Pow, ast.Mod, ast.USub, ast.UAdd, ast.Constant, ast.Name,
    ast.Call, ast.Load, ast.Tuple, ast.List,
}

# Allowed function/constant names plus common free variables bound at
# evaluation time. Free variables are bound to the sample point during
# equivalence sampling so single-variable expressions compare correctly.
_MATH_NS = {
    "sqrt": math.sqrt, "log": math.log, "ln": math.log, "log10": math.log10,
    "log2": math.log2, "exp": math.exp, "abs": abs, "floor": math.floor,
    "ceil": math.ceil, "round": round, "sin": math.sin, "cos": math.cos,
    "tan": math.tan, "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    "min": min, "max": max, "pi": math.pi, "e": math.e, "tau": math.tau,
}

_FREE_VARS = frozenset(
    "x y z n m a b c t k p q r u v w i j".split()
)

# Final-answer extraction. NOTE: \boxed extraction uses a brace-balanced
# parser (see _boxed_blocks) rather than a character-class regex, because the
# old r"\\boxed\{([^{}]*)\}" could not capture contents containing nested
# braces, e.g. \boxed{\frac{5}{2}}, \boxed{\sqrt{3}}, \boxed{(-3,0)}.
_ANSWER_RE = re.compile(
    r"(?i)\b(?:final\s+)?(?:answer|result)(?:\s+is\s+|\s*[=:]\s*|\s+)(.*)$"
)
_EQUALS_RE = re.compile(r"(?:^|[=:\s])([-+]?\s*(?:[0-9]|[a-z0-9(]))")


def insert_implicit_multiplication(expr: str) -> str:
    """Insert '*' where convention implies multiplication.

    Handles ``4x`` -> ``4*x``, ``2(x+1)`` -> ``2*(x+1)``,
    ``(x+1)(x-1)`` -> ``(x+1)*(x-1)``, and ``x y`` -> ``x*y``.
    Conservative: never rewrites already-typed operators.
    """
    out = re.sub(r"(\d)([a-zA-Z(])", r"\1*\2", expr)
    out = re.sub(r"\)(\()", r")*(", out)
    # Handle bare juxtaposition between a number and a sqrt call, e.g. 2sqrt(3).
    out = re.sub(r"(\d)(sqrt\()", r"\1*\2", out)
    return out


class MathParseError(ValueError):
    """Raised when a normalized expression cannot be safely parsed."""


class SafeMathEvaluator:
    """Parse and evaluate a whitelisted math expression safely."""

    def __init__(self, expr: str) -> None:
        self.raw = expr
        self.normalized = normalize_math(expr)
        self.parsed: ast.Expression | None = None
        self.is_number: bool = False
        self.number: Fraction | float | None = None
        self.error: str | None = None
        self._parse()

    def _parse(self) -> None:
        if not self.normalized:
            self.error = "empty expression"
            return
        # Try exact rational parse first (covers "1/2", "-3", "4.0").
        try:
            self.number = Fraction(self.normalized)
            self.is_number = True
            return
        except (ValueError, ZeroDivisionError):
            pass
        try:
            self.number = float(self.normalized)
            self.is_number = True
            return
        except ValueError:
            pass

        prepared = insert_implicit_multiplication(self.normalized)
        prepared = prepared.replace("^", "**")
        try:
            tree = ast.parse(prepared, mode="eval")
        except SyntaxError as exc:
            self.error = f"parse error: {exc}"
            return
        if not self._validate(tree):
            self.error = "unsupported syntax"
            return
        try:
            compile(tree, "<math-eval>", "eval")  # bytecode check
        except Exception as exc:  # noqa: BLE001 - report any compile failure
            self.error = f"compile error: {exc}"
            return
        self.parsed = tree

    def _validate(self, node: ast.AST) -> bool:
        if not isinstance(node, tuple(_ALLOWED_NODES)):
            return False
        for child in ast.iter_child_nodes(node):
            if not self._validate(child):
                return False
        if isinstance(node, ast.Name):
            if node.id not in _MATH_NS and node.id not in _FREE_VARS:
                return False
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _MATH_NS:
                return False
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float, complex)):
            return False
        if isinstance(node, ast.Constant) and isinstance(node.value, complex):
            return False
        return True

    @property
    def parseable(self) -> bool:
        return self.parsed is not None or self.is_number

    def evaluate(self, x: float) -> float | tuple | list | None:
        """Evaluate the expression at a given sample point.

        Scalars return a float; coordinates/vectors expressed as ``(a,b)`` or
        ``[a,b]`` return a tuple/list so they can be compared element-wise.
        """
        if self.is_number:
            num = self.number
            return float(num) if num is not None else None
        if self.parsed is None:
            return None
        ns = dict(_MATH_NS)
        ns["__builtins__"] = {}
        for var in _FREE_VARS:
            ns[var] = float(x)
        try:
            result = eval(  # noqa: S307 - AST-whitelisted + closed namespace
                compile(self.parsed, "<math-eval>", "eval"), ns
            )
        except Exception:  # noqa: BLE001 - domain errors are expected
            return None
        if isinstance(result, complex):
            return None
        if isinstance(result, (tuple, list)):
            vals = [_scalarize(v) for v in result]
            if any(v is None for v in vals):
                return None
            return tuple(vals)
        return float(result)


def _scalarize(value):
    """Convert an AST evaluation value to a numeric shape (scalar or tuple)."""
    if isinstance(value, complex):
        return None
    if isinstance(value, (tuple, list)):
        vals = [_scalarize(x) for x in value]
        if any(x is None for x in vals):
            return None
        return tuple(vals)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def values_close(a, b) -> bool:
    """Relative + absolute tolerance comparison, supporting scalar, tuple, and
    list values (coordinates/vectors compared element-wise)."""
    if isinstance(a, (tuple, list)) or isinstance(b, (tuple, list)):
        if not (isinstance(a, (tuple, list)) and isinstance(b, (tuple, list))):
            return False
        if len(a) != len(b):
            return False
        return all(values_close(x, y) for x, y in zip(a, b))
    if a == b:
        return True
    try:
        denom = max(1.0, abs(a), abs(b))
        return abs(a - b) <= REL_TOL * denom + ABS_TOL
    except TypeError:
        return False


def _try_equivalent(ref_expr: str, cand_expr: str,
                    min_samples: int = 3) -> tuple[bool, str, int]:
    """Core equivalence check between two expressions.

    Returns (equivalent, method, n_valid_samples).
    """
    r = SafeMathEvaluator(ref_expr)
    c = SafeMathEvaluator(cand_expr)

    if not r.parseable or not c.parseable:
        return False, "unparsable", 0

    if r.is_number and c.is_number:
        rn, cn = r.number, c.number
        if rn is None or cn is None:
            return False, "number_missing", 0
        return (values_close(float(rn), float(cn)), "number", 1)

    if not (r.parseable and c.parseable):
        return False, "unparsable", 0
    if r.is_number and c.parsed is None:
        return False, "non-numeric_uncomparable", 0
    if c.is_number and r.parsed is None:
        return False, "non-numeric_uncomparable", 0

    samples = list(_BASE_SAMPLES)
    ok = 0
    for x in samples:
        rv, cv = r.evaluate(x), c.evaluate(x)
        if rv is None or cv is None:
            continue
        if not values_close(rv, cv):
            return False, "numeric_sampling", ok
        ok += 1
        if ok >= 6:
            break
    if ok < min_samples:
        return False, "insufficient_samples", ok
    return True, "numeric_sampling", ok


def expressions_equivalent(ref_expr: str, cand_expr: str,
                           min_samples: int = 3) -> tuple[bool, str, int]:
    """Check whether two expressions are numerically equivalent.

    Returns (equivalent, method, n_valid_samples).

    RP-002: After the initial parse attempt fails, a robustness cascade of
    purely syntactic normalizations is tried on the candidate only. These
    transforms are safe: they only affect inputs that were previously
    unparsable and leave every previously-scored input byte-identical.
    """
    eq, method, n = _try_equivalent(ref_expr, cand_expr, min_samples)
    if eq:
        return eq, method, n

    # RP-002: robustness cascade — only applied when initial parse fails.
    for name, cand_norm in robust_normalize_cascade(cand_expr):
        if cand_norm == cand_expr:
            continue
        eq, method, n = _try_equivalent(ref_expr, cand_norm, min_samples)
        if eq:
            return True, f"robust({name})", n

    return False, "unparsable", 0


def _boxed_blocks(text: str) -> list[str]:
    """Return the contents of every ``\\boxed{...}`` via a brace-balanced scan.

    A naive ``[^{}]*`` regex stops at the first inner brace and yields nothing
    for ``\\boxed{\\frac{5}{2}}``, ``\\boxed{\\sqrt{3}}``, or a coordinate
    ``\\boxed{(-3,0)}``. This parser tracks brace depth so nested contents are
    captured whole.
    """
    blocks: list[str] = []
    i = 0
    n = len(text)
    token = "\\boxed"
    while True:
        start = text.find(token, i)
        if start == -1:
            break
        j = start + len(token)
        while j < n and text[j].isspace():
            j += 1
        if j >= n or text[j] != "{":
            i = start + len(token)
            continue
        depth = 0
        k = j
        while k < n:
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        if depth != 0:
            break
        blocks.append(text[j + 1 : k])
        i = k + 1
    return blocks


def _best_boxed(text: str) -> str | None:
    matches = _boxed_blocks(text)
    if matches:
        return matches[-1].strip()
    return None


def extract_final_answer(text: str) -> str:
    """Extract the final answer from math response text.

    Priority:
      1. last ``\\boxed{...}``,
      2. an "answer" / "final answer is" / "result:" line,
      3. the RHS of the last ``=`` on a mathy line,
      4. the last line that looks like an expression (contains digits and/or
         operators),
      5. fallback: normalized full text (best effort).
    """
    if not text:
        return ""

    boxed = _best_boxed(text)
    if boxed:
        return boxed

    # "answer: ..." / "final answer is ..." — take remainder of the line.
    for line in text.splitlines():
        m = _ANSWER_RE.search(line)
        if m:
            rest = m.group(1).strip().rstrip(".,")
            if rest:
                return rest

    # RHS of the last '=' outside boxed content.
    eq_positions = [m.start() for m in re.finditer(r"(?<![<>=!])=(?!=)", text)]
    if eq_positions:
        rhs = text[eq_positions[-1] + 1:]
        # RP-001: guard empty RHS (text ending in a bare '='); previously this
        # raised IndexError from splitlines()[0]. Scoring is unchanged for all
        # non-empty RHS (the ``if rhs`` below now simply falls through).
        rhs = rhs.splitlines()[0].strip().rstrip(".,;") if rhs else ""
        if rhs:
            return rhs

    # Last line that carries math signals.
    math_lines = [
        ln.strip().rstrip(".,;")
        for ln in text.splitlines()
        if re.search(r"[0-9]|[-+*/^()]", ln) and ln.strip()
    ]
    if math_lines:
        return math_lines[-1]

    # Fallback: a bare answer written in words ("seven", "x divided by two")
    # is valid only when it carries math signals after spoken->symbolic.
    norm = spoken_to_symbolic(normalize_text(text))
    if re.search(r"[0-9]|[-+*/^()]|\b(" + "|".join(NUMBER_WORDS) + r")\b", norm):
        return norm
    return ""


def _normalized_similarity(a: str, b: str) -> float:
    """Structural similarity for partial credit when numeric comparison fails."""
    ta = normalize_text(a).split()
    tb = normalize_text(b).split()
    return token_set_similarity(ta, tb)


@dataclass
class MathResult:
    correct: bool | None
    score: float
    method: str
    extracted_reference: str = ""
    extracted_candidate: str = ""
    normalized_reference: str = ""
    normalized_candidate: str = ""
    reason: str = ""
    confidence: float = 0.0
    details: dict = field(default_factory=dict)


class MathAnswerEvaluator:
    """Evaluate a candidate math answer against a reference answer."""

    def __init__(self, rel_tol: float = REL_TOL, min_samples: int = 3) -> None:
        self.rel_tol = rel_tol
        self.min_samples = min_samples

    def evaluate(self, question: str = "", reference: str = "",
                 candidate: str = "") -> MathResult:
        """Compare a candidate answer to a reference answer.

        ``reference`` may be empty when no canonical answer exists; in that
        case correctness is marked unverifiable (fail-closed).
        """
        ref = extract_final_answer(reference)
        cand = extract_final_answer(candidate)

        if not cand:
            return MathResult(
                correct=False, score=0.0, method="no_final_answer",
                extracted_reference=ref, extracted_candidate="",
                reason="no extractable final answer in candidate",
                confidence=0.2,
            )

        if not ref:
            return MathResult(
                correct=None, score=0.5, method="unverifiable",
                extracted_reference="", extracted_candidate=cand,
                reason="no reference final answer available; correctness not verifiable",
                confidence=0.3,
            )

        equivalent, method, n_ok = expressions_equivalent(ref, cand)
        n_ref = normalize_math(ref)
        n_cand = normalize_math(cand)

        if equivalent:
            return MathResult(
                correct=True, score=1.0, method=method,
                extracted_reference=ref, extracted_candidate=cand,
                normalized_reference=n_ref, normalized_candidate=n_cand,
                reason=f"expressions equivalent ({method}, {n_ok} sample(s))",
                confidence=0.95 if n_ok >= 3 else 0.7,
            )

        # Not equivalent — award partial credit only when there is real
        # structural overlap, so keyword-stuffed wrong answers get ~0.
        sim = _normalized_similarity(ref, cand)
        partial = max(0.0, min(1.0, sim * 0.5))
        return MathResult(
            correct=False, score=round(partial, 4), method=method,
            extracted_reference=ref, extracted_candidate=cand,
            normalized_reference=n_ref, normalized_candidate=n_cand,
            reason=f"not equivalent ({method}); structural similarity {sim:.2f}",
            confidence=0.9,
        )


def compare(a: str, b: str) -> dict:
    """Direct (question-free) comparison convenience used by tests/CLI."""
    r = MathAnswerEvaluator().evaluate(reference=a, candidate=b)
    return {
        "correct": r.correct,
        "score": r.score,
        "method": r.method,
        "extracted_reference": r.extracted_reference,
        "extracted_candidate": r.extracted_candidate,
        "reason": r.reason,
        "confidence": r.confidence,
    }
