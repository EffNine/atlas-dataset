"""config.py — GenerationConfig: immutable, locked generation configuration.

A ``GenerationConfig`` is the concrete, run-scoped inference configuration that
pairs with a ``GenerationPolicy``. It is immutable (frozen), strictly typed,
and fails closed on unknowns so a locked run cannot silently pick up a stray
field (Sprint 5A.4 reusable infrastructure).

The default values match the canonical Protocol v2 inference configuration
recorded in the baseline certificate (greedy, seed 42, NF4 + bf16), with the
tokenizer-dependent ``eos/pad`` ids left as ``None`` to be resolved by the
runner at generation time. ``schema_version`` enables version-aware loading.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields
from typing import Any

from .versioning import (
    BUDGET_FALLBACK,
    CONFIG_SCHEMA_VERSION,
    MAX_BUDGET,
    STOP_SEQUENCE,
    assert_schema_version_supported,
)


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class GenerationConfig:
    """Immutable locked generation configuration (inference side).

    Tokens ``eos_token_id`` / ``pad_token_id`` default to ``None``; the
    runner resolves them from the tokenizer at invoke time. If either is
    provided the pad must equal the eos (Generation Policy Lock §4.2).
    """

    schema_version: str = CONFIG_SCHEMA_VERSION
    quantization: str = "4bit_nf4_double_quant"
    compute_dtype: str = "bfloat16"
    sampling: str = "greedy"
    do_sample: bool = False
    seed: int = 42
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    max_budget: int = MAX_BUDGET
    budget_fallback: int = BUDGET_FALLBACK
    stop_sequence: str = STOP_SEQUENCE
    eos_token_id: int | None = None
    pad_token_id: int | None = None
    device_map: str = "auto"
    engine_commit: str | None = None

    # ------------------------------------------------------------------ #
    # Loading / serialization
    # ------------------------------------------------------------------ #
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GenerationConfig":
        """Strict, version-aware deserialization. Unknown keys raise."""
        if not isinstance(data, dict):
            raise TypeError(
                f"GenerationConfig.from_dict expects a dict, got {type(data).__name__}"
            )
        allowed = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - allowed)
        if unknown:
            raise ValueError(f"unknown GenerationConfig keys: {unknown}")

        schema_version = str(data.get("schema_version", CONFIG_SCHEMA_VERSION))
        assert_schema_version_supported(schema_version, artifact="GenerationConfig")

        kwargs: dict[str, Any] = {}
        for field_name in {
            "temperature", "top_p", "top_k", "eos_token_id", "pad_token_id",
            "engine_commit",
        }:
            kwargs[field_name] = data.get(field_name)

        return cls(
            schema_version=schema_version,
            quantization=str(data.get("quantization", "4bit_nf4_double_quant")),
            compute_dtype=str(data.get("compute_dtype", "bfloat16")),
            sampling=str(data.get("sampling", "greedy")),
            do_sample=bool(data.get("do_sample", False)),
            seed=int(data.get("seed", 42)),
            max_budget=int(data.get("max_budget", MAX_BUDGET)),
            budget_fallback=int(data.get("budget_fallback", BUDGET_FALLBACK)),
            stop_sequence=str(data.get("stop_sequence", STOP_SEQUENCE)),
            device_map=str(data.get("device_map", "auto")),
            **kwargs,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "quantization": self.quantization,
            "compute_dtype": self.compute_dtype,
            "sampling": self.sampling,
            "do_sample": self.do_sample,
            "seed": self.seed,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "max_budget": self.max_budget,
            "budget_fallback": self.budget_fallback,
            "stop_sequence": self.stop_sequence,
            "eos_token_id": self.eos_token_id,
            "pad_token_id": self.pad_token_id,
            "device_map": self.device_map,
            "engine_commit": self.engine_commit,
        }

    def sha256(self) -> str:
        return _sha256_hex(_canonical_json(self.to_dict()))

    def to_block(self) -> dict[str, Any]:
        """Serializable config block with a self-hash."""
        block = self.to_dict()
        block["config_sha256"] = self.sha256()
        block["config_block_sha256"] = _sha256_hex(
            _canonical_json({k: v for k, v in block.items() if k != "config_block_sha256"})
        )
        return block