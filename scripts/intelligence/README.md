# Batch Classification — Atlas Intelligence Layer

This directory provides the reusable tools for running production
difficulty classification on Atlas source shards.

## Quick Start

```bash
# Run all sources for v1.1 (default)
python scripts/intelligence/batch_classify.py

# Run all sources for a new release
python scripts/intelligence/batch_classify.py --release v2.0

# Run specific sources only
python scripts/intelligence/batch_classify.py --sources tulu3 openwebmath
```

All output goes to `metadata/intelligence/` unless overridden.

## Files

| File | Purpose |
|------|---------|
| `batch_classify.py` | Reusable module — CLI runner + importable API |
| `difficulty_analyzer.py` | Core classification engine (unchanged) |
| `difficulty_taxonomy_v1.json` | Difficulty level definitions |
| `archive/production_v1_1/` | Exact v1.1 one-off worker scripts (preserved) |

## Architecture

```
                        ┌─────────────────────────┐
                        │  batch_classify.py       │
                        │                          │
                        │  ProductionClassifier    │
                        │     .run()               │
                        └──────┬──────────────────┘
                               │
              ┌────────────────┼───────────────┬───────────────┐
              ▼                ▼               ▼               ▼
        tulu3 shards    openwebmath shards   arxiv shards    c4 shards
              │                │               │               │
              ▼                ▼               ▼               ▼
        ┌─────────┐    ┌──────────────┐  ┌──────────┐   ┌──────────┐
        │_tmp/    │    │_tmp/         │  │_tmp/     │   │_tmp/     │
        │classified│    │classified    │  │classified│   │classified│
        │_tulu3   │    │_openwebmath  │  │_arxiv    │   │_c4       │
        │.jsonl   │    │.jsonl        │  │.jsonl    │   │.jsonl    │
        └────┬────┘    └──────┬───────┘  └─────┬────┘   └─────┬────┘
             └────────────────┼────────────────┼──────────────┘
                              ▼
                    ┌────────────────────┐
                    │ merge_and_report() │
                    └──────┬─────────────┘
                           ▼
              ┌──────────────────────────┐
              │ unknown_classified_{rel} │  .jsonl (merged)
              │ difficulty_distribution_{rel} │  .json
              │ classification_summary_{rel}  │  .json
              └──────────────────────────┘
```

## Reusing for Future Releases

### Python API (import)

```python
from scripts.intelligence.batch_classify import (
    ProductionClassifier,
    SourceConfig,
)

# Custom sources for a new release
sources = [
    SourceConfig("new_source", "raw/generated/new_source_shard*_atlas.jsonl"),
    # Add more ...
]

classifier = ProductionClassifier(
    root_path="/path/to/atlas-dataset",
    release="v2.0",
    classifier_version="2.0.0",
    data_snapshot="atlas-v2.0-RC1",
    sources=sources,
)
stats = classifier.run()
```

### Per-source classification (selective)

```python
from scripts.intelligence.batch_classify import classify_source_shards, merge_and_report

# Classify one source independently
stats = classify_source_shards(
    root_path=".",
    config=SourceConfig("new_source", "raw/generated/new_source_shard*_atlas.jsonl"),
    output_path="_tmp/classified_new_source.jsonl",
)

# Merge just the sources you classified
merge_and_report(
    [stats],
    output_dir="metadata/intelligence",
    temp_dir="_tmp",
    release="v2.0",
)
```

### Command line (parallel workers)

For parallel execution of independent sources (like the v1.1 run):

```bash
# Terminal 1: Classify source A
python -m scripts.intelligence.batch_classify \
    --sources tulu3 --release v2.0

# Terminal 2: Classify source B (runs concurrently)
python -m scripts.intelligence.batch_classify \
    --sources openwebmath --release v2.0
```

Then merge offline:

```python
from scripts.intelligence.batch_classify import merge_and_report
import json

# Collect results from the parallel runs
results = [
    {"label": "tulu3", "total": ..., "classified": ..., "errors": 0},
    {"label": "openwebmath", "total": ..., "classified": ..., "errors": 0},
]
merge_and_report(results, ..., temp_dir, release="v2.0")
```

## Configuration Reference

### `ProductionClassifier` arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `root_path` | (required) | Root of atlas-dataset repo |
| `release` | `"v1.1"` | Release tag → output filenames |
| `classifier_version` | `"1.1.0"` | Version in report metadata |
| `data_snapshot` | `"atlas-v1.0-RC1"` | Snapshot tag in report metadata |
| `sources` | all 4 sources | List of `SourceConfig` |
| `temp_dir` | `<root>/metadata/intelligence/_tmp` | Per-source temp files |
| `output_dir` | `<root>/metadata/intelligence/` | Final output files |
| `print_progress_interval` | 20 | Print progress every N shards (0 = off) |

### `SourceConfig` fields

| Field | Required | Description |
|-------|----------|-------------|
| `label` | yes | Short identifier (used in filenames) |
| `glob_pattern` | yes | Glob relative to root_path |
| `description` | no | Human-readable name (printed in logs) |

## Notes

- Each source writes to its own temp file → safe for parallel execution
- The module is importable — no `sys.path` hacks needed when running from the
  atlas-dataset repo root
- Archive scripts at `archive/production_v1_1/` preserve the exact v1.1 run
  for reproducibility
- Large shards (e.g. 1 GB Tulu-3 shards) load the entire file into memory
  via `process_file()` — monitor RAM on low-memory hosts
- On 8 GB RAM systems, run sources sequentially or split large sources across
  parallel workers (see v1.1 archive for the split pattern)
