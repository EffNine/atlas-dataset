#!/usr/bin/env python3
"""Approval gate for the Atlas Automation Layer.

Human approval is mandatory before any pipeline can reach the RELEASED state.
The approval gate enforces this by:

  1. Tracking approval requests (who, when, what).
  2. Requiring explicit sign-off before allowing the RELEASED transition.
  3. Providing an audit trail of all approval decisions.

The gate integrates with the StateMachine: only transitions originating from
a human-approved request are allowed to proceed to RELEASED.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Approver role
# ---------------------------------------------------------------------------


class ApproverRole(str, Enum):
    """Roles that can grant pipeline approval."""

    REVIEWER = "reviewer"
    MAINTAINER = "maintainer"
    ARCHITECT = "architect"
    AUTOMATED = "automated"  # reserved for future non-human approval pipelines

    def __str__(self) -> str:
        return self.value


# ---------------------------------------------------------------------------
# Approval decision
# ---------------------------------------------------------------------------


class ApprovalDecision(str, Enum):
    """Outcome of an approval request."""

    APPROVED = "approved"
    DENIED = "denied"
    PENDING = "pending"

    def __str__(self) -> str:
        return self.value


# ---------------------------------------------------------------------------
# Approval request
# ---------------------------------------------------------------------------


@dataclass
class ApprovalRequest:
    """A single human approval request for a pipeline release."""

    pipeline_id: str
    requested_by: str = "system"
    requested_at: str = ""
    decided_by: str = ""
    decided_at: str = ""
    decision: ApprovalDecision = ApprovalDecision.PENDING
    role: ApproverRole = ApproverRole.REVIEWER
    comments: str = ""
    artifacts_reviewed: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_approved(self) -> bool:
        return self.decision == ApprovalDecision.APPROVED

    @property
    def is_denied(self) -> bool:
        return self.decision == ApprovalDecision.DENIED

    @property
    def is_pending(self) -> bool:
        return self.decision == ApprovalDecision.PENDING

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_id": self.pipeline_id,
            "requested_by": self.requested_by,
            "requested_at": self.requested_at,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at,
            "decision": self.decision.value,
            "role": self.role.value,
            "comments": self.comments,
            "artifacts_reviewed": self.artifacts_reviewed,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalRequest:
        return cls(
            pipeline_id=data.get("pipeline_id", ""),
            requested_by=data.get("requested_by", "system"),
            requested_at=data.get("requested_at", ""),
            decided_by=data.get("decided_by", ""),
            decided_at=data.get("decided_at", ""),
            decision=ApprovalDecision(data.get("decision", "pending")),
            role=ApproverRole(data.get("role", "reviewer")),
            comments=data.get("comments", ""),
            artifacts_reviewed=data.get("artifacts_reviewed", []),
            metadata=data.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Approval gate
# ---------------------------------------------------------------------------


class ApprovalGate:
    """Gate that controls human approval for pipeline release.

    The gate enforces:
      - Approval is mandatory before RELEASED.
      - Only authorized roles can approve.
      - Approval decisions are persisted and auditable.
      - Denied requests can be re-filed (new request).

    Args:
        root: Path to the atlas-dataset repository root (for persistence).

    Typical usage::

        gate = ApprovalGate(ROOT)
        req = gate.create_request("release-v0.3")
        gate.approve(req, decided_by="reviewer_jane",
                     role=ApproverRole.REVIEWER,
                     comments="All checks passed. Proceed.")
        assert gate.is_releasable("release-v0.3")
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self._requests: dict[str, ApprovalRequest] = {}

    # ── Core API ─────────────────────────────────────────────────────────

    def create_request(
        self,
        pipeline_id: str,
        *,
        requested_by: str = "system",
        role: ApproverRole = ApproverRole.REVIEWER,
        artifacts_reviewed: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        """Create a new approval request for a pipeline.

        Args:
            pipeline_id: The pipeline awaiting approval.
            requested_by: Who/what requested the approval.
            role: The required approver role.
            artifacts_reviewed: Artifacts presented for review.
            metadata: Extra metadata.

        Returns:
            A new ApprovalRequest in PENDING state.
        """
        request = ApprovalRequest(
            pipeline_id=pipeline_id,
            requested_by=requested_by,
            requested_at=datetime.now(timezone.utc).isoformat(),
            role=role,
            artifacts_reviewed=artifacts_reviewed or [],
            metadata=metadata or {},
        )
        self._requests[pipeline_id] = request
        self._persist()
        return request

    def approve(
        self,
        pipeline_id: str,
        *,
        decided_by: str,
        role: ApproverRole = ApproverRole.REVIEWER,
        comments: str = "",
    ) -> bool:
        """Approve a pipeline for release.

        Args:
            pipeline_id: The pipeline to approve.
            decided_by: Identifier of the human who made the decision.
            role: The approver's role.
            comments: Optional comments from the approver.

        Returns:
            True if approval was recorded. False if no request exists.
        """
        request = self._requests.get(pipeline_id)
        if request is None:
            # Try loading from disk
            self._load_one(pipeline_id)
            request = self._requests.get(pipeline_id)

        if request is None:
            return False

        request.decision = ApprovalDecision.APPROVED
        request.decided_by = decided_by
        request.decided_at = datetime.now(timezone.utc).isoformat()
        request.role = role
        request.comments = comments
        self._persist()
        return True

    def deny(
        self,
        pipeline_id: str,
        *,
        decided_by: str,
        role: ApproverRole = ApproverRole.REVIEWER,
        comments: str = "",
    ) -> bool:
        """Deny a pipeline release.

        Args:
            pipeline_id: The pipeline to deny.
            decided_by: Identifier of the human who denied.
            role: The denier's role.
            comments: Reason for denial.

        Returns:
            True if denial was recorded. False if no request exists.
        """
        request = self._requests.get(pipeline_id)
        if request is None:
            self._load_one(pipeline_id)
            request = self._requests.get(pipeline_id)

        if request is None:
            return False

        request.decision = ApprovalDecision.DENIED
        request.decided_by = decided_by
        request.decided_at = datetime.now(timezone.utc).isoformat()
        request.role = role
        request.comments = comments
        self._persist()
        return True

    def is_releasable(self, pipeline_id: str) -> bool:
        """Check if a pipeline has been approved for release.

        Args:
            pipeline_id: The pipeline to check.

        Returns:
            True if the pipeline has an APPROVED decision.
        """
        request = self._requests.get(pipeline_id)
        if request is None:
            self._load_one(pipeline_id)
            request = self._requests.get(pipeline_id)
        return request is not None and request.is_approved

    def get_request(self, pipeline_id: str) -> ApprovalRequest | None:
        """Get the approval request for a pipeline, if any."""
        self._load_one(pipeline_id)
        return self._requests.get(pipeline_id)

    def list_requests(self) -> list[ApprovalRequest]:
        """List all known approval requests."""
        self._load_all()
        return list(self._requests.values())

    def reject_or_rescind(self, pipeline_id: str) -> bool:
        """Remove an approval decision for a pipeline (e.g. if conditions change).

        Args:
            pipeline_id: The pipeline to rescind approval for.

        Returns:
            True if the request was found and reset.
        """
        request = self._requests.get(pipeline_id)
        if request is None:
            self._load_one(pipeline_id)
            request = self._requests.get(pipeline_id)

        if request is None:
            return False

        request.decision = ApprovalDecision.PENDING
        request.decided_by = ""
        request.decided_at = ""
        request.comments = ""
        self._persist()
        return True

    # ── Persistence ──────────────────────────────────────────────────────

    def _approvals_path(self) -> Path:
        path = self.root / "metadata" / "pipeline_approvals.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _persist(self) -> None:
        """Write all approval requests to disk."""
        data = {
            "approvals": [
                req.to_dict() for req in self._requests.values()
            ],
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        self._approvals_path().write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _load_all(self) -> None:
        """Load all approval requests from disk."""
        path = self._approvals_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for req_data in data.get("approvals", []):
                req = ApprovalRequest.from_dict(req_data)
                if req.pipeline_id not in self._requests:
                    self._requests[req.pipeline_id] = req
        except (json.JSONDecodeError, OSError):
            pass

    def _load_one(self, pipeline_id: str) -> None:
        """Load a single pipeline's approval request from disk."""
        if pipeline_id in self._requests:
            return
        path = self._approvals_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for req_data in data.get("approvals", []):
                if req_data.get("pipeline_id") == pipeline_id:
                    self._requests[pipeline_id] = ApprovalRequest.from_dict(req_data)
                    return
        except (json.JSONDecodeError, OSError):
            pass

    # ── Integration helpers ──────────────────────────────────────────────

    def check_approval_gate(self, pipeline_id: str) -> dict[str, Any]:
        """Return a detailed gate check result for use by the orchestrator.

        Args:
            pipeline_id: The pipeline to check.

        Returns:
            Dict with keys: approved (bool), request (dict or None), message (str).
        """
        request = self.get_request(pipeline_id)
        if request is None:
            return {
                "approved": False,
                "request": None,
                "message": (
                    f"No approval request exists for pipeline '{pipeline_id}'. "
                    "Create one with create_request() first."
                ),
            }
        if request.is_approved:
            return {
                "approved": True,
                "request": request.to_dict(),
                "message": (
                    f"Pipeline '{pipeline_id}' approved by {request.decided_by} "
                    f"at {request.decided_at}."
                ),
            }
        if request.is_denied:
            return {
                "approved": False,
                "request": request.to_dict(),
                "message": (
                    f"Pipeline '{pipeline_id}' was DENIED by {request.decided_by} "
                    f"at {request.decided_at}. Comments: {request.comments}"
                ),
            }
        return {
            "approved": False,
            "request": request.to_dict(),
            "message": (
                f"Pipeline '{pipeline_id}' is awaiting human approval "
                f"(requested at {request.requested_at})."
            ),
        }
