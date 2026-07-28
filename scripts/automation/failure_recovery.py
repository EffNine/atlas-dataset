#!/usr/bin/env python3
"""Atlas Automation Layer Failure Recovery v1 — retry and resume for failed pipelines.

Allows failed pipelines to recover without restarting from INGESTED by
supporting targeted retry of the failed agent and resume from the
pre-failure state.

Design constraints:
  - Does NOT modify existing agents (QualityAgent, ProvenanceAgent, etc.)
  - Retry history is persisted to metadata/pipeline_retries/<pipeline_id>.json
  - Only the failed agent is re-run on retry (scoped per agent type)
  - On success, the pipeline continues from the retried agent
  - On failure, the pipeline stays FAILED (no infinite loop)

Retry rules:
  - Failed quality → retry quality only
  - Failed provenance → retry provenance only
  - Failed validation → retry validation only
  - Failed revision → retry revision only
  - Successful retry continues pipeline
  - Failed retry remains FAILED

Usage::

    from automation.failure_recovery import RetryManager

    mgr = RetryManager("release-v0.3", root)
    result = mgr.retry_failed_agent()  # re-run failed agent only
    result = mgr.resume_pipeline()      # clear failure, run full pipeline
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .state_machine import PipelineState, StateMachine
from .pipeline_orchestrator import PipelineOrchestrator, PipelineResult, PipelineStatus
from .base_agent import AgentResult, AgentStatus

# ---------------------------------------------------------------------------
# Agent → pre-failure state mapping
# ---------------------------------------------------------------------------

_AGENT_TO_PRE_FAILURE_STATE: dict[str, PipelineState] = {
    "quality": PipelineState.INGESTED,
    "provenance": PipelineState.QUALITY_CHECK,
    "revision": PipelineState.PROVENANCE_CHECK,
    "validation": PipelineState.CONTENT_REVISION,
}


# ---------------------------------------------------------------------------
# Retry history persistence
# ---------------------------------------------------------------------------


class RetryManager:
    """Manages retry history persistence for a single pipeline.

    Retry records are written to::

        metadata/pipeline_retries/<pipeline_id>.json

    Each record has the schema::

        {
            "failed_agent": "quality",
            "previous_reason": "Quality score below threshold",
            "retry_count": 1,
            "timestamp": "2026-07-29T12:00:00+00:00",
            "result": "success"    # or "failed"
        }

    Args:
        pipeline_id: Unique identifier for the pipeline.
        root: Path to the atlas-dataset repository root.
    """

    RETRY_DIR = "metadata/pipeline_retries"

    def __init__(self, pipeline_id: str, root: str | Path) -> None:
        self.pipeline_id = pipeline_id
        self.root = Path(root).resolve()

    def _retries_path(self) -> Path:
        """Path to the retry history file for this pipeline."""
        return self.root / self.RETRY_DIR / f"{self.pipeline_id}.json"

    def load_history(self) -> list[dict[str, Any]]:
        """Load the full retry history from disk.

        Returns:
            List of retry record dicts. Empty list if no history exists.
        """
        path = self._retries_path()
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
            return []
        except (json.JSONDecodeError, ValueError):
            return []

    def record_retry(self, record: dict[str, Any]) -> None:
        """Append a retry record to persistent history.

        Args:
            record: Dict with keys ``failed_agent``, ``previous_reason``,
                   ``retry_count``, ``timestamp``, ``result``.
        """
        history = self.load_history()
        history.append(record)
        path = self._retries_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(history, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def get_retry_count(self, agent_name: str) -> int:
        """Count how many times a specific agent has been retried.

        Args:
            agent_name: Name of the agent (e.g. ``"quality"``).

        Returns:
            Number of retry records for this agent.
        """
        history = self.load_history()
        return sum(
            1 for r in history if r.get("failed_agent") == agent_name
        )

    def get_last_retry(self, agent_name: str) -> dict[str, Any] | None:
        """Get the most recent retry record for a specific agent.

        Args:
            agent_name: Name of the agent.

        Returns:
            The last retry record dict, or None if no retries exist.
        """
        history = self.load_history()
        for record in reversed(history):
            if record.get("failed_agent") == agent_name:
                return record
        return None


# ---------------------------------------------------------------------------
# Failure recovery logic
# ---------------------------------------------------------------------------


def _determine_pre_failure_state(
    agent_name: str,
    state_machine: StateMachine,
) -> PipelineState | None:
    """Determine the state to revert to before retrying a failed agent.

    Uses the agent name to look up the pre-failure state from the mapping.
    Falls back to INGESTED if unknown.

    Args:
        agent_name: The agent that failed (e.g. ``"quality"``).
        state_machine: Current state machine (for context).

    Returns:
        The PipelineState to transition back to, or None if unknown.
    """
    pre_state = _AGENT_TO_PRE_FAILURE_STATE.get(agent_name)
    if pre_state is None:
        # Unknown agent — fall back to INGESTED
        return PipelineState.INGESTED
    return pre_state


def retry_failed_agent(
    pipeline_id: str,
    root: str | Path,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Retry only the failed agent in a pipeline.

    1. Validates the pipeline is in FAILED state with failure_info.
    2. Determines the pre-failure state from the failed agent name.
    3. Transitions FAILED → pre-failure state.
    4. Clears failure_info.
    5. Records the retry in history.
    6. Runs ONLY the failed agent.
    7. If passed: continues the pipeline (advances remaining stages).
    8. If failed: stays FAILED with a new failure record.

    Args:
        pipeline_id: Unique pipeline identifier.
        root: Path to the atlas-dataset repository root.
        config: Optional config dict (passed to PipelineOrchestrator).

    Returns:
        Dict with keys:
            - ``action``: ``"retry"``
            - ``retry_result``: ``"success"`` or ``"failed"``
            - ``pipeline_result``: PipelineResult.to_dict() if pipeline continued
            - ``agent_result``: AgentResult.to_dict() from the retried agent
            - ``retry_record``: The retry history record
            - ``message``: Human-readable summary
            - ``error``: Error message if applicable
    """
    root_path = Path(root).resolve()
    config = config or {}

    # 1. Load state machine
    sm = StateMachine(pipeline_id, root_path)
    sm.load()

    # Validate pipeline is in FAILED state
    if sm.current_state != PipelineState.FAILED:
        return {
            "action": "retry",
            "retry_result": "skipped",
            "error": (
                f"Pipeline '{pipeline_id}' is not in FAILED state "
                f"(current: {sm.current_state.value}). "
                f"Cannot retry."
            ),
            "message": (
                f"Retry skipped: pipeline is in {sm.current_state.value}, "
                f"not FAILED."
            ),
        }

    # Validate failure_info exists
    failure_info = sm.failure_info
    if not failure_info:
        return {
            "action": "retry",
            "retry_result": "skipped",
            "error": (
                f"Pipeline '{pipeline_id}' is in FAILED state but has no "
                f"failure_info. Use 'resume' instead."
            ),
            "message": (
                f"Retry skipped: pipeline {pipeline_id} has no failure "
                f"information."
            ),
        }

    agent_name = failure_info.get("agent_name", "")
    previous_reason = failure_info.get("reason", "Unknown")
    next_action = failure_info.get("next_action", "")

    if not agent_name:
        return {
            "action": "retry",
            "retry_result": "skipped",
            "error": (
                f"Pipeline '{pipeline_id}' failure_info has no agent_name. "
                f"Cannot determine which agent to retry."
            ),
            "message": "Retry skipped: no agent name in failure_info.",
        }

    # Apply retry scoping rules
    # Failed quality → retry quality only
    # Failed provenance → retry provenance only
    # Failed validation → retry validation only
    # Failed revision → retry revision only
    allowed_agents = {"quality", "provenance", "revision", "validation"}
    if agent_name not in allowed_agents:
        return {
            "action": "retry",
            "retry_result": "skipped",
            "error": (
                f"Agent '{agent_name}' is not retryable. "
                f"Allowed: {', '.join(sorted(allowed_agents))}."
            ),
            "message": f"Retry skipped: {agent_name} is not a retryable agent.",
        }

    # 2. Determine pre-failure state
    pre_state = _determine_pre_failure_state(agent_name, sm)
    if pre_state is None:
        return {
            "action": "retry",
            "retry_result": "skipped",
            "error": (
                f"Cannot determine pre-failure state for agent '{agent_name}'."
            ),
            "message": "Retry skipped: unknown pre-failure state.",
        }

    # 3. Transition FAILED → pre-failure state
    transition_ok = sm.transition_to(
        pre_state,
        triggered_by="failure_recovery",
        reason=f"Retry: transitioning back to {pre_state.value} before re-running {agent_name}",
    )
    if not transition_ok:
        return {
            "action": "retry",
            "retry_result": "skipped",
            "error": (
                f"Cannot transition from FAILED to {pre_state.value} "
                f"for agent '{agent_name}': {sm.error}"
            ),
            "message": f"Retry skipped: transition to {pre_state.value} failed.",
        }

    # 4. Clear failure info
    sm.clear_failure()
    sm._persist()

    # 5. Build and run ONLY the failed agent
    orch = PipelineOrchestrator(pipeline_id, root_path, config=config)

    # Get the specific agent and run it
    try:
        agent = orch._get_agent(agent_name)
        context = {
            "pipeline_id": pipeline_id,
            "state": pre_state.value,
        }
        agent_result = agent.execute(context=context)
    except Exception as e:
        agent_result = AgentResult(
            agent_name=agent_name,
            status=AgentStatus.FAILED,
            summary=f"Agent execution crashed during retry: {e}",
            errors=[str(e)],
        )

    # Record retry in history
    retry_count = RetryManager(pipeline_id, root_path).get_retry_count(agent_name) + 1
    retry_record = {
        "failed_agent": agent_name,
        "previous_reason": previous_reason,
        "retry_count": retry_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "result": "success" if agent_result.passed else "failed",
    }
    RetryManager(pipeline_id, root_path).record_retry(retry_record)

    # 6/7. Handle retry outcome
    if agent_result.passed:
        # Continue pipeline from this state
        try:
            pipeline_result = orch.run_full_pipeline()
        except Exception as e:
            pipeline_result = PipelineResult(
                pipeline_id=pipeline_id,
                status=PipelineStatus.FAILED,
                current_state=orch.state_machine.current_state.value,
                errors=[f"Pipeline continuation crashed: {e}"],
                summary=f"Pipeline continuation failed after retry: {e}",
            )

        return {
            "action": "retry",
            "retry_result": "success",
            "agent_name": agent_name,
            "previous_reason": previous_reason,
            "agent_result": agent_result.to_dict(),
            "pipeline_result": pipeline_result.to_dict(),
            "retry_record": retry_record,
            "message": (
                f"Retry of agent '{agent_name}' succeeded. "
                f"Previous failure: {previous_reason}. "
                f"Pipeline status: {pipeline_result.status.value}. "
                + (
                    f"Pipeline completed successfully."
                    if pipeline_result.status == PipelineStatus.COMPLETED
                    else (
                        f"Pipeline resumed — current state: "
                        f"{pipeline_result.current_state}."
                    )
                )
            ),
        }
    else:
        # Failed again — stay FAILED
        sm.set_failure(
            agent_name=agent_name,
            reason=agent_result.summary,
            next_action=f"RETRY_{agent_name.upper()}_AGAIN",
        )
        sm.transition_to(
            PipelineState.FAILED,
            triggered_by="failure_recovery",
            reason=f"Retry of {agent_name} failed again: {agent_result.summary}",
        )

        return {
            "action": "retry",
            "retry_result": "failed",
            "agent_name": agent_name,
            "previous_reason": previous_reason,
            "agent_result": agent_result.to_dict(),
            "retry_record": retry_record,
            "message": (
                f"Retry of agent '{agent_name}' failed again. "
                f"Previous failure: {previous_reason}. "
                f"New failure: {agent_result.summary}. "
                f"Pipeline remains FAILED."
            ),
        }


def resume_pipeline(
    pipeline_id: str,
    root: str | Path,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resume a failed pipeline by clearing failure and continuing.

    1. Validates the pipeline is in FAILED state (or has failure_info).
    2. Determines the pre-failure state.
    3. Transitions FAILED → pre-failure state.
    4. Clears failure_info.
    5. Runs the full pipeline from the pre-failure state
       (re-runs remaining agents).

    Unlike ``retry_failed_agent``, this does NOT target a specific agent.
    It clears the failure state and runs the full pipeline.

    Args:
        pipeline_id: Unique pipeline identifier.
        root: Path to the atlas-dataset repository root.
        config: Optional config dict.

    Returns:
        Dict with keys:
            - ``action``: ``"resume"``
            - ``resume_result``: ``"success"``, ``"failed"``, or ``"skipped"``
            - ``pipeline_result``: PipelineResult.to_dict()
            - ``message``: Human-readable summary
            - ``error``: Error message if applicable
    """
    root_path = Path(root).resolve()
    config = config or {}

    # 1. Load state machine
    sm = StateMachine(pipeline_id, root_path)
    sm.load()

    # Determine what state we're in
    has_failure = sm.has_failed()
    is_failed = sm.current_state == PipelineState.FAILED

    if not is_failed and not has_failure:
        # Not failed at all — just return current status, don't run
        status_summary = sm.summary()
        return {
            "action": "resume",
            "resume_result": "skipped",
            "current_state": sm.current_state.value,
            "pipeline_result": None,
            "message": (
                f"Pipeline '{pipeline_id}' is not in FAILED state "
                f"(current: {sm.current_state.value}). "
                f"No resume needed."
            ),
        }

    # Read failure info
    failure_info = sm.failure_info or {}
    agent_name = failure_info.get("agent_name", "unknown")
    previous_reason = failure_info.get("reason", "Unknown")

    # 2. Determine pre-failure state
    pre_state = _determine_pre_failure_state(agent_name, sm)

    if is_failed and pre_state is not None:
        # 3. Transition FAILED → pre-failure state
        transition_ok = sm.transition_to(
            pre_state,
            triggered_by="failure_recovery",
            reason=f"Resume: clearing failure and continuing from {pre_state.value}",
        )
        if not transition_ok:
            return {
                "action": "resume",
                "resume_result": "skipped",
                "error": (
                    f"Cannot transition from FAILED to "
                    f"{pre_state.value}: {sm.error}"
                ),
                "message": (
                    f"Resume skipped: cannot transition from "
                    f"FAILED to {pre_state.value}."
                ),
            }

    # 4. Clear failure info
    sm.clear_failure()
    sm._persist()

    # 5. Run the full pipeline
    orch = PipelineOrchestrator(pipeline_id, root_path, config=config)
    try:
        pipeline_result = orch.run_full_pipeline()
    except Exception as e:
        pipeline_result = PipelineResult(
            pipeline_id=pipeline_id,
            status=PipelineStatus.FAILED,
            current_state=str(sm.current_state.value) if hasattr(sm.current_state, 'value') else str(sm.current_state),
            errors=[f"Pipeline crashed on resume: {e}"],
            summary=f"Resume failed with exception: {e}",
        )

    is_completed = pipeline_result.status == PipelineStatus.COMPLETED
    resume_result = (
        "success"
        if is_completed or pipeline_result.status == PipelineStatus.BLOCKED_ON_APPROVAL
        else "failed"
    )

    return {
        "action": "resume",
        "resume_result": resume_result,
        "agent_name": agent_name,
        "previous_reason": previous_reason,
        "pipeline_result": pipeline_result.to_dict(),
        "message": (
            f"Resume of pipeline '{pipeline_id}' completed. "
            f"Previous failure: {agent_name} — {previous_reason}. "
            f"Pipeline status: {pipeline_result.status.value}. "
            + (
                "Pipeline completed successfully."
                if is_completed
                else (
                    f"Pipeline now at: {pipeline_result.current_state}."
                )
            )
        ),
    }
