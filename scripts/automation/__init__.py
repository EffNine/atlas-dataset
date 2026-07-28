#!/usr/bin/env python3
"""Atlas Automation Layer v1 — Automated pipeline with human approval before release.

Transforms Atlas from a manual workflow into an automated pipeline while
preserving human governance at the release gate.

Architecture::

    ┌──────────────────────────────────────────────────────────┐
    │                  Pipeline Orchestrator                    │
    │  ┌─────────┐  ┌──────────┐  ┌────────┐  ┌───────────┐   │
    │  │ Quality │→│Provenance│→│Revision│→│ Validation │   │
    │  │ Agent   │  │ Agent    │  │ Agent  │  │ Agent      │   │
    │  └────┬────┘  └────┬─────┘  └───┬────┘  └─────┬─────┘   │
    │       │            │            │             │          │
    │       ▼            ▼            ▼             ▼          │
    │  ┌──────────────────────────────────────────────────┐    │
    │  │               State Machine (FSM)                 │    │
    │  │  INGESTED → QUALITY_CHECK → PROVENANCE_CHECK →   │    │
    │  │  CONTENT_REVISION → VALIDATION →                  │    │
    │  │  WAITING_HUMAN_APPROVAL → RELEASED                │    │
    │  └──────────────────────────────────────────────────┘    │
    │                        │                                  │
    │                        ▼                                  │
    │  ┌──────────────────────────────────────────────────┐    │
    │  │              Approval Gate                        │    │
    │  │  (blocks RELEASED without human sign-off)        │    │
    │  └──────────────────────────────────────────────────┘    │
    └──────────────────────────────────────────────────────────┘

Key design constraints:
  - Immutable dataset files (curated/) are never modified.
  - Existing tools are preserved; adapted through wrappers.
  - State is persisted in metadata/ for durability across restarts.
"""

from __future__ import annotations

from .state_machine import (
    PipelineState,
    StateTransition,
    StateMachine,
    VALID_TRANSITIONS,
    STATE_ORDER,
)
from .base_agent import BaseAgent, AgentResult, AgentStatus
from .approval_gate import (
    ApprovalGate,
    ApprovalRequest,
    ApprovalDecision,
    ApproverRole,
)
from .pipeline_orchestrator import (
    PipelineOrchestrator,
    PipelineResult,
    PipelineStatus,
)
from .provenance_agent import ProvenanceAgent
from .quality_agent import QualityAgent
from .revision_agent import RevisionAgent
from .validation_agent import ValidationAgent
from .release_manager import ReleaseManager

__all__ = [
    "PipelineState",
    "StateTransition",
    "StateMachine",
    "VALID_TRANSITIONS",
    "STATE_ORDER",
    "BaseAgent",
    "AgentResult",
    "AgentStatus",
    "ApprovalGate",
    "ApprovalRequest",
    "ApprovalDecision",
    "ApproverRole",
    "PipelineOrchestrator",
    "PipelineResult",
    "PipelineStatus",
    "ProvenanceAgent",
    "QualityAgent",
    "RevisionAgent",
    "ValidationAgent",
    "ReleaseManager",
]
