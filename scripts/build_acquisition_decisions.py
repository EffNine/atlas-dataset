#!/usr/bin/env python3
"""Generate metadata/acquisition_human_decisions.json from actual review decision JSONL."""

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECISION_FILES = [
    ROOT / "review/decisions/batch_001.jsonl",
    ROOT / "review/decisions/v0.2/batch_001.jsonl",
    ROOT / "review/decisions/v0.2/batch_002.jsonl",
]
OUT = ROOT / "metadata/acquisition_human_decisions.json"

DECISION_MAP = {
    "approved": "APPROVE",
    "approve": "APPROVE",
    "accepted": "APPROVE",
    "needs_revision": "DEFER",
    "defer": "DEFER",
    "deferred": "DEFER",
    "rejected": "REJECT",
    "reject": "REJECT",
    "blocked": "REJECT",
}


def load_decisions():
    records = []
    for path in DECISION_FILES:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    continue
                obj.setdefault("_source_file", str(path.relative_to(ROOT)))
                obj.setdefault("_line", i)
                records.append(obj)
    return records


def derive_packet_id(record_id: str):
    parts = record_id.split("_", 1)
    return parts[0] if parts else record_id


def normalize_decisions(raw_records):
    now = datetime.now(timezone.utc).isoformat()
    by_record = {}
    for rec in raw_records:
        record_id = rec.get("record_id") or rec.get("id") or rec.get("packet_id")
        if not record_id:
            continue
        decision = (rec.get("decision") or rec.get("action") or "PENDING").strip()
        normalized = DECISION_MAP.get(decision.lower()) if isinstance(decision, str) else None
        if normalized is None:
            normalized = "PENDING"
        entry = {
            "record_id": record_id,
            "packet_id": derive_packet_id(record_id),
            "decision": normalized,
            "reviewer_id": rec.get("reviewer_id", "unknown"),
            "timestamp": rec.get("timestamp", now),
            "source_file": rec.get("_source_file"),
            "line": rec.get("_line"),
            "reason": rec.get("reason") or rec.get("comment") or "",
        }
        if entry["record_id"] not in by_record:
            by_record[entry["record_id"]] = entry
        else:
            existing_ts = by_record[entry["record_id"]].get("timestamp", "")
            if entry["timestamp"] >= existing_ts:
                by_record[entry["record_id"]] = entry
    return by_record


def aggregate_source_decisions(by_record):
    source_stats = defaultdict(Counter)
    source_first_ts = {}
    source_last_ts = {}
    for entry in by_record.values():
        pid = entry["packet_id"]
        source_stats[pid][entry["decision"]] += 1
        ts = entry["timestamp"]
        source_first_ts.setdefault(pid, ts)
        if ts >= source_last_ts.get(pid, ts):
            source_last_ts[pid] = ts
    source_decisions = {}
    for pid, counter in source_stats.items():
        approved = counter.get("APPROVE", 0)
        deferred = counter.get("DEFER", 0)
        rejected = counter.get("REJECT", 0)
        decision = "PENDING"
        if rejected > 0 and approved == 0:
            decision = "REJECT"
        elif approved > 0 and rejected == 0 and deferred == 0:
            decision = "APPROVE"
        elif approved > 0:
            decision = "APPROVE"
        elif deferred > 0:
            decision = "DEFER"
        source_decisions[pid] = {
            "packet_id": pid,
            "decision": decision,
            "approved_count": approved,
            "deferred_count": deferred,
            "rejected_count": rejected,
            "reviewed_count": sum(counter.values()),
            "first_timestamp": source_first_ts.get(pid),
            "last_timestamp": source_last_ts.get(pid),
        }
    return source_decisions


def build_decision_doc(by_record, source_decisions):
    stats = Counter(v["decision"] for v in by_record.values())
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision_files": sorted({r["source_file"] for r in by_record.values()}),
        "normalization_note": "Decisions normalized from search/decisions JSONL into APPROVE/DEFER/REJECT/PENDING for acquisition.",
        "summary": {
            "total_records": len(by_record),
            "by_decision": {
                "APPROVE": stats.get("APPROVE", 0),
                "DEFER": stats.get("DEFER", 0),
                "REJECT": stats.get("REJECT", 0),
                "PENDING": stats.get("PENDING", 0),
            },
            "total_packets": len(source_decisions),
            "packet_decisions": {
                "APPROVE": sum(1 for v in source_decisions.values() if v["decision"] == "APPROVE"),
                "DEFER": sum(1 for v in source_decisions.values() if v["decision"] == "DEFER"),
                "REJECT": sum(1 for v in source_decisions.values() if v["decision"] == "REJECT"),
                "PENDING": sum(1 for v in source_decisions.values() if v["decision"] == "PENDING"),
            },
        },
        "packets": source_decisions,
        "records": list(by_record.values()),
    }


def main() -> int:
    raw = load_decisions()
    by_record = normalize_decisions(raw)
    source_decisions = aggregate_source_decisions(by_record)
    doc = build_decision_doc(by_record, source_decisions)
    OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote acquisition human decisions to: {OUT}")
    print(json.dumps(doc["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
