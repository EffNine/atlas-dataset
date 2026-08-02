# Release Tools Audit — Universal Scheduler Phase 7A

**Date:** 2026-08-02
**Mode:** AUDIT ONLY — no code changes, no dataset changes, no release/HF operations
**Baseline:** `a1eb632` (main; working tree has 4 untracked pre-existing report files)
**Upstream:** Phase 5E final audit (`reports/parallelism/universal_scheduler_final_audit.md`)
→ recommended Phase 7 as "Release tools — exemption-by-design doc for network-domain
retry/resume (upload) instead of forcing TaskRegistry; dedup is embarrassingly
parallel per category: candidate for scheduler (file/category task) with registry
resume; download already uses unified config". This audit tests that hypothesis
against the full on-disk release pipeline.

---

## 1. Executive Summary

The Atlas release pipeline is a **toolchain of 12 standalone CLI scripts** under
`scripts/release/` plus a shared helper module (`common.py`). Only **two** of them
use `concurrent.futures` today:

| Tool | Executor | Task unit | Registry | Retry | Resume |
|------|----------|-----------|----------|-------|--------|
| `dedup_release.py` | `ProcessPoolExecutor` (`--jobs`, default 1) | category (9 max) | ❌ | ❌ | ❌ |
| `upload_huggingface.py` | `ThreadPoolExecutor` (`--workers`, default 4) | section (3 max) | ❌ | ✅ network backoff (3x) | ✅ remote-size skip |

`compress_release.py` was migrated in Phase 6B (scheduler primary + PPE fallback).
Everything else — `join_release.py`, `generate_checksums.py`, `verify_release.py`,
`build_release_metadata.py`, `promote_release.py`, `publish_promotion.py`,
`update_release_index.py`, `download_release.py`, `audit_duplicates.py` — is
**sequential by design** and most of that is the right call.

**Migration verdict (refines 5E):**

1. **`dedup_release.py` → Universal Scheduler** (Phase 7B candidate). Category-level
   tasks, `dedup:{release}:{cat}`, process pool, registry stage `dedup`, retry,
   resume, lease recovery. Its worker (`dedup_category`) is already module-level
   and picklable; outputs are disjoint per category; a retry rewrites only that
   category's file (`open_zstd_writer` uses `"wb"`) → no duplicate records. The
   manifest build (`compute_statistics` + `build_manifest`) stays in **serialized
   finalize** (5C pattern).
2. **`upload_huggingface.py` → documented exemption-by-design** (network domain).
   Its backoff retry + remote-size resume + post-verify map poorly onto the
   task registry (5E). Harden instead: verify **sha256**, not just size; wire
   `--workers` default to the unified config; keep one section commit each.
3. **`publish_promotion.py` → documented exemption + hardening**. Single-commit
   batch `CommitOperationCopy` has a proven silent-drop failure mode (see Phase 5
   promotion runbook); no destination-existence check → duplicate-publish risk.
   Both are integrity/governance fixes, not scheduler migrations.
4. **`join_release.py`, `promote_release.py`, `generate_checksums.py`,
   `verify_release.py`, `build_release_metadata.py`, `update_release_index.py`,
   `download_release.py`, `audit_duplicates.py` → keep sequential; documented
   rationale.** Join's cross-pass stub-index semantics make parallelization
   unsafe; checksums/verify are pure sequential functions with deterministic
   ordering; promote/index/metadata are governance single-writer writes;
   download's resume/retry is library-managed (`snapshot_download`).

**Blocking issues:** none for Phase 7B (dedup). Publish/upload hardening is
independent work — safe to do in the same implementation phase or separately.

---

## 2. Pipeline Inventory

### 2.1 Entry points

| Entry point | Type | Executor | Invoked by |
|-------------|------|----------|------------|
| `scripts/release/common.py` | shared helper | — | all release tools |
| `scripts/release/join_release.py` | CLI `main()` | none (sequential) | manual; `tests/test_join_release.py` (10 tests) |
| `scripts/release/audit_duplicates.py` | CLI `main()` | none (sequential) | manual (read-only analysis) |
| `scripts/release/dedup_release.py` | CLI `main()` | `ProcessPoolExecutor(--jobs)` | manual; produced v1.0-RC2; **no tests** |
| `scripts/release/compress_release.py` | CLI `main()` | **scheduler (6B)** + PPE fallback | manual per docs; `tests/test_release_pipeline.py` (4 compression tests); `tests/test_scheduler_compression.py` (19) |
| `scripts/release/generate_checksums.py` | CLI `main()` | none (sequential) | manual; `tests/test_release_pipeline.py` (2) |
| `scripts/release/verify_release.py` | CLI `main()` | none (sequential) | manual pre/post upload; `tests/test_release_pipeline.py` (2) |
| `scripts/release/build_release_metadata.py` | CLI `main()` | none (sequential) | manual; **no tests** |
| `scripts/release/promote_release.py` | CLI `main()` | none (sequential, `--dry-run`) | manual governance; **no tests** |
| `scripts/release/publish_promotion.py` | CLI `main()` | none (sequential, 1 commit) | manual; **no tests** |
| `scripts/release/upload_huggingface.py` | CLI `main()` | `ThreadPoolExecutor(--workers)` | manual; `tests/test_release_pipeline.py` (4) |
| `scripts/release/update_release_index.py` | CLI + library `update_index` | none (sequential) | manual; called by `upload_huggingface.py`; `tests/test_release_pipeline.py` (1) |
| `scripts/release/download_release.py` | CLI `main()` | none (sequential; HF `snapshot_download` internally parallel) | manual; `tests/test_release_pipeline.py` (1) |

Call-graph (grep-verified): **no production code invokes any release tool as a
subprocess or library** except `upload_huggingface.py → update_release_index.update_index`
(an internal import within `scripts/release/`). `e2e_pipeline.py`, `publish_agent.py`,
`automation_runner.py` use the **separate v1.8-era `scripts/release_builder/` package**
(no executors, no `concurrent.futures`) — a different, legacy bundle path, not the
v1.0 release pipeline; out of scope here but inventoried for completeness.

### 2.2 Release chain (how tools compose a release)

```
approved.jsonl + raw/generated shards + pilot/curated
  → join_release.py        → releases/<rel>/dataset/<cat>/<cat>.jsonl(.zst)   [sequential, 3 passes]
  → dedup_release.py       → releases/<rel>/dataset/<cat>/<cat>.jsonl.zst + signed manifest  [PPE per category]
  → generate_checksums.py  → releases/<rel>/metadata/checksums.sha256          [sequential, sorted]
  → verify_release.py      → local bundle verification (31 checks)             [sequential]
  → build_release_metadata.py → release.json/statistics.json/provenance.json/docs  [sequential]
  → promote_release.py     → NEW frozen manifest (RC→final), chain signed      [sequential, governance, dry-run]
  → publish_promotion.py   → HF server-side copy + metadata/docs upload        [sequential, 1 commit]
  → upload_huggingface.py  → full HF upload (create repo, resume, verify, index) [TPE per section]
  → update_release_index.py → metadata/release_index.json hub record           [sequential, chain-preserving]
  → download_release.py    → restore from HF + checksum verify                 [sequential; HF-managed parallel]
```

### 2.3 CLI surfaces (executor-bearing tools only)

**`dedup_release.py`:**
| Flag | Default | Meaning |
|------|---------|---------|
| `--source` | `v1.0-RC1` | source release dir name |
| `--target` | `v1.0-RC2` | target release dir name |
| `--root` | repo root | fixture override |
| `--manifest` | `<root>/metadata/releases/<target>_release.json` | output manifest |
| `--report` | `<root>/reports/releases/<target>_dedup_report.json` | output report |
| `--skip-sign` | False | stats only (testing) |
| `--expect-total` | 9515938 | expected kept total (validation gate) |
| `--expect-software` | 997144 | expected 02_software kept count (validation gate) |
| `--jobs` | **1** | parallel worker processes (one per category) |

**`upload_huggingface.py`:**
| Flag | Default | Meaning |
|------|---------|---------|
| `--repo-id` | (required) | HF repo id |
| `--release` | `v1.0-RC1` | release tag |
| `--private` | False | create repo private |
| `--workers` | 4 | parallel section uploads (TPE) |
| `--dry-run` | False | plan only, no network |
| `--commit-message` | `Atlas {release} release` | commit message template |
| `--output` | None | release root override |

### 2.4 Output artifacts

- `releases/<rel>/dataset/<cat>/<cat>.jsonl.zst` — dedup output (9 category files).
- `metadata/releases/<rel>_release.json` — signed manifest (immutable, chained).
- `reports/releases/<rel>_dedup_report.json` — per-category stats + validation.
- `releases/<rel>/metadata/checksums.sha256` — sorted sha256sum-format file.
- `releases/<rel>/metadata/release.json|statistics.json|provenance.json`,
  `releases/<rel>/docs/*.md` — bundle metadata.
- `metadata/release_index.json` — hub publication registry (chain hashes preserved).
- HF remote tree `releases/<rel>/{dataset,metadata,docs}` — published bytes.

---

## 3. Execution Model

### 3.1 Join (sequential by design)

`ReleaseJoiner` streams `approved.jsonl` in **pass 1** (writes full records inline,
indexes review stubs into `stub_meta`), then **pass 2** resolves stubs by scanning
`raw/generated/*_atlas.jsonl` (id match → `merge_record`), then **pass 3** resolves
the last ~250 stubs from pilot/curated dirs. Writers are per-category and shared;
`written_ids` is a global set for duplicate detection; validation compares
per-category totals against the frozen manifest. **Parallelization hazard:**
`stub_meta.pop(rid)` first-wins semantics + `written_ids` global dedup are
cross-pass shared state; pass 2/3 depend on pass 1's index. Any scheduler
migration would need the full 5C "pure workers + serialized finalize" pattern AND
a shared stub index — high complexity for a one-shot assembly step with a hard
manifest-count gate. **Keep sequential (documented).**

### 3.2 Dedup (the migration candidate)

`dedup_category(src, dst, cat_stats)` — module-level, takes `Path`s, streams the
source `.zst` (`open_zstd_reader`), keeps first occurrence per record ID, drops
subsequent occurrences **only when byte-identical** (SHA-256 of the raw line),
keeps and flags conflicting duplicates. Writes via `open_zstd_writer(dst)` → `"wb"`
overwrite. Returns stats via the passed mutable dict.

Executor: `ProcessPoolExecutor(max_workers=args.jobs)`, `dedup_category_worker(src,
dst)` (str args) submitted per category; results collected via `as_completed` then
per-category stats aggregated in submission order. `--jobs 1` (default) → sequential
loop. **No registry, no retry, no resume**: a crash mid-category leaves a partial
`.zst`; re-running re-dedups from source (idempotent because the output is
rewritten from scratch) but wastes the completed categories' work.

After dedup: `compute_statistics(dst_dataset)` re-reads ALL output (counts,
licenses, difficulty, quality, sources) and `build_manifest(...)` signs the new
manifest chained to the source release's `chain_hash`. Both must see the complete
category set → **serialized finalize**.

### 3.3 Checksums / verify (pure sequential)

`generate_checksums.py` walks the release root, **sorts** relative paths, streams
SHA-256 per file, never checksums the checksum file itself, writes sha256sum
format with a header. `verify_release.py` runs 31 checks: structure, zst
decompress+count per category, checksums all-match, stats consistency, release
metadata parse. Both are O(1)-memory, deterministic-ordered, and fast. No executor,
no retry — and none is needed.

### 3.4 Upload (network domain; exemption)

`upload_huggingface.py`:
1. Collects local files + plans sections (`dataset`, `metadata`, `docs`).
2. `--dry-run` prints plan (no token needed).
3. Ensures repo exists (`create_repo` when missing, `--private`).
4. **Resume**: `_remote_sizes()` via `list_repo_files` + `get_paths_info`;
   `_resume_skip()` keeps only files missing or size-mismatched on the Hub.
5. Uploads pending sections via `_upload_section_with_retry` (one
   `upload_folder` commit per section; retry 3x with 2s·2^(n-1) backoff).
   `ThreadPoolExecutor(max_workers=--workers)` over sections (max 3 concurrent).
6. `_verify_remote()`: checks every local file exists remotely; **compares size
   only** (remote sha256 is fetched but never compared to local).
7. `update_release_index.update_index(...)` records the hub publication.

**Gaps:** (a) verification is size-only — a same-size/corrupted remote blob passes;
(b) `--workers` default 4 is a hardcoded CLI default, not the unified config
(`release.upload_workers: 4` happens to match today but isn't wired);
(c) `get_paths_info` is fetched with all remote paths — fine for 15-100 files, but
no pagination guard.

### 3.5 Publish / promote (governance; exemption)

`promote_release.py` — pure governance: checks source manifest exists, destination
does NOT exist, source status is `release_candidate`/`final`, has `chain_hash`;
builds a NEW manifest with `status: "final"`, carries stats/sources/gates verbatim,
signs with `sha256-chain-v1`, verifies its own signature, refuses to write on
mismatch; `--dry-run` writes nothing. **No executor; correctly sequential.**

`publish_promotion.py` — HF server-side copy: enumerates remote source dataset
files, builds **one `create_commit` with ALL `CommitOperationCopy` ops + metadata
`CommitOperationAdd` ops**, commits, verifies presence by path. **Two real risks:**
1. **Silent-drop failure mode** — a batch of many `CommitOperationCopy` ops in one
   commit has been observed to silently drop copies (Phase 5 promotion runbook:
   "run one commit per file"). The committed script uses the batched form.
2. **No destination-existence pre-check** — re-running publish copies again
   (duplicate-publish risk; content is identical but creates redundant commits).

### 3.6 Download (library-managed; exemption)

`download_release.py` calls `huggingface_hub.snapshot_download(...,
allow_patterns=[releases/<rel>/*], max_workers=dl_workers)` with `dl_workers` from
`resolve_worker_count("acquisition")` (falls back 4 on "auto"), then verifies the
downloaded tree against its own `checksums.sha256`. Retry/resume are HF-library
managed (cache + local_dir). **Quirk:** it reads the `acquisition` stage config,
not `release.upload_workers`/a download key — cosmetic but worth fixing when
touched (or leave: acquisition.file_workers=4 is a sensible download default).

### 3.7 Merge / order guarantees

- **Checksums**: `sorted(p for p in release_root.rglob("*"))` — deterministic order.
- **Dedup report**: per-category stats aggregated in `CATEGORIES` iteration order in
  the sequential path; scheduler path must sort by task_id (`dedup:{rel}:{cat}`
  sorts alphabetically, which for category names == `CATEGORIES` order — verified
  on disk: `01_foundation` … `09_personal_assistant`).
- **Manifest stats**: `compute_statistics` iterates `CATEGORIES` — deterministic.
- **Manifest signing**: `json.dumps(sort_keys=True)` — deterministic content_hash
  regardless of dict insertion order (RC2 and v1.0 both verify).
- **zstd**: single-threaded frames at fixed level → byte-deterministic per file.

### 3.8 Retry / resume summary

| Tool | Retry | Resume | Notes |
|------|-------|--------|-------|
| join | ❌ | ❌ | hard exit 1 on validation failure (correct: gate) |
| dedup | ❌ | ❌ | re-run from source; wasted completed categories |
| compress | ✅ (6B) | ✅ registry + disk | migrated |
| checksums | ❌ | ❌ | pure; re-run cheap |
| verify | ❌ | ❌ | pure; re-run cheap |
| build_metadata | ❌ | ❌ | pure derivation from manifest |
| promote | ❌ | ✅ `--dry-run` gate | governance; must NOT auto-retry |
| publish | ❌ | ❌ | network; must NOT auto-retry blindly (duplicate risk) |
| upload | ✅ 3x backoff | ✅ remote-size skip | domain-specific; exemption |
| update_index | ❌ | ✅ idempotent (upsert by version) | single-writer |
| download | ✅ (HF-managed) | ✅ (HF-managed) | library-managed; exemption |

### 3.9 Resource usage

| Tool | CPU | RAM | Disk | Notes |
|------|-----|-----|------|-------|
| join | 1 core | O(1) streaming + stub index (1.5M stubs in memory) | writes ~22GB | stub_meta is the memory driver |
| dedup | `--jobs` (default 1) | O(1) streaming + per-category `seen` dict (~1M ids) | rewrites full output | 9 categories; worker count raw CLI |
| checksums | 1 core | O(1) | read-only walk | fast |
| verify | 1 core | O(1) | decompress-heavy | per-file sequential |
| upload | threads (network-bound) | O(files) | read-only | 3 sections; IO cap not used |
| publish | 1 core | O(ops) | read-only | HF-side copy |
| download | HF-managed | HF-managed | writes full tree | config read from `acquisition` |

---

## 4. Migration Boundary

### 4.1 What becomes a Scheduler task (Phase 7B: dedup)

- **One task per category**: `dedup:{release}:{cat}` (release embedded — the
  registry is repo-global; a bare `dedup:{cat}` would collide across releases,
  same lesson as compression F5).
- **Worker** `dedup_task(task)` — module-level, wraps `dedup_category` verbatim
  (same worker the old PPE dispatched → byte-identical output by construction),
  returns the per-category stats dict; **raises** on any error so the scheduler
  records a retry.
- **Retry**: `max_retries=2` (registry default); retry rewrites only that
  category's output (`"wb"` overwrite) → no duplicates possible.
- **Resume**: completed categories skipped via registry; stale `running`
  re-claimed after lease (900s default).
- **Pool**: `process` (CPU-bound zstd + hashing; pure worker → no SQLite fork
  hazard on macOS).
- **Workers**: `resolve_worker_count("release")` reads `release.upload_workers`
  (4) today — a new `release.dedup_workers` key (default 4) is the clean fix;
  `--jobs` stays as the explicit CLI override (CLI > env > config).

### 4.2 What must remain serialized

| Step | Tool | Why |
|------|------|-----|
| Pass 1/2/3 join | `join_release.py` | cross-pass stub index + global dedup + manifest-count gate |
| Statistics recompute | `dedup_release.py` finalize | needs ALL category outputs |
| Manifest build + signing | `dedup_release.py` finalize | single immutable artifact; content_hash over sorted keys |
| Report write + exit code | `dedup_release.py` finalize | deterministic aggregation |
| Checksums / verify | `generate_checksums.py`, `verify_release.py` | pure sequential, deterministic order, cheap |
| Promote | `promote_release.py` | governance single-writer; dry-run gate; never auto |
| Publish | `publish_promotion.py` | network governance; duplicate prevention |
| Index update | `update_release_index.py` | single-writer; preserves chain hashes |
| Metadata/docs | `build_release_metadata.py` | derivation from frozen manifest |
| Download | `download_release.py` | library-managed resume/retry |

### 4.3 What requires network-aware retry

- `upload_huggingface.py` — HAS it (3x backoff). Keep domain-specific.
- `download_release.py` — HAS it (HF library). Keep.
- `publish_promotion.py` — currently NO retry. If hardened, add an idempotent
  check (destination exists → skip) BEFORE retrying; a blind retry of a partially
  committed batch could duplicate commits. Prefer per-file commits (runbook
  pattern) so retry is naturally idempotent.

### 4.4 What requires human approval gates

- **Promote** (RC → final): already gated by `--dry-run` + operator discipline
  (skill: "Do NOT promote without explicit user sign-off"). Keep — never a
  scheduler task.
- **Publish / upload** (HF write): docs safety rule "Never upload before an
  explicit human instruction". Keep as manual CLI; registry must NOT auto-resume
  a publish/upload across runs without explicit invocation.
- **Dedup** (creates a new release candidate + signed manifest): release-relevant,
  but it creates NEW artifacts (RC2 from RC1) and never mutates frozen ones.
  Safe to automate; the signed manifest is the gate. Optional human approval at
  the RC level is out of tool scope (governance already records it).

---

## 5. Evaluation Against Universal Scheduler (`scripts/parallel/`)

| Module | Evaluation for release (dedup focus) | Verdict |
|--------|-------------------------------------|---------|
| `config.py` | `resolve_worker_count("release")` → 4 today (`upload_workers`; `compress_workers` added in 6B). Need `release.dedup_workers` key. Env override `ATLAS_WORKERS_RELEASE` works. | READY (small config addition) |
| `resource.py` | `safe_worker_limit()` fits CPU-bound zstd+hash dedup; per-task RAM default 512MB is generous for O(1) streaming + ~1M-id seen dict; `disk_free()` reporting-only (5E R1 — still not wired; dedup rewrites ~5GB output) | READY; note disk headroom |
| `models.py` | `Task` + `TaskResult` fit category tasks; `extra={"source_dataset":…, "target_dataset":…, "expect_total":…}` | READY |
| `registry.py` | `TaskRegistry(root, "dedup")` → `metadata/pipeline_state/task_registry_dedup.jsonl`; lease re-claim 900s; `attempts()` from append-only file | READY (stage naming decision D1) |
| `planner.py` | `file_tasks()` could build one task per category file, but the task id must be `dedup:{release}:{cat}` — plan inline (like compression's `plan_compress_tasks`) for exact id control | READY (custom planner, not `file_tasks`) |
| `scheduler.py` | `Scheduler.run()` — bounded submission, retry ≤ max_retries, resume-skip, deterministic result sort by task_id, in-run task_id dedupe; `pool="process"`; `_backpressure()` still dead code (out of scope, scheduler-wide) | READY |
| `monitor.py` | Optional `Monitor` writes `reports/performance/dedup_scheduler_report.json`; not required for correctness | OPTIONAL |

### Boundary review (5E step 4 re-check)

- `scripts/parallel/` canonical and stable (7 pipelines now incl. compression).
- Worker picklable: `dedup_task` + `dedup_category` module-level, Path→str args.
- Task_ids deterministic: `dedup:{release}:{cat}` (release-embedded; sorts by
  category == CATEGORIES order → matches report aggregation).
- Merges sorted: finalize consumes results sorted by task_id; stats/manifest
  built in `CATEGORIES` order (same as today's sequential path).
- Retries don't duplicate outputs: category file opened `"wb"` (overwrite) per
  task; disjoint per-task outputs → no duplicate records on retry.
- **Checksum correctness is unaffected**: dedup migration does not touch
  `generate_checksums.py`; dedup's own per-category SHA-256 (in report) is
  informational.

---

## 6. Findings

| # | Finding | Severity | Impact |
|---|---------|----------|--------|
| F1 | Dedup has PPE but **no registry/retry/resume**; a crash mid-category loses the completed categories' work on re-run (rewrites from source) | Medium | Scheduler adoption (registry + lease + resume) closes this; per-category tasks make re-run incremental |
| F2 | Dedup worker count is raw CLI `--jobs` (default 1), no RAM/CPU caps; 9 categories → sequential by default on the real release | Medium | `release.dedup_workers` key + `resolve_worker_count("release")`; `--jobs` stays as override |
| F3 | Dedup manifest/statistics finalize MUST stay serialized after all category tasks (signed content_hash over complete stats) | High (design) | 5C "pure workers + serialized finalize"; finalize consumes sorted task results, builds stats + manifest exactly as today |
| F4 | **Upload verification is size-only**: remote sha256 fetched but never compared; same-size corrupted blob passes | Medium | Harden `_verify_remote` to compare local vs remote sha256 (LFS sha256 available via `get_paths_info` expand) |
| F5 | Upload `--workers` default 4 is hardcoded, not wired to `release.upload_workers` in unified config | Low | Wire default via `resolve_worker_count("release")` (value coincidentally 4 today) |
| F6 | **Publish uses one batch commit with many `CommitOperationCopy` ops — proven silent-drop mode** (Phase 5 runbook: "one commit per file") | High | Harden: one commit per file (runbook pattern), or verify each copied path post-commit; currently only presence-checked, not content-checked |
| F7 | Publish has **no destination-existence pre-check** → duplicate-publish risk on re-run | Medium | Check `dst in remote` before copy (mirror upload's resume skip); skip existing |
| F8 | Publish does not call `update_release_index` (v1.0 index entry exists — updated manually per promotion runbook, Step 5) | Low | Document; optionally auto-update after verified publish |
| F9 | Download reads `acquisition` worker config, not a release/download key | Low | Cosmetic; leave or add `release.download_workers` when touched |
| F10 | Join is sequential by design (cross-pass stub index, global dedup, manifest gate) — parallelizing is high-risk/low-value | Info | Keep sequential; document in design doc |
| F11 | Checksums/verify/build_metadata are pure sequential functions — no migration value | Info | Keep; documented exemption |
| F12 | Promote is correctly sequential + dry-run gated; must never become a scheduler task | Info | Keep; documented approval gate |
| F13 | No test coverage for `dedup_release.py`, `promote_release.py`, `publish_promotion.py`, `build_release_metadata.py` | Medium | Add `tests/test_scheduler_dedup.py` (planning/retry/resume/determinism) + smoke tests for promote/publish dry-run paths in 7B |

---

## 7. Decisions Needed Before Implementation

1. **Registry stage key**: `dedup` (→ `task_registry_dedup.jsonl`, isolates from
   compression `task_registry_compression.jsonl` and future upload) vs `release`
   (shared stage for all release tools). Recommendation: **`dedup`** — per-stage
   separation keeps each pipeline's state inspectable; task_ids carry operation
   prefix (`dedup:`, `compress:`) so a future shared `release` registry is still
   possible without breaking ids.
2. **Task unit**: category-level (9 tasks) — recommended. Per-file/shard-level is
   unnecessary: source is already one `.zst` per category; splitting inside a
   category would break the byte-identical dedup (`seen` dict spans the category).
3. **Worker config key**: add `release.dedup_workers: 4` to
   `config/parallelism.yaml` vs reuse `release.upload_workers`. Recommendation:
   **new key** `dedup_workers` — separate concern, clear logs, env override
   `ATLAS_WORKERS_RELEASE` still applies.
4. **Failure semantics**: worker raises on error (retryable, recommended — mirrors
   compression D4) vs hard exit-1 first-failure (today). Recommendation: **raise →
   retry**; terminal failure after `max_retries` exits 1 (same final semantics).
5. **Upload hardening scope**: fix `_verify_remote` sha256 comparison + wire
   `--workers` default (F4/F5) in the same phase as 7B, or defer to a later
   hardening phase. Recommendation: include — small, high-value, no scheduler
   dependency.
6. **Publish hardening scope**: per-file commit + destination pre-check (F6/F7).
   Recommendation: design as part of the same design doc but **implement only with
   explicit approval** (it touches HF write behavior; test in dry-run/list-only
   mode first).

---

## 8. Verification (this audit)

- Mode: read-only. No source/dataset/release/HF files modified.
- `git status` baseline: `a1eb632` clean except 4 untracked pre-existing reports
  (`compression_audit.{md,json}`, `universal_scheduler_final_audit.{md,json}` —
  untouched by this phase; they predate Phase 7A).
- On-disk probes run (fresh, temporary, cleaned up):
  - `resolve_worker_count("release")` → `4`; `release` stage cfg =
    `{'compress_workers': 4, 'upload_workers': 4}` (YAML now HAS a `release:`
    section — added in 6B; `compress_workers` pinned to 4).
  - Call graph greps: no production invoker of dedup/upload/publish/promote as
    subprocess; only tests + docs reference them.
  - `releases/` contains `v1.0-RC1`, `v1.0-RC2`, `restored/v1.0-RC1` — untouched.
  - `metadata/release_index.json` — v1.0-RC2 + v1.0 hub entries present; chain
    hashes intact.
  - Executor scan: `dedup_release.py` (PPE), `upload_huggingface.py` (TPE),
    `compress_release.py` (PPE fallback only — scheduler primary since 6B). No
    other `concurrent.futures` usage in `scripts/release/`.
- See `reports/parallelism/release_audit.json` for the machine-readable schema +
  probe evidence.

**STOP — awaiting design review approval before Phase 7B (implementation).**
