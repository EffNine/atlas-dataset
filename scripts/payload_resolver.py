#!/usr/bin/env python3
"""
payload_resolver.py — Canonical Payload Resolver for Atlas

Every Atlas workflow that needs a record payload must ask the Payload Resolver
instead of manually searching files.

Lookup priority (stop at first match):

  1. review_cache       — review_queue/*.jsonl
  2. review_input       — review/v0.2/batch_001_input.jsonl, review/quality_reviews.jsonl
  3. decision_artifact  — review/decisions/**/*.jsonl
  4. curated_dataset    — curated/v0.2/data/*.jsonl
  5. knowledge_pack     — knowledge_packs/*.jsonl.gz
  6. archived_dataset   — curated/v0.1/*.jsonl

Usage (as library):
    from payload_resolver import PayloadResolver
    pr = PayloadResolver(ROOT)
    result = pr.resolve("b1_07_business_knowledge_finance_0009")
    explain = pr.explain("some_id")

Usage (as CLI):
    python scripts/payload_resolver.py --resolve RECORD_ID
    python scripts/payload_resolver.py --explain RECORD_ID
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
from typing import Any


# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

PRIORITY_LABELS: dict[int, str] = {
    1: "review_cache",
    2: "review_input_artifact",
    3: "decision_artifact",
    4: "curated_dataset",
    5: "knowledge_pack",
    6: "archived_dataset",
}

NOT_FOUND = {
    "found": False,
    "payload": None,
    "source_layer": None,
    "source_file": None,
    "checksum": None,
}


# ──────────────────────────────────────────────────────────────────────
# Checksum helper
# ──────────────────────────────────────────────────────────────────────

def _compute_checksum(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# ──────────────────────────────────────────────────────────────────────
# Search helpers for each priority layer
# ──────────────────────────────────────────────────────────────────────

def _search_jsonl(files: list[Path], id_key: str, record_id: str, *,
                  id_in_subkey: str | None = None) -> dict | None:
    """
    Search one or more JSONL files for a record.

    * files           – list of file paths (non-existent files are silently skipped)
    * id_key          – top-level key containing the record id
    * record_id       – the id to look for
    * id_in_subkey    – if set, the actual payload is under this sub-key
                        (e.g. batch_001_input stores the record under "record")
    """
    for fpath in files:
        if not fpath.exists():
            continue
        try:
            with fpath.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get(id_key) == record_id:
                        payload = obj
                        if id_in_subkey:
                            inner = obj.get(id_in_subkey)
                            if isinstance(inner, dict):
                                payload = inner
                        return {
                            "found": True,
                            "payload": payload,
                            "source_file": str(fpath.resolve()),
                            "checksum": _compute_checksum(payload),
                        }
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _search_gzip_jsonl(files: list[Path], id_key: str, record_id: str) -> dict | None:
    """Search gzipped JSONL files (knowledge packs)."""
    for fpath in files:
        if not fpath.exists():
            continue
        try:
            with gzip.open(fpath, "rt", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if obj.get(id_key) == record_id:
                        payload = obj
                        return {
                            "found": True,
                            "payload": payload,
                            "source_file": str(fpath.resolve()),
                            "checksum": _compute_checksum(payload),
                        }
        except (OSError, json.JSONDecodeError, gzip.BadGzipFile):
            continue
    return None


# ──────────────────────────────────────────────────────────────────────
# Priority-layer builders
# ──────────────────────────────────────────────────────────────────────

def _build_review_cache_files(root: Path) -> list[Path]:
    q = root / "review_queue"
    return [
        q / "pending.jsonl",
        q / "pending_expansion.jsonl",
        q / "approved.jsonl",
        q / "rejected.jsonl",
        q / "needs_revision.jsonl",
    ]


def _build_review_input_files(root: Path) -> list[Path]:
    return [
        root / "review" / "v0.2" / "batch_001_input.jsonl",
        root / "review" / "quality_reviews.jsonl",
    ]


def _build_decision_files(root: Path) -> list[Path]:
    decisions = root / "review" / "decisions"
    # Collect all JSONL files under review/decisions (any version dir)
    paths: list[Path] = []
    if decisions.exists():
        # Direct children (batch_001.jsonl etc.)
        for p in sorted(decisions.iterdir()):
            if p.suffix == ".jsonl" and p.is_file():
                paths.append(p)
        # Version subdirs like v0.2/batch_*.jsonl
        for sub in sorted(decisions.iterdir()):
            if sub.is_dir():
                for p in sorted(sub.iterdir()):
                    if p.suffix == ".jsonl" and p.is_file():
                        paths.append(p)
    return paths


def _build_curated_files(root: Path) -> list[Path]:
    curated = root / "curated" / "v0.2" / "data"
    paths: list[Path] = []
    if curated.exists():
        for p in sorted(curated.iterdir()):
            if p.suffix == ".jsonl" and p.is_file():
                paths.append(p)
    return paths


def _build_knowledge_pack_files(root: Path) -> list[Path]:
    kp = root / "knowledge_packs"
    paths: list[Path] = []
    if kp.exists():
        for p in sorted(kp.iterdir()):
            if p.suffix == ".gz" and p.is_file():
                paths.append(p)
    return paths


def _build_archived_files(root: Path) -> list[Path]:
    """Collect all JSONL files under curated/v0.1/."""
    v01 = root / "curated" / "v0.1"
    paths: list[Path] = []
    if v01.exists():
        for p in sorted(v01.rglob("*.jsonl")):
            if p.is_file():
                paths.append(p)
    return paths


# ──────────────────────────────────────────────────────────────────────
# Priority search engine
# ──────────────────────────────────────────────────────────────────────

def _search_priority(priority: int, files: list[Path], id_key: str,
                     record_id: str, *,
                     id_in_subkey: str | None = None,
                     gzipped: bool = False) -> dict | None:
    """
    Search a priority layer.

    Returns the result dict (found, payload, source_file, checksum) with
    an added ``source_layer`` key, or None if not found.
    """
    if gzipped:
        result = _search_gzip_jsonl(files, id_key, record_id)
    else:
        result = _search_jsonl(files, id_key, record_id,
                               id_in_subkey=id_in_subkey)

    if result is not None:
        result["source_layer"] = PRIORITY_LABELS.get(priority, f"priority_{priority}")
    return result


# ──────────────────────────────────────────────────────────────────────
# PayloadResolver class
# ──────────────────────────────────────────────────────────────────────

class PayloadResolver:
    """
    Canonical Payload Resolver for Atlas.

    Searches a deterministic 6-priority lookup chain to find a record's
    payload.  No workflow should manually search files — ask the resolver.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

        # Build file lists once (immutable during the session)
        self._search_layers: list[tuple[str, str, list[Path], dict]] = [
            # (source_layer, id_key, file_list, extra_kwargs)
            ("review_cache",       "id",       _build_review_cache_files(self.root),     {}),
            ("review_input_artifact", "record_id",
                                                  _build_review_input_files(self.root),
                                                  {"id_in_subkey": "record"}),
            ("decision_artifact",  "record_id", _build_decision_files(self.root),        {}),
            ("curated_dataset",    "id",       _build_curated_files(self.root),          {}),
            ("knowledge_pack",     "id",       _build_knowledge_pack_files(self.root),
                                                  {"gzipped": True}),
            ("archived_dataset",   "id",       _build_archived_files(self.root),         {}),
        ]

    # ── Public API ───────────────────────────────────────────────────

    def resolve(self, record_id: str) -> dict[str, Any]:
        """
        Resolve a record ID to its payload.

        Returns
            found          – bool
            payload        – dict or None
            source_layer   – str or None
            source_file    – str or None
            checksum       – str or None
        """
        result = self._search(record_id)
        if result is not None:
            return result
        return dict(NOT_FOUND)

    def explain(self, record_id: str) -> dict[str, Any]:
        """
        Full explain report: shows every location checked and where the
        record was found (or that it was not found).

        Returns
            record_id         – the queried id
            found             – bool
            payload           – dict or None
            source_layer      – str or None
            source_file       – str or None
            checksum          – str or None
            lookup_log        – list of {priority, source_layer, source_file, found}
        """
        log: list[dict] = []

        priorities: list[tuple[int, str, str, list[Path], dict]] = [
            (1, "review_cache",         "id",        _build_review_cache_files(self.root),   {}),
            (2, "review_input_artifact", "record_id",
                                                     _build_review_input_files(self.root),
                                                     {"id_in_subkey": "record"}),
            (3, "decision_artifact",    "record_id", _build_decision_files(self.root),       {}),
            (4, "curated_dataset",      "id",        _build_curated_files(self.root),         {}),
            (5, "knowledge_pack",       "id",        _build_knowledge_pack_files(self.root),
                                                     {"gzipped": True}),
            (6, "archived_dataset",     "id",        _build_archived_files(self.root),        {}),
        ]

        for priority, layer_name, id_key, file_list, extra in priorities:
            gzipped = extra.get("gzipped", False)
            id_in_subkey = extra.get("id_in_subkey")

            for fpath in file_list:
                if not fpath.exists():
                    log.append({
                        "priority": priority,
                        "source_layer": layer_name,
                        "source_file": str(fpath),
                        "found": False,
                        "reason": "file does not exist",
                    })
                    continue

                hit = None
                if gzipped:
                    hit = _search_gzip_jsonl([fpath], id_key, record_id)
                else:
                    hit = _search_jsonl([fpath], id_key, record_id,
                                        id_in_subkey=id_in_subkey)

                if hit is not None:
                    log.append({
                        "priority": priority,
                        "source_layer": layer_name,
                        "source_file": str(fpath),
                        "found": True,
                    })
                    return {
                        "record_id": record_id,
                        "found": True,
                        "payload": hit["payload"],
                        "source_layer": layer_name,
                        "source_file": hit["source_file"],
                        "checksum": hit["checksum"],
                        "lookup_log": log,
                    }
                else:
                    log.append({
                        "priority": priority,
                        "source_layer": layer_name,
                        "source_file": str(fpath),
                        "found": False,
                        "reason": "record not found in file",
                    })

        return {
            "record_id": record_id,
            "found": False,
            "payload": None,
            "source_layer": None,
            "source_file": None,
            "checksum": None,
            "lookup_log": log,
        }

    # ── Internal ─────────────────────────────────────────────────────

    def _search(self, record_id: str) -> dict | None:
        for layer_name, id_key, file_list, extra in self._search_layers:
            gzipped = extra.get("gzipped", False)
            id_in_subkey = extra.get("id_in_subkey")

            if gzipped:
                result = _search_gzip_jsonl(file_list, id_key, record_id)
            else:
                result = _search_jsonl(file_list, id_key, record_id,
                                       id_in_subkey=id_in_subkey)

            if result is not None:
                result["source_layer"] = layer_name
                return result
        return None

    # ── Introspection ────────────────────────────────────────────────

    def describe_layers(self) -> list[dict]:
        """Return the configured lookup layers (for diagnostics)."""
        layers = []
        for i, (layer, id_key, files, extra) in enumerate(self._search_layers, 1):
            layers.append({
                "priority": i,
                "source_layer": layer,
                "id_key": id_key,
                "files": [str(f) for f in files if f.exists()],
                "gzipped": extra.get("gzipped", False),
            })
        return layers


# ──────────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────────

def _guess_root() -> Path:
    """Walk up from CWD or script dir to find the atlas-dataset repo root."""
    candidates = [
        Path.cwd(),
        Path(__file__).resolve().parent.parent,
    ]
    for c in candidates:
        if (c / "scripts" / "atlas.py").exists():
            return c
        # Try parent
        if (c.parent / "scripts" / "atlas.py").exists():
            return c.parent
    # Fallback: ancestor walk
    for c in candidates:
        for ancestor in [c] + list(c.parents):
            if (ancestor / "scripts" / "atlas.py").exists():
                return ancestor
    raise RuntimeError(
        "Cannot determine atlas-dataset root. "
        "Run from within the repository or set ATLAS_ROOT."
    )


def cli_resolve(args: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="atlas payload")
    ap.add_argument("--resolve", help="Record ID to resolve")
    ap.add_argument("--explain", help="Record ID to explain")
    parsed = ap.parse_args(args)

    root = Path(os.environ.get("ATLAS_ROOT", str(_guess_root())))
    resolver = PayloadResolver(root)

    if parsed.resolve:
        result = resolver.resolve(parsed.resolve)
        if result["found"]:
            print(json.dumps({
                "found": True,
                "source_layer": result["source_layer"],
                "source_file": result["source_file"],
                "checksum": result["checksum"],
                "payload_keys": list(result["payload"].keys()),
            }, indent=2))
        else:
            print(json.dumps({
                "found": False,
                "message": f"Record '{parsed.resolve}' not found in any priority layer.",
            }, indent=2))
        return 0

    if parsed.explain:
        explain = resolver.explain(parsed.explain)
        _print_explain(explain)
        return 0

    # Default: show available layers
    print("Atlas Payload Resolver")
    print("=" * 60)
    for layer in resolver.describe_layers():
        print(f"\nPriority {layer['priority']}: {layer['source_layer']}")
        print(f"  ID key : {layer['id_key']}")
        for f in layer["files"]:
            print(f"  File   : {f}")
    return 0


def _print_explain(explain: dict) -> None:
    print("=" * 60)
    print(f"ATLAS PAYLOAD EXPLAIN  —  {explain.get('record_id', '?')}")
    print("=" * 60)

    for entry in explain.get("lookup_log", []):
        status = "✓ FOUND" if entry["found"] else "✗ MISS"
        reason = entry.get("reason", "")
        print(f"  [{status}] P{entry['priority']} {entry['source_layer']}")
        print(f"         {entry['source_file']}")
        if reason:
            print(f"         ({reason})")
        if entry["found"]:
            print()

    print("-" * 60)
    if explain.get("found"):
        print(f"RESULT: FOUND")
        print(f"  Source layer : {explain['source_layer']}")
        print(f"  Source file  : {explain['source_file']}")
        print(f"  Checksum     : {explain['checksum']}")
        print(f"  Payload keys : {list(explain['payload'].keys())}")
    else:
        print(f"RESULT: NOT FOUND — record '{explain.get('record_id')}' could not be resolved")
    print("=" * 60)


# ──────────────────────────────────────────────────────────────────────
# Standalone entry
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    import sys
    raise SystemExit(cli_resolve(sys.argv[1:]))
