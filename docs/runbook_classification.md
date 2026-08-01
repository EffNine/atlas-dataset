# Atlas Classification Runbook — v1.2 Full-Source Classification

**Document**: docs/runbook_classification.md
**Owner**: Atlas Platform Team
**Last updated**: 2026-08-01
**Applies to**: `run_classify_all_v2.py` + `scripts/intelligence/batch_classify_v2.py`
**Target machine**: dev-pc (WSL2 Ubuntu-24.04, 16 CPUs, 30GB RAM, 8GB swap)

---

## 1. Purpose

This runbook lets a completely new operator run, resume, verify, and
troubleshoot the Atlas v1.2 full-source classification pipeline **without
asking questions**. It is the single source of truth for operating the
classification workflow.

**Do NOT** use this document to:
- Modify dataset contents (`raw/`, `curated/`)
- Modify release manifests
- Run Hugging Face publishing operations
- Promote releases

---

## 2. End-to-End Workflow Overview

```
raw/generated/*_atlas.jsonl  (source shards)
        │
        ▼
scripts/intelligence/batch_classify_v2.py   (per-source classification)
        │  --groups <source> --shard-workers N
        ▼
metadata/intelligence/classified_<source>.jsonl  (per-source output)
        │
        ▼
run_classify_all_v2.py  append_source_to_v12()  (append + delete source file)
        │
        ▼
metadata/intelligence/unknown_classified_v1.2.jsonl  (unified v1.2 output)
        │
        ▼
merge_v11_into_v12()  (optional v1.1 merge at end)
        │
        ▼
classification_summary_v1.2.json  +  difficulty_distribution_v1.2.json
```

**Model**: sequential sources, parallel shards within each source.
- Stage 1 (7 wiki sources): 8 shard workers each
- Stage 2 (32 sources): 10 shard workers each
- Worker counts come from `config/parallelism.yaml` — never hardcoded.

---

## 3. Required Environment

### 3.1 Target machine (dev-pc)

| Item | Value |
|------|-------|
| OS | Ubuntu-24.04 (WSL2) |
| Repo path | `/mnt/d/atlas-dataset` |
| Python | `.venv-release/bin/python` (Python 3.11+, has pyyaml) |
| CPUs | 16 (WSL config: 16 processors) |
| RAM | 30GB (WSL config) |
| Swap | 8GB |
| GitHub auth | `gh` CLI v2.45.0, user `EffNine` |
| HF auth | `hf` CLI (` .venv-release/bin/hf`), user `EffNine` |

**WSL config check** (already applied — verify if unsure):
```bash
cat /mnt/c/Users/<user>/.wslconfig
# Expected: processors=16, memory=30GB, swap=8GB
```

### 3.2 Control machine (Mac)

- SSH alias `dev-pc` must resolve to the Windows host.
- Commands wrap WSL: `ssh dev-pc "wsl -d Ubuntu-24.04 bash -lc '...'"`
- No API tokens are passed over SSH — dev-pc has persistent gh/hf auth.
- Script transfer uses **base64** (never heredoc over SSH — quoting breaks).

```bash
# Transfer a local script to dev-pc safely:
python3 -c "from pathlib import Path; import base64; print(base64.b64encode(Path('LOCAL').read_bytes()).decode())" \
  | ssh dev-pc "wsl -d Ubuntu-24.04 bash -lc 'cd /mnt/d/atlas-dataset && base64 -d > REMOTE && python3 REMOTE'"
```

### 3.3 Repo requirements

- Repo must be at a known-good commit: `git fetch origin && git status`
- `config/parallelism.yaml` must exist (see §8).
- `.venv-release/bin/python` must have `yaml` installed:
  ```bash
  .venv-release/bin/python -c "import yaml; print('yaml ok')"
  ```

---

## 4. Initial Setup (first run on a fresh machine)

```bash
# 1. Clone / sync the repo (dev-pc)
ssh dev-pc "wsl -d Ubuntu-24.04 bash -lc 'cd /mnt/d && git clone https://github.com/EffNine/atlas-dataset.git && cd atlas-dataset && git checkout main && git pull'"

# 2. Create the release venv (if not present)
ssh dev-pc "wsl -d Ubuntu-24.04 bash -lc 'cd /mnt/d/atlas-dataset && python3 -m venv .venv-release && .venv-release/bin/pip install -q pyyaml'"

# 3. Verify config parses
ssh dev-pc "wsl -d Ubuntu-24.04 bash -lc 'cd /mnt/d/atlas-dataset && .venv-release/bin/python -c \"import yaml; print(yaml.safe_load(open(\"config/parallelism.yaml\")))\"'"

# 4. Verify raw shards are present (count per source)
ssh dev-pc "wsl -d Ubuntu-24.04 bash -lc 'cd /mnt/d/atlas-dataset && ls raw/generated/wiki_ai_shard*_atlas.jsonl | wc -l'"

# 5. Dry-run the batch classifier to confirm source discovery
ssh dev-pc "wsl -d Ubuntu-24.04 bash -lc 'cd /mnt/d/atlas-dataset && .venv-release/bin/python scripts/intelligence/batch_classify_v2.py --dry-run'"
```

**Expected**: dry-run lists all source groups (wiki_* + Stage 2), no errors.

---

## 5. Commands

### 5.1 Full run (all sources)

```bash
# On dev-pc (or via ssh from Mac):
ssh dev-pc "wsl -d Ubuntu-24.04 bash -lc 'cd /mnt/d/atlas-dataset && export PYTHONUNBUFFERED=1 && .venv-release/bin/python run_classify_all_v2.py 2>&1'"
```

- Stage 1: `wiki_ai wiki_sw wiki_sys wiki_sci wiki_biz wiki_cre wiki_hw`
- Stage 2: 32 sources (synthetic_pa, swebench, codealpaca, … tulu3_hardcoded)
- At the end: v1.1 merge + summary regeneration.

### 5.2 Run with `--skip` (resume after crash / partial run)

```bash
.venv-release/bin/python run_classify_all_v2.py --skip wiki_ai,wiki_sw,wiki_sys
```

- Skips sources already appended to v1.2.
- **Critical**: a source may only be skipped if its records are already
  in `unknown_classified_v1.2.jsonl` AND `classified_<source>.jsonl` was
  deleted by the append step. Verify with §7 before skipping.
- v1.1 sources are automatically skipped when `skip_v11_sources: true`.

### 5.3 Run a single source directly (debug / re-run)

```bash
.venv-release/bin/python scripts/intelligence/batch_classify_v2.py \
  --shard-workers 8 --print-interval 1 --groups wiki_sys
```

Output goes to `metadata/intelligence/classified_wiki_sys.jsonl`.
It will NOT be appended to v1.2 unless you run `run_classify_all_v2.py`
or call `append_source_to_v12('wiki_sys')` manually.

### 5.4 Background long run (recommended pattern)

```bash
# Via Hermes: terminal(background=true, notify_on_complete=true)
# Via shell:
nohup .venv-release/bin/python run_classify_all_v2.py > /mnt/d/atlas-dataset/logs/classify_v12.log 2>&1 &
```

---

## 6. Resume Workflow (Failure Recovery)

**Principle**: never lose already-classified work. The runner appends each
source's output to v1.2 immediately after the source completes, then deletes
the source file. So a crash only loses the **current in-flight source**, not
previous ones.

### 6.1 Steps after a crash

```bash
# 1. Check what is already in v1.2
wc -l /mnt/d/atlas-dataset/metadata/intelligence/unknown_classified_v1.2.jsonl

# 2. Check which per-source outputs still exist (NOT yet appended)
ls -la /mnt/d/atlas-dataset/metadata/intelligence/classified_*.jsonl 2>/dev/null

# 3. If a classified_<source>.jsonl exists but was NOT appended (crash before append):
#    Either rerun the runner (it will append it), or append manually:
ssh dev-pc "wsl -d Ubuntu-24.04 bash -lc 'cd /mnt/d/atlas-dataset && .venv-release/bin/python -c \"from pathlib import Path; import shutil, json; v12=Path(\"metadata/intelligence/unknown_classified_v1.2.jsonl\"); src=Path(\"metadata/intelligence/classified_wiki_sys.jsonl\"); n=0; 
with open(src) as i, open(v12,\"a\") as o:
    [o.write(l) for l in i if l.strip() and (n:=n+1)]
print(f\"appended {n} records\")\"'"

# 4. Compute the skip list from sources already in v1.2, then resume:
.venv-release/bin/python run_classify_all_v2.py --skip wiki_ai,wiki_sw,wiki_sys,wiki_biz
```

### 6.2 Determining the skip list (verification first!)

```bash
# List source prefixes present in v1.2:
python3 - <<'EOF'
import json
from collections import Counter
srcs = Counter()
with open("/mnt/d/atlas-dataset/metadata/intelligence/unknown_classified_v1.2.jsonl") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        rid = rec.get("record_id", "?")
        prefix = rid.split("_")[0] if "_" in rid else rid
        srcs[prefix] += 1
for k, v in sorted(srcs.items()):
    print(f"{k}: {v:,}")
EOF
```

**WARNING**: a prefix may map to multiple sources (e.g. `tulu3_*` family).
Cross-check with the actual source list in §8 before skipping.

---

## 7. Verification Steps (Expected Outputs)

### 7.1 During a run (live checks)

```bash
# Process is alive
ps aux | grep run_classify_all_v2 | grep -v grep

# Batch workers count (should be ~8 or ~10)
ps aux | grep batch_classify | grep -v grep | wc -l

# v1.2 line count grows monotonically
wc -l metadata/intelligence/unknown_classified_v1.2.jsonl

# Recent log tail (progress + per-source summary)
tail -40 logs/classify_v12.log   # or the SSH session output
```

### 7.2 After each source completes

The runner prints a per-source block:
```
  Per-source breakdown:
    wiki_biz: total=1059971, classified=1059971
      L1: 505164 ( 47.7%)
      ...
  [merge] Appended 1,059,971 records from wiki_biz into v1.2; removed classified_wiki_biz.jsonl
```

**Health checks**:
- `total == classified` (100% classification rate)
- `[merge] Appended N` matches the source total
- Source file is **deleted** after append (`classified_<source>.jsonl` gone)

### 7.3 Full-run verification

```bash
# 1. Line count vs expectation (~9.5M total for full run)
wc -l metadata/intelligence/unknown_classified_v1.2.jsonl

# 2. Summary JSON is valid and matches
python3 -m json.tool metadata/intelligence/classification_summary_v1.2.json | head -30

# 3. No zero-size or empty output
find metadata/intelligence -name "*.jsonl" -size 0

# 4. Duplicate check (record_id uniqueness)
python3 - <<'EOF'
import json
seen = set()
dups = 0
with open("/mnt/d/atlas-dataset/metadata/intelligence/unknown_classified_v1.2.jsonl") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        rid = json.loads(line).get("record_id")
        if rid in seen:
            dups += 1
        seen.add(rid)
print(f"duplicates: {dups}")
EOF
```

**Expected**: `duplicates: 0`.

---

## 8. Performance Expectations

### 8.1 Worker configuration (config/parallelism.yaml)

```yaml
parallelism:
  classification:
    stage1_shard_workers: 8
    stage2_shard_workers: 10
    skip_v11_sources: true
    print_interval: 1
  validation:
    file_workers: 8
    chunk_size: 1000
    per_file_timeout_seconds: 600
  acquisition:
    file_workers: 4
    chunk_size: 500
  extraction:
    shard_workers: 8
    shards_per_source: 41
  training_views:
    workers: 8
```

### 8.2 Source list

**Stage 1 (wiki family — 6.2M records):**
`wiki_ai` (40 shards), `wiki_sw` (10), `wiki_sys` (8), `wiki_sci` (16),
`wiki_biz` (13), `wiki_cre` (8), `wiki_hw` (9)

**Stage 2 (32 sources):**
`synthetic_pa`, `swebench`, `codealpaca`, `ultrafeedback`, `oasst1`,
`oasst1_val`, `sciq`, `gsm8k`, `mmlu`, `capybara`, `capybara_extra`,
`fin_alpaca`, `github_readmes`, `stackoverflow`, `gutenberg`, `batch_new`,
`personahub_math`, `personahub_code`, `personahub_ifdata`, `numinamath`,
`codealpaca_heval`, `no_robots`, `coconot`, `flan_v2`, `tulu3_wildchat`,
`tulu3_aya`, `tulu3_wildjailbreak`, `tulu3_openmath2`,
`tulu3_synthetic_finalresp`, `tulu3_sciriff`, `tulu3_tablegpt`,
`tulu3_hardcoded`

**Skipped automatically (v1.1 sources)**: `tulu3`, `openwebmath`, `arxiv_*`, `c4`.

### 8.3 Rates (observed on dev-pc)

| Config | Aggregate rate | Notes |
|--------|---------------|-------|
| 4 shard workers | ~430–500 rec/sec | earlier run |
| 8 shard workers (Stage 1) | ~600–700 rec/sec | ~8 cores utilized |
| 10 shard workers (Stage 2) | similar per-source, faster tail | 10 cores |

**Do not** expect 16-core utilization — sources run sequentially, shards in
parallel. Full 16-core utilization requires source-level parallelism (future
work, not enabled by default).

---

## 9. Disk Usage

| Path | Typical size | Notes |
|------|-------------|-------|
| `raw/generated/*_atlas.jsonl` | ~several GB | Source shards; immutable |
| `metadata/intelligence/_tmp/` | GB-scale transient | Per-source temp shards; cleaned per source |
| `metadata/intelligence/classified_<source>.jsonl` | source-sized | Deleted after append |
| `metadata/intelligence/unknown_classified_v1.2.jsonl` | ~1–3 GB (9.5M rows) | Final unified output |
| `metadata/intelligence/classification_summary_v1.2.json` | KB | Summary |
| `metadata/intelligence/difficulty_distribution_v1.2.json` | KB | Distribution |

**Monitor**:
```bash
du -sh metadata/intelligence/ metadata/intelligence/_tmp/ raw/generated/
df -h /mnt/d
```

**Threshold**: if `/mnt/d` free space < 20GB, pause the run and clean
(see §10) before continuing. Swap usage above ~6GB while running indicates
memory pressure — reduce `stage2_shard_workers` to 8 and retry.

---

## 10. Cleanup

### 10.1 Safe cleanup (always OK)

```bash
# Remove leftover temp dirs from crashed runs
ssh dev-pc "wsl -d Ubuntu-24.04 bash -lc 'cd /mnt/d/atlas-dataset && rm -rf metadata/intelligence/_tmp && mkdir -p metadata/intelligence/_tmp'"

# Remove per-source outputs that were already appended (verify first!)
# ls metadata/intelligence/classified_*.jsonl  # review
# rm metadata/intelligence/classified_<source>.jsonl  # only if appended
```

### 10.2 Dangerous cleanup (DO NOT without explicit sign-off)

- **Never** delete `unknown_classified_v1.2.jsonl` — it is the unified output.
- **Never** delete `raw/` shards — they are the source of truth.
- **Never** run `git clean -fdx` in the repo root — wipes untracked data.
- **Never** touch release manifests / bundles during a classification run.

---

## 11. Common Troubleshooting

### 11.1 `OSError: [Errno 39] Directory not empty` on _tmp

Cause: nested `_tmp/_tmp_shards` left by a crashed run.
Fix:
```bash
rm -rf metadata/intelligence/_tmp && mkdir -p metadata/intelligence/_tmp
```

### 11.2 Runner "skips" a source that has no v1.2 records

Cause: skip list includes a source whose append never completed (file was
deleted but records not appended, or crash between delete and append).
Fix: re-run without that source in `--skip`, or append its
`classified_<source>.jsonl` manually (§6.1), then re-verify with §7.

### 11.3 v1.2 contains duplicate record_ids

Cause: append ran twice (old runner without delete-on-append, or manual
append of an already-appended file).
Fix: deduplicate keeping first occurrence:
```bash
python3 - <<'EOF'
import json
from pathlib import Path
v12 = Path("metadata/intelligence/unknown_classified_v1.2.jsonl")
out = Path("metadata/intelligence/unknown_classified_v1.2.dedup.jsonl")
seen = set()
with open(v12) as i, open(out, "w") as o:
    for line in i:
        line = line.strip()
        if not line:
            continue
        rid = json.loads(line).get("record_id")
        if rid in seen:
            continue
        seen.add(rid)
        o.write(line + "\n")
print(f"kept {len(seen)} unique")
EOF
mv metadata/intelligence/unknown_classified_v1.2.dedup.jsonl metadata/intelligence/unknown_classified_v1.2.jsonl
```

### 11.4 Low CPU utilization on a source

Cause: `--shard-workers` not applied (using old runner), or source has fewer
shards than workers.
Fix: use the current runner (`run_classify_all_v2.py`), confirm
`config/parallelism.yaml` values, and check `ps aux | grep batch_classify | wc -l`.

### 11.5 `ModuleNotFoundError: yaml`

Fix:
```bash
.venv-release/bin/pip install pyyaml
```

### 11.6 SSH quoting failures when transferring scripts

Fix: always use the base64 pattern (§3.2). Avoid nested `$(...)`, `awk`,
`grep -E` inside `bash -lc '...'`.

### 11.7 Run exits nonzero on one source

The runner calls `sys.exit(rc)` on failure — **later sources are NOT run**.
Fix: find the failing source in logs, fix the root cause, resume with
`--skip <all completed sources>`.

---

## 12. Best Practices

1. **Always verify before skipping** — §7 checks, never guess the skip list.
2. **Report only on milestones** — real completion, failure, or concrete
   progress; don't poll every minute.
3. **Never hand-edit `config/parallelism.yaml`** without a commit; it is the
   single source of truth for worker counts.
4. **Commit runner/config changes separately** per feature/version.
5. **Keep partial output** on crash — fix the tool first, keep the current
   partial output, continue from the next source. Never rebuild from scratch.
6. **Use `.venv-release/bin/python`** everywhere — the system python may lack
   deps.
7. **Log long runs to a file** (`logs/classify_v12.log`) so the SSH session
   can drop without killing the job.
8. **Backup before destructive cleanup** — `cp` a file before dedup/delete.
9. **Respect resource headroom** — dev-pc is dedicated; do not run concurrent
   Windows workloads during classification/model training.
10. **After a crash**, the order is always: inspect → verify → fix tool →
    resume with skip list → verify again.

---

## 13. Quick Reference (cheat sheet)

```bash
# Run all
.venv-release/bin/python run_classify_all_v2.py

# Resume from wiki_sci (wiki_ai, wiki_sw, wiki_sys, wiki_biz done)
.venv-release/bin/python run_classify_all_v2.py --skip wiki_ai,wiki_sw,wiki_sys,wiki_biz

# Single source debug
.venv-release/bin/python scripts/intelligence/batch_classify_v2.py --shard-workers 8 --groups wiki_sys

# Dry run
.venv-release/bin/python scripts/intelligence/batch_classify_v2.py --dry-run

# Progress
wc -l metadata/intelligence/unknown_classified_v1.2.jsonl
ps aux | grep -c "[b]atch_classify"

# Clean temp
rm -rf metadata/intelligence/_tmp && mkdir -p metadata/intelligence/_tmp
```

---

## 14. Change History

| Date | Change | Author |
|------|--------|--------|
| 2026-08-01 | Initial runbook for v1.2 classification (append-per-source, --skip, unified config) | Hermes |
