#!/usr/bin/env python3
"""Migration 002 — add complete lineage tracking.

Every Knowledge Object must be traceable: source -> transformations ->
knowledge_object -> curated_dataset -> training_view -> future_model.
Idempotent: builds/normalizes the lineage object; does not overwrite existing
meaningful values unless missing.
"""
MIGRATION_ID = "002_add_lineage"
DEPENDS_ON = ["001_initial_schema"]
IDEMPOTENT = True


def up(record: dict) -> dict:
    lineage = record.get("lineage")
    if not isinstance(lineage, dict):
        lineage = {}
    # source
    if not lineage.get("source"):
        sa = record.get("source_attribution", {})
        lineage["source"] = sa.get("name") or record.get("category", "unknown")
    # transformations (accumulate migration + pipeline tags)
    transforms = list(lineage.get("transformations", []))
    if "migrate:001_initial_schema" not in transforms:
        transforms.append("migrate:001_initial_schema")
    lineage["transformations"] = transforms
    # knowledge_object
    lineage["knowledge_object"] = record.get("id", "")
    # curated_dataset
    lineage.setdefault("curated_dataset", "curated/v0.1")
    # training_view (placeholder string of eligible views)
    tve = record.get("training_view_eligibility", {})
    eligible = [k for k in ("qwen", "llama", "deepseek") if tve.get(k)]
    lineage.setdefault("training_view", ",".join(eligible) if eligible else "qwen,llama,deepseek")
    # future_model
    lineage.setdefault("future_model", "8B-class LLM (Qwen/Llama/DeepSeek/Mistral/Gemma)")
    record["lineage"] = lineage
    return record
