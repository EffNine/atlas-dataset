"""validation.py — GenerationValidation: deterministic policy/config checks.

``GenerationValidation`` is the validation gate for the generation-policy
infrastructure (Sprint 5A.4). It is pure and deterministic: it never loads a
model, never runs inference, and never touches dataset artifacts. Every check
returns an immutable ``ValidationResult``; any issue means the policy/config
must not be used for a comparison arm (fail closed).

Checks cover:
  * family, policy format version, and schema version support,
  * budget-rule support and budget bound sanity,
  * determinism invariants of the locked config (greedy only, no sampling
    entropy, pad == eos when tokens are provided),
  * consistency between a policy and its paired config.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .budget import BudgetResult, StaticBudget
from .config import GenerationConfig
from .policy import GenerationPolicy
from .versioning import (
    SUPPORTED_BUDGET_RULES,
    SUPPORTED_FAMILIES,
    SUPPORTED_SAMPLING,
    assert_family_supported,
    assert_policy_version_supported,
    assert_schema_version_supported,
)


@dataclass(frozen=True)
class ValidationResult:
    """Immutable outcome of one validation call."""

    valid: bool
    issues: tuple[str, ...] = ()
    policy_sha256: str | None = None
    config_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "issues": list(self.issues),
            "policy_sha256": self.policy_sha256,
            "config_sha256": self.config_sha256,
        }


def _ok(**meta: Any) -> ValidationResult:
    return ValidationResult(valid=True, issues=(), **meta)


def _issues(items: list[str], **meta: Any) -> ValidationResult:
    return ValidationResult(valid=False, issues=tuple(items), **meta)


class GenerationValidation:
    """Deterministic validation entry points (pure, read-only)."""

    # ------------------------------------------------------------------ #
    # Policy
    # ------------------------------------------------------------------ #
    @staticmethod
    def validate_policy(policy: GenerationPolicy) -> ValidationResult:
        problems: list[str] = []
        try:
            assert_family_supported(policy.family)
        except ValueError as exc:
            problems.append(str(exc))
        try:
            assert_policy_version_supported(policy.version)
        except ValueError as exc:
            problems.append(str(exc))
        try:
            assert_schema_version_supported(policy.schema_version, "GenerationPolicy")
        except ValueError as exc:
            problems.append(str(exc))

        if not policy.system_message_text.strip():
            problems.append("system_message_text must be non-empty")
        if not policy.stop_sequence.strip():
            problems.append("stop_sequence must be non-empty")
        if policy.budget_rule not in SUPPORTED_BUDGET_RULES:
            problems.append(
                f"budget_rule {policy.budget_rule!r} not in supported "
                f"{sorted(SUPPORTED_BUDGET_RULES)}"
            )
        if not policy.extraction_rule.strip():
            problems.append("extraction_rule must be non-empty")
        if not policy.format_accounting:
            problems.append("format_accounting must not be empty")
        if not policy.determinism.strip():
            problems.append("determinism statement must be non-empty")
        if policy.budget_rule not in SUPPORTED_BUDGET_RULES:
            problems.append(
                f"budget_rule {policy.budget_rule!r} not in supported "
                f"{sorted(SUPPORTED_BUDGET_RULES)}"
            )
        if policy.budget_strategy not in ("static", "dynamic"):
            problems.append(
                f"budget_strategy {policy.budget_strategy!r} not in "
                f"('static', 'dynamic')"
            )
        if policy.budget_strategy == "dynamic":
            params = policy.budget_params or {}
            problems.extend(_validate_dynamic_params(params))

        if problems:
            return _issues(problems, policy_sha256=policy.sha256())
        return _ok(policy_sha256=policy.sha256())

    # ------------------------------------------------------------------ #
    # Config
    # ------------------------------------------------------------------ #
    @staticmethod
    def validate_config(config: GenerationConfig) -> ValidationResult:
        problems: list[str] = []
        try:
            assert_schema_version_supported(config.schema_version, "GenerationConfig")
        except ValueError as exc:
            problems.append(str(exc))

        if config.sampling not in SUPPORTED_SAMPLING:
            problems.append(
                f"sampling {config.sampling!r} not in supported {sorted(SUPPORTED_SAMPLING)}"
            )
        if config.do_sample:
            problems.append("do_sample must be False for a deterministic lock")
        if config.sampling == "greedy" and config.temperature not in (None, 1.0):
            problems.append("greedy lock must use temperature None or 1.0")
        if config.sampling == "greedy" and config.top_p not in (None, 1.0):
            problems.append("greedy lock must use top_p None or 1.0")
        if config.max_budget < 1:
            problems.append(f"max_budget must be >= 1 (got {config.max_budget})")
        if not (1 <= config.budget_fallback <= config.max_budget):
            problems.append(
                f"budget_fallback {config.budget_fallback} must satisfy "
                f"1 <= budget_fallback <= max_budget {config.max_budget}"
            )
        if not config.stop_sequence.strip():
            problems.append("stop_sequence must be non-empty")
        if config.eos_token_id is not None and config.eos_token_id < 0:
            problems.append("eos_token_id must be non-negative")
        if config.pad_token_id is not None and config.pad_token_id < 0:
            problems.append("pad_token_id must be non-negative")
        if (
            config.eos_token_id is not None
            and config.pad_token_id is not None
            and config.eos_token_id != config.pad_token_id
        ):
            problems.append("pad_token_id must equal eos_token_id (lock §4.2)")
        if not config.device_map.strip():
            problems.append("device_map must be non-empty")
        if config.seed < 0:
            problems.append("seed must be non-negative")

        if problems:
            return _issues(problems, config_sha256=config.sha256())
        return _ok(config_sha256=config.sha256())

    # ------------------------------------------------------------------ #
    # Policy <-> config pairing
    # ------------------------------------------------------------------ #
    @staticmethod
    def validate_pair(policy: GenerationPolicy, config: GenerationConfig) -> ValidationResult:
        """Cross-object consistency (stop sequence, budget fallback)."""
        problems: list[str] = []
        if config.stop_sequence != policy.stop_sequence:
            problems.append(
                f"config.stop_sequence {config.stop_sequence!r} != policy "
                f"{policy.stop_sequence!r}"
            )
        if policy.budget_rule == "fixed-fallback":
            if config.budget_fallback < 1:
                problems.append(
                    f"fixed-fallback policy requires budget_fallback >= 1 "
                    f"(got {config.budget_fallback})"
                )
        else:
            if config.budget_fallback > config.max_budget:
                problems.append(
                    "budget_fallback must not exceed max_budget"
                )
        if problems:
            return _issues(
                problems,
                policy_sha256=policy.sha256(),
                config_sha256=config.sha256(),
            )
        return _ok(
            policy_sha256=policy.sha256(),
            config_sha256=config.sha256(),
        )

    # ------------------------------------------------------------------ #
    # Budget results
    # ------------------------------------------------------------------ #
    @staticmethod
    def validate_budget_result(
        result: BudgetResult,
        budget_strategy: StaticBudget | None = None,
    ) -> ValidationResult:
        """Sanity-check a computed budget against the strategy bounds."""
        problems: list[str] = []
        # Accept either StaticBudget or DynamicBudgetStrategy for bounds checks.
        strat = budget_strategy
        if strat is None:
            # Default to static for the common case.
            from .budget import StaticBudget
            strat = StaticBudget()
        if result.budget < 1:
            problems.append(f"budget must be >= 1 (got {result.budget})")
        if result.fallback_used:
            if result.budget != strat.fallback_budget:
                problems.append(
                    f"fallback budget {result.budget} != strategy fallback "
                    f"{strat.fallback_budget}"
                )
        else:
            if result.reference_tokens is None:
                problems.append("reference_tokens must be set when not a fallback")
            if not (strat.minimum_budget <= result.budget <= strat.maximum_budget):
                problems.append(
                    f"budget {result.budget} outside strategy range "
                    f"[{strat.minimum_budget}, {strat.maximum_budget}]"
                )
        if problems:
            return _issues(problems)
        return _ok()


def run_policy_validation(policy: GenerationPolicy) -> ValidationResult:
    """Module-level convenience for policy validation."""
    return GenerationValidation.validate_policy(policy)


def run_config_validation(config: GenerationConfig) -> ValidationResult:
    """Module-level convenience for config validation."""
    return GenerationValidation.validate_config(config)


# --------------------------------------------------------------------------- #
# Dynamic budget param validation helpers
# --------------------------------------------------------------------------- #
def _validate_dynamic_params(params: dict[str, Any]) -> list[str]:
    """Return a list of issue strings for invalid dynamic budget params."""
    problems: list[str] = []
    required_keys = ("base_budget", "alpha", "minimum_budget", "maximum_budget")
    missing = [k for k in required_keys if k not in params]
    if missing:
        problems.append(f"dynamic budget params missing keys: {missing}")
        return problems

    base = params["base_budget"]
    alpha = params["alpha"]
    minb = params["minimum_budget"]
    maxb = params["maximum_budget"]

    if not isinstance(base, int) or base < 1:
        problems.append(f"base_budget must be an int >= 1 (got {base!r})")
    if not isinstance(alpha, (int, float)) or alpha <= 0:
        problems.append(f"alpha must be a positive number (got {alpha!r})")
    if not isinstance(minb, int) or minb < 1:
        problems.append(f"minimum_budget must be an int >= 1 (got {minb!r})")
    if not isinstance(maxb, int) or maxb < 1:
        problems.append(f"maximum_budget must be an int >= 1 (got {maxb!r})")
    if isinstance(minb, int) and isinstance(maxb, int):
        if maxb < minb:
            problems.append(
                f"maximum_budget {maxb} < minimum_budget {minb}"
            )
        # Allow base > min only if explicitly configured (unusual but valid).
    if problems:
        return problems
    return []