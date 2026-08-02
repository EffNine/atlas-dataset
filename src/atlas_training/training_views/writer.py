"""writer.py — Safe JSONL writer for training views."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class TrainingViewWriter:
    """Write training view artifacts safely.

    By default, this writer refuses to write into immutable or
    pre-existing paths. Opt-in write mode is required for explicit
    generation runs.
    """

    def __init__(self, *, mode: str = "safe") -> None:
        if mode not in {"safe", "write"}:
            raise ValueError("mode must be 'safe' or 'write'")
        self.mode = mode

    def write_jsonl(self, path: Path, records: list[dict[str, Any]]) -> Path:
        if self.mode != "write":
            raise PermissionError(
                f"Writer is in {self.mode!r} mode. Set mode='write' to emit artifacts."
            )
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite existing file: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return path

    def write_json(self, path: Path, payload: dict[str, Any]) -> Path:
        if self.mode != "write":
            raise PermissionError(
                f"Writer is in {self.mode!r} mode. Set mode='write' to emit artifacts."
            )
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite existing file: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        return path
