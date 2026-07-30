#!/usr/bin/env python3
"""
test_intelligence_layer.py — Validation suite for the Atlas Intelligence Layer v1.

Tests cover:
- Difficulty taxonomy schema validity
- Intelligence metadata schema validity
- Difficulty analyzer signal extraction
- Difficulty range (1-5) and confidence range (0-1)
- Missing fields handling
- Deterministic output
- No dataset modification invariant
"""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts" / "intelligence"))

from difficulty_analyzer import (
    analyze_record,
    _prompt_complexity,
    _answer_complexity,
    _technical_vocabulary_density,
    _reasoning_depth,
    _compute_difficulty,
    _detect_reasoning_types,
    _detect_skill_domains,
    _estimate_tokens,
    _text_from_messages,
    _normalize_source_name,
    _source_reliability,
    LEVEL_THRESHOLDS_V1_0,
    LEVEL_THRESHOLDS_V1_1,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SIMPLE_RECORD = {
    "id": "test_basic_001",
    "category": "01_foundation",
    "subcategory": "general_knowledge",
    "type": "qa",
    "source": {"name": "tulu3_sft", "license": "MIT"},
    "messages": [
        {"role": "user", "content": "What is the capital of France?"},
        {"role": "assistant", "content": "Paris."},
    ],
    "tags": ["geography"],
    "quality_score": 7,
    "verified": True,
    "notes": "",
}

COMPLEX_RECORD = {
    "id": "test_complex_002",
    "category": "04_ai_machine_learning",
    "subcategory": "nlp",
    "type": "reasoning",
    "source": {"name": "arxiv_cs", "license": "MIT"},
    "messages": [
        {
            "role": "user",
            "content": "Design a novel attention mechanism that reduces quadratic complexity in long-context transformers.",
        },
        {
            "role": "assistant",
            "content": (
                "We propose a sparse-slot attention mechanism. First, we project queries into "
                "K clusters via k-means hashing. Second, each key attends only to its top-k "
                "nearest cluster centroids. Third, we apply a softmax over the masked attention "
                "scores. This reduces complexity from O(n²) to O(nk) where k << n. However, "
                "the trade-off is that cross-cluster information flow is limited, which may "
                "degrade performance on tasks requiring global context. We evaluate on "
                "LongBench and demonstrate 2x throughput with < 3% accuracy loss. "
                "The implications for deployment in production RAG systems are significant, "
                "as it enables 128K context windows on consumer hardware."
            ),
        },
    ],
    "tags": ["transformer", "attention", "efficiency"],
    "quality_score": 9,
    "verified": True,
    "notes": "",
}

MINIMAL_RECORD = {
    "id": "test_minimal_003",
    "category": "01_foundation",
    "messages": [],
}

RECORD_WITH_CONTENT = {
    "id": "test_content_004",
    "category": "06_science_engineering",
    "subcategory": "mathematics",
    "source": {"name": "openwebmath", "license": "unknown"},
    "content": {
        "question": "Solve for x: 2x + 3 = 7",
        "answer": "2x + 3 = 7 => 2x = 4 => x = 2",
    },
    "tags": ["algebra"],
}

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


# ===================================================================
# Tests
# ===================================================================


def test_schema_validity() -> None:
    """Validate that the intelligence schema JSON is valid and has required fields."""
    schema_path = ROOT / "metadata" / "intelligence" / "intelligence_schema_v1.json"
    taxonomy_path = ROOT / "metadata" / "intelligence" / "difficulty_taxonomy_v1.json"

    check("Schema file exists", schema_path.exists())
    check("Taxonomy file exists", taxonomy_path.exists())

    if schema_path.exists():
        with open(schema_path, encoding="utf-8") as f:
            schema = json.load(f)
        check("Schema has required 'properties'", "properties" in schema)
        check("Schema defines 'difficulty' property", "difficulty" in schema.get("properties", {}))
        check(
            "Schema has definitions for difficulty_level",
            "difficulty_level" in schema.get("definitions", {}),
        )
        diff_level = schema["definitions"]["difficulty_level"]
        check("Difficulty level min=1", diff_level.get("minimum") == 1)
        check("Difficulty level max=5", diff_level.get("maximum") == 5)

    if taxonomy_path.exists():
        with open(taxonomy_path, encoding="utf-8") as f:
            taxa = json.load(f)
        levels = taxa.get("levels", {})
        check("Taxonomy defines 5 levels", len(levels) == 5)
        for lid in ["1", "2", "3", "4", "5"]:
            check(f"Level {lid} has label", "label" in levels.get(lid, {}))
            check(f"Level {lid} has indicators", "indicators" in levels.get(lid, {}))


def test_analyzer_accepts_valid_record() -> None:
    """analyze_record returns a valid result for a well-formed record."""
    result = analyze_record(SIMPLE_RECORD)
    check("analyze_record returns dict for valid record", isinstance(result, dict))

    if result:
        check("Result has 'record_id'", "record_id" in result)
        check("Result has 'difficulty'", "difficulty" in result)
        check("Result has 'reasoning_types'", "reasoning_types" in result)
        check("Result has 'skill_domains'", "skill_domains" in result)
        check("Result has 'classifier_version'", "classifier_version" in result)
        check("Result has 'classified_at'", "classified_at" in result)
        check("Result has 'features'", "features" in result)


def test_difficulty_level_range() -> None:
    """Difficulty level is always 1-5."""
    for rec in [SIMPLE_RECORD, COMPLEX_RECORD, RECORD_WITH_CONTENT]:
        result = analyze_record(rec)
        if result:
            level = result["difficulty"]["level"]
            check(
                f"{rec['id']}: difficulty level {level} in 1..5",
                1 <= level <= 5,
                f"got={level}",
            )


def test_confidence_range() -> None:
    """Confidence is always 0.0-1.0."""
    for rec in [SIMPLE_RECORD, COMPLEX_RECORD, RECORD_WITH_CONTENT]:
        result = analyze_record(rec)
        if result:
            conf = result["difficulty"]["confidence"]
            check(
                f"{rec['id']}: confidence {conf:.4f} in 0..1",
                0.0 <= conf <= 1.0,
                f"got={conf}",
            )


def test_deterministic_output() -> None:
    """Same record always produces identical output (excluding timestamps)."""
    r1 = analyze_record(COMPLEX_RECORD)
    r2 = analyze_record(COMPLEX_RECORD)
    r3 = analyze_record(COMPLEX_RECORD)

    check("Three calls all return dicts", r1 and r2 and r3)
    if r1 and r2 and r3:
        # Exclude time-variant fields from comparison
        def _stable(d: dict) -> str:
            d = deepcopy(d)
            d.pop("classified_at", None)
            return json.dumps(d, sort_keys=True)

        check("r1 == r2 (deterministic, excl. timestamps)", _stable(r1) == _stable(r2))
        check("r2 == r3 (deterministic, excl. timestamps)", _stable(r2) == _stable(r3))


def test_missing_fields_handled() -> None:
    """Analyzer handles records with missing or minimal fields gracefully."""
    result = analyze_record(MINIMAL_RECORD)
    # Should return None for truly empty records, or a valid result with low confidence
    check("Minimal record returns None or valid", result is None or (
        isinstance(result, dict) and "record_id" in result
    ))


def test_no_dataset_modification() -> None:
    """analyze_record NEVER modifies the input record."""
    original = deepcopy(SIMPLE_RECORD)
    _ = analyze_record(SIMPLE_RECORD)
    check("Original record unchanged", json.dumps(original, sort_keys=True) == json.dumps(SIMPLE_RECORD, sort_keys=True))

    original2 = deepcopy(COMPLEX_RECORD)
    _ = analyze_record(COMPLEX_RECORD)
    check("Complex record unchanged", json.dumps(original2, sort_keys=True) == json.dumps(COMPLEX_RECORD, sort_keys=True))


def test_signal_extractors() -> None:
    """Individual signal extractors produce sensible values."""
    prompt, answer = _text_from_messages(COMPLEX_RECORD["messages"])

    pc = _prompt_complexity(prompt, answer)
    check("Prompt complexity in 0..1", 0.0 <= pc <= 1.0, f"pc={pc:.4f}")
    check("Complex prompt scores > simple", pc > 0.1, f"pc={pc:.4f}")

    ac = _answer_complexity(answer)
    check("Answer complexity in 0..1", 0.0 <= ac <= 1.0, f"ac={ac:.4f}")
    check("Complex answer scores > minimal", ac > 0.1, f"ac={ac:.4f}")

    combined = prompt + " " + answer
    tv = _technical_vocabulary_density(combined, COMPLEX_RECORD["category"])
    check("Technical vocab density in 0..1", 0.0 <= tv <= 1.0, f"tv={tv:.4f}")

    rd = _reasoning_depth(prompt, answer)
    check("Reasoning depth in 0..1", 0.0 <= rd <= 1.0, f"rd={rd:.4f}")


def test_reasoning_type_detection() -> None:
    """Reasoning types are detected appropriately."""
    prompt_simple, answer_simple = _text_from_messages(SIMPLE_RECORD["messages"])
    types_simple = _detect_reasoning_types(prompt_simple, answer_simple)
    check("Simple record has at least 1 reasoning type", len(types_simple) >= 1)
    check("Simple record detected as 'factual'", "factual" in types_simple)

    prompt_complex, answer_complex = _text_from_messages(COMPLEX_RECORD["messages"])
    types_complex = _detect_reasoning_types(prompt_complex, answer_complex)
    check("Complex record has >= 1 type", len(types_complex) >= 1)
    # Complex record should have non-factual types
    has_deep_type = any(t in ["design", "analysis", "research"] for t in types_complex)
    check("Complex record has deep reasoning type", has_deep_type, f"types={types_complex}")


def test_skill_domain_detection() -> None:
    """Skill domains are mapped from categories and content."""
    domains_simple = _detect_skill_domains("What is the capital?", "Paris.", SIMPLE_RECORD["category"])
    check("Simple record has skill domains", len(domains_simple) >= 1)

    domains_complex = _detect_skill_domains(
        "Design a novel attention mechanism",
        "We propose sparse attention with k-means hashing.",
        COMPLEX_RECORD["category"],
    )
    check("Complex record has 'ai_ml' domain", "ai_ml" in domains_complex)


def test_complex_record_expert_level() -> None:
    """A complex design/research record should score at least L2."""
    result = analyze_record(COMPLEX_RECORD)
    if result:
        level = result["difficulty"]["level"]
        check(
            f"Complex record level >= 2",
            level >= 2,
            f"level={level}",
        )


def test_record_id_preserved() -> None:
    """The output record_id matches the input id."""
    result = analyze_record(SIMPLE_RECORD)
    if result:
        check(
            "record_id preserved",
            result["record_id"] == SIMPLE_RECORD["id"],
            f"expected={SIMPLE_RECORD['id']} got={result['record_id']}",
        )


def test_feature_fields() -> None:
    """Features are present and sensible."""
    result = analyze_record(COMPLEX_RECORD)
    if result and "features" in result:
        feat = result["features"]
        check("Features has prompt_tokens", isinstance(feat.get("prompt_tokens"), int))
        check("Features has answer_tokens", isinstance(feat.get("answer_tokens"), int))
        check("Features has total_tokens >= 0", feat.get("total_tokens", -1) >= 0)
        check("Features has vocabulary_density in 0..1", 0.0 <= feat.get("vocabulary_density", -1) <= 1.0)
        check("Features has reasoning_steps_estimate >= 0", feat.get("reasoning_steps_estimate", -1) >= 0)
        check("Features has cross_domain_flag", "cross_domain_flag" in feat)


def test_token_estimator() -> None:
    """Token estimation is positive for non-empty text."""
    check("Empty text -> 0 tokens", _estimate_tokens("") == 0)
    check("Non-empty text -> > 0 tokens", _estimate_tokens("Hello world this is text") > 0)


def test_text_from_messages() -> None:
    """Text extraction from messages works correctly."""
    prompt, answer = _text_from_messages(SIMPLE_RECORD["messages"])
    check("Prompt extracted", len(prompt) > 0)
    check("Answer extracted", len(answer) > 0)

    prompt2, answer2 = _text_from_messages([])
    check("No messages -> empty prompt", prompt2 == "")
    check("No messages -> empty answer", answer2 == "")


# ---------------------------------------------------------------------------
# v1.1 Regression tests
# ---------------------------------------------------------------------------


def test_source_trust_normalization() -> None:
    """Source names are normalized to match SOURCE_TRUST keys."""
    # open-web-math (hyphenated) -> openwebmath key
    rec1 = {"id": "t1", "source": {"name": "open-web-math/open-web-math", "license": "ODC-BY"}}
    trust1 = _source_reliability(rec1)
    check("open-web-math matches openwebmath trust (0.80)", abs(trust1 - 0.80) < 0.01, f"got={trust1}")

    # Tulu-3 with OASST1 sub-source
    rec2 = {"id": "t2", "source": {"name": "ai2-adapt-dev/oasst1_converted", "license": "MIT"}}
    trust2 = _source_reliability(rec2)
    check(
        "oasst1_converted falls back to 'other' (no tulu3_sft in name)",
        abs(trust2 - 0.40) < 0.01,
        f"got={trust2}",
    )

    # arXiv (capitalised, with dot notation)
    rec3 = {"id": "t3", "source": {"name": "arXiv cs.LO, cs.PL, cs.SE", "license": "arXiv"}}
    trust3 = _source_reliability(rec3)
    check("arXiv cs.* matches arxiv_cs trust (0.90)", abs(trust3 - 0.90) < 0.01, f"got={trust3}")

    # C4 direct match
    rec4 = {"id": "t4", "source": {"name": "allenai/c4", "license": "ODC-BY"}}
    trust4 = _source_reliability(rec4)
    check("allenai/c4 direct match (0.60)", abs(trust4 - 0.60) < 0.01, f"got={trust4}")

    # Empty / missing source -> other
    rec5 = {"id": "t5"}
    trust5 = _source_reliability(rec5)
    check("Missing source -> other (0.40)", abs(trust5 - 0.40) < 0.01, f"got={trust5}")


def test_short_record_confidence() -> None:
    """Short records with clear signals should not have collapsed confidence."""
    # A very short but clear Q&A: confidence should NOT be ~0.24
    rec = {
        "id": "short_001",
        "category": "01_foundation",
        "source": {"name": "tulu3_sft", "license": "MIT"},
        "messages": [
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4."},
        ],
    }
    result = analyze_record(rec)
    check("Short record is classified", result is not None)
    if result:
        conf = result["difficulty"]["confidence"]
        check(
            f"Short record confidence > 0.30 (no collapse)",
            conf > 0.30,
            f"got={conf}",
        )
        check(
            "Short record is L1",
            result["difficulty"]["level"] == 1,
            f"got level={result['difficulty']['level']}",
        )


def test_override_thresholds() -> None:
    """_compute_difficulty accepts override_thresholds for A/B calibration."""
    # Use v1.0 thresholds to reproduce v1.0 behaviour
    level, conf = _compute_difficulty(
        prompt_complexity=0.38,
        answer_complexity=0.40,
        tech_vocab_density=0.30,
        reasoning_depth=0.35,
        source_reliability=0.80,
        domain_offset=0.20,
        override_thresholds=LEVEL_THRESHOLDS_V1_0,
    )
    # Under v1.0 thresholds: raw ~0.38*0.15+0.40*0.30+0.30*0.18+0.35*0.30+0.20*0.07
    # = 0.057+0.12+0.054+0.105+0.014 = 0.35 → L2 (below 0.40 L3 threshold)
    check(
        "V1.0 thresholds: raw ~0.35 → L2",
        level == 2,
        f"got level={level}",
    )
    # Under v1.1 thresholds: same raw=0.35 → L3 (above 0.35)
    level2, _ = _compute_difficulty(
        prompt_complexity=0.38,
        answer_complexity=0.40,
        tech_vocab_density=0.30,
        reasoning_depth=0.35,
        source_reliability=0.80,
        domain_offset=0.20,
        override_thresholds=LEVEL_THRESHOLDS_V1_1,
    )
    check(
        "V1.1 thresholds: raw ~0.35 → L3",
        level2 == 3,
        f"got level={level2}",
    )


def test_threshold_calibration_shifts() -> None:
    """V1.1 thresholds should push more records into higher levels."""
    # Near-boundary record: raw ~0.38
    high_v1 = 0
    high_v1_1 = 0
    borderline_cases = [
        # (prompt, answer, tech_vocab, reasoning_depth, source, domain)
        (0.35, 0.40, 0.15, 0.30, 0.80, 0.20),  # raw ≈ 0.34
        (0.40, 0.42, 0.20, 0.35, 0.80, 0.20),  # raw ≈ 0.38
        (0.45, 0.50, 0.25, 0.40, 0.80, 0.20),  # raw ≈ 0.43
        (0.50, 0.55, 0.35, 0.50, 0.80, 0.30),  # raw ≈ 0.52
        (0.55, 0.65, 0.40, 0.60, 0.80, 0.30),  # raw ≈ 0.60
    ]
    for sig in borderline_cases:
        lv1, _ = _compute_difficulty(*sig, override_thresholds=LEVEL_THRESHOLDS_V1_0)
        lv11, _ = _compute_difficulty(*sig, override_thresholds=LEVEL_THRESHOLDS_V1_1)
        if lv11 > lv1:
            high_v1_1 += 1
        elif lv11 == lv1:
            high_v1 += 1

    check(
        "V1.1 thresholds promote >=1 borderline case vs v1.0",
        high_v1_1 >= 1,
        f"v1.0 higher={high_v1}, v1.1 higher={high_v1_1}",
    )


# ===================================================================
# Main
# ===================================================================


def main() -> int:
    print("=" * 60)
    print("Atlas Intelligence Layer v1 — Validation Suite")
    print("=" * 60)
    print()

    tests = [
        ("Schema validity", test_schema_validity),
        ("Analyzer accepts valid record", test_analyzer_accepts_valid_record),
        ("Difficulty level range (1-5)", test_difficulty_level_range),
        ("Confidence range (0-1)", test_confidence_range),
        ("Deterministic output", test_deterministic_output),
        ("Missing fields handled", test_missing_fields_handled),
        ("No dataset modification", test_no_dataset_modification),
        ("Signal extractors", test_signal_extractors),
        ("Reasoning type detection", test_reasoning_type_detection),
        ("Skill domain detection", test_skill_domain_detection),
        ("Complex record classification", test_complex_record_expert_level),
        ("Record ID preserved", test_record_id_preserved),
        ("Feature fields", test_feature_fields),
        ("Token estimator", test_token_estimator),
        ("Text from messages", test_text_from_messages),
        ("Source trust normalization (v1.1)", test_source_trust_normalization),
        ("Short record confidence (v1.1)", test_short_record_confidence),
        ("Override thresholds (v1.1)", test_override_thresholds),
        ("Threshold calibration shifts (v1.1)", test_threshold_calibration_shifts),
    ]

    failures = 0
    for name, func in tests:
        try:
            func()
        except Exception as e:
            print(f"  [ERROR] {name} raised exception: {e}")
            failures += 1

    # Summary
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)

    print()
    print("=" * 60)
    print(f"  Total checks: {len(results)}")
    print(f"  Passed:       {passed}")
    print(f"  Failed:       {failed}")
    print(f"  Errors:       {failures}")
    print("=" * 60)

    if failed > 0 or failures > 0:
        print("\nFailed checks:")
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name}  [{detail}]")

    return 1 if (failed > 0 or failures > 0) else 0


if __name__ == "__main__":
    sys.exit(main())
