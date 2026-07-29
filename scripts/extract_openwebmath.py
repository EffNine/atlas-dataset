#!/usr/bin/env python3
"""Extract OpenWebMath parquet shards to Atlas JSONL."""
import json, sys, os
import pyarrow.parquet as pq

shard_idx = int(sys.argv[1])
parquet_path = sys.argv[2]
output_path = sys.argv[3]

table = pq.read_table(parquet_path)
rows = table.to_pydict()
keys = list(rows.keys())
n = min(len(rows[keys[0]]), 15000)

out = []
for i in range(n):
    text = ""
    for k in keys:
        v = rows[k][i]
        if isinstance(v, str) and len(v) > 50:
            text = v
            break
    if not text or len(text) < 100:
        continue
    text = text[:2000]
    
    out.append({
        "id": f"openwebmath_{shard_idx}_{i:06d}",
        "category": "06_science_engineering",
        "subcategory": "mathematics",
        "type": "qa",
        "source": {"name": "open-web-math/open-web-math", "url": "https://huggingface.co/datasets/open-web-math/open-web-math", "license": "ODC-BY"},
        "messages": [
            {"role": "user", "content": "Explain this mathematical concept."},
            {"role": "assistant", "content": text}
        ],
        "language": "en", "difficulty": 3, "tags": ["math", "science"],
        "quality_score": 7, "verified": False, "notes": ""
    })

with open(output_path, "w") as f:
    for rec in out:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

print(len(out))
