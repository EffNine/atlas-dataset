#!/usr/bin/env python3
"""Tests for AcquisitionAgent v1."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys_path_guard = str(ROOT / "scripts")
if sys_path_guard not in __import__("sys").path:
    __import__("sys").path.insert(0, sys_path_guard)
from automation.acquisition_agent import AcquisitionAgent  # noqa: E402
from automation.base_agent import AgentStatus  # noqa: E402


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_packet(packet_id: str = "p1", source_id: str = "s1", batch_id: str = "B01"):
    return {
        "packet_id": packet_id,
        "source_id": source_id,
        "name": f"source/{source_id}",
        "batch_id": batch_id,
        "theme": "t",
        "license": "MIT",
    }


def _make_root(tmp_path: Path, *, packets, decisions, registry, allowed_ids=None):
    root = tmp_path
    (root / "metadata").mkdir(exist_ok=True)
    (root / "metadata/acquisition_manifest_v0.1.json").write_text(
        json.dumps({
            "manifest_version": "0.1.0",
            "batches": [
                {
                    "batch_id": p.get("batch_id", "B01"),
                    "theme": p.get("theme", "t"),
                    "datasets": [
                        {
                            "source_id": p.get("source_id", p.get("packet_id")),
                            "name": p.get("name", f"source/{p.get('source_id',p.get('packet_id'))}"),
                            "license": p.get("license", "MIT"),
                        }
                    ],
                }
                for p in packets
            ],
        }, indent=2),
        encoding="utf-8",
    )
    (root / "metadata/source_registry.json").write_text(
        json.dumps({"sources": registry}, indent=2),
        encoding="utf-8",
    )
    (root / "metadata/acquisition_human_decisions.json").write_text(
        json.dumps(decisions, indent=2),
        encoding="utf-8",
    )
    return root


def test_approved_packet_proceeds():
    packets = [_make_packet("s1", "s1", "B01")]
    decisions = {
        "packets": {
            "s1": {"packet_id": "s1", "decision": "APPROVE", "timestamp": "2026-07-29T00:00:00Z"},
        },
        "summary": {"total_packets": 1, "packet_decisions": {"APPROVE": 1}},
    }
    registry = [
        {"id": "s1", "name": "source/s1", "status": "accepted", "license": "MIT"},
    ]
    with tempfile.TemporaryDirectory() as td:
        root = _make_root(Path(td), packets=packets, decisions=decisions, registry=registry)
        agent = AcquisitionAgent(root, config={"mode": "dry-run"})
        result = agent.execute()
    assert result.status == AgentStatus.PASSED
    assert len(result.data["planned"]) == 1
    assert result.data["planned"][0]["packet_id"] == "s1"
    assert result.data["stats"]["planned"] == 1


def test_deferred_packet_skipped():
    packets = [_make_packet("s1", "s1", "B01")]
    decisions = {
        "packets": {
            "s1": {"packet_id": "s1", "decision": "DEFER", "timestamp": "2026-07-29T00:00:00Z"},
        }
    }
    registry = [{"id": "s1", "status": "accepted"}]
    with tempfile.TemporaryDirectory() as td:
        root = _make_root(Path(td), packets=packets, decisions=decisions, registry=registry)
        agent = AcquisitionAgent(root, config={"mode": "dry-run"})
        result = agent.execute()
    assert len(result.data["skipped"]) == 1
    assert result.data["skipped"][0]["decision"] == "DEFER"


def test_rejected_packet_skipped():
    packets = [_make_packet("s1", "s1", "B01")]
    decisions = {
        "packets": {
            "s1": {"packet_id": "s1", "decision": "REJECT", "timestamp": "2026-07-29T00:00:00Z"},
        }
    }
    registry = [{"id": "s1", "status": "accepted"}]
    with tempfile.TemporaryDirectory() as td:
        root = _make_root(Path(td), packets=packets, decisions=decisions, registry=registry)
        agent = AcquisitionAgent(root, config={"mode": "dry-run"})
        result = agent.execute()
    assert len(result.data["skipped"]) == 1
    assert result.data["skipped"][0]["decision"] == "REJECT"


def test_missing_decision_blocks():
    packets = [_make_packet("s1", "s1", "B01")]
    decisions = {"packets": {}}
    registry = [{"id": "s1", "status": "accepted"}]
    with tempfile.TemporaryDirectory() as td:
        root = _make_root(Path(td), packets=packets, decisions=decisions, registry=registry)
        agent = AcquisitionAgent(root, config={"mode": "dry-run"})
        result = agent.execute()
    assert result.status == AgentStatus.BLOCKED
    assert result.data["stats"]["unknown_blocked"] == 1


def test_dry_run_has_zero_dataset_writes():
    packets = [_make_packet("s1", "s1", "B01")]
    decisions = {
        "packets": {
            "s1": {"packet_id": "s1", "decision": "APPROVE", "timestamp": "2026-07-29T00:00:00Z"},
        }
    }
    registry = [{"id": "s1", "status": "accepted"}]
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        curated = root / "curated/v0.1/ok.jsonl"
        curated.parent.mkdir(parents=True, exist_ok=True)
        curated.write_text("a\n", encoding="utf-8")
        _make_root(root, packets=packets, decisions=decisions, registry=registry)
        mtime_before = curated.stat().st_mtime
        agent = AcquisitionAgent(root, config={"mode": "dry-run"})
        result = agent.execute()
        mtime_after = curated.stat().st_mtime
    assert result.status == AgentStatus.PASSED
    assert mtime_before == mtime_after
    assert not (root / "metadata/acquisition_logs").exists()


def test_checksum_persistence_and_mismatch():
    packets = [_make_packet("s1", "s1", "B01")]
    decisions = {
        "packets": {
            "s1": {"packet_id": "s1", "decision": "APPROVE", "timestamp": "2026-07-29T00:00:00Z"},
        }
    }
    registry = [{"id": "s1", "status": "accepted"}]
    with tempfile.TemporaryDirectory() as td:
        root = _make_root(Path(td), packets=packets, decisions=decisions, registry=registry)
        agent = AcquisitionAgent(root, config={"mode": "acquire"})
        first = agent.execute()
        assert first.status == AgentStatus.PASSED
        logged = first.data["acquired"][0]
        log_path = root / "metadata/acquisition_logs" / "s1.acquisition.json"
        assert log_path.exists()
        original = log_path.read_text(encoding="utf-8")
        log_path.write_text(original.replace(logged["checksum"], "bad"), encoding="utf-8")
        agent2 = AcquisitionAgent(root, config={"mode": "acquire"})
        with pytest.raises(RuntimeError, match="checksum mismatch"):
            agent2.execute()
