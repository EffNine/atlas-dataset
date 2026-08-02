# Atlas Expert Definition v0.1

## Purpose

Freeze what “expert” means before sourcing or scoring expert data.
This definition is used by acquisition, filtering, difficulty scoring, and training-view generation.

## Tier Definitions

| Tier | Description | Examples |
|------|-------------|----------|
| E1 | Professional knowledge | Linux docs, engineering papers, API references, verified operational runbooks |
| E2 | Advanced reasoning | Hard coding problems, university math, debugging cases, system design questions |
| E3 | Frontier | Research papers, olympiad problems, novel solutions, experimental analysis |

## Intended Mix for 300M Specialist Training

| Tier | Target Share | Rationale |
|------|--------------|-----------|
| E1 | 60% | Stable professional signal; largest usable expert corpus |
| E2 | 30% | Reasoning muscle; hardest to collect at scale |
| E3 | 10% | Frontier signal; too sparse to dominate |

## Mapping to Atlas Intelligence Signals

- L4/L5 records are **candidate E2/E3 seeds**, but not all L4/L5 are frontier.
- E1 should include high-trust professional docs and verified Q&A regardless of difficulty label.
- E2/E3 should require stronger gates: verified answers, high-confidence classification, strong provenance.

## Usage Rules

- Do not equate “expert” with `difficulty >= 4`.
- Use expert tier together with domain, source quality, license, and verification state.
- Expert data must still pass the normal Atlas pipeline: license check -> quality filter -> difficulty scoring -> expert layer -> training dataset.
