#!/usr/bin/env python3
"""Extract one MMLU subject parquet file to Atlas JSONL."""
import json, sys, os
import pyarrow.parquet as pq

parquet_path = sys.argv[1]
output_path = sys.argv[2]
subject = sys.argv[3]
cat = sys.argv[4]
subcat = sys.argv[5]

table = pq.read_table(parquet_path)
rows = table.to_pydict()
keys = list(rows.keys())
n = len(rows[keys[0]])

out = []
for i in range(n):
    q = str(rows.get('question', [''])[i]) if 'question' in rows else ''
    a_raw = rows.get('answer', [''])[i] if 'answer' in rows else ''
    a = str(a_raw) if a_raw is not None else ''
    
    # Add choices if present
    choices = rows.get('choices', None)
    if choices and i < len(choices) and choices[i]:
        letters = ['A', 'B', 'C', 'D']
        for j, ch in enumerate(choices[i]):
            if j < len(letters):
                q += '\n' + letters[j] + '. ' + str(ch)
    
    if not q or not a:
        continue
    
    # Convert answer index (0-3) to letter if needed
    if a.isdigit() and choices and i < len(choices) and choices[i]:
        idx = int(a)
        if 0 <= idx < len(choices[i]):
            a = str(choices[i][idx])
    
    out.append({
        "id": "mmlu_" + subject + "_" + str(i).zfill(6),
        "category": cat,
        "subcategory": subcat,
        "type": "qa",
        "source": {"name": "cais/mmlu (" + subject + ")", "url": "https://huggingface.co/datasets/cais/mmlu", "license": "MIT"},
        "messages": [{"role": "user", "content": q}, {"role": "assistant", "content": a}],
        "language": "en", "difficulty": 3, "tags": ["mmlu", subject],
        "quality_score": 8, "verified": False, "notes": ""
    })

with open(output_path, "w") as f:
    for rec in out:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

print(len(out))
