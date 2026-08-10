"""Tests for Protocol v2 reference-leakage prevention and detection.

Covers:
  * ``prompts.build_reference_free_prompt`` — reference-free prompt contract,
    fail-closed on missing/empty ``canonical_answer``,
  * ``prompts.guard_reference_free`` — the v1 leaked pattern MUST trip
    (positive control) while a clean reference-free prompt passes (negative
    control),
  * prompt-hash / fingerprint reproducibility,
  * the deterministic ChatML renderer output format,
  * L1 ``scan`` verdicts on clean vs. leaked eval records.

Hermetic, offline, stdlib-only (conftest.py adds ``scripts/`` to sys.path).
"""

from __future__ import annotations

import pytest

from evaluation_engine.leakage.prompts import (
    ReferenceLeakError,
    build_reference_free_prompt,
    get_policy_lock,
    guard_reference_free,
    prompt_fingerprint,
    prompt_sha256,
    render_chatml_qwen25,
    TEMPLATE_VERSION,
)
from evaluation_engine.leakage.scan import scan_record


def make_math_record(problem="What is 2+2?", canonical="The answer is 4.",
                     **overrides):
    rec = {
        "record_id": "expert_math_test_0001",
        "family": "math",
        "eval_set_id": "math_eval_v2",
        "problem": problem,
        "canonical_answer": canonical,
        "canonical_answer_sha256": None,
        "messages": [{"role": "user", "content": problem}],
    }
    rec.update(overrides)
    return rec


# --------------------------------------------------------------------------- #
# Reference-free prompt builder
# --------------------------------------------------------------------------- #
class TestBuildReferenceFreePrompt:
    def test_prompt_from_problem_only(self):
        rec = make_math_record()
        prompt = build_reference_free_prompt(rec, get_policy_lock("math"))
        assert rec["problem"] in prompt
        assert rec["canonical_answer"] not in prompt
        assert rec["canonical_answer"].split()[0] not in prompt

    def test_missing_canonical_answer_fails_closed(self):
        rec = make_math_record(canonical="")
        with pytest.raises(ReferenceLeakError):
            build_reference_free_prompt(rec, get_policy_lock("math"))

    def test_missing_problem_fails_closed(self):
        rec = make_math_record(problem="")
        with pytest.raises(ReferenceLeakError):
            build_reference_free_prompt(rec, get_policy_lock("math"))

    def test_hash_reproducible(self):
        rec = make_math_record()
        p1 = build_reference_free_prompt(rec, get_policy_lock("math"))
        p2 = build_reference_free_prompt(rec, get_policy_lock("math"))
        assert p1 == p2
        assert prompt_sha256(p1) == prompt_sha256(p2)
        assert prompt_fingerprint(p1) == prompt_fingerprint(p2)

    def test_messages_never_read(self):
        # A record whose messages carry the gold (a hostile/buggy record) must
        # not change the prompt: the builder only reads problem + policy.
        rec = make_math_record()
        clean_prompt = build_reference_free_prompt(rec, get_policy_lock("math"))
        rec["messages"] = [
            {"role": "user", "content": rec["problem"]},
            {"role": "assistant", "content": rec["canonical_answer"]},
        ]
        same_prompt = build_reference_free_prompt(rec, get_policy_lock("math"))
        assert clean_prompt == same_prompt


# --------------------------------------------------------------------------- #
# Runtime guard
# --------------------------------------------------------------------------- #
class TestGuardReferenceFree:
    def test_clean_prompt_passes(self):
        rec = make_math_record()
        prompt = build_reference_free_prompt(rec, get_policy_lock("math"))
        guard_reference_free(prompt, rec["canonical_answer"], rec["record_id"])

    def test_v1_leaked_pattern_trips(self):
        """Reconstruct the historical v1 leak: full ``messages`` (including the
        assistant gold) rendered with the ChatML template and an empty
        generation turn. The guard MUST raise (positive control)."""
        rec = make_math_record()
        leaked = render_chatml_qwen25(
            get_policy_lock("math").system_message_text,
            rec["problem"],
            add_generation_prompt=False,
        ) + f"<|im_start|>assistant\n{rec['canonical_answer']}<|im_end|>\n" \
            "<|im_start|>assistant\n"
        with pytest.raises(ReferenceLeakError):
            guard_reference_free(leaked, rec["canonical_answer"], rec["record_id"])

    def test_gold_appended_to_prompt_trips(self):
        prompt = build_reference_free_prompt(
            make_math_record(), get_policy_lock("math"))
        with pytest.raises(ReferenceLeakError):
            guard_reference_free(
                prompt + " " + "The answer is 4.", "The answer is 4.", "r1")

    def test_empty_reference_trips(self):
        prompt = build_reference_free_prompt(
            make_math_record(), get_policy_lock("math"))
        with pytest.raises(ReferenceLeakError):
            guard_reference_free(prompt, "   ", "r1")


# --------------------------------------------------------------------------- #
# Deterministic renderer
# --------------------------------------------------------------------------- #
class TestRenderer:
    def test_template_version(self):
        assert TEMPLATE_VERSION == "qwen2.5-chatml-deterministic-v1"

    def test_chatml_format(self):
        out = render_chatml_qwen25("SYS", "USER")
        assert out.startswith("<|im_start|>system\nSYS<|im_end|>\n")
        assert "<|im_start|>user\nUSER<|im_end|>\n" in out
        assert out.endswith("<|im_start|>assistant\n")

    def test_deterministic(self):
        assert render_chatml_qwen25("S", "U") == render_chatml_qwen25("S", "U")


# --------------------------------------------------------------------------- #
# L1 static scan
# --------------------------------------------------------------------------- #
class TestScan:
    def test_clean_record_passes(self):
        rec = make_math_record()
        rec["canonical_answer_sha256"] = __import__(
            "hashlib").sha256(rec["canonical_answer"].encode()).hexdigest()
        verdict = scan_record(rec, "math")
        assert verdict["leak_verdict"] == "pass"
        assert verdict["checks"]["reference_absent_from_prompt"] is True
        assert verdict["checks"]["messages_reference_free"] is True

    def test_leaked_record_fails(self):
        # canonical_answer appears verbatim in the problem -> must fail.
        rec = make_math_record(
            problem="The answer is 4.", canonical="The answer is 4.")
        verdict = scan_record(rec, "math")
        assert verdict["leak_verdict"] == "fail"

    def test_messages_with_gold_fails(self):
        rec = make_math_record()
        rec["canonical_answer_sha256"] = __import__(
            "hashlib").sha256(rec["canonical_answer"].encode()).hexdigest()
        rec["messages"] = [
            {"role": "user", "content": rec["problem"]},
            {"role": "assistant", "content": rec["canonical_answer"]},
        ]
        verdict = scan_record(rec, "math")
        assert verdict["leak_verdict"] == "fail"
        assert verdict["checks"]["messages_reference_free"] is False

    def test_missing_canonical_answer_fails(self):
        rec = make_math_record(canonical="")
        verdict = scan_record(rec, "math")
        assert verdict["leak_verdict"] == "fail"
        assert verdict["checks"]["has_canonical_answer"] is False
