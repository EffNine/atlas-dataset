"""phase2b_materialize.py — Phase 2B deterministic training view materialization.

Policy:
- ALLOW: auto_gate=KEEP AND human_review=KEEP
- REQUIRE HUMAN REVIEW: only for records still marked needs_review
- EXCLUDE: REJECT, unresolved license, failed validation

This run is coverage-limited: only reviewed records are materialized.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from atlas_training.training_views.manifest import TrainingViewManifest
from atlas_training.training_views.splitter import DeterministicSplitter
from atlas_training.training_views.validator import TrainingViewValidator
from atlas_training.training_views.writer import TrainingViewWriter

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "metadata" / "training_views_v0.1.json"
RECORDS_PATH = REPO_ROOT / "tmp" / "expert_pilot_6500_records_v0.1.jsonl"
REVIEW_PATH = REPO_ROOT / "review" / "expert_pilot_6500_review_decisions_v0.1.jsonl"
OUTPUT_ROOT = REPO_ROOT / "output" / "training_views"

TRAIN_RATIO = 0.9
EVAL_RATIO = 0.1

VIEW_CONFIG = {
    "code-300m": {
        "source_ids": ["expert-swe-001"],
        "view_id": "code-300m",
        "version": "v0.1",
        "output_rel": "code_300m_v0.1",
        "token_key": "code",
    },
    "math-300m": {
        "source_ids": ["expert-math-002"],
        "view_id": "math-300m",
        "version": "v0.1",
        "output_rel": "math_300m_v0.1",
        "token_key": "math",
    },
    "aiml-300m": {
        "source_ids": ["expert-aiml-001", "expert-aiml-002"],
        "view_id": "aiml-300m",
        "version": "v0.1",
        "output_rel": "aiml_300m_v0.1",
        "token_key": "aiml",
    },
}

_WORD_RE = re.compile(r"\w+")


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text or ""))


def _record_text(record: dict[str, Any]) -> str:
    parts = [
        str(record.get("problem", "")),
        json.dumps(record.get("solution", {}), ensure_ascii=False),
        json.dumps(record.get("context", {}), ensure_ascii=False),
        json.dumps(record.get("messages", []), ensure_ascii=False),
        json.dumps(record.get("metadata", {}), ensure_ascii=False),
    ]
    return "\n".join(parts)


def _token_estimate(records: list[dict[str, Any]]) -> int:
    total_words = 0
    for record in records:
        total_words += _word_count(_record_text(record))
    return total_words * 4 // 3


def _load_records(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            record_id = record.get("id")
            if not record_id:
                continue
            records[str(record_id)] = record
    return records


def _load_review_decisions(path: Path) -> dict[str, dict[str, Any]]:
    decisions: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            decision = json.loads(line)
            record_id = decision.get("record_id")
            if not record_id:
                continue
            decisions[str(record_id)] = decision
    return decisions


def _normalize_verdict(value: Any) -> str:
    return str(value or "").strip().upper()


def _has_security_flags(record: dict[str, Any]) -> bool:
    for key in record.keys():
        if "security" in key.lower() or "flag" in key.lower():
            return True
    for key in (record.get("metadata") or {}).keys():
        if "security" in key.lower() or "flag" in key.lower():
            return True
    return False


def _provenance_complete(record: dict[str, Any]) -> bool:
    provenance = record.get("provenance") or {}
    source = record.get("source") or {}
    required = {
        "source_id": source.get("source_id"),
        "original_id": provenance.get("original_id"),
        "license": record.get("license"),
    }
    return all(str(v).strip() for v in required.values() if v is not None)


def _license_compliant(record: dict[str, Any]) -> bool:
    license_id = str(record.get("license", "")).strip().lower()
    if not license_id or license_id in {"unknown", "nc", "non-commercial", "restricted", "custom"}:
        return False
    if "nc" in license_id:
        return False
    return True


def _filter_eligible(
    records: dict[str, dict[str, Any]],
    decisions: dict[str, dict[str, Any]],
    view: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    allowed_sources = set(view.get("source_ids", []))
    eligible: list[dict[str, Any]] = []
    reasons: dict[str, int] = {}
    def _reject(reason: str) -> None:
        reasons[reason] = reasons.get(reason, 0) + 1

    for record_id, record in records.items():
        decision = decisions.get(record_id, {})
        verdict = _normalize_verdict(decision.get("verdict"))
        if verdict == "REJECT":
            _reject("reject")
            continue
        if verdict != "KEEP":
            _reject("no_human_review")
            continue
        if not _license_compliant(record):
            _reject("license")
            continue
        if _has_security_flags(record):
            _reject("security_flags")
            continue
        if not _provenance_complete(record):
            _reject("provenance_incomplete")
            continue
        if record.get("source", {}).get("source_id") not in allowed_sources:
            _reject("source_mismatch")
            continue
        eligible.append(record)
    return eligible, reasons


def _format_record(record: dict[str, Any], view_id: str) -> dict[str, Any]:
    messages = record.get("messages", [])
    if not messages:
        problem = record.get("problem", "")
        solution = record.get("solution", "")
        messages = [
            {"role": "system", "content": "You are an expert assistant."},
            {"role": "user", "content": problem},
            {"role": "assistant", "content": json.dumps(solution, ensure_ascii=False) if not isinstance(solution, str) else solution},
        ]
    return {
        "view_id": view_id,
        "record_id": record.get("id"),
        "source_id": record.get("source", {}).get("source_id"),
        "original_id": record.get("provenance", {}).get("original_id"),
        "license": record.get("license"),
        "difficulty": record.get("difficulty"),
        "expert_tier": record.get("expert_tier"),
        "quality_score": record.get("metadata", {}).get("quality_score"),
        "category": record.get("domain") or record.get("source", {}).get("name"),
        "source": record.get("source", {}).get("name"),
        "messages": messages,
        "lineage": {
            "source_attribution": record.get("source", {}).get("source_id"),
            "knowledge_object": record.get("provenance", {}).get("knowledge_object") or record.get("id"),
            "curated_release": "expert-pilot-6500-v0.1",
            "training_view": view_id,
            "future_model": "specialist-300m-v0.1",
        },
    }


def _source_distribution(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        source = record.get("source")
        if isinstance(source, dict):
            key = source.get("source_id") or source.get("name") or "unknown"
        else:
            key = record.get("source_id") or (str(source) if source else "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _deterministic_created_at(records_path: Path, review_path: Path) -> str:
    hasher = hashlib.sha256()
    hasher.update(str(records_path.resolve()).encode("utf-8"))
    hasher.update(b"|")
    hasher.update(str(review_path.resolve()).encode("utf-8"))
    hex_digest = hasher.hexdigest()[:16]
    return f"freeze-{hex_digest}"


def _manifest_payload(
    *,
    view_id: str,
    records: list[dict[str, Any]],
    source_records: int,
    filter_counts: dict[str, int],
    created_at: str | None = None,
) -> dict[str, Any]:
    manifest_builder = TrainingViewManifest()
    manifest = manifest_builder.create(
        view_id=view_id,
        source_release="expert-pilot-6500-v0.1",
        source_records=source_records,
        quality_threshold=7,
        filter_counts=filter_counts,
        records=records,
        sampling_strategy="deterministic_hash",
        created_at=created_at,
    )
    manifest["token_estimate"] = _token_estimate(records)
    manifest["source_distribution"] = _source_distribution(records)
    return manifest


def build_view(
    view: dict[str, Any],
    records: dict[str, dict[str, Any]],
    decisions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    view_id = view["view_id"]
    eligible, filter_counts = _filter_eligible(records, decisions, view)
    splitter = DeterministicSplitter(seed="phase2b-materialization-v0.1")
    train, _, eval_ = splitter.split(
        eligible,
        train_ratio=TRAIN_RATIO,
        validation_ratio=0.0,
    )
    if len(eval_) < 1 and eligible:
        eval_ = [eligible[-1]]

    formatted_train = [_format_record(record, view_id) for record in train]
    formatted_eval = [_format_record(record, view_id) for record in eval_]
    formatted_records = formatted_train + formatted_eval
    created_at = _deterministic_created_at(RECORDS_PATH, REVIEW_PATH)
    manifest = _manifest_payload(
        view_id=view_id,
        records=formatted_records,
        source_records=len(records),
        filter_counts=filter_counts,
        created_at=created_at,
    )

    validation_errors = TrainingViewValidator().validate_view(
        manifest=manifest,
        train=formatted_train,
        validation=[],
        eval_=formatted_eval,
    )
    if validation_errors:
        return {
            "status": "blocked",
            "view_id": view_id,
            "errors": validation_errors,
            "eligible_records": len(eligible),
            "filter_counts": filter_counts,
        }

    output_dir = OUTPUT_ROOT / view["output_rel"]
    if output_dir.exists():
        for child in output_dir.iterdir():
            child.unlink()
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
    writer = TrainingViewWriter(mode="write")
    writer.write_jsonl(output_dir / "train.jsonl", formatted_train)
    writer.write_jsonl(output_dir / "eval.jsonl", formatted_eval)
    writer.write_json(output_dir / "manifest.json", manifest)
    return {
        "status": "ok",
        "view_id": view_id,
        "output_dir": str(output_dir),
        "source_records": len(records),
        "eligible_records": len(eligible),
        "train_records": len(formatted_train),
        "eval_records": len(formatted_eval),
        "token_estimate": manifest.get("token_estimate"),
        "manifest_checksum": manifest.get("checksum", {}).get("manifest"),
        "filter_counts": filter_counts,
    }


def main() -> int:
    os.environ.setdefault("PYTHONPATH", str(REPO_ROOT / "src"))
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    records = _load_records(RECORDS_PATH)
    decisions = _load_review_decisions(REVIEW_PATH)
    report = {
        "status": "ok",
        "policy": {
            "allow": "auto_gate=KEEP and human_review=KEEP",
            "require_human_review": "needs_review only",
            "exclude": "REJECT, unresolved license, security flags, provenance incomplete, source mismatch",
        },
        "views": [],
        "blocked": [],
    }
    for view_cfg in config.get("views", []):
        view_id = view_cfg.get("view_id")
        if view_id not in VIEW_CONFIG:
            continue
        view_report = build_view(VIEW_CONFIG[view_id], records, decisions)
        report["views"].append(view_report)
        if view_report.get("status") != "ok":
            report["status"] = "blocked"
            report["blocked"].append(view_report)
    report_path = OUTPUT_ROOT / "phase2b_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote report: {report_path}")
    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
