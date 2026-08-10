"""metadata.py — GenerationMetadata: policy-lock metadata block builders.

``GenerationMetadata`` builds the ``generation_policy_lock`` metadata block a
run records (Protocol v2 §3.8), plus the per-record budget bookkeeping and
aggregate policy covariates (Protocol v2 §3.6, §3.7). Everything is
deterministic and hashed over the canonical sorted JSON form, so identical
inputs produce identical blocks (Sprint 5A.4 reusable infrastructure).

The metadata is read-only bookkeeping: it never modifies a record, a prompt, an
evaluator, or a dataset artifact.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from typing import Any, Iterable

from .budget import BudgetResult
from .config import GenerationConfig
from .policy import GenerationPolicy
from .versioning import GENERATION_POLICY_VERSION


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def block_sha256(block: dict[str, Any], excluded: str = "block_sha256") -> str:
    """SHA-256 over the canonical block minus its self-hash key."""
    return sha256_hex(
        canonical_json({k: v for k, v in block.items() if k != excluded})
    )


class GenerationMetadata:
    """Deterministic policy-lock metadata builders."""

    # ------------------------------------------------------------------ #
    # Blocks
    # ------------------------------------------------------------------ #
    @staticmethod
    def policy_block(policy: GenerationPolicy) -> dict[str, Any]:
        """Full policy metadata block (includes the self-hash)."""
        return policy.to_block()

    @staticmethod
    def config_block(config: GenerationConfig) -> dict[str, Any]:
        """Full config metadata block (includes the self-hash)."""
        return config.to_block()

    @staticmethod
    def run_policy_lock_block(
        policy: GenerationPolicy,
        config: GenerationConfig,
        prompt_template_sha256: str,
        per_record_budgets: Iterable[BudgetResult] = (),
        extraction_rule_version: str = "v1",
    ) -> dict[str, Any]:
        """The ``generation_policy_lock`` run block (Protocol v2 §3.8).

        Combines the policy and config self-hashes, the rendered prompt
        template hash, the extraction rule version, and the per-record budgets
        (deterministic). Used identically for every arm of a comparison.
        """
        budgets = tuple(per_record_budgets)
        block = {
            "policy_block_version": GENERATION_POLICY_VERSION,
            "policy_sha256": policy.sha256(),
            "config_sha256": config.sha256(),
            "policy_block_sha256": policy.to_block()["policy_block_sha256"],
            "config_block_sha256": config.to_block()["config_block_sha256"],
            "template_version": policy.template_version,
            "prompt_template_sha256": prompt_template_sha256,
            "stop_sequence": config.stop_sequence,
            "eos_token_id": config.eos_token_id,
            "pad_token_id": config.pad_token_id,
            "budget_rule": policy.budget_rule,
            "budget_fallback": config.budget_fallback,
            "extraction_rule": policy.extraction_rule,
            "extraction_rule_version": extraction_rule_version,
            "per_record_budgets": [r.to_dict() for r in budgets],
            "covariates": GenerationMetadata.covariates(budgets),
        }
        block["block_sha256"] = block_sha256(block)
        return block

    # ------------------------------------------------------------------ #
    # Per-record bookkeeping
    # ------------------------------------------------------------------ #
    @staticmethod
    def per_record_metadata(
        record_id: str,
        budget: BudgetResult,
        prompt_sha256: str,
    ) -> dict[str, Any]:
        """Per-record policy metadata written into per-example artifacts."""
        return {
            "record_id": record_id,
            "prompt_sha256": prompt_sha256,
            "budget": budget.budget,
            "budget_rule": budget.rule,
            "reference_tokens": budget.reference_tokens,
            "budget_fallback_used": budget.fallback_used,
            "budget_capped": budget.capped,
            "budget_floor_applied": budget.floor_applied,
        }

    # ------------------------------------------------------------------ #
    # Aggregates / covariates
    # ------------------------------------------------------------------ #
    @staticmethod
    def covariates(budget_results: Iterable[BudgetResult]) -> dict[str, Any]:
        """Aggregate budget covariates over a set of per-record results.

        Deterministic over the input order. Empty input yields all-zero
        aggregates (never fabricated values).
        """
        results = list(budget_results)
        n = len(results)
        if n == 0:
            return {
                "n": 0,
                "fallback_rate": 0.0,
                "cap_rate": 0.0,
                "floor_rate": 0.0,
                "budget_mean": None,
                "budget_median": None,
                "budget_min": None,
                "budget_max": None,
            }
        budgets = [r.budget for r in results]
        return {
            "n": n,
            "fallback_rate": round(
                sum(1 for r in results if r.fallback_used) / n, 4),
            "cap_rate": round(sum(1 for r in results if r.capped) / n, 4),
            "floor_rate": round(sum(1 for r in results if r.floor_applied) / n, 4),
            "budget_mean": round(statistics.mean(budgets), 2),
            "budget_median": float(statistics.median(budgets)),
            "budget_min": min(budgets),
            "budget_max": max(budgets),
        }

    @staticmethod
    def generation_policy_summary(
        policy: GenerationPolicy,
        config: GenerationConfig,
        prompt_template_sha256: str,
    ) -> dict[str, Any]:
        """A compact, self-describing summary block for run reports."""
        return {
            "policy_version": policy.version,
            "family": policy.family,
            "policy_sha256": policy.sha256(),
            "config_sha256": config.sha256(),
            "template_version": policy.template_version,
            "prompt_template_sha256": prompt_template_sha256,
            "budget_rule": policy.budget_rule,
            "stop_sequence": config.stop_sequence,
            "determinism": policy.determinism,
            "extraction_rule": policy.extraction_rule,
        }