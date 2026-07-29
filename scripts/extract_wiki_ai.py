"""Extract Wikipedia AI/ML articles and convert to Atlas format."""
import json, pyarrow.parquet as pq
from huggingface_hub import hf_hub_download
import os, sys

AI_ML_KEYWORDS = [
    "machine learning", "artificial intelligence", "deep learning", "neural network",
    "natural language processing", "computer vision", "reinforcement learning",
    "supervised learning", "unsupervised learning", "transformer", "convolutional",
    "recurrent neural", "generative adversarial", "large language model", "llm",
    "nlp", "computer science", "data science", "artificial neural", "deep neural",
    "attention mechanism", "backpropagation", "gradient descent", "stochastic gradient",
    "support vector", "random forest", "decision tree", "k-means", "clustering",
    "dimensionality reduction", "principal component", "autoencoder", "variational",
    "bayesian network", "markov", "knowledge graph", "semantic web", "expert system",
    "recommender system", "collaborative filtering", "content-based filtering",
    "speech recognition", "image classification", "object detection", "image segmentation",
    "machine translation", "text generation", "sentiment analysis", "information retrieval"
]

def contains_ai_ml(title, text):
    title_lower = title.lower()
    text_lower = text.lower()
    for kw in AI_ML_KEYWORDS:
        if kw in title_lower or kw in text_lower[:5000]:  # Check first 5000 chars of text
            return True
    return False

SHARD = int(sys.argv[1]) if len(sys.argv) > 1 else 0

print(f"Downloading Wikipedia shard {SHARD}...")
path = hf_hub_download(
    repo_id="wikimedia/wikipedia",
    repo_type="dataset",
    filename=f"20231101.en/train-{SHARD:05d}-of-00041.parquet"
)

print(f"Reading parquet from {path}...")
t = pq.read_table(path)
data = t.to_pydict()
total = len(data["title"])
print(f"Total articles in shard {SHARD}: {total}")

atlas_records = []
for i in range(total):
    title = data["title"][i]
    text = data["text"][i]
    if not title or not text:
        continue
    if contains_ai_ml(title, text):
        # Truncate to first 3000 chars for assistant response
        content = text[:3000]
        atlas_records.append({
            "id": f"wiki_ai_{SHARD}_{i:07d}",
            "category": "04_ai_machine_learning",
            "subcategory": "general",
            "type": "document",
            "source": {"name": "wikimedia/wikipedia", "url": data["url"][i], "license": "CC-BY-SA-3.0"},
            "messages": [
                {"role": "user", "content": f"Explain: {title}"},
                {"role": "assistant", "content": content}
            ],
            "language": "en",
            "difficulty": 2,
            "tags": ["wikipedia", "ai", "ml"],
            "quality_score": 7,
            "verified": False,
            "notes": ""
        })

output = f"raw/generated/wiki_ai_shard{SHARD}_atlas.jsonl"
with open(output, "w") as f:
    for rec in atlas_records:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

print(f"AI/ML articles: {len(atlas_records)} -> {output}")
print(f"Done!")
