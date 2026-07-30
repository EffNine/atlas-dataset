#!/usr/bin/env python3
"""Extract Wikipedia creative/arts articles for 08_creative_knowledge."""
import json, pyarrow.parquet as pq, sys
from huggingface_hub import hf_hub_download

CREATIVE_KW = [
    "art", "artist", "painting", "painter", "sculpture", "sculptor",
    "music", "musician", "song", "composer", "orchestra", "symphony",
    "jazz", "rock", "pop music", "classical music", "opera",
    "literature", "novel", "poem", "poetry", "poet", "author",
    "writer", "fiction", "nonfiction", "biography", "playwright",
    "drama", "theater", "theatre", "film", "movie", "cinema",
    "actor", "actress", "director", "producer", "screenwriter",
    "photography", "photographer", "digital art", "graphic design",
    "architecture", "architect", "fashion", "designer", "couture",
    "dance", "dancer", "choreography", "ballet", "contemporary art",
    "museum", "gallery", "exhibition", "curator", "art history",
    "renaissance", "baroque", "romanticism", "impressionism",
    "modernism", "surrealism", "abstract art", "pop art",
    "landscape", "portrait", "still life", "watercolor", "oil painting",
    "drawing", "printmaking", "ceramics", "pottery", "weaving",
    "jewelry", "glass art", "mosaic", "fresco", "calligraphy",
    "illustration", "animation", "cartoon", "comic", "graphic novel",
    "typography", "logo design", "branding", "interior design",
    "landscape architecture", "urban design", "industrial design",
    "furniture design", "textile", "costume design", "makeup art",
    "culinary", "cooking", "chef", "gastronomy", "wine making",
    "craft", "handicraft", "folk art", "indigenous art",
    "street art", "graffiti", "installation art", "performance art",
    "conceptual art", "video art", "sound art", "mixed media",
    "collage", "assemblage", "relief", "engraving", "etching",
    "lithography", "screen printing", "serigraphy", "tapestry",
    "embroidery", "knitting", "crochet", "quilting", "woodworking",
    "metalworking", "papermaking", "bookbinding", "origami"
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

KW_SET = set(kw.lower() for kw in CREATIVE_KW)

def is_creative(title, text):
    t = title.lower()
    content = text.lower()[:3000]
    return any(kw in t or kw in content for kw in KW_SET)

atlas = []
for i in range(total):
    title = data["title"][i]
    text = data["text"][i]
    if not title or not text:
        continue
    if is_creative(title, text):
        atlas.append({
            "id": f"wiki_cre_{SHARD}_{i:07d}",
            "category": "08_creative_knowledge",
            "subcategory": "arts",
            "type": "document",
            "source": {"name": "wikimedia/wikipedia", "url": data["url"][i], "license": "CC-BY-SA-3.0"},
            "messages": [
                {"role": "user", "content": f"Explain: {title}"},
                {"role": "assistant", "content": text[:3000]}
            ],
            "language": "en",
            "difficulty": 2,
            "tags": ["wikipedia", "creative", "arts"],
            "quality_score": 7,
            "verified": False,
            "notes": ""
        })

output = f"raw/generated/wiki_cre_shard{SHARD}_atlas.jsonl"
with open(output, "w") as f:
    for rec in atlas:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

print(f"Creative articles: {len(atlas)} -> {output}")
