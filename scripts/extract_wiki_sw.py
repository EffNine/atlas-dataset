#!/usr/bin/env python3
"""Extract Wikipedia software engineering articles for 02_software_engineering."""
import json, pyarrow.parquet as pq, sys
from huggingface_hub import hf_hub_download

SW_KW = [
    "software", "programming", "algorithm", "data structure", 
    "computing", "computer science", "operating system", "database",
    "network protocol", "programming language", "compiler", "debugger",
    "api", "framework", "library", "code", "coding",
    "software engineering", "development", "web development",
    "mobile app", "application", "server", "client", "backend",
    "frontend", "devops", "continuous integration", "deployment",
    "version control", "git", "docker", "kubernetes", "container",
    "microservice", "architecture pattern", "design pattern",
    "object-oriented", "functional programming", "test-driven",
    "agile", "scrum", "refactoring", "code review",
    "python", "javascript", "java", "c++", "ruby", "rust", "go",
    "typescript", "html", "css", "sql", "nosql", "rest api",
    "graphql", "http", "tcp/ip", "encryption", "authentication",
    "cloud computing", "aws", "azure", "google cloud",
    "linux", "unix", "shell", "bash", "command line",
    "open source", "github", "stack overflow"
]

SHARD = int(sys.argv[1])
print(f"Loading Wikipedia shard {SHARD}...")
path = hf_hub_download(
    repo_id="wikimedia/wikipedia",
    repo_type="dataset",
    filename=f"20231101.en/train-{SHARD:05d}-of-00041.parquet"
)

t = pq.read_table(path)
data = t.to_pydict()
total = len(data["title"])
print(f"Total articles: {total}")

KW_SET = set(kw.lower() for kw in SW_KW)

def is_sw(title, text):
    t = title.lower()
    content = text.lower()[:3000]
    return any(kw in t or kw in content for kw in KW_SET)

atlas = []
for i in range(total):
    title = data["title"][i]
    text = data["text"][i]
    if not title or not text:
        continue
    if is_sw(title, text):
        content = text[:3000]
        atlas.append({
            "id": f"wiki_sw_{SHARD}_{i:07d}",
            "category": "02_software_engineering",
            "subcategory": "software-engineering",
            "type": "document",
            "source": {"name": "wikimedia/wikipedia", "url": data["url"][i], "license": "CC-BY-SA-3.0"},
            "messages": [
                {"role": "user", "content": f"Explain: {title}"},
                {"role": "assistant", "content": content}
            ],
            "language": "en",
            "difficulty": 2,
            "tags": ["wikipedia", "software"],
            "quality_score": 7,
            "verified": False,
            "notes": ""
        })

output = f"raw/generated/wiki_sw_shard{SHARD}_atlas.jsonl"
with open(output, "w") as f:
    for rec in atlas:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

print(f"Software articles: {len(atlas)} -> {output}")
