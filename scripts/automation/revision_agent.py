#!/usr/bin/env python3
"""Revision agent — production implementation (v1.3).

Generates actionable revision proposals from quality evaluation findings.

The agent:
  1. Reads curated dataset records.
  2. Evaluates each record with the quality engine (``quality_score.evaluate_record``).
  3. Maps low dimension scores and quality flags to structured revision proposals
     organised by revision category (completeness, technical_depth, clarity,
     usefulness).
  4. Preserves original content — never modifies dataset records.
  5. Writes proposals to ``metadata/pipeline_revisions/`` for audit and human review.

Flow::

    QualityAgent  ── scores ──▶  RevisionAgent  ── proposals ──▶  ValidationAgent
                                       │
                                       ▼
                              metadata/pipeline_revisions/<id>.json

Revision categories:
  - **completeness**: missing explanation, insufficient detail, missing context
  - **technical_depth**: missing mechanism explanation, missing examples,
    missing trade-offs
  - **clarity**: unclear wording, poor structure
  - **usefulness**: insufficient practical guidance
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base_agent import BaseAgent, AgentResult, AgentStatus


# ---------------------------------------------------------------------------
# Revision proposal data classes
# ---------------------------------------------------------------------------


@dataclass
class RevisionProposal:
    """A single actionable revision for one record area."""

    area: str  # completeness | technical_depth | clarity | usefulness
    problem: str
    suggestion: str


@dataclass
class RecordRevision:
    """Complete revision analysis for one record."""

    record_id: str
    status: str  # PROPOSAL_CREATED | PASS | SKIPPED
    quality_score: int
    issues_detected: list[str] = field(default_factory=list)
    revision_proposals: list[dict[str, str]] = field(default_factory=list)
    confidence: float = 0.0
    requires_human_review: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "status": self.status,
            "quality_score": self.quality_score,
            "issues_detected": self.issues_detected,
            "revision_proposals": self.revision_proposals,
            "confidence": round(self.confidence, 3),
            "requires_human_review": self.requires_human_review,
        }


# ---------------------------------------------------------------------------
# Dimension → revision category mapping
#
# Each mapping entry defines:
#   - dim:       The quality_score dimension name
#   - threshold: Score below which a proposal is generated
#   - area:      Revision category
#   - problems:  Problem templates keyed by flag or reason prefix
#   - fallback:  Default problem/suggestion when no specific match
# ---------------------------------------------------------------------------

_DIMENSION_MAP: list[dict[str, Any]] = [
    {
        "dim": "completeness",
        "threshold": 0.5,
        "area": "completeness",
        "indicators": [
            {
                "trigger": lambda s, f, r: r and "empty" in r.lower(),
                "problem": "Answer is empty or contains no substantive content.",
                "suggestion": "Provide a complete answer with explanation, context, and supporting details.",
            },
            {
                "trigger": lambda s, f, r: r and "word" in r.lower() and int(_extract_words(r)) < 12,
                "problem": "Answer is too short to address the question adequately.",
                "suggestion": "Expand the answer with more detail, context, and supporting information.",
            },
        ],
        "fallback": {
            "problem": "Answer lacks sufficient completeness for the question asked.",
            "suggestion": (
                "Add more detail: explain the concept fully, provide context, "
                "and cover the key aspects the question expects."
            ),
        },
    },
    {
        "dim": "technical_correctness",
        "threshold": 0.55,
        "area": "technical_depth",
        "indicators": [
            {
                "trigger": lambda s, f, r: "unclosed code fence" in r.lower(),
                "problem": "Code block has unbalanced fence markers (missing opening or closing ```).",
                "suggestion": "Ensure all code blocks have matching opening and closing ``` delimiters.",
            },
            {
                "trigger": lambda s, f, r: "keyword_hits=0" in r.lower() or "keyword_hits=1" in r.lower() if r else False,
                "problem": "Answer lacks domain-specific technical terms or code examples.",
                "suggestion": "Include relevant technical terminology, code snippets, or concrete values to ground the explanation.",
            },
            {
                "trigger": lambda s, f, r: "has_specific_values=False" in r.lower() if r else False,
                "problem": "Answer is too abstract — missing concrete numbers, parameters, or specific references.",
                "suggestion": "Add specific values, parameters, or concrete references to make the answer more technically precise.",
            },
        ],
        "fallback": {
            "problem": "Technical depth is insufficient for the topic.",
            "suggestion": (
                "Deepen the technical explanation: explain how and why the mechanism works, "
                "include relevant examples, and discuss trade-offs where applicable."
            ),
        },
    },
    {
        "dim": "clarity",
        "threshold": 0.55,
        "area": "clarity",
        "indicators": [
            {
                "trigger": lambda s, f, r: "ALLCAPS" in r if r else False,
                "problem": "Answer contains excessive ALLCAPS text, reducing readability.",
                "suggestion": "Replace ALLCAPS text with normal case for better readability.",
            },
            {
                "trigger": lambda s, f, r: r and "no sentences" in r.lower(),
                "problem": "Answer has no complete sentences — it may be fragmentary or empty.",
                "suggestion": "Write in complete sentences with proper structure and punctuation.",
            },
            {
                "trigger": lambda s, f, r: r and "avg sentence" in r.lower() if r else False,
                "problem": "Sentence structure could be improved for clarity.",
                "suggestion": (
                    "Vary sentence length and structure. Break overly long sentences into "
                    "shorter ones, and connect ideas with clear transitions."
                ),
            },
        ],
        "fallback": {
            "problem": "Answer lacks clarity or is poorly structured.",
            "suggestion": (
                "Restructure the answer with clear paragraphs, logical flow, "
                "and transitions between ideas."
            ),
        },
    },
    {
        "dim": "usefulness",
        "threshold": 0.5,
        "area": "usefulness",
        "indicators": [
            {
                "trigger": lambda s, f, r: not s.get("user_imperative", True) if isinstance(s, dict) else True,
                "problem": "Response does not directly address an actionable user need.",
                "suggestion": "Focus on answering the specific question with practical, actionable guidance.",
            },
        ],
        "fallback": {
            "problem": "Answer lacks practical or actionable guidance.",
            "suggestion": (
                "Add concrete steps, examples, or actionable recommendations "
                "that the user can directly apply."
            ),
        },
    },
]

# Quality flag → revision proposal mapping
_FLAG_MAP: dict[str, tuple[str, str, str]] = {
    "very_short_answer": (
        "completeness",
        "Answer is extremely short — likely insufficient for any meaningful instruction.",
        "Provide a thorough answer with explanation, examples, and complete coverage of the topic.",
    ),
    "boilerplate_opener": (
        "clarity",
        "Answer begins with a generic boilerplate phrase ('Sure, here is...', 'As an AI...'), reducing originality.",
        "Remove boilerplate openers and start with the substance of the answer directly.",
    ),
    "low_relevance": (
        "technical_depth",
        "Answer lacks relevance signals for its assigned category.",
        "Ensure the answer uses domain-appropriate terminology and addresses the category-specific topic.",
    ),
    "unclosed_code_fence": (
        "technical_depth",
        "Code block markers are unbalanced — this will render incorrectly.",
        "Fix the unbalanced code fence markers (```) so the code block renders correctly.",
    ),
    "low_confidence": (
        "completeness",
        "Quality evaluation had low confidence due to insufficient evidence.",
        "Add more content, context, and detail so the answer can be properly evaluated.",
    ),
}


def _extract_words(reason: str) -> str:
    """Extract the word count from a reason string like 'answer 12 words...'."""
    import re
    m = re.search(r"(\d+)\s+words?", reason)
    return m.group(1) if m else "0"


# ---------------------------------------------------------------------------
# Revision agent
# ---------------------------------------------------------------------------


class RevisionAgent(BaseAgent):
    """Production revision proposal agent (v1.3).

    Generates structured revision proposals by analysing quality evaluation
    results for each record.  Proposals are written to
    ``metadata/pipeline_revisions/`` for audit and human review.

    Config keys:
        curated_path:   Override the default dataset path.
        min_score:      Quality score threshold for automatic PASS
                        (default 7).  Records below this threshold generate
                        proposals.
        dim_threshold:  Per-dimension score threshold for proposal
                        generation (default 0.5).
        output_dir:     Override the revision proposals output directory
                        (default ``metadata/pipeline_revisions``).
        generate_all:   If ``True`` (default), generate proposals for all
                        records regardless of score.  If ``False``, only
                        generate proposals for records below ``min_score``.

    Args:
        root:   Path to the atlas-dataset repository root.
        config: Optional configuration dict (see above).
    """

    name: str = "revision_agent"
    description: str = (
        "Generates revision proposals from quality evaluation — "
        "completeness, technical_depth, clarity, usefulness"
    )

    def __init__(
        self,
        root: str | Path,
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(root, config)
        cfg = config or {}
        self.min_score = cfg.get("min_score", 7)
        self.dim_threshold = cfg.get("dim_threshold", 0.5)
        self.generate_all = cfg.get("generate_all", True)
        self._output_dir_override = cfg.get("output_dir")

        # Ensure scripts/ is on sys.path for quality engine import
        scripts = str(self.root / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)

    # ── Public API ─────────────────────────────────────────────────────

    @property
    def output_dir(self) -> Path:
        if self._output_dir_override:
            return Path(self._output_dir_override).resolve()
        return self.root / "metadata" / "pipeline_revisions"

    # ── Agent execution ────────────────────────────────────────────────

    def execute(self, context: dict[str, Any] | None = None) -> AgentResult:
        """Run revision analysis against a curated dataset file.

        The agent reads records, evaluates quality, generates revision
        proposals for records with identified issues, and persists the
        proposals to disk.

        Args:
            context: Optional dict with keys:
                - ``pipeline_id``: Used to scope output files.
                - ``state``: Current pipeline state (unused in v1.3).

        Returns:
            ``AgentResult`` with per-record revision proposals and
            aggregate summary.
        """
        pipeline_id = (context or {}).get("pipeline_id", "default")

        path = self._resolve_path()
        if path is None:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SKIPPED,
                summary="No dataset file found for revision analysis",
                data={"searched": self._list_curated_files()},
            )

        # ── 1. Load records ────────────────────────────────────────────
        records, parse_errors = self._parse_jsonl(path)
        if not records and parse_errors:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILED,
                summary=f"All lines failed JSON parsing at {path}",
                data={"checked_path": str(path), "parse_errors": parse_errors},
                errors=parse_errors,
            )

        if not records:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SKIPPED,
                summary="No records to analyse",
                data={"checked_path": str(path), "total_records": 0},
            )

        # ── 2. Import quality engine ───────────────────────────────────
        try:
            qee = _import("quality_score")
        except ImportError as exc:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILED,
                summary=f"Cannot import quality_score engine: {exc}",
                errors=[str(exc)],
            )

        # ── 3. Analyse every record ────────────────────────────────────
        all_revisions: list[RecordRevision] = []
        proposal_counts: dict[str, int] = {}
        records_with_proposals: list[str] = []

        for rec in records:
            rid = rec.get("id", "<no-id>")
            ev = qee.evaluate_record(rec)
            qs = ev["quality_score"]
            dims = ev.get("dimensions", {})
            flags = ev.get("flags", [])
            rationale = ev.get("rationale", [])
            conf = ev.get("confidence", 0.0)

            # Build a map dim_name → reason for quick lookup
            reasons: dict[str, str] = {}
            for r in rationale:
                reasons[r.get("dimension", "")] = r.get("reason", "")

            # Determine if this record needs revision
            score_low = qs < self.min_score
            dims_low = {
                dim: score
                for dim, score in dims.items()
                if score < self.dim_threshold
            }

            if not self.generate_all and not score_low and not dims_low and not flags:
                all_revisions.append(
                    RecordRevision(
                        record_id=rid,
                        status="PASS",
                        quality_score=qs,
                        confidence=conf,
                        requires_human_review=False,
                    )
                )
                continue

            # Generate proposals
            proposals: list[dict[str, str]] = []
            issues: list[str] = []

            # Proposals from dimension scores
            for mapping in _DIMENSION_MAP:
                dim_name = mapping["dim"]
                dim_score = dims.get(dim_name, 1.0)
                if dim_score >= mapping["threshold"]:
                    continue

                # Check specific indicators
                matched = False
                for indicator in mapping["indicators"]:
                    try:
                        if indicator["trigger"](dims, flags, reasons.get(dim_name)):
                            proposals.append({
                                "area": mapping["area"],
                                "problem": indicator["problem"],
                                "suggestion": indicator["suggestion"],
                            })
                            issues.append(f"{mapping['area']}: {indicator['problem']}")
                            matched = True
                            break
                    except Exception:
                        continue

                if not matched:
                    proposals.append({
                        "area": mapping["area"],
                        "problem": mapping["fallback"]["problem"],
                        "suggestion": mapping["fallback"]["suggestion"],
                    })
                    issues.append(f"{mapping['area']}: {mapping['fallback']['problem']}")

            # Proposals from quality flags
            for flag in flags:
                if flag in _FLAG_MAP:
                    area, problem, suggestion = _FLAG_MAP[flag]
                    # Avoid duplicate proposals for the same area+problem
                    dup = any(
                        p["area"] == area and p["problem"] == problem
                        for p in proposals
                    )
                    if not dup:
                        proposals.append({
                            "area": area,
                            "problem": problem,
                            "suggestion": suggestion,
                        })
                        issues.append(f"{area}: {problem}")

            # De-duplicate by (area, problem)
            seen: set[tuple[str, str]] = set()
            deduped_proposals: list[dict[str, str]] = []
            for p in proposals:
                key = (p["area"], p["problem"])
                if key not in seen:
                    seen.add(key)
                    deduped_proposals.append(p)

            revision = RecordRevision(
                record_id=rid,
                status="PROPOSAL_CREATED",
                quality_score=qs,
                issues_detected=issues,
                revision_proposals=deduped_proposals,
                confidence=conf,
                requires_human_review=len(deduped_proposals) > 0,
            )
            all_revisions.append(revision)

            if deduped_proposals:
                records_with_proposals.append(rid)
                for p in deduped_proposals:
                    area = p["area"]
                    proposal_counts[area] = proposal_counts.get(area, 0) + 1

        # ── 4. Persist proposals ───────────────────────────────────────
        output_file = self._write_proposals(pipeline_id, all_revisions)

        # ── 5. Build result data ───────────────────────────────────────
        total_proposals = sum(len(r.revision_proposals) for r in all_revisions)
        total_issues = sum(len(r.issues_detected) for r in all_revisions)
        passed_count = sum(1 for r in all_revisions if r.status == "PASS")
        proposal_count = sum(1 for r in all_revisions if r.status == "PROPOSAL_CREATED")

        data: dict[str, Any] = {
            "checked_path": str(path),
            "total_records": len(records),
            "parse_errors": parse_errors,
            "revision_engine": "revision_agent.py",
            "thresholds": {
                "min_score": self.min_score,
                "dim_threshold": self.dim_threshold,
                "generate_all": self.generate_all,
            },
            "aggregate": {
                "passed_count": passed_count,
                "proposal_count": proposal_count,
                "total_proposals": total_proposals,
                "total_issues": total_issues,
                "records_with_proposals": sorted(records_with_proposals),
                "proposals_by_area": dict(
                    sorted(proposal_counts.items(), key=lambda x: -x[1])
                ),
            },
            "proposals_path": str(output_file),
            "records": [r.to_dict() for r in all_revisions],
        }

        # ── 6. Determine status ────────────────────────────────────────
        errors: list[str] = []
        warnings: list[str] = []

        if parse_errors:
            errors.append(f"{len(parse_errors)} line(s) failed JSON parsing")

        if proposal_count > 0:
            warnings.append(
                f"{proposal_count} record(s) have revision proposals "
                f"({total_proposals} total proposals)"
            )

        # Revision is advisory — generates proposals but doesn't block
        if errors:
            status = AgentStatus.FAILED
            summary = f"Revision analysis FAILED: {'; '.join(errors)}"
        elif proposal_count > 0:
            status = AgentStatus.PASSED
            summary = (
                f"Revision analysis complete: {passed_count} passed, "
                f"{proposal_count} with proposals ({total_proposals} total proposals "
                f"across {len(proposal_counts)} categories)"
            )
        else:
            status = AgentStatus.PASSED
            summary = (
                f"Revision analysis: all {passed_count} record(s) passed — "
                f"no revisions proposed"
            )

        return AgentResult(
            agent_name=self.name,
            status=status,
            summary=summary,
            data=data,
            errors=errors,
            warnings=warnings,
        )

    # ── Persistence ───────────────────────────────────────────────────

    def _write_proposals(
        self,
        pipeline_id: str,
        revisions: list[RecordRevision],
    ) -> Path:
        """Write revision proposals to a JSON file.

        Writes to ``metadata/pipeline_revisions/<pipeline_id>.json``.

        Returns:
            The path to the written file.
        """
        out_dir = self.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / f"{pipeline_id}.json"

        data = {
            "pipeline_id": pipeline_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_records": len(revisions),
            "revision_engine": "revision_agent.py",
            "records": [r.to_dict() for r in revisions],
        }
        output_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return output_path

    # ── Path resolution ───────────────────────────────────────────────

    def _resolve_path(self) -> Path | None:
        """Resolve the dataset path from config or discover it."""
        curated_path = self.config.get("curated_path")
        if curated_path:
            p = Path(curated_path)
            return p if p.exists() else None

        candidates = [
            self.root / "curated" / "v0.1" / "pilot_candidates.jsonl",
            self.root / "curated" / "v0.1" / "atlas_synthetic_test_v0.1.jsonl",
            self.root / "curated" / "v0.1" / "atlas_v0.1.jsonl",
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def _list_curated_files(self) -> list[str]:
        curated = self.root / "curated"
        if not curated.exists():
            return []
        return sorted(
            str(p.relative_to(self.root))
            for p in curated.rglob("*.jsonl")
            if p.is_file()
        )

    # ── Parsing ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
        records: list[dict[str, Any]] = []
        parse_errors: list[str] = []
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as e:
                parse_errors.append(f"Line {line_no}: {e}")
        return records, parse_errors


def _import(target: str):
    """Lazy-import a module from the scripts directory."""
    return __import__(target)
