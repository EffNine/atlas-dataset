"""versioning.py — version registry and support checks.

The generation-policy infrastructure (Sprint 5A.4) records a version on every
serializable artifact so a run can (a) fail closed on an unsupported schema and
(b) change-detect a drift in the policy or config format. Values mirror the
numbers published in the Protocol v2 baseline certificate and the Generation
Policy Lock (``docs/research/protocol_v2_transition.md`` §3.6,
``docs/research/p8_generation_policy.md`` §4).

Artifacts and their current versions:

+--------------------------------+---------------------+
| Artifact                      | Version             |
+--------------------------------+---------------------+
| ``GenerationPolicy`` format   | ``1.0``             |
| ``GenerationPolicy`` schema    | ``1``               |
| ``GenerationConfig`` schema    | ``1``               |
+--------------------------------+---------------------+

Deterministic, offline, stdlib-only. No model is loaded and no inference is
performed anywhere in this package.
"""

from __future__ import annotations

from ..leakage.prompts import (
    BUDGET_FALLBACK,
    BUDGET_RULE,
    STOP_SEQ,
    TEMPLATE_VERSION,
)

# --------------------------------------------------------------------------- #
# Schema / format versions
# --------------------------------------------------------------------------- #
GENERATION_POLICY_VERSION = "1.0"
POLICY_SCHEMA_VERSION = "1"
CONFIG_SCHEMA_VERSION = "1"

# Version families a loader or validator must understand. Any other value is
# rejected (fail closed) rather than guessed at.
SUPPORTED_FAMILIES = ("math", "code", "semantic")
SUPPORTED_POLICY_VERSIONS = frozenset({GENERATION_POLICY_VERSION})
SUPPORTED_SCHEMA_VERSIONS = frozenset({POLICY_SCHEMA_VERSION, CONFIG_SCHEMA_VERSION})

# --------------------------------------------------------------------------- #
# Generation Policy Lock constants (protocol_v2_transition.md §3.6; the code
# family lock is defined in p8_generation_policy.md §4). These are protocol
# constants, not measured numbers.
# --------------------------------------------------------------------------- #
MAX_BUDGET = 4096
MIN_BUDGET = 256
BASE_TOKENS = 128
BUDGET_MULTIPLIER = 1.5

# Canonical, human-readable budget rule. Kept in lock-step with the value
# advertised in the Protocol v2 certificate and the leakage cache lock.
RULE_REFERENCE_DERIVED = BUDGET_RULE
RULE_FIXED_FALLBACK = "fixed-fallback"
RULE_DYNAMIC_REFERENCE_DERIVED = "dynamic-reference-derived"
SUPPORTED_BUDGET_RULES = frozenset({
    RULE_REFERENCE_DERIVED,
    RULE_FIXED_FALLBACK,
    RULE_DYNAMIC_REFERENCE_DERIVED,
})

# Template used to render a StaticBudget/DynamicBudgetStrategy rule from its
# actual constants. With the protocol defaults its output is byte-identical to
# RULE_REFERENCE_DERIVED (verified in the unit suite).
BUDGET_RULE_TEMPLATE = (
    "budget_i = min({max_budget}, max({min_budget}, {base_tokens} + "
    "ceil({multiplier} * N_tokens(reference_i))))"
)

STOP_SEQUENCE = STOP_SEQ

# Deterministic sampling modes a locked config may declare. Only ``greedy`` is
# supported today; anything else is rejected (fail closed) rather than
# interpreted, because the determinism statement in the policy lock assumes it.
SUPPORTED_SAMPLING = ("greedy",)

# --------------------------------------------------------------------------- #
# Per-family calibrated budget parameters (Sprint 5A.5 calibration report).
#
# Source: ``docs/research/generation_policy_calibration_5A5.md`` §12.1.
# These are design inputs, not measured numbers. ``semantic`` is provisional —
# the same coefficients as math are used as a conservative placeholder until
# a semantic eval set is available.
# --------------------------------------------------------------------------- #
FAMILY_BUDGET_PARAMS: dict[str, dict[str, object]] = {
    "math": {
        "base_budget": 128,
        "alpha": 3.0,
        "minimum_budget": 256,
        "maximum_budget": 4096,
    },
    "code": {
        "base_budget": 256,
        "alpha": 2.0,
        "minimum_budget": 256,
        "maximum_budget": 4096,
    },
    "semantic": {
        "base_budget": 128,
        "alpha": 3.0,
        "minimum_budget": 256,
        "maximum_budget": 4096,
    },
}

# --------------------------------------------------------------------------- #
# Support checks
# --------------------------------------------------------------------------- #
def assert_policy_version_supported(version: str) -> None:
    """Raise ``ValueError`` unless ``version`` is a supported policy version."""
    if version not in SUPPORTED_POLICY_VERSIONS:
        raise ValueError(
            f"unsupported GenerationPolicy version {version!r}; supported "
            f"{sorted(SUPPORTED_POLICY_VERSIONS)}"
        )


def assert_schema_version_supported(schema_version: str,
                                    artifact: str = "artifact") -> None:
    """Raise ``ValueError`` unless ``schema_version`` is supported."""
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(
            f"unsupported {artifact} schema version {schema_version!r}; "
            f"supported {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )


def assert_family_supported(family: str) -> None:
    """Raise ``ValueError`` unless ``family`` is a supported policy family."""
    if family not in SUPPORTED_FAMILIES:
        raise ValueError(
            f"unsupported policy family {family!r}; expected one of "
            f"{sorted(SUPPORTED_FAMILIES)}"
        )


def version_info() -> dict[str, object]:
    """Declarative version snapshot for metadata blocks and reports."""
    return {
        "generation_policy_version": GENERATION_POLICY_VERSION,
        "policy_schema_version": POLICY_SCHEMA_VERSION,
        "config_schema_version": CONFIG_SCHEMA_VERSION,
        "template_version": TEMPLATE_VERSION,
        "stop_sequence": STOP_SEQUENCE,
        "supported_families": list(SUPPORTED_FAMILIES),
    }