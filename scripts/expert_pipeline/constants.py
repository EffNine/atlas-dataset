"""Shared constants for the Atlas Expert pipeline.

Mirrors docs/expert_record_schema_v0.1.md, docs/expert_quality_gate_v0.1.md,
and the approved 6500 pilot composition
(docs/specialist_10k_pilot_extraction_plan_v0.1.md, Option A).
"""

from __future__ import annotations

from pathlib import Path

# --- Pilot composition (approved Option A) ---
PILOT_TOTAL = 6500
PILOT_COMPOSITION = {
    "expert-swe-001": 500,
    "expert-math-002": 3000,
    "expert-aiml-001": 3000,
}

# --- Schema constants (expert_record_schema_v0.1) ---
DOMAINS = {"software_engineering", "ai_machine_learning", "mathematics", "science", "system_engineering"}
TIERS = {"E1", "E2", "E3"}
TYPES = {"qa", "instruction", "reasoning", "code"}
VERIFY_STATUSES = {"verified", "unverified", "needs_review", "rejected"}
VERIFY_METHODS = {
    "gold_patch", "unit_test", "auto_grader", "human_review", "peer_review",
    "verified_solution_set", "doc_template",
}

# Required leaf fields: dotted path -> expected python type.
REQUIRED_LEAF = {
    "id": str,
    "domain": str,
    "expert_tier": str,
    "difficulty": int,
    "type": str,
    "source.source_id": str,
    "source.name": str,
    "source.url": str,
    "source.license": str,
    "source.accessed_at": str,
    "license": str,
    "attribution": str,
    "problem": str,
    "solution": str,
    "verification.method": str,
    "verification.status": str,
    "provenance.original_id": str,
    "provenance.ingestion_pipeline": str,
    "provenance.transformations": list,
    "metadata.language": str,
    "metadata.quality_score": int,
    "metadata.synthetic": bool,
    "metadata.model_generated": bool,
    "messages": list,
    "created_at": str,
    "curated": bool,
}

# --- Quality gate thresholds (per docs/expert_quality_gate_v0.1.md) ---
SCORER_VERSION = "calibration-heuristic-v0.1"
GATE_KEEP_MIN_CORRECTNESS = 3
GATE_KEEP_MIN_PROVENANCE = 3
GATE_REJECT_MAX_CORRECTNESS = 2
GATE_REJECT_MAX_PROVENANCE = 1
GOLD_MIN = {
    "correctness": 4,
    "reasoning_depth": 4,
    "explanation_quality": 4,
}
QUALITY_SCORE_MIN_TARGET = 7  # expert target

# --- Duplicate policy ---
NEAR_DUP_GROUP_MAX = 1  # collapse near-duplicate clusters to <= 1 survivor

# --- Security hard gate patterns ---
SECURITY_PATTERNS = [
    ("private_key", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("aws_key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("openai_key", r"\bsk-[A-Za-z0-9]{20,}\b"),
    ("generic_token", r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    ("local_win_path", r"[A-Za-z]:\\Users\\"),
    (
        "credential_home_path",
        r"/Users/[A-Za-z0-9_]+/(?:\.ssh|\.aws|\.gnupg|\.netrc|\.config/gcloud|"
        r"credentials|secrets?|tokens?|id_rsa|\.pem)\b",
    ),
]

# --- Licenses allowed in the pilot ---
ALLOWED_LICENSES = {
    "MIT",
    "Apache-2.0",
    "CC-BY-4.0",
    "arXiv non-exclusive license",
}
BLOCKED_LICENSE_MARKERS = ("nc", "non-commercial", "unknown", "none listed", "other")

# --- Output paths (pilot dirs only) ---
ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "metadata" / "expert_pilot_6500_manifest_v0.1.json"
RECORDS_PATH = ROOT / "tmp" / "expert_pilot_6500_records_v0.1.jsonl"
QUALITY_REPORT_PATH = ROOT / "reports" / "expert_pilot_6500_quality_v0.1.json"
