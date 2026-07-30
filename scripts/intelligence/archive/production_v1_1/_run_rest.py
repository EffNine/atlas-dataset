#!/usr/bin/env python3
"""Process non-Tulu-3 sources sequentially, writing to a single temp file."""
import sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from difficulty_analyzer import process_file

ROOT = Path("/Users/afnanrudy/Github-Projects/atlas-dataset")
TEMP = ROOT / "metadata" / "intelligence" / "_tmp"
TEMP.mkdir(parents=True, exist_ok=True)
OUT = TEMP / "classified_rest.jsonl"

sources = [
    ("raw/generated/openwebmath_shard*_atlas.jsonl", "openwebmath"),
    ("raw/generated/arxiv_*_atlas.jsonl", "arxiv"),
    ("raw/generated/c4_ai_shard*_atlas.jsonl", "c4"),
]

print(f"REST: Processing OpenWebMath + ArXiv + C4", flush=True)
total = 0
start = time.time()
with open(OUT, "w") as out:
    for glob_pat, label in sources:
        shards = sorted(ROOT.glob(glob_pat))
        shards = [f for f in shards if f.stat().st_size > 0]
        print(f"  {label}: {len(shards)} shards", flush=True)
        for i, shard in enumerate(shards, 1):
            t0 = time.time()
            shard_total, shard_classified, results, errors = process_file(shard, None)
            for r in results:
                out.write(json.dumps(r, ensure_ascii=False) + "\n")
            out.flush()
            total += len(results)
            elapsed = time.time() - t0
            rate = len(results) / max(elapsed, 0.1)
            if i % 20 == 0 or i == len(shards):
                print(f"  [{i}/{len(shards)}] {label}/{shard.name}: {len(results)} classified ({elapsed:.0f}s, {rate:.0f}/s)", flush=True)

elapsed = time.time() - start
print(f"REST DONE: {total} total in {elapsed:.0f}s ({elapsed/60:.1f}m)", flush=True)
