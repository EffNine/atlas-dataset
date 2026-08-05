"""code_eval.py — QEE v2 code / functional correctness evaluator.

Problem addressed
-----------------
QEE v1 had no way to judge code answers beyond "contains a code fence":
* any answer with a balanced ``` block scored near-maximum,
* correctness was never verified against the reference implementation,
* patch/diff answers (e.g. xarray / scikit-learn SWE tasks) were graded by
  raw substring overlap.

Design
------
The v2 code evaluator:
1. **Extracts code** from fenced blocks and detects patch/diff responses.
2. **Validates syntax** (Python via ``compile``/``ast``) so broken code is
   penalized instead of rewarded for containing keywords.
3. **Compares structurally** using a canonical AST token stream, not
   substrings — renames, formatting and comments do not hide a wrong body.
4. **Compares patches** by aligning the ``+`` (added) lines of the candidate
   and reference diffs.
5. **Runs unit tests** when the reference includes a test specification,
   giving true functional-correctness evidence.
6. **Fails closed**: if the answer cannot be interpreted as code or a patch,
   correctness is ``0`` for code-typed items (unverifiable is reserved for
   missing reference).

Determinism / safety
--------------------
* Stdlib-only; ``exec``/``compile`` run inside an isolated namespace with
  restricted builtins and are only invoked on locally supplied test payloads.
* Pure functions; no network; no mutation of inputs.
"""

from __future__ import annotations

import ast
import difflib
import re
from dataclasses import dataclass, field
from typing import Any

from .normalize import normalize_text

_FENCE_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
_PATCH_RE = re.compile(r"(?m)^(diff --git |--- a/|\+\+\+ b/|@@ )")
_ADDED_LINE_RE = re.compile(r"(?m)^\+")
_HUNK_LINE_RE = re.compile(r"^[+\- ]")
_BUILTIN_NAMES = frozenset(
    """abs all any bool bytearray bytes callable chr complex dict divmod
    enumerate filter float format frozenset getattr hasattr hash hex id int
    isinstance issubclass iter len list map max min next object oct ord pow
    range repr reversed round set slice sorted str sum tuple zip type vars
    isinstance str int float len range list dict set tuple min max sum abs
    round sorted enumerate zip filter map
    """.split()
)


@dataclass
class CodeResult:
    correct: bool | None
    score: float
    method: str
    reason: str = ""
    confidence: float = 0.0
    details: dict = field(default_factory=dict)


def extract_code_blocks(text: str) -> list[tuple[str, str]]:
    """Return [(language, code), ...] for all fenced code blocks."""
    blocks = []
    for m in _FENCE_RE.finditer(text):
        lang = (m.group(1) or "").strip()
        blocks.append((lang, m.group(2)))
    if not blocks and text.strip():
        blocks.append(("", text.strip()))
    return blocks


def is_patch(text: str) -> bool:
    return bool(_PATCH_RE.search(text or ""))


def extract_added_lines(text: str) -> list[str]:
    """Return the ``+`` lines (additions) of a unified diff, minus headers."""
    out = []
    for line in (text or "").splitlines():
        if line.startswith("+++"):
            continue
        if line.startswith("+"):
            out.append(line[1:].rstrip())
    return out


def validate_python_syntax(code: str) -> tuple[bool, str]:
    """Check Python syntax. Returns (ok, error_or_empty)."""
    if not code.strip():
        return False, "empty code"
    try:
        ast.parse(code)
        compile(code, "<atlas-code-eval>", "exec")
        return True, ""
    except SyntaxError as exc:
        return False, f"SyntaxError at line {exc.lineno}: {exc.msg}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def ast_tokens(code: str) -> list[str]:
    """Canonical token stream from a Python AST.

    Node types, names and numeric constants are kept; comments, whitespace,
    docstrings and string contents are dropped so formatting and prose do not
    influence structural similarity.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    tokens: list[str] = []
    for node in ast.walk(tree):
        tokens.append(type(node).__name__)
        if isinstance(node, ast.Name):
            tokens.append(f"id:{node.id}")
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                tokens.append(f"num:{node.value!r}")
            elif node.value is None:
                tokens.append("const:None")
            elif isinstance(node.value, bool):
                tokens.append(f"bool:{node.value!r}")
            # strings omitted (docstrings / messages)
    return tokens


def operator_signature(code: str) -> list[str]:
    """Sequence of arithmetic/comparison operators in source order.

    Catches logic changes that rename-resilient token streams miss: swapping
    ``+`` for ``*`` (or ``<`` for ``>``) changes this signature decisively.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    sig: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp):
            sig.append(type(node.op).__name__)
        elif isinstance(node, ast.UnaryOp):
            sig.append(type(node.op).__name__)
        elif isinstance(node, ast.Compare):
            sig.extend(type(op).__name__ for op in node.ops)
        elif isinstance(node, ast.BoolOp):
            sig.append(type(node.op).__name__)
    return sig


def structural_similarity(a: str, b: str) -> float:
    """Functional-structural similarity between two Python sources.

    Blend of AST-token similarity (0.5) and operator-signature similarity
    (0.5) so that operator/logic differences are not drowned out by the
    surrounding structural scaffolding.
    """
    ta, tb = ast_tokens(a), ast_tokens(b)
    if not ta or not tb:
        return 0.0
    token_ratio = difflib.SequenceMatcher(None, ta, tb).ratio()
    sa, sb = operator_signature(a), operator_signature(b)
    if not sa or not sb:
        return token_ratio
    op_ratio = difflib.SequenceMatcher(None, sa, sb).ratio()
    return 0.5 * token_ratio + 0.5 * op_ratio


def text_similarity(a: str, b: str) -> float:
    """Normalized token-level similarity for non-Python code."""
    na = normalize_text(a).split()
    nb = normalize_text(b).split()
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def patch_similarity(a: str, b: str) -> float:
    """Similarity of two unified diffs based on their added lines."""
    added_a = extract_added_lines(a)
    added_b = extract_added_lines(b)
    if not added_a or not added_b:
        # fall back to whole-patch text comparison
        fa = [ln for ln in a.splitlines() if _HUNK_LINE_RE.match(ln)]
        fb = [ln for ln in b.splitlines() if _HUNK_LINE_RE.match(ln)]
        if not fa or not fb:
            return 0.0
        return difflib.SequenceMatcher(None, fa, fb).ratio()
    return difflib.SequenceMatcher(None, added_a, added_b).ratio()


def run_function_tests(code: str, tests: list[dict]) -> dict:
    """Run (function_name, args, expected) unit tests against candidate code.

    ``tests`` is a list of dicts: ``{"name": str, "args": list, "expected": any}``.
    Execution is isolated: a fresh namespace, restricted builtins, no I/O.
    """
    results = {"passed": 0, "failed": 0, "errors": 0, "cases": []}
    ns: dict[str, Any] = {
        "__name__": "atlas_test_runner",
        "__builtins__": {
            name: __builtins__[name] for name in _BUILTIN_NAMES
            if name in __builtins__
        },
    }
    try:
        exec(compile(code, "<atlas-code-eval>", "exec"), ns)  # noqa: S102
    except Exception as exc:  # noqa: BLE001
        results["errors"] = len(tests)
        results["cases"] = [
            {"name": t.get("name", "?"), "status": "error",
             "detail": f"{type(exc).__name__}: {exc}"} for t in tests
        ]
        return results

    for t in tests:
        name = str(t.get("name", ""))
        case = {"name": name, "status": "error", "detail": ""}
        try:
            fn = ns.get(name)
            if fn is None:
                case["detail"] = f"function '{name}' not defined"
            else:
                actual = fn(*t.get("args", []))
                if actual == t.get("expected"):
                    case["status"] = "passed"
                    results["passed"] += 1
                else:
                    case["status"] = "failed"
                    results["failed"] += 1
                    case["detail"] = (
                        f"expected {t.get('expected')!r}, got {actual!r}"
                    )
        except Exception as exc:  # noqa: BLE001
            case["detail"] = f"{type(exc).__name__}: {exc}"
            results["errors"] += 1
        results["cases"].append(case)
    return results


class CodeAnswerEvaluator:
    """Evaluate a candidate code/patch answer against a reference answer."""

    def __init__(self, patch_weight: float = 1.0,
                 test_weight: float = 0.4) -> None:
        self.patch_weight = patch_weight
        self.test_weight = test_weight

    def evaluate(self, question: str = "", reference: str = "",
                 candidate: str = "", tests: list[dict] | None = None) -> CodeResult:
        """Score candidate against reference for code/patch answers."""
        if not candidate.strip():
            return CodeResult(
                correct=False, score=0.0, method="empty",
                reason="empty candidate answer",
            )

        candidate_is_patch = is_patch(candidate)
        reference_is_patch = is_patch(reference)

        if reference_is_patch or candidate_is_patch:
            if not reference.strip():
                return CodeResult(
                    correct=None, score=0.5, method="unverifiable",
                    reason="patch answer provided but no reference patch",
                    confidence=0.3,
                )
            sim = patch_similarity(reference, candidate)
            ratio = self.patch_weight * sim
            return CodeResult(
                correct=ratio >= 0.85,
                score=round(min(1.0, ratio), 4),
                method="patch",
                reason=f"patch added-line similarity {sim:.2f}",
                confidence=0.85,
                details={"patch_similarity": round(sim, 4)},
            )

        # Non-patch code: extract candidate + reference code.
        cand_blocks = extract_code_blocks(candidate)
        ref_blocks = extract_code_blocks(reference)
        cand_code = cand_blocks[0][1] if cand_blocks else ""
        ref_code = ref_blocks[0][1] if ref_blocks else reference.strip()

        if not ref_code:
            # No reference code — grade candidate quality only (syntax + structure).
            if cand_code and self._is_python(cand_blocks[0][0]):
                ok, err = validate_python_syntax(cand_code)
                if not ok:
                    return CodeResult(
                        correct=False, score=0.4, method="syntax",
                        reason=f"candidate code has syntax error: {err}",
                        confidence=0.8,
                    )
                return CodeResult(
                    correct=None, score=0.5, method="unverifiable_no_reference",
                    reason="syntax-valid code but no reference implementation to compare",
                    confidence=0.5,
                )
            return CodeResult(
                correct=None, score=0.5, method="unverifiable_no_reference",
                reason="no reference or candidate code extracted",
                confidence=0.3,
            )

        lang = cand_blocks[0][0] if cand_blocks else ""
        if self._is_python(lang):
            ok_c, err_c = validate_python_syntax(cand_code)
            if not ok_c:
                return CodeResult(
                    correct=False, score=0.3, method="syntax",
                    reason=f"candidate code has syntax error: {err_c}",
                    confidence=0.85,
                )
            struct = structural_similarity(cand_code, ref_code)

            if tests:
                tr = run_function_tests(cand_code, tests)
                total = tr["passed"] + tr["failed"] + tr["errors"]
                pass_rate = tr["passed"] / total if total else 0.0
                score = 0.3 * struct + 0.7 * self.test_weight * pass_rate
                # Normalize: tests dominate when provided.
                score = min(1.0, struct * (1 - self.test_weight) + pass_rate * self.test_weight)
                return CodeResult(
                    correct=pass_rate >= 0.9 and struct >= 0.5,
                    score=round(score, 4),
                    method="syntax_structural_tests",
                    reason=(f"syntax ok; structural similarity {struct:.2f}; "
                            f"tests {tr['passed']}/{total} passed"),
                    confidence=0.9,
                    details={
                        "structural_similarity": round(struct, 4),
                        "test_results": tr,
                    },
                )
            return CodeResult(
                correct=struct >= 0.85,
                score=round(struct, 4),
                method="syntax_structural",
                reason=f"syntax ok; structural similarity {struct:.2f}",
                confidence=0.85,
                details={"structural_similarity": round(struct, 4)},
            )

        # Non-Python code: token-level similarity fallback.
        sim = text_similarity(cand_code, ref_code)
        return CodeResult(
            correct=sim >= 0.8,
            score=round(sim, 4),
            method="text_similarity",
            reason=f"non-python code token similarity {sim:.2f}",
            confidence=0.6,
        )

    @staticmethod
    def _is_python(lang: str) -> bool:
        return lang in ("", "python", "py", "python3")


def compare(reference: str, candidate: str,
            tests: list[dict] | None = None) -> dict:
    """Convenience wrapper used by tests/CLI."""
    r = CodeAnswerEvaluator().evaluate(reference=reference, candidate=candidate,
                                       tests=tests)
    return {
        "correct": r.correct,
        "score": r.score,
        "method": r.method,
        "reason": r.reason,
        "confidence": r.confidence,
        "details": r.details,
    }
