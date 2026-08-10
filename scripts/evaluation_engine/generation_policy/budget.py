"""budget.py — BudgetStrategy interface, StaticBudget, and DynamicBudgetStrategy.

The Generation Policy Lock (Protocol v2 §3.6) defines a per-record,
reference-derived token budget:

    budget_i = min(4096, max(256, 128 + ceil(1.5 * N_tokens(reference_i))))

This module isolates that computation as a reusable, deterministic
infrastructure component (Sprint 5A.4–5A.6). It does NOT tune the budget at
runtime: the rule and its constants are configuration-frozen (immutable), and
the only per-call inputs are the reference text and an optional token counter.
The fixed-1024 fallback of the lock is exposed as the ``RULE_FIXED_FALLBACK``
mode (``StaticBudget.fixed_fallback``) and via the no-counter code path.

``TokenCounter`` abstracts a tokenizer so the computation stays testable and
fully offline. When no counter is supplied the fallback budget is returned and
``fallback_used`` records the reason — the runner records that as a covariate,
it is never silently merged into a measured number.

Sprint 5A.6 adds ``DynamicBudgetStrategy``, a parameterized strategy whose
``base_budget``, ``alpha``, ``minimum_budget``, and ``maximum_budget`` are
loaded from configuration (the calibrated values from
``docs/research/generation_policy_calibration_5A5.md``). Both strategies
implement the same ``BudgetStrategy`` Protocol, selected by
``GenerationPolicy.budget_strategy``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol

from .versioning import (
    BASE_TOKENS,
    BUDGET_FALLBACK,
    BUDGET_MULTIPLIER,
    BUDGET_RULE_TEMPLATE,
    MAX_BUDGET,
    MIN_BUDGET,
    RULE_REFERENCE_DERIVED,
)


class TokenCounter(Protocol):
    """Any callable returning a stable, deterministic token count for text."""

    def __call__(self, text: str) -> int: ...


class BudgetStrategy(Protocol):
    """Interface implemented by every token-budget strategy.

    ``compute`` is deterministic: the same ``reference`` and ``token_counter``
    always yield the same ``BudgetResult``. ``BudgetResult`` is immutable.
    """

    def compute(
        self,
        reference: str,
        token_counter: TokenCounter | None = None,
    ) -> "BudgetResult": ...


@dataclass(frozen=True)
class BudgetResult:
    """Immutable outcome of one budget computation."""

    budget: int
    rule: str
    reference_tokens: int | None
    fallback_used: bool
    capped: bool
    floor_applied: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget": self.budget,
            "rule": self.rule,
            "reference_tokens": self.reference_tokens,
            "fallback_used": self.fallback_used,
            "capped": self.capped,
            "floor_applied": self.floor_applied,
        }


def _format_number(value: float) -> str:
    """Render a float without a trailing ``.0`` (e.g. 1.5 -> "1.5")."""
    if value == int(value):
        return str(int(value))
    return repr(value)


@dataclass(frozen=True)
class StaticBudget:
    """Deterministic reference-derived budget (Generation Policy Lock §4.3).

    Frozen by construction. The default parameters reproduce the canonical
    protocol rule byte-for-byte; a non-default construction is still
    deterministic and its recorded ``rule`` reflects the actual constants.
    """

    max_budget: int = MAX_BUDGET
    min_budget: int = MIN_BUDGET
    base_tokens: int = BASE_TOKENS
    multiplier: float = BUDGET_MULTIPLIER
    fallback_budget: int = BUDGET_FALLBACK

    @property
    def rule(self) -> str:
        if (
            self.max_budget == MAX_BUDGET
            and self.min_budget == MIN_BUDGET
            and self.base_tokens == BASE_TOKENS
            and self.multiplier == BUDGET_MULTIPLIER
            and self.fallback_budget == BUDGET_FALLBACK
        ):
            return RULE_REFERENCE_DERIVED
        return BUDGET_RULE_TEMPLATE.format(
            max_budget=self.max_budget,
            min_budget=self.min_budget,
            base_tokens=self.base_tokens,
            multiplier=_format_number(self.multiplier),
        )

    @property
    def minimum_budget(self) -> int:
        """Alias for ``min_budget`` to match ``DynamicBudgetStrategy``."""
        return self.min_budget

    @property
    def maximum_budget(self) -> int:
        """Alias for ``max_budget`` to match ``DynamicBudgetStrategy``."""
        return self.max_budget

    def compute(
        self,
        reference: str,
        token_counter: TokenCounter | None = None,
    ) -> BudgetResult:
        """Compute ``budget_i`` for one reference.

        With a counter: ``min(max, max(min, base + ceil(mult * N)))``. Without
        a counter (or on a counter failure) the fallback budget is returned and
        ``fallback_used=True`` so the runner records it as a covariate.
        """
        n_tokens: int | None = None
        fallback_used = False

        if token_counter is not None:
            try:
                n_tokens = token_counter(reference)
            except Exception:  # noqa: BLE001 - budget is a covariate; fail soft
                fallback_used = True
            else:
                if n_tokens is None or n_tokens < 0:
                    n_tokens = None
                    fallback_used = True
        else:
            fallback_used = True

        if fallback_used or n_tokens is None:
            return BudgetResult(
                budget=self.fallback_budget,
                rule=self.rule,
                reference_tokens=None,
                fallback_used=True,
                capped=False,
                floor_applied=False,
            )

        budget = self.base_tokens + math.ceil(self.multiplier * n_tokens)
        capped = budget >= self.max_budget
        floor_applied = budget <= self.min_budget
        budget = min(self.max_budget, max(self.min_budget, budget))
        return BudgetResult(
            budget=budget,
            rule=self.rule,
            reference_tokens=n_tokens,
            fallback_used=False,
            capped=capped,
            floor_applied=floor_applied,
        )

    def fixed_fallback(self) -> BudgetResult:
        """Deterministic ``RULE_FIXED_FALLBACK`` result (no counter needed)."""
        return BudgetResult(
            budget=self.fallback_budget,
            rule="fixed-fallback",
            reference_tokens=None,
            fallback_used=True,
            capped=False,
            floor_applied=False,
        )


DEFAULT_STATIC_BUDGET = StaticBudget()


@dataclass(frozen=True)
class DynamicBudgetStrategy:
    """Parameterized reference-derived budget (Sprint 5A.6).

    The formula is identical to ``StaticBudget``:

        budget_i = min(maximum_budget, max(minimum_budget,
                                          base_budget + ceil(alpha * N_tokens(reference_i))))

    but all four parameters are configurable at construction time, drawn from
    the per-family calibration in ``docs/research/generation_policy_calibration_5A5.md``
    rather than from hardcoded protocol constants. A ``DynamicBudgetStrategy``
    instance is immutable; the same ``reference`` and ``token_counter`` always
    yield the same ``BudgetResult``.

    ``rule`` renders a human-readable description of the actual constants in use.
    """

    base_budget: int
    alpha: float
    minimum_budget: int
    maximum_budget: int
    fallback_budget: int = BUDGET_FALLBACK

    @property
    def rule(self) -> str:
        return BUDGET_RULE_TEMPLATE.format(
            max_budget=self.maximum_budget,
            min_budget=self.minimum_budget,
            base_tokens=self.base_budget,
            multiplier=_format_number(self.alpha),
        )

    def compute(
        self,
        reference: str,
        token_counter: TokenCounter | None = None,
    ) -> BudgetResult:
        """Compute ``budget_i`` for one reference (same formula as
        ``StaticBudget.compute``)."""
        n_tokens: int | None = None
        fallback_used = False

        if token_counter is not None:
            try:
                n_tokens = token_counter(reference)
            except Exception:  # noqa: BLE001 - budget is a covariate; fail soft
                fallback_used = True
            else:
                if n_tokens is None or n_tokens < 0:
                    n_tokens = None
                    fallback_used = True
        else:
            fallback_used = True

        if fallback_used or n_tokens is None:
            return BudgetResult(
                budget=self.fallback_budget,
                rule=self.rule,
                reference_tokens=None,
                fallback_used=True,
                capped=False,
                floor_applied=False,
            )

        budget = self.base_budget + math.ceil(self.alpha * n_tokens)
        capped = budget >= self.maximum_budget
        floor_applied = budget <= self.minimum_budget
        budget = min(self.maximum_budget, max(self.minimum_budget, budget))
        return BudgetResult(
            budget=budget,
            rule=self.rule,
            reference_tokens=n_tokens,
            fallback_used=False,
            capped=capped,
            floor_applied=floor_applied,
        )

    def fixed_fallback(self) -> BudgetResult:
        """Deterministic ``RULE_FIXED_FALLBACK`` result (no counter needed)."""
        return BudgetResult(
            budget=self.fallback_budget,
            rule="fixed-fallback",
            reference_tokens=None,
            fallback_used=True,
            capped=False,
            floor_applied=False,
        )