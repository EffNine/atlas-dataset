# Atlas Automated-Quality-Filter Prototype — `jev-quality-filter-v0.1`

**Experiment only. Not a gate. Not calibrated. Does not modify Atlas data.**

## Question

Can Atlas automatically keep high-quality records (JEV first pass) and spend a
second, independent AI review **only** on ambiguous cases?

## Pipeline

```
Atlas sample (reused JEV pilot 500 records; JEV NOT rerun)
  → deterministic validation (local, no AI)
  → JEV first-pass (REUSED stored results from jev-pilot-atlas-v0.1)
  → confidence classification (3 experimental band configs: A / B / C)
      ├── HIGH → ACCEPT (no AI-2)
      ├── LOW  → REJECT / QUARANTINE (no AI-2)
      └── AMBIGUOUS → AI-2 blind independent review → ACCEPT / REJECT / AMBIGUOUS
```

## What this directory contains

| file | purpose |
|------|---------|
| `ai2_reviewer.py` | Blind second reviewer: independent prompt, OpenAI-compatible transport over stdlib, strict JSON parsing, fail-safe (errors → `ERROR`, never accept) |
| `run_filter.py` | Pipeline: validate → reuse JEV → band (A/B/C) → AI-2 on union-ambiguous → results + summary |
| `ai2_results.jsonl` | One line per AI-2 call (resume-safe). AI-2 never saw JEV scores/decisions/reasoning |
| `filter_results.jsonl` | One line per record: ids, hashes, deterministic verdict, JEV signals, per-config band + final, AI-2 where invoked, latency/tokens |
| `config_summary.json` | Machine-readable per-config metrics |
| `REPORT.md` | Concise workflow evaluation (no accuracy claims) |

## Read-only inputs (never written)

- `../jev-pilot-atlas-v0.1/jev_results.jsonl` — reused JEV first-pass (no rerun)
- `../jev-pilot-atlas-v0.1/sample_content_index.json` — record text for validation + AI-2
- `../jev-pilot-atlas-v0.1/sample_manifest.json` — arm/category metadata

## Confidence bands — EXPERIMENTAL OPERATING THRESHOLDS ONLY

These bands are **not scientifically calibrated**. They were chosen by inspecting
JEV pilot score quantiles (correct p25≈0.58/p50≈0.78; quality p25≈2.19/p50≈2.79;
problematic p50≈0.15/p75≈0.26) to span a reasonable escalation range, so the
experiment can compare workflow operating points. Three configs are evaluated on
the SAME 500 records with the SAME single AI-2 verdict per escalated record.

- **HIGH (auto-ACCEPT):** `correct ≥ C_HI AND quality ≥ Q_HI AND problematic ≤ P_LO`
- **LOW (auto-REJECT/quarantine):** `correct ≤ C_LO OR quality ≤ Q_LO OR problematic ≥ P_HI`
- else **AMBIGUOUS** → AI-2.

| config | C_HI | Q_HI | P_LO | C_LO | Q_LO | P_HI | intent |
|--------|------|------|------|------|------|------|--------|
| A-balanced | 0.85 | 3.0 | 0.15 | 0.35 | 1.8 | 0.50 | middle operating point |
| B-strict-accept | 0.90 | 3.2 | 0.10 | 0.50 | 2.0 | 0.40 | hard to auto-accept, easy to quarantine |
| C-lenient-accept | 0.75 | 2.5 | 0.25 | 0.25 | 1.2 | 0.65 | easy to auto-accept, hard to quarantine |

## Final-decision rule

- Deterministic INVALID → `REJECT` (reason `deterministic_gate`), no AI involved.
- JEV HIGH → `ACCEPT`; JEV LOW → `REJECT` (+ `quarantine=true`).
- AMBIGUOUS → AI-2 verdict: `ACCEPT`→accept, `REJECT`→reject,
  `AMBIGUOUS`/`ERROR`→`AMBIGUOUS` (remains unresolved; routed to human review in
  any real deployment — **this prototype performs no human review**).

## Explicit non-goals / non-claims

- Phase-2 human labels are **never read** and are **not ground truth** here.
- No accuracy / precision / recall / "correctness" claims. `agreement` below is a
  *workflow* measure (AI-2 verdict vs a documented JEV-lean heuristic), not a
  quality judgment.
- AI-2 cost is reported as **tokens + latency**. No USD figures are invented;
  apply the operator's provider price card to the token counts.
- AI-2 verdicts are single-sample, temperature-0 generations — a second opinion,
  not an oracle.

## AI-2 independence

AI-2 receives: the record's user/assistant text + claimed category/subcategory
(record metadata, not JEV output). It never receives JEV scores, bands,
decisions, or reasoning. Its prompt, rubric, and model family
(`agnes-2.5-flash` via OpenAI-compatible API) differ from JEV (`jev-1.13.0`).

## Reproduce

```bash
.venv/bin/python experiments/jev-quality-filter-v0.1/run_filter.py bands   # no network: bands only
.venv/bin/python experiments/jev-quality-filter-v0.1/run_filter.py run [--limit N]  # AI-2 on union-ambiguous
.venv/bin/python experiments/jev-quality-filter-v0.1/run_filter.py report  # rebuild results + summary
```
