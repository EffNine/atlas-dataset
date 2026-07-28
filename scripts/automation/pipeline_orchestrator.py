#!/usr/bin/env python3
"""Pipeline orchestrator — coordinates the Atlas automation pipeline.

The orchestrator:
  1. Runs pipeline agents in sequence according to the state machine.
  2. Checks the approval gate before allowing release.
  3. Collects and reports results from each stage.
  4. Handles failures gracefully (stops on critical errors).

Pipeline flow::

    Orchestrator.run()
        │
        ├── ingesting... (external — state = INGESTED)
        ├── quality_check() → transition to QUALITY_CHECK
        ├── provenance_check() → transition to PROVENANCE_CHECK
        ├── content_revision() → transition to CONTENT_REVISION
        ├── validate() → transition to VALIDATION
        ├── request_approval() → transition to WAITING_HUMAN_APPROVAL
        └── release() → transition to RELEASED (after human approval)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .state_machine import PipelineState, StateMachine
from .approval_gate import ApprovalGate, ApproverRole
from .base_agent import BaseAgent, AgentResult, AgentStatus
from .quality_agent import QualityAgent
from .provenance_agent import ProvenanceAgent
from .revision_agent import RevisionAgent
from .validation_agent import ValidationAgent
from .release_manager import ReleaseManager


# ---------------------------------------------------------------------------
# Pipeline status
# ---------------------------------------------------------------------------


class PipelineStatus(str, Enum):
    """Overall pipeline execution status."""

    INITIALIZED = "initialized"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED_ON_APPROVAL = "blocked_on_approval"
    CANCELLED = "cancelled"

    def __str__(self) -> str:
        return self.value


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------


@dataclass
class PipelineResult:
    """Complete result from a pipeline run."""

    pipeline_id: str
    status: PipelineStatus
    current_state: str
    agent_results: dict[str, AgentResult] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    summary: str = ""
    started_at: str = ""
    completed_at: str = ""

    @property
    def all_agents_passed(self) -> bool:
        return all(
            r.status == AgentStatus.PASSED or r.status == AgentStatus.SKIPPED
            for r in self.agent_results.values()
        )

    @property
    def any_agent_failed(self) -> bool:
        return any(r.status == AgentStatus.FAILED for r in self.agent_results.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_id": self.pipeline_id,
            "status": self.status.value,
            "current_state": self.current_state,
            "agent_results": {
                name: r.to_dict() for name, r in self.agent_results.items()
            },
            "errors": self.errors,
            "summary": self.summary,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------


class PipelineOrchestrator:
    """Orchestrates the Atlas automation pipeline from ingestion to release.

    The orchestrator owns the state machine, approval gate, and all agents.
    It sequences operations according to the pipeline state machine.

    Args:
        pipeline_id: Unique identifier (e.g. "release-v0.3").
        root: Path to the atlas-dataset repository root.
        config: Optional configuration dict:
            - agents: dict of agent configs keyed by agent name.
            - approval_role: Required approver role (default: REVIEWER).
            - resolve_provenance: If True, run provenance agent (default: True).

    Typical usage::

        orch = PipelineOrchestrator("release-v0.3", ROOT)
        result = orch.run_full_pipeline()
        if result.status == PipelineStatus.COMPLETED:
            print("Pipeline released!")
        elif result.status == PipelineStatus.BLOCKED_ON_APPROVAL:
            print("Waiting for human to approve...")
    """

    def __init__(
        self,
        pipeline_id: str,
        root: str | Path,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.pipeline_id = pipeline_id
        self.root = Path(root).resolve()
        self.config = config or {}

        # Core components
        self.state_machine = StateMachine(pipeline_id, self.root)
        self.approval_gate = ApprovalGate(self.root)

        # Attempt to load persisted state
        self.state_machine.load()

        # Agents (lazy-initialized)
        self._agents: dict[str, BaseAgent] = {}

    # ── Agent factory ────────────────────────────────────────────────────

    def _get_agent(self, name: str) -> BaseAgent:
        """Get or create a pipeline agent by name."""
        if name not in self._agents:
            agent_config = self.config.get("agents", {}).get(name, {})
            if name == "quality":
                self._agents[name] = QualityAgent(self.root, agent_config)
            elif name == "provenance":
                self._agents[name] = ProvenanceAgent(self.root, agent_config)
            elif name == "revision":
                self._agents[name] = RevisionAgent(self.root, agent_config)
            elif name == "validation":
                self._agents[name] = ValidationAgent(self.root, agent_config)
            elif name == "release":
                self._agents[name] = ReleaseManager(self.root, agent_config)
            else:
                raise ValueError(f"Unknown agent: {name}")
        return self._agents[name]

    # ── Full pipeline ────────────────────────────────────────────────────

    def run_full_pipeline(self) -> PipelineResult:
        """Run the complete pipeline from current state through to release.

        Returns:
            PipelineResult with all agent results and final status.
        """
        started_at = datetime.now(timezone.utc).isoformat()
        agent_results: dict[str, AgentResult] = {}
        errors: list[str] = []

        # Determine starting point based on current state
        try:
            self._advance_pipeline(agent_results, errors)
        except Exception as e:
            errors.append(f"Pipeline crashed: {e}")

        completed_at = datetime.now(timezone.utc).isoformat()
        current_state = self.state_machine.current_state

        # Determine overall status
        if self.state_machine.is_terminal():
            status = PipelineStatus.COMPLETED
        elif self.state_machine.is_blocked():
            status = PipelineStatus.BLOCKED_ON_APPROVAL
        elif errors:
            status = PipelineStatus.FAILED
        else:
            status = PipelineStatus.RUNNING

        summary = self._build_summary(status, agent_results, errors)

        return PipelineResult(
            pipeline_id=self.pipeline_id,
            status=status,
            current_state=current_state.value,
            agent_results=agent_results,
            errors=errors,
            summary=summary,
            started_at=started_at,
            completed_at=completed_at,
        )

    def _advance_pipeline(
        self,
        agent_results: dict[str, AgentResult],
        errors: list[str],
    ) -> None:
        """Advance the pipeline through each stage from the current state."""
        state = self.state_machine.current_state

        # ── QUALITY_CHECK ──────────────────────────────────────────────
        if state == PipelineState.INGESTED:
            result = self._run_agent("quality")
            agent_results["quality"] = result
            if result.passed:
                self.state_machine.transition_to(
                    PipelineState.QUALITY_CHECK,
                    triggered_by="quality_agent",
                    reason=result.summary,
                )

        # ── PROVENANCE_CHECK ───────────────────────────────────────────
        if self.state_machine.current_state == PipelineState.QUALITY_CHECK:
            result = self._run_agent("provenance")
            agent_results["provenance"] = result
            # Provenance can pass even with unresolved records (advisory)
            if result.status in (AgentStatus.PASSED, AgentStatus.FAILED):
                self.state_machine.transition_to(
                    PipelineState.PROVENANCE_CHECK,
                    triggered_by="provenance_agent",
                    reason=result.summary,
                )

        # ── CONTENT_REVISION ───────────────────────────────────────────
        if self.state_machine.current_state == PipelineState.PROVENANCE_CHECK:
            result = self._run_agent("revision")
            agent_results["revision"] = result
            if result.passed:
                self.state_machine.transition_to(
                    PipelineState.CONTENT_REVISION,
                    triggered_by="revision_agent",
                    reason=result.summary,
                )
            else:
                # Records need revision — still advance (revision is informational)
                self.state_machine.transition_to(
                    PipelineState.CONTENT_REVISION,
                    triggered_by="revision_agent",
                    reason=f"Continuing with {len(result.errors)} revision(s) outstanding",
                )

        # ── VALIDATION ─────────────────────────────────────────────────
        if self.state_machine.current_state == PipelineState.CONTENT_REVISION:
            result = self._run_agent("validation")
            agent_results["validation"] = result
            if result.passed:
                self.state_machine.transition_to(
                    PipelineState.VALIDATION,
                    triggered_by="validation_agent",
                    reason=result.summary,
                )
            else:
                errors.append(f"Validation failed: {result.summary}")
                return  # Block pipeline — validation is critical

        # ── WAITING_HUMAN_APPROVAL ─────────────────────────────────────
        if self.state_machine.current_state == PipelineState.VALIDATION:
            # Check if approval already exists
            if self.approval_gate.is_releasable(self.pipeline_id):
                self.state_machine.transition_to(
                    PipelineState.WAITING_HUMAN_APPROVAL,
                    triggered_by="approval_gate",
                    reason="Human approval already granted",
                )
            else:
                self.state_machine.transition_to(
                    PipelineState.WAITING_HUMAN_APPROVAL,
                    triggered_by="pipeline_orchestrator",
                    reason="Awaiting human approval before release",
                )

        # ── RELEASE (via ReleaseManager) ──────────────────────────────
        if self.state_machine.current_state == PipelineState.WAITING_HUMAN_APPROVAL:
            # Only proceed when human has approved
            if not self.approval_gate.is_releasable(self.pipeline_id):
                return  # Stay blocked — waiting for human approval

            # Check human approval status for context
            approval_check = self.approval_gate.check_approval_gate(self.pipeline_id)

            # Run the ReleaseManager with accumulated agent results
            release_context = {
                "pipeline_id": self.pipeline_id,
                "state": self.state_machine.current_state.value,
                "agent_results": agent_results,
                "approval_status": approval_check,
            }
            result = self._run_agent("release", custom_context=release_context)
            agent_results["release"] = result

            release_status = result.data.get("status", "RELEASE_REJECTED")
            if release_status == "READY_FOR_RELEASE":
                self.state_machine.transition_to(
                    PipelineState.READY_FOR_RELEASE,
                    triggered_by="release_manager",
                    reason=result.summary,
                )
                # Immediately advance to RELEASED
                if self.state_machine.current_state == PipelineState.READY_FOR_RELEASE:
                    self.state_machine.transition_to(
                        PipelineState.RELEASED,
                        triggered_by="release_manager",
                        reason="All gates pass — dataset released",
                    )
            else:
                self.state_machine.transition_to(
                    PipelineState.RELEASE_REJECTED,
                    triggered_by="release_manager",
                    reason=result.summary if result.errors else "Release rejected",
                )

    def _run_agent(self, name: str, custom_context: dict[str, Any] | None = None) -> AgentResult:
        """Run a single agent and return its result.

        Args:
            name: Agent identifier.
            custom_context: Override the default context dict. When provided
                           this is passed verbatim to ``agent.execute()``
                           instead of the standard pipeline context.
        """
        try:
            agent = self._get_agent(name)
            context = custom_context if custom_context is not None else {
                "pipeline_id": self.pipeline_id,
                "state": self.state_machine.current_state.value,
            }
            return agent.execute(context=context)
        except Exception as e:
            return AgentResult(
                agent_name=name,
                status=AgentStatus.FAILED,
                summary=f"Agent crashed: {e}",
                errors=[str(e)],
            )

    # ── Step-by-step pipeline (for manual control) ────────────────────────

    def run_to_approval(self) -> PipelineResult:
        """Run all pipeline stages up to (but not through) human approval.

        Returns the pipeline state at WAITING_HUMAN_APPROVAL.
        """
        started_at = datetime.now(timezone.utc).isoformat()
        agent_results: dict[str, AgentResult] = {}
        errors: list[str] = []

        try:
            self._advance_pipeline(agent_results, errors)
        except Exception as e:
            errors.append(f"Pipeline crashed: {e}")

        completed_at = datetime.now(timezone.utc).isoformat()
        current_state = self.state_machine.current_state

        is_blocked = self.state_machine.is_blocked()
        status = PipelineStatus.BLOCKED_ON_APPROVAL if is_blocked else (
            PipelineStatus.FAILED if errors else PipelineStatus.RUNNING
        )

        summary = self._build_summary(status, agent_results, errors)

        return PipelineResult(
            pipeline_id=self.pipeline_id,
            status=status,
            current_state=current_state.value,
            agent_results=agent_results,
            errors=errors,
            summary=summary,
            started_at=started_at,
            completed_at=completed_at,
        )

    # ── Approval helpers ─────────────────────────────────────────────────

    def request_human_approval(
        self,
        *,
        requested_by: str = "system",
        role: ApproverRole = ApproverRole.REVIEWER,
        artifacts: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a human approval request for the current pipeline.

        Args:
            requested_by: Who requested the approval.
            role: Required approver role.
            artifacts: Artifacts to present for review.

        Returns:
            The approval request details.
        """
        return self.approval_gate.create_request(
            self.pipeline_id,
            requested_by=requested_by,
            role=role,
            artifacts_reviewed=artifacts,
        ).to_dict()

    def approve_release(
        self,
        *,
        decided_by: str,
        role: ApproverRole = ApproverRole.REVIEWER,
        comments: str = "",
    ) -> dict[str, Any]:
        """Approve the pipeline for release.

        Auto-creates an approval request if one does not already exist.
        Also attempts to advance the pipeline from WAITING_HUMAN_APPROVAL
        to RELEASED after a successful approval.

        Args:
            decided_by: Identifier of the human approver.
            role: The approver's role.
            comments: Optional comments.

        Returns:
            Approval gate check result.
        """
        # Auto-create request if none exists
        existing = self.approval_gate.get_request(self.pipeline_id)
        if existing is None:
            self.approval_gate.create_request(
                self.pipeline_id,
                requested_by="system",
                role=role,
            )

        result = self.approval_gate.approve(
            self.pipeline_id,
            decided_by=decided_by,
            role=role,
            comments=comments,
        )
        if result:
            # Try to advance the pipeline from WAITING_HUMAN_APPROVAL to RELEASED
            self._try_release()
        return self.approval_gate.check_approval_gate(self.pipeline_id)

    def deny_release(
        self,
        *,
        decided_by: str,
        role: ApproverRole = ApproverRole.REVIEWER,
        comments: str = "",
    ) -> dict[str, Any]:
        """Deny the pipeline release.

        Args:
            decided_by: Identifier of the human who denied.
            role: The denier's role.
            comments: Reason for denial.

        Returns:
            Approval gate check result.
        """
        result = self.approval_gate.deny(
            self.pipeline_id,
            decided_by=decided_by,
            role=role,
            comments=comments,
        )
        return self.approval_gate.check_approval_gate(self.pipeline_id)

    def _try_release(self) -> bool:
        """Attempt to transition from WAITING_HUMAN_APPROVAL to RELEASED via ReleaseManager.

        Steps through READY_FOR_RELEASE as an intermediate state.
        """
        if self.state_machine.current_state != PipelineState.WAITING_HUMAN_APPROVAL:
            return False
        if not self.approval_gate.is_releasable(self.pipeline_id):
            return False
        # Transition through READY_FOR_RELEASE to RELEASED
        ok = self.state_machine.transition_to(
            PipelineState.READY_FOR_RELEASE,
            triggered_by="release_manager",
            reason="Human approval received — preparing release",
        )
        if not ok:
            return False
        return self.state_machine.transition_to(
            PipelineState.RELEASED,
            triggered_by="release_manager",
            reason="Human approval received — dataset released",
        )

    # ── Pipeline status ──────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Get the current pipeline status."""
        state_summary = self.state_machine.summary()
        approval_check = self.approval_gate.check_approval_gate(self.pipeline_id)

        return {
            "pipeline_id": self.pipeline_id,
            "state": state_summary,
            "approval": approval_check,
        }

    def reset_pipeline(self) -> None:
        """Reset the pipeline to its initial state."""
        self.state_machine.reset()
        self.approval_gate.reject_or_rescind(self.pipeline_id)

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _build_summary(
        status: PipelineStatus,
        agent_results: dict[str, AgentResult],
        errors: list[str],
    ) -> str:
        if status == PipelineStatus.COMPLETED:
            return "Pipeline completed successfully — all agents passed, dataset released."
        if status == PipelineStatus.BLOCKED_ON_APPROVAL:
            return "Pipeline ready for release — awaiting human approval."
        if status == PipelineStatus.FAILED:
            failed = [
                f"{name}: {r.summary}"
                for name, r in agent_results.items()
                if r.failed
            ]
            parts = [f"Pipeline failed with {len(errors)} error(s)"]
            if failed:
                parts.append(f"Failed agents: {'; '.join(failed)}")
            return " | ".join(parts)
        passed = [n for n, r in agent_results.items() if r.passed]
        return f"Pipeline running — {len(passed)} agent(s) completed"
