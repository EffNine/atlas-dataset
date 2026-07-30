# Atlas Intelligence Layer v1.1 — Production Classification (2026-07-31)

This directory archives the exact one-off worker scripts used for the
Atlas Intelligence Layer v1.1 production classification run.

## Run Summary

| Pipeline | Sources | Records | Wall Time | Result |
|----------|---------|---------|-----------|--------|
| Tulu3-A  | tulu3_shard0..2 | 469,672 | 92.0 min | exit 0 |
| Tulu3-B  | tulu3_shard3..5 | 469,671 | 45.7 min | exit 0 |
| Rest     | openwebmath, arxiv, c4 | 1,636,279 | 111.2 min | exit 0 |
| **Total** | **4 sources** | **2,575,622** | **~2h (parallel)** | **exit 0** |

## Strategy

The production run used **3 parallel background processes** instead of one
sequential pipeline:

- **Tulu3-A** (`_run_tulu3_a.py`) — largest source (940k records, 6 shards),
  split across two workers to halve wall time. Handled shards 0-2.
- **Tulu3-B** (`_run_tulu3_b.py`) — handled shards 3-5.
- **Rest** (`_run_rest.py`) — OpenWebMath (114 small shards, fast per-shard),
  then ArXiv (3 shards), then C4 (12 medium shards).

Each script writes to a separate temp file under `metadata/intelligence/_tmp/`.
An offline merge step concatenated the temp files and generated the two
report JSON files.

## Archived Scripts

| Script | Purpose |
|--------|---------|
| `_run_tulu3.py` | Sequential 6-shard worker (superseded by split) |
| `_run_tulu3_a.py` | Parallel worker for shards 0-2 |
| `_run_tulu3_b.py` | Parallel worker for shards 3-5 |
| `_run_rest.py` | Sequential OWM+ArXiv+C4 worker |
| `_run_c4.py` | C4-only worker (not used; Rest handled C4) |
| `batch_classify_v1_1.py` | Original single-threaded classifier |
| `parallel_classify.py` | Parallel coordinator (not used; simpler per-source scripts used instead) |

## Output Files

```
metadata/intelligence/
├── unknown_classified_v1.1.jsonl      (1.4 GB, 2,575,622 records)
├── difficulty_distribution_v1.1.json  (report)
└── classification_summary_v1.1.json   (report)
```
