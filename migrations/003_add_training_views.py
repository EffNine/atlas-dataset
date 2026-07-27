#!/usr/bin/env python3
"""Migration 003 — add training-view eligibility.

Marks which future training views (qwen/llama/deepseek) each object can support.
This drives training_views/ placeholder generation; it does NOT write training
data, only eligibility flags. Idempotent.
"""
MIGRATION_ID = "003_add_training_views"
DEPENDS_ON = ["001_initial_schema", "002_add_lineage"]
IDEMPOTENT = True

# Categories well-suited to instruction-style chat SFT across all three views.
ALL_VIEWS = ("qwen", "llama", "deepseek")


def up(record: dict) -> dict:
    tve = record.get("training_view_eligibility")
    if not isinstance(tve, dict):
        tve = {}
    for v in ALL_VIEWS:
        # default: eligible unless explicitly disabled
        tve.setdefault(v, True)
    # code/reasoning objects are eligible everywhere; creative may be limited
    # but kept eligible for pilot parity.
    record["training_view_eligibility"] = tve
    # keep lineage.training_view in sync
    eligible = [v for v in ALL_VIEWS if tve.get(v)]
    record.setdefault("lineage", {})["training_view"] = ",".join(eligible)
    return record
