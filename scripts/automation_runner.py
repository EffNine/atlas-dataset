#!/usr/bin/env python3
"""
Atlas Automation Runner v1.5 — CLI entry point for PipelineOrchestrator.

End-to-end pipeline execution with dry-run, status checking, approval
interaction, and release execution.

Usage::

    # Run the full pipeline (ingestion → release)
    python -m scripts.automation_runner run --pipeline-id release-v0.3

    # Dry-run — simulate without side effects
    python -m scripts.automation_runner run --pipeline-id release-v0.3 --dry-run

    # Check pipeline status
    python -m scripts.automation_runner status --pipeline-id release-v0.3

    # Request human approval
    python -m scripts.automation_runner request-approval \\
        --pipeline-id release-v0.3 --role reviewer

    # Approve a pipeline
    python -m scripts.automation_runner approve \\
        --pipeline-id release-v0.3 --by reviewer_jane

    # Deny a pipeline
    python -m scripts.automation_runner deny \\
        --pipeline-id release-v0.3 --by reviewer_bob --reason "Need more data"

    # Release (run only the release stage on an approved pipeline)
    python -m scripts.automation_runner release --pipeline-id release-v0.3

Design:

    AutomationRunner (v1.5)
        │
        ├── run()           ← Compose PipelineOrchestrator end-to-end
        ├── status()        ← Read pipeline state without running agents
    ├── request_approval() ← Create approval request via ApprovalGate
        ├── approve()       ← Sign off via ApprovalGate → PipelineOrchestrator
        ├── deny()          ← Reject via ApprovalGate
        └── release()       ← Execute release on approved pipeline

    Key constraint: ZERO modifications to existing agents.
                    The runner composes existing components only.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

# Ensure scripts/ is on sys.path for imports of the automation package
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from automation.state_machine import _STATE_INDEX, PipelineState, StateMachine
from automation.approval_gate import ApprovalGate, ApproverRole
from automation.base_agent import AgentStatus
from automation.pipeline_orchestrator import PipelineOrchestrator, PipelineResult, PipelineStatus
from automation.failure_recovery import retry_failed_agent, resume_pipeline, RetryManager
from automation.acquisition_agent import AcquisitionAgent
from downloader import DownloadAgent, CacheManager
from etl import ExtractAgent
from publish_agent import PublishAgent
from transform import run_transform
from view_builder import build_views
from release_builder import build_release
from atlas_paths import discover_root


# ═══════════════════════════════════════════════════════════════════════
# Defaults
# ═══════════════════════════════════════════════════════════════════════

_DEFAULT_ROOT: Path | None = None


def _get_root() -> Path:
    """Discover and cache the atlas-dataset repository root."""
    global _DEFAULT_ROOT
    if _DEFAULT_ROOT is None:
        _DEFAULT_ROOT = discover_root()
    return _DEFAULT_ROOT


# ═══════════════════════════════════════════════════════════════════════
# Dry-run orchestrator wrapper
# ═══════════════════════════════════════════════════════════════════════


class DryRunOrchestrator:
    """Simulates PipelineOrchestrator execution without side effects.

    Reads current state from the state machine without advancing it,
    and produces a DryRunPipelineResult describing what *would* happen.
    No agents are invoked and no state is persisted.
    """

    def __init__(self, pipeline_id: str, root: Path, config: dict[str, Any] | None = None) -> None:
        self.pipeline_id = pipeline_id
        self.root = root
        self.config = config or {}

        # Read-only state — init a state machine and load, but never
        # call transition_to() so no disk writes occur on load.
        self.state_machine = StateMachine(pipeline_id, root)
        self.state_machine.load()

        self.approval_gate = ApprovalGate(root)

    def simulate_full_pipeline(self) -> dict[str, Any]:
        """Simulate a full pipeline run and return a dry-run report."""
        state = self.state_machine.current_state
        approval = self.approval_gate.check_approval_gate(self.pipeline_id)

        # Upcoming agents based on current state
        agents_ahead = self._agents_ahead(state)

        # Build simulated state progression (no side effects)
        simulated_progression: list[dict[str, Any]] = []
        sim_state = state
        for _ in range(20):  # safety limit
            transition = self._simulate_next(sim_state, approval)
            if transition is None:
                break
            simulated_progression.append(transition)
            # Convert back to PipelineState for the next iteration
            sim_state = PipelineState(transition["to_state"])
            if sim_state in (PipelineState.RELEASED, PipelineState.RELEASE_REJECTED):
                break

        return {
            "pipeline_id": self.pipeline_id,
            "mode": "dry-run",
            "current_state": state.value,
            "is_terminal": self.state_machine.is_terminal(),
            "is_blocked_on_approval": self.state_machine.is_blocked(),
            "agents_to_run": agents_ahead,
            "simulated_progression": simulated_progression,
            "approval_status": approval,
            "would_advance": not self.state_machine.is_terminal() and bool(agents_ahead),
            "simulated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _agents_ahead(self, state: PipelineState) -> list[str]:
        """List agents that would run from the current state forward."""
        current_idx = _STATE_INDEX.get(state, -1)

        agent_map: dict[int, str] = {
            _STATE_INDEX[PipelineState.INGESTED]: "quality",
            _STATE_INDEX[PipelineState.QUALITY_CHECK]: "provenance",
            _STATE_INDEX[PipelineState.PROVENANCE_CHECK]: "revision",
            _STATE_INDEX[PipelineState.CONTENT_REVISION]: "validation",
        }

        agents: list[str] = []
        for idx in sorted(agent_map):
            if current_idx <= idx:
                agents.append(agent_map[idx])

        # Add human_approval and release_manager based on position
        val_idx = _STATE_INDEX[PipelineState.CONTENT_REVISION]
        if current_idx <= val_idx:
            agents.append("human_approval")
            agents.append("release_manager")
        elif current_idx >= _STATE_INDEX[PipelineState.VALIDATION]:
            agents.append("human_approval")
            agents.append("release_manager")
        elif current_idx == _STATE_INDEX[PipelineState.WAITING_HUMAN_APPROVAL]:
            agents.append("release_manager")

        return agents

    def _simulate_next(self, state: PipelineState,
                       approval: dict[str, Any]) -> dict[str, Any] | None:
        """Return the next transition from *state* (no side effects)."""
        transitions: dict[PipelineState, tuple[PipelineState, str, str]] = {
            PipelineState.INGESTED: (
                PipelineState.QUALITY_CHECK,
                "quality_agent",
                "Quality gate (simulated)",
            ),
            PipelineState.QUALITY_CHECK: (
                PipelineState.PROVENANCE_CHECK,
                "provenance_agent",
                "Provenance gate (simulated)",
            ),
            PipelineState.PROVENANCE_CHECK: (
                PipelineState.CONTENT_REVISION,
                "revision_agent",
                "Content revision gate (simulated)",
            ),
            PipelineState.CONTENT_REVISION: (
                PipelineState.VALIDATION,
                "validation_agent",
                "Validation gate (simulated)",
            ),
            PipelineState.VALIDATION: (
                PipelineState.WAITING_HUMAN_APPROVAL,
                "pipeline_orchestrator",
                "Human approval gate (simulated)",
            ),
        }

        if state in transitions:
            to_state, triggered_by, reason = transitions[state]
            return {
                "from_state": state.value,
                "to_state": to_state.value,
                "triggered_by": triggered_by,
                "reason": reason,
            }

        if state == PipelineState.WAITING_HUMAN_APPROVAL:
            if approval and approval.get("approved", False):
                return {
                    "from_state": state.value,
                    "to_state": PipelineState.READY_FOR_RELEASE.value,
                    "triggered_by": "approval_gate",
                    "reason": "Human approval already granted (simulated)",
                }
            else:
                return None  # Blocked

        if state == PipelineState.READY_FOR_RELEASE:
            return {
                "from_state": state.value,
                "to_state": PipelineState.RELEASED.value,
                "triggered_by": "release_manager",
                "reason": "Release executed (simulated)",
            }

        return None


# ═══════════════════════════════════════════════════════════════════════
# Pipeline state helpers (read-only, no agent modification)
# ═══════════════════════════════════════════════════════════════════════


def _build_state_machine(pipeline_id: str, root: Path) -> StateMachine:
    """Build and load a StateMachine, returning it regardless of load success."""
    sm = StateMachine(pipeline_id, root)
    sm.load()
    return sm


def _build_orchestrator(pipeline_id: str, root: Path,
                        config: dict[str, Any] | None = None) -> PipelineOrchestrator:
    """Build a PipelineOrchestrator (agents are lazy-initialized, no side effects)."""
    return PipelineOrchestrator(pipeline_id, str(root), config=config)


def _build_approval_gate(root: Path) -> ApprovalGate:
    return ApprovalGate(root)


# ═══════════════════════════════════════════════════════════════════════
# CLI action handlers
# ═══════════════════════════════════════════════════════════════════════


def cmd_run(args: argparse.Namespace) -> dict[str, Any]:
    """Execute the full pipeline or simulate with --dry-run.

    Returns a dict suitable for JSON serialisation.
    """
    root = Path(args.root) if args.root else _get_root()
    config: dict[str, Any] = {}
    if args.config:
        try:
            config = json.loads(args.config)
        except json.JSONDecodeError as e:
            return _error_result(f"Invalid --config JSON: {e}")

    if args.dry_run:
        dry = DryRunOrchestrator(args.pipeline_id, root, config)
        report = dry.simulate_full_pipeline()
        return {
            "command": "run",
            "mode": "dry-run",
            "pipeline_id": args.pipeline_id,
            "dry_run_report": report,
            "message": (
                f"DRY-RUN: Pipeline '{args.pipeline_id}' would advance from "
                f"{report['current_state']} through "
                f"{len(report['simulated_progression'])} transition(s). "
                f"Use without --dry-run to execute."
            ),
        }

    orch = _build_orchestrator(args.pipeline_id, root, config)
    result = orch.run_full_pipeline()

    return {
        "command": "run",
        "mode": "live",
        "pipeline_id": args.pipeline_id,
        "result": result.to_dict(),
        "message": _human_readable_summary(result),
    }


def cmd_status(args: argparse.Namespace) -> dict[str, Any]:
    """Check pipeline status without executing agents.

    Reads state machine + approval gate state. Read-only.
    """
    root = Path(args.root) if args.root else _get_root()
    sm = _build_state_machine(args.pipeline_id, root)
    gate = _build_approval_gate(root)
    approval = gate.check_approval_gate(args.pipeline_id)
    state_summary = sm.summary()

    order = [s.value for s in PipelineState]
    try:
        current_idx = order.index(state_summary["current_state"])
    except ValueError:
        current_idx = -1

    pipeline_progress = {
        "state": state_summary["current_state"],
        "index": current_idx,
        "total_states": len(order),
        "progress_pct": round((current_idx + 1) / len(order) * 100, 1) if current_idx >= 0 else 0,
    }

    return {
        "command": "status",
        "pipeline_id": args.pipeline_id,
        "state_machine": state_summary,
        "approval_gate": approval,
        "pipeline_progress": pipeline_progress,
        "is_terminal": state_summary["is_terminal"],
        "is_blocked_on_approval": state_summary["is_blocked_on_human_approval"],
        "has_approval_request": approval.get("request") is not None,
        "is_approved": approval.get("approved", False),
        "message": _build_status_message(state_summary, approval),
    }


def cmd_request_approval(args: argparse.Namespace) -> dict[str, Any]:
    """Create a human approval request for the pipeline.

    Does NOT run agents — only creates the approval request record
    so the pipeline can be blocked at WAITING_HUMAN_APPROVAL.
    """
    root = Path(args.root) if args.root else _get_root()
    orch = _build_orchestrator(args.pipeline_id, root)
    role = ApproverRole(args.role) if args.role else ApproverRole.REVIEWER

    # Check if a request already exists
    existing = orch.approval_gate.get_request(args.pipeline_id)
    if existing is not None:
        return {
            "command": "request-approval",
            "pipeline_id": args.pipeline_id,
            "created": False,
            "existing_request": existing.to_dict(),
            "message": (
                f"Approval request already exists for pipeline "
                f"'{args.pipeline_id}' (decision: {existing.decision.value}). "
                f"Use 'approve' or 'deny' to act on it, or "
                f"'rescind' to clear it."
            ),
        }

    artifacts = args.artifacts.split(",") if args.artifacts else None

    request = orch.request_human_approval(
        requested_by=args.requested_by or "cli_user",
        role=role,
        artifacts=artifacts,
    )

    return {
        "command": "request-approval",
        "pipeline_id": args.pipeline_id,
        "created": True,
        "request": request,
        "message": (
            f"Approval request created for pipeline '{args.pipeline_id}'. "
            f"Role required: {role.value}. "
            f"Use 'approve' or 'deny' to respond."
        ),
    }


def cmd_approve(args: argparse.Namespace) -> dict[str, Any]:
    """Approve a pipeline for release.

    If the pipeline is at WAITING_HUMAN_APPROVAL, the runner attempts
    to advance it through to RELEASED via PipelineOrchestrator.approve_release().
    """
    root = Path(args.root) if args.root else _get_root()
    orch = _build_orchestrator(args.pipeline_id, root)
    role = ApproverRole(args.role) if args.role else ApproverRole.REVIEWER

    approval_check = orch.approve_release(
        decided_by=args.by,
        role=role,
        comments=args.comment or "",
    )

    # Re-read state machine to see if we advanced
    sm = _build_state_machine(args.pipeline_id, root)
    current_state = sm.current_state.value

    is_released = current_state == PipelineState.RELEASED.value
    is_approved = approval_check.get("approved", False)

    return {
        "command": "approve",
        "pipeline_id": args.pipeline_id,
        "approved": True,
        "pipeline_state": current_state,
        "is_released": is_released,
        "approval_check": approval_check,
        "message": (
            f"Pipeline '{args.pipeline_id}' approved by {args.by}. "
            f"Pipeline state: {current_state}. "
            + ("Release completed successfully."
               if is_released
               else "Waiting for manual release execution.")
        ),
    }


def cmd_deny(args: argparse.Namespace) -> dict[str, Any]:
    """Deny a pipeline release."""
    root = Path(args.root) if args.root else _get_root()
    orch = _build_orchestrator(args.pipeline_id, root)
    role = ApproverRole(args.role) if args.role else ApproverRole.REVIEWER

    # Auto-create request if none exists (so denial has a record)
    existing = orch.approval_gate.get_request(args.pipeline_id)
    if existing is None:
        orch.request_human_approval(
            requested_by="cli_user",
            role=role,
        )

    approval_check = orch.deny_release(
        decided_by=args.by,
        role=role,
        comments=args.reason or "",
    )

    return {
        "command": "deny",
        "pipeline_id": args.pipeline_id,
        "denied": True,
        "pipeline_state": orch.state_machine.current_state.value,
        "approval_check": approval_check,
        "message": (
            f"Pipeline '{args.pipeline_id}' denied by {args.by}. "
            + (f"Reason: {args.reason}. " if args.reason else "")
            + "Release blocked."
        ),
    }


def cmd_release(args: argparse.Namespace) -> dict[str, Any]:
    """Execute release on a pipeline that has human approval.

    This runs the final stage of the pipeline only: it checks that
    human approval is in place, then executes the ReleaseManager.

    Unlike ``run``, this does not re-run quality/provenance/revision/validation.
    """
    root = Path(args.root) if args.root else _get_root()
    gate = _build_approval_gate(root)

    # Check approval status first
    if not gate.is_releasable(args.pipeline_id):
        approval = gate.check_approval_gate(args.pipeline_id)
        return {
            "command": "release",
            "pipeline_id": args.pipeline_id,
            "executed": False,
            "reason": "NOT_APPROVED",
            "approval_gate": approval,
            "message": (
                f"Cannot release pipeline '{args.pipeline_id}': "
                f"human approval not granted. "
                f"Use 'approve' first, or 'run' to run the full pipeline."
            ),
        }

    # Build the orchestrator and try to advance from current state
    sm = _build_state_machine(args.pipeline_id, root)
    state_str = sm.current_state.value
    state = PipelineState(state_str)

    if state == PipelineState.WAITING_HUMAN_APPROVAL:
        orch = _build_orchestrator(args.pipeline_id, root)
        result = orch.run_full_pipeline()
        return {
            "command": "release",
            "pipeline_id": args.pipeline_id,
            "executed": True,
            "pipeline_result": result.to_dict(),
            "is_released": result.status == PipelineStatus.COMPLETED,
            "message": _human_readable_summary(result),
        }

    if state == PipelineState.READY_FOR_RELEASE:
        # Direct transition to RELEASED
        sm.transition_to(
            PipelineState.RELEASED,
            triggered_by="automation_runner",
            reason="Release executed via CLI",
        )
        return {
            "command": "release",
            "pipeline_id": args.pipeline_id,
            "executed": True,
            "pipeline_state": PipelineState.RELEASED.value,
            "message": (
                f"Pipeline '{args.pipeline_id}' released. "
                f"State: RELEASED."
            ),
        }

    if state == PipelineState.RELEASED:
        return {
            "command": "release",
            "pipeline_id": args.pipeline_id,
            "executed": False,
            "reason": "ALREADY_RELEASED",
            "pipeline_state": state.value,
            "message": (
                f"Pipeline '{args.pipeline_id}' has already been released. "
                f"Current state: RELEASED."
            ),
        }

    if state == PipelineState.RELEASE_REJECTED:
        return {
            "command": "release",
            "pipeline_id": args.pipeline_id,
            "executed": False,
            "reason": "PREVIOUSLY_REJECTED",
            "pipeline_state": state.value,
            "message": (
                f"Cannot release pipeline '{args.pipeline_id}': "
                f"it was previously rejected. "
                f"Use 'run' to restart the pipeline."
            ),
        }

    # For any other state, run the full pipeline starting from here
    orch = _build_orchestrator(args.pipeline_id, root)
    result = orch.run_full_pipeline()
    return {
        "command": "release",
        "pipeline_id": args.pipeline_id,
        "executed": True,
        "pipeline_result": result.to_dict(),
        "is_released": result.status == PipelineStatus.COMPLETED,
        "message": _human_readable_summary(result),
    }


def cmd_rescind(args: argparse.Namespace) -> dict[str, Any]:
    """Rescind/clear an approval decision (reset to PENDING)."""
    root = Path(args.root) if args.root else _get_root()
    gate = _build_approval_gate(root)

    result = gate.reject_or_rescind(args.pipeline_id)
    if result:
        return {
            "command": "rescind",
            "pipeline_id": args.pipeline_id,
            "rescinded": True,
            "message": (
                f"Approval decision for pipeline '{args.pipeline_id}' "
                f"has been rescinded (reset to PENDING)."
            ),
        }
    return {
        "command": "rescind",
        "pipeline_id": args.pipeline_id,
        "rescinded": False,
        "message": (
            f"No approval request found for pipeline "
            f"'{args.pipeline_id}'. Nothing to rescind."
        ),
    }


# ═══════════════════════════════════════════════════════════════════════
# Formatting helpers
# ═══════════════════════════════════════════════════════════════════════


def _human_readable_summary(result: PipelineResult) -> str:
    """Build a concise human-readable summary from a PipelineResult."""
    parts = [
        f"Pipeline '{result.pipeline_id}' — {result.status}",
        f"  State: {result.current_state}",
    ]

    if result.agent_results:
        parts.append("  Agents:")
        for name, ar in sorted(result.agent_results.items()):
            icon = {
                "passed": "✓",
                "failed": "✗",
                "skipped": "–",
                "pending": "○",
                "running": "▶",
                "blocked": "⊘",
            }.get(getattr(ar, "status", ""), "?")
            summary_text = getattr(ar, "summary", "")
            parts.append(f"    {icon} {name}: {summary_text}")

    if result.errors:
        parts.append(f"  Errors ({len(result.errors)}):")
        for err in result.errors[:5]:
            parts.append(f"    ⚠ {err}")
        if len(result.errors) > 5:
            parts.append(f"    ... and {len(result.errors) - 5} more")

    parts.append(f"  Summary: {result.summary}")
    return "\n".join(parts)


def _build_status_message(state_summary: dict[str, Any],
                          approval: dict[str, Any]) -> str:
    """Build a human-readable status message."""
    state = state_summary.get("current_state", "UNKNOWN")
    parts = [f"Pipeline status: {state}"]

    if state_summary.get("is_terminal"):
        parts.append("  ✓ Pipeline has reached a terminal state.")
    elif state_summary.get("is_blocked_on_human_approval"):
        parts.append("  ⊘ Pipeline is BLOCKED — awaiting human approval.")
        req = approval.get("request")
        if req:
            parts.append(f"    Requested at: {req.get('requested_at', '?')}")
            parts.append(f"    Required role: {req.get('role', '?')}")
        else:
            parts.append("    No approval request has been created yet.")
    elif state_summary.get("has_failure") or state == "FAILED":
        parts.append("  ✗ Pipeline has FAILED.")
        fi = state_summary.get("failure_info")
        if fi:
            parts.append(f"    Failed agent: {fi.get('agent_name', '?')}")
            parts.append(f"    Reason: {fi.get('reason', '?')}")
            parts.append(f"    Recommended action: {fi.get('next_action', '?')}")
            parts.append(f"    Failed at: {fi.get('timestamp', '?')}")
    else:
        parts.append("  Pipeline is active and can advance.")

    if approval.get("approved"):
        parts.append("  ✓ Human approval has been GRANTED.")
    elif approval.get("request") is not None:
        decision = approval.get("request", {}).get("decision", "pending")
        parts.append(f"  Decision: {decision}")

    transitions = state_summary.get("total_transitions", 0)
    if transitions:
        parts.append(f"  Transitions recorded: {transitions}")

    error = state_summary.get("error")
    if error:
        parts.append(f"  Error: {error}")

    return "\n".join(parts)


def _error_result(message: str) -> dict[str, Any]:
    return {
        "error": True,
        "message": message,
    }


def cmd_retry(args: argparse.Namespace) -> dict[str, Any]:
    """Retry a failed agent in a pipeline.

    Only re-runs the specific agent that failed.
    On success, continues the rest of the pipeline.
    On failure, stays FAILED with an updated retry record.
    """
    root = Path(args.root) if args.root else _get_root()
    config: dict[str, Any] = {}
    if args.config:
        try:
            config = json.loads(args.config)
        except json.JSONDecodeError as e:
            return _error_result(f"Invalid --config JSON: {e}")

    result = retry_failed_agent(
        pipeline_id=args.pipeline_id,
        root=root,
        config=config,
    )

    return {
        "command": "retry",
        "pipeline_id": args.pipeline_id,
        **result,
    }


def cmd_resume(args: argparse.Namespace) -> dict[str, Any]:
    """Resume a failed pipeline by clearing failure and continuing.

    Transitions back to the pre-failure state and runs the full pipeline.
    """
    root = Path(args.root) if args.root else _get_root()
    config: dict[str, Any] = {}
    if args.config:
        try:
            config = json.loads(args.config)
        except json.JSONDecodeError as e:
            return _error_result(f"Invalid --config JSON: {e}")

    result = resume_pipeline(
        pipeline_id=args.pipeline_id,
        root=root,
        config=config,
    )

    return {
        "command": "resume",
        "pipeline_id": args.pipeline_id,
        **result,
    }


def cmd_retry_history(args: argparse.Namespace) -> dict[str, Any]:
    """Show retry history for a pipeline."""
    root = Path(args.root) if args.root else _get_root()
    mgr = RetryManager(args.pipeline_id, root)
    history = mgr.load_history()

    return {
        "command": "retry-history",
        "pipeline_id": args.pipeline_id,
        "retry_count": len(history),
        "retry_history": history,
        "message": (
            f"Pipeline '{args.pipeline_id}' has {len(history)} retry "
            f"record(s)."
        ),
    }


def cmd_acquire(args: argparse.Namespace) -> dict[str, Any]:
    """Run AcquisitionAgent v1 for the Atlas acquisition workflow."""
    root = Path(args.root) if args.root else _get_root()
    agent = AcquisitionAgent(root, config={"mode": args.mode})

    try:
        result = agent.execute()
    except Exception as exc:
        return {
            "command": "acquire",
            "mode": args.mode,
            "error": True,
            "message": f"AcquisitionAgent failed: {exc}",
        }

    payload = result.to_dict()
    payload["command"] = "acquire"
    payload["mode"] = args.mode
    payload["message"] = result.summary
    return payload


def cmd_download(args: argparse.Namespace) -> dict[str, Any]:
    """Run DownloadAgent v1.6 — fetch acquired sources into raw/.cache/."""
    root = Path(args.root) if args.root else _get_root()
    config: dict[str, Any] = {
        "mode": args.mode,
        "max_retries": args.max_retries,
        "timeout": args.timeout,
    }
    if args.source_id:
        config["source_ids"] = list(args.source_id)
    if args.use_registry:
        config["use_registry"] = True
    if args.max_files is not None:
        config["max_files"] = args.max_files
    if args.force:
        config["force"] = True

    agent = DownloadAgent(root, config=config)
    try:
        result = agent.execute()
    except Exception as exc:
        return {
            "command": "download",
            "mode": args.mode,
            "error": True,
            "message": f"DownloadAgent failed: {exc}",
        }

    payload = result.to_dict()
    payload["command"] = "download"
    payload["mode"] = args.mode
    payload["message"] = result.summary
    if result.failed:
        payload["error"] = True
    return payload


def cmd_cache_stats(args: argparse.Namespace) -> dict[str, Any]:
    """Show content-addressable cache statistics."""
    root = Path(args.root) if args.root else _get_root()
    cache = CacheManager(root)
    stats = cache.stats()
    entries = [e.to_dict() for e in cache.list_entries()]
    return {
        "command": "cache-stats",
        "stats": stats,
        "entries": entries if args.list_entries else [],
        "message": (
            f"Cache at {stats['cache_dir']}: {stats['entries']} entries, "
            f"{stats['total_bytes']} bytes"
        ),
    }


def cmd_etl(args: argparse.Namespace) -> dict[str, Any]:
    """Run Extract → Normalize → Clean (ETL v1.7) on cached downloads."""
    root = Path(args.root) if args.root else _get_root()
    config: dict[str, Any] = {
        "promote_atlas": not args.no_promote,
    }
    if args.source_id:
        config["source_ids"] = list(args.source_id)
    if args.limit is not None:
        config["limit"] = args.limit

    agent = ExtractAgent(root, config=config)
    try:
        result = agent.execute()
    except Exception as exc:
        return {
            "command": "etl",
            "error": True,
            "message": f"ExtractAgent failed: {exc}",
        }

    payload = result.to_dict()
    payload["command"] = "etl"
    payload["message"] = result.summary
    if result.failed:
        payload["error"] = True
    return payload


def cmd_transform(args: argparse.Namespace) -> dict[str, Any]:
    """Run Transform layer v1.8 on ETL cleaned/staging records."""
    root = Path(args.root) if args.root else _get_root()
    source_ids = list(args.source_id) if args.source_id else []
    if not source_ids:
        etl_root = root / "metadata" / "etl"
        source_ids = sorted(p.name for p in etl_root.iterdir() if p.is_dir()) if etl_root.exists() else []
    if not source_ids:
        return {"command": "transform", "error": True, "message": "No source ids / ETL outputs found."}

    reports = []
    for sid in source_ids:
        reports.append(run_transform(root, sid, limit=args.limit, prefer=args.prefer))
    failed = [r for r in reports if r.get("status") == "failed"]
    return {
        "command": "transform",
        "reports": reports,
        "message": (
            f"Transform complete for {len(reports)} source(s); "
            f"{len(failed)} failure(s)"
        ),
        "error": bool(failed) and len(failed) == len(reports),
    }


def cmd_views(args: argparse.Namespace) -> dict[str, Any]:
    """Build model-family training views (v1.8)."""
    root = Path(args.root) if args.root else _get_root()
    models = [m.strip() for m in (args.models or "qwen,llama,deepseek").split(",") if m.strip()]
    result = build_views(
        root,
        version=args.version,
        models=models,
        source_ids=list(args.source_id) if args.source_id else None,
        curated_version=args.curated_version,
        allow_staging=not args.production,
        quality_threshold=args.quality_threshold,
        eval_ratio=args.eval_ratio,
        limit=args.limit,
    )
    payload = result.to_dict()
    payload["command"] = "views"
    payload["message"] = result.summary
    if result.status in {"failed", "blocked"}:
        payload["error"] = True
    return payload


def cmd_release_build(args: argparse.Namespace) -> dict[str, Any]:
    """Package a release bundle (v1.8 Release Builder)."""
    root = Path(args.root) if args.root else _get_root()
    result = build_release(
        root,
        version=args.version,
        source_ids=list(args.source_id) if args.source_id else None,
        view_version=args.view_version or args.version,
        allow_staging=not args.production,
        hub_publish=args.hub_publish,
    )
    payload = result.to_dict()
    payload["command"] = "release-build"
    payload["message"] = result.summary
    if result.status in {"failed", "blocked"}:
        payload["error"] = True
    return payload


def cmd_publish(args: argparse.Namespace) -> dict[str, Any]:
    """Orchestrate Transform → Views → Release Bundle."""
    root = Path(args.root) if args.root else _get_root()
    config: dict[str, Any] = {
        "version": args.version,
        "allow_staging": not args.production,
        "hub_publish": args.hub_publish,
        "skip_transform": args.skip_transform,
        "skip_views": args.skip_views,
    }
    if args.source_id:
        config["source_ids"] = list(args.source_id)
    if args.models:
        config["models"] = [m.strip() for m in args.models.split(",") if m.strip()]
    if args.limit is not None:
        config["limit"] = args.limit

    agent = PublishAgent(root, config=config)
    try:
        result = agent.execute()
    except Exception as exc:
        return {"command": "publish", "error": True, "message": f"PublishAgent failed: {exc}"}

    payload = result.to_dict()
    payload["command"] = "publish"
    payload["message"] = result.summary
    if result.failed or result.status.value == "blocked":
        payload["error"] = True
    return payload


# ═══════════════════════════════════════════════════════════════════════
# CLI argument parser
# ═══════════════════════════════════════════════════════════════════════


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="automation-runner",
        description="Atlas Automation Runner v1.5 — pipeline orchestration CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:

              # Full pipeline run
              %(prog)s run --pipeline-id release-v0.3

              # Dry-run (simulate, no side effects)
              %(prog)s run --pipeline-id release-v0.3 --dry-run

              # Check status
              %(prog)s status --pipeline-id release-v0.3

              # Request approval
              %(prog)s request-approval --pipeline-id release-v0.3 --role reviewer

              # Approve
              %(prog)s approve --pipeline-id release-v0.3 --by reviewer_jane

              # Deny
              %(prog)s deny --pipeline-id release-v0.3 --by reviewer_bob --reason "Need fixes"

              # Execute release on approved pipeline
              %(prog)s release --pipeline-id release-v0.3

              # Rescind a previous approval
              %(prog)s rescind --pipeline-id release-v0.3

              # Retry a failed agent
              %(prog)s retry --pipeline-id release-v0.3

              # Resume a failed pipeline
              %(prog)s resume --pipeline-id release-v0.3

              # Show retry history
              %(prog)s retry-history --pipeline-id release-v0.3
        """),
    )

    parser.add_argument(
        "--root",
        help="Path to atlas-dataset repository root (auto-discovered by default).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output raw JSON instead of formatted text.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── run ──────────────────────────────────────────────────────────
    run_parser = subparsers.add_parser(
        "run",
        help="Execute the full pipeline end-to-end.",
    )
    run_parser.add_argument("--pipeline-id", required=True,
                            help="Pipeline identifier (e.g. release-v0.3).")
    run_parser.add_argument("--dry-run", action="store_true",
                            help="Simulate pipeline execution without side effects.")
    run_parser.add_argument("--config", help="JSON config string for the pipeline.")
    run_parser.set_defaults(func=cmd_run)

    # ── status ───────────────────────────────────────────────────────
    status_parser = subparsers.add_parser(
        "status",
        help="Check pipeline status without executing agents.",
    )
    status_parser.add_argument("--pipeline-id", required=True,
                               help="Pipeline identifier to query.")
    status_parser.set_defaults(func=cmd_status)

    # ── request-approval ─────────────────────────────────────────────
    req_parser = subparsers.add_parser(
        "request-approval",
        help="Create a human approval request for the pipeline.",
    )
    req_parser.add_argument("--pipeline-id", required=True)
    req_parser.add_argument("--role", default="reviewer",
                            choices=[r.value for r in ApproverRole],
                            help="Required approver role (default: reviewer).")
    req_parser.add_argument("--requested-by", default="cli_user",
                            help="Who is requesting the approval.")
    req_parser.add_argument("--artifacts",
                            help="Comma-separated artifact paths for review.")
    req_parser.set_defaults(func=cmd_request_approval)

    # ── approve ──────────────────────────────────────────────────────
    approve_parser = subparsers.add_parser(
        "approve",
        help="Approve a pipeline for release.",
    )
    approve_parser.add_argument("--pipeline-id", required=True)
    approve_parser.add_argument("--by", required=True,
                                help="Identifier of the approver (e.g. reviewer_jane).")
    approve_parser.add_argument("--role", default="reviewer",
                                choices=[r.value for r in ApproverRole],
                                help="Approver's role (default: reviewer).")
    approve_parser.add_argument("--comment", default="",
                                help="Optional approval comment.")
    approve_parser.set_defaults(func=cmd_approve)

    # ── deny ─────────────────────────────────────────────────────────
    deny_parser = subparsers.add_parser(
        "deny",
        help="Deny a pipeline release.",
    )
    deny_parser.add_argument("--pipeline-id", required=True)
    deny_parser.add_argument("--by", required=True,
                             help="Identifier of the person denying.")
    deny_parser.add_argument("--role", default="reviewer",
                             choices=[r.value for r in ApproverRole],
                             help="Denier's role (default: reviewer).")
    deny_parser.add_argument("--reason", default="",
                             help="Reason for denial.")
    deny_parser.set_defaults(func=cmd_deny)

    # ── release ──────────────────────────────────────────────────────
    release_parser = subparsers.add_parser(
        "release",
        help="Execute release on an approved pipeline.",
    )
    release_parser.add_argument("--pipeline-id", required=True)
    release_parser.set_defaults(func=cmd_release)

    # ── rescind ──────────────────────────────────────────────────────
    rescind_parser = subparsers.add_parser(
        "rescind",
        help="Rescind/clear a previous approval decision.",
    )
    rescind_parser.add_argument("--pipeline-id", required=True)
    rescind_parser.set_defaults(func=cmd_rescind)

    # ── retry ───────────────────────────────────────────────────────
    retry_parser = subparsers.add_parser(
        "retry",
        help="Retry a failed agent in a pipeline.",
    )
    retry_parser.add_argument("--pipeline-id", required=True,
                              help="Pipeline identifier to retry.")
    retry_parser.add_argument("--config",
                              help="JSON config string for the pipeline.")
    retry_parser.set_defaults(func=cmd_retry)

    # ── resume ──────────────────────────────────────────────────────
    resume_parser = subparsers.add_parser(
        "resume",
        help="Resume a failed pipeline by clearing failure and continuing.",
    )
    resume_parser.add_argument("--pipeline-id", required=True,
                               help="Pipeline identifier to resume.")
    resume_parser.add_argument("--config",
                               help="JSON config string for the pipeline.")
    resume_parser.set_defaults(func=cmd_resume)

    # ── acquire ───────────────────────────────────────────────────────
    acquire_parser = subparsers.add_parser(
        "acquire",
        help="Run AcquisitionAgent v1 with dry-run or acquire mode.",
    )
    acquire_parser.add_argument("--mode", default="dry-run", choices=["dry-run", "acquire"],
                                help="Acquisition mode.")
    acquire_parser.set_defaults(func=cmd_acquire)

    # ── download (v1.6) ──────────────────────────────────────────────
    download_parser = subparsers.add_parser(
        "download",
        help="Download acquired sources into raw/.cache/ (Downloader v1.6).",
    )
    download_parser.add_argument(
        "--mode",
        default="dry-run",
        choices=["dry-run", "download"],
        help="Download mode (default: dry-run).",
    )
    download_parser.add_argument(
        "--source-id",
        action="append",
        default=[],
        help="Limit to one or more source ids (repeatable).",
    )
    download_parser.add_argument(
        "--use-registry",
        action="store_true",
        help="Fall back to accepted/review registry sources when no acquisition logs exist.",
    )
    download_parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Max files per HuggingFace dataset (default adapter: 3).",
    )
    download_parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Network retry budget (default: 3).",
    )
    download_parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Per-request timeout seconds (default: 60).",
    )
    download_parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even when a cache entry already exists.",
    )
    download_parser.set_defaults(func=cmd_download)

    # ── cache-stats ──────────────────────────────────────────────────
    cache_parser = subparsers.add_parser(
        "cache-stats",
        help="Show raw/.cache/ statistics and optional entry listing.",
    )
    cache_parser.add_argument(
        "--list-entries",
        action="store_true",
        help="Include per-source cache entries in the output.",
    )
    cache_parser.set_defaults(func=cmd_cache_stats)

    # ── etl (v1.7) ───────────────────────────────────────────────────
    etl_parser = subparsers.add_parser(
        "etl",
        help="Extract → Normalize → Clean cached downloads (ETL v1.7).",
    )
    etl_parser.add_argument(
        "--source-id",
        action="append",
        default=[],
        help="Source id(s) to process (repeatable). Defaults to all download logs.",
    )
    etl_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max records to extract per source (useful for smoke tests).",
    )
    etl_parser.add_argument(
        "--no-promote",
        action="store_true",
        help="Skip promotion to atlas_staging.jsonl.",
    )
    etl_parser.set_defaults(func=cmd_etl)

    # ── transform (v1.8) ─────────────────────────────────────────────
    transform_parser = subparsers.add_parser(
        "transform",
        help="Transform cleaned ETL records into 5 training types (v1.8).",
    )
    transform_parser.add_argument("--source-id", action="append", default=[])
    transform_parser.add_argument("--limit", type=int, default=None)
    transform_parser.add_argument(
        "--prefer",
        choices=["cleaned", "atlas_staging", "normalized"],
        default="cleaned",
        help="Which ETL artifact to transform (default: cleaned).",
    )
    transform_parser.set_defaults(func=cmd_transform)

    # ── views (v1.8) ─────────────────────────────────────────────────
    views_parser = subparsers.add_parser(
        "views",
        help="Build model-family training views (v1.8).",
    )
    views_parser.add_argument("--version", required=True, help="View package version id.")
    views_parser.add_argument("--source-id", action="append", default=[])
    views_parser.add_argument("--models", default="qwen,llama,deepseek")
    views_parser.add_argument("--curated-version", default=None,
                              help="Load from curated/<version> instead of ETL staging.")
    views_parser.add_argument("--production", action="store_true",
                              help="Require approved curated records (no staging).")
    views_parser.add_argument("--quality-threshold", type=int, default=7)
    views_parser.add_argument("--eval-ratio", type=float, default=0.1)
    views_parser.add_argument("--limit", type=int, default=None)
    views_parser.set_defaults(func=cmd_views)

    # ── release-build (v1.8) ─────────────────────────────────────────
    rb_parser = subparsers.add_parser(
        "release-build",
        help="Package a release bundle under metadata/release_bundles/ (v1.8).",
    )
    rb_parser.add_argument("--version", required=True)
    rb_parser.add_argument("--source-id", action="append", default=[])
    rb_parser.add_argument("--view-version", default=None)
    rb_parser.add_argument("--production", action="store_true")
    rb_parser.add_argument("--hub-publish", action="store_true",
                           help="Request HF Hub publish (stub — not configured).")
    rb_parser.set_defaults(func=cmd_release_build)

    # ── publish (v1.8 orchestrator) ──────────────────────────────────
    pub_parser = subparsers.add_parser(
        "publish",
        help="Run Transform → Views → Release Bundle (PublishAgent v1.8).",
    )
    pub_parser.add_argument("--version", required=True)
    pub_parser.add_argument("--source-id", action="append", default=[])
    pub_parser.add_argument("--models", default="qwen,llama,deepseek")
    pub_parser.add_argument("--limit", type=int, default=None)
    pub_parser.add_argument("--production", action="store_true")
    pub_parser.add_argument("--hub-publish", action="store_true")
    pub_parser.add_argument("--skip-transform", action="store_true")
    pub_parser.add_argument("--skip-views", action="store_true")
    pub_parser.set_defaults(func=cmd_publish)

    # ── retry-history ───────────────────────────────────────────────
    rh_parser = subparsers.add_parser(
        "retry-history",
        help="Show retry history for a pipeline.",
    )
    rh_parser.add_argument("--pipeline-id", required=True,
                           help="Pipeline identifier to query.")
    rh_parser.set_defaults(func=cmd_retry_history)

    return parser


# ═══════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════


def main(argv: list[str] | None = None) -> NoReturn | None:
    """CLI entry point. Parses args, dispatches to the handler, prints result.

    Returns None on success, exits with code 1 on error.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        result = args.func(args)
    except Exception as e:
        result = _error_result(str(e))

    if args.output_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        _render_text(result)

    if result.get("error"):
        sys.exit(1)


def _render_text(result: dict[str, Any]) -> None:
    """Render the result dict as human-readable text."""
    if result.get("error"):
        print(f"ERROR: {result['message']}", file=sys.stderr)
        return

    header = f"── {result.get('command', 'action').upper()} ──"
    print(f"\n{header}")
    print(result.get("message", json.dumps(result, indent=2)))

    # Additional detail sections for specific commands
    if result.get("command") == "status":
        sm = result.get("state_machine", {})
        progress = result.get("pipeline_progress", {})
        print(f"\n  Progress: {progress.get('progress_pct', '?')}% "
              f"({progress.get('index', 0)}/{progress.get('total_states', 0)} states)")

        # Show failure details when present
        if sm.get("has_failure"):
            fi = sm.get("failure_info")
            print("  ✗ FAILURE:")
            if fi:
                print(f"    Agent: {fi.get('agent_name', '?')}")
                print(f"    Reason: {fi.get('reason', '?')}")
                print(f"    Recommended: {fi.get('next_action', '?')}")
                print(f"    Time: {fi.get('timestamp', '?')}")

        if result.get("has_approval_request"):
            approval = result.get("approval_gate", {})
            print(f"  Approval: {'GRANTED' if result.get('is_approved') else 'PENDING/DENIED'}")
            req = approval.get("request")
            if req:
                print(f"    Requested at: {req.get('requested_at', '?')}")
                if req.get("decided_at"):
                    print(f"    Decided at: {req.get('decided_at', '?')}")
                    print(f"    Decided by: {req.get('decided_by', '?')}")
                    print(f"    Comments: {req.get('comments', '')}")

        transitions = sm.get("last_transition")
        if transitions:
            print(f"  Last transition: "
                  f"{transitions.get('from_state', '?')} "
                  f"→ {transitions.get('to_state', '?')} "
                  f"({transitions.get('triggered_by', '?')})")

    elif result.get("command") == "run" and result.get("mode") == "dry-run":
        report = result.get("dry_run_report", {})
        agents = report.get("agents_to_run", [])
        progression = report.get("simulated_progression", [])
        print(f"\n  Agents to run: {', '.join(agents) if agents else '(none)'}")
        print(f"  Simulated transitions:")
        for step in progression:
            print(f"    {step.get('from_state', '?')} → {step.get('to_state', '?')} "
                  f"({step.get('triggered_by', '?')})")

    elif result.get("command") == "run" and result.get("mode") == "live":
        pipeline_result = result.get("result", {})
        agents = pipeline_result.get("agent_results", {})
        if agents:
            print(f"\n  Agent results:")
            for name, ar in sorted(agents.items()):
                status = ar.get("status", "?")
                summary = ar.get("summary", "")
                print(f"    [{status.upper():8s}] {name}: {summary}")

    elif result.get("command") == "etl":
        totals = (result.get("data") or {}).get("totals") or {}
        sources = (result.get("data") or {}).get("sources") or []
        print(f"\n  Totals: extracted={totals.get('extracted', 0)} "
              f"cleaned={totals.get('cleaned', 0)} "
              f"atlas_staging={totals.get('atlas_records', 0)} "
              f"dropped={totals.get('dropped', 0)}")
        for src in sources:
            print(f"    [{src.get('status', '?'):7s}] {src.get('source_id')}: "
                  f"{src.get('summary', '')}")
            if src.get("output_dir"):
                print(f"             → {src['output_dir']}")

    elif result.get("command") == "transform":
        for rep in result.get("reports") or []:
            print(f"    [{rep.get('status', '?'):7s}] {rep.get('source_id')}: "
                  f"{rep.get('summary', '')}")
            if rep.get("type_counts"):
                print(f"             types={rep['type_counts']}")

    elif result.get("command") == "views":
        print(f"\n  Mode: {result.get('mode')}  records={result.get('record_count')}  "
              f"eval={result.get('eval_count')}")
        for model, meta in (result.get("views") or {}).items():
            print(f"    {model}: {meta.get('records')} → {meta.get('path')}")
        if result.get("output_dir"):
            print(f"  Output: {result['output_dir']}")

    elif result.get("command") == "release-build":
        print(f"\n  Bundle: {result.get('bundle_dir')}")
        print(f"  Records: {result.get('record_count')}  files={len(result.get('files') or [])}")

    elif result.get("command") == "publish":
        data = result.get("data") or {}
        if data.get("release"):
            print(f"\n  Release: {data['release'].get('summary')}")
            print(f"  Bundle: {data['release'].get('bundle_dir')}")


if __name__ == "__main__":
    main()
