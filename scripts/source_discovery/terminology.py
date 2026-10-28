"""Terminology sidecar builder (v1.1).

Dictionaries are lexical resources, NEVER sentence-pair training data. This
module downloads JMdict (ja-en) and CC-CEDICT (zh-en), parses them with stdlib
only, and writes a separate sidecar corpus:

  {source_lang, target_lang, source_term, target_term, domain, source_id,
   license, license_state, provenance:{revision, entry_ref, acquired_utc}}

Both sources are share-alike (RESTRICTED) — the sidecar carries its license
on every row and stays out of training_ready.jsonl. KO/MS dictionaries have
no verified open release (recorded gaps, not scraped).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sys
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atlas_paths import get_root  # noqa: E402

from source_discovery.corpus_v1_1 import (  # noqa: E402
    V11, V11_TMP, _guard_write, _utcnow, _write_jsonl)

JMDICT_URLS = [
    "http://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz",
    "https://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz",
]
CCEDICT_URLS = [
    "https://cc-cedict.org/download/cedict_1_0_ts_utf-8_mdbg.zip",
    "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.zip",
]

TERM_DIR = V11 / "terminology"


def _fetch(urls: list[str], dest: Path, timeout_s: int = 120) -> dict[str, Any]:
    _guard_write(dest)
    last_err = ""
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "atlas-source-discovery-v1.1"})
            with urllib.request.urlopen(req, timeout=timeout_s) as r, \
                    open(dest, "wb") as f:
                h = hashlib.sha256()
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
            return {"url": url, "bytes": dest.stat().st_size,
                    "sha256": h.hexdigest(), "acquired_utc": _utcnow()}
        except Exception as exc:  # noqa: BLE001 — try next mirror
            last_err = f"{type(exc).__name__}: {str(exc)[:200]}"
    return {"error": last_err, "urls_tried": urls}


def parse_jmdict(path: Path, revision_note: str) -> Iterator[dict]:
    """Stream JMdict entries -> (keb, english gloss) rows. stdlib iterparse."""
    import xml.etree.ElementTree as ET
    with gzip.open(path, "rb") as f:
        context = ET.iterparse(f, events=("end",))
        for _ev, elem in context:
            if elem.tag != "entry":
                continue
            seq = (elem.findtext("ent_seq") or "").strip()
            kebs = [k.text for k in elem.findall("k_ele/keb")
                    if k.text and k.text.strip()]
            rebs = [r.text for r in elem.findall("r_ele/reb")
                    if r.text and r.text.strip()]
            head = kebs[0].strip() if kebs else (
                rebs[0].strip() if rebs else "")
            if not head:
                elem.clear()
                continue
            for sense in elem.findall("sense"):
                glosses = [g.text for g in sense.findall("gloss")
                           if g.text and g.text.strip()
                           and (g.get("{http://www.w3.org/XML/1998/namespace}lang")
                                in (None, "eng") or g.get("lang") in
                                (None, "eng"))]
                field = [fl.text for fl in sense.findall("field")
                         if fl.text]
                domain = "general"
                if any("ling" in (x or "") or "lit" in (x or "")
                       for x in field):
                    domain = "literary"
                for g in glosses:
                    yield {
                        "source_lang": "ja", "target_lang": "en",
                        "source_term": head,
                        "target_term": g.strip()[:500],
                        "domain": domain,
                        "source_id": "jmdict",
                        "license": "CC-BY-SA-4.0 (verify header; share-alike)",
                        "license_state": "RESTRICTED",
                        "provenance": {
                            "revision": revision_note,
                            "entry_ref": f"ent_seq:{seq}",
                            "acquired_utc": _utcnow(),
                        },
                    }
            elem.clear()


def parse_cccedict(lines: Iterator[str],
                   revision_note: str) -> Iterator[dict]:
    import re as _re
    pat = _re.compile(r"^(\S+)\s+(\S+)\s+\[([^\]]+)\]\s+/(.+)/\s*$")
    for lineno, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = pat.match(line)
        if not m:
            continue
        _trad, simp, _pinyin, defs = m.groups()
        for d in defs.split("/"):
            d = d.strip()
            if d:
                yield {
                    "source_lang": "zh", "target_lang": "en",
                    "source_term": simp,
                    "target_term": d[:500],
                    "domain": "general",
                    "source_id": "cc-cedict",
                    "license": "CC-BY-SA-4.0 (verify header; share-alike)",
                    "license_state": "RESTRICTED",
                    "provenance": {
                        "revision": revision_note,
                        "entry_ref": f"line:{lineno}",
                        "acquired_utc": _utcnow(),
                    },
                }


def build_sidecar() -> dict[str, Any]:
    TERM_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"built_utc": _utcnow(), "sources": {}}
    all_rows: list[dict] = []

    # JMdict
    jd = V11_TMP / "JMdict_e.gz"
    dl = _fetch(JMDICT_URLS, jd)
    if "error" in dl:
        manifest["sources"]["jmdict"] = {"status": "FAILED", **dl}
    else:
        rows = list(parse_jmdict(jd, dl["sha256"][:16]))
        manifest["sources"]["jmdict"] = {
            "status": "INGESTED", **dl, "n_terms": len(rows),
            "license": "CC-BY-SA-4.0", "license_state": "RESTRICTED"}
        all_rows.extend(rows)

    # CC-CEDICT
    cd = V11_TMP / "cedict.zip"
    dl2 = _fetch(CCEDICT_URLS, cd)
    if "error" in dl2:
        manifest["sources"]["cc-cedict"] = {"status": "FAILED", **dl2}
    else:
        try:
            with zipfile.ZipFile(cd) as z:
                inner = [n for n in z.namelist()
                         if n.lower().endswith(".u8") or "cedict" in
                         n.lower() and n.endswith(".txt")]
                inner_name = inner[0] if inner else z.namelist()[0]
                with z.open(inner_name) as f:
                    text = f.read().decode("utf-8", errors="replace")
            rows = list(parse_cccedict(iter(text.splitlines()),
                                       dl2["sha256"][:16]))
            manifest["sources"]["cc-cedict"] = {
                "status": "INGESTED", **dl2, "inner": inner_name,
                "n_terms": len(rows), "license": "CC-BY-SA-4.0",
                "license_state": "RESTRICTED"}
            all_rows.extend(rows)
        except Exception as exc:  # noqa: BLE001
            manifest["sources"]["cc-cedict"] = {
                "status": "FAILED",
                "error": f"{type(exc).__name__}: {str(exc)[:200]}"}

    manifest["sources"]["koen-wikt"] = {
        "status": "GAP",
        "note": "no verified open ko-en dictionary release; not scraped"}
    manifest["sources"]["msmy-dict"] = {
        "status": "GAP",
        "note": "no verified open ms-en dictionary release; not scraped"}

    n, sha = _write_jsonl(TERM_DIR / "terminology.jsonl", all_rows)
    manifest.update({"n_terms": n, "sha256": sha,
                     "note": "sidecar only — never sentence-pair training data"})
    with open(TERM_DIR / "terminology_manifest.json", "w",
              encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    return manifest
