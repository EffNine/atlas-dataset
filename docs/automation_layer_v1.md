# Atlas Automation Layer v1

> **Transform Atlas from manual workflow into an automated pipeline with human approval before release.**

---

## Architecture Overview

```
                    ┌─────────────────────────────────────────────┐
                    │            Pipeline Orchestrator             │
                    │  (scripts/automation/pipeline_orchestrator)  │
                    └────────────────────┬────────────────────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    │                    │                    │
                    ▼                    ▼                    ▼
         ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
         │   State Machine   │  │  Approval Gate    │  │     Agents       │
         │   (FSM)           │  │  (Human Gate)     │  │  (Executors)    │
         └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘
                  │                      │                     │
                  ▼                      ▼                     ▼
         ┌──────────────────────────────────────────────────────────┐
         │              Persistence Layer (metadata/)               │
         │    pipeline_state/<id>.json    pipeline_approvals.json   │
         └──────────────────────────────────────────────────────────┘
```

---

## Pipeline States

The pipeline progresses through exactly 7 states in strict forward order:

```
INGESTED ──→ QUALITY_CHECK ──→ PROVENANCE_CHECK ──→ CONTENT_REVISION
    ──→ VALIDATION ──→ WAITING_HUMAN_APPROVAL ──→ RELEASED
```

| State | Description |
|---|---|
| `INGESTED` | Raw data has been ingested into the pipeline. Starting state. |
| `QUALITY_CHECK` | Automated quality scoring is complete. Scores validated. |
| `PROVENANCE_CHECK` | Source provenance has been resolved for all records. |
| `CONTENT_REVISION` | Content revision review is complete. Flagged items addressed. |
| `VALIDATION` | Final structural validation passed (schemas, JSONL, license gate). |
| `WAITING_HUMAN_APPROVAL` | All automated checks passed. Awaiting human sign-off. |
| `RELEASED` | Dataset officially released. Terminal state. |

### State Machine Rules

1. **Forward-only**: Transitions are irreversible — no backward movement.
2. **Sequential**: States cannot be skipped (e.g. `INGESTED → VALIDATION` is invalid).
3. **Terminal**: `RELEASED` has no outgoing transitions.
4. **Human approval mandatory**: The orchestrator blocks `RELEASED` unless the approval gate grants sign-off.

---

## Components

### 1. State Machine (`state_machine.py`)

The FSM manages pipeline lifecycle with validation and persistence.

```
StateMachine(pipeline_id, root)
├── transition_to(target, triggered_by, reason, metadata) → bool
├── can_transition_to(target) → bool
├── is_terminal() → bool
├── is_blocked() → bool
├── is_after(state) / is_before(state) → bool
├── load() → bool          # Load persisted state from disk
├── reset()                # Reset to INGESTED
└── summary() → dict
```

**Persistence**: State is automatically saved to `metadata/pipeline_state/<pipeline_id>.json` on every transition. Loading a `StateMachine` with the same `pipeline_id` restores the previous state.

### 2. Approval Gate (`approval_gate.py`)

Controls human approval for release. Enforces the mandatory gate.

```
ApprovalGate(root)
├── create_request(pipeline_id, requested_by, role, artifacts) → ApprovalRequest
├── approve(pipeline_id, decided_by, role, comments) → bool
├── deny(pipeline_id, decided_by, role, comments) → bool
├── is_releasable(pipeline_id) → bool
├── get_request(pipeline_id) → ApprovalRequest | None
├── reject_or_rescind(pipeline_id) → bool
└── check_approval_gate(pipeline_id) → dict
```

**Persistence**: All approval decisions are saved to `metadata/pipeline_approvals.json`.

### 3. Base Agent Interface (`base_agent.py`)

Abstract interface that all pipeline agents implement.

```python
class BaseAgent(ABC):
    name: str = "base_agent"
    description: str = "Base agent — override in subclass."

    def __init__(self, root, config=None): ...
    @abstractmethod
    def execute(self, context=None) -> AgentResult: ...
    def validate_config(self) -> list[str]: ...
```

### 4. Agents

| Agent | Type | Description |
|---|---|---|
| `QualityAgent` | Placeholder | Validates quality scores exist and are in valid range (0-10). Reports summary statistics. |
| `ProvenanceAgent` | Adapter | Wraps the existing `ProvenanceResolver` via adapter pattern. No modifications to the original tool. |
| `RevisionAgent` | Placeholder | Scans for records flagged `needs_revision`. Reports verification status distribution. |
| `ValidationAgent` | Placeholder | Performs final structural validation (JSONL format, required fields, license gate). |

**Design constraint**: The provenance adapter wraps `provenance_resolver.py` without modifying it. All existing tools are preserved — new functionality is added through the adapter/agent pattern.

### 5. Pipeline Orchestrator (`pipeline_orchestrator.py`)

Coordinates the full pipeline run.

```
PipelineOrchestrator(pipeline_id, root, config)
├── run_full_pipeline() → PipelineResult   # Complete run INGESTED → RELEASED
├── run_to_approval() → PipelineResult     # Run up to WAITING_HUMAN_APPROVAL
├── request_human_approval(...) → dict     # Create approval request
├── approve_release(...) → dict            # Grant approval (auto-creates request)
├── deny_release(...) → dict               # Deny release
├── get_status() → dict                    # Current pipeline snapshot
└── reset_pipeline() → void                # Reset to initial state
```

---

## Human Approval Flow

The requirement that **human approval is mandatory before RELEASED** is enforced at two levels:

### 1. Orchestrator Level (Gate Check)

The orchestrator's `_advance_pipeline()` method checks `self.approval_gate.is_releasable()` before calling `state_machine.transition_to(RELEASED)`. Without a matching `ApprovalRequest` in `APPROVED` state, the transition is never called.

### 2. State Machine Level (Design)

The FSM design makes `WAITING_HUMAN_APPROVAL` a mandatory state before `RELEASED`. The transition `VALIDATION → RELEASED` is **not** a valid transition — the pipeline must pass through the human approval gate.

### Typical Release Flow

```python
# 1. Create the orchestrator
orch = PipelineOrchestrator("release-v0.3", ROOT)

# 2. Run automated checks
result = orch.run_to_approval()
assert result.status == PipelineStatus.BLOCKED_ON_APPROVAL

# 3. Human reviews and approves
orch.approve_release(
    decided_by="reviewer_alice",
    role=ApproverRole.REVIEWER,
    comments="All automated checks passed. Release approved."
)

# 4. Complete the release
result = orch.run_full_pipeline()
assert result.status == PipelineStatus.COMPLETED
```

---

## Design Decisions

### Why the Orchestrator Owns Both State Machine and Approval Gate?

Separation of concerns:
- **State Machine**: Pure FSM logic (states, transitions, persistence)
- **Approval Gate**: Human interaction tracking (requests, decisions, audit)
- **Orchestrator**: Workflow logic (sequence, gate enforcement, error recovery)

This allows the state machine to be tested independently of approval logic, and allows the approval gate to be used standalone for other purposes.

### Why an Adapter for Provenance (Not a Rewrite)?

The existing `ProvenanceResolver` (817 lines) is production code with tests, docs, and CLI integration. Wrapping it in an adapter:
- Preserves the original tool and its test coverage
- Adds zero regression risk
- Makes the adapter testable in isolation (injecting a mock resolver is straightforward)
- Follows the Open/Closed Principle (open to extension, closed to modification)

### Why Placeholder Agents for Quality/Revision/Validation?

v1 focuses on the **pipeline automation infrastructure** (state machine, gate, orchestrator, adapter pattern). The placeholder agents:
- Validate the pipeline flow end-to-end
- Provide ready integration points for future work
- Do real structural checks (score ranges, field presence, license gates)
- Can be swapped for full implementations without changing the orchestrator

---

## Migration Impact

### Files Created (7 files)

| File | Lines | Purpose |
|---|---|---|
| `scripts/automation/__init__.py` | 63 | Package exports |
| `scripts/automation/state_machine.py` | 315 | FSM with 7 states, transitions, persistence |
| `scripts/automation/base_agent.py` | 100 | Abstract agent interface |
| `scripts/automation/approval_gate.py` | 328 | Human approval gate with persistence |
| `scripts/automation/provenance_agent.py` | 155 | ProvenanceResolver adapter |
| `scripts/automation/quality_agent.py` | 151 | Quality check placeholder |
| `scripts/automation/revision_agent.py` | 128 | Revision check placeholder |
| `scripts/automation/validation_agent.py` | 162 | Validation check placeholder |
| `scripts/automation/pipeline_orchestrator.py` | 466 | Pipeline orchestrator |
| `tests/test_automation_layer.py` | 494 | 47 tests |
| `docs/automation_layer_v1.md` | — | This document |

**Total: 11 files, ~2,362 lines of new code**

### Files Modified

| File | Change |
|---|---|
| None | **Zero existing files modified.** |

### Immutable Dataset Protection

The automation layer **never writes to**:
- `curated/` — immutable dataset files
- `review_queue/` — review queue artifacts
- `training_views/` — training view files
- `raw/` — raw data sources

**Only writes to:**
- `metadata/pipeline_state/` — state machine persistence
- `metadata/pipeline_approvals.json` — approval gate persistence
- `tmp/` — temporary reports

---

## Tests

All 47 tests pass covering:

| Category | Tests | What's Tested |
|---|---|---|
| **State Machine - Valid** | 7 | Initial state, full sequence, no error, mutual exclusion, terminal, history, metadata |
| **State Machine - Invalid** | 6 | Skip, backward, skip approval, post-terminal, can_transition_to, non-enum |
| **State Machine - Helpers** | 5 | is_after, is_before, is_blocked, is_terminal, summary |
| **State Machine - Persistence** | 4 | Round-trip, file exists, no-file, reset |
| **Approval Gate** | 10 | Create, approve, deny, nonexistent, check gate (4), persistence, list, rescind |
| **Approval Blocking** | 4 | Mandatory approval, orchestrator blocks, orchestrator releases, denied blocks |
| **Base Agent** | 3 | Abstract, properties, serialization |
| **Orchestrator** | 4 | Initial, reset, request, approval integration |
| **Configuration** | 3 | Valid transitions completeness, state order, transition count |
| **Total** | **47** | |

---

## Quick Start

```python
# Import
from automation import (
    PipelineOrchestrator, PipelineState, PipelineStatus,
    ApproverRole, QualityAgent, ProvenanceAgent,
)

# Run the full pipeline
orch = PipelineOrchestrator("release-v0.3", "/path/to/atlas-dataset")
result = orch.run_full_pipeline()

# Check status
if result.status == PipelineStatus.BLOCKED_ON_APPROVAL:
    print("Pipeline waiting for human approval")
elif result.status == PipelineStatus.COMPLETED:
    print("Dataset released!")
elif result.status == PipelineStatus.FAILED:
    print(f"Pipeline failed: {result.errors}")
```

---

## Future Work

- [ ] **QualityAgent**: Integrate with `quality_score.py` and calibration baselines
- [ ] **RevisionAgent**: Route complex revisions to human reviewers, auto-apply common fixes
- [ ] **ValidationAgent**: Full schema validation, integrity cross-checks with acquisition engine
- [ ] **Webhook integration**: Notify humans when pipeline reaches `WAITING_HUMAN_APPROVAL`
- [ ] **CLI commands**: `atlas pipeline run`, `atlas pipeline approve`, `atlas pipeline status`
- [ ] **Multi-pipeline orchestration**: Parallel datasets, dependency graphs
