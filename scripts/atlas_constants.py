#!/usr/bin/env python3
"""
atlas_constants.py — Canonical enum registry and license utilities for Atlas.

Centralizes all shared constants (category enums, knowledge types, verification
statuses, lifecycle states, roles, license helpers) so that each consumer
imports from a single source of truth.

This module is stdlib-only and importable from anywhere in the project.
"""

from __future__ import annotations

import re
from typing import Callable

# ---------------------------------------------------------------------------
# Category enums
# ---------------------------------------------------------------------------

VALID_CATEGORIES: frozenset[str] = frozenset({
    "01_foundation", "02_software_engineering", "03_system_engineering",
    "04_ai_machine_learning", "05_hardware_engineering", "06_science_engineering",
    "07_business_knowledge", "08_creative_knowledge", "09_personal_assistant",
})

# ---------------------------------------------------------------------------
# Dataset types (instruction, conversation, qa, reasoning)
# ---------------------------------------------------------------------------

VALID_TYPES: frozenset[str] = frozenset({
    "instruction", "conversation", "qa", "reasoning",
})

# ---------------------------------------------------------------------------
# Knowledge types (validate_knowledge_object.py)
# ---------------------------------------------------------------------------

VALID_KNOWLEDGE_TYPES: frozenset[str] = frozenset({
    "fact", "procedure", "concept", "reasoning", "code", "reference", "creative",
})

# ---------------------------------------------------------------------------
# Verification statuses
# validate_dataset.py uses "pending", "approved", "rejected", "needs_revision", "unknown"
# validate_knowledge_object.py uses "pending", "approved", "rejected", "needs_revision"
# release.py uses the same 5 as validate_dataset.py
# ---------------------------------------------------------------------------

VERIFICATION_STATUSES: frozenset[str] = frozenset({
    "pending", "approved", "rejected", "needs_revision", "unknown",
})

# ---------------------------------------------------------------------------
# Lifecycle states (from lifecycle.py)
# ---------------------------------------------------------------------------

LIFECYCLE_STATES: list[str] = [
    "raw", "processing", "curated", "review", "approved",
    "released", "archived", "rejected",
]

# ---------------------------------------------------------------------------
# Chat roles (shared by validate_dataset.py and validate_knowledge_object.py)
# ---------------------------------------------------------------------------

VALID_ROLES: frozenset[str] = frozenset({
    "system", "user", "assistant", "tool",
})

# ---------------------------------------------------------------------------
# Training-view eligibility target models
# ---------------------------------------------------------------------------

VALID_TRAINING_MODELS: frozenset[str] = frozenset({
    "qwen", "llama", "deepseek",
})

# ---------------------------------------------------------------------------
# Semantic diff: verification status ranking (used in release.py SemanticDiff)
# ---------------------------------------------------------------------------

VERIFICATION_STATUS_RANK: dict[str, int] = {
    "approved": 4, "released": 4, "review": 3,
    "curated": 2, "pending": 2, "processing": 1,
    "raw": 0, "needs_revision": 1, "rejected": 0,
}

# ---------------------------------------------------------------------------
# License utilities
# ---------------------------------------------------------------------------

# Commercial-safety patterns: see docs/source_policy.md and ADR-002.
# CC-BY-NC*  = non-commercial (blocks commercial use)
# CC-BY-ND*  = no-derivatives (cannot reshape into instruction format)
# proprietary / all-rights-reserved = no redistribution/derivative rights
# unknown    = cannot confirm commercial safety
_DENIED_LICENSE_PATTERNS: tuple[str, ...] = (
    "cc-by-nc", "cc-by-nd", "proprietary", "all-rights-reserved", "unknown",
)

# Share-alike patterns: CC-BY-SA variants (require downstream share-alike)
_SHARE_ALIKE_PATTERNS: tuple[str, ...] = ("cc-by-sa",)

# Attribution-required patterns: all CC variants except CC0 require attribution
_ATTRIBUTION_REQUIRED_PATTERNS: tuple[str, ...] = ("cc-by-", "cc-by-sa-", "cc-by-nc-", "cc-by-nd-")
_ATTRIBUTION_ALWAYS_REQUIRED: tuple[str, ...] = ("apache-2.0", "bsd", "mit", "odc-by")


def is_denied_license(lic: str) -> bool:
    """Check if a license is denied by commercial-safety policy.

    Returns True for NC/ND/proprietary/all-rights-reserved/unknown.
    CC-BY-SA and RAIL variants are NOT denied (they carry tracking/subsetting
    obligations handled at the ingestion level).
    """
    if not isinstance(lic, str):
        return True
    low = lic.strip().lower()
    return any(p in low for p in _DENIED_LICENSE_PATTERNS)


def is_share_alike(lic: str) -> bool:
    """Check if a license requires share-alike (CC-BY-SA variants)."""
    if not isinstance(lic, str):
        return False
    low = lic.strip().lower()
    return any(p in low for p in _SHARE_ALIKE_PATTERNS)


def requires_attribution(lic: str) -> bool:
    """Check if a license requires attribution.

    Returns True for:
      - All CC variants except CC0 (CC-BY, CC-BY-SA, CC-BY-NC, CC-BY-ND)
      - Apache-2.0, BSD, MIT, ODC-BY
      - Any license containing 'attribution' in its name/identifier
    """
    if not isinstance(lic, str):
        return False
    low = lic.strip().lower()
    # CC0 = no attribution required
    if low == "cc0" or low == "cc0-1.0" or low.startswith("cc0"):
        return False
    # Any CC variant except CC0
    for p in _ATTRIBUTION_REQUIRED_PATTERNS:
        if p in low:
            return True
    # Standard permissive
    for p in _ATTRIBUTION_ALWAYS_REQUIRED:
        if p in low:
            return True
    # License mentions attribution explicitly
    if "attribution" in low:
        return True
    return False
