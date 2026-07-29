#!/usr/bin/env python3
"""Extract OpenAssistant/oasst1 conversation tree to Atlas JSONL."""
import json, sys, os
import pyarrow.parquet as pq
from collections import defaultdict

parquet_path = sys.argv[1]
output_path = sys.argv[2]
max_records = int(sys.argv[3]) if len(sys.argv) > 3 else 200000

table = pq.read_table(parquet_path)
rows = table.to_pydict()
n = len(rows['message_id'])

# Build conversation tree from flat message list
# Each row has: message_id, parent_id, text, role, message_tree_id
messages_by_tree = defaultdict(list)
for i in range(n):
    tree_id = str(rows['message_tree_id'][i]) if rows['message_tree_id'][i] else str(rows['message_id'][i])
    messages_by_tree[tree_id].append({
        'id': str(rows['message_id'][i]),
        'parent_id': str(rows['parent_id'][i]) if rows['parent_id'][i] else None,
        'text': str(rows['text'][i]) if rows['text'][i] else '',
        'role': str(rows['role'][i]) if rows['role'][i] else '',
        'lang': str(rows['lang'][i]) if rows['lang'][i] else 'en',
    })

out = []
record_id = 0

for tree_id, msgs in messages_by_tree.items():
    if record_id >= max_records:
        break
    
    # Build a conversation by following parent links from leaf to root
    # Find messages without children (leaf nodes - likely assistant responses)
    msg_map = {m['id']: m for m in msgs}
    children = defaultdict(list)
    for m in msgs:
        if m['parent_id']:
            children[m['parent_id']].append(m['id'])
    
    # Find leaf messages (assistant responses at the end of threads)
    leaf_ids = [m['id'] for m in msgs if m['id'] not in children and m['role'] == 'assistant']
    
    for leaf_id in leaf_ids[:5]:  # max 5 threads per tree
        if record_id >= max_records:
            break
        
        # Walk up from leaf to root to build conversation
        conversation = []
        current = leaf_id
        while current and current in msg_map:
            m = msg_map[current]
            role = 'user' if m['role'] in ('prompter', 'user') else 'assistant'
            conversation.insert(0, {'role': role, 'content': m['text']})
            current = m['parent_id']
        
        if len(conversation) < 2:
            continue
        
        lang = msgs[0]['lang'] if msgs else 'en'
        if lang != 'en':
            continue  # English only
        
        out.append({
            "id": f"oasst1_{record_id:06d}",
            "category": "01_foundation",
            "subcategory": "instruction-following",
            "type": "conversation" if len(conversation) > 2 else "qa",
            "source": {
                "name": "OpenAssistant/oasst1",
                "url": "https://huggingface.co/datasets/OpenAssistant/oasst1",
                "license": "Apache-2.0"
            },
            "messages": conversation[:6],
            "language": "en",
            "difficulty": 2,
            "tags": ["oasst1", "conversation"],
            "quality_score": 7,
            "verified": False,
            "notes": ""
        })
        record_id += 1

with open(output_path, "w") as f:
    for rec in out:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

print(len(out))
