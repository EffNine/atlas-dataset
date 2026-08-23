#!/usr/bin/env python3
"""Tests for the local agentic-trajectory adapter (offline, synthetic)."""

from __future__ import annotations

import json

from expert_pipeline.adapters.agentic_local import (
    AgenticLocalAdapter,
    completion_verdict,
    count_observations,
    difficulty_from_observations,
    split_system,
    structural_gate,
)
from expert_pipeline.runner import ADAPTERS, SOURCE_TO_KEY
from expert_pipeline.validation import validate_provenance, validate_schema

from conftest import score_record


def _msg(role, content):
    return {"role": role, "content": content}


def _trajectory(*, turns=12, verdict="completed", system=True,
                end_assistant=True, obs=4):
    msgs = []
    if system:
        msgs.append(_msg("system", "You are a coding agent. Repo: /repo"))
    msgs.append(_msg("user", "Fix the failing test in utils.py"))
    for i in range(max(1, (turns - 2) // 2)):
        msgs.append(_msg("assistant", f"THOUGHT: step {i}\n```bash\ncat file{i}\n```"))
        msgs.append(_msg("user", f"<returncode>0</returncode>\noutput {i}"))
        if i == 0:
            msgs.append(_msg("user", "OBSERVATION: test list loaded"))
    if verdict == "completed":
        msgs.append(_msg("assistant", "All tests passing. The bug is fixed and verified."))
    elif verdict == "failed":
        msgs.append(_msg("assistant", "Traceback shows the fix did not work."))
    else:
        msgs.append(_msg("assistant", "Status remains unclear so far."))
    if not end_assistant:
        msgs.append(_msg("user", "<returncode>0</returncode>\nok"))
    # ensure observation floor for short trajectories
    while count_observations(msgs) < obs:
        msgs.insert(len(msgs) - 1, _msg("user", "<returncode>0</returncode>\nx"))
    return {"id": f"traj_{abs(hash(turns)) % 99999}", "messages": msgs,
            "verified": False, "language": "en", "category": "swe",
            "subcategory": "debug", "quality_score": 7}


def test_split_system_and_observations():
    t = _trajectory()
    rest, sys_text = split_system(t["messages"])
    assert all(m["role"] != "system" for m in rest)
    assert "coding agent" in sys_text
    assert count_observations(rest) >= 2


def test_completion_verdict_variants():
    assert completion_verdict(split_system(_trajectory(verdict="completed")["messages"])[0]) == "completed"
    assert completion_verdict(split_system(_trajectory(verdict="failed")["messages"])[0]) == "failed"
    assert completion_verdict(split_system(_trajectory(verdict="inconclusive")["messages"])[0]) == "inconclusive"


def test_difficulty_mapping():
    assert difficulty_from_observations(25) == 4
    assert difficulty_from_observations(12) == 3
    assert difficulty_from_observations(6) == 2
    assert difficulty_from_observations(3) == 1


def test_structural_gate_reasons():
    good = split_system(_trajectory()["messages"])[0]
    assert structural_gate(good, 4, "completed") is None
    assert structural_gate(good[:5], 2, "completed") == "too_few_messages"
    assert structural_gate(good, 1, "completed") == "too_few_observations"
    bad_end = split_system(_trajectory(end_assistant=False)["messages"])[0]
    assert structural_gate(bad_end, 4, "completed") == "does_not_end_on_assistant"
    assert structural_gate(good, 4, "failed").startswith("verdict_")


def test_iter_raw_gates_and_yields(tmp_path):
    rows = [
        json.dumps(_trajectory(turns=14)),                       # ok
        json.dumps(_trajectory(verdict="failed")),               # gated out
        json.dumps({"messages": [_msg("user", "hi")]}),          # gated out
        "{not json",                                             # skipped
        json.dumps(_trajectory(turns=16)),
    ]
    p = tmp_path / "traj.jsonl"
    p.write_text("\n".join(rows) + "\n")

    adapter = AgenticLocalAdapter(accessed_at="2026-08-23", paths=[p])
    raws = list(adapter.iter_raw(limit=10))
    assert len(raws) == 2
    assert all(r["_stats"]["verdict"] == "completed" for r in raws)
    # skip counters accumulate: by the second yield, all three rejects are counted
    stats = raws[1]["_stats"]["skipped_before_yield"]
    assert stats.get("verdict_failed") == 1
    assert stats.get("too_few_messages") == 1
    assert stats.get("bad_json") == 1


def test_to_record_schema_valid(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(json.dumps(_trajectory()) + "\n")
    adapter = AgenticLocalAdapter(accessed_at="2026-08-23", paths=[p])
    raw = next(adapter.iter_raw(limit=1))
    rec = adapter.to_record(raw, 0)

    assert rec["source"]["source_id"] == "expert-agentic-001"
    assert rec["license"] == "MIT"
    assert rec["type"] == "code"
    assert rec["metadata"]["model_generated"] is True
    assert rec["metadata"]["synthetic"] is True
    assert rec["verification"]["status"] == "unverified"
    assert rec["provenance"]["original_id"].startswith("expert-agentic-001:")
    # canonical messages carry no system role; first user, last assistant
    assert rec["messages"][0]["role"] == "user"
    assert rec["messages"][-1]["role"] == "assistant"
    assert all(m["role"] != "system" for m in rec["messages"])
    assert "[upstream system]" in rec["context"]

    score_record(rec)
    assert validate_schema(rec) == []
    assert validate_provenance(rec) == []


def test_registry_consistency():
    assert ADAPTERS["agentic-local"].source_id == "expert-agentic-001"
    assert SOURCE_TO_KEY["expert-agentic-001"] == "agentic-local"
