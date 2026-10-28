"""Live metadata verification for Source Discovery v1.0.

Never invents details. For Hugging Face repo_ids it queries the Hub API
(revision SHA, card license, row counts where cheap); for HTTP(S) URLs it
attempts a lightweight HEAD. Every outcome — success or failure — is recorded
with method + timestamp. Unverifiable candidates keep status DISCOVERED with an
explicit verification note (never silently discarded).
"""

from __future__ import annotations

import time
import urllib.request
from datetime import datetime, timezone
from typing import Any


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def verify_hf_dataset(repo_id: str, timeout_s: float = 15.0) -> dict[str, Any]:
    """Query Hub API for dataset metadata. Returns detail dict (never raises)."""
    detail: dict[str, Any] = {
        "method": "hf_hub_api",
        "repo_id": repo_id,
        "verified_at": _utcnow(),
        "ok": False,
    }
    try:
        from huggingface_hub import HfApi  # lazy: optional dependency
        info = HfApi().dataset_info(repo_id, timeout=timeout_s)
        detail["ok"] = True
        detail["revision_sha"] = getattr(info, "sha", "") or ""
        card = getattr(info, "cardData", None)
        card_dict: dict[str, Any] = {}
        if card is not None:
            try:
                card_dict = dict(card) if isinstance(card, dict) else {
                    k: getattr(card, k) for k in dir(card)
                    if not k.startswith("_")}
            except Exception:  # noqa: BLE001 — verification must not crash
                card_dict = {}
        # license may live in cardData.license or tags
        lic = ""
        if isinstance(card_dict.get("license"), str):
            lic = card_dict["license"]
        elif isinstance(card_dict.get("license"), list) and card_dict["license"]:
            lic = str(card_dict["license"][0])
        tags = getattr(info, "tags", []) or []
        detail["card_license"] = lic
        detail["tags_sample"] = list(tags)[:20]
        detail["siblings_sample"] = [
            getattr(s, "rfilename", str(s)) for s in
            (getattr(info, "siblings", []) or [])][:10]
        detail["likes"] = getattr(info, "likes", None)
        detail["downloads"] = getattr(info, "downloads", None)
    except Exception as exc:  # noqa: BLE001 — record, never raise
        detail["ok"] = False
        detail["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    return detail


def verify_http_url(url: str, timeout_s: float = 10.0) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "method": "http_head", "url": url, "verified_at": _utcnow(),
        "ok": False,
    }
    if not url or not url.startswith(("http://", "https://")):
        detail["error"] = "no_http_url_to_check"
        return detail
    try:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "atlas-sd-v1"})
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            detail["ok"] = True
            detail["http_status"] = getattr(resp, "status", None)
            detail["content_type"] = resp.headers.get("Content-Type", "")
            detail["content_length"] = resp.headers.get("Content-Length", "")
    except Exception as exc:  # noqa: BLE001
        detail["ok"] = False
        detail["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
    return detail


def verify_candidate(entry: dict[str, Any],
                     check_http: bool = True) -> dict[str, Any]:
    """Verify one registry entry in place; returns verification detail."""
    checks: dict[str, Any] = {}
    repo_id = (entry.get("repo_id") or "").strip()
    if repo_id and "/" in repo_id:
        hf = verify_hf_dataset(repo_id)
        checks["huggingface"] = hf
        if hf.get("ok"):
            if hf.get("revision_sha") and not entry.get("source_revision"):
                entry["source_revision"] = hf["revision_sha"]
            card_lic = (hf.get("card_license") or "").strip()
            if card_lic and (entry.get("license") or "UNKNOWN") == "UNKNOWN":
                entry["license"] = card_lic
                entry["license_evidence"] = (
                    f"Hub cardData.license={card_lic!r} for {repo_id} "
                    f"(verified {hf['verified_at']}; confirm card text before "
                    f"training-ready use).")
                from .license_policy import classify_license
                state, reason = classify_license(entry["license"],
                                                 entry["license_evidence"])
                entry["license_state"] = state
    else:
        checks["huggingface"] = {"method": "hf_hub_api", "ok": False,
                                 "reason": "no_hf_repo_id"}
    if check_http:
        checks["http"] = verify_http_url(entry.get("url", ""))
    else:
        checks["http"] = {"method": "http_head", "ok": False,
                          "reason": "skipped"}
    detail = {"source_id": entry.get("source_id"), "checks": checks,
              "verified_at": _utcnow()}
    entry.setdefault("verification", {})
    if isinstance(entry["verification"], dict):
        entry["verification"]["last_check"] = detail
    else:
        entry["verification"] = {"last_check": detail}
    return detail


def verify_registry(sources: list[dict[str, Any]],
                    check_http: bool = True,
                    pause_s: float = 0.5) -> dict[str, Any]:
    results = []
    for entry in sources:
        results.append(verify_candidate(entry, check_http=check_http))
        if pause_s:
            time.sleep(pause_s)
    ok_hf = sum(1 for r in results
                if r["checks"].get("huggingface", {}).get("ok"))
    ok_http = sum(1 for r in results
                  if r["checks"].get("http", {}).get("ok"))
    return {
        "verified_at": _utcnow(),
        "n_sources": len(sources),
        "n_hf_ok": ok_hf,
        "n_http_ok": ok_http,
        "results": results,
    }
