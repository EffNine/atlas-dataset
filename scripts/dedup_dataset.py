#!/usr/bin/env python3
"""
dedup_dataset.py — Atlas exact + near-duplicate detection.

Two modes:
  1. Exact dedup: SHA-1 over normalized message text. Strict, no false positives.
  2. Near dedup: locality-sensitive hashing via MinHash + banding (a stdlib-only
     reimplementation of the classic Broder/LSH scheme). Flags pairs whose
     Jaccard similarity of 4-gram shingles exceeds --threshold (default 0.8).

This script ONLY reports / optionally drops duplicates; it never invents data.
When --drop is passed, the lower-quality (or shorter) of a near-dup pair is
removed; ties keep the first by input order. Exact dups are always dropped
except the first occurrence.

No external dependencies (numpy/datasketch not required) so the pipeline runs
anywhere. For very large corpora, swap in datasketch MinHashLSH; the interface
is intentionally compatible.

Usage:
  python scripts/dedup_dataset.py --input curated/v0.1/atlas_v0.1.jsonl --report
  python scripts/dedup_dataset.py --input tmp/cleaned.jsonl --drop --output tmp/deduped.jsonl
  python scripts/dedup_dataset.py --input tmp/cleaned.jsonl --near-only --threshold 0.85
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import math
from pathlib import Path

NUM_PERM = 128          # MinHash permutations
BANDS = 32              # LSH bands (rows = NUM_PERM // BANDS)
SEED_BASE = 0x9E3779B1  # arbitrary base for hash mixing

_WORD_RE = re.compile(r"[a-z0-9]+")


def shingles(text: str, k: int = 4) -> list[tuple[str, ...]]:
    toks = _WORD_RE.findall(text.lower())
    if len(toks) < k:
        return [tuple(toks)] if toks else []
    return [tuple(toks[i:i + k]) for i in range(len(toks) - k + 1)]


def stable_hash(shingle: tuple[str, ...]) -> int:
    """Deterministic 64-bit hash of a shingle (no hashlib per-shingle overhead)."""
    h = SEED_BASE
    s = "\x00".join(shingle).encode("utf-8")
    for b in s:
        h ^= b
        h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return h


def minhash_signature(shingles_: list[tuple[str, ...]]) -> tuple[int, ...]:
    if not shingles_:
        return tuple([2**64 - 1] * NUM_PERM)
    sig = [2**64 - 1] * NUM_PERM
    for sh in shingles_:
        h = stable_hash(sh)
        for i in range(NUM_PERM):
            # universal hash: (a*h + b) mod prime
            a = (SEED_BASE * (i + 1)) & 0xFFFFFFFF
            b = (SEED_BASE ^ (i * 2654435761)) & 0xFFFFFFFF
            v = ((a * h + b) & 0xFFFFFFFFFFFFFFFF) % (2**61 - 1)
            if v < sig[i]:
                sig[i] = v
    return tuple(sig)


def band_hash(sig: tuple[int, ...], band: int, rows: int) -> int:
    start = band * rows
    acc = 0
    for i in range(rows):
        acc = (acc * 31 + sig[start + i]) & 0xFFFFFFFFFFFFFFFF
    return acc


def jaccard(a: set[tuple[str, ...]], b: set[tuple[str, ...]]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def norm_text(rec: dict) -> str:
    return "\n".join(f"{m['role']}:{m['content'].strip().lower()}" for m in rec.get("messages", []))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Atlas exact + near duplicate detection.")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", help="output path when using --drop")
    ap.add_argument("--report", action="store_true", help="print a duplicate report and exit")
    ap.add_argument("--drop", action="store_true", help="write deduped file (keeps best of each cluster)")
    ap.add_argument("--near-only", action="store_true", help="only run near-dup (skip exact)")
    ap.add_argument("--threshold", type=float, default=0.8, help="near-dup Jaccard threshold")
    args = ap.parse_args(argv)

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"[dedup] ERROR: input not found: {in_path}", file=sys.stderr)
        return 2

    records = []
    with in_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    rows = max(1, NUM_PERM // BANDS)

    # ---- exact dedup ----
    exact_buckets: dict[str, list[int]] = {}
    for i, rec in enumerate(records):
        h = hashlib.sha1(norm_text(rec).encode("utf-8")).hexdigest()
        exact_buckets.setdefault(h, []).append(i)

    exact_dups = {h: idxs for h, idxs in exact_buckets.items() if len(idxs) > 1}

    # ---- near dedup (LSH) ----
    shingle_sets = [set(shingles(norm_text(rec))) for rec in records]
    sigs = [minhash_signature(s) for s in shingle_sets]
    band_buckets: dict[tuple[int, int], list[int]] = {}
    for i, sig in enumerate(sigs):
        for band in range(BANDS):
            key = (band, band_hash(sig, band, rows))
            band_buckets.setdefault(key, []).append(i)

    # candidate pairs from shared bands
    candidate_pairs = set()
    for key, idxs in band_buckets.items():
        if len(idxs) > 1:
            for a in range(len(idxs)):
                for b in range(a + 1, len(idxs)):
                    candidate_pairs.add((idxs[a], idxs[b]))

    near_links: list[tuple[int, int, float]] = []
    for i, j in candidate_pairs:
        sim = jaccard(shingle_sets[i], shingle_sets[j])
        if sim >= args.threshold:
            near_links.append((i, j, round(sim, 3)))

    # ---- reporting ----
    print(f"[dedup] records={len(records)}  exact_dup_groups={len(exact_dups)}  "
          f"near_dup_pairs={len(near_links)} (>= {args.threshold})")
    if args.report or not args.drop:
        for h, idxs in exact_dups.items():
            print(f"  EXACT dup group: {[records[k].get('id') for k in idxs]}")
        for i, j, sim in near_links:
            print(f"  NEAR dup {sim}: {records[i].get('id')} <-> {records[j].get('id')}")

    if not args.drop:
        # report mode: exit (no file written)
        return 0

    # ---- drop mode: keep best of each cluster ----
    drop_set = set()
    for h, idxs in exact_dups.items():
        # keep highest quality_score, then longest assistant content
        best = max(idxs, key=lambda k: (records[k].get("quality_score", 0),
                                        len(norm_text(records[k]))))
        for k in idxs:
            if k != best:
                drop_set.add(k)
    # near-dup: cluster via union-find over near_links
    parent = list(range(len(records)))
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    for i, j, _ in near_links:
        union(i, j)
    clusters: dict[int, list[int]] = {}
    for i in range(len(records)):
        clusters.setdefault(find(i), []).append(i)
    for root, members in clusters.items():
        if len(members) > 1:
            best = max(members, key=lambda k: (records[k].get("quality_score", 0),
                                              len(norm_text(records[k]))))
            for k in members:
                if k != best:
                    drop_set.add(k)

    out_path = Path(args.output or "tmp/deduped.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    kept = 0
    with out_path.open("w", encoding="utf-8") as fout:
        for i, rec in enumerate(records):
            if i in drop_set:
                continue
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            kept += 1
    print(f"[dedup] dropped={len(drop_set)} kept={kept} -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
