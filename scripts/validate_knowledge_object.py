#!/usr/bin/env python3
"""
validate_knowledge_object.py — validate Atlas Canonical Knowledge Objects.

Knowledge Objects (schemas/knowledge_object_schema.json) are a SUPERSET of the
base canonical record. The base validate_dataset.py deliberately uses
additionalProperties:false, so it will (correctly) reject the superset. This
script validates the superset instead.

Like the rest of the pipeline it is dependency-light: it prefers jsonschema when
available, but always falls back to a thorough STRUCTURAL check so it runs
anywhere (including environments where the jsonschema/referencing native deps
are broken).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from atlas_constants import (
    VALID_CATEGORIES as CATS,
    VALID_KNOWLEDGE_TYPES as KTYPES,
    VERIFICATION_STATUSES as VSTATES,
    VALID_TRAINING_MODELS as TVE,
    VALID_ROLES as ROLES,
)
from atlas_schema import (
    KNOWLEDGE_OBJECT_REQUIRED_FIELDS,
    LINEAGE_SUB_FIELDS,
    QUALITY_SCORE_MIN, QUALITY_SCORE_MAX,
    DIFFICULTY_MIN, DIFFICULTY_MAX,
    MIN_MESSAGE_TURNS,
)

ROOT = Path(__file__).resolve().parents[1]
KO_SCHEMA = ROOT / "schemas" / "knowledge_object_schema.json"


def structural_errors(rec: dict) -> list[str]:
    errs = []
    if not isinstance(rec, dict):
        return ["not an object"]
    miss = [k for k in KNOWLEDGE_OBJECT_REQUIRED_FIELDS if k not in rec]
    if miss:
        errs.append("missing required: " + ",".join(miss))
    if rec.get("category") not in CATS:
        errs.append(f"category invalid: {rec.get('category')!r}")
    if rec.get("knowledge_type") not in KTYPES:
        errs.append(f"knowledge_type invalid: {rec.get('knowledge_type')!r}")
    if rec.get("verification_status") not in VSTATES:
        errs.append(f"verification_status invalid: {rec.get('verification_status')!r}")
    try:
        qs = int(rec.get("quality_score", -1))
        if not (QUALITY_SCORE_MIN <= qs <= QUALITY_SCORE_MAX):
            errs.append("quality_score out of range")
    except (TypeError, ValueError):
        errs.append("quality_score not int")
    try:
        d = int(rec.get("difficulty", -1))
        if not (DIFFICULTY_MIN <= d <= DIFFICULTY_MAX):
            errs.append("difficulty out of range")
    except (TypeError, ValueError):
        errs.append("difficulty not int")
    sa = rec.get("source_attribution")
    if not isinstance(sa, dict) or not sa.get("source_id") or not sa.get("license"):
        errs.append("source_attribution incomplete")
    elif sa.get("share_alike") is True and not str(sa.get("license", "")).lower().startswith("cc-by-sa"):
        errs.append("share_alike flagged but license not CC-BY-SA")
    lic = rec.get("license")
    if not isinstance(lic, str) or not lic or lic.lower() == "unknown":
        errs.append("license missing/unknown")
    lin = rec.get("lineage")
    if not isinstance(lin, dict):
        errs.append("lineage missing")
    else:
        for k in LINEAGE_SUB_FIELDS:
            if k not in lin:
                errs.append(f"lineage.{k} missing")
    tve = rec.get("training_view_eligibility")
    if not isinstance(tve, dict) or set(tve.keys()) != TVE:
        errs.append("training_view_eligibility must be {qwen,llama,deepseek}")
    msgs = rec.get("messages")
    if not isinstance(msgs, list) or len(msgs) < MIN_MESSAGE_TURNS:
        errs.append(f"messages need >= {MIN_MESSAGE_TURNS} turns")
    else:
        seen_u = seen_a = False
        for m in msgs:
            if not isinstance(m, dict) or "role" not in m or "content" not in m:
                errs.append("message missing role/content")
                continue
            if m["role"] not in ROLES:
                errs.append(f"message role invalid: {m['role']!r}")
            if not isinstance(m["content"], str) or not m["content"].strip():
                errs.append("message content empty")
            if m["role"] == "user":
                seen_u = True
            if m["role"] == "assistant":
                seen_a = True
        if not seen_u:
            errs.append("no user turn")
        if not seen_a:
            errs.append("no assistant turn")
    if rec.get("verified") is not (rec.get("verification_status") == "approved"):
        errs.append("verified flag inconsistent with verification_status")
    return errs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Validate Atlas Knowledge Objects.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--strict", action="store_true",
                    help="require verified==True AND quality_score>=8.5 (curated gate)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    path = Path(args.input)
    if not path.exists():
        print(f"[ko] ERROR: not found: {path}", file=sys.stderr)
        return 2

    total = 0
    bad = 0
    try:
        import jsonschema  # type: ignore
        from referencing import Registry, Resource  # type: ignore
        schema = json.loads(KO_SCHEMA.read_text())
        chat = json.loads((ROOT / "schemas" / "chat_schema.json").read_text())
        reg = Registry().with_resources([
            (schema["$id"], Resource.from_contents(schema)),
            (chat["$id"], Resource.from_contents(chat)),
        ])
        validator = jsonschema.Draft202012Validator(schema, registry=reg)
        use_jsonschema = True
    except Exception:
        use_jsonschema = False

    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                bad += 1
                print(f"[ko] line {i}: bad JSON ({e})", file=sys.stderr)
                continue
            if use_jsonschema:
                errs = [f"schema: {e.message}" for e in validator.iter_errors(rec)]
            else:
                errs = structural_errors(rec)
            if args.strict:
                if rec.get("verification_status") != "approved":
                    errs.append("not approved")
                if int(rec.get("quality_score", 0)) < 8.5:
                    errs.append("quality_score < 8.5")
            if errs:
                bad += 1
                if not args.quiet:
                    print(f"[ko] {rec.get('id', f'line{i}')}: {'; '.join(errs)}", file=sys.stderr)

    print(f"[ko] total={total} records_with_errors={bad} mode={'jsonschema' if use_jsonschema else 'structural'}")
    print(f"[ko] RESULT: {'PASS' if bad == 0 else 'FAIL'}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
