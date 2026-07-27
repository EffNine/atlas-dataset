# Payload Resolver Architecture

> Phase 4B.5.10 — Canonical Payload Resolution Layer
> July 2026

---

## 1. Design Goals

1. **Deterministic lookup** — Every workflow resolves a record payload through
   the same priority chain. The result depends only on the record ID and the
   on-disk artifact state, not on which module performs the lookup.

2. **Stop-at-first-match** — The search halts immediately at the first priority
   layer that contains the record, guaranteeing O(N) worst-case where N is the
   number of files checked *before* the hit (not the total dataset size).

3. **Isolation from storage layout** — No workflow should know whether a
   payload lives in a review queue file, a compressed knowledge pack, or an
   archived version directory. Every caller uses `resolve(id)` and receives a
   uniform result dict.

4. **Transparent debugging** — The `--explain` mode traces every file checked,
   the reason for each miss, and the exact match point, enabling rapid diagnosis
   of resolution failures.

5. **Zero side effects** — The resolver is strictly read-only. It never
   modifies datasets, review artifacts, releases, or metadata.

---

## 2. Lookup Priority Order

```
Priority   Layer                     ID field      Examples
─────────────────────────────────────────────────────────────────
1          review_cache              id            review_queue/pending.jsonl
                                                  review_queue/pending_expansion.jsonl
                                                  review_queue/approved.jsonl
                                                  review_queue/rejected.jsonl
                                                  review_queue/needs_revision.jsonl

2          review_input_artifact     record_id     review/v0.2/batch_001_input.jsonl
                                                  review/quality_reviews.jsonl

3          decision_artifact         record_id     review/decisions/batch_001.jsonl
                                                  review/decisions/v0.2/batch_001.jsonl
                                                  review/decisions/v0.2/batch_002.jsonl

4          curated_dataset           id            curated/v0.2/data/v0.2_full.jsonl
                                                  curated/v0.2/data/phase4b_expansion.jsonl

5          knowledge_pack            id            knowledge_packs/foundation-pack.jsonl.gz
                                                  (gzipped JSONL, scanned line-by-line)

6          archived_dataset          id            curated/v0.1/atlas_synthetic_test_v0.1.jsonl
                                                  curated/v0.1/pilot_candidates.jsonl
                                                  curated/v0.1/data/*.jsonl
```

### Search rule

For each layer in priority order:

1. Enumerate all JSONL files matching that layer's file glob.
2. Read each file line by line (decompressing gzip on the fly for layer 5).
3. For each line, parse JSON and compare the configured ID field against the
   target `record_id`.
4. **First match wins** — return immediately with payload, source layer,
   source file, and SHA-256 checksum.
5. If no file in the layer matches, proceed to the next priority.

If all six layers are exhausted without a match, return `NOT_FOUND`.

---

## 3. Result Shape

### Successful resolve

```json
{
  "found": true,
  "payload": { ... full record ... },
  "source_layer": "review_cache",
  "source_file": "/path/to/review_queue/pending.jsonl",
  "checksum": "sha256-of-payload"
}
```

### NOT_FOUND

```json
{
  "found": false,
  "payload": null,
  "source_layer": null,
  "source_file": null,
  "checksum": null
}
```

### Explain result

Extends the resolve result with `lookup_log`:

```json
{
  "record_id": "01_foundation_communication_t0048",
  "found": true,
  "source_layer": "knowledge_pack",
  "source_file": ".../foundation-pack.jsonl.gz",
  "checksum": "dcfabd8df5d95...",
  "payload": { ... },
  "lookup_log": [
    { "priority": 1, "source_layer": "review_cache",
      "source_file": ".../pending.jsonl", "found": false,
      "reason": "record not found in file" },
    ...
    { "priority": 5, "source_layer": "knowledge_pack",
      "source_file": ".../foundation-pack.jsonl.gz",
      "found": true }
  ]
}
```

---

## 4. CLI Usage

### Resolve a record

```bash
python scripts/atlas.py payload --resolve b1_07_business_knowledge_finance_0009
```

Output (JSON):
```json
{
  "found": true,
  "source_layer": "review_cache",
  "source_file": "/.../review_queue/pending.jsonl",
  "checksum": "30c81c80419e00be9da141863bce89e07f0cc927ac4d37b687be98868c3556ec",
  "payload_keys": ["id", "category", "subcategory", ...]
}
```

### Explain (full trace)

```bash
python scripts/atlas.py payload --explain 01_foundation_general-reasoning_t0053
```

Output (human-readable trace):
```
============================================================
ATLAS PAYLOAD EXPLAIN  —  01_foundation_general-reasoning_t0053
============================================================
  [✗ MISS] P1 review_cache         .../pending.jsonl (record not found in file)
  [✗ MISS] P1 review_cache         .../pending_expansion.jsonl (record not found)
  ...
  [✓ FOUND] P6 archived_dataset    .../curated/v0.1/atlas_synthetic_test_v0.1.jsonl
------------------------------------------------------------
RESULT: FOUND   Source layer: archived_dataset   Checksum: ee32e42857...
============================================================
```

### Unknown ID

```bash
python scripts/atlas.py payload --resolve nonexistent_999999
```

```json
{ "found": false, "message": "Record 'nonexistent_999999' not found in any priority layer." }
```

### Library API

```python
from payload_resolver import PayloadResolver

pr = PayloadResolver("/path/to/atlas-dataset")
result = pr.resolve("b1_07_business_knowledge_finance_0009")
if result["found"]:
    print(result["source_layer"])   # "curated_dataset"
    print(result["checksum"])       # "sha256hex..."
    payload = result["payload"]     # dict

# Full explain with lookup log
explain = pr.explain("some_id")
for entry in explain["lookup_log"]:
    print(f"  P{entry['priority']} {entry['source_layer']}: {entry['found']}")
```

---

## 5. Performance Considerations

| Layer        | File type      | Typical lines | Decompression | Lookup cost       |
|--------------|----------------|---------------|---------------|-------------------|
| 1 – cache    | plain JSONL    | ~250          | none          | ~1ms (hit fast)   |
| 2 – input    | plain JSONL    | ~125          | none          | ~1ms              |
| 3 – decision | plain JSONL    | ~75           | none          | <1ms              |
| 4 – curated  | plain JSONL    | ~250–400      | none          | ~2ms              |
| 5 – pack     | gzip JSONL     | ~42           | gzip          | ~5–10ms           |
| 6 – archive  | plain JSONL    | ~200          | none          | ~2ms              |

**Worst case (NOT_FOUND)**: all 6 layers scanned: ~15–20ms.
**Best case (cache hit)**: single file scanned, ~1ms.

Memory: O(1) — files are streamed line-by-line, never loaded entirely into
memory. The gzip decompressor reads in streaming fashion.

---

## 6. Future Extension

### Pluggable priority layers

The `_search_layers` list is a simple Python data structure. New layers can be
added by appending a `(source_layer, id_key, file_list, extra_kwargs)` tuple.

### Caching

If resolve latency becomes a concern (e.g., called in a tight loop over
thousands of IDs), a simple `dict`-based in-memory cache can wrap the resolver
without changing its API:

```python
class CachingResolver:
    def __init__(self, resolver: PayloadResolver):
        self._inner = resolver
        self._cache: dict[str, dict] = {}

    def resolve(self, record_id: str) -> dict:
        if record_id not in self._cache:
            self._cache[record_id] = self._inner.resolve(record_id)
        return self._cache[record_id]
```

### Indexed lookup

For very large datasets (10⁶+ records), line-by-line scan becomes expensive.
A future version could maintain a Bloom-filter or SQLite index mapping
record_id → (source_layer, file, byte_offset) for O(1) lookup, falling back
to the linear scan for cache misses.

### Remote layers

The resolver currently operates on local files only. A `RemotePayloadResolver`
subclass could fetch from S3, HuggingFace Datasets, or an HTTP API while
preserving the same `resolve(id)` contract.

---

## 7. Failure Behavior

| Situation                              | Behavior                                            |
|----------------------------------------|-----------------------------------------------------|
| Missing file (deleted)                 | Silently skipped (no crash)                         |
| Corrupt JSONL line                     | Line skipped, next line tried                       |
| Corrupt gzip archive                   | File skipped, next file in layer tried              |
| Record not in any layer                | Return `found: false` with source_layer: null       |
| Duplicate record IDs within a file     | First match returned (file order)                   |
| File permissions error                 | File silently skipped                               |
| Empty file                             | File scanned, no match, next file tried             |
| Symlink loop                           | Avoided by using resolved paths (`Path.resolve()`)  |

The resolver never raises on data errors. It degrades gracefully by skipping
unreadable files and malformed lines. Callers should always check
`result["found"]` before accessing the payload.

---

## 8. Non-Goals (explicit)

The Payload Resolver does NOT:

- **Modify payloads** — read-only by design
- **Repair records** — no fix-up or migration logic
- **Modify datasets** — no writes to `curated/`, `review_queue/`, or
  `knowledge_packs/`
- **Modify review decisions** — no writes to `review/` or metadata
- **Release v0.2** — release gating is unaffected (still BLOCKED)
- **Validate payloads** — no schema enforcement; returns payload as-is
- **Merge records** — returns exactly one match, not a union of fields
- **Rewrite history** — preserves all existing artifact structure

---

## 9. Implementation

**Module**: `scripts/payload_resolver.py`
**Class**: `PayloadResolver(root: str | Path)`
**Dependencies**: Python 3.9+ standard library only (`json`, `hashlib`,
`gzip`, `pathlib`). No third-party packages.

The resolver is imported lazily from `scripts/atlas.py` to keep the main
CLI import chain light:

```python
from payload_resolver import PayloadResolver
pr = PayloadResolver(ATLAS_ROOT)
```

---

## 10. Validation Summary

| Test                              | Status | Notes                              |
|-----------------------------------|--------|------------------------------------|
| Record in review cache (P1)       | ✓ PASS | Found in `pending.jsonl`           |
| Record in review input (P2)       | ✓ PASS | Found in `batch_001_input.jsonl`   |
| Record in decisions (P3)          | ✓ PASS | Found in `batch_001.jsonl`         |
| Record in curated dataset (P4)    | ✓ PASS | Found in `v0.2_full.jsonl`         |
| Record in knowledge pack (P5)     | ✓ PASS | Found in `foundation-pack.jsonl.gz`|
| Record in archived dataset (P6)   | ✓ PASS | Found in `v0.1/atlas_synthetic_...`|
| Unknown ID                        | ✓ PASS | Returns `found: false`             |
| Deterministic (same ID, same hit) | ✓ PASS | Same ID → same source layer/file   |
| No duplicate payload              | ✓ PASS | First match only                   |
| No dataset modification           | ✓ PASS | No writes during resolve           |
| No review modification            | ✓ PASS | No writes during resolve           |
| Release remains BLOCKED           | ✓ PASS | Resolver is read-only; no release  |
