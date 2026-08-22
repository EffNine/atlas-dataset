"""Report generation for the 6500 pilot: manifest, records JSONL, quality report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .constants import QUALITY_REPORT_PATH, RECORDS_PATH, MANIFEST_PATH
from .util import sha256_hex, utc_now_iso


def _jsonl_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def write_records(records: list[dict], path: Path | None = None) -> Path:
    """Write converted records as JSONL. Never overwrites silently."""
    out = path or RECORDS_PATH
    if out.exists():
        raise FileExistsError(f"refusing to overwrite existing records file: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return out


def write_manifest(per_source: dict[str, dict], records: list[dict],
                   path: Path | None = None,
                   records_path: Path | None = None) -> Path:
    out = path or MANIFEST_PATH
    if out.exists():
        raise FileExistsError(f"refusing to overwrite existing manifest: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "manifest_name": "expert_pilot_6500_manifest_v0.1",
        "phase": "0.5 pilot extraction (Option A)",
        "generated_at": utc_now_iso(),
        "total_records": len(records),
        "per_source": per_source,
        "records_file": str(records_path or RECORDS_PATH),
        "records_sha256": sha256_hex(
            "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in records)
        ),
        "constraints": ["no training", "no release", "pilot extraction only"],
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return out


def write_quality_report(stats: dict, path: Path | None = None) -> Path:
    """Write the pilot quality report from aggregated stats."""
    out = path or QUALITY_REPORT_PATH
    if out.exists():
        raise FileExistsError(f"refusing to overwrite existing quality report: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    return out
