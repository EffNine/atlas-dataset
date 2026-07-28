#!/usr/bin/env python3
"""
provenance_resolver.py — Automated provenance resolution helper for Phase 5E.4.

Reduces manual human completion work for provenance_pending records sourced
from StackExchange (source_id s5).  This tool:

  1. Reads records from review_queue/pending_expansion.jsonl (or any JSONL source).
  2. Identifies StackExchange (s5) records that lack specific post attribution.
  3. Classifies modification type (verbatim / condensed / rephrased / unknown)
     by analysing the assistant turn content against heuristics.
  4. Generates a per-record provenance suggestion (source URL, answer URL,
     attribution_text template, share_alike_notice, modifications, lineage).
  5. Writes a **report only** — no immutable dataset files are touched.

Usage (library):
    from provenance_resolver import ProvenanceResolver
    resolver = ProvenanceResolver(ROOT)
    report = resolver.run()
    resolver.write_report(report, output_path=...)

Usage (standalone CLI):
    python scripts/provenance_resolver.py [--input PATH] [--output PATH]
    python scripts/provenance_resolver.py --explain RECORD_ID

Usage (atlas subcommand):
    atlas resolve-provenance
    atlas resolve-provenance --input review_queue/pending_expansion.jsonl
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# StackExchange source identifiers known to the registry
STACKEXCHANGE_SOURCE_IDS: frozenset[str] = frozenset({"s5"})
STACKEXCHANGE_SOURCE_NAME = "StackExchange Code (Stack Overflow / Unix & Linux)"
STACKEXCHANGE_DUMP_URL = "https://archive.org/details/stackexchange"

# CC-BY-SA-4.0 constants
SHARE_ALIKE_NOTICE = "Distributed under the same license (CC-BY-SA-4.0)."
DEFAULT_LICENSE = "CC-BY-SA-4.0"

# Confidence thresholds for modification classification
CONFIDENCE_MAX_WORDS = 30       # very short answers likely condensed
VERBATIM_MIN_CHARS = 60        # answers at least this long may be verbatim

# Scoring constants
EXACT_MATCH_THRESHOLD = 0.95   # Jaccard word overlap → verbatim
HIGH_OVERLAP_THRESHOLD = 0.75  # Jaccard word overlap → rephrased

# Path to the provenance resolutions metadata file (relative to repo root)
PROVENANCE_RESOLUTIONS_PATH = "metadata/provenance_resolutions.json"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ModificationScores:
    """Similarity scores between a record's answer and a candidate source."""

    answer_word_count: int = 0
    jaccard_similarity: float = 0.0
    contains_technical_terms: bool = False
    has_list_structure: bool = False
    is_capitalized_sentence: bool = False


@dataclass
class ProvenanceSuggestion:
    """Single provenance suggestion for one record."""

    record_id: str
    source_id: str = "s5"
    source_name: str = STACKEXCHANGE_SOURCE_NAME
    source_url: str = STACKEXCHANGE_DUMP_URL
    answer_url: str = ""  # human must supply
    answer_author: str = ""  # human must supply
    question_url: str = ""  # specific question page URL
    license: str = DEFAULT_LICENSE
    attribution_text: str = ""
    share_alike_notice: str = SHARE_ALIKE_NOTICE
    modifications: str = ""
    modifications_classification: str = "unknown"
    modifications_confidence: float = 0.0
    lineage_parent_url: str = ""  # human must supply
    acquisition_origin: str = "Stack Exchange data dump pipeline (Phase 4B) — exact dump date not recorded"
    checksum: str = ""

    # Human-action tracking
    needs_human_url: bool = True
    needs_human_author: bool = True
    needs_human_attribution_text: bool = True
    needs_human_acquisition_date: bool = True
    resolved: bool = False  # True when human-resolved metadata was found and applied


@dataclass
class ProvenanceReport:
    """Full resolution report for one run."""

    timestamp: str = ""
    source_file: str = ""
    total_records_checked: int = 0
    stackexchange_records_found: int = 0
    suggestions: list[ProvenanceSuggestion] = field(default_factory=list)
    records_without_source: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Modification classifier
# ---------------------------------------------------------------------------


def _jaccard_word_overlap(a: str, b: str) -> float:
    """Compute Jaccard similarity on word sets of two strings."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a and not words_b:
        return 1.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union) if union else 0.0


def _count_technical_terms(text: str) -> int:
    """Count domain-specific technical terms in text."""
    terms = {
        # Programming / CS
        "algorithm", "api", "array", "async", "binary", "buffer", "cache",
        "callback", "class", "compile", "concurrency", "database", "debug",
        "deploy", "encrypt", "framework", "function", "hash", "http", "https",
        "index", "inherit", "instance", "interface", "iteration", "json",
        "library", "loop", "method", "middleware", "module", "namespace",
        "network", "null", "object", "package", "parallel", "polymorphism",
        "protocol", "queue", "recursion", "refactor", "regex", "response",
        "request", "schema", "serialize", "server", "socket", "stack",
        "string", "syntax", "tcp", "template", "thread", "token", "udp",
        "url", "variable", "vector", "virtual", "workflow", "xml", "yaml",
        # Networking
        "bandwidth", "connection-oriented", "connectionless", "dns", "firewall",
        "ip", "latency", "load-balancer", "port", "router", "ssl", "tls",
        "throughput",
        # Systems
        "daemon", "filesystem", "fifo", "kernel", "lifo", "memory",
        "mutex", "process", "semaphore",
    }
    words = set(re.findall(r"[a-z0-9_-]+", text.lower()))
    return sum(1 for t in terms if t in words)


def _has_list_structure(text: str) -> bool:
    """Check if text reads like a list/bullet-point structure."""
    lines = text.strip().split("\n")
    list_markers = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("- ", "* ", "1. ", "2. ", "3. ", "4. ", "5. ")):
            list_markers += 1
        elif re.match(r"^\d+\.\s", stripped):
            list_markers += 1
    return list_markers >= 2


def _is_capitalized_sentence(text: str) -> bool:
    """Check if text reads as a well-formed sentence starting with capital."""
    stripped = text.strip()
    if not stripped:
        return False
    # Check if it starts with uppercase and ends with sentence-ending punctuation
    return stripped[0].isupper() and stripped[-1] in ".!?"


def classify_modification(answer_text: str, *, source_text: str | None = None) -> tuple[str, float, ModificationScores]:
    """Classify how the answer text relates to its source.

    Uses content heuristics when ``source_text`` is not available (the common
    case during Phase 5E.4, where the specific post has not been identified).

    Args:
        answer_text: The assistant turn content from the record.
        source_text: Optional original post text (for exact-match comparison).

    Returns:
        Tuple of (classification_label, confidence, scores).
        Labels: ``verbatim``, ``condensed``, ``rephrased``, ``unknown``.
    """
    if not answer_text or not answer_text.strip():
        return "unknown", 0.0, ModificationScores()

    scores = ModificationScores()
    words = answer_text.split()
    scores.answer_word_count = len(words)
    scores.contains_technical_terms = _count_technical_terms(answer_text) >= 2
    scores.has_list_structure = _has_list_structure(answer_text)
    scores.is_capitalized_sentence = _is_capitalized_sentence(answer_text)

    # If we have source text, compute direct similarity
    if source_text and source_text.strip():
        scores.jaccard_similarity = _jaccard_word_overlap(answer_text, source_text)

        if scores.jaccard_similarity >= EXACT_MATCH_THRESHOLD:
            return "verbatim", scores.jaccard_similarity * 0.95, scores
        elif scores.jaccard_similarity >= HIGH_OVERLAP_THRESHOLD:
            return "rephrased", scores.jaccard_similarity * 0.8, scores
        elif scores.jaccard_similarity > 0.3:
            return "condensed", scores.jaccard_similarity * 0.6, scores
        else:
            return "unknown", max(0.1, scores.jaccard_similarity * 0.3), scores

    # No source text — use content-based heuristics
    # Very short answers are likely condensed from a longer post
    if scores.answer_word_count <= CONFIDENCE_MAX_WORDS:
        confidence = 0.6 + (0.01 * scores.answer_word_count)
        return "condensed", min(confidence, 0.85), scores

    # List/bullet structure suggests condensed from prose
    if scores.has_list_structure:
        return "condensed", 0.7, scores

    # Technical, well-formed sentence with moderate length → likely verbatim
    if scores.is_capitalized_sentence and scores.contains_technical_terms:
        if scores.answer_word_count >= 15:
            return "verbatim", 0.65, scores
        return "condensed", 0.55, scores

    # Good-length answer that reads like prose → likely rephrased
    if scores.answer_word_count >= VERBATIM_MIN_CHARS // 5:
        return "rephrased", 0.5, scores

    return "unknown", 0.3, scores


# ---------------------------------------------------------------------------
# Attribution text builder
# ---------------------------------------------------------------------------


def build_attribution_template(record_id: str, question_title: str,
                                modifications_classification: str,
                                *, resolved: dict[str, Any] | None = None) -> str:
    """Return attribution text for a record.

    When ``resolved`` is provided (a dict with keys ``answer_author``,
    ``question_url``, ``answer_url``, ``license``, ``title``), the returned
    string uses the real values.  Otherwise it returns a template with
    ``[PLACEHOLDER]`` markers for fields the human must supply.

    Args:
        record_id: Unused — retained for API compatibility.
        question_title: The extracted question text.
        modifications_classification: Unused — retained for API compatibility.
        resolved: Optional dict of human-resolved provenance metadata.

    Returns:
        A fully-formed attribution string or placeholder template.
    """
    if resolved:
        author = resolved.get("answer_author", "[ANSWER AUTHOR NAME]")
        title = resolved.get("title", question_title)
        url = resolved.get("question_url", "[SPECIFIC POST URL]")
        lic = resolved.get("license", DEFAULT_LICENSE)
        return (
            f"This content is derived from the answer by {author} "
            f"to \"{title}\" on Stack Exchange ({url}), "
            f"licensed under {lic}."
        )
    # Placeholder template for human completion
    return (
        f"This content is derived from the answer by [ANSWER AUTHOR NAME] "
        f"to \"{question_title}\" on Stack Exchange "
        f"([SPECIFIC POST URL]), "
        f"licensed under {DEFAULT_LICENSE}."
    )


def build_modifications_text(classification: str, answer_word_count: int) -> str:
    """Generate the modifications description based on classification."""
    mapping = {
        "verbatim": (
            "Used verbatim from the original Stack Exchange post."
        ),
        "condensed": (
            "Adapted from the original answer — content was condensed "
            "for training use."
        ),
        "rephrased": (
            "Adapted from the original answer — content was rephrased "
            "for clarity and training use."
        ),
        "unknown": (
            "Content sourced from Stack Exchange data dump pipeline. "
            "Specific modifications from the original post, if any, "
            "are not recorded."
        ),
    }
    return mapping.get(classification, mapping["unknown"])


# ---------------------------------------------------------------------------
# Record loader
# ---------------------------------------------------------------------------


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load a JSONL file, returning a list of parsed record dicts."""
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as e:
                print(f"Warning: invalid JSON on line {line_no}: {e}", file=sys.stderr)
    return records


# ---------------------------------------------------------------------------
# CSV / Markdown summary helpers
# ---------------------------------------------------------------------------


def _suggestion_to_row(s: ProvenanceSuggestion) -> dict[str, str]:
    """Flatten a ProvenanceSuggestion to a dict for reporting."""
    return {
        "record_id": s.record_id,
        "classification": s.modifications_classification,
        "confidence": f"{s.modifications_confidence:.2f}",
        "needs_human_url": "YES" if s.needs_human_url else "no",
        "needs_human_author": "YES" if s.needs_human_author else "no",
        "needs_human_acquisition_date": "YES" if s.needs_human_acquisition_date else "no",
        "modifications": s.modifications,
    }


def _report_to_markdown(report: ProvenanceReport) -> str:
    """Render the full report as markdown."""
    lines: list[str] = []
    lines.append("# Provenance Resolution Report")
    lines.append("")
    lines.append(f"- **Timestamp:** {report.timestamp}")
    lines.append(f"- **Source file:** {report.source_file}")
    lines.append(f"- **Records checked:** {report.total_records_checked}")
    lines.append(f"- **StackExchange records found:** {report.stackexchange_records_found}")
    lines.append("")

    if report.errors:
        lines.append("## Errors")
        for err in report.errors:
            lines.append(f"- ⚠️ {err}")
        lines.append("")

    if report.records_without_source:
        lines.append("## Records Without Source Identification")
        for rid in report.records_without_source:
            lines.append(f"- {rid}")
        lines.append("")

    if report.suggestions:
        lines.append("## Provenance Suggestions")
        lines.append("")
        resolved_count = sum(1 for s in report.suggestions if s.resolved)
        lines.append(f"- **Resolved from metadata:** {resolved_count} / {len(report.suggestions)}")
        lines.append("")
        lines.append("| Record ID | Classification | Confidence | Resolved | Needs URL | Needs Author | Modifications |")
        lines.append("|-----------|---------------|------------|----------|-----------|--------------|---------------|")
        for s in report.suggestions:
            row = _suggestion_to_row(s)
            resolved_mark = "✅" if s.resolved else "❌"
            lines.append(
                f"| {row['record_id']} | {row['classification']} | "
                f"{row['confidence']} | {resolved_mark} | {row['needs_human_url']} | "
                f"{row['needs_human_author']} | {row['modifications']} |"
            )
        lines.append("")

        lines.append("### Detailed Suggestions")
        lines.append("")
        for s in report.suggestions:
            lines.append(f"#### {s.record_id}")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(asdict(s), indent=2, ensure_ascii=False))
            lines.append("```")
            lines.append("")

    lines.append("---")
    lines.append("_Report generated by provenance_resolver.py_")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main resolver
# ---------------------------------------------------------------------------


class ProvenanceResolver:
    """Automated provenance resolution for Phase 5E.4 StackExchange records.

    Args:
        root: Path to the atlas-dataset repository root.

    Typical usage::

        resolver = ProvenanceResolver(ROOT)
        report = resolver.run()
        resolver.write_report(report)
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self._source_registry: dict[str, Any] | None = None
        self._provenance_resolutions: dict[str, Any] | None = None

    # ── Public API ──────────────────────────────────────────────────────

    def run(self, input_path: str | Path | None = None) -> ProvenanceReport:
        """Run the provenance resolver against a JSONL input file.

        Args:
            input_path: Path to the JSONL file to analyse.  Defaults to
                        ``review_queue/pending_expansion.jsonl``.

        Returns:
            A :class:`ProvenanceReport` with all suggestions and metadata.
        """
        from datetime import datetime

        report = ProvenanceReport()
        report.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if input_path is None:
            input_path = self.root / "review_queue" / "pending_expansion.jsonl"
        report.source_file = str(Path(input_path).resolve())

        records = load_jsonl(Path(input_path))
        report.total_records_checked = len(records)

        for rec in records:
            try:
                self._process_record(rec, report)
            except Exception as e:
                report.errors.append(
                    f"Error processing {rec.get('id', 'unknown')}: {e}"
                )

        return report

    def resolve_single(self, record_id: str) -> ProvenanceSuggestion | None:
        """Resolve provenance for a single record by ID.

        Searches pending_expansion.jsonl for the record and returns a
        suggestion, or ``None`` if not found.
        """
        records = load_jsonl(
            self.root / "review_queue" / "pending_expansion.jsonl"
        )
        for rec in records:
            if rec.get("id") == record_id:
                suggestion = self._build_suggestion(rec)
                return suggestion
        return None

    def resolve_record(self, record: dict[str, Any]) -> ProvenanceSuggestion:
        """Build a provenance suggestion from a raw record dict.

        Useful for callers who already have a record loaded.
        """
        return self._build_suggestion(record)

    def write_report(self, report: ProvenanceReport,
                     output_path: str | Path | None = None) -> Path:
        """Write the provenance report to a file.

        Args:
            report: The report to write.
            output_path: Destination path.  Defaults to
                         ``tmp/provenance_resolution_report.md``.

        Returns:
            The path the report was written to.
        """
        if output_path is None:
            output_path = self.root / "tmp" / "provenance_resolution_report.md"

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(_report_to_markdown(report), encoding="utf-8")
        return output

    # ── Internal ───────────────────────────────────────────────────────

    def _load_source_registry(self) -> dict[str, Any]:
        """Lazy-load the source registry."""
        if self._source_registry is None:
            path = self.root / "metadata" / "source_registry.json"
            if path.exists():
                self._source_registry = json.loads(path.read_text(encoding="utf-8"))
            else:
                self._source_registry = {"sources": []}
        # Safe: always populated above
        return self._source_registry  # type: ignore[return-value]

    def _load_provenance_resolutions(self) -> dict[str, Any]:
        """Lazy-load the provenance resolutions metadata file.

        Returns the ``resolutions`` dict keyed by record ID, or empty dict
        if the file doesn't exist or is unparseable.
        """
        if self._provenance_resolutions is not None:
            return self._provenance_resolutions

        path = self.root / PROVENANCE_RESOLUTIONS_PATH
        if not path.exists():
            self._provenance_resolutions = {}
            return self._provenance_resolutions

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._provenance_resolutions = data.get("resolutions", {})
        except (json.JSONDecodeError, OSError):
            self._provenance_resolutions = {}
        return self._provenance_resolutions  # type: ignore[return-value]

    def _get_resolved_metadata(self, record_id: str) -> dict[str, Any] | None:
        """Look up human-resolved provenance metadata for a record.

        Returns the resolution dict (with keys ``question_url``,
        ``answer_url``, ``answer_author``, ``license``, ``title``, etc.)
        or ``None`` if no resolution has been recorded for this record.
        """
        resolutions = self._load_provenance_resolutions()
        return resolutions.get(record_id)

    def _is_stackexchange_record(self, rec: dict[str, Any]) -> bool:
        """Check if a record originates from a StackExchange source."""
        source_id = rec.get("source_id", "")
        source_name = (rec.get("source_name", "") or "").lower()
        if source_id in STACKEXCHANGE_SOURCE_IDS:
            return True
        if "stackexchange" in source_name or "stack overflow" in source_name:
            return True
        return False

    def _extract_answer_text(self, rec: dict[str, Any]) -> str:
        """Extract the assistant's answer from a record's messages.

        Falls back to ``canonical_answer`` if the messages array is
        unavailable or doesn't contain an assistant turn.
        """
        # Try canonical_answer first (full knowledge object schema)
        ca = rec.get("canonical_answer")
        if ca and isinstance(ca, str) and ca.strip():
            return ca.strip()

        # Fall back to messages array
        messages = rec.get("messages", [])
        for msg in messages:
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    return content.strip()
        return ""

    def _extract_question_text(self, rec: dict[str, Any]) -> str:
        """Extract the user's question from a record's messages."""
        messages = rec.get("messages", [])
        for msg in messages:
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    return content.strip()
        return ""

    def _build_suggestion(self, rec: dict[str, Any]) -> ProvenanceSuggestion:
        """Build a ProvenanceSuggestion for a single record."""
        record_id = rec.get("id", "unknown")
        answer_text = self._extract_answer_text(rec)
        question_text = self._extract_question_text(rec)

        # Classify modification type
        classification, confidence, scores = classify_modification(answer_text)

        # Build suggestion fields
        modifications_text = build_modifications_text(classification, scores.answer_word_count)

        # Compute checksum for the record
        checksum = self._compute_checksum(rec)

        # Check for human-resolved provenance metadata
        resolved = self._get_resolved_metadata(record_id)
        is_resolved = resolved is not None

        if is_resolved:
            # Use resolved values — all provenance data is complete
            resolved_license = resolved.get("license", DEFAULT_LICENSE)
            resolved_share_alike = (
                f"Distributed under the same license ({resolved_license})."
                if resolved_license != DEFAULT_LICENSE
                else SHARE_ALIKE_NOTICE
            )
            attribution_text = build_attribution_template(
                record_id, question_text, classification,
                resolved=resolved,
            )
            suggestion = ProvenanceSuggestion(
                record_id=record_id,
                source_url=resolved.get("question_url", STACKEXCHANGE_DUMP_URL),
                answer_url=resolved.get("answer_url", ""),
                answer_author=resolved.get("answer_author", ""),
                question_url=resolved.get("question_url", ""),
                license=resolved_license,
                attribution_text=attribution_text,
                share_alike_notice=resolved_share_alike,
                modifications=modifications_text,
                modifications_classification=classification,
                modifications_confidence=confidence,
                lineage_parent_url=resolved.get("question_url", ""),
                acquisition_origin=(
                    f"Acquisition method: Stack Exchange data dump pipeline "
                    f"(Phase 4B). Specific post identified via human review "
                    f"on {resolved.get('resolved_date', 'unknown date')}."
                ),
                checksum=checksum,
                needs_human_url=False,
                needs_human_author=False,
                needs_human_attribution_text=False,
                needs_human_acquisition_date=False,
                resolved=True,
            )
        else:
            # No resolved metadata — use placeholder template
            attribution_template = build_attribution_template(
                record_id, question_text, classification,
            )
            suggestion = ProvenanceSuggestion(
                record_id=record_id,
                modifications=modifications_text,
                modifications_classification=classification,
                modifications_confidence=confidence,
                attribution_text=attribution_template,
                checksum=checksum,
                needs_human_url=True,
                needs_human_author=True,
                needs_human_attribution_text=True,
                needs_human_acquisition_date=True,
                resolved=False,
            )

        return suggestion

    def _process_record(self, rec: dict[str, Any],
                        report: ProvenanceReport) -> None:
        """Process a single record, mutating the report in place."""
        record_id = rec.get("id", "unknown")

        # Skip non-StackExchange records
        if not self._is_stackexchange_record(rec):
            return

        report.stackexchange_records_found += 1

        # Check if we have source metadata
        source_id = rec.get("source_id", "")
        source_name = rec.get("source_name", "")
        if not source_id and not source_name:
            report.records_without_source.append(record_id)
            report.errors.append(
                f"{record_id}: no source_id or source_name — cannot resolve provenance"
            )
            return

        # Build suggestion
        suggestion = self._build_suggestion(rec)
        report.suggestions.append(suggestion)

    @staticmethod
    def _compute_checksum(record: dict[str, Any]) -> str:
        """Compute SHA-256 of a record's JSON representation."""
        import hashlib
        raw = json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Standalone CLI
# ---------------------------------------------------------------------------


def cli_main(args: list[str] | None = None) -> int:
    """CLI entry point for ``python scripts/provenance_resolver.py``."""
    import argparse
    from datetime import datetime

    if args is None:
        args = sys.argv[1:]

    ap = argparse.ArgumentParser(
        prog="provenance_resolver",
        description="Phase 5E.4 automated provenance resolution for StackExchange records.",
    )
    ap.add_argument("--input", default=None,
                    help="JSONL input file (default: review_queue/pending_expansion.jsonl)")
    ap.add_argument("--output", default=None,
                    help="Report output path (default: tmp/provenance_resolution_report.md)")
    ap.add_argument("--explain", default=None,
                    help="Resolve provenance for a single record ID and print details")
    ap.add_argument("--json", action="store_true",
                    help="Output suggestions as JSON instead of markdown report")

    parsed = ap.parse_args(args)

    # Detect repo root
    root = _guess_root()

    resolver = ProvenanceResolver(root)

    # Single-record explain
    if parsed.explain:
        suggestion = resolver.resolve_single(parsed.explain)
        if suggestion is None:
            print(f"Record '{parsed.explain}' not found in pending_expansion.jsonl.",
                  file=sys.stderr)
            return 1
        if parsed.json:
            print(json.dumps(asdict(suggestion), indent=2, ensure_ascii=False))
        else:
            print(json.dumps(asdict(suggestion), indent=2, ensure_ascii=False))
        return 0

    # Full run
    report = resolver.run(input_path=parsed.input)
    out_path = resolver.write_report(report, output_path=parsed.output)

    # Print summary to stderr
    resolved_count = sum(1 for s in report.suggestions if s.resolved)
    summary = (
        f"Provenance resolution complete.\n"
        f"  Records checked:     {report.total_records_checked}\n"
        f"  StackExchange found: {report.stackexchange_records_found}\n"
        f"  Suggestions made:    {len(report.suggestions)}\n"
        f"  Resolved from file:  {resolved_count}\n"
        f"  Errors:              {len(report.errors)}\n"
        f"  Report written to:   {out_path}\n"
    )

    if parsed.json:
        # JSON mode: print suggestions as JSON array to stdout
        print(json.dumps(
            [asdict(s) for s in report.suggestions],
            indent=2, ensure_ascii=False,
        ))
        print(summary, file=sys.stderr)
    else:
        print(summary)

    if report.errors:
        for err in report.errors:
            print(f"  ⚠ {err}", file=sys.stderr)

    return 0 if not report.errors else 1


def _guess_root() -> Path:
    """Walk up from CWD or script dir to find the atlas-dataset repo root."""
    candidates = [
        Path.cwd(),
        Path(__file__).resolve().parent.parent,
    ]
    for c in candidates:
        if (c / "scripts" / "atlas.py").exists():
            return c
        if (c.parent / "scripts" / "atlas.py").exists():
            return c.parent
    for c in candidates:
        for ancestor in [c] + list(c.parents):
            if (ancestor / "scripts" / "atlas.py").exists():
                return ancestor
    raise RuntimeError(
        "Cannot determine atlas-dataset root. "
        "Run from within the repository or set ATLAS_ROOT."
    )


# ---------------------------------------------------------------------------
# atlas.py subcommand integration (called from atlas.py)
# ---------------------------------------------------------------------------


def cmd_resolve_provenance(argv: list[str]) -> int:
    """``atlas resolve-provenance`` subcommand handler."""
    return cli_main(argv)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(cli_main())
