# Provenance Resolver — Phase 5E.4 Automated Provenance Help

## Purpose

The **provenance resolver** reduces manual human completion work for
`provenance_pending` records by automating the parts of CC-BY-SA-4.0
attribution that **don't** require a web search.

For each StackExchange (source `s5`) record in the review queue, the
resolver:

1. **Identifies** s5 records and extracts the question + answer content.
2. **Classifies** the modification type (`verbatim`, `condensed`,
   `rephrased`, or `unknown`) using content heuristics.
3. **Generates** a provenance suggestion with pre-filled fields:
   - `source_url`, `license`, `share_alike_notice`, `modifications`
   - An `attribution_text` template with `[PLACEHOLDER]` markers for
     fields the human must still supply (answer author, specific post URL).
4. **Reports** all suggestions in a markdown report or JSON array.
5. **Does NOT modify** any immutable dataset files (`curated/`,
   `review_queue/*.jsonl`, `metadata/source_registry.json`,
   `review/decisions/`).

---

## Files Created

| File | Purpose |
|------|---------|
| `scripts/provenance_resolver.py` | Main resolver module with classifier, data classes, and CLI |
| `tests/test_provenance_resolver.py` | 36+ unit + integration tests |
| `metadata/provenance_resolutions.json` | Human-resolved provenance metadata for specific records (question_url, answer_url, author, license) |
| `tmp/provenance_resolution_report.md` | Auto-generated report output (gitignored) |

**No existing files were modified.** The resolver and metadata file are new
tooling that does not touch curated data, review queues, or the source registry.

---

## CLI Usage

### Full run (defaults to `review_queue/pending_expansion.jsonl`)

```bash
# Run from the repository root
python scripts/provenance_resolver.py

# Or via the atlas CLI
python scripts/atlas.py resolve-provenance

# Specify custom input/output
python scripts/provenance_resolver.py \
    --input review_queue/pending_expansion.jsonl \
    --output docs/provenance_resolution_report.md
```

### Single record explain

```bash
python scripts/provenance_resolver.py --explain s5_02_software_engineering_programming_0029
```

### JSON output

```bash
python scripts/provenance_resolver.py --json > provenance_suggestions.json
```

---

## Modification Classification

The resolver classifies each record's answer text using heuristic rules:

| Label | When Applied | Example |
|-------|-------------|---------|
| **verbatim** | Well-formed technical sentence ≥15 words with capitalization and punctuation | *"A deadlock occurs when two or more threads are each waiting for a resource held by another..."* |
| **condensed** | Very short (≤30 words), list/bullet structure, or key-value format | *"Average: O(n log n). Worst: O(n²)."* |
| **rephrased** | Prose-length answer (≥60 chars) that reads like an adaptation | *"The CAP theorem states that a distributed data store can provide at most two of three guarantees..."* |
| **unknown** | Minimal content, no clear signal | *"It works fine."* |

If the original source text is available (via `source_text` parameter),
Jaccard word similarity is used instead of content heuristics:
- `≥0.95` → verbatim
- `≥0.75` → rephrased
- `≥0.30` → condensed
- `<0.30` → unknown

---

## Output Format

### Markdown Report (default)

The report is written to `tmp/provenance_resolution_report.md` by default.
It contains a summary table and per-record JSON blocks ready for human review.

```markdown
# Provenance Resolution Report

- **Records checked:** 45
- **StackExchange found:** 4
- **Suggestions made:** 4

| Record ID | Classification | Confidence | Needs URL | Needs Author |
|-----------|---------------|------------|-----------|--------------|
| s5_...0005 | condensed | 0.72 | YES | YES |
| s5_...0029 | verbatim | 0.65 | YES | YES |

### s5_02_software_engineering_programming_0029

```json
{
  "record_id": "s5_02_software_engineering_programming_0029",
  "source_id": "s5",
  "license": "CC-BY-SA-4.0",
  "attribution_text": "This content is derived from the answer by [ANSWER AUTHOR NAME] to \"What is the difference between TCP and UDP? ...\" on Stack Exchange ([SPECIFIC POST URL]), licensed under CC-BY-SA-4.0.",
  "share_alike_notice": "Distributed under the same license (CC-BY-SA-4.0).",
  "modifications": "Used verbatim from the original Stack Exchange post.",
  ...
}
```
```

### JSON Output

With `--json`, each suggestion is printed as a JSON array to stdout:

```bash
python scripts/provenance_resolver.py \
    --explain s5_02_software_engineering_programming_0029 --json
```

---

## Provenance Resolutions Metadata

The file `metadata/provenance_resolutions.json` stores human-resolved
provenance data for specific records.  Once a human identifies the exact
StackExchange post for a record, the metadata is recorded here so the
resolver can generate real attribution text automatically.

### Structure

```json
{
  "version": "0.1.0",
  "phase": "phase-5E4-provenance-resolution",
  "resolutions": {
    "s5_02_software_engineering_programming_0029": {
      "question_url": "https://stackoverflow.com/questions/5970383/...",
      "answer_url": "https://stackoverflow.com/a/5970545",
      "answer_author": "Heisenbug",
      "license": "CC-BY-SA-3.0",
      "title": "Difference between TCP and UDP?",
      "resolved_by": "human",
      "resolved_date": "2026-07-28"
    }
  }
}
```

### How Resolved vs Unresolved Records Behave

| Aspect | Unresolved (no entry in metadata file) | Resolved (entry present) |
|--------|----------------------------------------|--------------------------|
| `attribution_text` | Placeholder with `[ANSWER AUTHOR NAME]` and `[SPECIFIC POST URL]` | Real text with author, URL, and license |
| `needs_human_url` | `True` | `False` |
| `needs_human_author` | `True` | `False` |
| `question_url` / `answer_url` / `answer_author` | Empty strings | Populated from metadata |
| `license` | Default `CC-BY-SA-4.0` | Record-specific (e.g. `CC-BY-SA-3.0`) |
| `resolved` flag | `False` | `True` |

### Adding New Resolutions

When a human identifies the post for another s5 record, add an entry
to `metadata/provenance_resolutions.json` under the `resolutions` key
keyed by the record ID.  No code changes needed — the resolver picks
it up automatically on the next run.

---

## Human Workflow Integration

The resolver is designed to fit into the existing Phase 5E.4 workflow
documented in `governance/v0.2_phase5E4_s5_0029_human_workflow.md`:

1. **Run the resolver** → pre-fills attribution template, identifies
   records needing human action, and classifies modifications.
2. **Human reviews** each record's suggestion, performs the web search
   for the specific StackExchange post, and fills in the placeholder
   fields (`[ANSWER AUTHOR NAME]`, `[SPECIFIC POST URL]`).
3. **Human completes** the revision record by updating
   `review/revisions/v0.2/<record_id>.json` with the finalised data.
4. **Governance updates** `metadata/source_registry.json` if needed.

The resolver **replaces none of the human tasks** — it automates the
mechanical preparation so the human can focus on the web-search and
verification steps.

---

## Running Tests

```bash
# Using pytest
python -m pytest tests/test_provenance_resolver.py -v

# Standalone
python tests/test_provenance_resolver.py
```

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Heuristic-based classification** | No original source text is available for pending records during Phase 5E.4 — the specific post hasn't been identified yet. Content heuristics are the only viable approach. |
| **No modification to immutable files** | Following existing Atlas policy: `curated/`, `review_queue/`, `metadata/source_registry.json`, and `review/decisions/` are immutable and never modified by tooling. |
| **Stdlib-only dependencies** | Following existing Atlas convention (`atlas_constants.py`, `payload_resolver.py`). Only `json`, `re`, `pathlib`, `dataclasses`, `hashlib` are used. |
| **Report-only output** | A markdown report in `tmp/` is non-destructive and gitignored. Human reviewers read the report and make the actual changes to revision records. |
| **`[PLACEHOLDER]` markers in attribution_text** | Makes it impossible to accidentally submit incomplete provenance. The brackets force human attention on missing fields. |
