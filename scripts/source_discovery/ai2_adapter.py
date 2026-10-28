"""Blind AI-2 reviewer boundary for Source Discovery v1.0.

Reuses the existing blind AI-2 architecture WITHOUT copying it: message
construction mirrors experiments/jev-quality-filter-v0.2/ai2_reviewer.py
(build_messages contract: payload keys EXACTLY
{claimed_category, claimed_subcategory, user, assistant}) and is
contract-tested against the real module.

Hard rules enforced here:
  - AI-2 NEVER receives JEV scores, bands, confidence, decisions, or reasoning
    (review_translation_pair accepts no JEV arguments by construction).
  - AI-2 is called ONLY for ambiguous cases (caller enforces routing).
  - Fail closed: missing config, transport error, or parse error ->
    verdict ERROR -> final AMBIGUOUS with quarantine=true. Never ACCEPT.

v1.0 scope: boundary + contract verification only. No live AI-2 calls are made
by the smoke pipeline (credentials almost certainly absent in CI/sandbox).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

AI2_PATH = (Path(__file__).resolve().parent.parent.parent
            / "experiments" / "jev-quality-filter-v0.2" / "ai2_reviewer.py")

EXPECTED_PAYLOAD_KEYS = frozenset({"claimed_category", "claimed_subcategory",
                                   "user", "assistant"})


def load_ai2_module() -> dict[str, Any]:
    if not AI2_PATH.exists():
        return {"available": False,
                "reason": f"ai2_not_found:{AI2_PATH}"}
    try:
        spec = importlib.util.spec_from_file_location("sd_ai2_reviewer_v02",
                                                      AI2_PATH)
        if spec is None or spec.loader is None:
            return {"available": False, "reason": "import_spec_failed"}
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return {"available": True, "module": mod,
                "path": str(AI2_PATH)}
    except Exception as exc:  # noqa: BLE001
        return {"available": False,
                "reason": f"{type(exc).__name__}: {str(exc)[:300]}"}


def build_ai2_request(source: str, target: str, source_id: str,
                      direction: str, domain: str = "") -> list[dict]:
    """Build the blind AI-2 message pair. No JEV data can be passed.

    Mapping: user=source text, assistant=target text (translation pair as a
    QA-shaped record), claimed_category=source_id/domain, claimed_subcategory
    =direction. Truncation mirrors the upstream MAX_CONTENT_CHARS budget.
    """
    loaded = load_ai2_module()
    if loaded.get("available"):
        mod = loaded["module"]
        try:
            return mod.build_messages(source, target, source_id,
                                      f"{direction}:{domain}" if domain
                                      else direction)
        except Exception:  # noqa: BLE001 — fall through to local builder
            pass
    import json as _json
    record = {"claimed_category": source_id,
              "claimed_subcategory": f"{direction}:{domain}" if domain
              else direction,
              "user": source[:6000], "assistant": target[:6000]}
    return [
        {"role": "system",
         "content": "Independent translation-data quality reviewer. "
                    "Judge ONLY the record content."},
        {"role": "user", "content": _json.dumps(record, ensure_ascii=False)},
    ]


def quarantine_result(reason: str) -> dict[str, Any]:
    return {"verdict": "ERROR", "final": "AMBIGUOUS", "quarantine": True,
            "reason": reason, "blind": True,
            "note": "fail-closed: reviewer errors never become acceptances"}


def review_or_quarantine(source: str, target: str, source_id: str,
                         direction: str, domain: str = "",
                         allow_live_call: bool = False) -> dict[str, Any]:
    """Fail-closed AI-2 entry point. v1.0 default: no live calls.

    With allow_live_call=False (default) this builds the blind request for
    inspection and returns a quarantined NOT-CALLED marker — proving the
    wiring without spending reviewer budget. With True it attempts one live
    review; ANY failure quarantines.
    """
    messages = build_ai2_request(source, target, source_id, direction, domain)
    if not allow_live_call:
        return {"verdict": "NOT-CALLED", "final": "AMBIGUOUS",
                "quarantine": True, "blind": True,
                "reason": "v1.0 smoke: live AI-2 disabled by default",
                "messages_built": True,
                "n_messages": len(messages)}
    loaded = load_ai2_module()
    if not loaded.get("available"):
        return quarantine_result(str(loaded.get("reason")))
    mod = loaded["module"]
    try:
        config = mod.resolve_config()
        res = mod.review_record(source, target, source_id,
                                f"{direction}:{domain}" if domain
                                else direction, config)
        verdict = res.get("verdict")
        if verdict == "ACCEPT":
            final = "ACCEPT"
        elif verdict == "REJECT":
            final = "REJECT"
        else:
            final = "AMBIGUOUS"
        return {"verdict": verdict, "final": final,
                "quarantine": final != "ACCEPT", "blind": True,
                "detail": {k: res.get(k) for k in (
                    "confidence", "correctness", "completeness",
                    "suitability", "rationale")}}
    except Exception as exc:  # noqa: BLE001 — fail closed
        reason = getattr(exc, "reason", type(exc).__name__)
        return quarantine_result(f"{reason}: {str(exc)[:200]}")
