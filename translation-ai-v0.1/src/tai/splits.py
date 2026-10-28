"""Step 3 — Deterministic train/val/test splits with leak prevention.

Method (per language, stratified):
  1. Group records by near-identity key: lowercase, keep alphanumerics only,
     of the source side. Near-identical sources land in one group.
  2. Sort group keys; assign each group by sha256(key) uniform value:
     < test_frac -> test, < test_frac+val_frac -> val, else train.
     Whole groups go to one split, so near-duplicates cannot leak.
  3. Target exact 90/5/5 is approximate (group-granular); manifest records
     the realised counts.

Usage:
    PYTHONPATH=src .venv/bin/python -m tai.splits --inp data/clean \
        --out data/splits --seed 7
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path

LANGS = ("zh", "ja", "ko", "ms")
TEST_FRAC, VAL_FRAC = 0.05, 0.05


def norm_key(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    return "".join(ch for ch in text if ch.isalnum())


def split_of(key: str) -> str:
    h = hashlib.sha256(key.encode("utf-8")).digest()
    u = int.from_bytes(h[:8], "big") / 2**64
    if u < TEST_FRAC:
        return "test"
    if u < TEST_FRAC + VAL_FRAC:
        return "val"
    return "train"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inp", default="data/clean")
    ap.add_argument("--out", default="data/splits")
    ap.add_argument("--seed", type=int, default=7)  # recorded; partition itself is hash-based
    args = ap.parse_args()
    inp, out = Path(args.inp), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    manifest = {"seed": args.seed, "test_frac": TEST_FRAC, "val_frac": VAL_FRAC,
                "method": "sha256(norm_source) group partition, per-language",
                "per_lang": {}}
    for lang in LANGS:
        f = inp / f"clean_{lang}-en.jsonl"
        groups: dict[str, list] = {}
        order: dict[str, int] = {}
        with open(f, encoding="utf-8") as fin:
            for idx, line in enumerate(fin):
                rec = json.loads(line)
                k = norm_key(rec["source"]) or f"__empty__{idx}"
                groups.setdefault(k, []).append(rec)
                order.setdefault(k, idx)
        buckets = {"train": [], "val": [], "test": []}
        for k in sorted(groups, key=lambda k: order[k]):
            buckets[split_of(k)].extend(groups[k])
        # deterministic in-split order: keep file order (stable)
        counts = {}
        for split, rows in buckets.items():
            with open(out / f"{split}_{lang}-en.jsonl", "w", encoding="utf-8") as fo:
                for r in rows:
                    fo.write(json.dumps(r, ensure_ascii=False) + "\n")
            counts[split] = len(rows)
        # leak check: norm keys disjoint across splits
        keysets = {}
        for split in buckets:
            ks = set()
            for r in buckets[split]:
                ks.add(norm_key(r["source"]))
            keysets[split] = ks
        leak = (keysets["train"] & keysets["val"]) | (keysets["train"] & keysets["test"]) | (keysets["val"] & keysets["test"])
        assert not leak, f"{lang}: {len(leak)} leaked keys!"
        manifest["per_lang"][lang] = {"counts": counts, "groups": len(groups),
                                      "leak_keys": 0}
        print(f"{lang}-en: {counts} groups={len(groups)} leak=0", flush=True)

    with open(out / "split_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
