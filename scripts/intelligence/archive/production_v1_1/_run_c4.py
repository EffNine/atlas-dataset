#!/usr/bin/env python3
"""Process C4 shards only (parallel with OpenWebMath)."""
import sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from difficulty_analyzer import process_file

ROOT = Path("/Users/afnanrudy/Github-Projects/atlas-dataset")
SHARDS = sorted(ROOT.glob("raw/generated/c4_ai_shard*_atlas.jsonl"))
SHARDS = [f for f in SHARDS if f.stat().st_size > 0]
TEMP = ROOT / "metadata" / "intelligence" / "_tmp"
TEMP.mkdir(parents=True, exist_ok=True)
OUT = TEMP / "classified_c4.jsonl"

print(f"C4: {len(SHARDS)} shards", flush=True)
total = 0
start = time.time()
with open(OUT, "w") as out:
    for i, shard in enumerate(SHARDS, 1):
        t0 = time.time()
        _, _, results, errors = process_file(shard, None)
        for r in results:
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
        out.flush()
        total += len(results)
        rate = len(results) / max(time.time() - t0, 0.1)
        if i % 2 == 0 or i == len(SHARDS):
            print(f"  [{i}/{len(SHARDS)}] {shard.name}: {len(results)} ({time.time()-t0:.0f}s, {rate:.0f}/s)", flush=True)
print(f"C4 DONE: {total} in {(time.time()-start)/60:.1f}m", flush=True)
