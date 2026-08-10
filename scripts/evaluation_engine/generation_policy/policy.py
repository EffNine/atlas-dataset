"""policy.py — GenerationPolicy: immutable per-family generation policy.

A ``GenerationPolicy`` is the family-scoped declaration of HOW a model may be
asked to respond (Sprint 5A.4 infrastructure). It composes the prompt-side
lock (``evaluation_engine.leakage.prompts.PolicyLock``) with the budget rule,
extraction rule, and format-accounting contract of Protocol v2 §3.6 without
changing any prompt text. The prompt-side lock remains the single source of
system-message constants (rule P4); this module only *references* it.

Immutability and determinism:
  * frozen dataclass — a policy cannot be edited after construction,
  * ``from_family`` resolves family defaults deterministically from the
    canonical prompt module (never from a record),
  * ``from_dict`` / ``to_dict`` are strict (unknown keys raise) and lossless,
  * ``sha256`` hashes the canonical sorted JSON form so a policy change is
    always a hash change.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields
from typing import Any

from ..leakage.prompts import PolicyLock, get_policy_lock
from .versioning import (
    FAMILY_BUDGET_PARAMS,
    GENERATION_POLICY_VERSION,
    POLICY_SCHEMA_VERSION,
    RULE_DYNAMIC_REFERENCE_DERIVED,
    RULE_REFERENCE_DERIVED,
    STOP_SEQUENCE,
    TEMPLATE_VERSION,
    assert_family_supported,
    assert_policy_version_supported,
    assert_schema_version_supported,
)

# Extraction rules per family (Protocol v2 §3.6 "Extraction" row). These are
# deterministic rule names recorded in metadata, not measured numbers.
FAMILY_EXTRACTION_RULES: dict[str, str] = {
    "math": "qee-v2-math-extractor (Phase 5A.4 + 6.4 patches)",
    "code": "P8 generation-policy-lock v1.0 diff extraction wrapper (§4.5)",
    "semantic": "qee-v2-semantic-rubric",
}

# Format-accounting contract per family (Protocol v2 §3.6 "Format accounting"
# row): which output-shape failures are counted separately from capability.
FAMILY_FORMAT_ACCOUNTING: dict[str, tuple[str, ...]] = {
    "math": ("no_final_answer",),
    "code": ("patch_emission_rate", "prose_rate", "fenced_rate"),
    "semantic": ("empty",),
}

# Deterministic generation determinism statement (Protocol v2 §3.6
# "Determinism" row).
DETERMINISM = "greedy, fixed seed 42, NF4 4-bit + bf16, engine commit recorded"


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class GenerationPolicy:
    """Immutable per-family generation policy (Generation Policy Lock).

    Defaults reproduce the canonical Protocol v2 family policies
    (``docs/research/protocol_v2_transition.md`` §3.6). Construct directly, via
    ``GenerationPolicy.from_family(family)``, or via ``load_policy``.
    """

    family: str
    version: str = GENERATION_POLICY_VERSION
    schema_version: str = POLICY_SCHEMA_VERSION
    system_message_text: str = ""
    system_message_sha256: str = ""
    policy_lock_sha256: str = ""
    template_version: str = TEMPLATE_VERSION
    stop_sequence: str = STOP_SEQUENCE
    budget_rule: str = RULE_REFERENCE_DERIVED
    budget_strategy: str = "static"
    budget_params: dict[str, object] | None = None
    extraction_rule: str = ""
    format_accounting: tuple[str, ...] = ()
    determinism: str = DETERMINISM

    # ------------------------------------------------------------------ #
    # Constructors
    # ------------------------------------------------------------------ #
    @classmethod
    def from_family(cls, family: str) -> "GenerationPolicy":
        """Build the canonical policy for a family from the shared prompt
        module (single source of system-message constants).

        Family-specific calibrated budget parameters (Sprint 5A.5) are used
        to set ``budget_strategy="dynamic"`` and ``budget_params`` when
        available; families without calibrated params fall back to the
        canonical ``StaticBudget`` rule.
        """
        assert_family_supported(family)
        lock: PolicyLock = get_policy_lock(family)
        params = FAMILY_BUDGET_PARAMS.get(family)
        budget_strategy = "dynamic" if params is not None else "static"
        budget_params = dict(params) if params is not None else None
        budget_rule = (
            RULE_DYNAMIC_REFERENCE_DERIVED
            if budget_strategy == "dynamic"
            else lock.budget_rule
        )
        return cls(
            family=family,
            system_message_text=lock.system_message_text,
            system_message_sha256=_sha256_hex(lock.system_message_text),
            policy_lock_sha256=lock.to_block()["policy_block_sha256"],
            template_version=lock.template_version,
            stop_sequence=lock.stop_sequence,
            budget_rule=budget_rule,
            budget_strategy=budget_strategy,
            budget_params=budget_params,
            extraction_rule=FAMILY_EXTRACTION_RULES[family],
            format_accounting=FAMILY_FORMAT_ACCOUNTING[family],
            determinism=DETERMINISM,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GenerationPolicy":
        """Strict, version-aware deserialization. Unknown keys raise.

        Omitted prompt-side fields are resolved deterministically from the
        canonical family lock (they are derived protocol constants, never
        guessed). Explicit values are taken verbatim.
        """
        if not isinstance(data, dict):
            raise TypeError(
                f"GenerationPolicy.from_dict expects a dict, got {type(data).__name__}"
            )
        allowed = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ValueError(f"unknown GenerationPolicy keys: {unknown}")

        family = str(data.get("family", ""))
        assert_family_supported(family)

        version = str(data.get("version", GENERATION_POLICY_VERSION))
        schema_version = str(data.get("schema_version", POLICY_SCHEMA_VERSION))
        assert_policy_version_supported(version)
        assert_schema_version_supported(schema_version, artifact="GenerationPolicy")

        lock: PolicyLock = get_policy_lock(family)

        def _pick(key: str, fallback: Any) -> Any:
            return data.get(key, fallback)

        budget_strategy = str(_pick("budget_strategy", "static"))
        budget_params_raw = data.get("budget_params")
        if budget_params_raw is not None and not isinstance(budget_params_raw, dict):
            raise TypeError(
                f"budget_params must be a dict or null, got "
                f"{type(budget_params_raw).__name__}"
            )
        budget_params: dict[str, object] | None = (
            {k: v for k, v in budget_params_raw.items()}
            if budget_params_raw is not None
            else None
        )
        budget_rule: str = str(_pick(
            "budget_rule",
            RULE_DYNAMIC_REFERENCE_DERIVED
            if budget_strategy == "dynamic"
            else lock.budget_rule,
        ))

        return cls(
            family=family,
            version=version,
            schema_version=schema_version,
            system_message_text=_pick(
                "system_message_text", lock.system_message_text),
            system_message_sha256=_pick(
                "system_message_sha256", _sha256_hex(lock.system_message_text)),
            policy_lock_sha256=_pick(
                "policy_lock_sha256", lock.to_block()["policy_block_sha256"]),
            template_version=_pick("template_version", lock.template_version),
            stop_sequence=_pick("stop_sequence", lock.stop_sequence),
            budget_rule=budget_rule,
            budget_strategy=budget_strategy,
            budget_params=budget_params,
            extraction_rule=_pick(
                "extraction_rule", FAMILY_EXTRACTION_RULES[family]),
            format_accounting=tuple(
                _pick("format_accounting", list(FAMILY_FORMAT_ACCOUNTING[family]))),
            determinism=_pick("determinism", DETERMINISM),
        )

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "version": self.version,
            "schema_version": self.schema_version,
            "system_message_text": self.system_message_text,
            "system_message_sha256": self.system_message_sha256,
            "policy_lock_sha256": self.policy_lock_sha256,
            "template_version": self.template_version,
            "stop_sequence": self.stop_sequence,
            "budget_rule": self.budget_rule,
            "budget_strategy": self.budget_strategy,
            "budget_params": self.budget_params,
            "extraction_rule": self.extraction_rule,
            "format_accounting": list(self.format_accounting),
            "determinism": self.determinism,
        }

    def sha256(self) -> str:
        return _sha256_hex(_canonical_json(self.to_dict()))

    def to_block(self) -> dict[str, Any]:
        """Serializable policy metadata block with a self-hash."""
        block = self.to_dict()
        block["policy_sha256"] = self.sha256()
        block["policy_block_sha256"] = _sha256_hex(
            _canonical_json({k: v for k, v in block.items() if k != "policy_block_sha256"})
        )
        return block