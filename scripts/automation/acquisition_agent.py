#!/usr/bin/env python3
"""AcquisitionAgent v1 — deterministic packet acquirer for Atlas.

Modes:
- dry-run: show planned acquisitions and skipped packets with reasons.
- acquire:  create metadata/acquisition_logs/ and record acquisition checksums.

Safety guarantees:
- Only APPROVE decisions are processed; DEFER/REJECT are skipped.
- Unknown/absent human decision blocks acquisition (fail closed).
- Rejected-source registry entries are never acquired.
- Dataset roots curated/, review_queue/, training_views/, raw/ are never mutated.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from automation.base_agent import BaseAgent, AgentResult, AgentStatus

# Module-level default: used by the standalone main() / build() wrappers.
# The AcquisitionAgent class itself resolves all paths against self.root.
_MODULE_ROOT = Path(__file__).resolve().parents[2]

# Source registry statuses that are acceptable for acquisition.
REGISTRY_ACCEPTABLE = {"accepted", "review"}


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Path helpers (relative to an atlas root)
# ---------------------------------------------------------------------------


def _decisions_path(root: Path) -> Path:
    return root / "metadata" / "acquisition_human_decisions.json"


def _manifest_path(root: Path) -> Path:
    return root / "metadata" / "acquisition_manifest_v0.1.json"


def _registry_path(root: Path) -> Path:
    return root / "metadata" / "source_registry.json"


def _log_dir(root: Path) -> Path:
    return root / "metadata" / "acquisition_logs"


# ---------------------------------------------------------------------------
# AcquisitionAgent
# ---------------------------------------------------------------------------


class AcquisitionAgent(BaseAgent):
    name = "acquisition_agent"
    description = "Deterministic packet acquirer — dry-run / acquire modes with human-decision gating"

    def __init__(self, root: str | Path, config: dict[str, Any] | None = None) -> None:
        super().__init__(root, config)
        self.mode = (self.config.get("mode") or "dry-run").strip().lower()
        if self.mode not in {"dry-run", "acquire"}:
            raise ValueError("mode must be 'dry-run' or 'acquire'")

        # Resolve input file paths (config override → self.root-relative default)
        self._decisions_path = self._resolve_path("decisions_path", _decisions_path(self.root))
        self._manifest_path = self._resolve_path("manifest_path", _manifest_path(self.root))
        self._registry_path = self._resolve_path("registry_path", _registry_path(self.root))
        self._log_dir = _log_dir(self.root)

    # ── public API ──────────────────────────────────────────────────────

    def execute(self, context: dict[str, Any] | None = None) -> AgentResult:
        # Precondition: all input files exist
        pre_errors = self._check_preconditions()
        if pre_errors:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILED,
                summary="Precondition check failed",
                errors=pre_errors,
            )

        decisions = self._load_decisions()
        manifest_packets = self._load_manifest()
        registry = self._load_registry()

        planned: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        acquired: list[dict[str, Any]] = []
        unknown_blocked: list[dict[str, Any]] = []

        # Build packet map, keying on packet_id (falls back to source_id)
        packet_map: dict[str, dict[str, Any]] = {}
        for p in manifest_packets:
            pid = p.get("packet_id") or self._source_id_from_packet(p)
            p = dict(p)
            p.setdefault("packet_id", pid)
            packet_map[pid] = p

        decision_map = {str(k): v for k, v in (decisions.get("packets") or {}).items()}

        for packet_id, packet in packet_map.items():
            source_id = self._source_id_from_packet(packet)
            decision_entry = decision_map.get(str(packet_id))

            # Missing human decision → blocked
            if decision_entry is None:
                unknown_blocked.append({
                    "packet_id": packet_id,
                    "source_id": source_id,
                    "reason": "missing human decision",
                })
                continue

            decision = (decision_entry.get("decision") or "").strip().upper()

            # Non-APPROVE decision → skip
            if decision != "APPROVE":
                skipped.append({
                    "packet_id": packet_id,
                    "source_id": source_id,
                    "decision": decision,
                    "reason": self._skip_reason(packet, decision, registry.get(source_id)),
                })
                continue

            # Registry gate
            registry_rec = registry.get(source_id, {})
            reg_status = (registry_rec.get("status") or "candidate").strip().lower()
            if reg_status not in REGISTRY_ACCEPTABLE:
                skipped.append({
                    "packet_id": packet_id,
                    "source_id": source_id,
                    "decision": decision,
                    "reason": f"registry status '{reg_status}' not acquirable",
                })
                continue

            planned.append({
                "packet_id": packet_id,
                "source_id": source_id,
                "source_name": packet.get("name") or registry_rec.get("name"),
                "batch_id": packet.get("batch_id"),
                "decision": decision,
                "registry_status": reg_status,
            })

            if self.mode == "acquire":
                acquired.append(self._record_acquisition(packet_id, source_id, packet, registry_rec))

        # Determine final status
        if unknown_blocked:
            status = AgentStatus.BLOCKED
            summary = f"Blocked: {len(unknown_blocked)} packet(s) missing human decision"
        elif self.mode == "acquire" and acquired:
            status = AgentStatus.PASSED
            summary = f"Acquired {len(acquired)} packet(s); skipped {len(skipped)}"
        elif self.mode == "dry-run":
            status = AgentStatus.PASSED
            summary = f"Dry-run complete: {len(planned)} planned, {len(skipped)} skipped"
        else:
            status = AgentStatus.SKIPPED
            summary = f"Nothing to acquire; {len(skipped)} skipped"

        data: dict[str, Any] = {
            "mode": self.mode,
            "planned": planned,
            "skipped": skipped,
            "unknown_blocked": unknown_blocked,
            "stats": {
                "planned": len(planned),
                "skipped": len(skipped),
                "acquired": len(acquired),
                "unknown_blocked": len(unknown_blocked),
            },
        }
        if self.mode == "acquire":
            data["acquired"] = acquired

        return AgentResult(agent_name=self.name, status=status, summary=summary, data=data)

    # ── Pre-condition & I/O helpers ──────────────────────────────────────

    def _check_preconditions(self) -> list[str]:
        errors: list[str] = []
        for path, label in [
            (self._decisions_path, "human decisions file"),
            (self._manifest_path, "acquisition manifest"),
            (self._registry_path, "source registry"),
        ]:
            if not path.exists():
                errors.append(f"missing {label}: {path}")
        return errors

    def _load_decisions(self) -> dict[str, Any]:
        return json.loads(self._decisions_path.read_text(encoding="utf-8"))

    def _load_manifest(self) -> list[dict[str, Any]]:
        manifest = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        packets: list[dict[str, Any]] = []
        for batch in manifest.get("batches", []):
            for dataset in batch.get("datasets", []):
                entry = dict(dataset)
                entry["batch_id"] = batch.get("batch_id")
                entry["batch_theme"] = batch.get("theme")
                packets.append(entry)
        return packets

    def _load_registry(self) -> dict[str, Any]:
        registry = json.loads(self._registry_path.read_text(encoding="utf-8"))
        return {str(s.get("id") or ""): s for s in registry.get("sources", []) if s.get("id")}

    # ── Acquisition logic helpers ───────────────────────────────────────

    def _source_id_from_packet(self, packet: dict[str, Any]) -> str:
        source_id = packet.get("source_id")
        if source_id:
            return str(source_id)
        name = packet.get("name") or ""
        return name.split("/")[-1] if name else packet.get("packet_id", "")

    def _skip_reason(self, packet: dict[str, Any], decision: str,
                     registry_rec: dict[str, Any] | None) -> str:
        if decision == "DEFER":
            return "human decision: DEFER"
        if decision == "REJECT":
            return "human decision: REJECT"
        if decision == "PENDING":
            return "missing human decision"
        reg_status = (registry_rec or {}).get("status", "candidate").strip().lower()
        if reg_status not in REGISTRY_ACCEPTABLE:
            return f"registry status '{reg_status}' rejected"
        return "not approved"

    def _record_acquisition(self, packet_id: str, source_id: str,
                            packet: dict[str, Any],
                            registry_rec: dict[str, Any]) -> dict[str, Any]:
        manifest_name = packet.get("name") or registry_rec.get("name") or source_id
        manifest_license = packet.get("license") or registry_rec.get("license") or "unknown"
        registry_status = (registry_rec.get("status") or "unknown").strip().lower()

        checksum_input = json.dumps({
            "packet_id": packet_id,
            "source_id": source_id,
            "name": manifest_name,
            "license": manifest_license,
            "registry_status": registry_status,
            "batch_id": packet.get("batch_id"),
        }, sort_keys=True, separators=(",", ":"))
        checksum = _sha256_hex(checksum_input)

        if self.mode == "acquire":
            self._log_dir.mkdir(parents=True, exist_ok=True)
            target = self._log_dir / f"{packet_id}.acquisition.json"
            if target.exists():
                existing_checksum = json.loads(target.read_text(encoding="utf-8")).get("checksum")
                if existing_checksum != checksum:
                    raise RuntimeError(
                        f"existing acquisition log checksum mismatch for {packet_id}"
                    )
            else:
                doc = {
                    "packet_id": packet_id,
                    "source_id": source_id,
                    "source": manifest_name,
                    "timestamp": _ts(),
                    "checksum": checksum,
                    "status": "acquired",
                    "registry_status": registry_status,
                    "manifest_license": manifest_license,
                    "batch_id": packet.get("batch_id"),
                }
                target.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

        return {
            "packet_id": packet_id,
            "source_id": source_id,
            "source": manifest_name,
            "timestamp": _ts(),
            "checksum": checksum,
            "acquisition_status": "acquired",
            "registry_status": registry_status,
            "manifest_license": manifest_license,
            "batch_id": packet.get("batch_id"),
        }

    # ── Internal helpers ─────────────────────────────────────────────────

    def _resolve_path(self, config_key: str, default: Path) -> Path:
        value = self.config.get(config_key) if config_key in self.config else None
        if value is None:
            return default
        path = Path(value)
        return path if path.is_absolute() else self.root / path


# ---------------------------------------------------------------------------
# Functional wrapper (for scripting / integration tests)
# ---------------------------------------------------------------------------


def build(
    decisions_path: str | Path | None = None,
    manifest_path: str | Path | None = None,
    registry_path: str | Path | None = None,
    mode: str = "dry-run",
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Run the AcquisitionAgent and return the result dict."""
    root_path = Path(root) if root else _MODULE_ROOT
    config: dict[str, Any] = {"mode": mode}
    if decisions_path is not None:
        config["decisions_path"] = str(decisions_path)
    if manifest_path is not None:
        config["manifest_path"] = str(manifest_path)
    if registry_path is not None:
        config["registry_path"] = str(registry_path)
    agent = AcquisitionAgent(root_path, config=config)
    result = agent.execute()
    return result.to_dict()


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="AcquisitionAgent v1")
    ap.add_argument("--mode", choices=["dry-run", "acquire"], default="dry-run")
    ap.add_argument("--decisions", default=None)
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--registry", default=None)
    args = ap.parse_args(argv)

    result = build(
        decisions_path=args.decisions,
        manifest_path=args.manifest,
        registry_path=args.registry,
        mode=args.mode,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result.get("status") == "failed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
