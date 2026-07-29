# Atlas Automation Layer v1.0

## Release Summary

Atlas Automation Layer v1.0 transforms the Atlas dataset pipeline from a
primarily manual workflow into an automated, auditable pipeline while
preserving human governance at the release gate.

The automation layer sits on top of existing Atlas infrastructure
(provenance resolver, quality engine, validation tools) without modifying
any existing tool or dataset file. It provides a deterministic state
machine, four pipeline agents, a human approval gate, a release manager,
a CLI runner, and a failure recovery system — all persisted to
`metadata/` for durability across restarts.

---

## Release Highlights

Seven commits built the automation layer incrementally over the existing
codebase:

| Component | Commits | Lines | Purpose |
|-----------|---------|-------|---------|
| State Machine + Approval Gate | 1 | ~630 | FSM with 10 states, persistence, approval workflow |
| ValidationAgent | 1 | ~360 | Structural validation, license gate, duplicate detection |
| QualityAgent | 1 | ~330 | 7-dimension quality scoring with issue flags |
| RevisionAgent | 1 | ~440 | Content revision proposals across 4 categories |
| ReleaseManager | 1 | ~440 | Final release gate with checksummed manifest generation |
| PipelineOrchestrator | 1 | ~610 | Coordinates all agents, enforces approval gate |
| Automation Runner CLI | 1 | ~1,020 | CLI entry point with 10 subcommands |
| Failure Recovery | 1 | ~540 | Retry/resume for failed pipelines |

**Total: 7 commits, 12 files, 5,122 lines of production code.**

### Pipeline Orchestrator

The orchestrator (`PipelineOrchestrator`) owns the state machine,
approval gate, and all agents. It sequences pipeline stages in the
correct order, collects results from each agent, enforces gate policies,
and produces a `PipelineResult` with detailed per-agent status.

### State Machine

The FSM (`StateMachine`) governs pipeline lifecycle with 10 states and
20 valid transitions. State is persisted to
`metadata/pipeline_state/<pipeline_id>.json` on every transition.
Transitions are forward-only by default; FAILED state supports recovery
paths back to each pre-failure stage.

### Human Approval Gate

The approval gate (`ApprovalGate`) enforces that no dataset reaches
RELEASED without a signed-off `ApprovalRequest`. Requests flow through
PENDING → APPROVED / DENIED cycles, and all decisions are persisted
to `metadata/pipeline_approvals.json`.

### Provenance Agent

The provenance agent wraps the existing `ProvenanceResolver` (817 lines
of production code) via an adapter pattern. No existing tool is
modified. The adapter runs provenance resolution and reports unresolved
records as advisory warnings without blocking the pipeline.

### Quality Agent

The quality agent evaluates each record across 7 dimensions (accuracy,
completeness, technical correctness, clarity, usefulness, originality,
relevance). It computes aggregate statistics, flags issues (boilerplate,
very short answers, unclosed code fences), and reports a mean quality
score. Configurable thresholds determine pass/fail.

### Validation Agent

The validation agent performs structural checks on the curated dataset:
- Required field presence
- JSONL parse validity
- ID format validation (no spaces, correct prefix convention)
- License gate (rejects NC / proprietary licenses)
- Duplicate ID and duplicate content detection
- Optional strict mode (minimum quality, verified requirement)
- Schema type detection (base vs. knowledge_object)

### Revision Agent

The revision agent scans records for improvement opportunities across
4 categories: completeness, technical depth, clarity, and usefulness.
It generates structured revision proposals with area, problem statement,
and suggested improvements. Proposals are written to
`metadata/pipeline_revisions/` for human review.

### Release Manager

The release manager is the final gate. It verifies all preceeding gates
(quality, provenance, revision, validation, human approval), generates
a checksummed release manifest and detailed report, and writes them to
`metadata/releases/`. The manifest includes deterministic SHA-256
checksums for integrity verification.

### Automation Runner CLI

The CLI (`automation-runner`) provides 10 subcommands for pipeline
interaction. It supports dry-run simulation, full execution, approval
workflow, and failure recovery — all in both human-readable and JSON
output modes.

### Failure Recovery System

The failure recovery system (`failure_recovery.py`) allows pipelines
that have reached FAILED state to recover without restarting from
INGESTED. It provides:
- **Retry**: re-run only the specific failed agent, continue on success
- **Resume**: clear failure state and run the full pipeline
- **Retry history**: persisted to `metadata/pipeline_retries/`

Retry scoping rules ensure only the relevant agent is re-executed:
- Failed quality → retry quality only
- Failed provenance → retry provenance only
- Failed validation → retry validation only
- Failed revision → retry revision only

---

## Architecture Overview

### Pipeline Flow

```
INGESTED
  │  QualityAgent
  ▼
QUALITY_CHECK
  │  ProvenanceAgent (adapter)
  ▼
PROVENANCE_CHECK
  │  RevisionAgent
  ▼
CONTENT_REVISION
  │  ValidationAgent
  ▼
VALIDATION
  │  PipelineOrchestrator
  ▼
WAITING_HUMAN_APPROVAL
  │  Human Approval Gate (mandatory)
  ├── APPROVED → READY_FOR_RELEASE → RELEASED
  └── DENIED   → RELEASE_REJECTED  (terminal)

Every forward state can also transition to FAILED:

INGESTED ─→ FAILED ─→ INGESTED | QUALITY_CHECK | PROVENANCE_CHECK
                        | CONTENT_REVISION | VALIDATION
```

### Immutable Dataset Protection

The automation layer **never writes** to protected directories:

| Directory | Status | Purpose |
|-----------|--------|---------|
| `curated/` | Read-only | Dataset files — never modified |
| `review_queue/` | Read-only | Review artifacts — never modified |
| `training_views/` | Read-only | Training view files — never modified |
| `raw/` | Read-only | Raw data sources — never modified |

**Only writes to:**

| Path | Purpose |
|------|---------|
| `metadata/pipeline_state/` | State machine persistence |
| `metadata/pipeline_approvals.json` | Approval decisions |
| `metadata/pipeline_revisions/` | Revision proposals |
| `metadata/pipeline_retries/` | Retry history |
| `metadata/releases/` | Release manifests and reports |

No existing file or directory in the repository is modified by the
automation layer. All state is additive and namespaced under `metadata/`.

### Human-Controlled Release Gate

Every pipeline run reaches WAITING_HUMAN_APPROVAL after all automated
checks pass. No dataset can proceed to RELEASED without a signed
approval request. The gate is enforced at two levels:

1. **Orchestrator level**: checks `ApprovalGate.is_releasable()` before
   any transition to READY_FOR_RELEASE.
2. **State machine level**: VALIDATION → RELEASED is not a valid
   transition; the pipeline must pass through WAITING_HUMAN_APPROVAL.

---

## CLI Usage

The `automation-runner` CLI is invoked via:

```bash
python -m scripts.automation_runner <command> [options]
```

### Available Commands

| Command | Purpose |
|---------|---------|
| `run` | Execute full pipeline (INGESTED → RELEASED) |
| `status` | Check pipeline state without running agents |
| `request-approval` | Create a human approval request |
| `approve` | Sign off on a pipeline for release |
| `deny` | Reject a pipeline release |
| `release` | Execute release on an approved pipeline |
| `rescind` | Clear/reset an approval decision |
| `retry` | Re-run a failed agent only |
| `resume` | Clear failure and run full pipeline |
| `retry-history` | Show retry records for a pipeline |

### Example Commands

```bash
# Full pipeline run
python -m scripts.automation_runner run --pipeline-id release-v0.3

# Dry-run without side effects
python -m scripts.automation_runner run --pipeline-id release-v0.3 --dry-run

# Check pipeline status
python -m scripts.automation_runner status --pipeline-id release-v0.3

# Request human approval
python -m scripts.automation_runner request-approval \
    --pipeline-id release-v0.3 --role reviewer

# Approve a pipeline
python -m scripts.automation_runner approve \
    --pipeline-id release-v0.3 --by reviewer_jane

# Deny a pipeline
python -m scripts.automation_runner deny \
    --pipeline-id release-v0.3 --by reviewer_bob \
    --reason "Quality gate not met"

# Retry a failed quality agent after fixing data
python -m scripts.automation_runner retry --pipeline-id release-v0.3

# Resume a failed pipeline
python -m scripts.automation_runner resume --pipeline-id release-v0.3

# Show retry history
python -m scripts.automation_runner retry-history --pipeline-id release-v0.3
```

### JSON Output

All commands support `--json` flag for machine-readable output:

```bash
python -m scripts.automation_runner --json status --pipeline-id release-v0.3
```

---

## Agent Responsibilities

| Agent | Responsibility | Failure Behavior |
|-------|---------------|------------------|
| **QualityAgent** | Evaluate records on 7 quality dimensions. Compute aggregate scores. Flag issues (boilerplate, short answers, code fence problems). | Blocks pipeline. Transitions to FAILED. Recommended action: `RETRY_QUALITY`. |
| **ProvenanceAgent** | Resolve source provenance via `ProvenanceResolver` adapter. Report unresolved records. | Advisory failure. Pipeline continues, failure info recorded. Recommended action: `REVIEW_PROVENANCE_RECORDS`. |
| **RevisionAgent** | Scan records for improvement areas (completeness, technical depth, clarity, usefulness). Generate structured revision proposals. | Advisory failure. Pipeline continues with outstanding proposals. Recommended action: `RESOLVE_REVISIONS`. |
| **ValidationAgent** | Structural validations (required fields, JSONL parse, ID format, license gate, duplicate detection). Optional strict mode. | Blocks pipeline. Transitions to FAILED. Recommended action: `RETRY_VALIDATION`. |
| **ReleaseManager** | Verify all gates (quality, provenance, revision, validation, human approval). Generate release manifest with checksums. Write release artifacts. | Blocks release. On human denial: `RETURN_TO_REVISION_QUEUE`. On gate failure: remains at WAITING_HUMAN_APPROVAL or returns to queue. |

---

## Failure Recovery

### FAILED State

When a blocking agent (quality or validation) fails, the pipeline
transitions to FAILED. Failure details are persisted in the state
machine:

```json
{
  "agent_name": "quality",
  "reason": "Mean quality score 6.4 < minimum 7",
  "next_action": "RETRY_QUALITY",
  "timestamp": "2026-07-28T12:00:00+00:00"
}
```

### RetryManager

`RetryManager` persists retry history to
`metadata/pipeline_retries/<pipeline_id>.json`. Each record captures:

```json
{
  "failed_agent": "quality",
  "previous_reason": "Mean quality score 6.4 < minimum 7",
  "retry_count": 1,
  "timestamp": "2026-07-28T12:00:00+00:00",
  "result": "success"
}
```

### retry vs resume

| Operation | Behavior |
|-----------|----------|
| `retry` | Transitions FAILED → pre-failure state. Runs **only** the failed agent. On success: continues pipeline. On failure: stays FAILED with new retry record. |
| `resume` | Transitions FAILED → pre-failure state. Clears failure info. Runs full pipeline from pre-failure state (all remaining agents). |

### Seat belt: non-FAILED pipelines

Both `retry` and `resume` return a `skipped` result if the pipeline
is not in FAILED state or has no failure info. No state is modified.

---

## Testing and Verification

### Test Suite

| Suite | Tests | Status |
|-------|-------|--------|
| Automation Layer (`test_automation_layer.py`) | 117 | All pass |
| Failure Recovery (`test_failure_recovery.py`) | 15 | All pass |
| Provenance Resolver (`test_provenance_resolver.py`) | 36 | All pass |
| **Total** | **168** | **All pass** |

### Ad-Hoc Verification

A standalone verification probe executed 25 checks covering:
- Quality failure → retry → success ✓
- Quality failure → retry → fail again ✓
- Validation failure → retry → success ✓
- Validation failure → retry → fail again ✓
- Resume after quality failure → success ✓
- Resume after quality failure → fail again ✓
- Retry on non-failed pipeline → skipped ✓
- Retry with no failure_info → skipped ✓
- Retry history persistence across reloads ✓
- Immutable directory protection ✓

### Safety Guarantees

- **Zero immutable dataset modifications**: No write to `curated/`,
  `review_queue/`, `training_views/`, or `raw/`.
- **Zero unsafe writes**: All pipeline state is written under `metadata/`.
- **Zero existing tool modifications**: All agents compose existing tools
  (ProvenanceResolver, quality_score.py, etc.) without modification.

---

## Design Principles

### Immutable Dataset Policy

Curated dataset files are treated as immutable artifacts. The automation
layer reads from `curated/` but never writes to it. All pipeline state,
approvals, and release artifacts go to `metadata/`.

### Deterministic Evaluation

Quality scores, validation results, and release checksums are
deterministic for a given dataset. Re-running the pipeline on the same
data produces identical results.

### Auditability

Every state transition, approval decision, and retry attempt is
persisted with timestamps and identifiers. The complete history of a
pipeline can be reconstructed from `metadata/pipeline_state/`.

### Human Approval Before Release

No automated pipeline can reach RELEASED without an explicit human
approval. The gate is enforced at the orchestrator level and the state
machine level, providing defense in depth.

### Backward Compatibility

The automation layer is fully additive. No existing Atlas tool,
workflow, or dataset structure is affected. Existing scripts continue
to work unchanged.

---

## Limitations / Deferred to v2

The following capabilities are explicitly deferred to future releases:

- **Web dashboard**: No browser-based pipeline monitoring or control.
- **Scheduler**: No cron-based or event-driven pipeline triggering.
- **Distributed workers**: Parallel agent execution across machines.
- **Autonomous acquisition**: Automated source discovery and ingestion
  triggering.
- **Cloud execution**: No deployment to cloud infrastructure.
- **Human review UI**: No dedicated interface for revision review
  or approval workflows.
- **Webhook integration**: No notifications when pipelines reach
  WAITING_HUMAN_APPROVAL.
- **Multi-pipeline orchestration**: Parallel datasets, dependency
  graphs, and cross-pipeline coordination.

---

## Migration / Upgrade Notes

- **Existing Atlas tools remain compatible.** No tool was modified.
  The provenance resolver, quality scorer, validators, and all CLI
  scripts continue to work as before.
- **The automation layer is additive.** It introduces 12 new files
  under `scripts/automation/` and one new CLI entry point
  (`scripts/automation_runner.py`). No existing file was changed in
  the original automation layer v1.1–v1.4 commits.
- **No existing dataset structure was changed.** The `curated/`,
  `schemas/`, `raw/`, `training_views/`, and `review_queue/`
  directories are untouched.
- **Migration to v2** will follow the same additive pattern. The agent
  interface (`BaseAgent`), state machine, and orchestrator are designed
  for extension without modification.

---

## Release Metadata

| Field | Value |
|-------|-------|
| **Version** | Atlas Automation Layer v1.0 |
| **Status** | Stable |
| **Release Date** | 2026-07-28 |
| **Repository** | [EffNine/atlas-dataset](https://github.com/EffNine/atlas-dataset) |
| **Tag** | `atlas-automation-v1.0` |
| **Commits** | 7 (automation layer only) |
| **Production code** | 5,122 lines across 12 files |
| **Tests** | 168 total (132 automation + 36 provenance) |
| **Test pass rate** | 100% |
| **Immutability** | Zero writes to curated/, review_queue/, training_views/, raw/ |
| **License** | MIT |
