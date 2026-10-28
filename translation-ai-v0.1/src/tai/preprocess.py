"""Step 2 — Deterministic preprocessing of the canonical parallel corpus.

Checks (in order, first-hit reason recorded):
  1. malformed_pair   — missing/non-string fields, bad language codes
  2. empty_pair       — either side empty after strip
  3. bad_script       — script-based language-ID fails on either side
                        zh: >=15% CJK ideographs; ja: >=10% hiragana/katakana
                            or >=15% CJK; ko: >=15% Hangul;
                            ms/en: >=70% latin letters among letters
  4. copy_pair        — source == target (case-sensitive raw equality)
  5. too_long         — > MAX_CHARS chars or > MAX_TOKENS whitespace tokens
  6. misaligned       — char-length ratio outside [1/8, 8]
  7. duplicate        — exact (source, target) seen before (keeps first)

Language provenance is preserved verbatim on every kept record.

Usage:
    PYTHONPATH=src .venv/bin/python -m tai.preprocess \
        --inp data/raw --out data/clean
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

LANGS = ("zh", "ja", "ko", "ms")
MAX_CHARS = 1000
MAX_TOKENS = 200
MIN_RATIO, MAX_RATIO = 1 / 8, 8.0

_WS = re.compile(r"\s+")


def _cats(text: str):
    cjk = hira = kata = hang = latin = letters = 0
    for ch in text:
        if ch.isspace():
            continue
        cat = unicodedata.category(ch)
        if not cat.startswith("L"):
            continue
        letters += 1
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF:
            cjk += 1
        elif 0x3040 <= o <= 0x309F:
            hira += 1
        elif 0x30A0 <= o <= 0x30FF:
            kata += 1
        elif 0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF:
            hang += 1
        elif (0x41 <= o <= 0x5A) or (0x61 <= o <= 0x7A) or 0xC0 <= o <= 0xFF:
            latin += 1
    return dict(cjk=cjk, hira=hira, kata=kata, hang=hang, latin=latin, letters=letters)


def script_ok(text: str, lang: str) -> bool:
    c = _cats(text)
    n = c["letters"]
    if n == 0:
        return False
    if lang == "zh":
        return c["cjk"] / n >= 0.15
    if lang == "ja":
        return (c["hira"] + c["kata"]) / n >= 0.10 or c["cjk"] / n >= 0.15
    if lang == "ko":
        return c["hang"] / n >= 0.15
    if lang in ("ms", "en"):
        return c["latin"] / n >= 0.70
    return False


def check_pair(rec: dict, seen: set) -> str | None:
    """Return None if kept, else the rejection reason."""
    if not isinstance(rec, dict):
        return "malformed_pair"
    src, tgt = rec.get("source"), rec.get("target")
    sl, tl = rec.get("source_lang"), rec.get("target_lang")
    if (not isinstance(src, str) or not isinstance(tgt, str)
            or sl not in LANGS or tl != "en"):
        return "malformed_pair"
    s, t = src.strip(), tgt.strip()
    if not s or not t:
        return "empty_pair"
    if not script_ok(s, sl) or not script_ok(t, "en"):
        return "bad_script"
    if s == t:
        return "copy_pair"
    if (len(s) > MAX_CHARS or len(t) > MAX_CHARS
            or len(_WS.split(s)) > MAX_TOKENS or len(_WS.split(t)) > MAX_TOKENS):
        return "too_long"
    ratio = len(s) / max(1, len(t))
    if not (MIN_RATIO <= ratio <= MAX_RATIO):
        return "misaligned"
    if (s, t) in seen:
        return "duplicate"
    return None


def clean_file(inp: Path, outp: Path, rejp: Path) -> dict:
    seen: set = set()
    stats: dict = {"kept": 0}
    with open(inp, encoding="utf-8") as fin, \
         open(outp, "w", encoding="utf-8") as fout, \
         open(rejp, "w", encoding="utf-8") as frej:
        for line in fin:
            line = line.strip()
            if not line:
                stats["empty_line"] = stats.get("empty_line", 0) + 1
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                stats["malformed_pair"] = stats.get("malformed_pair", 0) + 1
                frej.write(json.dumps({"reason": "malformed_pair", "line": line[:200]},
                                      ensure_ascii=False) + "\n")
                continue
            reason = check_pair(rec, seen)
            if reason is None:
                seen.add((rec["source"].strip(), rec["target"].strip()))
                rec["source"] = rec["source"].strip()
                rec["target"] = rec["target"].strip()
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                stats["kept"] += 1
            else:
                stats[reason] = stats.get(reason, 0) + 1
                frej.write(json.dumps({"reason": reason, "id": rec.get("id")},
                                      ensure_ascii=False) + "\n")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inp", default="data/raw")
    ap.add_argument("--out", default="data/clean")
    args = ap.parse_args()
    inp, out = Path(args.inp), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    all_stats = {}
    for lang in LANGS:
        f = inp / f"raw_{lang}-en.jsonl"
        if not f.exists():
            print(f"skip {lang}: {f} missing")
            continue
        st = clean_file(f, out / f"clean_{lang}-en.jsonl", out / f"rejected_{lang}-en.jsonl")
        all_stats[lang] = st
        print(f"{lang}-en: {st}", flush=True)
    with open(out / "clean_stats.json", "w", encoding="utf-8") as f:
        json.dump({"thresholds": {"max_chars": MAX_CHARS, "max_tokens": MAX_TOKENS,
                                  "ratio": [MIN_RATIO, MAX_RATIO]},
                   "per_lang": all_stats}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
