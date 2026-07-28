#!/usr/bin/env python3
"""Release Manager agent — controls final dataset release after all gates pass.

The ReleaseManager is the last gate in the pipeline. It:

  1. Verifies ALL required gates are PASS (quality, provenance, revision,
     validation, human approval).
  2. Generates release candidate metadata with checksums.
  3. Creates release artifacts in ``metadata/releases/``.
  4. Supports approval and rejection workflows.
  5. Preserves a full audit trail of release attempts.

Flow::

    QualityAgent → ProvenanceAgent → RevisionAgent → ValidationAgent
                                                          │
                                                          ▼
                                                  Human Approval Gate
                                                          │
                                                          ▼
                                                  ReleaseManager
                                                          │
                                          ┌───────────────┼───────────────┐
                                          ▼               ▼               ▼
                                     READY_FOR      RELEASE         RELEASE
                                     _RELEASE       _REJECTED       _REJECTED
                                          │               │
                                          ▼               ▼
                                     RELEASED      (terminal)

All release artifacts are written to ``metadata/releases/`` only.
No immutable dataset files are ever modified.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base_agent import BaseAgent, AgentResult, AgentStatus


# ---------------------------------------------------------------------------
# Release status constants
# ---------------------------------------------------------------------------

READY_FOR_RELEASE = "READY_FOR_RELEASE"
RELEASE_REJECTED = "RELEASE_REJECTED"
GATE_PASS = "PASS"
GATE_FAIL = "FAIL"
GATE_SKIPPED = "SKIPPED"
GATE_APPROVED = "APPROVED"
GATE_DENIED = "DENIED"
GATE_PENDING = "PENDING"


# ---------------------------------------------------------------------------
# Release metadata
# ---------------------------------------------------------------------------


def compute_checksum(data: dict[str, Any]) -> str:
    """Compute a deterministic SHA-256 checksum of a JSON-serialisable dict."""
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Gate result mapping helpers
# ---------------------------------------------------------------------------

_GATE_MAP: dict[str, tuple[str, str]] = {
    "quality": ("quality", "quality agent"),
    "provenance": ("provenance", "provenance agent"),
    "revision": ("revision", "revision agent"),
    "validation": ("validation", "validation agent"),
}


def _agent_status_to_gate(status: str | None) -> str:
    """Map an AgentStatus string to a gate status string."""
    if status is None:
        return GATE_SKIPPED
    s = status.lower()
    if s in ("passed",):
        return GATE_PASS
    if s in ("failed",):
        return GATE_FAIL
    if s in ("skipped",):
        return GATE_SKIPPED
    return GATE_FAIL


def _approval_to_gate(decision: str | None) -> str:
    """Map an approval decision string to a gate status string."""
    if decision is None:
        return GATE_PENDING
    d = decision.lower()
    if d == "approved":
        return GATE_APPROVED
    if d == "denied":
        return GATE_DENIED
    return GATE_PENDING


# ---------------------------------------------------------------------------
# Release manager
# ---------------------------------------------------------------------------


class ReleaseManager(BaseAgent):
    """Production release manager (v1.4).

    Verifies all pipeline gates, generates release candidate metadata,
    and produces release artifacts in ``metadata/releases/``.

    The agent runs at the end of the pipeline, after human approval, and
    determines whether the release proceeds or is rejected.

    Context requirements (passed via ``execute(context=...)``):
        - ``pipeline_id``: Unique pipeline identifier.
        - ``agent_results``: Dict of ``{agent_name: AgentResult}`` from
          prior pipeline stages.
        - ``approval_status``: Dict with keys ``approved`` (bool),
          ``request`` (dict or None), ``message`` (str).

    Config keys:
        release_version:  Version string for the release (e.g. ``\"v0.3\"``).
                          Auto-generated from pipeline_id if omitted.
        output_dir:       Override release artifacts directory (default:
                          ``metadata/releases``).
        require_all_gates: If ``True`` (default), all gates must PASS for
                          release.  Skipped gates are treated as PASS.

    Args:
        root:   Path to the atlas-dataset repository root.
        config: Optional configuration dict (see above).
    """

    name: str = "release_manager"
    description: str = (
        "Final release gate — verifies all pipeline gates and generates "
        "release artifacts"
    )

    def __init__(
        self,
        root: str | Path,
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(root, config)
        cfg = config or {}
        self.require_all_gates = cfg.get("require_all_gates", True)

        scripts = str(self.root / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)

    @property
    def output_dir(self) -> Path:
        override = self.config.get("output_dir")
        if override:
            return Path(override).resolve()
        return self.root / "metadata" / "releases"

    # ── Agent execution ────────────────────────────────────────────────

    def execute(self, context: dict[str, Any] | None = None) -> AgentResult:
        """Run the release gate.

        Verifies all pipeline gates, generates release artefacts, and
        returns the release decision.

        Args:
            context: Required - must include ``pipeline_id``,
                     ``agent_results``, and ``approval_status``.

        Returns:
            ``AgentResult`` with release decision, gate statuses,
            manifest path, and checksum.
        """
        ctx = context or {}
        pipeline_id = ctx.get("pipeline_id", "default")
        agent_results: dict[str, Any] = ctx.get("agent_results", {})
        approval_status: dict[str, Any] = ctx.get("approval_status", {})

        release_version = self.config.get("release_version") or self._derive_version(pipeline_id)
        created_at = datetime.now(timezone.utc).isoformat()

        # ── 1. Evaluate all gates ──────────────────────────────────────
        gates: dict[str, str] = {}

        # Agent gates
        for gate_name, (result_key, _) in _GATE_MAP.items():
            ar = agent_results.get(result_key) if isinstance(agent_results, dict) else None
            status = ar.get("status") if isinstance(ar, dict) else None
            gates[gate_name] = _agent_status_to_gate(status)

        # Human approval gate
        if isinstance(approval_status, dict):
            gates["human_approval"] = _approval_to_gate(
                approval_status.get("decision")
                if isinstance(approval_status, dict)
                else None
            )
        else:
            gates["human_approval"] = GATE_PENDING

        # ── 2. Determine gate outcomes ─────────────────────────────────
        failed_gates: list[str] = []
        skipped_gates: list[str] = []

        for gate_name, status in gates.items():
            if status in (GATE_FAIL, GATE_DENIED, GATE_PENDING):
                failed_gates.append(gate_name)
            elif status == GATE_SKIPPED:
                skipped_gates.append(gate_name)

        all_pass = len(failed_gates) == 0
        human_approved = gates.get("human_approval") == GATE_APPROVED
        human_denied = gates.get("human_approval") == GATE_DENIED

        # ── 3. Determine release decision ──────────────────────────────
        if human_denied:
            release_status = RELEASE_REJECTED
            reason = (
                f"Release rejected by human — "
                f"approval decision was DENIED"
            )
            next_action = "RETURN_TO_REVISION_QUEUE"
        elif not human_approved:
            release_status = RELEASE_REJECTED
            reason = (
                f"Release blocked — human approval is "
                f"{gates.get('human_approval', 'missing')}"
            )
            next_action = "WAIT_FOR_HUMAN_APPROVAL"
        elif not all_pass and self.require_all_gates:
            release_status = RELEASE_REJECTED
            reason = (
                f"Release blocked — {len(failed_gates)} gate(s) failed: "
                f"{', '.join(failed_gates)}"
            )
            next_action = "RETURN_TO_REVISION_QUEUE"
        else:
            release_status = READY_FOR_RELEASE
            reason = "All gates pass — ready for release"
            next_action = "PROCEED_TO_RELEASE"

        # ── 4. Build release metadata ──────────────────────────────────
        release_metadata: dict[str, Any] = {
            "release_id": pipeline_id,
            "release_version": release_version,
            "status": release_status,
            "reason": reason,
            "next_action": next_action,
            "gates": dict(sorted(gates.items())),
            "failed_gates": failed_gates,
            "skipped_gates": skipped_gates,
            "created_at": created_at,
        }

        # Compute checksum on stable fields only (exclude timestamp)
        stable_fields = {k: release_metadata[k] for k in release_metadata if k != "created_at"}
        checksum = compute_checksum(stable_fields)
        release_metadata["checksum"] = checksum

        # ── 5. Generate release artifacts ──────────────────────────────
        manifest_path = self._write_manifest(pipeline_id, release_metadata)
        report_path = self._write_report(
            pipeline_id, release_metadata, agent_results, approval_status
        )

        # ── 6. Build result data ───────────────────────────────────────
        data: dict[str, Any] = {
            "release_id": pipeline_id,
            "release_version": release_version,
            "status": release_status,
            "gates": dict(sorted(gates.items())),
            "failed_gates": failed_gates,
            "reason": reason,
            "next_action": next_action,
            "checksum": checksum,
            "manifest_path": str(manifest_path),
            "report_path": str(report_path),
            "created_at": created_at,
        }

        # ── 7. Determine status ────────────────────────────────────────
        if release_status == READY_FOR_RELEASE:
            status = AgentStatus.PASSED
            summary = (
                f"Release gate PASSED — {len([g for g in gates.values() if g == GATE_PASS])}/"
                f"{len(gates)} gates pass. "
                f"Release {release_version} ready."
            )
        elif release_status == RELEASE_REJECTED and human_denied:
            status = AgentStatus.FAILED
            summary = (
                f"Release REJECTED by human. "
                f"Next action: {next_action}. "
                f"Reason: {reason}"
            )
        else:
            status = AgentStatus.FAILED
            summary = (
                f"Release BLOCKED — {len(failed_gates)} gate(s) failed: "
                f"{', '.join(failed_gates)}. "
                f"Next action: {next_action}"
            )

        errors_list = []
        if failed_gates:
            errors_list.append(f"Failed gates: {', '.join(failed_gates)}")
        if human_denied:
            errors_list.append("Human denied the release")

        return AgentResult(
            agent_name=self.name,
            status=status,
            summary=summary,
            data=data,
            errors=errors_list,
        )

    # ── Artifact generation ───────────────────────────────────────────

    def _write_manifest(
        self,
        pipeline_id: str,
        release_metadata: dict[str, Any],
    ) -> Path:
        """Write the release manifest to metadata/releases/.

        The manifest is the canonical release record containing gate
        statuses, checksum, and provenance.

        Returns:
            Path to the written manifest file.
        """
        out_dir = self.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        manifest_path = out_dir / f"{pipeline_id}_manifest.json"

        # Build a clean manifest with full audit trail
        manifest = {
            "release_id": pipeline_id,
            "release_version": release_metadata["release_version"],
            "status": release_metadata["status"],
            "reason": release_metadata["reason"],
            "next_action": release_metadata["next_action"],
            "gates": release_metadata["gates"],
            "failed_gates": release_metadata["failed_gates"],
            "created_at": release_metadata["created_at"],
            "checksum": release_metadata["checksum"],
            "manifest_checksum": compute_checksum({
                "release_id": pipeline_id,
                "status": release_metadata["status"],
                "gates": release_metadata["gates"],
                "created_at": release_metadata["created_at"],
            }),
            "generated_by": "release_manager.py",
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return manifest_path

    def _write_report(
        self,
        pipeline_id: str,
        release_metadata: dict[str, Any],
        agent_results: dict[str, Any],
        approval_status: dict[str, Any],
    ) -> Path:
        """Write a detailed release report to metadata/releases/.

        The report includes full agent summaries, approval details, and
        the release decision.

        Returns:
            Path to the written report file.
        """
        out_dir = self.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        report_path = out_dir / f"{pipeline_id}_report.json"

        # Build agent summaries
        agent_summaries: dict[str, Any] = {}
        if isinstance(agent_results, dict):
            for name, ar in agent_results.items():
                if isinstance(ar, dict):
                    agent_summaries[name] = {
                        "status": ar.get("status"),
                        "summary": ar.get("summary", ""),
                        "errors": ar.get("errors", []),
                    }
                else:
                    agent_summaries[str(name)] = {
                        "status": str(getattr(ar, "status", "unknown")),
                        "summary": str(getattr(ar, "summary", "")),
                    }

        report = {
            "release_id": pipeline_id,
            "report_type": "release_report",
            "release_status": release_metadata["status"],
            "reason": release_metadata["reason"],
            "next_action": release_metadata["next_action"],
            "gates": release_metadata["gates"],
            "failed_gates": release_metadata["failed_gates"],
            "created_at": release_metadata["created_at"],
            "checksum": release_metadata["checksum"],
            "agent_summaries": agent_summaries,
            "approval_details": approval_status if isinstance(approval_status, dict) else {},
            "generated_by": "release_manager.py",
        }
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return report_path

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _derive_version(pipeline_id: str) -> str:
        """Derive a release version from the pipeline_id."""
        # Strip common prefixes to find the version
        for prefix in ("release-", "pipeline-", "atlas-"):
            if pipeline_id.startswith(prefix):
                return pipeline_id[len(prefix):]
        return pipeline_id
