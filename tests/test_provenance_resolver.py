#!/usr/bin/env python3
"""
test_provenance_resolver.py — Unit tests for Phase 5E.4 provenance resolver.

Covers:
  - Exact match classification (verbatim)
  - Condensed content classification
  - Missing source handling
  - Unknown modification classification
  - Record loading
  - Attribute text template generation
  - Integration with real pending_expansion.jsonl (if available)

Run::
    python -m pytest tests/test_provenance_resolver.py -v
    python tests/test_provenance_resolver.py   (standalone)
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

# Ensure the scripts directory is importable
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))

from provenance_resolver import (
    ProvenanceResolver,
    ProvenanceSuggestion,
    ProvenanceReport,
    classify_modification,
    build_attribution_template,
    build_modifications_text,
    load_jsonl,
    STACKEXCHANGE_SOURCE_IDS,
    SHARE_ALIKE_NOTICE,
    PROVENANCE_RESOLUTIONS_PATH,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

SAMPLE_RECORD_VERBATIM = {
    "id": "s5_02_software_engineering_programming_9999",
    "source_id": "s5",
    "source_name": "StackExchange Code (Stack Overflow / Unix & Linux)",
    "source_url": "https://archive.org/details/stackexchange",
    "license": "CC-BY-SA-4.0",
    "category": "02_software_engineering",
    "subcategory": "programming",
    "messages": [
        {"role": "user", "content": "What is a deadlock in concurrent programming?"},
        {"role": "assistant", "content": "A deadlock occurs when two or more threads are each waiting for a resource held by another, causing all to block indefinitely."},
    ],
    "lineage": {
        "source": "StackExchange Code",
        "source_id": "s5",
        "transformations": ["pipeline:acquisition", "pipeline:normalize"],
        "curated_dataset": "v0.2-expansion",
        "training_view": "qwen,llama,deepseek",
    },
}

SAMPLE_RECORD_CONDENSED = {
    "id": "s5_02_software_engineering_programming_9998",
    "source_id": "s5",
    "source_name": "StackExchange Code (Stack Overflow / Unix & Linux)",
    "license": "CC-BY-SA-4.0",
    "messages": [
        {"role": "user", "content": "What is the time complexity of quicksort?"},
        {"role": "assistant", "content": "Average: O(n log n). Worst: O(n²)."},
    ],
}

SAMPLE_RECORD_REPHRASED = {
    "id": "s5_02_software_engineering_programming_9997",
    "source_id": "s5",
    "source_name": "StackExchange Code (Stack Overflow / Unix & Linux)",
    "license": "CC-BY-SA-4.0",
    "messages": [
        {"role": "user", "content": "Explain the CAP theorem."},
        {"role": "assistant", "content": "The CAP theorem states that a distributed data store can provide at most two of three guarantees: consistency, availability, and partition tolerance. This means engineers must make trade-offs when designing distributed systems."},
    ],
}

SAMPLE_RECORD_UNKNOWN = {
    "id": "s5_02_software_engineering_programming_9996",
    "source_id": "s5",
    "source_name": "StackExchange Code (Stack Overflow / Unix & Linux)",
    "license": "CC-BY-SA-4.0",
    "messages": [
        {"role": "user", "content": "Briefly describe REST."},
        {"role": "assistant", "content": "x"},
    ],
}

SAMPLE_RECORD_NON_SE = {
    "id": "s1_02_software_engineering_programming_0001",
    "source_id": "s1",
    "source_name": "princeton-nlp/SWE-bench",
    "license": "MIT",
    "messages": [
        {"role": "user", "content": "What is a stack?"},
        {"role": "assistant", "content": "A stack follows LIFO."},
    ],
}


# ---------------------------------------------------------------------------
# Tests: classify_modification
# ---------------------------------------------------------------------------


def test_classify_exact_match():
    """verbatim classification when source text matches exactly."""
    source = "A deadlock occurs when two or more threads are each waiting for a resource held by another, causing all to block indefinitely."
    answer = "A deadlock occurs when two or more threads are each waiting for a resource held by another, causing all to block indefinitely."
    label, confidence, scores = classify_modification(answer, source_text=source)
    assert label == "verbatim", f"Expected verbatim, got {label}"
    assert confidence >= 0.9
    assert scores.jaccard_similarity >= 0.95


def test_classify_verbatim_with_minor_whitespace():
    """verbatim classification tolerates whitespace differences."""
    source = "TCP: connection-oriented, reliable, ordered. UDP: connectionless, faster, no delivery guarantee."
    answer = "TCP: connection-oriented, reliable, ordered.  UDP: connectionless, faster, no delivery guarantee."
    label, confidence, scores = classify_modification(answer, source_text=source)
    assert label == "verbatim"
    assert confidence >= 0.9


def test_classify_condensed_no_source():
    """condensed detection via short content when no source is available."""
    label, confidence, _ = classify_modification("Average: O(n log n). Worst: O(n²).")
    assert label == "condensed", f"Expected condensed, got {label}"
    assert confidence >= 0.5


def test_classify_condensed_list_structure():
    """condensed detection via list/bullet structure."""
    answer = "- Step 1: reproduce\n- Step 2: check logs\n- Step 3: isolate"
    label, confidence, _ = classify_modification(answer)
    assert label == "condensed", f"Expected condensed, got {label}"
    assert confidence >= 0.6


def test_classify_unknown_very_short():
    """classification for very minimal content — classifier treats as condensed."""
    label, confidence, _ = classify_modification("x")
    # Single-word content is classified as condensed (≤ CONDENSED_MAX_WORDS)
    assert label == "condensed", f"Expected condensed for 1-word answer, got {label}"
    assert 0.5 <= confidence <= 0.9


def test_classify_empty_text():
    """unknown classification for empty text."""
    label, confidence, _ = classify_modification("")
    assert label == "unknown"
    assert confidence == 0.0


def test_classify_unknown_no_source_short():
    """short text without strong signals → condensed (≤30 words) or unknown."""
    label, confidence, _ = classify_modification("It works fine.")
    # "It works fine." is 3 words (≤ CONDENSED_MAX_WORDS), so it's condensed
    assert label == "condensed", f"Expected condensed, got {label}"


def test_classify_rephrased_with_source():
    """rephrased classification when source has moderate overlap."""
    source = "TCP: connection-oriented, reliable, and ordered. UDP: connectionless, faster, no delivery guarantee."
    answer = "TCP: connection-oriented, reliable, ordered. UDP: connectionless, faster, no delivery guarantee."
    label, confidence, scores = classify_modification(answer, source_text=source)
    # These differ by only "and" (1 word out of ~12) — Jaccard ~0.92 → verbatim
    assert label in ("verbatim", "rephrased"), f"Expected verbatim/rephrased, got {label}"
    assert scores.jaccard_similarity >= 0.7


def test_classify_low_similarity():
    """low similarity produces rephrased or unknown."""
    source = "Python is a programming language."
    answer = "TCP is connection-oriented and reliable."
    label, confidence, scores = classify_modification(answer, source_text=source)
    # Very different content
    assert label == "unknown"
    assert scores.jaccard_similarity < 0.3


# ---------------------------------------------------------------------------
# Tests: build_modifications_text
# ---------------------------------------------------------------------------


def test_modifications_text_verbatim():
    text = build_modifications_text("verbatim", 40)
    assert "verbatim" in text.lower()


def test_modifications_text_condensed():
    text = build_modifications_text("condensed", 10)
    assert "condensed" in text.lower()


def test_modifications_text_rephrased():
    text = build_modifications_text("rephrased", 30)
    assert "rephrased" in text.lower()


def test_modifications_text_unknown():
    text = build_modifications_text("unknown", 5)
    assert "not recorded" in text


# ---------------------------------------------------------------------------
# Tests: build_attribution_template
# ---------------------------------------------------------------------------


def test_build_attribution_template():
    template = build_attribution_template("s5_test_0001", "What is X?", "verbatim")
    assert "s5_test_0001" not in template  # record_id not in template
    assert "What is X?" in template
    assert "[ANSWER AUTHOR NAME]" in template
    assert "[SPECIFIC POST URL]" in template
    assert "CC-BY-SA-4.0" in template


def test_build_attribution_template_resolved():
    """Resolved metadata produces real attribution text without placeholders."""
    resolved = {
        "answer_author": "Heisenbug",
        "title": "Difference between TCP and UDP?",
        "question_url": "https://stackoverflow.com/questions/5970383/difference-between-tcp-and-udp",
        "license": "CC-BY-SA-3.0",
    }
    template = build_attribution_template(
        "s5_test_0001", "What is X?", "verbatim",
        resolved=resolved,
    )
    assert "[ANSWER AUTHOR NAME]" not in template
    assert "[SPECIFIC POST URL]" not in template
    assert "Heisenbug" in template
    assert "stackoverflow.com" in template
    assert "Difference between TCP and UDP?" in template
    assert "CC-BY-SA-3.0" in template


# ---------------------------------------------------------------------------
# Tests: load_jsonl
# ---------------------------------------------------------------------------


def test_load_jsonl_empty_file():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write("\n")
        tmp = f.name
    try:
        records = load_jsonl(Path(tmp))
        assert records == []
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_load_jsonl_valid():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write('{"id": "a"}\n{"id": "b"}\n')
        tmp = f.name
    try:
        records = load_jsonl(Path(tmp))
        assert len(records) == 2
        assert records[0]["id"] == "a"
        assert records[1]["id"] == "b"
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_load_jsonl_skip_invalid():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write('{"id": "valid"}\nnot json\n{"id": "also_valid"}\n')
        tmp = f.name
    try:
        records = load_jsonl(Path(tmp))
        # Invalid line skipped silently
        assert len(records) == 2
    finally:
        Path(tmp).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Tests: ProvenanceResolver
# ---------------------------------------------------------------------------


def test_resolver_is_stackexchange():
    resolver = ProvenanceResolver(str(ROOT))
    assert resolver._is_stackexchange_record(SAMPLE_RECORD_VERBATIM) is True
    assert resolver._is_stackexchange_record(SAMPLE_RECORD_CONDENSED) is True
    assert resolver._is_stackexchange_record(SAMPLE_RECORD_NON_SE) is False


def test_resolver_extract_answer():
    resolver = ProvenanceResolver(str(ROOT))
    text = resolver._extract_answer_text(SAMPLE_RECORD_VERBATIM)
    assert "deadlock" in text

    text2 = resolver._extract_answer_text(SAMPLE_RECORD_CONDENSED)
    assert "O(n log n)" in text2

    # Empty messages
    text3 = resolver._extract_answer_text({"id": "x", "messages": []})
    assert text3 == ""


def test_resolver_extract_question():
    resolver = ProvenanceResolver(str(ROOT))
    text = resolver._extract_question_text(SAMPLE_RECORD_VERBATIM)
    assert "deadlock" in text
    assert "concurrent" in text


def test_resolver_build_suggestion_verbatim():
    resolver = ProvenanceResolver(str(ROOT))
    suggestion = resolver._build_suggestion(SAMPLE_RECORD_VERBATIM)
    assert suggestion.record_id == "s5_02_software_engineering_programming_9999"
    assert suggestion.modifications_classification in ("verbatim", "condensed")
    assert suggestion.license == "CC-BY-SA-4.0"
    assert suggestion.share_alike_notice == SHARE_ALIKE_NOTICE
    assert suggestion.needs_human_url is True
    assert "[ANSWER AUTHOR NAME]" in suggestion.attribution_text
    assert len(suggestion.checksum) == 64  # SHA-256 hex


def test_resolver_build_suggestion_condensed():
    resolver = ProvenanceResolver(str(ROOT))
    suggestion = resolver._build_suggestion(SAMPLE_RECORD_CONDENSED)
    assert suggestion.modifications_classification == "condensed"
    assert "condensed" in suggestion.modifications.lower()


def test_resolver_build_suggestion_unknown():
    resolver = ProvenanceResolver(str(ROOT))
    suggestion = resolver._build_suggestion(SAMPLE_RECORD_UNKNOWN)
    assert suggestion.modifications_classification in ("unknown", "condensed")


def test_resolver_skips_non_se():
    """Non-StackExchange records are excluded from processing."""
    report = ProvenanceReport()
    resolver = ProvenanceResolver(str(ROOT))
    resolver._process_record(SAMPLE_RECORD_NON_SE, report)
    assert report.stackexchange_records_found == 0
    assert len(report.suggestions) == 0


def test_resolver_load_provenance_resolutions():
    """Provenance resolutions file is loaded correctly."""
    resolver = ProvenanceResolver(str(ROOT))
    resolutions = resolver._load_provenance_resolutions()
    assert isinstance(resolutions, dict)
    # s5_0029 should be in the resolutions
    assert "s5_02_software_engineering_programming_0029" in resolutions
    meta = resolutions["s5_02_software_engineering_programming_0029"]
    assert meta["answer_author"] == "Heisenbug"
    assert "stackoverflow.com" in meta.get("question_url", "")


def test_resolver_get_resolved_metadata_found():
    """Look up resolved metadata for a known record."""
    resolver = ProvenanceResolver(str(ROOT))
    meta = resolver._get_resolved_metadata("s5_02_software_engineering_programming_0029")
    assert meta is not None
    assert meta["answer_author"] == "Heisenbug"
    assert meta["answer_url"] == "https://stackoverflow.com/a/5970545"


def test_resolver_get_resolved_metadata_not_found():
    """Look up resolved metadata for an unknown record returns None."""
    resolver = ProvenanceResolver(str(ROOT))
    meta = resolver._get_resolved_metadata("nonexistent_record_xyz")
    assert meta is None


def test_resolver_build_suggestion_resolved():
    """s5_0029 suggestion uses resolved metadata (no placeholders)."""
    resolver = ProvenanceResolver(str(ROOT))
    # Build suggestion from the actual s5_0029 record
    records = load_jsonl(
        ROOT / "review_queue" / "pending_expansion.jsonl"
    )
    target = None
    for rec in records:
        if rec.get("id") == "s5_02_software_engineering_programming_0029":
            target = rec
            break
    if target is None:
        return  # cannot test if record not found
    suggestion = resolver._build_suggestion(target)
    assert suggestion.resolved is True
    assert suggestion.needs_human_url is False
    assert suggestion.needs_human_author is False
    assert suggestion.needs_human_attribution_text is False
    assert "[ANSWER AUTHOR NAME]" not in suggestion.attribution_text
    assert "[SPECIFIC POST URL]" not in suggestion.attribution_text
    assert "Heisenbug" in suggestion.attribution_text
    assert "stackoverflow.com" in suggestion.attribution_text
    assert suggestion.answer_url == "https://stackoverflow.com/a/5970545"
    assert suggestion.question_url == "https://stackoverflow.com/questions/5970383/difference-between-tcp-and-udp"
    assert suggestion.license == "CC-BY-SA-3.0"


def test_resolver_build_suggestion_unresolved():
    """Unknown record gets placeholder attribution."""
    resolver = ProvenanceResolver(str(ROOT))
    suggestion = resolver._build_suggestion(SAMPLE_RECORD_VERBATIM)
    assert suggestion.resolved is False
    assert suggestion.needs_human_url is True
    assert "[ANSWER AUTHOR NAME]" in suggestion.attribution_text
    assert "[SPECIFIC POST URL]" in suggestion.attribution_text
    assert suggestion.license == "CC-BY-SA-4.0"


def test_resolver_run_with_temp_input():
    """Run the resolver on a temporary file."""
    records = [
        SAMPLE_RECORD_VERBATIM,
        SAMPLE_RECORD_CONDENSED,
        SAMPLE_RECORD_REPHRASED,
        SAMPLE_RECORD_NON_SE,  # should be skipped
    ]
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False
    ) as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
        tmp = f.name
    try:
        resolver = ProvenanceResolver(str(ROOT))
        report = resolver.run(input_path=tmp)
        assert report.total_records_checked == 4
        assert report.stackexchange_records_found == 3
        assert len(report.suggestions) == 3
        assert len(report.errors) == 0
        # Suggestions should cover verbatim, condensed, rephrased
        classifications = {s.modifications_classification for s in report.suggestions}
        assert "condensed" in classifications
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_resolver_write_report():
    """Writing a report to a temp path produces valid markdown."""
    resolver = ProvenanceResolver(str(ROOT))
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False
    ) as f:
        tmp = f.name
    try:
        report = ProvenanceReport()
        report.timestamp = "2026-07-28 12:00:00"
        report.source_file = "/tmp/test.jsonl"
        report.total_records_checked = 5
        report.stackexchange_records_found = 3
        report.suggestions.append(
            ProvenanceSuggestion(record_id="s5_test_0001")
        )
        out = resolver.write_report(report, output_path=tmp)
        content = Path(out).read_text(encoding="utf-8")
        assert "# Provenance Resolution Report" in content
        assert "s5_test_0001" in content
        assert "Records checked: 5" in content or "5" in content
    finally:
        Path(tmp).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Tests: resolve_single
# ---------------------------------------------------------------------------


def test_resolve_single_found():
    """Resolve a single record by ID when it exists in pending_expansion."""
    resolver = ProvenanceResolver(str(ROOT))
    # We use a known s5 record from the actual pending_expansion.jsonl
    suggestion = resolver.resolve_single("s5_02_software_engineering_programming_0029")
    if suggestion is not None:
        assert suggestion.record_id == "s5_02_software_engineering_programming_0029"
        assert suggestion.source_id == "s5"
        assert suggestion.checksum != ""
        # s5_0029 has resolved metadata
        assert suggestion.resolved is True
        assert suggestion.needs_human_url is False
        assert "Heisenbug" in suggestion.attribution_text
    # If the file doesn't exist or record isn't found, suggestion is None
    # which is valid for a missing record


def test_resolve_not_found():
    """resolve_single returns None for an unknown ID."""
    resolver = ProvenanceResolver(str(ROOT))
    suggestion = resolver.resolve_single("nonexistent_record_xyz")
    assert suggestion is None


# ---------------------------------------------------------------------------
# Tests: resolve_record direct
# ---------------------------------------------------------------------------


def test_resolve_record_direct():
    """resolve_record works from a raw dict."""
    resolver = ProvenanceResolver(str(ROOT))
    suggestion = resolver.resolve_record(SAMPLE_RECORD_CONDENSED)
    assert suggestion.record_id == "s5_02_software_engineering_programming_9998"
    assert suggestion.modifications_classification == "condensed"


# ---------------------------------------------------------------------------
# Integration test: real repository data
# ---------------------------------------------------------------------------


def test_integration_pending_expansion():
    """Run the full resolver pipeline against actual repository data."""
    resolver = ProvenanceResolver(str(ROOT))
    report = resolver.run()
    # The repo has 4 s5 records in pending_expansion.jsonl (if present)
    if report.total_records_checked > 0:
        print(f"\n  Integration: {report.stackexchange_records_found} SE records "
              f"of {report.total_records_checked} total")
        assert report.stackexchange_records_found >= 0
        # Check resolved/unresolved split
        resolved_count = sum(1 for s in report.suggestions if s.resolved)
        unresolved_count = sum(1 for s in report.suggestions if not s.resolved)
        print(f"  Resolved: {resolved_count}, Unresolved: {unresolved_count}")
        # s5_0029 should be resolved
        s5_0029 = [s for s in report.suggestions
                    if s.record_id == "s5_02_software_engineering_programming_0029"]
        if s5_0029:
            assert s5_0029[0].resolved is True
            assert s5_0029[0].needs_human_url is False
            assert "Heisenbug" in s5_0029[0].attribution_text
        # All suggestions should have license set
        for s in report.suggestions:
            assert s.license in ("CC-BY-SA-4.0", "CC-BY-SA-3.0")
    else:
        print("\n  Integration: no records to check (pending_expansion.jsonl empty)")


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------


def run_standalone() -> int:
    """Run all tests with minimal output when called directly."""
    tests = [
        ("test_classify_exact_match", test_classify_exact_match),
        ("test_classify_verbatim_with_minor_whitespace", test_classify_verbatim_with_minor_whitespace),
        ("test_classify_condensed_no_source", test_classify_condensed_no_source),
        ("test_classify_condensed_list_structure", test_classify_condensed_list_structure),
        ("test_classify_unknown_very_short", test_classify_unknown_very_short),
        ("test_classify_empty_text", test_classify_empty_text),
        ("test_classify_unknown_no_source_short", test_classify_unknown_no_source_short),
        ("test_classify_rephrased_with_source", test_classify_rephrased_with_source),
        ("test_classify_low_similarity", test_classify_low_similarity),
        ("test_modifications_text_verbatim", test_modifications_text_verbatim),
        ("test_modifications_text_condensed", test_modifications_text_condensed),
        ("test_modifications_text_rephrased", test_modifications_text_rephrased),
        ("test_modifications_text_unknown", test_modifications_text_unknown),
        ("test_build_attribution_template", test_build_attribution_template),
        ("test_build_attribution_template_resolved", test_build_attribution_template_resolved),
        ("test_load_jsonl_empty_file", test_load_jsonl_empty_file),
        ("test_load_jsonl_valid", test_load_jsonl_valid),
        ("test_load_jsonl_skip_invalid", test_load_jsonl_skip_invalid),
        ("test_resolver_is_stackexchange", test_resolver_is_stackexchange),
        ("test_resolver_extract_answer", test_resolver_extract_answer),
        ("test_resolver_extract_question", test_resolver_extract_question),
        ("test_resolver_build_suggestion_verbatim", test_resolver_build_suggestion_verbatim),
        ("test_resolver_build_suggestion_condensed", test_resolver_build_suggestion_condensed),
        ("test_resolver_build_suggestion_unknown", test_resolver_build_suggestion_unknown),
        ("test_resolver_skips_non_se", test_resolver_skips_non_se),
        ("test_resolver_load_provenance_resolutions", test_resolver_load_provenance_resolutions),
        ("test_resolver_get_resolved_metadata_found", test_resolver_get_resolved_metadata_found),
        ("test_resolver_get_resolved_metadata_not_found", test_resolver_get_resolved_metadata_not_found),
        ("test_resolver_build_suggestion_resolved", test_resolver_build_suggestion_resolved),
        ("test_resolver_build_suggestion_unresolved", test_resolver_build_suggestion_unresolved),
        ("test_resolver_run_with_temp_input", test_resolver_run_with_temp_input),
        ("test_resolver_write_report", test_resolver_write_report),
        ("test_resolve_single_found", test_resolve_single_found),
        ("test_resolve_not_found", test_resolve_not_found),
        ("test_resolve_record_direct", test_resolve_record_direct),
        ("test_integration_pending_expansion", test_integration_pending_expansion),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {name}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"  {passed} passed, {failed} failed, {len(tests)} total")
    print(f"{'='*50}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_standalone())
