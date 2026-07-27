#!/usr/bin/env python3
"""
atlas_schema.py — Canonical schema field definitions for Atlas.

Centralizes all required fields, optional fields, field types, validation
patterns, and schema version constants so that every consumer imports from
a single source of truth.

This module is stdlib-only and importable from anywhere in the project.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Schema version constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION_BASE = "0.1"
SCHEMA_VERSION_KNOWLEDGE_OBJECT = "0.1"
CHAT_SCHEMA_VERSION = "0.1"
SUPPORTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({"0.1"})

# ---------------------------------------------------------------------------
# Field definitions for the BASE dataset schema (validate_dataset.py)
# ---------------------------------------------------------------------------

BASE_REQUIRED_FIELDS: frozenset[str] = frozenset({
    "id", "category", "subcategory", "type", "source", "messages",
    "language", "difficulty", "tags", "quality_score", "verified", "notes",
})

BASE_OPTIONAL_FIELDS: frozenset[str] = frozenset({
    "converted_from", "original_id",
})

# All allowed keys for base schema records (structural validation check)
BASE_ALLOWED_KEYS: frozenset[str] = BASE_REQUIRED_FIELDS | BASE_OPTIONAL_FIELDS

# ---------------------------------------------------------------------------
# Field definitions for the KNOWLEDGE OBJECT schema
# (validate_knowledge_object.py, knowledge_object_schema.json)
# ---------------------------------------------------------------------------

KNOWLEDGE_OBJECT_REQUIRED_FIELDS: list[str] = [
    "id", "category", "subcategory", "difficulty", "knowledge_type",
    "canonical_answer", "metadata", "source_attribution", "license", "tags",
    "quality_score", "verification_status", "lineage", "training_view_eligibility",
    "messages",
]

# Lineage sub-fields
LINEAGE_SUB_FIELDS: tuple[str, ...] = (
    "source", "transformations", "knowledge_object", "curated_dataset",
    "training_view", "future_model",
)

# ---------------------------------------------------------------------------
# Field definitions for the self-test structural fallback
# (atlas.py cmd_self_test)
# ---------------------------------------------------------------------------

SELF_TEST_REQUIRED_FIELDS: frozenset[str] = frozenset(KNOWLEDGE_OBJECT_REQUIRED_FIELDS)

# ---------------------------------------------------------------------------
# Regex validation patterns
# ---------------------------------------------------------------------------

ID_PATTERN: re.Pattern = re.compile(r"^[a-z0-9_-]+$")
TAG_PATTERN: re.Pattern = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
DATE_PATTERN: re.Pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LANGUAGE_PATTERN: re.Pattern = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")

# ---------------------------------------------------------------------------
# Field type / range helpers
# ---------------------------------------------------------------------------

# quality_score range
QUALITY_SCORE_MIN = 0
QUALITY_SCORE_MAX = 10

# difficulty range
DIFFICULTY_MIN = 0
DIFFICULTY_MAX = 3

# Minimum message turns required
MIN_MESSAGE_TURNS = 2


def validate_quality_score(value: Any) -> list[str]:
    """Validate a quality_score value. Returns list of error messages."""
    errs: list[str] = []
    if not isinstance(value, int):
        errs.append(f"quality_score must be int 0-10: {value!r}")
    elif not (QUALITY_SCORE_MIN <= value <= QUALITY_SCORE_MAX):
        errs.append(f"quality_score out of range {QUALITY_SCORE_MIN}-{QUALITY_SCORE_MAX}: {value}")
    return errs


def validate_difficulty(value: Any) -> list[str]:
    """Validate a difficulty value. Returns list of error messages."""
    errs: list[str] = []
    allowed = {DIFFICULTY_MIN, DIFFICULTY_MAX - 1, DIFFICULTY_MAX}  # 0, 2, 3
    # Actually all ints 0-3 are valid
    try:
        d = int(value)
        if not (DIFFICULTY_MIN <= d <= DIFFICULTY_MAX):
            errs.append(f"difficulty must be {DIFFICULTY_MIN}-{DIFFICULTY_MAX}: {d}")
    except (TypeError, ValueError):
        errs.append(f"difficulty not int: {value!r}")
    return errs


def validate_messages(messages: Any) -> list[str]:
    """Validate messages field. Returns list of error messages."""
    errs: list[str] = []
    if not isinstance(messages, list) or len(messages) < MIN_MESSAGE_TURNS:
        errs.append(f"messages must be a list with >= {MIN_MESSAGE_TURNS} turns")
    return errs


def validate_id(rid: Any) -> list[str]:
    """Validate a record ID. Returns list of error messages."""
    errs: list[str] = []
    if not isinstance(rid, str) or not ID_PATTERN.match(rid):
        errs.append(f"id invalid (must match {ID_PATTERN.pattern})")
    return errs


def field_info() -> dict[str, dict[str, Any]]:
    """Return structured metadata about all schema fields for introspection."""
    return {
        "id": {
            "type": "string",
            "required_in": ["base", "knowledge_object"],
            "pattern": ID_PATTERN.pattern,
        },
        "category": {
            "type": "string (enum)",
            "required_in": ["base", "knowledge_object"],
        },
        "subcategory": {
            "type": "string",
            "required_in": ["base", "knowledge_object"],
        },
        "type": {
            "type": "string (enum)",
            "required_in": ["base"],
        },
        "source": {
            "type": "dict",
            "required_in": ["base"],
            "sub_fields": ["name", "license", "date"],
        },
        "source_attribution": {
            "type": "dict",
            "required_in": ["knowledge_object"],
            "sub_fields": ["source_id", "name", "url", "license", "attribution_text"],
        },
        "messages": {
            "type": "list[dict]",
            "required_in": ["base", "knowledge_object"],
            "min_items": MIN_MESSAGE_TURNS,
        },
        "quality_score": {
            "type": "int",
            "required_in": ["base", "knowledge_object"],
            "min": QUALITY_SCORE_MIN,
            "max": QUALITY_SCORE_MAX,
        },
        "difficulty": {
            "type": "int",
            "required_in": ["base", "knowledge_object"],
            "min": DIFFICULTY_MIN,
            "max": DIFFICULTY_MAX,
        },
        "verified": {
            "type": "bool",
            "required_in": ["base"],
        },
        "verification_status": {
            "type": "string (enum)",
            "required_in": ["knowledge_object"],
        },
        "tags": {
            "type": "list[string]",
            "required_in": ["base", "knowledge_object"],
        },
        "language": {
            "type": "string",
            "required_in": ["base"],
            "default": "en",
        },
        "knowledge_type": {
            "type": "string (enum)",
            "required_in": ["knowledge_object"],
        },
        "canonical_answer": {
            "type": "string",
            "required_in": ["knowledge_object"],
        },
        "license": {
            "type": "string",
            "required_in": ["knowledge_object"],
        },
        "lineage": {
            "type": "dict",
            "required_in": ["knowledge_object"],
            "sub_fields": list(LINEAGE_SUB_FIELDS),
        },
        "training_view_eligibility": {
            "type": "dict[str, bool]",
            "required_in": ["knowledge_object"],
        },
        "metadata": {
            "type": "dict",
            "required_in": ["knowledge_object"],
        },
    }
