#!/usr/bin/env python3
"""Training View Builder v1.8 — materialize model-family views from Atlas records.

Wraps ``convert_format.py`` templates and optionally consults
``training_view_engine`` filters for production (approved) paths.

Staging mode (``allow_staging=True``) builds views from ETL transformed
records even when ``verified`` is false — for pipeline prove-out only.
Production mode requires approved curated records.

Writes under ``metadata/views/<version>/`` by default (never curated/).
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# scripts/ on path for convert_format + training_view_engine
_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import convert_format as _cf  # noqa: E402
from etl.types import read_jsonl, utc_now, write_jsonl  # noqa: E402

# Model family → convert_format template key
MODEL_FORMATS: dict[str, str] = {
    "qwen": "qwen_chatml",
    "llama": "llama_instruction",
    "deepseek": "qwen_chatml",  # DeepSeek uses ChatML-compatible formatting
    "mistral": "mistral_instruct",
    "gemma": "gemma_instruct",
    "sharegpt": "sharegpt",
    "alpaca": "alpaca",
}


@dataclass
class ViewBuildResult:
    version: str
    status: str
    summary: str
    models: list[str] = field(default_factory=list)
    record_count: int = 0
    views: dict[str, Any] = field(default_factory=dict)
    eval_count: int = 0
    output_dir: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    mode: str = "staging"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_records(
    root: Path,
    *,
    source_ids: list[str] | None,
    curated_version: str | None,
    prefer_transformed: bool,
) -> tuple[list[dict[str, Any]], str]:
    """Load atlas-shaped records from ETL staging or curated release."""
    if curated_version:
        curated = root / "curated" / curated_version
        rows: list[dict[str, Any]] = []
        if curated.exists():
            for fp in sorted(curated.rglob("*.jsonl")):
                rows.extend(read_jsonl(fp))
        return rows, f"curated/{curated_version}"

    source_ids = source_ids or []
    if not source_ids:
        etl_root = root / "metadata" / "etl"
        if etl_root.exists():
            source_ids = sorted(p.name for p in etl_root.iterdir() if p.is_dir())

    rows = []
    labels = []
    for sid in source_ids:
        etl_dir = root / "metadata" / "etl" / sid
        if prefer_transformed and (etl_dir / "transformed_atlas.jsonl").exists():
            path = etl_dir / "transformed_atlas.jsonl"
        elif (etl_dir / "atlas_staging.jsonl").exists():
            path = etl_dir / "atlas_staging.jsonl"
        else:
            continue
        part = read_jsonl(path)
        rows.extend(part)
        labels.append(f"{sid}:{path.name}:{len(part)}")
    return rows, ",".join(labels) or "none"


def _is_production_eligible(rec: dict[str, Any], quality_threshold: int) -> bool:
    if rec.get("verification_status") == "approved" or rec.get("verified") is True:
        pass
    else:
        return False
    try:
        score = int(rec.get("quality_score") or 0)
    except (TypeError, ValueError):
        return False
    return score >= quality_threshold


def _holdout_split(
    records: list[dict[str, Any]],
    *,
    eval_ratio: float = 0.1,
    seed: str = "atlas-v1.8",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deterministic holdout split by id hash."""
    if not records or eval_ratio <= 0:
        return records, []
    scored = []
    for rec in records:
        h = hashlib.sha256(f"{seed}:{rec.get('id')}".encode()).hexdigest()
        scored.append((h, rec))
    scored.sort(key=lambda x: x[0])
    n_eval = max(1, int(len(scored) * eval_ratio)) if len(scored) >= 10 else 0
    eval_set = [r for _, r in scored[:n_eval]]
    train_set = [r for _, r in scored[n_eval:]]
    return train_set, eval_set


def _render_records(records: list[dict[str, Any]], format_key: str) -> list[str]:
    templates = _cf.load_templates()
    if format_key not in templates["formats"]:
        raise ValueError(f"unknown format {format_key}")
    fmt = templates["formats"][format_key]
    builder = fmt.get("builder")
    lines: list[str] = []
    for rec in records:
        if not rec.get("messages"):
            continue
        try:
            if builder in ("chatml", "llama"):
                out = _cf.render_chatml(rec, fmt, raw=False)
            elif builder == "gemma":
                out = _cf.render_gemma(rec, fmt)
            elif builder == "sharegpt":
                out = _cf.render_sharegpt(rec, fmt)
            elif builder == "alpaca":
                out = _cf.render_alpaca(rec, fmt)
                if not out:
                    continue
            else:
                continue
            lines.append(out)
        except Exception:
            continue
    return lines


def build_views(
    root: str | Path,
    *,
    version: str,
    models: list[str] | None = None,
    source_ids: list[str] | None = None,
    curated_version: str | None = None,
    allow_staging: bool = True,
    quality_threshold: int = 7,
    eval_ratio: float = 0.1,
    limit: int | None = None,
) -> ViewBuildResult:
    root = Path(root).resolve()
    models = models or ["qwen", "llama", "deepseek"]
    out_dir = root / "metadata" / "views" / version
    out_dir.mkdir(parents=True, exist_ok=True)

    result = ViewBuildResult(
        version=version,
        status="passed",
        summary="",
        models=list(models),
        output_dir=str(out_dir),
        mode="staging" if allow_staging and not curated_version else "production",
    )

    records, source_label = _load_records(
        root,
        source_ids=source_ids,
        curated_version=curated_version,
        prefer_transformed=True,
    )
    if limit is not None:
        records = records[: int(limit)]

    if not records:
        result.status = "failed"
        result.errors.append(f"no records loaded ({source_label})")
        result.summary = "View build failed: no records"
        return result

    if not allow_staging or curated_version:
        before = len(records)
        records = [r for r in records if _is_production_eligible(r, quality_threshold)]
        if not records:
            result.status = "blocked"
            result.errors.append(
                f"BLOCKED: 0/{before} records approved with quality>={quality_threshold}"
            )
            result.summary = "View build blocked: no approved curated records"
            result.warnings.append(source_label)
            return result
        result.warnings.append(f"production filter kept {len(records)}/{before}")
    else:
        result.warnings.append(
            "staging mode: building views from unverified ETL records"
        )

    train_recs, eval_recs = _holdout_split(records, eval_ratio=eval_ratio)
    result.record_count = len(train_recs)
    result.eval_count = len(eval_recs)

    # Canonical snapshot for the view package
    snapshot_path = out_dir / "canonical_train.jsonl"
    write_jsonl(snapshot_path, train_recs)
    eval_path = out_dir / "eval_holdout.jsonl"
    write_jsonl(eval_path, eval_recs)

    views_meta: dict[str, Any] = {}
    for model in models:
        format_key = MODEL_FORMATS.get(model)
        if not format_key:
            result.warnings.append(f"unknown model '{model}' skipped")
            continue
        model_dir = out_dir / model
        model_dir.mkdir(parents=True, exist_ok=True)
        lines = _render_records(train_recs, format_key)
        out_file = model_dir / "train.jsonl"
        out_file.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        checksum = _sha256_file(out_file) if out_file.exists() else ""
        views_meta[model] = {
            "format": format_key,
            "path": str(out_file.relative_to(root)),
            "records": len(lines),
            "checksum_sha256": checksum,
        }

    manifest = {
        "version": version,
        "generated_at": utc_now(),
        "mode": result.mode,
        "source": source_label,
        "train_records": len(train_recs),
        "eval_records": len(eval_recs),
        "models": views_meta,
        "canonical_train": {
            "path": str(snapshot_path.relative_to(root)),
            "checksum_sha256": _sha256_file(snapshot_path),
        },
        "eval_holdout": {
            "path": str(eval_path.relative_to(root)),
            "checksum_sha256": _sha256_file(eval_path) if eval_recs else "",
            "records": len(eval_recs),
        },
        "quality_threshold": quality_threshold,
        "allow_staging": allow_staging,
    }
    (out_dir / "view_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    result.views = views_meta
    result.summary = (
        f"Views {version}: train={len(train_recs)} eval={len(eval_recs)} "
        f"models={','.join(views_meta.keys())}"
    )
    return result
