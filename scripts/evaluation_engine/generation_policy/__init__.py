"""evaluation_engine.generation_policy — Generation Policy infrastructure
(Sprint 5A.4).

Reusable, immutable, deterministic infrastructure for declaring and recording
the Generation Policy Lock (Protocol v2 §3.6). This package is a pure library:

  * it never loads a model, never runs inference, and never scores,
  * it never reads or writes dataset / eval-set artifacts,
  * it is stdlib-only and fully offline.

Public API:

+-------------------------+------------------------------------------------+
| Symbol                  | Role                                           |
+-------------------------+------------------------------------------------+
| ``GenerationPolicy``    | Immutable per-family generation policy         |
| ``GenerationConfig``    | Immutable locked inference configuration       |
| ``GenerationValidation``| Deterministic policy/config validation gate    |
| ``ValidationResult``    | Immutable validation outcome                   |
| ``GenerationMetadata``  | Policy-lock metadata block builders            |
| ``BudgetStrategy``      | Token-budget strategy interface (Protocol)     |
| ``StaticBudget``        | Reference-derived budget implementation        |
| ``BudgetResult``        | Immutable per-record budget outcome            |
| ``load_policy``         | Strict dict loading (version-aware)            |
| ``load_config``         | Strict dict loading (version-aware)            |
| ``load_policy_file``    | JSON file loading for policies                 |
| ``load_config_file``    | JSON file loading for configs                  |
| ``family_default_policy`` | Canonical policy for a family                |
| ``default_generation_config`` | Canonical locked config                 |
+-------------------------+------------------------------------------------+

Version support: every serializable artifact carries a ``schema_version`` /
``version``; unsupported versions and unknown keys are rejected (fail closed).
"""

from .budget import (
    DEFAULT_STATIC_BUDGET,
    BudgetResult,
    BudgetStrategy,
    DynamicBudgetStrategy,
    StaticBudget,
    TokenCounter,
)
from .config import GenerationConfig
from .metadata import GenerationMetadata
from .policy import GenerationPolicy
from .schema import (
    default_generation_config,
    family_default_policy,
    load_config,
    load_config_file,
    load_policy,
    load_policy_file,
    write_config_file,
    write_policy_file,
)
from .validation import (
    GenerationValidation,
    ValidationResult,
    run_config_validation,
    run_policy_validation,
)
from .versioning import (
    CONFIG_SCHEMA_VERSION,
    GENERATION_POLICY_VERSION,
    POLICY_SCHEMA_VERSION,
    RULE_DYNAMIC_REFERENCE_DERIVED,
    SUPPORTED_BUDGET_RULES,
    SUPPORTED_FAMILIES,
    SUPPORTED_POLICY_VERSIONS,
    SUPPORTED_SAMPLING,
    SUPPORTED_SCHEMA_VERSIONS,
    assert_family_supported,
    assert_policy_version_supported,
    assert_schema_version_supported,
    version_info,
)

__all__ = [
    "DEFAULT_STATIC_BUDGET",
    "BudgetResult",
    "BudgetStrategy",
    "DynamicBudgetStrategy",
    "StaticBudget",
    "TokenCounter",
    "GenerationConfig",
    "GenerationMetadata",
    "GenerationPolicy",
    "GenerationValidation",
    "ValidationResult",
    "default_generation_config",
    "family_default_policy",
    "load_config",
    "load_config_file",
    "load_policy",
    "load_policy_file",
    "run_config_validation",
    "run_policy_validation",
    "write_config_file",
    "write_policy_file",
    "CONFIG_SCHEMA_VERSION",
    "GENERATION_POLICY_VERSION",
    "POLICY_SCHEMA_VERSION",
    "RULE_DYNAMIC_REFERENCE_DERIVED",
    "SUPPORTED_BUDGET_RULES",
    "SUPPORTED_FAMILIES",
    "SUPPORTED_POLICY_VERSIONS",
    "SUPPORTED_SAMPLING",
    "SUPPORTED_SCHEMA_VERSIONS",
    "assert_family_supported",
    "assert_policy_version_supported",
    "assert_schema_version_supported",
    "version_info",
]