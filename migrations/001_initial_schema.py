#!/usr/bin/env python3
"""Migration 001 — initial canonical Knowledge Object schema.

Adds the base superset fields required by schemas/knowledge_object_schema.json
when not present. Idempotent: only fills missing fields; never overwrites.
"""
MIGRATION_ID = "001_initial_schema"
DEPENDS_ON = []
IDEMPOTENT = True

VALID_CATEGORIES = {
    "01_foundation", "02_software_engineering", "03_system_engineering",
    "04_ai_machine_learning", "05_hardware_engineering", "06_science_engineering",
    "07_business_knowledge", "08_creative_knowledge", "09_personal_assistant",
}
KNOWN_TYPES = {"fact", "procedure", "concept", "reasoning", "code", "reference", "creative"}


def _default_knowledge_type(rec: dict) -> str:
    cat = rec.get("category", "")
    txt = " ".join(m.get("content", "") for m in rec.get("messages", [])).lower()
    if cat == "02_software_engineering" or "```" in txt:
        return "code"
    if cat in ("06_science_engineering", "05_hardware_engineering"):
        return "concept"
    return "procedure"


def up(record: dict) -> dict:
    # id
    record.setdefault("id", "")
    # category
    if record.get("category") not in VALID_CATEGORIES:
        record["category"] = "01_foundation"
    # subcategory
    record.setdefault("subcategory", "general")
    # difficulty
    try:
        record["difficulty"] = int(record.get("difficulty", 0))
    except (TypeError, ValueError):
        record["difficulty"] = 0
    record["difficulty"] = max(0, min(3, record["difficulty"]))
    # knowledge_type
    if record.get("knowledge_type") not in KNOWN_TYPES:
        record["knowledge_type"] = _default_knowledge_type(record)
    # canonical_answer (extract assistant content)
    if not record.get("canonical_answer"):
        asst = [m.get("content", "") for m in record.get("messages", []) if m.get("role") == "assistant"]
        record["canonical_answer"] = "\n\n".join(asst).strip()
    # metadata
    meta = record.get("metadata")
    if not isinstance(meta, dict):
        meta = {}
    meta.setdefault("language", "en")
    meta.setdefault("synthetic", bool(record.get("source_attribution", {}).get("license", "").startswith("CC-BY-4.0 (generated")))
    record["metadata"] = meta
    # source_attribution (from existing source or empty placeholders)
    sa = record.get("source_attribution")
    if not isinstance(sa, dict):
        src = record.get("source", {})
        sa = {
            "source_id": record.get("lineage", {}).get("source", "") or src.get("name", "unknown"),
            "name": src.get("name", "unknown"),
            "url": src.get("url", ""),
            "license": src.get("license", "unknown"),
            "attribution_text": "",
            "access_date": src.get("date", ""),
            "share_alike": "sa" in str(src.get("license", "")).lower(),
        }
        record["source_attribution"] = sa
    # license (resolved)
    if not record.get("license"):
        record["license"] = record["source_attribution"].get("license", "unknown")
    # tags
    if not isinstance(record.get("tags"), list):
        record["tags"] = []
    # quality_score
    try:
        record["quality_score"] = int(record.get("quality_score", 0))
    except (TypeError, ValueError):
        record["quality_score"] = 0
    record["quality_score"] = max(0, min(10, record["quality_score"]))
    # verification_status
    if record.get("verification_status") not in ("pending", "approved", "rejected", "needs_revision"):
        record["verification_status"] = "pending"
    # verified mirror
    record["verified"] = (record["verification_status"] == "approved")
    # notes
    record.setdefault("notes", "")
    return record
