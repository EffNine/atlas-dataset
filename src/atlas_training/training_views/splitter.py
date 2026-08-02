"""splitter.py — Deterministic train / validation / eval splitting."""

from __future__ import annotations

import hashlib
from typing import Any


def _stable_key(record: dict[str, Any], seed: str) -> str:
    rid = record.get("id") or record.get("record_id") or ""
    return hashlib.sha256(f"{seed}:{rid}".encode("utf-8")).hexdigest()


class DeterministicSplitter:
    """Deterministic, reproducible record splitting.

    Sort order is derived from stable hashes over record id and an
    explicit seed, so identical inputs always yield identical splits.
    """

    def __init__(self, seed: str = "atlas-training-views-v0.1") -> None:
        self.seed = seed

    def split(
        self,
        records: list[dict[str, Any]],
        *,
        train_ratio: float = 0.8,
        validation_ratio: float = 0.1,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        if not records:
            return [], [], []
        if train_ratio + validation_ratio > 1.0:
            raise ValueError("train_ratio + validation_ratio must be <= 1.0")

        sorted_records = sorted(records, key=lambda r: _stable_key(r, self.seed))
        n = len(sorted_records)
        n_train = max(1, int(n * train_ratio)) if n >= 10 else n
        n_val = max(1, int(n * validation_ratio)) if n >= 10 else 0
        n_eval = max(0, n - n_train - n_val)

        train = sorted_records[:n_train]
        validation = sorted_records[n_train:n_train + n_val]
        eval_ = sorted_records[n_train + n_val:n_train + n_val + n_eval]
        return train, validation, eval_
