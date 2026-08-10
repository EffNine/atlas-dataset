"""schema.py — configuration loading (dict / JSON file).

Central, strict, version-aware loading entry points for ``GenerationPolicy``
and ``GenerationConfig`` (Sprint 5A.4). File loading is deterministic and
offline; both ``load_policy`` and ``load_config`` fail closed on an unknown
schema version or an unknown key rather than silently dropping them.

No frozen asset is read or modified by this module. A caller supplies a path or
a dict; defaults come from the canonical family policy and the canonical locked
configuration.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import GenerationConfig
from .policy import GenerationPolicy
from .versioning import CONFIG_SCHEMA_VERSION


def load_policy(data: dict[str, Any]) -> GenerationPolicy:
    """Deserialize a ``GenerationPolicy`` from a dict (strict, version-aware)."""
    return GenerationPolicy.from_dict(data)


def load_config(data: dict[str, Any]) -> GenerationConfig:
    """Deserialize a ``GenerationConfig`` from a dict (strict, version-aware)."""
    return GenerationConfig.from_dict(data)


def _read_json(path: str | Path) -> dict[str, Any]:
    if not isinstance(path, Path):
        path = Path(path)
    with path.open(encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise TypeError(
            f"expected a JSON object at {str(path)}, got {type(payload).__name__}"
        )
    return payload


def load_policy_file(path: str | Path) -> GenerationPolicy:
    """Load a ``GenerationPolicy`` from a JSON file."""
    return GenerationPolicy.from_dict(_read_json(path))


def load_config_file(path: str | Path) -> GenerationConfig:
    """Load a ``GenerationConfig`` from a JSON file."""
    return GenerationConfig.from_dict(_read_json(path))


def family_default_policy(family: str) -> GenerationPolicy:
    """Canonical ``GenerationPolicy`` for a family (from the shared prompt
    module)."""
    return GenerationPolicy.from_family(family)


def default_generation_config() -> GenerationConfig:
    """Canonical locked ``GenerationConfig`` (Protocol v2 defaults)."""
    return GenerationConfig()


def write_policy_file(policy: GenerationPolicy, path: str | Path) -> None:
    """Serialize a policy to a JSON file (mkdir -p; deterministically)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(policy.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_config_file(config: GenerationConfig, path: str | Path) -> None:
    """Serialize a config to a JSON file (mkdir -p; deterministically)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(config.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def config_schema_version() -> str:
    """Report the current config schema version (declared)."""
    return CONFIG_SCHEMA_VERSION