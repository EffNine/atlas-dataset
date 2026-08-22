# EffNine Benchmark Task Bank

Task IDs use category prefixes matching the capability taxonomy:

- `EB-ARCH-NNN` — Architecture
- `EB-DEBUG-NNN` — Debugging
- `EB-CODE-NNN` — Coding
- `EB-UNDERSTAND-NNN` — Understanding
- `EB-PLAN-NNN` — Planning
- `EB-TEST-NNN` — Testing
- `EB-ADVISORY-NNN` — Advisory
- `EB-JUDGMENT-NNN` — Judgment
- `EB-EVIDENCE-NNN` — Evidence
- `EB-MYENG-NNN` — MY Engineering
- `EB-AGENT-NNN` — Agentic
- `EB-LONG-NNN` — Long Horizon

## Task Organization

Tasks are organized by **capability category**, not by execution mode.
Each task carries a `mode` field indicating its execution mode:

```json
{
  "id": "EB-ARCH-001",
  "category": "architecture",
  "mode": "SINGLE",
  "difficulty": "L4",
  "capabilities": ["ARCH", "PLAN"],
  ...
}
```

Execution modes:

| Mode | Description |
|------|-------------|
| SINGLE | Standalone reasoning / architecture / advisory / judgment tasks |
| MULTI  | Multi-turn tasks with changing context or requirements |
| EXEC   | Model works inside a repository/environment (Docker sandbox) |
| LONG   | Long-horizon engineering scenarios with multiple stages |

## Partitions

| Partition | Description |
|-----------|-------------|
| development | Visible to developers, may be used for calibration |
| validation  | Internal quality check, not for public release |
| private     | Calibrated but not yet approved for public use |
| hidden      | Secret eval set, never mixed with training data |

## Long Horizon Tasks

LONG tasks may have a structured directory layout:

```
tasks/long_horizon/EB-LONG-001/
├── task.json       # Task definition
├── stages.json     # Stage-by-stage requirements
├── fixtures/       # Repository/environment fixtures
└── expected/       # Expected outputs per stage
```

## Isolation Rule

Benchmark tasks must remain separate from Atlas training data.
Hidden and private partitions are never included in training datasets.
