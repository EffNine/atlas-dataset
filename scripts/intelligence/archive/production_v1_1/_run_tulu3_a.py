#!/usr/bin/env python3
"""Process Tulu-3 shards 0-2 (half the data)."""
import sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from difficulty_analyzer import process_file

ROOT = Path("/Users/afnanrudy/Github-Projects/atlas-dataset")
SHARDS = sorted(ROOT.glob("raw/generated/tulu3_shard0*_atlas.jsonl"))
SHARDS += sorted(ROOT.glob("raw/generated/tulu3_shard1*_atlas.jsonl"))
SHARDS += sorted(ROOT.glob("raw/generated/tulu3_shard2*_atlas.jsonl"))
TEMP = ROOT / "metadata" / "intelligence" / "_tmp"
TEMP.mkdir(parents=True, exist_ok=True)
OUT = TEMP / "classified_tulu3_A.jsonl"

print(f"TULU3-A (shards 0-2): {len(SHARDS)} shards", flush=True)
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
        print(f"  [{i}/{len(SHARDS)}] {shard.name}: {len(results)} classified ({time.time()-t0:.0f}s)", flush=True)
print(f"TULU3-A DONE: {total} in {(time.time()-start)/60:.1f}m", flush=True)
