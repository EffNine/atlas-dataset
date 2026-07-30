#!/usr/bin/env python3
"""Extract Wikipedia science articles for 06_science_engineering category."""
import json, pyarrow.parquet as pq, sys, os
from huggingface_hub import hf_hub_download

SCIENCE_KW = [
    "physics", "chemistry", "biology", "mathematics", "engineering", 
    "science", "astronomy", "geology", "medicine", "molecular",
    "genetics", "evolution", "ecosystem", "quantum", "thermodynamics",
    "electromagnetism", "mechanics", "optics", "nuclear", "atomic",
    "particle", "molecule", "cell", "dna", "protein", "organism",
    "species", "biodiversity", "climate", "geology", "mineral",
    "volcano", "earthquake", "ocean", "atmosphere", "planet",
    "star", "galaxy", "solar", "orbit", "telescope", "spectrum",
    "chemical", "reaction", "element", "compound", "alloy",
    "equation", "algorithm", "statistics", "probability",
    "calculus", "algebra", "geometry", "graph theory",
    "differential", "integral", "topology", "number theory",
    "neuroscience", "anatomy", "physiology", "pathology",
    "pharmacology", "immunology", "microbiology", "biochemistry",
    "ecology", "zoology", "botany", "paleontology", "anthropology",
    "archaeology", "geophysics", "hydrology", "meteorology",
    "astrophysics", "cosmology", "relativity", "gravitational",
    "wave", "frequency", "velocity", "acceleration", "force",
    "energy", "momentum", "entropy", "magnetism", "electricity",
    "semiconductor", "circuit", "signal", "processor", "sensor",
    "robotics", "automation", "biotechnology", "nanotechnology"
]

SHARD = int(sys.argv[1]) if len(sys.argv) > 1 else 0

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

SCIENCE_KW_SET = set(kw.lower() for kw in SCIENCE_KW)

def is_science(title, text):
    t = title.lower()
    content = text.lower()[:3000]
    return any(kw in t or kw in content for kw in SCIENCE_KW_SET)

atlas = []
for i in range(total):
    title = data["title"][i]
    text = data["text"][i]
    if not title or not text:
        continue
    if is_science(title, text):
        content = text[:3000]
        atlas.append({
            "id": f"wiki_sci_{SHARD}_{i:07d}",
            "category": "06_science_engineering",
            "subcategory": "science",
            "type": "document",
            "source": {"name": "wikimedia/wikipedia", "url": data["url"][i], "license": "CC-BY-SA-3.0"},
            "messages": [
                {"role": "user", "content": f"Explain: {title}"},
                {"role": "assistant", "content": content}
            ],
            "language": "en",
            "difficulty": 2,
            "tags": ["wikipedia", "science"],
            "quality_score": 7,
            "verified": False,
            "notes": ""
        })

output = f"raw/generated/wiki_sci_shard{SHARD}_atlas.jsonl"
with open(output, "w") as f:
    for rec in atlas:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

print(f"Science articles: {len(atlas)} -> {output}")
