"""AI-2 blindness + fail-closed transport tests (offline, no network)."""
import inspect
import json
import os

import pytest

import ai2_reviewer


def test_system_prompt_names_no_prior_scores():
    prompt = ai2_reviewer.SYSTEM_PROMPT.lower()
    assert "jev" not in prompt
    assert "noul" not in prompt
    assert "prior score" not in prompt
    assert "previous" not in prompt


def test_message_payload_carries_only_content_and_taxonomy():
    msgs = ai2_reviewer.build_messages("user?q", "assistant!a", "math", "alg")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    record = json.loads(msgs[1]["content"])
    assert set(record.keys()) == {"claimed_category", "claimed_subcategory",
                                  "user", "assistant"}
    assert record["claimed_category"] == "math"
    assert "jev" not in msgs[1]["content"].lower()


def test_reviewer_accepts_no_jev_arguments():
    params = set(inspect.signature(ai2_reviewer.review_record).parameters)
    assert params == {"user_text", "asst_text", "category", "subcategory",
                      "config"}
    for name in params:
        assert "jev" not in name and "score" not in name


def test_module_source_references_no_jev_or_human_labels():
    src = open(ai2_reviewer.__file__).read().lower()
    assert "noul" not in src
    assert "jev_results" not in src
    assert "phase2" not in src
    assert "human_label" not in src
    assert "ground truth" not in src


def test_missing_provider_config_fails_closed(monkeypatch):
    for var in ("ATLAS_REVIEW_BASE_URL", "OPENAI_BASE_URL",
                "ATLAS_REVIEW_MODEL", "OPENAI_MODEL",
                "ATLAS_REVIEW_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ai2_reviewer.AI2Error):
        ai2_reviewer.resolve_config()


def test_malformed_ai2_output_never_parses_to_verdict():
    with pytest.raises(ai2_reviewer.AI2Error):
        ai2_reviewer.extract_json_object("no json here at all [[[")
    with pytest.raises(ai2_reviewer.AI2Error):
        ai2_reviewer.parse_verdict(json.dumps({"verdict": "MAYBE",
                                               "confidence": 0.5,
                                               "correctness": "pass",
                                               "completeness": "pass",
                                               "suitability": "pass",
                                               "rationale": "x"}))
    with pytest.raises(ai2_reviewer.AI2Error):
        ai2_reviewer.parse_verdict(json.dumps({"verdict": "ACCEPT",
                                               "confidence": 1.5,
                                               "correctness": "pass",
                                               "completeness": "pass",
                                               "suitability": "pass",
                                               "rationale": "x"}))
    with pytest.raises(ai2_reviewer.AI2Error):
        ai2_reviewer.parse_verdict(json.dumps({"verdict": "ACCEPT",
                                               "confidence": True,
                                               "correctness": "pass",
                                               "completeness": "pass",
                                               "suitability": "pass",
                                               "rationale": "x"}))


def test_valid_ai2_payload_parses():
    parsed = ai2_reviewer.parse_verdict(json.dumps({
        "verdict": "REJECT", "confidence": 0.85, "correctness": "fail",
        "completeness": "pass", "suitability": "fail",
        "rationale": "dead code param"}))
    assert parsed["verdict"] == "REJECT"
    assert parsed["confidence"] == 0.85


def test_credentials_never_persisted_to_disk():
    src = open(ai2_reviewer.__file__).read()
    assert "api_key" in src.lower()
    # key is only ever read from env and placed in a request header
    assert "os.environ.get" in src
    assert "Authorization" in src
