#!/usr/bin/env python3
"""Tests for the interactive review UI (offline, scripted IO)."""

from __future__ import annotations

import json

from expert_pipeline import review_ui as rui


def _blind_block(i: int) -> dict:
    return {
        "review_id": f"rev_{i:06d}",
        "record_id": f"expert_arch_{i:06d}",
        "payload": {
            "id": f"expert_arch_{i:06d}",
            "problem": f"motivation {i}",
            "solution": f"## Proposal\n\ndesign {i}",
            "context": "SIG: sig-x",
            "difficulty": 3,
            "extraction": {
                "title": f"KEP-{i}: Test KEP",
                "sig": "sig-x",
                "kep_number": str(i),
                "source_path": f"keps/sig-x/{i:04d}-t/README.md",
            },
        },
    }


def _sample_index(gate="KEEP"):
    return {f"rev_{i:06d}": {"review_id": f"rev_{i:06d}", "calibration": {"auto_gate": gate}}
            for i in range(10)}


class ScriptedInput:
    def __init__(self, seq):
        self._it = iter(seq)

    def __call__(self, prompt: str = "") -> str:
        return next(self._it)


def test_parse_dims_variants():
    assert rui.parse_dims("", [4, 3, 4, 4]) == [4, 3, 4, 4]
    assert rui.parse_dims("4,3,4,5", [4, 3, 4, 4]) == [4, 3, 4, 5]
    assert rui.parse_dims("4 3 4 5", [4, 3, 4, 4]) == [4, 3, 4, 5]
    assert rui.parse_dims("4,3,4", [4, 3, 4, 4]) is None      # wrong count
    assert rui.parse_dims("6,3,4,5", [4, 3, 4, 4]) is None    # out of range
    assert rui.parse_dims("0,3,4,5", [4, 3, 4, 4]) is None
    assert rui.parse_dims("a,b,c,d", [4, 3, 4, 4]) is None


def test_build_decision_shape_and_snapshot_join():
    block = _blind_block(0)
    entry = {"review_id": "rev_000000", "calibration": {"auto_gate": "KEEP"}}
    d = rui.build_decision(block, entry, "KEEP", [4, 3, 4, 4], "  solid doc ",
                           "human:test", now="2026-08-22T00:00:00+00:00")
    assert d == {
        "review_id": "rev_000000",
        "record_id": "expert_arch_000000",
        "reviewer": "human:test",
        "verdict": "KEEP",
        "dimensions": {
            "correctness": 4,
            "reasoning_depth": 3,
            "explanation_quality": 4,
            "provenance_confidence": 4,
        },
        "notes": "solid doc",
        "reviewed_at": "2026-08-22T00:00:00+00:00",
        "auto_gate_snapshot": "KEEP",
    }


def test_build_decision_without_sample_entry():
    d = rui.build_decision(_blind_block(0), None, "REVISE", [3, 2, 3, 3],
                           "", "human:test")
    assert d["auto_gate_snapshot"] is None
    assert d["verdict"] == "REVISE"
    assert d["notes"] == ""


def test_run_session_keep_flow(tmp_path):
    decisions = tmp_path / "decisions.jsonl"
    blocks = [_blind_block(0), _blind_block(1)]
    counts = rui.run_session(
        blocks, _sample_index(), decisions, "human:test",
        input_fn=ScriptedInput(["k", "", "faithful motivation->design map", "q"]),
        print_fn=lambda *a, **k: None,
        now_fn=lambda: "2026-08-22T00:00:00+00:00",
    )
    assert counts["KEEP"] == 1
    assert counts["skipped"] == 0  # quit with nothing left pending
    lines = [json.loads(l) for l in decisions.read_text().splitlines()]
    assert len(lines) == 1
    assert lines[0]["review_id"] == "rev_000000"
    assert lines[0]["verdict"] == "KEEP"
    assert lines[0]["dimensions"]["correctness"] == 4
    assert lines[0]["auto_gate_snapshot"] == "KEEP"
    # second block untouched
    assert rui.decided_ids(decisions) == {"rev_000000"}


def test_run_session_resume_skips_decided(tmp_path):
    decisions = tmp_path / "decisions.jsonl"
    pre = rui.build_decision(_blind_block(0), _sample_index()["rev_000000"],
                             "KEEP", [4, 3, 4, 4], "earlier session",
                             "human:test", now="T0")
    rui.append_decision(decisions, pre)

    counts = rui.run_session(
        [_blind_block(i) for i in range(2)], _sample_index(), decisions,
        "human:test",
        input_fn=ScriptedInput(["x", "1 1 2 3", "truncated mid-section"]),
        print_fn=lambda *a, **k: None,
        now_fn=lambda: "2026-08-22T01:00:00+00:00",
    )
    assert counts["REJECT"] == 1
    lines = [json.loads(l) for l in decisions.read_text().splitlines()]
    assert len(lines) == 2
    assert lines[0]["review_id"] == "rev_000000"   # from earlier session
    assert lines[1]["review_id"] == "rev_000001"   # resume starts here
    assert lines[1]["verdict"] == "REJECT"


def test_run_session_pager_then_verdict(tmp_path):
    decisions = tmp_path / "decisions.jsonl"
    paged: list[str] = []

    def fake_pager(text: str) -> None:
        paged.append(text)

    counts = rui.run_session(
        [_blind_block(0)], _sample_index(), decisions, "human:test",
        input_fn=ScriptedInput(["f", "k", "", ""]),
        print_fn=lambda *a, **k: None,
        pager_fn=fake_pager,
        now_fn=lambda: "T0",
    )
    assert counts["KEEP"] == 1
    assert len(paged) == 1
    assert "PROBLEM (motivation)" in paged[0]
    assert "[+" not in paged[0]  # full text: no truncation marker


def test_render_truncation_marker():
    long_block = _blind_block(0)
    long_block["payload"]["solution"] = "x" * 5000
    short = rui.render(long_block, max_solution=100)
    assert "[+" in short and "press f for full text" in short
    full = rui.render(long_block, full=True)
    assert "[+" not in full


def test_append_creates_parent_dirs(tmp_path):
    out = tmp_path / "sub" / "dir" / "decisions.jsonl"
    rui.append_decision(out, {"review_id": "rev_000000"})
    assert rui.decided_ids(out) == {"rev_000000"}
