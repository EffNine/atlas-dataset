"""Script-based language check for Source Discovery v1.0 (stdlib only).

Thresholds mirror the proven translation-ai-v0.1 preprocess heuristics
(documented judgment, not fitted): zh needs CJK density, ja needs kana or
CJK, ko needs Hangul, ms/en need Latin-letter density. Reimplemented here so
Atlas does not vendor the translation-ai package (which forbids vendoring).
"""

from __future__ import annotations

import unicodedata

SD_SUPPORTED_LANGS = ("zh", "ja", "ko", "ms", "en")


def script_profile(text: str) -> dict[str, int]:
    cjk = hira = kata = hang = latin = letters = 0
    for ch in text:
        if ch.isspace():
            continue
        if not unicodedata.category(ch).startswith("L"):
            continue
        letters += 1
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF \
                or 0xF900 <= o <= 0xFAFF:
            cjk += 1
        elif 0x3040 <= o <= 0x309F:
            hira += 1
        elif 0x30A0 <= o <= 0x30FF:
            kata += 1
        elif 0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF:
            hang += 1
        elif 0x41 <= o <= 0x5A or 0x61 <= o <= 0x7A or 0xC0 <= o <= 0xFF:
            latin += 1
    return {"cjk": cjk, "hira": hira, "kata": kata, "hang": hang,
            "latin": latin, "letters": letters}


def lang_ok(text: str, lang: str) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    p = script_profile(text)
    n = p["letters"]
    if n == 0:
        return False
    if lang == "zh":
        return p["cjk"] / n >= 0.15
    if lang == "ja":
        return (p["hira"] + p["kata"]) / n >= 0.10 or p["cjk"] / n >= 0.15
    if lang == "ko":
        return p["hang"] / n >= 0.15
    if lang in ("ms", "en"):
        return p["latin"] / n >= 0.70
    return False


def check_pair_languages(source: str, target: str, source_lang: str,
                         target_lang: str = "en") -> str | None:
    """Return None when both sides pass, else a reason code."""
    if source_lang not in SD_SUPPORTED_LANGS or target_lang != "en":
        return "unsupported_language"
    if not lang_ok(source, source_lang):
        return f"wrong_language_source_{source_lang}"
    if not lang_ok(target, "en"):
        return "wrong_language_target_en"
    return None
