"""contamination.py — Benchmark contamination audit against training records.

Audits benchmark eval records for overlap with M1/M2/M2' training records at
four levels:
  1. Exact ID overlap
  2. Exact text overlap (problem field)
  3. Normalized text overlap (whitespace-collapsed, lowercased)
  4. Near-duplicate overlap (where existing Atlas dedup infrastructure supports it)

The benchmark is NEVER used as a training source. This is a read-only audit.

Produces: total benchmark records, exact/normalized/near overlaps, records
removed, final clean count, manifest, checksum.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifacts import sha256_file, sha256_text, canonical_json


# --------------------------------------------------------------------------- #
# Overlap detection
# --------------------------------------------------------------------------- #

def normalize_text(text: str) -> str:
    """Normalize text for comparison: collapse whitespace, lowercase."""
    return re.sub(r"\s+", " ", text.strip().lower())


def exact_match(a: str, b: str) -> bool:
    return a.strip() == b.strip()


def normalized_match(a: str, b: str) -> bool:
    return normalize_text(a) == normalize_text(b)


def prefix_overlap(a: str, b: str, min_len: int = 50) -> bool:
    """Check if one text is a substantial prefix/substring of the other."""
    na, nb = normalize_text(a), normalize_text(b)
    if len(na) >= min_len and na in nb:
        return True
    if len(nb) >= min_len and nb in na:
        return True
    return False


# --------------------------------------------------------------------------- #
# Training record loader
# --------------------------------------------------------------------------- #

def load_training_records(subset_path: Path) -> list[dict]:
    """Load training records from a JSONL file."""
    records = []
    with subset_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def get_training_records(root: Path, key: str) -> list[dict]:
    """Get cached training records for a given key."""
    cache_path = root / "metadata" / "_training_cache" / f"{key}.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    loaders = {
        "M1": lambda: load_training_records(
            root / "experiments" / "phase7_scale" / "subsets" / "M1_math_train.jsonl"),
        "M2": lambda: load_training_records(
            root / "experiments" / "phase7_scale" / "subsets" / "M2_math_train.jsonl"),
        "M2PRIME": lambda: load_training_records(
            root / "experiments" / "lora_pilot_math_m2prime_v0.1" / "staged_train.jsonl"),
    }
    records = loaders.get(key, lambda: [])()
    cache_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    return records


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class OverlapRecord:
    """One benchmark record's overlap findings."""
    benchmark_id: str
    problem_text: str
    exact_id_matches: list[str] = field(default_factory=list)
    exact_text_matches: list[str] = field(default_factory=list)
    normalized_matches: list[str] = field(default_factory=list)
    near_duplicate_matches: list[str] = field(default_factory=list)
    removed: bool = False
    removal_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "exact_id_matches": self.exact_id_matches,
            "exact_text_matches": self.exact_text_matches,
            "normalized_matches": self.normalized_matches,
            "near_duplicate_matches": self.near_duplicate_matches,
            "removed": self.removed,
            "removal_reason": self.removal_reason,
        }


class ContaminationAuditor:
    """Audit benchmark records against training sets for contamination."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def audit_record(self, bench_record: dict, training_sets: list[str] | None = None) -> OverlapRecord:
        """Audit a single benchmark record against specified training sets."""
        if training_sets is None:
            training_sets = ["M1", "M2", "M2PRIME"]

        bid = bench_record.get("record_id") or bench_record.get("original_id", "unknown")
        problem = bench_record.get("problem", "")

        exact_ids, exact_texts, normalized, near_dup = [], [], [], []

        for ts in training_sets:
            train_records = get_training_records(self.root, ts)
            for tr in train_records:
                tid = tr.get("id") or tr.get("record_id") or tr.get("original_id", "")
                tproblem = tr.get("problem", "")

                if tid and bid and exact_match(bid, tid):
                    key = f"{ts}:{tid}"
                    if key not in exact_ids:
                        exact_ids.append(key)

                if tproblem and problem and exact_match(problem, tproblem):
                    key = f"{ts}:{tid}"
                    if key not in exact_texts:
                        exact_texts.append(key)

                if tproblem and problem and normalized_match(problem, tproblem):
                    key = f"{ts}:{tid}"
                    if key not in normalized:
                        normalized.append(key)

                if tproblem and problem and prefix_overlap(problem, tproblem):
                    key = f"{ts}:{tid}"
                    if key not in near_dup:
                        near_dup.append(key)

        removed = bool(exact_ids or exact_texts or normalized or near_dup)
        reason_parts = []
        if exact_ids:
            reason_parts.append(f"exact_id:{len(exact_ids)}")
        if exact_texts:
            reason_parts.append(f"exact_text:{len(exact_texts)}")
        if normalized:
            reason_parts.append(f"normalized:{len(normalized)}")
        if near_dup:
            reason_parts.append(f"near_dup:{len(near_dup)}")

        return OverlapRecord(
            benchmark_id=bid, problem_text=problem[:200],
            exact_id_matches=exact_ids, exact_text_matches=exact_texts,
            normalized_matches=normalized, near_duplicate_matches=near_dup,
            removed=removed,
            removal_reason="; ".join(reason_parts) if reason_parts else "",
        )

    def audit_set(self, eval_file: Path, training_sets: list[str] | None = None) -> dict:
        """Audit all records in an eval set. Returns a result dict."""
        records = []
        with eval_file.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))

        if not records:
            return {"n_total": 0, "n_clean": 0, "verdict": "HOLD", "status": "empty"}

        results = [self.audit_record(r, training_sets) for r in records]
        exact_id_count = sum(1 for r in results if r.exact_id_matches)
        exact_text_count = sum(1 for r in results if r.exact_text_matches)
        normalized_count = sum(1 for r in results if r.normalized_matches and not r.exact_text_matches)
        near_dup_count = sum(1 for r in results if r.near_duplicate_matches and not r.normalized_matches)
        removed_count = sum(1 for r in results if r.removed)
        clean_count = len(records) - removed_count

        if exact_id_count > 0 or exact_text_count > 0:
            verdict = "FAIL"
        elif normalized_count > 0:
            verdict = "HOLD"
        elif near_dup_count > 0:
            verdict = "HOLD"
        else:
            verdict = "PASS"

        return {
            "eval_set": str(eval_file),
            "n_total": len(records),
            "n_exact_id": exact_id_count,
            "n_exact_text": exact_text_count,
            "n_normalized": normalized_count,
            "n_near_duplicate": near_dup_count,
            "n_removed": removed_count,
            "n_clean": clean_count,
            "verdict": verdict,
            "per_record": [r.to_dict() for r in results],
            "status": "completed",
        }


def run_contamination_audit(
    eval_file: Path,
    root: Path | None = None,
    training_sets: list[str] | None = None,
    output_path: Path | None = None,
) -> dict:
    """Run a full contamination audit and persist results."""
    if root is None:
        root = Path(__file__).resolve().parent.parent
    auditor = ContaminationAuditor(root)
    result = auditor.audit_set(eval_file, training_sets)

    # Load records for checksum
    records = []
    with eval_file.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    result["audit_id"] = hashlib.sha256(
        f"{eval_file}:{len(records)}:{result['verdict']}".encode()
    ).hexdigest()[:16]
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    result["checksum"] = sha256_text(canonical_json(records))

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    return result
