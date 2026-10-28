"""Dual-mode SFT semantic review contract (human | ai).

Implements the normalized review/decision contract shared by both review
modes so human decisions (review_ui.py) and AI reviews (ai_reviewer.py)
are directly comparable and auditable.

Design rules (per docs/expert_pilot_6500_sonnet5_review_execution_plan_v0.1.md
and the dual-mode SFT review architecture):

- Deterministic gates (sft_view.gate_record) always run BEFORE semantic
  review, in both modes. Semantic review can never re-accept a record the
  deterministic gates rejected.
- Decision vocabulary: accept | review | reject. Legacy human verdicts map
  KEEP->accept, REVISE->review, REJECT->reject.
- Criteria are scored 1..5 (matching the existing human dimension rubric);
  the top-level quality_score is 0..10.
- Uncertainty NEVER becomes acceptance by default: low confidence,
  conflicting criteria, or any risk flag routes to review/reject.
- Reviewer failures produce explicit failure results routed to `review`
  (never PASS) — see reviewer_failure_result().
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .util import sha256_hex

REVIEW_MODE_HUMAN = "human"
REVIEW_MODE_AI = "ai"
REVIEW_MODES = (REVIEW_MODE_HUMAN, REVIEW_MODE_AI)

REVIEW_VERSION = "sft-review-v0.1"

DECISION_ACCEPT = "accept"
DECISION_REVIEW = "review"
DECISION_REJECT = "reject"
DECISIONS = (DECISION_ACCEPT, DECISION_REVIEW, DECISION_REJECT)

# Legacy verdict vocabulary (review_ui.py + sonnet5 execution plan).
LEGACY_TO_DECISION = {"KEEP": DECISION_ACCEPT, "REVISE": DECISION_REVIEW,
                      "REJECT": DECISION_REJECT}
DECISION_TO_LEGACY = {v: k for k, v in LEGACY_TO_DECISION.items()}

# --- Rubric criteria (scored 1..5, mirroring the human dimension rubric) ---
GENERIC_CRITERIA = (
    "correctness",            # verifiable correctness of solution vs problem
    "relevance",              # answer addresses the actual question/task
    "completeness",           # material aspects covered; nothing essential missing
    "instruction_following",  # follows the user's stated constraints/format
    "factual_consistency",    # internally consistent, no self-contradiction
    "security_safety",        # no unsafe/insecure/credential-leaking content
    "overall_quality",        # aggregate training-suitability judgment
)

AGENTIC_CRITERIA = GENERIC_CRITERIA + (
    "task_completion",         # did the trajectory actually complete the task
    "tool_use_correctness",    # commands/tools appropriate and correctly formed
    "observation_consistency", # observations follow plausibly from actions
    "trajectory_coherence",    # steps connect logically; no broken loops
    "final_answer_correctness",# closing assistant turn is a valid resolution
)

AIML_CRITERIA = GENERIC_CRITERIA + (
    "scientific_consistency",  # claims consistent with established ML/AI knowledge
    "context_preservation",    # stays within scope of the provided context
    "answer_validity",         # final answer is technically valid
    "unsupported_claims",      # 5 = all claims supported; 1 = most unsupported
)

CRITERIA_BY_CATEGORY = {
    "agentic": AGENTIC_CRITERIA,
    "aiml": AIML_CRITERIA,
}
DEFAULT_CATEGORY = "generic"


def criteria_for_category(category: str) -> tuple[str, ...]:
    """Required criteria tuple for an SFT category."""
    return CRITERIA_BY_CATEGORY.get(category, GENERIC_CRITERIA)


# Risk flags that make a record untrainable regardless of scores.
BLOCKING_RISK_FLAGS = frozenset({
    "security_concern",
    "credential_exposure",
    "unsafe_content",
    "license_issue",
    "provenance_failure",
})


@dataclass
class ReviewThresholds:
    """Explicit decision thresholds (configurable; defaults documented)."""

    reject_max_criterion: int = 2   # any criterion <= this => reject
    reject_max_quality: int = 5     # quality_score <= this => reject
    accept_min_quality: int = 8     # quality_score >= this required to accept
    accept_min_confidence: float = 0.7
    # max-min criterion spread >= this => review (uncertain/conflicting
    # signals). With the reject floor at 2 this only fires when no single
    # dimension fails outright but scores still disagree (e.g. 5 vs 3).
    conflict_spread: int = 2

    def as_dict(self) -> dict:
        return {
            "reject_max_criterion": self.reject_max_criterion,
            "reject_max_quality": self.reject_max_quality,
            "accept_min_quality": self.accept_min_quality,
            "accept_min_confidence": self.accept_min_confidence,
            "conflict_spread": self.conflict_spread,
        }


DEFAULT_THRESHOLDS = ReviewThresholds()


def decide(criteria: dict[str, int], quality_score: int, confidence: float,
           risk_flags: list[str],
           thresholds: ReviewThresholds = DEFAULT_THRESHOLDS) -> dict:
    """Apply explicit decision rules. Returns {"decision", "reasons"}.

    Order matters: reject conditions first, then review conditions;
    only clearly high-quality + high-confidence records are accepted.
    """
    reasons: list[str] = []
    blocking = [f for f in risk_flags if f in BLOCKING_RISK_FLAGS]
    if blocking:
        return {"decision": DECISION_REJECT,
                "reasons": [f"blocking_risk_flag:{f}" for f in blocking]}
    values = [int(v) for v in criteria.values()]
    if values:
        weak = [k for k, v in criteria.items()
                if int(v) <= thresholds.reject_max_criterion]
        if weak:
            return {"decision": DECISION_REJECT,
                    "reasons": [f"criterion_below_floor:{k}" for k in weak]}
        spread = max(values) - min(values)
        if spread >= thresholds.conflict_spread:
            reasons.append(f"criteria_conflict_spread:{spread}")
    if quality_score <= thresholds.reject_max_quality:
        return {"decision": DECISION_REJECT,
                "reasons": [f"quality_score_below_reject_floor:{quality_score}"]}
    if quality_score < thresholds.accept_min_quality:
        reasons.append(f"quality_below_accept_threshold:{quality_score}")
    if confidence < thresholds.accept_min_confidence:
        reasons.append(f"confidence_below_threshold:{confidence:.2f}")
    non_blocking = [f for f in risk_flags if f not in BLOCKING_RISK_FLAGS]
    for flag in non_blocking:
        reasons.append(f"risk_flag:{flag}")
    if reasons:
        return {"decision": DECISION_REVIEW, "reasons": reasons}
    return {"decision": DECISION_ACCEPT, "reasons": ["meets_all_thresholds"]}


def input_hash(record: dict) -> str:
    """Deterministic SHA-256 of the canonical record content."""
    return sha256_hex(json.dumps(record, sort_keys=True, ensure_ascii=False))


def validate_review_result(result: dict, *, mode: str | None = None) -> list[str]:
    """Validate a normalized review result. Empty list == valid.

    Strict for ai mode; confidence is optional (None allowed) for human mode.
    """
    problems: list[str] = []
    m = mode or result.get("review_mode")
    if m not in REVIEW_MODES:
        problems.append("invalid:review_mode")
    if result.get("decision") not in DECISIONS:
        problems.append("invalid:decision")
    q = result.get("quality_score")
    if not isinstance(q, int) or isinstance(q, bool) or not 0 <= q <= 10:
        problems.append("invalid:quality_score")
    conf = result.get("confidence")
    if m == REVIEW_MODE_AI:
        if not isinstance(conf, (int, float)) or isinstance(conf, bool) \
                or not 0.0 <= float(conf) <= 1.0:
            problems.append("invalid:confidence")
    elif conf is not None and (
            not isinstance(conf, (int, float)) or isinstance(conf, bool)
            or not 0.0 <= float(conf) <= 1.0):
        problems.append("invalid:confidence")
    criteria = result.get("criteria")
    if not isinstance(criteria, dict) or not criteria:
        problems.append("invalid:criteria")
    else:
        bad = {k: v for k, v in criteria.items()
               if not isinstance(v, int) or isinstance(v, bool)
               or not 1 <= v <= 5}
        if bad:
            problems.append(f"invalid:criteria_values:{sorted(bad)}")
    flags = result.get("risk_flags")
    if not isinstance(flags, list) or not all(isinstance(f, str) for f in flags):
        problems.append("invalid:risk_flags")
    reviewer = result.get("reviewer")
    if not isinstance(reviewer, dict) or not all(
            isinstance(reviewer.get(k), str) and reviewer.get(k)
            for k in ("provider", "model", "version")):
        problems.append("invalid:reviewer")
    ih = result.get("input_hash")
    if ih is not None and not (isinstance(ih, str) and len(ih) == 64):
        problems.append("invalid:input_hash")
    if not isinstance(result.get("record_id"), str) or not result["record_id"]:
        problems.append("invalid:record_id")
    if not isinstance(result.get("reviewed_at"), str) or not result["reviewed_at"]:
        problems.append("invalid:reviewed_at")
    rv = result.get("review_version")
    if not isinstance(rv, str) or not rv:
        problems.append("invalid:review_version")
    return problems


def normalize_human_decision(decision: dict) -> dict:
    """Convert a legacy review_ui.py decision line into the normalized contract.

    Legacy shape: {review_id, record_id, reviewer ("human:<user>"), verdict
    (KEEP|REVISE|REJECT), dimensions {4 x 1..5}, notes, reviewed_at,
    auto_gate_snapshot}.
    """
    verdict = decision.get("verdict", "")
    dec = LEGACY_TO_DECISION.get(verdict)
    dims = decision.get("dimensions") or {}
    overall = None
    if dims:
        vals = [int(v) for v in dims.values() if isinstance(v, (int, float))]
        if vals:
            overall = round(sum(vals) / len(vals) * 2)
    reviewer_raw = decision.get("reviewer") or "human:unknown"
    provider, _, who = reviewer_raw.partition(":")
    return {
        "review_id": decision.get("review_id"),
        "record_id": decision.get("record_id"),
        "review_mode": REVIEW_MODE_HUMAN,
        "decision": dec,
        "legacy_verdict": verdict,
        "quality_score": overall,
        "confidence": None,
        "criteria": dict(dims),
        "risk_flags": [],
        "notes": decision.get("notes", ""),
        "auto_gate_snapshot": decision.get("auto_gate_snapshot"),
        "reviewer": {
            "provider": provider or "human",
            "model": who or "unknown",
            "version": "review_ui",
        },
        "input_hash": None,
        "reviewed_at": decision.get("reviewed_at"),
        "review_version": REVIEW_VERSION,
    }


def reviewer_failure_result(record: dict, error: Exception | str, *,
                            now_iso: str, config_summary: dict | None = None,
                            record_hash: str | None = None) -> dict:
    """Fail-safe result for a reviewer that could not produce a verdict.

    Routed to `review` with a reviewer_failure risk flag — never accepted.
    """
    err_str = str(error)
    reason = getattr(error, "reason", "reviewer_exception")
    return {
        "record_id": (record or {}).get("id", ""),
        "review_mode": REVIEW_MODE_AI,
        "decision": DECISION_REVIEW,
        "decision_source": "reviewer_failure",
        "failure_reason": reason,
        "failure_detail": err_str[:500],
        "quality_score": None,
        "confidence": 0.0,
        "criteria": {},
        "risk_flags": ["reviewer_failure"],
        "notes": f"semantic review could not run ({reason}); needs adjudication",
        "reviewer": {
            "provider": (config_summary or {}).get("provider", "unknown"),
            "model": (config_summary or {}).get("model", "unknown"),
            "version": REVIEW_VERSION,
        },
        "input_hash": record_hash,
        "reviewed_at": now_iso,
        "review_version": REVIEW_VERSION,
    }
