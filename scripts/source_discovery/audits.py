"""JA/KO/MS audits for v1.1 (verify-only; no scraping, no gate bypass).

- JParaCrawl: repair the URL (v1.0 guessed jparacrawl.org wrongly), check
  reachability of the corrected NTT KECL page, record licensing as
  human-read-required.
- JESC: confirm project page + discover the documented download surface
  (report only; no bulk fetch in v1.1).
- KO/MS: probe Tatoeba per-language exports (tiny, CC-BY) for eng-ko /
  eng-ms pairs; ingest capped samples through the standard cleaner when the
  files actually exist. AI-Hub stays BLOCKED_ACCESS (never bypassed).
- Literary verdicts are recorded explicitly: subtitle != novel.
"""

from __future__ import annotations

import gzip
import io
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from source_discovery.corpus_v1_1 import (  # noqa: E402
    V11, V11_STAGING, _utcnow, clean_and_stage)

AUDIT_DIR = V11 / "audits"

JPARACRAWL_CANDIDATE_URLS = [
    "https://www.kecl.ntt.co.jp/icl/lirg/jparacrawl/",
    "https://jparacrawl.org/",
]
JESC_URL = "https://nlp.stanford.edu/projects/jesc/"
TATOEBA_INDEX = "https://downloads.tatoeba.org/exports/per_language/eng/"


def _head(url: str, timeout_s: int = 20) -> dict[str, Any]:
    try:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent":
                                              "atlas-source-discovery-v1.1"})
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            return {"url": url, "ok": True, "status": r.status,
                    "content_type": r.headers.get("Content-Type", "")}
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "ok": False,
                "error": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _get_text(url: str, limit: int = 200000,
              timeout_s: int = 30) -> tuple[str, dict]:
    req = urllib.request.Request(url, headers={"User-Agent":
                                               "atlas-source-discovery-v1.1"})
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        return r.read(limit).decode("utf-8", errors="replace"), {
            "status": r.status}


def audit_jparacrawl() -> dict[str, Any]:
    out: dict[str, Any] = {"audited_utc": _utcnow(), "checks": [],
                           "domain": "general/web (NOT literary)",
                           "license_note": "UNVERIFIED — usage terms require a "
                           "human read of the official site before any use."}
    for u in JPARACRAWL_CANDIDATE_URLS:
        out["checks"].append(_head(u))
    out["reachable"] = [c["url"] for c in out["checks"] if c.get("ok")]
    out["verdict"] = ("corrected URL reachable; corpus NOT ingested in v1.1 "
                      "(license + file layout need confirmation)"
                      if out["reachable"] else
                      "no candidate URL reachable; JA web-parallel still open")
    return out


def audit_jesc() -> dict[str, Any]:
    out: dict[str, Any] = {"audited_utc": _utcnow(), "page": _head(JESC_URL),
                           "domain": "subtitle/dialogue (NOT novel)",
                           "license_note": "UNVERIFIED — confirm project terms "
                           "before any use."}
    try:
        html, _ = _get_text(JESC_URL)
        links = sorted({a for a in
                        __import__("re").findall(r'href="([^"]+)"', html)
                        if "jesc" in a.lower() or a.endswith(
                            (".tsv", ".gz", ".zip", ".txt"))})
        out["download_links_found"] = links[:20]
        out["verdict"] = ("page reachable; download surface reported above; "
                          "bulk fetch deferred (subtitle domain, lower "
                          "priority than literary)")
    except Exception as exc:  # noqa: BLE001
        out["download_links_found"] = []
        out["verdict"] = f"page fetch failed: {type(exc).__name__}"
    return out


def tatoeba_probe() -> dict[str, Any]:
    """List eng/ export index; report ko/ms file availability (no fetch)."""
    out: dict[str, Any] = {"audited_utc": _utcnow(), "index": TATOEBA_INDEX}
    try:
        html, _ = _get_text(TATOEBA_INDEX)
        files = sorted(set(__import__("re").findall(
            r'href="([^"]+\.(?:bz2|gz|tsv))"', html)))
        out["n_files"] = len(files)
        out["ko_files"] = [f for f in files if "_ko" in f or "kor" in f][:10]
        out["ms_files"] = [f for f in files if "_ms" in f or "msa" in f
                           or "may" in f][:10]
        out["ok"] = True
    except Exception as exc:  # noqa: BLE001
        out.update(ok=False,
                   error=f"{type(exc).__name__}: {str(exc)[:200]}")
    return out


def _dl_bytes(url: str, limit: int = 200 * 1024 * 1024) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent":
                                               "atlas-source-discovery-v1.1"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read(limit)


def ingest_tatoeba_joined(lang: str, cap: int = 20000) -> dict[str, Any]:
    """Join Tatoeba eng-XX links with per-language sentence exports.

    lang: 'ko' (kor) or 'ms' (zsm). Deterministic: links sorted by (en_id,
    xx_id), capped. Orientation fixed xx->en by construction (sentence files
    are per-language). License CC-BY-2.0-FR (verify).
    """
    code = {"ko": "kor", "ms": "zsm"}[lang]
    source_id = f"tatoeba-{lang}en"
    base = "https://downloads.tatoeba.org/exports/per_language/"
    import bz2 as _bz2

    def _sentences(url: str) -> dict[str, str]:
        blob = _dl_bytes(url)
        try:
            text = _bz2.decompress(blob).decode("utf-8", errors="replace")
        except OSError:
            text = blob.decode("utf-8", errors="replace")
        out = {}
        for line in text.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and parts[0].strip().isdigit():
                out[parts[0].strip()] = parts[2]
        return out

    links_blob = _dl_bytes(f"{base}eng/eng-{code}_links.tsv.bz2")
    try:
        links_text = _bz2.decompress(links_blob).decode("utf-8",
                                                        errors="replace")
    except OSError:
        links_text = links_blob.decode("utf-8", errors="replace")
    pairs = set()
    for line in links_text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].strip().isdigit() \
                and parts[1].strip().isdigit():
            pairs.add((parts[0].strip(), parts[1].strip()))
    pairs = sorted(pairs)[:cap * 2]
    en_sents = _sentences(f"{base}eng/eng_sentences.tsv.bz2")
    xx_sents = _sentences(f"{base}{code}/{code}_sentences.tsv.bz2")

    def rows():
        n = 0
        for en_id, xx_id in pairs:
            if n >= cap:
                break
            if en_id in en_sents and xx_id in xx_sents:
                yield {"source": xx_sents[xx_id], "target": en_sents[en_id],
                       "source_lang": lang, "target_lang": "en",
                       "source_revision": f"eng-{code}_links",
                       "source_record_id": f"{source_id}-{en_id}-{xx_id}",
                       "method": "tatoeba_join", "parser_format": "tsv.bz2"}
                n += 1

    staging = V11_STAGING / source_id
    manifest_extra = {"lang": lang, "cap": cap, "n_link_pairs": len(pairs),
                      "license": "CC-BY-2.0-FR (verify Tatoeba terms)",
                      "license_state": "ALLOW", "domain": "general"}
    stats = clean_and_stage(rows(), source_id, staging,
                            manifest_extra=manifest_extra)
    stats.update(manifest_extra)
    return stats


def run_audits() -> dict[str, Any]:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "audited_utc": _utcnow(),
        "jparacrawl": audit_jparacrawl(),
        "jesc": audit_jesc(),
        "tatoeba": tatoeba_probe(),
        "aihub": {"status": "BLOCKED_ACCESS",
                  "note": "HTTP 403 (v1.0); gated application required; "
                          "never bypassed in v1.1"},
        "ja_literary_verdict": "NO verified open JA literary parallel corpus "
                               "found — recorded as explicit gap",
        "ko_literary_verdict": "NO verified open KO literary parallel corpus "
                               "found — recorded as explicit gap",
        "ms_literary_verdict": "NO verified open MS literary parallel corpus "
                               "found — recorded as explicit gap",
    }
    with open(AUDIT_DIR / "ja_ko_ms_audits.json", "w",
              encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return report
