#!/usr/bin/env python3
"""Base agent interface for the Atlas Automation Layer.

All pipeline agents inherit from ``BaseAgent`` and implement:
  - ``execute()`` — run the agent's core logic
  - ``name`` — human-readable agent identifier
  - ``description`` — what this agent does

Agents produce an ``AgentResult`` carrying status, data, and optional errors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Agent status
# ---------------------------------------------------------------------------


class AgentStatus(str, Enum):
    """Execution status of an agent run."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"

    def __str__(self) -> str:
        return self.value


# ---------------------------------------------------------------------------
# Agent result
# ---------------------------------------------------------------------------


@dataclass
class AgentResult:
    """Result produced by a single agent execution."""

    agent_name: str
    status: AgentStatus
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == AgentStatus.PASSED

    @property
    def failed(self) -> bool:
        return self.status == AgentStatus.FAILED

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "status": self.status.value,
            "summary": self.summary,
            "data": self.data,
            "errors": self.errors,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# Base agent
# ---------------------------------------------------------------------------


class BaseAgent(ABC):
    """Abstract base class for all Atlas pipeline agents.

    Subclasses must define:
      - ``name`` (class-level identifier)
      - ``description`` (what the agent does)
      - ``execute()`` (the agent's core logic returning an AgentResult)

    Args:
        root: Path to the atlas-dataset repository root.
        config: Optional agent-specific configuration dict.
    """

    name: str = "base_agent"
    description: str = "Base agent — override in subclass."

    def __init__(
        self,
        root: str | Path,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.config = config or {}

    @abstractmethod
    def execute(self, context: dict[str, Any] | None = None) -> AgentResult:
        """Execute the agent's core logic.

        Args:
            context: Optional pipeline context (current state, prior results, etc.).

        Returns:
            An AgentResult with status and data.
        """
        ...

    def validate_config(self) -> list[str]:
        """Validate agent configuration.

        Returns:
            A list of configuration error messages (empty = valid).
        """
        return []

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, root={self.root})"
