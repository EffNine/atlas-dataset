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

from atlas_constants import VALID_CATEGORIES, VALID_TYPES, VALID_ROLES, is_denied_license
from atlas_schema import (
    ID_PATTERN, TAG_PATTERN, DATE_PATTERN,
    BASE_ALLOWED_KEYS,
    QUALITY_SCORE_MIN, QUALITY_SCORE_MAX,
    DIFFICULTY_MIN, DIFFICULTY_MAX,
    MIN_MESSAGE_TURNS,
)
from atlas_paths import schemas_dir, categories_metadata_path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
CATEGORIES_FILE = ROOT / "metadata" / "categories.json"

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
    if not isinstance(rid, str) or not ID_PATTERN.match(rid):
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
        elif is_denied_license(lic):
            errs.append(f"source.license DENIED by commercial-safety policy: {lic!r} (NC/proprietary/ambiguous -> never ingest)")
        if src.get("date") not in (None, "",) and not (isinstance(src.get("date"), str) and DATE_PATTERN.match(src["date"])):
            errs.append("source.date not ISO-8601 (YYYY-MM-DD)")

    msgs = rec.get("messages")
    if not isinstance(msgs, list) or len(msgs) < MIN_MESSAGE_TURNS:
        errs.append(f"messages must be a list with >= {MIN_MESSAGE_TURNS} turns")
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
            if not isinstance(t, str) or not TAG_PATTERN.match(t):
                errs.append(f"tag invalid: {t!r}")

    qs = rec.get("quality_score")
    if not isinstance(qs, int) or not (QUALITY_SCORE_MIN <= qs <= QUALITY_SCORE_MAX):
        errs.append(f"quality_score must be int {QUALITY_SCORE_MIN}-{QUALITY_SCORE_MAX}: {qs!r}")

    if not isinstance(rec.get("verified"), bool):
        errs.append("verified must be bool")

    lang = rec.get("language", "en")
    if lang != "en" and not (isinstance(lang, str) and re.match(r"^[a-z]{2}(-[A-Z]{2})?$", lang)):
        errs.append(f"language invalid: {lang!r}")

    diff = rec.get("difficulty", 0)
    if diff not in (DIFFICULTY_MIN, DIFFICULTY_MIN + 1, DIFFICULTY_MAX - 1, DIFFICULTY_MAX):
        errs.append(f"difficulty must be {DIFFICULTY_MIN}-{DIFFICULTY_MAX}: {diff!r}")

    if "notes" not in rec or not isinstance(rec.get("notes"), str):
        errs.append("notes missing or not string")

    # extra keys not in schema
    extra = set(rec.keys()) - BASE_ALLOWED_KEYS
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


def load_parallelism_config() -> dict:
    """Load unified parallelism config (config/parallelism.yaml)."""
    cfg_path = ROOT / "config" / "parallelism.yaml"
    try:
        import yaml
        with open(cfg_path, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def validate_one_file(path: Path, strict: bool = False, quiet: bool = False) -> dict:
    """Validate a single JSONL file, returning summary stats.

    Kept self-contained so it can be dispatched to process workers.
    """
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
                print(f"[validate] {path}: line {i}: invalid JSON ({e})", file=sys.stderr)

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
    if strict:
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
            if not quiet:
                print(f"[validate] {path}: {records[idx].get('id', f'line{idx+1}')}: {'; '.join(errs)}", file=sys.stderr)

    return {
        "path": str(path),
        "total": total,
        "bad_json": bad_json,
        "record_errors": record_errors,
    }


def validate_task(task) -> dict:
    """Scheduler worker wrapper: dispatch a Task to validate_one_file.

    Module-level so it can be pickled into ProcessPool workers.
    Task.extra carries strict/quiet flags.
    """
    extra = getattr(task, "extra", {}) or {}
    return validate_one_file(
        Path(task.input),
        strict=bool(extra.get("strict", False)),
        quiet=bool(extra.get("quiet", False)),
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Validate Atlas dataset JSONL.")
    ap.add_argument("--input", required=True, help="JSONL file or glob pattern")
    ap.add_argument("--stats", action="store_true", help="print composition statistics")
    ap.add_argument("--strict", action="store_true", help="enforce curated-stage gate (verified + score>=7 + license!=unknown)")
    ap.add_argument("--quiet", action="store_true", help="only print errors + summary")
    ap.add_argument("--file-workers", type=int, default=None,
                    help="parallel files to validate (default: config validation.file_workers or 1)")
    args = ap.parse_args(argv)

    config = load_parallelism_config()
    file_workers = args.file_workers or config.get("parallelism", {}).get("validation", {}).get("file_workers", 1)

    # Expand glob / single file
    raw = Path(args.input)
    if any(ch in args.input for ch in "*?["):
        files = sorted(raw.parent.glob(raw.name))
    else:
        files = [raw] if raw.exists() else []

    if not files:
        print(f"[validate] ERROR: input not found: {args.input}", file=sys.stderr)
        return 2

    if file_workers > 1 and len(files) > 1:
        # Universal Scheduler pilot: same worker function, scheduler-owned
        # pool. Results are identical to the manual ProcessPoolExecutor path
        # (per-file validate_one_file stats), but the scheduler adds
        # registry resume, adaptive worker limits, and retry.
        try:
            from parallel.models import Task
            from parallel.planner import file_tasks
            from parallel.scheduler import Scheduler

            tasks = file_tasks(files, source="validation", operation="validate_one_file",
                               extra={"strict": args.strict, "quiet": args.quiet})
            sched = Scheduler(
                "validation",
                registry_root=str(ROOT / "metadata" / "pipeline_state"),
                workers=file_workers,
                pool="process",
                max_retries=2,
            )
            print(f"[validate] scheduler: validating {len(files)} files with {sched.workers} adaptive workers...")
            trs = sched.run(tasks, validate_task)
            results = []
            for tr in trs:
                if tr.status == "completed":
                    r = dict(tr.result) if isinstance(tr.result, dict) else {
                        "path": "", "total": 0, "bad_json": 0, "record_errors": 0,
                    }
                    results.append(r)
                elif tr.status == "failed":
                    t = next((t for t in tasks if t.task_id == tr.task_id), None)
                    results.append({
                        "path": t.input if t else tr.task_id,
                        "total": 0, "bad_json": 0, "record_errors": -1, "error": tr.error,
                    })
                else:  # skipped (completed in a prior run)
                    t = next((t for t in tasks if t.task_id == tr.task_id), None)
                    results.append({
                        "path": t.input if t else tr.task_id,
                        "total": 0, "bad_json": 0, "record_errors": 0, "skipped": True,
                    })
        except Exception as sched_exc:
            # Fallback: manual ProcessPoolExecutor (behavior identical).
            print(f"[validate] scheduler unavailable ({sched_exc}); falling back to ProcessPoolExecutor", file=sys.stderr)
            from concurrent.futures import ProcessPoolExecutor, as_completed
            results = []
            with ProcessPoolExecutor(max_workers=file_workers) as ex:
                futures = {ex.submit(validate_one_file, p, args.strict, args.quiet): p for p in files}
                for fut in as_completed(futures):
                    try:
                        results.append(fut.result())
                    except Exception as e:
                        results.append({"path": str(futures[fut]), "total": 0, "bad_json": 0, "record_errors": -1, "error": str(e)})
    else:
        results = [validate_one_file(p, args.strict, args.quiet) for p in files]

    total = sum(r["total"] for r in results)
    bad_json = sum(r["bad_json"] for r in results)
    record_errors = sum(r["record_errors"] for r in results)

    for r in results:
        print(f"[validate] {r['path']}: total={r['total']} bad_json={r['bad_json']} records_with_errors={r['record_errors']}")

    print(f"[validate] FILES={len(files)} TOTAL={total} bad_json={bad_json} records_with_errors={record_errors}")
    ok = (bad_json == 0 and record_errors == 0)
    print(f"[validate] RESULT: {'PASS' if ok else 'FAIL'}")

    if args.stats and len(files) == 1:
        records = []
        with files[0].open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        print_stats(records)

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
