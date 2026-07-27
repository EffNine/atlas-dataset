#!/usr/bin/env python3
"""
validate_dataset.py — Atlas schema + quality-gate validation & stats.

Validates every record in a JSONL file against the canonical Atlas schema
(schemas/dataset_schema.json). Uses the `jsonschema` package when available
for strict checking; otherwise falls back to a built-in structural validator
so the pipeline runs with stdlib only.

Also performs dataset-level checks:
  * duplicate ids
  * exact/normalized duplicate content
  * category/subcategory against metadata/categories.json (if present)
  * curated-stage license prohibition ("unknown")
  * quality gate (quality_score >= 7 and verified == true for curated/)

With --stats, prints a composition report (counts, per-category, score dist).

Usage:
  python scripts/validate_dataset.py --input examples/sample_dataset.jsonl
  python scripts/validate_dataset.py --input curated/v0.1/atlas_v0.1.jsonl --stats --strict
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
CATEGORIES_FILE = ROOT / "metadata" / "categories.json"

VALID_CATEGORIES = {
    "01_foundation", "02_software_engineering", "03_system_engineering",
    "04_ai_machine_learning", "05_hardware_engineering", "06_science_engineering",
    "07_business_knowledge", "08_creative_knowledge", "09_personal_assistant",
}
VALID_TYPES = {"instruction", "conversation", "qa", "reasoning"}
VALID_ROLES = {"system", "user", "assistant", "tool"}
ID_RE = re.compile(r"^[a-z0-9_-]+$")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_CATEGORIES_CACHE: dict | None = None


def load_categories() -> dict:
    global _CATEGORIES_CACHE
    if _CATEGORIES_CACHE is not None:
        return _CATEGORIES_CACHE
    if CATEGORIES_FILE.exists():
        try:
            _CATEGORIES_CACHE = json.loads(CATEGORIES_FILE.read_text(encoding="utf-8")).get("categories", {})
        except Exception:
            _CATEGORIES_CACHE = {}
    else:
        _CATEGORIES_CACHE = {}
    return _CATEGORIES_CACHE


def norm_content(messages) -> str:
    """Normalized signature of an example for duplicate detection."""
    parts = []
    for m in messages:
        parts.append(f"{m['role']}:{m['content'].strip().lower()}")
    return "\n".join(parts)


def structural_errors(rec: dict) -> list[str]:
    errs: list[str] = []
    if not isinstance(rec, dict):
        return ["record is not an object"]

    rid = rec.get("id")
    if not isinstance(rid, str) or not ID_RE.match(rid):
        errs.append("id invalid (must match ^[a-z0-9_]+$)")

    cat = rec.get("category")
    if cat not in VALID_CATEGORIES:
        errs.append(f"category invalid: {cat!r}")

    sub = rec.get("subcategory")
    if not isinstance(sub, str) or not sub:
        errs.append("subcategory missing/empty")
    else:
        cats = load_categories()
        allowed = cats.get(cat, {}).get("subcategories") if cats else None
        if allowed and sub not in allowed:
            errs.append(f"subcategory {sub!r} not in controlled list for {cat}")

    if rec.get("type") not in VALID_TYPES:
        errs.append(f"type invalid: {rec.get('type')!r}")

    src = rec.get("source")
    if not isinstance(src, dict):
        errs.append("source missing")
    else:
        if not isinstance(src.get("name"), str) or not src.get("name"):
            errs.append("source.name missing")
        lic = src.get("license")
        if not isinstance(lic, str) or not lic:
            errs.append("source.license missing")
        if src.get("date") not in (None, "",) and not (isinstance(src.get("date"), str) and DATE_RE.match(src["date"])):
            errs.append("source.date not ISO-8601 (YYYY-MM-DD)")

    msgs = rec.get("messages")
    if not isinstance(msgs, list) or len(msgs) < 2:
        errs.append("messages must be a list with >=2 turns")
    else:
        seen_user = seen_asst = False
        for j, m in enumerate(msgs):
            if not isinstance(m, dict) or "role" not in m or "content" not in m:
                errs.append(f"messages[{j}] missing role/content")
                continue
            if m["role"] not in VALID_ROLES:
                errs.append(f"messages[{j}].role invalid: {m['role']!r}")
            if not isinstance(m["content"], str) or not m["content"].strip():
                errs.append(f"messages[{j}].content empty")
            if m["role"] == "user":
                seen_user = True
            if m["role"] == "assistant":
                seen_asst = True
        if not seen_user:
            errs.append("no user turn")
        if not seen_asst:
            errs.append("no assistant turn")

    tags = rec.get("tags")
    if not isinstance(tags, list):
        errs.append("tags must be a list")
    else:
        for t in tags:
            if not isinstance(t, str) or not TAG_RE.match(t):
                errs.append(f"tag invalid: {t!r}")

    qs = rec.get("quality_score")
    if not isinstance(qs, int) or not (0 <= qs <= 10):
        errs.append(f"quality_score must be int 0-10: {qs!r}")

    if not isinstance(rec.get("verified"), bool):
        errs.append("verified must be bool")

    lang = rec.get("language", "en")
    if lang != "en" and not (isinstance(lang, str) and re.match(r"^[a-z]{2}(-[A-Z]{2})?$", lang)):
        errs.append(f"language invalid: {lang!r}")

    diff = rec.get("difficulty", 0)
    if diff not in (0, 1, 2, 3):
        errs.append(f"difficulty must be 0-3: {diff!r}")

    if "notes" not in rec or not isinstance(rec.get("notes"), str):
        errs.append("notes missing or not string")

    # extra keys not in schema
    allowed_keys = {"id", "category", "subcategory", "type", "source", "messages", "language", "difficulty", "tags", "quality_score", "verified", "notes"}
    extra = set(rec.keys()) - allowed_keys
    if extra:
        errs.append(f"unexpected keys: {sorted(extra)}")

    return errs


def strict_jsonschema(records: list[dict]) -> list[list[str]]:
    """Strict JSON-Schema validation via jsonschema, with OFFLINE resolution
    of the local chat_schema.json reference.

    The canonical schema references chat_schema.json by relative URI, which the
    referencing engine resolves against the schema's $id and would otherwise
    try to fetch over the network. We pre-load both local schema files into a
    referencing Registry so strict validation works fully offline (the README
    guarantees the pipeline runs anywhere without network access).

    On any failure to import jsonschema/referencing, to read the schema files,
    or to build the registry, we return [] so the structural validator (which
    always runs) remains the fallback. This keeps the script robust and keeps
    the 'runs anywhere / no hard dependency' guarantee intact.
    """
    try:
        import jsonschema  # type: ignore
        from referencing import Registry, Resource  # type: ignore
    except Exception:
        return []
    try:
        dataset_schema = json.loads((SCHEMA_DIR / "dataset_schema.json").read_text(encoding="utf-8"))
        chat_schema = json.loads((SCHEMA_DIR / "chat_schema.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    try:
        registry = Registry().with_resources([
            (dataset_schema["$id"], Resource.from_contents(dataset_schema)),
            (chat_schema["$id"], Resource.from_contents(chat_schema)),
        ])
        validator = jsonschema.Draft202012Validator(dataset_schema, registry=registry)
    except Exception:
        # Any ref-resolution problem: degrade to structural validation only.
        return []
    out = []
    for rec in records:
        try:
            e = [f"schema: {err.message}" for err in validator.iter_errors(rec)]
        except Exception:
            e = []
        out.append(e)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Validate Atlas dataset JSONL.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--stats", action="store_true", help="print composition statistics")
    ap.add_argument("--strict", action="store_true", help="enforce curated-stage gate (verified + score>=7 + license!=unknown)")
    ap.add_argument("--quiet", action="store_true", help="only print errors + summary")
    args = ap.parse_args(argv)

    path = Path(args.input)
    if not path.exists():
        print(f"[validate] ERROR: input not found: {path}", file=sys.stderr)
        return 2

    records = []
    bad_json = 0
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                bad_json += 1
                print(f"[validate] line {i}: invalid JSON ({e})", file=sys.stderr)

    total = len(records)
    errors_per_record: list[list[str]] = [[] for _ in records]
    record_errors = 0

    # structural (always)
    for idx, rec in enumerate(records):
        errs = structural_errors(rec)
        errors_per_record[idx].extend(errs)

    # jsonschema (if available) — additive
    for idx, errs in enumerate(strict_jsonschema(records)):
        errors_per_record[idx].extend(errs)

    # duplicate id
    ids = Counter(r.get("id") for r in records)
    dup_ids = {i for i, c in ids.items() if c > 1}
    for idx, rec in enumerate(records):
        if rec.get("id") in dup_ids:
            errors_per_record[idx].append("duplicate id")

    # duplicate content
    seen_hash = {}
    for idx, rec in enumerate(records):
        h = hashlib.sha1(norm_content(rec.get("messages", [])).encode("utf-8")).hexdigest()
        if h in seen_hash:
            errors_per_record[idx].append(f"duplicate content (also id={seen_hash[h]})")
        else:
            seen_hash[h] = rec.get("id")

    # strict gate
    if args.strict:
        for idx, rec in enumerate(records):
            if rec.get("source", {}).get("license") == "unknown":
                errors_per_record[idx].append("curated license must not be 'unknown'")
            if not rec.get("verified"):
                errors_per_record[idx].append("curated record not verified")
            if int(rec.get("quality_score", 0)) < 7:
                errors_per_record[idx].append("curated quality_score < 7")

    for idx, errs in enumerate(errors_per_record):
        if errs:
            record_errors += 1
            if not args.quiet or True:
                print(f"[validate] {records[idx].get('id', f'line{idx+1}')}: {'; '.join(errs)}", file=sys.stderr)

    if args.stats:
        print_stats(records)

    print(f"[validate] total={total} bad_json={bad_json} records_with_errors={record_errors}")
    ok = (bad_json == 0 and record_errors == 0)
    print(f"[validate] RESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def print_stats(records: list[dict]) -> None:
    print("\n=== Atlas Dataset Statistics ===")
    print(f"records: {len(records)}")
    by_cat = Counter(r.get("category") for r in records)
    print("\nper category:")
    for c in sorted(VALID_CATEGORIES):
        print(f"  {c:28s} {by_cat.get(c, 0)}")
    by_type = Counter(r.get("type") for r in records)
    print("\nper type:", dict(by_type))
    scores = [int(r.get("quality_score", 0)) for r in records]
    print(f"quality_score: min={min(scores) if scores else '-'} max={max(scores) if scores else '-'} "
          f"avg={sum(scores)/len(scores):.2f}" if scores else "quality_score: n/a")
    print(f"verified: {sum(1 for r in records if r.get('verified'))}/{len(records)}")
    unk = sum(1 for r in records if r.get('source', {}).get('license') == 'unknown')
    print(f"unknown-license: {unk}")
    # balance vs target
    print("\nbalance vs v0.1 target:")
    target = {
        "01_foundation": 0.10, "02_software_engineering": 0.20, "03_system_engineering": 0.15,
        "04_ai_machine_learning": 0.20, "05_hardware_engineering": 0.08, "06_science_engineering": 0.10,
        "07_business_knowledge": 0.07, "08_creative_knowledge": 0.05, "09_personal_assistant": 0.05,
    }
    n = len(records) or 1
    for c in sorted(VALID_CATEGORIES):
        share = by_cat.get(c, 0) / n
        delta = share - target.get(c, 0)
        flag = "OK" if abs(delta) < 0.05 else ("LOW" if delta < 0 else "HIGH")
        print(f"  {c:28s} {share*100:5.1f}%  target {target.get(c,0)*100:4.0f}%  [{flag}]")


if __name__ == "__main__":
    raise SystemExit(main())
