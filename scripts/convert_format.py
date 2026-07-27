#!/usr/bin/env python3
"""
convert_format.py — Atlas multi-format converter.

Converts canonical Atlas JSONL records into model-specific training formats.
Template definitions live in configs/formatting/templates.json so adding a
future model format is a config edit, not a code change. This is the core of
the model-agnostic mandate: the canonical dataset never changes.

Supported formats (from templates.json):
  qwen_chatml      -> Qwen ChatML text (one rendered conversation per line, JSON-wrapped)
  llama_instruction-> Llama-3 style ChatML with <|begin_of_text|>
  sharegpt         -> {conversations: [{role, content}]} per line
  alpaca           -> {instruction, input, output} per line

All output is JSONL unless --raw is passed for chatml/llama (renders raw text).

Usage:
  python scripts/convert_format.py --format qwen_chatml \
      --input curated/v0.1/atlas_v0.1.jsonl --output tmp/qwen.jsonl
  python scripts/convert_format.py --format llama_instruction \
      --input examples/sample_dataset.jsonl --output tmp/llama.jsonl --raw
  python scripts/convert_format.py --format sharegpt --input examples/sample_dataset.jsonl --output tmp/sharegpt.jsonl
  python scripts/convert_format.py --format alpaca  --input examples/sample_dataset.jsonl --output tmp/alpaca.jsonl
  python scripts/convert_format.py --list
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "configs" / "formatting" / "templates.json"

DEFAULT_SYSTEM = "You are Atlas, a precise and helpful AI assistant."


def load_templates() -> dict:
    if not TEMPLATES.exists():
        print(f"[convert] ERROR: templates not found: {TEMPLATES}", file=sys.stderr)
        raise SystemExit(2)
    return json.loads(TEMPLATES.read_text(encoding="utf-8"))


def render_gemma(rec: dict, fmt: dict) -> str:
    """Render Gemma-style turns: <start_of_turn>user ... <end_of_turn>."""
    user_t = fmt["user_template"]
    asst_t = fmt["assistant_template"]
    system_content = None
    for m in rec["messages"]:
        if m["role"] == "system":
            system_content = m["content"]
            break
    out_parts = []
    first_user = True
    for m in rec["messages"]:
        if m["role"] == "system":
            continue
        if m["role"] == "user":
            content = m["content"]
            if first_user and system_content:
                content = f"{system_content}\n\n{content}"
            out_parts.append(user_t.format(content=content))
            first_user = False
        elif m["role"] == "assistant":
            out_parts.append(asst_t.format(content=m["content"]))
    text = "".join(out_parts)
    return json.dumps({"text": text}, ensure_ascii=False)


def render_chatml(rec: dict, fmt: dict, raw: bool) -> str:
    """Render a record as ChatML-style text."""
    header = fmt.get("header", "")
    sys_t = fmt.get("system_template")
    user_t = fmt["user_template"]
    asst_t = fmt["assistant_template"]
    system_fallback = fmt.get("system_fallback", DEFAULT_SYSTEM)
    fold_system = fmt.get("system_fold", False)

    parts = [header] if header else []
    system_content = None
    for m in rec["messages"]:
        if m["role"] == "system":
            system_content = m["content"]
    if not system_content:
        if fmt.get("strip_empty_system", True):
            system_content = None
        else:
            system_content = system_fallback

    if system_content and not fold_system and sys_t:
        parts.append(sys_t.format(content=system_content))

    first_user = True
    for m in rec["messages"]:
        if m["role"] == "system":
            continue
        if m["role"] == "user":
            content = m["content"]
            if first_user and system_content and fold_system:
                content = f"System: {system_content}\n\n{content}"
            parts.append(user_t.format(content=content))
            first_user = False
        elif m["role"] == "assistant":
            parts.append(asst_t.format(content=m["content"]))
        # tool turns: skip in text mode (reserved for future)

    text = "".join(parts)
    if raw:
        return text
    return json.dumps({"text": text}, ensure_ascii=False)


def render_sharegpt(rec: dict, fmt: dict) -> str:
    role_map = fmt.get("role_map", {"system": "system", "user": "human", "assistant": "gpt"})
    conv = []
    for m in rec["messages"]:
        role = role_map.get(m["role"], m["role"])
        conv.append({"role": role, "content": m["content"]})
    return json.dumps({"conversations": conv, "id": rec.get("id")}, ensure_ascii=False)


def render_alpaca(rec: dict, fmt: dict) -> str:
    messages = rec["messages"]
    user_turns = [m for m in messages if m["role"] == "user"]
    asst_turns = [m for m in messages if m["role"] == "assistant"]
    if not user_turns or not asst_turns:
        return ""  # invalid for alpaca; skip
    first_user = user_turns[0]["content"]
    # split instruction / input on first blank line if present
    if "\n\n" in first_user:
        instruction, inp = first_user.split("\n\n", 1)
    else:
        instruction, inp = first_user, ""
    output = asst_turns[0]["content"]
    obj = {
        "instruction": instruction,
        "input": inp,
        "output": output,
        "category": rec.get("category"),
        "id": rec.get("id"),
    }
    if len(user_turns) > 1 or len(asst_turns) > 1:
        obj["_warn"] = "multiturn-collapsed"
    return json.dumps(obj, ensure_ascii=False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Convert Atlas JSONL to model formats.")
    ap.add_argument("--format", help="target format key from templates.json")
    ap.add_argument("--input", help="canonical Atlas JSONL")
    ap.add_argument("--output", help="output JSONL")
    ap.add_argument("--raw", action="store_true", help="for chatml/llama: emit raw text instead of JSON-wrapped")
    ap.add_argument("--list", action="store_true", help="list available formats and exit")
    args = ap.parse_args(argv)

    templates = load_templates()

    if args.list or not args.format:
        print("Available formats:")
        for k, v in templates["formats"].items():
            print(f"  {k:20s} {v.get('label','')}  -> targets: {', '.join(v.get('targets', []))}")
        return 0

    if args.format not in templates["formats"]:
        print(f"[convert] ERROR: unknown format {args.format!r}. Use --list.", file=sys.stderr)
        return 2
    if not args.input or not args.output:
        print("[convert] ERROR: --input and --output required.", file=sys.stderr)
        return 2

    fmt = templates["formats"][args.format]
    builder = fmt.get("builder")

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"[convert] ERROR: input not found: {in_path}", file=sys.stderr)
        return 2
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    n = 0
    skipped = 0
    with in_path.open(encoding="utf-8") as fin, out_path.open("w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            try:
                if builder in ("chatml", "llama"):
                    out = render_chatml(rec, fmt, args.raw)
                elif builder == "gemma":
                    out = render_gemma(rec, fmt)
                elif builder == "sharegpt":
                    out = render_sharegpt(rec, fmt)
                elif builder == "alpaca":
                    out = render_alpaca(rec, fmt)
                    if not out:
                        skipped += 1
                        continue
                else:
                    print(f"[convert] ERROR: unknown builder {builder!r}", file=sys.stderr)
                    return 2
                fout.write(out + "\n")
                n += 1
            except Exception as e:
                skipped += 1
                print(f"[convert] skip {rec.get('id')}: {e}", file=sys.stderr)

    print(f"[convert] wrote {n} records ({skipped} skipped) -> {out_path} [{args.format}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
