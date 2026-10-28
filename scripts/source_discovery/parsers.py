"""Generic parsers for Source Discovery v1.0.

Supported: JSON, JSONL, CSV, TSV, TXT (one segment per non-empty line),
compressed archives (.zip/.tar.gz/.tgz — listing + selective extract),
Parquet (optional pyarrow; clear error when unavailable), Hugging Face
streaming samples (optional datasets; lazy import), git checkouts (via
subprocess git clone --depth 1; caller confines output to tmp/).

All parsers are deterministic (input order preserved, no sampling, no
shuffling) and report malformed inputs instead of silently dropping them.
"""

from __future__ import annotations

import csv
import json
import subprocess
import tarfile
import zipfile
from pathlib import Path
from typing import Any


def detect_format(path: str | Path) -> str:
    suffixes = [s.lower() for s in Path(path).suffixes]
    joined = "".join(suffixes)
    if joined.endswith(".jsonl") or joined.endswith(".ndjson"):
        return "jsonl"
    if joined.endswith(".json"):
        return "json"
    if joined.endswith(".tsv"):
        return "tsv"
    if joined.endswith(".csv"):
        return "csv"
    if joined.endswith(".txt"):
        return "txt"
    if joined.endswith(".parquet"):
        return "parquet"
    if joined.endswith(".zip"):
        return "zip"
    if ".tar" in joined or joined.endswith(".tgz"):
        return "tar"
    return "unknown"


def parse_jsonl(path: str | Path) -> tuple[list[Any], list[dict]]:
    records, errors = [], []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            s = line.strip()
            if not s:
                continue
            try:
                records.append(json.loads(s))
            except json.JSONDecodeError as exc:
                errors.append({"lineno": lineno, "error": str(exc)[:200]})
    return records, errors


def parse_json(path: str | Path) -> tuple[list[Any], list[dict]]:
    with open(path, encoding="utf-8") as f:
        obj = json.load(f)
    if isinstance(obj, list):
        return obj, []
    return [obj], []


def parse_csv(path: str | Path, delimiter: str = ",") -> tuple[list[dict], list[dict]]:
    records, errors = [], []
    with open(path, encoding="utf-8", newline="") as f:
        try:
            reader = csv.DictReader(f, delimiter=delimiter)
            for lineno, row in enumerate(reader, 2):
                records.append(dict(row))
        except csv.Error as exc:
            errors.append({"error": str(exc)[:200]})
    return records, errors


def parse_tsv(path: str | Path) -> tuple[list[dict], list[dict]]:
    return parse_csv(path, delimiter="\t")


def parse_txt(path: str | Path) -> tuple[list[str], list[dict]]:
    with open(path, encoding="utf-8") as f:
        return [ln.rstrip("\n") for ln in f if ln.strip()], []


def parse_parquet(path: str | Path) -> tuple[list[dict], list[dict]]:
    try:
        import pyarrow.parquet as pq  # lazy: optional
    except ImportError as exc:
        return [], [{"error": f"pyarrow_unavailable: {exc}"}]
    table = pq.read_table(path)
    return table.to_pylist(), []


def list_archive(path: str | Path) -> list[str]:
    fmt = detect_format(path)
    if fmt == "zip":
        with zipfile.ZipFile(path) as z:
            return sorted(z.namelist())
    if fmt == "tar":
        with tarfile.open(path, "r:*") as t:
            return sorted(m.name for m in t.getmembers() if m.isfile())
    raise ValueError(f"not an archive: {path}")


def parse_file(path: str | Path) -> tuple[list[Any], list[dict], str]:
    fmt = detect_format(path)
    if fmt == "jsonl":
        recs, errs = parse_jsonl(path)
    elif fmt == "json":
        recs, errs = parse_json(path)
    elif fmt == "csv":
        recs, errs = parse_csv(path)
    elif fmt == "tsv":
        recs, errs = parse_tsv(path)
    elif fmt == "txt":
        recs, errs = parse_txt(path)
    elif fmt == "parquet":
        recs, errs = parse_parquet(path)
    else:
        return [], [{"error": f"unsupported_format:{fmt}"}], fmt
    return recs, errs, fmt


def git_shallow_clone(url: str, dest: str | Path,
                      timeout_s: int = 300) -> dict[str, Any]:
    """Shallow-clone a git repo into dest (caller ensures dest is tmp-safe)."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["git", "clone", "--depth", "1", url, str(dest)],
        capture_output=True, text=True, timeout=timeout_s)
    return {"returncode": proc.returncode, "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-2000:], "dest": str(dest)}


def hf_stream_sample(repo_id: str, config: str = "",
                     split: str = "train",
                     limit: int = 50) -> tuple[list[dict], dict]:
    """Stream the first `limit` rows of an HF dataset (lazy import)."""
    from datasets import load_dataset  # lazy: optional
    kw: dict[str, Any] = {"split": split, "streaming": True}
    if config:
        ds = load_dataset(repo_id, config, **kw)
    else:
        ds = load_dataset(repo_id, **kw)
    rows = []
    for i, ex in enumerate(ds):
        if i >= limit:
            break
        rows.append(dict(ex))
    return rows, {"repo_id": repo_id, "config": config, "split": split,
                  "rows": len(rows)}
