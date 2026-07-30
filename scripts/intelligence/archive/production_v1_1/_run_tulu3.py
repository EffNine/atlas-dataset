#!/usr/bin/env python3
"""Process Tulu-3 shards sequentially, output to temp file."""
import sys, os, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from difficulty_analyzer import process_file

ROOT = Path("/Users/afnanrudy/Github-Projects/atlas-dataset")
SHARDS = sorted(ROOT.glob("raw/generated/tulu3_shard*_atlas.jsonl"))
SHARDS = [f for f in SHARDS if f.stat().st_size > 0]
TEMP = ROOT / "metadata" / "intelligence" / "_tmp"
TEMP.mkdir(parents=True, exist_ok=True)
OUT = TEMP / "classified_tulu3.jsonl"

print(f"TULU-3: {len(SHARDS)} shards", flush=True)
total = 0
start = time.time()
with open(OUT, "w") as out:
    for i, shard in enumerate(SHARDS, 1):
        t0 = time.time()
        shard_total, shard_classified, results, errors = process_file(shard, None)
        for r in results:
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
        out.flush()
        total += len(results)
        elapsed = time.time() - t0
        print(f"  [{i}/{len(SHARDS)}] {shard.name}: {len(results)} classified, {len(errors)} errors ({elapsed:.0f}s)", flush=True)

elapsed = time.time() - start
print(f"TULU-3 DONE: {total} total in {elapsed:.0f}s ({elapsed/60:.1f}m)", flush=True)
