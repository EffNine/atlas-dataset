#!/usr/bin/env python3
"""
clean_dataset.py — Atlas data cleaning stage.

Reads raw JSONL records (loosely structured) and normalizes them into the
canonical Atlas record format defined by schemas/dataset_schema.json.

Design goals:
  * Stdlib only (no pip installs) so the pipeline runs anywhere.
  * Non-destructive: never touches raw/ inputs; writes to a new output file.
  * Idempotent: re-running on already-clean data yields equivalent records
    (minus auto-assigned ids, which are stable given the same input order).

Cleaning operations performed:
  1. Unicode normalization (NFC).
  2. Whitespace collapse + strip on all text fields.
  3. Control-character stripping (except newlines/tabs).
  4. Drop empty/invalid records with a logged reason.
  5. Best-effort coercion of common field shapes into the canonical schema.
  6. Assign a canonical id when missing, using <category>_<subcategory>_<seq>.
  7. Normalize tags (lowercase, hyphenate spaces/underscores).
  8. Coerce quality_score into 0-10 int; verified into bool.

Usage:
  python scripts/clean_dataset.py --input raw/generated/draft.jsonl \
                                  --output tmp/cleaned.jsonl [--category 04_ai_machine_learning]

The cleaner does NOT validate against the JSON Schema (that is validate_dataset.py),
but it guarantees structural shape so validation is meaningful.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

VALID_CATEGORIES = {
    "01_foundation", "02_software_engineering", "03_system_engineering",
    "04_ai_machine_learning", "05_hardware_engineering", "06_science_engineering",
    "07_business_knowledge", "08_creative_knowledge", "09_personal_assistant",
}
VALID_TYPES = {"instruction", "conversation", "qa", "reasoning"}
VALID_ROLES = {"system", "user", "assistant", "tool"}

_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS_RE = re.compile(r"[ \t]+")
_TAG_RE = re.compile(r"[^a-z0-9]+")


def clean_text(text) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    text = unicodedata.normalize("NFC", text)
    text = _CTRL_RE.sub("", text)
    # collapse internal whitespace; keep paragraph breaks (newlines) intact
    text = "\n".join(_WS_RE.sub(" ", line).strip() for line in text.split("\n"))
    return text.strip()


def normalize_tag(tag) -> str:
    if not isinstance(tag, str):
        tag = str(tag)
    tag = tag.strip().lower()
    tag = _TAG_RE.sub("-", tag)
    return tag.strip("-")


def coerce_messages(raw) -> list[dict]:
    """Coerce a variety of input shapes into canonical messages list."""
    out = []
    if isinstance(raw, list):
        for m in raw:
            if not isinstance(m, dict):
                continue
            role = m.get("role", m.get("from"))  # ShareGPT uses 'from'
            content = m.get("content", m.get("value", m.get("text")))
            if role is None or content is None:
                continue
            role = str(role).lower().strip()
            if role not in VALID_ROLES:
                # map common sharegpt roles
                role = {"human": "user", "gpt": "assistant"}.get(role, role)
            if role not in VALID_ROLES:
                continue
            out.append({"role": role, "content": clean_text(content)})
    elif isinstance(raw, dict):
        # Alpaca-style instruction/input/output
        instr = clean_text(raw.get("instruction"))
        inp = clean_text(raw.get("input"))
        outp = clean_text(raw.get("output"))
        if instr:
            user = instr + (f"\n\n{inp}" if inp else "")
            out.append({"role": "user", "content": user})
        if outp:
            out.append({"role": "assistant", "content": outp})
    return out


def coerce_source(raw, default_category) -> dict:
    if isinstance(raw, dict):
        name = clean_text(raw.get("name") or raw.get("source") or "unknown")
        url = clean_text(raw.get("url", ""))
        license_ = clean_text(raw.get("license", "unknown"))
        date = clean_text(raw.get("date", ""))
    else:
        name = "unknown"
        url = ""
        license_ = "unknown"
        date = ""
    return {
        "name": name or "unknown",
        "url": url,
        "license": license_ or "unknown",
        "date": date,
    }


def build_record(raw: dict, seq: int, default_category: str | None) -> tuple[dict | None, str | None]:
    if not isinstance(raw, dict):
        return None, "record is not an object"

    category = clean_text(raw.get("category", default_category or ""))
    if not category:
        return None, "missing category"
    # accept both "04_ai_machine_learning" and "ai_machine_learning"
    if category not in VALID_CATEGORIES:
        maybe = f"{category}" if category[:2].isdigit() else None
        # try to prefix-match
        for c in VALID_CATEGORIES:
            if c == category or c.endswith(category) or category.endswith(c.split("_", 1)[1]):
                category = c
                break
        else:
            return None, f"unknown category: {category}"

    subcategory = clean_text(raw.get("subcategory", "")) or "general"
    rtype = clean_text(raw.get("type", ""))
    if rtype not in VALID_TYPES:
        rtype = "qa"

    messages = coerce_messages(raw.get("messages", raw))
    # also accept top-level instruction/response shorthand
    if not messages and raw.get("prompt") and raw.get("completion"):
        messages = [
            {"role": "user", "content": clean_text(raw["prompt"])},
            {"role": "assistant", "content": clean_text(raw["completion"])},
        ]
    if len(messages) < 2 or not any(m["role"] == "user" for m in messages) \
            or not any(m["role"] == "assistant" for m in messages):
        return None, "insufficient valid message turns"

    rid = clean_text(raw.get("id", ""))
    if not rid:
        rid = f"{category}_{subcategory}_{seq:04d}"

    try:
        q = int(round(float(raw.get("quality_score", 0) or 0)))
    except (TypeError, ValueError):
        q = 0
    q = max(0, min(10, q))

    verified = bool(raw.get("verified", False))

    tags = []
    for t in raw.get("tags", []) or []:
        nt = normalize_tag(t)
        if nt and nt not in tags:
            tags.append(nt)

    lang = clean_text(raw.get("language", "en")) or "en"
    try:
        diff = int(raw.get("difficulty", 0) or 0)
    except (TypeError, ValueError):
        diff = 0
    diff = max(0, min(3, diff))

    notes = clean_text(raw.get("notes", ""))

    out = {
        "id": rid,
        "category": category,
        "subcategory": subcategory,
        "type": rtype,
        "source": coerce_source(raw.get("source"), category),
        "messages": messages,
        "language": lang,
        "difficulty": diff,
        "tags": tags,
        "quality_score": q,
        "verified": verified,
        "notes": notes,
    }
    return out, None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Clean raw Atlas JSONL into canonical form.")
    ap.add_argument("--input", required=True, help="input JSONL (raw draft)")
    ap.add_argument("--output", required=True, help="output JSONL (cleaned)")
    ap.add_argument("--category", default=None, help="default category if records omit one")
    ap.add_argument("--fail-on-error", action="store_true", help="exit non-zero if any record dropped")
    args = ap.parse_args(argv)

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"[clean] ERROR: input not found: {in_path}", file=sys.stderr)
        return 2

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    kept, dropped = 0, 0
    with in_path.open(encoding="utf-8") as fin, out_path.open("w", encoding="utf-8") as fout:
        for i, line in enumerate(fin, 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as e:
                dropped += 1
                print(f"[clean] line {i}: invalid JSON ({e})", file=sys.stderr)
                continue
            rec, reason = build_record(raw, kept + 1, args.category)
            if rec is None:
                dropped += 1
                print(f"[clean] line {i}: dropped ({reason})", file=sys.stderr)
                continue
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            kept += 1

    print(f"[clean] done. kept={kept} dropped={dropped} -> {out_path}")
    return 2 if (args.fail_on_error and dropped) else 0


if __name__ == "__main__":
    raise SystemExit(main())
