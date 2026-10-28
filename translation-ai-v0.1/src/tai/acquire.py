"""Step 1 — Acquire real parallel data (read-only wrt existing projects).

Source: Helsinki-NLP/opus-100 (OPUS OpenSubtitles-derived, research use).
Configs: en-zh, en-ja, en-ko, en-ms. Direction flipped to xx->en.

Determinism: streaming read order is fixed for a pinned dataset revision;
we take the first N rows per language and record the revision + row offsets
in the manifest. No existing repo data is read or modified.

Usage:
    PYTHONPATH=src .venv/bin/python -m tai.acquire --out data/raw --seed 7
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

CAPS = {"zh": 60_000, "ja": 60_000, "ko": 40_000, "ms": 40_000}
CONFIGS = {"zh": "en-zh", "ja": "en-ja", "ko": "en-ko", "ms": "en-ms"}
DATASET = "Helsinki-NLP/opus-100"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/raw")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--cap-scale", type=float, default=1.0,
                    help="Multiply all per-language caps (smoke tests use 0.005).")
    args = ap.parse_args()

    from datasets import load_dataset
    from huggingface_hub import HfApi

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    revision = HfApi().dataset_info(DATASET).sha
    manifest = {
        "dataset": DATASET,
        "revision": revision,
        "seed": args.seed,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "license_note": ("OPUS/opus-100: sentences collected from open subtitles "
                         "and other open sources; mixed upstream licenses, used here "
                         "for local research/baseline training only. Not redistributed."),
        "direction": "xx->en",
        "languages": {},
    }

    for lang, cfg in CONFIGS.items():
        cap = max(100, int(CAPS[lang] * args.cap_scale))
        ds = load_dataset(DATASET, cfg, split="train", streaming=True)
        rows, n = [], 0
        for i, ex in enumerate(ds):
            if n >= cap:
                break
            tr = ex["translation"]
            # opus-100 config en-xx: keys are 'en' and xx code
            src = tr.get(lang) or tr.get({"zh": "zh", "ja": "ja", "ko": "ko", "ms": "ms"}[lang])
            tgt = tr.get("en")
            rows.append({
                "id": f"opus100-{cfg}-train-{i:07d}",
                "source_lang": lang,
                "source": src,
                "target_lang": "en",
                "target": tgt,
                "provenance": {
                    "dataset": DATASET,
                    "revision": revision,
                    "config": cfg,
                    "orig_split": "train",
                    "row_offset": i,
                },
            })
            n += 1
        with open(out / f"raw_{lang}-en.jsonl", "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        manifest["languages"][lang] = {"config": cfg, "rows": n, "cap": cap}
        print(f"{lang}-en: wrote {n} raw rows", flush=True)

    with open(out / "acquire_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print("manifest:", json.dumps(manifest["languages"], indent=2))


if __name__ == "__main__":
    main()
