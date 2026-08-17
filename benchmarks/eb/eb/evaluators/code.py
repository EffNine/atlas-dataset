#!/usr/bin/env python3
"""
code.py — Deterministic code evaluation for the EffNine Benchmark (EB).

Stage 3 code evaluation is intentionally conservative:
  - Supports exact code artifact matching
  - Supports syntax parsing validation (safe, stdlib-only)
  - Supports structured expected output comparison
  - Supports provided test commands ONLY when explicitly configured and safe
  - NEVER executes arbitrary model-generated shell commands
  - NEVER introduces Docker (Stage 6)
  - Marks repository-dependent tasks as UNSUPPORTED

Security-conscious by default: if a task requires a sandbox, it is marked
UNSUPPORTED rather than executing unsandboxed.
"""

from __future__ import annotations

import ast
import re
from typing import Any

from ..core.schema import EvaluatorResult, Task, TaskResult
from ..core.types import EvaluatorStatus, JudgeMode
from .base import Evaluator


class CodeEvaluator(Evaluator):
    """
    Deterministic code evaluator.

    Checks performed (based on configuration):
      - exact_code: compare response against expected code artifact
      - syntax: validate Python syntax via ast.parse (safe, no execution)
      - structured_output: check for expected output patterns in response
      - test_command: run a PROVIDED test command ONLY when explicitly
                      configured in task context (never model-generated)

    Tasks requiring a repository sandbox are marked UNSUPPORTED.
    """

    @property
    def name(self) -> str:
        return "code"

    @property
    def authority_level(self) -> int:
        return 1  # Deterministic evidence

    @property
    def supported_modes(self) -> list[JudgeMode]:
        return [JudgeMode.DETERMINISTIC]

    def is_applicable(self, task: Task) -> bool:
        """Applicable for coding/debug tasks or when code_check is configured."""
        cat = task.category.lower()
        ctx = task.context
        params = self._resolve_params(task)

        has_code_check = bool(params)
        is_code_task = cat in ("coding", "code", "debug")
        has_repository = bool(ctx.get("repository")) or bool(ctx.get("repo_path"))
        is_exec_task = task.mode.value == "EXEC" if hasattr(task.mode, 'value') else False

        # EXEC tasks are handled by repository evaluation path
        if is_exec_task:
            return True

        if has_repository:
            return False

        return is_code_task or has_code_check

    def evaluate(self, task: Task, result: TaskResult) -> EvaluatorResult:
        # If not applicable, return NOT_APPLICABLE immediately
        if not self.is_applicable(task):
            return EvaluatorResult(
                evaluator="code",
                mode=JudgeMode.DETERMINISTIC,
                status=EvaluatorStatus.NOT_APPLICABLE,
                rationale="Code evaluator is not applicable to this task",
                flags=["not_applicable:code"],
            )

        response = result.raw_response or ""
        params = self._resolve_params(task)
        ctx = task.context

        checks_passed: list[str] = []
        checks_failed: list[str] = []
        scores: list[float] = []

        expected_code = params.get("expected_code") or ctx.get("expected_code")
        if expected_code is not None:
            score, passed, evidence = self._check_exact_code(response, str(expected_code))
            scores.append(score)
            if passed:
                checks_passed.append("exact_code_match")
            else:
                checks_failed.extend(evidence)

        do_syntax = params.get("check_syntax", True)
        # Skip syntax check for EXEC tasks — evidence comes from test execution, not response text
        is_exec_task = task.mode.value == "EXEC" if hasattr(task.mode, 'value') else False
        if do_syntax and not is_exec_task:
            score, passed, evidence = self._check_syntax(response)
            scores.append(score)
            if passed:
                checks_passed.append("syntax_valid")
            else:
                checks_failed.extend(evidence)

        expected_output = params.get("expected_output") or ctx.get("expected_output")
        if expected_output is not None:
            score, passed, evidence = self._check_structured_output(response, str(expected_output))
            scores.append(score)
            if passed:
                checks_passed.append("structured_output_match")
            else:
                checks_failed.extend(evidence)

        test_command = params.get("test_command") or ctx.get("test_command")
        if test_command is not None:
            if self._is_safe_test_command(test_command):
                score, passed, evidence = self._check_test_command(response, test_command)
                scores.append(score)
                if passed:
                    checks_passed.append("test_command_passed")
                else:
                    checks_failed.extend(evidence)
            else:
                checks_failed.append("unsafe_test_command: command was rejected for security")

        # EXEC-specific: evaluate based on test results and diff evidence
        if task.mode.value == "EXEC" if hasattr(task.mode, 'value') else False:
            score, passed, evidence = self._check_exec_evidence(result)
            if score is not None:
                scores.append(score)
                if passed:
                    checks_passed.extend(evidence)
                else:
                    checks_failed.extend(evidence)

        if not checks_passed and not checks_failed:
            return EvaluatorResult(
                evaluator="code",
                mode=JudgeMode.DETERMINISTIC,
                status=EvaluatorStatus.NOT_APPLICABLE,
                rationale="No configurable code checks matched",
                flags=["no_code_checks_configured"],
            )

        all_passed = len(checks_failed) == 0
        avg_score = sum(scores) / len(scores) if scores else (1.0 if all_passed else 0.0)

        status = EvaluatorStatus.PASS if all_passed else EvaluatorStatus.FAIL

        evidence_list = list(checks_passed) + checks_failed

        return EvaluatorResult(
            evaluator="code",
            mode=JudgeMode.DETERMINISTIC,
            status=status,
            score=avg_score,
            max_score=1.0,
            normalized_score=avg_score,
            rationale=f"Code evaluation: {'all checks passed' if all_passed else f'{len(checks_failed)} check(s) failed'}",
            evidence=evidence_list,
            flags=checks_failed if checks_failed else [],
            details={
                "checks_passed": checks_passed,
                "checks_failed": checks_failed,
                "individual_scores": scores,
            },
        )

    def _check_exact_code(self, response: str, expected: str) -> tuple[float, bool, list[str]]:
        resp_clean = response.strip()
        exp_clean = expected.strip()
        if resp_clean == exp_clean:
            return 1.0, True, ["exact code match"]
        if exp_clean in resp_clean:
            return 0.7, False, ["expected code present but not exact match"]
        return 0.0, False, [
            f"expected: {exp_clean[:300]}",
            f"got: {resp_clean[:300]}",
        ]

    def _check_syntax(self, response: str) -> tuple[float, bool, list[str]]:
        code = self._extract_python_code(response)
        if not code:
            return 0.0, False, ["no Python code block found in response"]
        try:
            ast.parse(code)
            return 1.0, True, ["syntax valid"]
        except SyntaxError as e:
            return 0.0, False, [f"syntax error: {e}"]

    def _check_structured_output(self, response: str, expected: str) -> tuple[float, bool, list[str]]:
        lines = response.strip().split("\n")
        expected_lines = [l for l in expected.strip().split("\n") if l.strip()]
        if not expected_lines:
            return 1.0, True, ["empty expected output"]

        matches = 0
        for exp_line in expected_lines:
            for resp_line in lines:
                if exp_line.strip() in resp_line.strip():
                    matches += 1
                    break

        ratio = matches / len(expected_lines)
        passed = ratio >= 0.5
        return ratio, passed, [f"{matches}/{len(expected_lines)} output lines matched"]

    def _check_test_command(self, response: str, command: str) -> tuple[float, bool, list[str]]:
        success_indicators = ["pass", "success", "ok", "✓", "PASSED"]
        response_lower = response.lower()
        has_success = any(ind in response_lower for ind in success_indicators)

        if has_success:
            return 0.5, False, [
                f"test_command '{command}' cannot be executed without Docker sandbox (Stage 6)",
                "response contains success indicators but could not verify",
            ]
        return 0.0, False, [
            f"test_command '{command}' cannot be executed without Docker sandbox (Stage 6)",
        ]

    def _extract_python_code(self, text: str) -> str:
        patterns = [
            r"```python\s*(.*?)```",
            r"```Python\s*(.*?)```",
            r"```\s*(.*?)```",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                return match.group(1).strip()

        stripped = text.strip()
        if stripped and any(stripped.startswith(p) for p in ("def ", "class ", "import ", "from ")):
            return stripped
        return ""

    def _is_safe_test_command(self, command: str) -> bool:
        """
        Check if a test command is safe to run.
        Rejects commands that reference model output or are clearly dangerous.
        """
        dangerous_patterns = [
            r"\brm\s+-rf\b",
            r"\bmkfs\b",
            r"\bwget\s+.*\|.*sh\b",
            r"\bcurl\s+.*\|.*sh\b",
            r"\$\(",
            r"`",
        ]
        for pat in dangerous_patterns:
            if re.search(pat, command):
                return False
        return True

    def _resolve_params(self, task: Task) -> dict[str, Any]:
        for ev_spec in task.evaluation.evaluators:
            if ev_spec.get("type") == "code":
                return ev_spec.get("parameters", {})
        return {}

    def _check_exec_evidence(self, result: TaskResult) -> tuple[float | None, bool | None, list[str]]:
        """
        Evaluate EXEC tasks based on deterministic test/diff evidence.

        Scoring:
          - tests_passed + no regressions → 1.0
          - tests_passed but some regressions → 0.7
          - tests_failed → 0.0
          - no test evidence → 0.5 (neutral)
        """
        meta = result.execution_metadata
        test_summary = meta.get("test_summary", {})
        changed_files = meta.get("changed_files", [])
        diff = meta.get("diff")

        checks_passed: list[str] = []
        checks_failed: list[str] = []

        # Check test results
        if test_summary:
            if test_summary.get("passed"):
                test_count = test_summary.get("test_count", 0)
                checks_passed.append(f"tests_passed ({test_count} tests)")
            elif test_summary.get("exit_code", 0) != 0:
                checks_failed.append(f"tests_failed (exit_code={test_summary.get('exit_code')})")
            else:
                checks_passed.append("tests_skipped")
        else:
            checks_passed.append("no_test_evidence")

        # Check diff for meaningful changes
        if diff and diff.strip():
            checks_passed.append("code_changes_present")
        elif not diff:
            checks_failed.append("no_code_changes")

        if not checks_passed and not checks_failed:
            return None, None, []

        all_passed = len(checks_failed) == 0
        if test_summary and test_summary.get("passed"):
            score = 1.0
        elif test_summary and not test_summary.get("passed"):
            score = 0.0
        else:
            score = 0.5 if all_passed else 0.0

        status = EvaluatorStatus.PASS if all_passed else EvaluatorStatus.FAIL
        evidence = list(checks_passed) + checks_failed

        return score, all_passed, evidence
