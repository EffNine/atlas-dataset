#!/usr/bin/env python3
"""
repository.py — EXEC execution mode runner for the EffNine Benchmark (EB).

Handles repository-based tasks where the model must:
  1. Inspect source code inside a Docker sandbox
  2. Edit files to fix bugs or implement features
  3. Run tests and verification commands
  4. Produce deterministic pass/fail results

The runner provides a bounded tool interface (list_files, read_file, write_file,
patch_file, run_command, run_tests) that executes exclusively inside the sandbox.
Host filesystem is never directly accessible.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..adapters.base import ModelAdapter, ModelRequest
from ..core.schema import Task, TaskResult
from ..core.types import ExecutionMode
from ..evaluators.dispatcher import EvaluatorDispatcher
from ..paths import repositories_dir
from ..sandbox.base import ExecResult
from ..sandbox.manager import SandboxManager
from ..sandbox.security import SecurityPolicy, is_path_safe
from .base import RunContext, Runner, TaskStatus


# ---------------------------------------------------------------------------
# Tool protocol
# ---------------------------------------------------------------------------


@dataclass
class ToolCall:
    """A single tool invocation by the model."""

    tool_name: str
    arguments: dict[str, Any]
    call_id: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "call_id": self.call_id,
            "timestamp": self.timestamp,
        }


@dataclass
class ToolResult:
    """Result of a tool execution inside the sandbox."""

    call_id: str
    tool_name: str
    success: bool
    output: str = ""
    error: str | None = None
    exit_code: int = 0
    duration_s: float = 0.0
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "success": self.success,
            "output": self.output[:2000],
            "error": self.error,
            "exit_code": self.exit_code,
            "duration_s": self.duration_s,
            "truncated": self.truncated,
        }


# ---------------------------------------------------------------------------
# Repository fixture management
# ---------------------------------------------------------------------------


@dataclass
class RepositoryFixture:
    """Metadata about a benchmark repository fixture."""

    fixture_id: str
    version: str = "1.0"
    language: str = ""
    framework: str = ""
    image: str = ""
    source_path: str = "source"
    test_command: str = ""
    lint_command: str | None = None
    typecheck_command: str | None = None
    timeout: float = 300.0
    expected_base_state: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    fixture_hash: str = ""
    workspace_path: str = "/workspace"

    @classmethod
    def from_manifest(cls, manifest_path: Path) -> "RepositoryFixture":
        """Load fixture metadata from a fixture.json manifest."""
        with manifest_path.open(encoding="utf-8") as f:
            data = json.load(f)
        return cls(
            fixture_id=data["id"],
            version=data.get("version", "1.0"),
            language=data.get("language", ""),
            framework=data.get("framework", ""),
            image=data.get("image", ""),
            source_path=data.get("source_path", "source"),
            test_command=data.get("test_command", ""),
            lint_command=data.get("lint_command"),
            typecheck_command=data.get("typecheck_command"),
            timeout=data.get("timeout", 300.0),
            expected_base_state=data.get("expected_base_state", {}),
            metadata=data.get("metadata", {}),
        )

    def compute_hash(self, fixtures_root: Path) -> str:
        """Compute SHA-256 of the fixture source directory contents."""
        # Fixtures are stored under repositories/fixtures/<fixture_id>/
        fixture_dir = fixtures_root / "fixtures" / self.fixture_id
        h = hashlib.sha256()
        for fpath in sorted(fixture_dir.rglob("*")):
            if fpath.is_file() and "/.git/" not in str(fpath):
                h.update(fpath.read_bytes())
                h.update(f"{fpath.relative_to(fixture_dir)}\n".encode())
        self.fixture_hash = h.hexdigest()[:16]
        return self.fixture_hash


# ---------------------------------------------------------------------------
# EXEC runner context
# ---------------------------------------------------------------------------


@dataclass
class ExecRunContext:
    """Mutable execution context for an EXEC task."""

    run_id: str
    task_id: str
    repeat_id: str
    workspace: Path
    tool_history: list[ToolCall] = field(default_factory=list)
    command_history: list[dict[str, Any]] = field(default_factory=list)
    file_changes: list[dict[str, Any]] = field(default_factory=list)
    test_results: dict[str, Any] = field(default_factory=dict)
    timestamps: dict[str, str] = field(default_factory=dict)
    sandbox_id: str = ""
    sandbox_image: str = ""
    sandbox_policy: SecurityPolicy | None = None

    def record_tool_call(self, call: ToolCall) -> None:
        self.tool_history.append(call)

    def record_command(self, command: list[str], result: ExecResult) -> None:
        self.command_history.append({
            "command": command,
            "exit_code": result.exit_code,
            "stdout": result.stdout[:500],
            "stderr": result.stderr[:200],
            "duration_s": result.duration_s,
        })


# ---------------------------------------------------------------------------
# EXEC runner
# ---------------------------------------------------------------------------


def _async_run(coro: Any) -> Any:
    """Run an async coroutine synchronously (for compatibility with sync Runner base)."""
    import inspect
    # If not actually a coroutine (e.g. mocked), return directly
    if not inspect.iscoroutine(coro) and not asyncio.isfuture(coro):
        return coro
    # asyncio.run() creates and manages its own event loop.
    # If it fails, the coroutine is consumed and cannot be retried.
    # We catch the error and re-raise it rather than attempting to
    # reuse the consumed coroutine with a manual loop.
    return asyncio.run(coro)


class RepositoryRunner(Runner):
    """
    Runner for ExecutionMode.EXEC tasks.

    Executes repository-based tasks inside a Docker sandbox with bounded
    tool access. The model can inspect, edit, and test code — but only
    within the sandbox workspace.
    """

    @property
    def mode(self) -> ExecutionMode:
        return ExecutionMode.EXEC

    def __init__(
        self,
        adapter: ModelAdapter,
        dispatcher: EvaluatorDispatcher | None = None,
        sandbox_manager: SandboxManager | None = None,
        max_tool_calls: int = 50,
        max_total_time_s: float = 600.0,
        max_command_time_s: float = 60.0,
        docker_image: str = "python:3.11-slim",
    ) -> None:
        self._adapter = adapter
        self._dispatcher = dispatcher or EvaluatorDispatcher()
        self._sandbox_manager = sandbox_manager or SandboxManager()
        self._max_tool_calls = max_tool_calls
        self._max_total_time_s = max_total_time_s
        self._max_command_time_s = max_command_time_s
        self._docker_image = docker_image

    @property
    def adapter(self) -> ModelAdapter:
        return self._adapter

    @property
    def dispatcher(self) -> EvaluatorDispatcher:
        return self._dispatcher

    def run(self, task: Task, ctx: RunContext) -> TaskResult:
        """
        Execute an EXEC task via the model agent loop inside a Docker sandbox.

        Flow:
          1. Load and validate repository fixture
          2. Create clean workspace copy
          3. Start Docker sandbox
          4. Copy fixture into sandbox
          5. Run model agent loop (bounded tool calls)
          6. Collect diff + test results
          7. Evaluate with code evaluator
          8. Clean up sandbox
        """
        if task.mode != ExecutionMode.EXEC:
            return TaskResult(
                task_id=task.id,
                run_id=ctx.run_id,
                raw_response=None,
                flags=[f"mode_mismatch: expected EXEC, got {task.mode.value}"],
                execution_metadata={
                    "status": TaskStatus.SKIPPED.value,
                    "reason": f"Task mode {task.mode.value} not supported by RepositoryRunner",
                },
            )

        task_start = datetime.now(timezone.utc)
        repeat_id = f"r{ctx.repeat_index + 1:02d}"
        repository_id = task.context.get("repository_id", "")

        # 1. Load fixture
        fixture = self._load_fixture(repository_id)
        if fixture is None:
            return TaskResult(
                task_id=task.id,
                run_id=ctx.run_id,
                raw_response=None,
                flags=[f"fixture_not_found: {repository_id}"],
                execution_metadata={
                    "status": TaskStatus.ERROR.value,
                    "repeat_id": repeat_id,
                    "timestamp": task_start.isoformat(),
                },
            )

        # 2. Create clean workspace copy
        workspace = self._create_workspace_copy(fixture)
        if workspace is None:
            return TaskResult(
                task_id=task.id,
                run_id=ctx.run_id,
                raw_response=None,
                flags=["workspace_creation_failed"],
                execution_metadata={
                    "status": TaskStatus.ERROR.value,
                    "repeat_id": repeat_id,
                    "timestamp": task_start.isoformat(),
                },
            )

        # 3. Prepare security policy
        policy = self._build_policy(task)

        # 4. Start sandbox
        sandbox_id = ""
        sandbox_image = fixture.image or self._docker_image
        try:
            sandbox_id = _async_run(self._sandbox_manager.create(sandbox_image, policy))
        except Exception as e:
            return TaskResult(
                task_id=task.id,
                run_id=ctx.run_id,
                raw_response=None,
                flags=[f"sandbox_start_failed: {type(e).__name__}: {e}"],
                execution_metadata={
                    "status": TaskStatus.ERROR.value,
                    "repeat_id": repeat_id,
                    "timestamp": task_start.isoformat(),
                    "sandbox_image": sandbox_image,
                },
            )

        # 5. Copy fixture into sandbox
        try:
            _async_run(
                self._sandbox_manager.copy_in(
                    sandbox_id, workspace, fixture.workspace_path
                )
            )
        except Exception as e:
            self._cleanup(sandbox_id)
            return TaskResult(
                task_id=task.id,
                run_id=ctx.run_id,
                raw_response=None,
                flags=[f"fixture_copy_failed: {type(e).__name__}: {e}"],
                execution_metadata={
                    "status": TaskStatus.ERROR.value,
                    "repeat_id": repeat_id,
                    "timestamp": task_start.isoformat(),
                    "sandbox_id": sandbox_id,
                },
            )

        # 6. Run agent loop
        exec_ctx = ExecRunContext(
            run_id=ctx.run_id,
            task_id=task.id,
            repeat_id=repeat_id,
            workspace=workspace,
            sandbox_id=sandbox_id,
            sandbox_image=sandbox_image,
            sandbox_policy=policy,
        )

        agent_result = self._run_agent_loop(task, exec_ctx, policy)
        raw_response = agent_result.get("response", "")
        tool_calls = agent_result.get("tool_calls", [])
        errors = agent_result.get("errors", [])

        # 7. Collect evidence
        evidence: dict[str, Any] = {}
        try:
            evidence = _async_run(self._sandbox_manager.collect(sandbox_id))
        except Exception:
            pass

        # 8. Run tests if configured
        test_summary = self._run_tests(sandbox_id, fixture, exec_ctx)

        # 9. Get diff
        diff_result = self._get_diff(sandbox_id)

        # 10. Cleanup
        self._cleanup(sandbox_id)

        # 11. Build TaskResult
        result = TaskResult(
            task_id=task.id,
            run_id=ctx.run_id,
            raw_response=raw_response,
            repository_id=repository_id,
            repository_hash=fixture.fixture_hash,
            docker_image=sandbox_image,
            sandbox_id=sandbox_id,
            execution_metadata={
                "status": TaskStatus.SUCCESS.value if not errors else TaskStatus.ERROR.value,
                "repeat_id": repeat_id,
                "repository_id": repository_id,
                "repository_hash": fixture.fixture_hash,
                "docker_image": sandbox_image,
                "sandbox_id": sandbox_id,
                "tool_calls": [tc.to_dict() for tc in tool_calls],
                "command_count": len(exec_ctx.command_history),
                "changed_files": evidence.get("changed_files", []),
                "test_summary": test_summary,
                "diff": diff_result,
                "execution_time": round(
                    (datetime.now(timezone.utc) - task_start).total_seconds(), 2
                ),
                "timeout_status": (
                    "EXCEEDED"
                    if len(tool_calls) >= self._max_tool_calls
                    else (evidence.get("timed_out", False) and "TIMEOUT" or None)
                ),
                "resource_limit_status": {},
                "policy": policy.to_dict(),
                "timestamp": task_start.isoformat(),
            },
        )

        if errors:
            result.flags.extend(errors)

        # 12. Evaluate
        self._evaluate(task, result, evidence, test_summary)

        return result

    # -----------------------------------------------------------------------
    # Internal methods
    # -----------------------------------------------------------------------

    def _load_fixture(self, repository_id: str) -> RepositoryFixture | None:
        """Load a repository fixture by ID."""
        fixtures_root = repositories_dir()
        # Fixtures are stored under repositories/fixtures/<fixture_id>/
        fixture_dir = fixtures_root / "fixtures" / repository_id
        manifest_path = fixture_dir / "fixture.json"
        if not manifest_path.exists():
            return None
        try:
            fixture = RepositoryFixture.from_manifest(manifest_path)
            fixture.compute_hash(fixtures_root)
            return fixture
        except Exception:
            return None

    def _create_workspace_copy(self, fixture: RepositoryFixture) -> Path | None:
        """Create a clean temporary copy of the fixture for this run."""
        fixtures_root = repositories_dir()
        # Fixtures are stored under repositories/fixtures/<fixture_id>/
        source_dir = fixtures_root / "fixtures" / fixture.fixture_id
        if not source_dir.exists():
            return None

        tmp_dir = Path(tempfile.mkdtemp(prefix=f"eb-exec-{fixture.fixture_id}-"))
        try:
            for item in source_dir.iterdir():
                if item.is_dir():
                    shutil.copytree(item, tmp_dir / item.name, symlinks=True)
                else:
                    shutil.copy2(item, tmp_dir / item.name)
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return None

        return tmp_dir

    def _build_policy(self, task: Task) -> SecurityPolicy:
        """Build security policy from task context and runner defaults."""
        ctx = task.context
        return SecurityPolicy(
            network_enabled=ctx.get("network_enabled", False),
            cpu_limit=ctx.get("cpu_limit"),
            memory_limit=ctx.get("memory_limit"),
            timeout_seconds=ctx.get("timeout", self._max_total_time_s),
            max_tool_calls=ctx.get("max_tool_calls", self._max_tool_calls),
            max_command_time_s=ctx.get("max_command_time_s", self._max_command_time_s),
            allowed_env=ctx.get("allowed_env") or SecurityPolicy().allowed_env,
        )

    def _run_agent_loop(
        self,
        task: Task,
        exec_ctx: ExecRunContext,
        policy: SecurityPolicy,
    ) -> dict[str, Any]:
        """
        Run the model agent loop with bounded tool calls.

        Returns response text, tool call history, and any errors.
        """
        tool_calls: list[ToolCall] = []
        errors: list[str] = []
        max_calls = min(policy.max_tool_calls, self._max_tool_calls)

        system_prompt = self._build_system_prompt(task, policy, max_calls)
        prompt = task.prompt

        total_time = 0.0
        start_time = time.time()

        while len(tool_calls) < max_calls:
            elapsed = time.time() - start_time
            if elapsed >= self._max_total_time_s:
                errors.append("total_time_exceeded")
                break

            messages = self._build_messages(task, prompt, tool_calls, errors)
            request = ModelRequest(
                model=exec_ctx.run_id,
                messages=messages,
                context={"task": task.model_dump()},
            )

            try:
                response = self._adapter.generate(request)
            except Exception as e:
                errors.append(f"generation_error: {type(e).__name__}: {e}")
                break

            if not response.success:
                errors.append(f"adapter_error: {response.error or 'empty response'}")
                break

            parsed = self._parse_model_response(response.text, tool_calls)
            if parsed is None:
                prompt = response.text
                break

            call_id, tool_name, arguments = parsed

            tool_result = self._execute_tool(
                exec_ctx, tool_name, arguments, policy
            )

            tool_calls.append(ToolCall(
                tool_name=tool_name,
                arguments=arguments,
                call_id=call_id,
            ))
            exec_ctx.record_tool_call(tool_calls[-1])

            if tool_result.success:
                prompt = f"[Tool: {tool_name}]\n{tool_result.output}"
            else:
                prompt = f"[Tool: {tool_name}]\n[Error] {tool_result.error}"
            exec_ctx.record_command(
                [tool_name, json.dumps(arguments)],
                ExecResult(
                    command=[tool_name, json.dumps(arguments)],
                    exit_code=0 if tool_result.success else -1,
                    stdout=tool_result.output,
                    stderr=tool_result.error or "",
                    duration_s=tool_result.duration_s,
                ),
            )

        final_response = prompt
        if tool_calls:
            last = tool_calls[-1]
            if "_final_answer" in last.arguments:
                final_response = last.arguments["_final_answer"]

        return {
            "response": final_response,
            "tool_calls": tool_calls,
            "errors": errors,
        }

    def _build_system_prompt(self, task: Task, policy: SecurityPolicy, max_calls: int) -> str:
        tools_desc = self._get_tool_descriptions()
        return (
            f"You are an AI agent working inside a restricted Docker sandbox.\n"
            f"Your goal is to complete the task by using the available tools.\n\n"
            f"AVAILABLE TOOLS:\n{tools_desc}\n"
            f"SECURITY CONSTRAINTS:\n"
            f"- Network: {'enabled' if policy.network_enabled else 'DISABLED'}\n"
            f"- Working directory: {policy.workspace_path}\n"
            f"- Max tool calls: {max_calls}\n"
            f"- You CANNOT access the host filesystem\n"
            f"- You CANNOT run privileged commands\n"
            f"- You CANNOT escape the sandbox\n\n"
            f"Respond with tool calls in the format:\n"
            f"TOOL_CALL:<tool_name>:<json_arguments>\n\n"
            f"Or when done, respond with:\n"
            f"FINAL_ANSWER:<your answer>\n"
        )

    def _get_tool_descriptions(self) -> str:
        return """
list_files(path=".") — List files in the workspace. Args: {"path": "string"}
read_file(path) — Read a file. Args: {"path": "string"}
write_file(path, content) — Write a file. Args: {"path": "string", "content": "string"}
patch_file(path, old_text, new_text) — Apply a text patch. Args: {"path", "old_text", "new_text"}
run_command(command) — Execute a command. Args: {"command": ["list", "of", "args"]}
run_tests() — Run the fixture's test command. Args: {}
""".strip()

    def _build_messages(
        self,
        task: Task,
        current_prompt: str,
        tool_calls: list[ToolCall],
        errors: list[str],
    ) -> list[dict[str, str]]:
        messages = [
            {"role": "system", "content": self._build_system_prompt(
                task, SecurityPolicy(), self._max_tool_calls,
            )},
            {"role": "user", "content": current_prompt},
        ]
        for call in tool_calls:
            messages.append({"role": "assistant", "content": f"TOOL_CALL:{call.tool_name}"})
        return messages

    def _parse_model_response(
        self,
        text: str,
        existing_calls: list[ToolCall],
    ) -> tuple[str, str, dict[str, Any]] | None:
        text = text.strip()
        if text.startswith("FINAL_ANSWER:"):
            return None
        if text.startswith("TOOL_CALL:"):
            parts = text[len("TOOL_CALL:"):].split(":", 1)
            if len(parts) == 2:
                tool_name = parts[0].strip()
                try:
                    arguments = json.loads(parts[1].strip())
                except json.JSONDecodeError:
                    arguments = {"_raw": parts[1].strip()}
                call_id = f"call-{len(existing_calls)+1:03d}"
                return call_id, tool_name, arguments
        try:
            data = json.loads(text)
            if "tool_name" in data and "arguments" in data:
                call_id = f"call-{len(existing_calls)+1:03d}"
                return call_id, data["tool_name"], data["arguments"]
        except (json.JSONDecodeError, TypeError):
            pass
        return None

    def _execute_tool(
        self,
        exec_ctx: ExecRunContext,
        tool_name: str,
        arguments: dict[str, Any],
        policy: SecurityPolicy,
    ) -> ToolResult:
        call_id = arguments.pop("_call_id", f"call-{len(exec_ctx.tool_history)+1:03d}")
        start_time = time.time()

        try:
            if tool_name == "list_files":
                path = arguments.get("path", ".")
                if not is_path_safe(path, policy.workspace_path):
                    return ToolResult(call_id=call_id, tool_name=tool_name, success=False,
                                      error="path_traversal_rejected")
                result = _async_run(self._sandbox_manager.exec(
                    exec_ctx.sandbox_id,
                    ["ls", "-la", policy.workspace_path + "/" + path],
                    timeout_s=self._max_command_time_s,
                ))
                return ToolResult(
                    call_id=call_id, tool_name=tool_name,
                    success=result.success, output=result.stdout,
                    error=result.error, exit_code=result.exit_code,
                    duration_s=time.time() - start_time,
                )

            elif tool_name == "read_file":
                path = arguments.get("path", "")
                if not is_path_safe(path, policy.workspace_path):
                    return ToolResult(call_id=call_id, tool_name=tool_name, success=False,
                                      error="path_traversal_rejected")
                full_path = policy.workspace_path + "/" + path
                result = _async_run(self._sandbox_manager.exec(
                    exec_ctx.sandbox_id,
                    ["cat", full_path],
                    timeout_s=self._max_command_time_s,
                ))
                return ToolResult(
                    call_id=call_id, tool_name=tool_name,
                    success=result.success, output=result.stdout,
                    error=result.error, exit_code=result.exit_code,
                    duration_s=time.time() - start_time,
                )

            elif tool_name == "write_file":
                path = arguments.get("path", "")
                content = arguments.get("content", "")
                if not is_path_safe(path, policy.workspace_path):
                    return ToolResult(call_id=call_id, tool_name=tool_name, success=False,
                                      error="path_traversal_rejected")
                src = Path(tempfile.mktemp())
                try:
                    src.write_text(content)
                    _async_run(self._sandbox_manager.copy_in(
                        exec_ctx.sandbox_id, src, path
                    ))
                    return ToolResult(
                        call_id=call_id, tool_name=tool_name, success=True,
                        output=f"Wrote {len(content)} bytes to {path}",
                        duration_s=time.time() - start_time,
                    )
                finally:
                    src.unlink(missing_ok=True)

            elif tool_name == "patch_file":
                path = arguments.get("path", "")
                old_text = arguments.get("old_text", "")
                new_text = arguments.get("new_text", "")
                if not is_path_safe(path, policy.workspace_path):
                    return ToolResult(call_id=call_id, tool_name=tool_name, success=False,
                                      error="path_traversal_rejected")
                full_path = policy.workspace_path + "/" + path
                read_result = _async_run(self._sandbox_manager.exec(
                    exec_ctx.sandbox_id,
                    ["cat", full_path],
                    timeout_s=self._max_command_time_s,
                ))
                if not read_result.success:
                    return ToolResult(
                        call_id=call_id, tool_name=tool_name, success=False,
                        error=f"Failed to read {path}: {read_result.error}",
                    )
                content = read_result.stdout
                if old_text not in content:
                    return ToolResult(
                        call_id=call_id, tool_name=tool_name, success=False,
                        error=f"old_text not found in {path}",
                    )
                patched = content.replace(old_text, new_text, 1)
                src = Path(tempfile.mktemp())
                try:
                    src.write_text(patched)
                    _async_run(self._sandbox_manager.copy_in(
                        exec_ctx.sandbox_id, src, path
                    ))
                    return ToolResult(
                        call_id=call_id, tool_name=tool_name, success=True,
                        output=f"Patched {path}",
                        duration_s=time.time() - start_time,
                    )
                finally:
                    src.unlink(missing_ok=True)

            elif tool_name == "run_command":
                cmd = arguments.get("command", [])
                if not isinstance(cmd, list):
                    return ToolResult(
                        call_id=call_id, tool_name=tool_name, success=False,
                        error="command must be a list of strings",
                    )
                result = _async_run(self._sandbox_manager.exec(
                    exec_ctx.sandbox_id,
                    cmd,
                    timeout_s=self._max_command_time_s,
                ))
                return ToolResult(
                    call_id=call_id, tool_name=tool_name,
                    success=result.success, output=result.stdout,
                    error=result.error, exit_code=result.exit_code,
                    duration_s=result.duration_s,
                    truncated=result.stdout_truncated or result.stderr_truncated,
                )

            elif tool_name == "run_tests":
                test_cmd = arguments.get("command") or "pytest -q"
                cmd = test_cmd.split() if isinstance(test_cmd, str) else test_cmd
                result = _async_run(self._sandbox_manager.exec(
                    exec_ctx.sandbox_id,
                    cmd,
                    timeout_s=policy.timeout_seconds,
                ))
                return ToolResult(
                    call_id=call_id, tool_name=tool_name,
                    success=result.success, output=result.stdout,
                    error=result.stderr, exit_code=result.exit_code,
                    duration_s=result.duration_s,
                )

            else:
                return ToolResult(
                    call_id=call_id, tool_name=tool_name, success=False,
                    error=f"Unknown tool: {tool_name}",
                )

        except Exception as e:
            return ToolResult(
                call_id=call_id, tool_name=tool_name, success=False,
                error=f"{type(e).__name__}: {e}",
                duration_s=time.time() - start_time,
            )

    def _run_tests(
        self,
        sandbox_id: str,
        fixture: RepositoryFixture,
        exec_ctx: ExecRunContext,
    ) -> dict[str, Any]:
        if not fixture.test_command:
            return {"skipped": True, "reason": "No test_command in fixture"}

        result = _async_run(self._sandbox_manager.exec(
            sandbox_id,
            fixture.test_command.split(),
            timeout_s=fixture.timeout,
        ))

        passed = result.success
        test_count = 0
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if "passed" in line.lower() and line.endswith("passed"):
                parts = line.split()
                try:
                    test_count = int(parts[-2])
                except (ValueError, IndexError):
                    pass

        return {
            "command": fixture.test_command,
            "exit_code": result.exit_code,
            "passed": passed,
            "test_count": test_count,
            "stdout": result.stdout[:1000],
            "stderr": result.stderr[:500],
            "duration_s": result.duration_s,
            "timed_out": result.timed_out,
        }

    def _get_diff(self, sandbox_id: str) -> str | None:
        result = _async_run(self._sandbox_manager.exec(
            sandbox_id, ["git", "diff"],
        ))
        if result.success and result.stdout.strip():
            return result.stdout.strip()
        return None

    def _evaluate(self, task: Task, result: TaskResult, evidence: dict, test_summary: dict) -> None:
        evaluator_specs = task.evaluation.evaluators if task.evaluation.evaluators else None
        eval_results = self._dispatcher.dispatch(task, result, evaluator_specs)
        result.evaluator_results = eval_results

        from ..scoring.raw import aggregate_task_evaluator_results
        strategy = task.evaluation.aggregation.get("strategy", "single_authoritative")
        raw_score = aggregate_task_evaluator_results(eval_results, strategy)
        result.raw_task_score = raw_score

        all_evidence = []
        for ev in eval_results:
            all_evidence.extend(ev.evidence)
        result.primary_evidence = all_evidence[:10]

        for ev in eval_results:
            result.flags.extend(ev.flags)

    def _cleanup(self, sandbox_id: str) -> None:
        if sandbox_id:
            try:
                _async_run(self._sandbox_manager.stop(sandbox_id))
            except Exception:
                pass
            try:
                _async_run(self._sandbox_manager.destroy(sandbox_id))
            except Exception:
                pass
