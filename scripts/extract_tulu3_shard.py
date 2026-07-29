"""Extract Tulu-3 shard using python3.11 with correct ID generation."""
import json, pyarrow.parquet as pq, sys

shard_num = int(sys.argv[1])
parquet_path = sys.argv[2]
output_path = sys.argv[3]

table = pq.read_table(parquet_path)
rows = table.to_pydict()
n = len(rows['id'])
msgs = rows.get('messages', [])
sources = rows.get('source', [''] * n) if isinstance(rows.get('source'), list) else [''] * n

# Calculate start ID based on shard number
# Shard 0: 0-156557, Shard 1: 156558-313115, etc.
SHARD_SIZE = 156558
start_id = shard_num * SHARD_SIZE

out = []
for i in range(n):
    messages = msgs[i]
    clean = []
    for m in messages:
        role = m.get('role', '')
        content = m.get('content', '')
        if role == 'prompter':
            role = 'user'
        if role in ('user', 'assistant', 'system'):
            clean.append({"role": role, "content": content})
    if not clean:
        continue
    source_str = str(sources[i]) if isinstance(sources, list) else ''
    
    out.append({
        "id": f"s6_tulu3_{start_id + i:06d}",
        "category": "01_foundation",
        "subcategory": "instruction-following",
        "type": "conversation" if len(clean) > 2 else "qa",
        "source": {
            "name": source_str or "allenai/tulu-3-sft-mixture",
            "url": "https://huggingface.co/datasets/allenai/tulu-3-sft-mixture",
            "license": "ODC-BY"
        },
        "messages": clean,
        "language": "en",
        "difficulty": 2,
        "tags": ["sft", "tulu-3"],
        "quality_score": 7,
        "verified": False,
        "notes": ""
    })

with open(output_path, "w") as f:
    for rec in out:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

print(f"Shard {shard_num}: {len(out)} records (IDs {start_id}-{start_id + n - 1})")
