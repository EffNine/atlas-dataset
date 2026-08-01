# Hugging Face Release Pipeline — Atlas Dataset

Production pipeline for publishing frozen Atlas releases to Hugging Face Hub.

- **Repo**: private (created on first upload)
- **Format**: per-category JSONL compressed with zstd (`*.jsonl.zst`)
- **Integrity**: SHA-256 per file (`metadata/checksums.sha256`), hash-chained release manifest
- **Token**: `HF_TOKEN` env var only — never hardcoded

---

## 1. How to create the repo

You do **not** create the repo manually. `upload_huggingface.py` creates it on
first upload when it does not exist:

```bash
export HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxx   # https://huggingface.co/settings/tokens

.venv-release/bin/python scripts/release/upload_huggingface.py \
    --repo-id EffNine/atlas-dataset \
    --release v1.0-RC1 \
    --private \
    --workers 4
```

- `--private` makes the repo private on creation.
- If the repo already exists, it is reused; `--private` only applies at
  creation time (a public repo stays public — the script warns).

### Creating the repo manually (optional)

If you prefer to create it yourself:

```bash
huggingface-cli repo create atlas-dataset --type dataset --private
# or with the newer CLI:
hf repos create atlas-dataset --type dataset --private
```

---

## 2. How to login / authenticate

The pipeline reads `HF_TOKEN` from the environment. It never reads a
hardcoded token and never prompts interactively.

```bash
# Option A — env var (used by the scripts)
export HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxx

# Option B — CLI login (cached for other tools, not used by the scripts)
hf auth login

# Verify
hf auth whoami          # should print your username
```

> ⚠️ `upload_huggingface.py` and `download_release.py` call `require_env("HF_TOKEN")`
> and **exit with an error** if it is missing.

---

## 3. Release workflow (end-to-end)

```bash
# 0. Setup (once)
python3.11 -m venv .venv-release
.venv-release/bin/pip install zstandard huggingface_hub

# 1. Compress JSONL shards → per-category JSONL.ZST
.venv-release/bin/python scripts/release/compress_release.py \
    --release v1.0-RC1 --workers 2

# 2. Generate checksums (after any file lands in the release dir)
.venv-release/bin/python scripts/release/generate_checksums.py --release v1.0-RC1

# 3. Verify the local release bundle
.venv-release/bin/python scripts/release/verify_release.py --release v1.0-RC1

# 4. Dry-run upload plan (no network)
.venv-release/bin/python scripts/release/upload_huggingface.py \
    --repo-id EffNine/atlas-dataset --release v1.0-RC1 --private --dry-run

# 5. Upload (resumable, parallel, verified; updates release_index.json)
export HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxx
.venv-release/bin/python scripts/release/upload_huggingface.py \
    --repo-id EffNine/atlas-dataset --release v1.0-RC1 --private --workers 4
```

Expected release layout (this repo):

```
releases/v1.0-RC1/
├── dataset/
│   ├── 01_foundation/          *.jsonl.zst shards
│   ├── 02_software_engineering/
│   ├── 03_system_engineering/
│   ├── 04_ai_machine_learning/
│   ├── 05_hardware_engineering/
│   ├── 06_science_engineering/
│   ├── 07_business_knowledge/
│   ├── 08_creative_knowledge/
│   └── 09_personal_assistant/
├── metadata/
│   ├── release.json            frozen manifest (hash-chained)
│   ├── statistics.json         per-category record counts
│   ├── provenance.json         source lineage
│   ├── checksums.sha256        SHA-256 of every file
│   └── compression_report.json compression summary
└── docs/
    ├── dataset_card.md
    └── release_notes.md
```

---

## 4. How to restore (download)

```bash
export HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxx

.venv-release/bin/python scripts/release/download_release.py \
    --repo-id EffNine/atlas-dataset \
    --release v1.0-RC1 \
    --output releases/restored/v1.0-RC1 \
    --verify
```

What it does:

1. `snapshot_download(..., allow_patterns=["releases/v1.0-RC1/*"])` pulls
   the release tree into `releases/restored/v1.0-RC1/`
2. Reads the downloaded `metadata/checksums.sha256`
3. Verifies every file's SHA-256 (and flags files missing from the checksum
   list)

Private repos require `HF_TOKEN`.

---

## 5. Versioning policy

- Releases are tagged `vX.Y` (minor) or `vX.Y-RCn` (release candidate).
- A release is **frozen** when its manifest is written with a hash chain:
  `release_id = sha256(previous_release_hash + content_hash)[:16]`.
- The Hub repo holds **all releases** under `releases/<version>/` — never
  overwrite a frozen release directory.
- Each upload is a separate Hub commit; checksums per release make any
  accidental modification detectable (`verify_release.py --release ...`).
- **Never mutate** `releases/<version>/` after upload. If a fix is needed,
  create a new version (v1.0-RC2, v1.0, ...) — do not edit a frozen release.

---

## 6. Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'zstandard'` | ran with system python | use `.venv-release/bin/python` |
| `ERROR: environment variable HF_TOKEN is not set` | token missing | `export HF_TOKEN=hf_...` |
| `ERROR: release root does not exist` | release dir missing | run `compress_release.py` first |
| `checksums.sha256` verification fails | file modified after checksums | regenerate checksums, find what changed |
| upload "skips everything" | files already on Hub with same size | intended resume behavior |
| repo is public despite `--private` | repo existed already | set visibility in Hub settings |
| `Verify failed: ... MISMATCH` | interrupted/corrupt upload | re-run upload; it re-uploads mismatched sizes |
| 429 / rate limit | too many parallel uploads | lower `--workers` to 1–2 |
| disk full during compress | 22GB raw + compressed output | use `--workers 1`, ensure free space ≥ source size |

### OOM / memory notes (this machine: 8 GB RAM)

- Compression is **streaming** (O(1) memory per worker), but zstd level 19 is
  CPU-hungry. Keep `--workers 2` for the 313-shard corpus.
- `verify_release.py` decompresses one file at a time — safe.
- Do not run compression and heavy dataset processing simultaneously.

---

## 7. Files in this pipeline

| Script | Purpose |
|---|---|
| `scripts/release/common.py` | shared helpers (sha256, zstd, env) |
| `scripts/release/compress_release.py` | JSONL → per-category JSONL.ZST, parallel, verified |
| `scripts/release/generate_checksums.py` | write/verify `checksums.sha256` |
| `scripts/release/upload_huggingface.py` | upload to Hub (resume/parallel/retry/verify) |
| `scripts/release/verify_release.py` | local integrity verification (structure, counts, hashes) |
| `scripts/release/download_release.py` | restore a release from Hub + verify |
| `scripts/release/update_release_index.py` | record Hub publication in `release_index.json` |

## 8. Safety rules

1. **Never** hardcode tokens. Use `HF_TOKEN`.
2. **Never** upload before an explicit human instruction.
3. **Never** modify `releases/<version>/` after freeze.
4. Always run `verify_release.py` before and after an upload.
5. `release_index.json` updates preserve chain hashes (`chain_hash`,
   `content_hash`, `previous_hash` are untouched).
