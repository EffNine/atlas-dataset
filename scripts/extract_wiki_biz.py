#!/usr/bin/env python3
"""Extract Wikipedia business articles for 07_business_knowledge."""
import json, pyarrow.parquet as pq, sys
from huggingface_hub import hf_hub_download

BIZ_KW = [
    "business", "finance", "economy", "economic", "market", "marketing",
    "management", "accounting", "investment", "banking", "trade",
    "commerce", "entrepreneurship", "startup", "corporation",
    "company", "industry", "manufacturing", "supply chain",
    "sales", "revenue", "profit", "stock", "shareholder",
    "merger", "acquisition", "fund", "venture capital", "equity",
    "real estate", "insurance", "audit", "tax", "budget",
    "strategy", "leadership", "organization", "operations",
    "logistics", "retail", "wholesale", "franchise", "licensing",
    "brand", "advertising", "public relation", "consumer",
    "import", "export", "globalization", "monopoly", "competition",
    "pricing", "distribution", "production", "productivity",
    "stakeholder", "supplier", "procurement", "outsourcing",
    "scalability", "business model", "revenue stream",
    "cost analysis", "break even", "return on investment",
    "capital", "liability", "asset", "depreciation", "amortization",
    "dividend", "bond", "securities", "loan", "credit",
    "mortgage", "interest rate", "inflation", "deflation",
    "gdp", "gnp", "fiscal policy", "monetary policy",
    "central bank", "treasury", "subsidy", "tariff", "quota",
    "joint venture", "partnership", "sole proprietorship",
    "cryptocurrency", "blockchain", "fintech", "payments",
    "wealth management", "portfolio", "diversification",
    "hedging", "option", "futures", "commodity", "index fund"
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

KW_SET = set(kw.lower() for kw in BIZ_KW)

def is_biz(title, text):
    t = title.lower()
    content = text.lower()[:3000]
    return any(kw in t or kw in content for kw in KW_SET)

atlas = []
for i in range(total):
    title = data["title"][i]
    text = data["text"][i]
    if not title or not text:
        continue
    if is_biz(title, text):
        atlas.append({
            "id": f"wiki_biz_{SHARD}_{i:07d}",
            "category": "07_business_knowledge",
            "subcategory": "general-business",
            "type": "document",
            "source": {"name": "wikimedia/wikipedia", "url": data["url"][i], "license": "CC-BY-SA-3.0"},
            "messages": [
                {"role": "user", "content": f"Explain: {title}"},
                {"role": "assistant", "content": text[:3000]}
            ],
            "language": "en",
            "difficulty": 2,
            "tags": ["wikipedia", "business"],
            "quality_score": 7,
            "verified": False,
            "notes": ""
        })

output = f"raw/generated/wiki_biz_shard{SHARD}_atlas.jsonl"
with open(output, "w") as f:
    for rec in atlas:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

print(f"Business articles: {len(atlas)} -> {output}")
