#!/usr/bin/env python3
"""Tests for the AI semantic reviewer (offline; fake transport, no network)."""

from __future__ import annotations

import json

import pytest

from expert_pipeline import ai_reviewer as air
from expert_pipeline import review_mode as rm
from expert_pipeline.sft_view import gate_record

from conftest import score_record, swe_instance


def _make_record(**overrides) -> dict:
    from expert_pipeline.adapters.swebench import SwebenchAdapter
    rec = SwebenchAdapter(accessed_at="2026-08-23").to_record(
        swe_instance(), 0)
    score_record(rec)
    rec["metadata"]["quality_score"] = 8
    rec.update(overrides)
    return rec


def _model_output(decision="accept", quality=9, confidence=0.9,
                  extra_criteria=None, risk_flags=None, fenced=False,
                  notes="solid record") -> str:
    criteria = {c: 4 for c in air.rm.criteria_for_category("code")}
    if extra_criteria:
        criteria.update(extra_criteria)
    obj = {
        "decision": decision,
        "quality_score": quality,
        "confidence": confidence,
        "criteria": criteria,
        "risk_flags": risk_flags or [],
        "notes": notes,
    }
    text = json.dumps(obj)
    return f"```json\n{text}\n```" if fenced else text


class FakeTransport:
    """Scriptable transport: list of responses/exceptions per call."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, config, messages):
        self.calls.append({"config": config, "messages": messages})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _config() -> air.ReviewerConfig:
    return air.ReviewerConfig(base_url="http://fake/v1", model="reviewer-x",
                              timeout_s=1, max_retries=0)


# --- parsing ---------------------------------------------------------------

def test_parse_accepts_plain_and_fenced_json():
    assert air.parse_review_response(_model_output(), "code")["decision"] == "accept"
    parsed = air.parse_review_response(_model_output(fenced=True), "code")
    assert parsed["quality_score"] == 9
    assert parsed["criteria"]["correctness"] == 4


def test_parse_requires_category_specific_criteria():
    # agentic output missing agentic-specific keys must fail for code category?
    # reverse: code-shaped output reviewed as agentic lacks trajectory criteria.
    with pytest.raises(air.ReviewerError) as ei:
        air.parse_review_response(_model_output(), "agentic")
    assert ei.value.reason == "invalid_structure"
    assert "missing criteria" in str(ei.value)


@pytest.mark.parametrize("raw", [
    "not json at all",
    "{\"decision\": \"pass\"}",
])
def test_parse_rejects_malformed_output(raw):
    with pytest.raises(air.ReviewerError) as ei:
        air.parse_review_response(raw, "code")
    assert ei.value.reason in {"malformed_response", "invalid_structure"}


def test_parse_rejects_out_of_range_scores():
    with pytest.raises(air.ReviewerError):
        air.parse_review_response(_model_output(quality=11), "code")
    with pytest.raises(air.ReviewerError):
        air.parse_review_response(_model_output(confidence=1.5), "code")
    bad = json.loads(_model_output())
    bad["criteria"]["correctness"] = 0
    with pytest.raises(air.ReviewerError):
        air.parse_review_response(json.dumps(bad), "code")


# --- end-to-end single record ---------------------------------------------

def test_review_record_produces_auditable_metadata():
    transport = FakeTransport([_model_output()])
    rec = _make_record()
    result = air.review_record(rec, _config(), transport=transport)
    assert result["decision"] == "accept"
    assert result["review_mode"] == "ai"
    assert result["input_hash"] == rm.input_hash(rec)
    assert len(result["input_hash"]) == 64
    assert result["reviewer"]["provider"] == "openai-compatible"
    assert result["reviewer"]["model"] == "reviewer-x"
    assert result["thresholds"]["accept_min_quality"] == 8
    assert rm.validate_review_result(result) == []
    # blind payload: no quality_score / auto_gate leaks to the model
    user_text = transport.calls[0]["messages"][1]["content"]
    assert "quality_score" not in user_text
    assert "auto_gate" not in user_text


def test_review_record_model_decision_vs_policy_decision():
    # model says accept but confidence low -> policy routes to review
    transport = FakeTransport([_model_output(confidence=0.2)])
    result = air.review_record(_make_record(), _config(), transport=transport)
    assert result["model_decision"] == "accept"
    assert result["decision"] == "review"


def test_transport_failure_raises_reviewer_error():
    with pytest.raises(air.ReviewerError) as ei:
        air.review_record(_make_record(), _config(),
                          transport=FakeTransport([air.ReviewerError(
                              "provider_error", "HTTP 500")]))
    assert ei.value.reason == "provider_error"


def test_missing_api_key_is_fail_closed():
    cfg = air.ReviewerConfig(base_url="", model="")
    with pytest.raises(air.ReviewerError) as ei:
        air.http_transport(cfg, [{"role": "user", "content": "x"}],
                           environ={})
    assert ei.value.reason == "missing_provider_config"
    cfg2 = air.ReviewerConfig(base_url="http://fake/v1", model="m")
    with pytest.raises(air.ReviewerError) as ei2:
        air.http_transport(cfg2, [{"role": "user", "content": "x"}],
                           environ={})
    assert ei2.value.reason == "missing_api_key"


# --- batch run --------------------------------------------------------------

def test_batch_runs_deterministic_gates_first():
    good = _make_record()
    bad_license = _make_record()
    bad_license["id"] = "expert_swe_000009"
    bad_license["license"] = "CC-BY-NC-4.0"   # fails license gate
    out = FakeTransport([_model_output()])
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "reviews.jsonl"
        summary = air.run_batch([good, bad_license], _config(), path,
                                transport=out)
        lines = [json.loads(l) for l in
                 path.read_text().splitlines() if l.strip()]
    # gated-out record never reached the model
    assert len(out.calls) == 1
    gated = [l for l in lines
             if l.get("decision_source") == "deterministic_gate"]
    assert len(gated) == 1
    assert "license" in gated[0]["gate_reasons"]
    assert gated[0]["decision"] == "reject"
    assert summary["gated_out"] == 1
    assert summary["accepted"] == 1


def test_batch_reviewer_failure_routes_to_review_not_pass():
    good = _make_record()
    transport = FakeTransport([air.ReviewerError("timeout", "t")])
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "reviews.jsonl"
        summary = air.run_batch([good], _config(), path, transport=transport)
        lines = [json.loads(l) for l in
                 path.read_text().splitlines() if l.strip()]
    assert summary["failures"] == 1
    assert summary["accepted"] == 0
    entry = lines[0]
    assert entry["decision"] == "review"
    assert entry["decision_source"] == "reviewer_failure"
    assert entry["failure_reason"] == "timeout"


def test_batch_resume_skips_already_reviewed_records():
    good = _make_record()
    transport = FakeTransport([_model_output()])
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "reviews.jsonl"
        air.run_batch([good], _config(), path, transport=transport)
        first_calls = len(transport.calls)
        summary2 = air.run_batch([good], _config(), path, transport=transport)
    assert first_calls == 1
    assert summary2["skipped_resume"] == 1
    assert len(transport.calls) == first_calls  # no second model call


def test_gate_record_unchanged_still_enforced_before_semantic_review():
    rec = _make_record()
    assert gate_record(rec, max_tokens=4096, min_quality=7) == []
    rec["metadata"]["quality_score"] = 3
    assert "quality_below_threshold" in gate_record(rec, max_tokens=4096,
                                                    min_quality=7)


# --- config ----------------------------------------------------------------

def test_config_from_env_and_api_key_resolution():
    env = {"ATLAS_REVIEW_BASE_URL": "http://envhost/v1",
           "ATLAS_REVIEW_MODEL": "env-model",
           "ATLAS_REVIEW_API_KEY": "k1"}
    cfg = air.config_from_env(env)
    assert cfg.base_url == "http://envhost/v1"
    assert cfg.model == "env-model"
    assert cfg.resolve_api_key(env) == "k1"
    assert cfg.resolve_api_key({"OPENAI_API_KEY": "k2"}) == "k2"
    assert cfg.resolve_api_key({}) == ""
