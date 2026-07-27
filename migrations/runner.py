#!/usr/bin/env python3
"""
migrations/runner.py — Atlas schema migration runner.

Purpose: evolve the canonical Knowledge Object schema over time WITHOUT manually
editing historical records. Each migration in migrations/ is a module exposing:

    MIGRATION_ID = "001_initial_schema"
    DEPENDS_ON  = []            # list of migration ids that must run first
    def up(record: dict) -> dict: ...   # idempotent transform

The runner:
  * loads migrations/ in filename order (001_*, 002_*, ...),
  * applies each migration's up() to every record (idempotent — safe to re-run),
  * records applied migration ids in each record's `lineage.transformations`
    and in a migrations/applied.json state file,
  * never deletes fields; only adds/normalizes. Historical raw/ data is immutable.

Usage:
  python migrations/runner.py --input curated/v0.1/pilot.jsonl --output curated/v0.1/pilot_migrated.jsonl
  python migrations/runner.py --check      # list migrations + applied state
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT / "migrations"
STATE_FILE = MIGRATIONS_DIR / "applied.json"

VALID_CATEGORIES = {
    "01_foundation", "02_software_engineering", "03_system_engineering",
    "04_ai_machine_learning", "05_hardware_engineering", "06_science_engineering",
    "07_business_knowledge", "08_creative_knowledge", "09_personal_assistant",
}


def load_migrations():
    """Return ordered list of (id, module)."""
    mods = []
    for p in sorted(MIGRATIONS_DIR.glob("*.py")):
        if p.name in ("__init__.py", "runner.py"):
            continue
        spec = importlib.util.spec_from_file_location(p.stem, p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mods.append((getattr(mod, "MIGRATION_ID", p.stem), mod))
    return mods


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def apply_record(record: dict, mods) -> tuple[dict, list[str]]:
    applied = list(record.get("lineage", {}).get("transformations", []))
    for mid, mod in mods:
        # idempotent: only apply if not already recorded
        tag = f"migrate:{mid}"
        if tag in applied and getattr(mod, "IDEMPOTENT", True):
            continue
        record = mod.up(record)
        if tag not in applied:
            applied.append(tag)
    return record, applied


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Apply Atlas schema migrations.")
    ap.add_argument("--input", help="JSONL of knowledge objects")
    ap.add_argument("--output", help="output path (migrated)")
    ap.add_argument("--check", action="store_true", help="list migrations + applied state")
    args = ap.parse_args(argv)

    mods = load_migrations()
    state = load_state()

    if args.check:
        print(f"[migrate] discovered {len(mods)} migrations:")
        for mid, _ in mods:
            print(f"  - {mid}  applied={mid in state.get('applied', [])}")
        return 0

    if not args.input or not args.output:
        print("[migrate] ERROR: --input and --output required (or --check)", file=sys.stderr)
        return 2

    records = []
    with open(args.input, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    applied_ids = list(state.get("applied", []))
    for rec in records:
        rec, applied = apply_record(rec, mods)
        rec.setdefault("lineage", {})["transformations"] = applied
        for mid in applied:
            if mid not in applied_ids:
                applied_ids.append(mid)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    save_state({"applied": applied_ids})
    print(f"[migrate] applied {len(mods)} migrations to {len(records)} records -> {out}")
    print(f"[migrate] state: {applied_ids}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
