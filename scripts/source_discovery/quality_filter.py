"""Cheap automated quality filter for Source Discovery v1.0.

Purpose: remove OBVIOUS garbage cheaply. No literary-quality judgment.
Deterministic, stdlib-only, first-hit reason recorded.

Check order (first hit wins):
  malformed_record, empty_pair, corrupted_encoding, copy_pair, too_long,
  bad_script (delegates to language_check), misaligned_ratio, html_boilerplate,
  repeated_text, duplicate_content

Thresholds (documented judgment for v1.0, literary-tolerant):
  MAX_CHARS=5000, MAX_TOKENS=1000, RATIO in [1/8, 8].
"""

from __future__ import annotations

import re
from typing import Any

from .language_check import check_pair_languages

MAX_CHARS = 5000
MAX_TOKENS = 1000
MIN_RATIO, MAX_RATIO = 1 / 8, 8.0

_WS = re.compile(r"\s+")
_HTML_TAG = re.compile(r"</?(html|body|div|span|nav|header|footer|script|style|a|button)\b", re.I)
_BOILER = re.compile(
    r"(subscribe\s+(now|here)|click\s+here|cookie\s+policy|all\s+rights\s+reserved"
    r"|sign\s+in|log\s+in|add\s+to\s+cart|404\s+not\s+found|page\s+not\s+found)",
    re.I)


def _tokens(text: str) -> int:
    return len(_WS.split(text.strip())) if text.strip() else 0


def _is_repeated(text: str) -> bool:
    s = text.strip()
    if len(s) < 100:
        return False
    # Pathological low-diversity: fewer than 20 distinct characters in a
    # 300+ char text (e.g. "ab"x500, "哈哈哈…" spam). Deliberately absolute,
    # NOT a ratio: normal long English uses ~70 distinct chars, so a ratio
    # test misfires on healthy prose (alphabet is small by construction).
    # Gated at 300+ chars because short sentences legitimately use <20
    # distinct symbols (e.g. 115-char EN with 19 uniques is normal).
    # Shorter texts are still covered by the dominance + block rules below.
    if len(s) >= 300 and len(set(s)) < 20:
        return True
    # Single-character dominance: one char covers >70% of a 200+ char text
    # (dot-lines, dash-lines, char spam). Legit dialogue ("哈哈哈" bursts)
    # rarely sustains this over 200 chars.
    if len(s) >= 200:
        from collections import Counter as _C
        top = _C(s).most_common(1)[0][1]
        if top / len(s) > 0.70:
            return True
    # Same 40-char block covering >60% of the text.
    block = s[:40]
    if len(block) == 40 and s.count(block) * 40 > 0.6 * len(s):
        return True
    return False


def filter_record(rec: dict[str, Any],
                  seen_hashes: set[str] | None = None) -> str | None:
    """Return None if kept, else the rejection reason (first hit)."""
    if not isinstance(rec, dict):
        return "malformed_record"
    src, tgt = rec.get("source"), rec.get("target")
    sl, tl = rec.get("source_lang"), rec.get("target_lang")
    if not isinstance(src, str) or not isinstance(tgt, str) \
            or not isinstance(sl, str) or tl != "en":
        return "malformed_record"
    s, t = src.strip(), tgt.strip()
    if not s or not t:
        return "empty_pair"
    if "\x00" in src or "\x00" in tgt or "�" in src or "�" in tgt:
        return "corrupted_encoding"
    if s == t:
        return "copy_pair"
    if len(s) > MAX_CHARS or len(t) > MAX_CHARS \
            or _tokens(s) > MAX_TOKENS or _tokens(t) > MAX_TOKENS:
        return "too_long"
    lang_reason = check_pair_languages(s, t, sl, "en")
    if lang_reason is not None:
        return lang_reason if lang_reason.startswith(
            ("wrong_language", "unsupported")) else "bad_script"
    ratio = len(s) / max(1, len(t))
    if not (MIN_RATIO <= ratio <= MAX_RATIO):
        return "misaligned_ratio"
    if _HTML_TAG.search(s) or _HTML_TAG.search(t) \
            or _BOILER.search(s) or _BOILER.search(t):
        return "html_boilerplate"
    if _is_repeated(s) or _is_repeated(t):
        return "repeated_text"
    ch = rec.get("content_sha256")
    if seen_hashes is not None and isinstance(ch, str) and ch in seen_hashes:
        return "duplicate_content"
    return None


def filter_corpus(records: list[dict[str, Any]]) -> tuple[list[dict], list[dict], dict]:
    kept, rejected, stats = [], [], {"n_input": len(records)}
    seen: set[str] = set()
    for rec in records:
        reason = filter_record(rec, seen)
        if reason is None:
            kept.append(rec)
            ch = rec.get("content_sha256")
            if isinstance(ch, str):
                seen.add(ch)
            stats["kept"] = stats.get("kept", 0) + 1
        else:
            rejected.append({"id": rec.get("id") if isinstance(rec, dict) else None,
                             "reason": reason})
            stats[reason] = stats.get(reason, 0) + 1
    stats["n_kept"] = len(kept)
    stats["n_rejected"] = len(rejected)
    return kept, rejected, stats
