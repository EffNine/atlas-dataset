# Atlas Engineering Handbook

**Version:** 1.0  
**Last Updated:** 2026-07-29  
**Maintainer:** Atlas Engineering Team  
**Audience:** Human contributors and AI agents  
**Scope:** All Atlas dataset pipeline development and operations

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Core Engineering Principles](#2-core-engineering-principles)
3. [AI Agent Operating Rules](#3-ai-agent-operating-rules)
4. [Forbidden Actions](#4-forbidden-actions)
5. [Repository Change Rules](#5-repository-change-rules)
6. [Coding Standards](#6-coding-standards)
7. [Agent Development Pattern](#7-agent-development-pattern)
8. [State Machine Rules](#8-state-machine-rules)
9. [Testing Requirements](#9-testing-requirements)
10. [Git Workflow](#10-git-workflow)
11. [Commit Standards](#11-commit-standards)
12. [Release Procedure](#12-release-procedure)
13. [Incident Recovery](#13-incident-recovery)
14. [Future Extension Rules](#14-future-extension-rules)
15. [Engineering Checklist](#15-engineering-checklist)

---

## 1. Introduction

### Purpose

This handbook defines the engineering rules, development workflow, safety constraints, and operating procedures for all future contributors and AI agents working on Atlas. It is the single source of truth for how Atlas is built, maintained, and operated safely.

### Audience

This document is mandatory reading for:

- Human engineers contributing to the Atlas codebase
- AI coding agents operating within the Atlas repository
- Code reviewers evaluating Atlas changes
- Release managers coordinating Atlas deployments
- Any automated system that interacts with Atlas artifacts

### Why Atlas Requires Strict Engineering Discipline

Atlas is a dataset automation system operating at the intersection of data provenance, governance compliance, and production machine learning. Errors in dataset construction propagate silently into downstream model training, where they waste compute resources, degrade model quality, and — in the case of license violations or provenance gaps — create legal liability.

Atlas is a safety-first dataset automation system where correctness, reproducibility, provenance, and governance are more important than speed.

Engineering discipline is not optional. Every shortcut, guessed value, or bypassed gate is a potential failure mode that can corrupt datasets, invalidate releases, or violate licensing terms. This handbook exists to make those boundaries explicit and enforceable.

---

## 2. Core Engineering Principles

### 2.1 Immutable Data Protection

**Rule:** Never modify `curated/`, `raw/`, `review_queue/`, or `training_views/` directories directly.

**Rationale:** Datasets are artifacts of record. Once ingested, cleaned, or released, they must remain verifiably unchanged from the moment their checksum was recorded. Any modification after the fact invalidates the provenance chain and makes the artifact untrustworthy.

**How to comply:**

- All transformations must produce new artifacts — never in-place edits.
- New artifacts receive their own checksum, provenance record, and timestamp.
- Old artifacts remain at their original path with their original checksum.
- If an artifact must be superseded, create a new version — do not replace the old one.
- Deletion of old artifacts is only permitted after a formal deprecation period and audit.

### 2.2 Fail Closed

**Rule:** When any invariant is uncertain, stop immediately. Do not guess, do not proceed, do not make assumptions.

**Triggers for fail-closed:**

| Condition | Action |
|---|---|
| Unknown state | Stop. Report state uncertainty. |
| Missing metadata | Stop. Do not infer values. |
| Missing approval | Stop. Do not assume implied consent. |
| License uncertainty | Stop. Do not proceed without resolution. |
| Checksum mismatch | Stop. Flag provenance failure. |
| Schema violation | Stop. Do not coerce or silently adapt. |

**Rationale:** Every guess is a potential source of silent corruption. Atlas deals with training data where undetected errors compound across thousands of records. The cost of stopping to ask for clarification is always lower than the cost of shipping corrupted data.

### 2.3 Human Approval Boundary

**Rule:** Automation may prepare decisions. Automation may not bypass human approval.

**Boundary definition:**

- **Automation-allowed:** Ingest, validate, score, deduplicate, format, stage, and generate reports.
- **Human-required:** Approve releases, override scores, grant license exceptions, modify governance constraints, accept provenance gaps.

**Gate locations requiring human approval:**

1. Release candidate promotion to release
2. Manual override of automated quality scores
3. Inclusion of sources with ambiguous licensing
4. Exception to any policy defined in this handbook
5. Schema changes to released artifacts

### 2.4 Provenance First

**Rule:** Every dataset artifact must carry a complete provenance record.

**Minimal provenance fields for every artifact:**

| Field | Description |
|---|---|
| `source` | Original origin (URL, DOI, collection name) |
| `license` | SPDX identifier or explicit license text |
| `timestamp` | ISO 8601 timestamp of ingestion/creation |
| `transformation_history` | Ordered list of every transformation applied |
| `checksum` | SHA-256 hash of the artifact content |

**Provenance invariants:**

- No artifact may exist in the dataset pipeline without a matching provenance record.
- Provenance records themselves are immutable once created.
- Transformation history must be append-only — entries are never removed or reordered.
- If provenance is lost or corrupted, the associated artifact is treated as untrusted.

### 2.5 Deterministic Execution

**Rule:** Given the same input, the system must produce the same output, the same checksum, and the same release artifact every time.

**Requirements:**

- All random operations must use a seeded random number generator (seed recorded in metadata).
- Date and time dependencies must use an injected clock — never `datetime.now()` directly.
- Order-dependent operations (sort, group) must use explicit ordering keys.
- External service calls must be deterministic or have their results cached and checksummed.
- Parallel execution must not introduce non-determinism through ordering artifacts.

**Why this matters:** Non-determinism makes bugs unreproducible, releases unverifiable, and audits unreliable. If two engineers cannot independently produce identical datasets from identical inputs, the system is not production-ready.

### 2.6 Modular Agents

**Rule:** Every agent must have exactly one responsibility.

**Design constraints:**

- An agent does one thing and does it well.
- An agent uses existing shared utilities — it does not duplicate logic.
- An agent exposes clear, documented inputs and outputs.
- An agent has no side effects beyond its documented outputs.
- An agent can be tested independently of other agents.

**Signs of a non-modular agent:**

- Performs two or more unrelated operations (e.g., validates and transforms in one step)
- Contains duplicate utility code found in another agent
- Modifies files outside its documented output paths
- Cannot be tested without running other agents first
- Has implicit dependencies on execution order

---

## 3. AI Agent Operating Rules

These rules apply specifically to AI coding agents (including large language model agents) operating in the Atlas repository. They supplement — and are equally enforceable as — all other rules in this handbook.

### 3.1 Pre-Code Inspection Requirements

Before writing any code, an AI agent **must** inspect the following:

1. **Repository structure:** Understand the directory layout, including where source, tests, docs, metadata, and datasets live.
2. **Existing agents:** Read the code of existing agents to understand patterns, conventions, and shared utilities.
3. **Tests:** Examine the test suite to understand expected behaviour, coverage patterns, and test infrastructure.
4. **Metadata contracts:** Review schema definitions, provenance record formats, and manifest structures.
5. **State machine:** Understand the pipeline state definitions, allowed transitions, and terminal states.
6. **Invariants:** Identify the invariants that must hold before, during, and after the agent's operation.
7. **Safety boundaries:** Know which files, directories, and metadata are off-limits for modification.

### 3.2 Pre-Modification Requirements

Before modifying any file, an AI agent **must** explain:

1. **Why the change is needed:** What requirement, bug, or improvement drives this change.
2. **Affected files:** The exact set of files that will be created, modified, or deleted.
3. **Risks:** What could go wrong, which invariants might be affected, and what safety boundaries are being crossed.
4. **Rollback plan:** How the change can be reverted — ideally a single `git revert` command.

### 3.3 Post-Code Requirements

After writing code, an AI agent **must** provide:

1. **Files changed:** A complete list of files created, modified, or deleted.
2. **Tests executed:** Which tests were run, with what results.
3. **Verification results:** Evidence that the code behaves as intended (actual terminal output, not described intent).
4. **Safety confirmation:** Explicit confirmation that no forbidden actions (Section 4) were performed.

### 3.4 Prohibited Agent Behaviours

AI agents **must not**:

- Guess or fabricate data to fill a gap — use explicit placeholders like `[HUMAN MUST SUPPLY]`.
- Claim a result was produced without actually producing it (tool output must back every claim).
- Silently modify files outside the stated scope of work.
- Bypass human approval gates under any circumstances.
- Remove or weaken validation rules to make tests pass.
- Use `--force` or `--no-verify` flags without explicit authorization.

---

## 4. Forbidden Actions

The following actions are **strictly prohibited** under any circumstances unless explicitly authorized in writing by the Atlas engineering lead and recorded in a signed governance record.

### 4.1 Data Modification

- **Never** modify curated datasets, raw datasets, review queue contents, or training views in place.
- **Never** delete, truncate, or overwrite a provenance record.
- **Never** alter a checksum to match an artifact — alter the artifact to match its checksum.
- **Never** modify metadata to hide a governance gap or approval absence.

### 4.2 Validation and Safety

- **Never** bypass, disable, or weaken a validation rule.
- **Never** remove or skip tests to make CI pass.
- **Never** use `--force`, `--yes`, `--no-verify`, or equivalent flags to bypass safeguards.
- **Never** ignore a failing safety check.
- **Never** suppress errors that indicate a potential invariants violation.

### 4.3 Governance and Licensing

- **Never** include data with unknown or ambiguous licensing.
- **Never** hardcode a source decision that should be data-driven.
- **Never** approve a release without recorded human approval.
- **Never** modify a human approval record after it is logged.

### 4.4 System Integrity

- **Never** change a schema without updating all consumers.
- **Never** create hidden side effects — all outputs must be documented and expected.
- **Never** introduce non-determinism into a pipeline step that is expected to be deterministic.
- **Never** delete or overwrite release artifacts.
- **Never** modify the state machine or state transition logic without a formal engineering review.

### 4.5 Enforcement

Violations of any forbidden action must be:

1. Immediately reported to the Atlas engineering lead.
2. Documented in an incident record (see Section 13).
3. Audited to determine whether any dataset artifacts were affected.
4. Remediated before any further work proceeds.

---

## 5. Repository Change Rules

### 5.1 Allowed Changes

The following categories may be changed freely (following standard git workflow):

| Category | Examples |
|---|---|
| `scripts/` | Agent implementations, utilities, CLI tools |
| `tests/` | All test files and test infrastructure |
| `docs/` | All documentation (including this handbook) |
| `metadata/` | Schema definitions, manifest templates, configuration files |
| Temporary runtime files | Logs, caches, intermediate results (must not be committed) |

### 5.2 Restricted Changes

The following categories require explicit approval from the Atlas engineering lead:

| Category | Examples | Approval Required |
|---|---|---|
| `datasets/` | Any file under `curated/`, `raw/`, `review_queue/`, `training_views/` | Written approval + governance record |
| Release artifacts | Final packaged releases, signed manifests | Release manager approval |
| Production metadata | Active manifests, gate state records, approval logs | Engineering lead approval |
| `docs/project/` | This handbook, project governance documents | Engineering lead approval |
| CI/CD configuration | `.github/workflows/`, pipeline definitions | Engineering lead approval |
| Dependency manifests | `requirements.txt`, `pyproject.toml`, `Pipfile` | Team review |

### 5.3 Change Approval Process

For restricted changes:

1. **Request:** Create an issue or pull request describing the change and its justification.
2. **Review:** At least one other engineer must review the proposed change.
3. **Approve:** The Atlas engineering lead or delegate records explicit approval.
4. **Merge:** Merge only after CI passes and all review comments are resolved.
5. **Verify:** Confirm the change had the intended effect and no regressions.

---

## 6. Coding Standards

### 6.1 Python Style

- Follow **PEP 8** with the following additions and exceptions:
  - Line length: 100 characters maximum.
  - Indentation: 4 spaces. No tabs.
  - Blank lines: Two blank lines around top-level definitions; one blank line around method definitions.
  - Imports: Grouped as standard library → third-party → local. Alphabetical within groups.

### 6.2 Naming Conventions

| Element | Convention | Example |
|---|---|---|
| Modules | `snake_case` | `validation_agent.py` |
| Classes | `PascalCase` | `ValidationAgent` |
| Functions | `snake_case` | `verify_checksum()` |
| Variables | `snake_case` | `artifact_path` |
| Constants | `UPPER_SNAKE_CASE` | `MAX_RETRY_COUNT` |
| Private members | Leading underscore | `_validate_internal()` |
| Type variables | PascalCase, short | `T`, `ArtifactT` |

### 6.3 Type Hints

- All function signatures **must** include type annotations for parameters and return values.
- Use `Optional[T]` instead of `T | None` for Python < 3.10 compatibility (or `T | None` if minimum Python 3.10+ is established).
- Use `TypedDict` for structured dictionary types.
- Use `Protocol` for duck-typed interfaces.
- Run `mypy --strict` on all new code.

### 6.4 Error Handling

- Raise specific exception types — never bare `raise Exception` or `raise RuntimeError`.
- Define custom exception classes in a shared `exceptions.py` module.
- Catch only exceptions you can handle — never bare `except:` without re-raising.
- Use `contextlib.suppress` for expected, ignorable errors.
- All external operations (I/O, network, subprocess) must have timeout and retry logic.
- Log every exception at the appropriate level (`error` for failures, `warning` for recoverable).

### 6.5 Logging

- Use Python's `logging` module with structured log records.
- Use the following log levels consistently:

| Level | When to use |
|---|---|
| `DEBUG` | Detailed diagnostic information |
| `INFO` | Normal operation milestones |
| `WARNING` | Recoverable issues, unexpected but non-fatal states |
| `ERROR` | Failures that prevent an operation from completing |
| `CRITICAL` | System-level failures requiring human intervention |

- Include a `correlation_id` in every log record for tracing across agent calls.
- Never log sensitive data (license keys, personal information, raw dataset contents).

### 6.6 Configuration Handling

- Configuration must be externalized — never hardcoded.
- Use YAML for configuration files with a defined schema.
- Default configurations live in the repository at `config/default.yaml`.
- Environment-specific overrides use `config/{environment}.yaml`.
- All configuration values must have documented defaults and validation.

### 6.7 Dependency Policy

- **Stdlib-first:** Use the Python standard library unless a third-party package provides a substantial advantage.
- All new dependencies must be approved by the engineering lead.
- Dependencies must be pinned to exact versions in `requirements.txt` or `pyproject.toml`.
- Minimal dependency footprint is preferred — avoid frameworks when a standard library module suffices.
- Document why each dependency was chosen in the project README.

### 6.8 Testing Requirements

See Section 9 for the full testing requirements. At minimum:

- Every function must have at least one unit test.
- Every agent must have integration tests against its documented inputs/outputs.
- Test coverage must be at or above 90% for all new code.
- Tests must be deterministic — no network calls, no wall-clock dependencies.

---

## 7. Agent Development Pattern

### 7.1 Standard Agent Architecture

Every agent follows a layered architecture:

```
BaseAgent (abstract)
    │
    ├── Input validation
    ├── Provenance record
    ├── Operation logic
    ├── Output validation
    └── Auditing/logging
         │
Agent Implementation
    │
    ├── Inherits BaseAgent
    ├── Implements specific transformation
    └── Registers with Orchestrator
         │
Orchestrator Integration
    │
    ├── Pipeline configuration
    ├── Agent ordering/dependencies
    └── Error propagation
         │
CLI Exposure
    │
    ├── Command-line entry point
    ├── Argument parsing
    └── Return codes
         │
Tests
    │
    ├── Unit tests
    ├── Integration tests
    └── Safety tests
         │
Verification
    ├── Checksum verification
    ├── Provenance verification
    └── Invariant verification
```

### 7.2 Required Agent Components

Every agent implementation **must** include:

| Component | Description |
|---|---|
| **Input definition** | Schema for all input parameters with validation rules |
| **Output definition** | Schema for all output artifacts with expected paths and formats |
| **Persistence** | How state is saved between runs (checkpoints, progress files) |
| **Failure handling** | What happens on partial failure, timeout, or invalid state |
| **Audit trail** | Log entries, provenance records, and exception detail |
| **Rollback support** | How to revert the agent's effects |

### 7.3 BaseAgent Contract

The `BaseAgent` abstract class defines:

- `validate_inputs()` — verify all inputs conform to schema
- `provenance_record()` — create/find the provenance entry for this operation
- `execute()` — perform the agent's primary operation (abstract)
- `validate_outputs()` — verify outputs match expected shape
- `audit()` — write completion record to audit log
- `rollback()` — revert changes if execution fails

### 7.4 Orchestrator Contract

Agents registered with the orchestrator must:

- Accept a standardized configuration dictionary.
- Return a standardized result dictionary containing:
  - `status`: `success`, `failure`, or `partial`
  - `artifacts`: list of produced artifact paths
  - `checksums`: SHA-256 of each artifact
  - `provenance_id`: identifier of the provenance record
  - `errors`: list of error messages (empty on success)
- Not modify shared state outside their documented output paths.

---

## 8. State Machine Rules

### 8.1 Pipeline States

The Atlas pipeline operates through the following state machine:

```
SOURCE_DISCOVERY
    │
    ▼
ACQUISITION_MANIFEST  ◄──── retry
    │
    ▼
PILOT_INGESTION
    │
    ▼
CALIBRATION
    │
    ▼
FULL_INGESTION        ◄──── retry
    │
    ▼
VALIDATION
    │
    ├──► FAILED ─────────► (terminal)
    │
    ▼
QUALITY_CHECK
    │
    ├──► REJECTED ───────► REVIEW
    │                        │
    │                        ▼
    │                     APPROVED or DISCARDED
    │
    ▼
RELEASE_CANDIDATE
    │
    ▼
HUMAN_APPROVAL
    │
    ├──► REJECTED ───────► REVIEW
    │
    ▼
RELEASED               (terminal)
```

### 8.2 Allowed Transitions

| From | To | Condition |
|---|---|---|
| SOURCE_DISCOVERY | ACQUISITION_MANIFEST | Sources documented and licensed |
| ACQUISITION_MANIFEST | PILOT_INGESTION | Manifest validated |
| PILOT_INGESTION | CALIBRATION | Pilot sample verified |
| CALIBRATION | FULL_INGESTION | Scorer calibrated and verified |
| FULL_INGESTION | VALIDATION | Ingestion complete with no errors |
| VALIDATION | FAILED | Validation errors exceed threshold |
| VALIDATION | QUALITY_CHECK | Validation passes |
| QUALITY_CHECK | REJECTED | Quality score below threshold |
| QUALITY_CHECK | RELEASE_CANDIDATE | Quality score meets threshold |
| REJECTED | REVIEW | Human review required |
| REVIEW | QUALITY_CHECK | Re-scored and re-submitted |
| REVIEW | DISCARDED | Source permanently rejected |
| RELEASE_CANDIDATE | HUMAN_APPROVAL | Manifest and provenance complete |
| HUMAN_APPROVAL | REJECTED | Human rejects the release |
| HUMAN_APPROVAL | RELEASED | Human approves the release |
| Any non-terminal | ACQUISITION_MANIFEST | Retry after failure |
| Any state | AUDIT_LOCK | Corruption or incident detected |

### 8.3 Forbidden State Operations

**Direct state manipulation is strictly forbidden.** This means:

- Never manually set a pipeline state in a database or configuration file.
- Never skip a state by calling a downstream function directly.
- Never modify the state machine definition without a formal engineering review.
- Never bypass the `HUMAN_APPROVAL` state — it is the only route to `RELEASED`.

**Rationale:** State machines exist to enforce ordering guarantees. Direct manipulation bypasses validation, safety checks, and human gates. Every transition in the allowed table is there because it includes an invariant check. Skipping one means that invariant is not verified.

### 8.4 Failure Handling

- Transient failures (network timeouts, temporary storage issues): **retry** up to 3 times with exponential backoff.
- Validation failures: **fail** — do not retry without fixing the underlying issue.
- Quality failures: **transition to `REJECTED`** — human review determines next action.
- Corruption detection: **transition to `AUDIT_LOCK`** — all operations halt until audit completes.

### 8.5 Terminal States

- `FAILED`: Pipeline terminated due to unrecoverable error. Requires human intervention to restart.
- `RELEASED`: Artifact successfully released. No further transitions permitted.
- `DISCARDED`: Source permanently rejected. Cannot be re-submitted without full re-discovery.
- `AUDIT_LOCK`: Corruption or governance violation detected. All pipeline activity frozen.

---

## 9. Testing Requirements

### 9.1 Mandatory Test Types

Every feature — every agent, utility, or pipeline modification — must include the following test types:

| Test Type | What It Verifies | Minimum Count |
|---|---|---|
| **Unit tests** | Individual functions behave correctly in isolation | 1 per public function |
| **Integration tests** | Agent works end-to-end with real inputs and outputs | 1 per agent |
| **Safety tests** | Forbidden actions are not possible via the agent's interface | 1 per safety boundary |
| **Persistence tests** | Agent state survives restart, crash recovery, and checkpoints | 1 per persistence path |
| **Failure tests** | Agent handles invalid inputs, missing files, corrupt data gracefully | 1 per error path |

### 9.2 Test Quality Standards

- **Determinism:** Tests must produce the same result every time. No network calls, no `datetime.now()`, no random data.
- **Isolation:** Tests must not depend on execution order. Each test sets up and tears down its own state.
- **Speed:** Unit tests must complete in under 1 second. Integration tests under 30 seconds.
- **Independence:** Tests must work without access to external services or shared resources.

### 9.3 Ad-Hoc Verification

In addition to automated tests, every change must undergo ad-hoc verification:

1. Run the agent or utility against a representative sample.
2. Verify the output checksum matches expectations.
3. Verify no unexpected side effects occurred (check file system, metadata, logs).
4. Run the full test suite and confirm zero failures.

### 9.4 Minimum Expectations Before Merge

Before any branch is merged:

- [ ] All unit tests pass (coverage ≥ 90%)
- [ ] All integration tests pass
- [ ] All safety tests pass
- [ ] All persistence tests pass
- [ ] All failure tests pass
- [ ] Ad-hoc verification completed and documented
- [ ] No test was modified to weaken its assertions
- [ ] No test was removed or marked as expected failure
- [ ] CI passes on the target branch

---

## 10. Git Workflow

### 10.1 Branch Strategy

Atlas uses a structured branch naming convention:

| Branch Pattern | Purpose | Created From | Merges Into |
|---|---|---|---|
| `main` | Stable, production-ready code | N/A | N/A |
| `develop` | Integration branch | `main` | `main` |
| `feature/<name>` | New features | `develop` | `develop` |
| `fix/<name>` | Bug fixes | `develop` | `develop` |
| `docs/<name>` | Documentation changes | `develop` | `develop` |
| `release/<version>` | Release preparation | `develop` | `main` and `develop` |
| `hotfix/<name>` | Urgent production fixes | `main` | `main` and `develop` |

### 10.2 Workflow Steps

1. **Create branch** — Branch from the appropriate source for your change type.
2. **Implement** — Write code following the standards in this handbook.
3. **Test** — Run the full test suite. All tests must pass.
4. **Verify** — Perform ad-hoc verification (Section 9.3).
5. **Commit** — Write a descriptive commit message (see Section 11).
6. **Push** — Push your branch to the remote repository.
7. **Review** — Open a pull request. At least one reviewer must approve.
8. **Merge** — Merge only after all checks pass and review is complete.

### 10.3 Pull Request Standards

Every pull request must include:

- A descriptive title following the commit style (Section 11).
- A body explaining the motivation, approach, and any risks.
- Links to related issues or governance records.
- A checklist of verification steps performed.
- Explicit confirmation that no forbidden actions (Section 4) were performed.

### 10.4 Branch Protection Rules

- `main` and `develop` are protected branches.
- Direct pushes to protected branches are forbidden.
- All merges require passing CI and at least one approved review.

---

## 11. Commit Standards

### 11.1 Commit Style

Commit messages follow this format:

```
<component> <description>

<optional body: motivation, approach, risks>
```

**Examples:**

```
Atlas AcquisitionAgent v1

Implement the initial Acquisition Agent with resume support,
checksum verification, and provenance recording.

- Resumable ingestion with checkpoint tracking
- SHA-256 checksum generation per artifact
- Provenance record creation with full transformation history
- Configurable source discovery via manifest
```

```
Atlas ValidationAgent v1.1

Add format validation for JSONL artifacts. Detect malformed
records before they enter the curation pipeline.

- JSONL parser with per-line error reporting
- Schema validation against field definitions
- Integration test with known-bad inputs
```

```
Atlas Failure Recovery v1

Implement rollback and retry behaviour for failed pipeline steps.
Agents can now resume from checkpoints instead of restarting.

- BaseAgent.rollback() contract defined
- Retry loop with exponential backoff and jitter
- Persistence tests for crash recovery
```

### 11.2 Commit Characteristics

Every commit should be:

| Property | Description |
|---|---|
| **Small** | One logical change per commit. If you can describe it in a sentence, it's small enough. |
| **Descriptive** | The message explains what changed and why, not just that it changed. |
| **Reviewable** | A reviewer can understand the change from the diff alone, with the commit message providing context. |
| **Atomic** | The codebase is in a consistent state before and after the commit. Tests pass at every commit. |

### 11.3 Commit Granularity Rules

- **Feature version** — Each feature version (v1, v1.1, v2) should be committed separately with its own descriptive message.
- **Multi-phase features** — When implementing a multi-phase feature, commit each phase individually after tests pass, not as one bulk commit covering all phases.
- **No mixed concerns** — A commit must not mix refactoring with feature work, or documentation with code changes, or bug fixes with new features.

### 11.4 What Not to Commit

- Temporary files, logs, caches, or intermediate results
- Hardcoded credentials, API keys, or tokens
- Large binary files that should be in dataset storage
- Generated files that are produced by build scripts
- Personal IDE or editor configuration

---

## 12. Release Procedure

### 12.1 Pre-Release Checklist

Before any release is created, **all** of the following conditions must be met:

- [ ] All tests pass (unit, integration, safety, persistence, failure)
- [ ] Test coverage is ≥ 90% for all changed code
- [ ] Validation of every artifact in the release is complete
- [ ] Provenance records exist for every artifact
- [ ] Provenance records pass integrity checks (chain continuity, checksum match)
- [ ] Human approval is recorded in the governance log
- [ ] Release manifest is generated and includes artifact paths, checksums, and timestamps
- [ ] Checksum verification: every artifact SHA-256 matches its manifest entry
- [ ] No forbidden actions were committed during the release cycle
- [ ] All known incidents from this cycle are documented and resolved

### 12.2 Release Process

1. Create a `release/<version>` branch from `develop`.
2. Run the full pre-release checklist (Section 12.1).
3. If any check fails, fix the issue on `develop`, then rebase the release branch.
4. Generate the release manifest with checksums and provenance references.
5. Present the release candidate for human approval.
6. Upon approval, tag the release: `git tag -a v<version> -m "Atlas v<version>"`.
7. Merge the release branch into `main` and `develop`.
8. Archive the release manifest and provenance records.

### 12.3 Release Manifest

Every release must include a manifest containing:

- Release version and date
- Complete list of artifact paths
- SHA-256 checksum of each artifact
- Provenance record identifiers for each artifact
- Link to the human approval record
- Summary of changes since the previous release

### 12.4 Post-Release Verification

After release:

1. Verify the release tag exists and matches the expected commit.
2. Verify the release manifest checksums match the actual artifacts.
3. Verify provenance records are archived and accessible.
4. Verify the human approval record is linked in the release documentation.

---

## 13. Incident Recovery

### 13.1 Incident Types and Response Procedures

#### 13.1.1 Agent Failure

| Condition | An agent crashes, returns an error, or produces invalid output |
|---|---|
| **Response** | 1. Halt dependent agents. 2. Check agent logs for the failure reason. 3. Determine if the failure is transient or persistent. 4. For transient failures: retry up to 3 times with exponential backoff. 5. For persistent failures: file an issue, fix the root cause, rerun. |
| **Rollback** | If the agent produced partial output before failure, run the agent's `rollback()` method to revert its effects. Verify rollback completed. |

#### 13.1.2 Validation Failure

| Condition | A validation check fails during the `VALIDATION` pipeline state |
|---|---|
| **Response** | 1. Log which artifacts failed and why. 2. Determine if the failure is in the data or the validation logic. 3. If data: quarantine failed artifacts, return the pipeline to `PILOT_INGESTION` for re-processing. 4. If validation logic: fix the validation rule, re-validate from the last clean state. |
| **Rollback** | Revert to the last state where validation passed. Re-validate the full dataset after the fix. |

#### 13.1.3 Quality Failure

| Condition | Quality scores fall below the acceptance threshold |
|---|---|
| **Response** | 1. Generate a quality report detailing which sources/records failed. 2. Transition to `REJECTED` state. 3. Present the quality report for human review. 4. Human decides: re-score with adjusted parameters, discard failed sources, or accept the current quality level as an exception. |
| **Rollback** | No automated rollback — human review determines the next action. |

#### 13.1.4 Release Rejection

| Condition | Human reviewer rejects a release candidate |
|---|---|
| **Response** | 1. Record the rejection reason in the governance log. 2. Transition back to `RELEASE_CANDIDATE` or earlier state based on the rejection reason. 3. Address each rejection reason with a fix or documented exception. 4. Re-submit for human approval. |
| **Rollback** | No rollback needed — the release was not published. Re-work the candidate. |

#### 13.1.5 Corrupted Metadata

| Condition | Checksum mismatch, provenance chain break, or schema violation detected in metadata |
|---|---|
| **Response** | 1. Transition immediately to `AUDIT_LOCK` state — freeze all pipeline activity. 2. Identify the scope: which artifacts and records are affected. 3. Restore metadata from the most recent clean backup or git revision. 4. Re-validate all affected artifacts. 5. Determine if the corruption was accidental or malicious — file an incident report. 6. Document the root cause and preventive measures. |
| **Rollback** | Full rollback to the last known-good state. Re-run validation on all artifacts since that state. |

### 13.2 General Recovery Principles

- **Retry first:** Transient failures should be retried before escalating.
- **Resume from checkpoint:** Agents with persistence support resume from the last valid checkpoint, not from the beginning.
- **Rollback when uncertain:** If the extent of corruption is unknown, roll back to the last known-good state.
- **Audit every incident:** Every incident must produce a written record with root cause, scope, remediation, and preventive measures.
- **Never suppress incidents:** An incident that is ignored today becomes a corrupted release tomorrow.

---

## 14. Future Extension Rules

### 14.1 Extension Integration Principle

All future systems — downloaders, normalizers, cleaners, training builders, distributed workers, external plugins — **must** integrate through the existing Atlas architecture. They may not bypass state machines, validation gates, provenance recording, or human approval boundaries.

### 14.2 Extension Requirements

| Requirement | Description |
|---|---|
| **Input/output compatibility** | Must accept and produce artifacts in formats defined by the existing metadata contracts |
| **State machine integration** | Must declare which pipeline state they operate in and which transitions they trigger |
| **Provenance support** | Must create a provenance record for every artifact they produce |
| **Checksum generation** | Must generate and verify SHA-256 checksums for all outputs |
| **Failure handling** | Must implement retry, rollback, and audit logging per this handbook |
| **Test coverage** | Must include unit, integration, safety, persistence, and failure tests |
| **Human approval** | Must respect all human approval gates — may not bypass them |

### 14.3 Specific Extension Types

#### 14.3.1 Downloader

- Must operate within the `ACQUISITION_MANIFEST` or `FULL_INGESTION` state.
- Must record source URL, download timestamp, and content checksum.
- Must support resumable downloads.
- Must validate downloaded content against expected format before proceeding.

#### 14.3.2 Normalizer

- Must operate between `FULL_INGESTION` and `VALIDATION`.
- Must preserve original raw data — output normalized data as a new artifact.
- Must record the normalization rules applied in the transformation history.

#### 14.3.3 Cleaner / Deduplicator

- Must operate within `VALIDATION` state.
- Must produce a report of all removed or modified records.
- Must not modify existing artifacts — creates cleaned artifacts with lineage pointing to originals.

#### 14.3.4 Training Builder

- Must operate after `RELEASED` state — never before.
- Must reference release artifacts by their checksum, not by path.
- Must include the release version and artifact checksum in the training manifest.

#### 14.3.5 Distributed Workers

- Must maintain the deterministic execution principle — no ordering differences between worker runs.
- Must merge results deterministically (sorted, by checksum, etc.).
- Must report individual worker provenance so any single artifact can be traced to the worker that produced it.

#### 14.3.6 External Plugins

- Must be isolated from core pipeline state — operate on copies, not live data.
- Must be approved and reviewed before integration.
- Must comply with all safety, governance, and testing requirements in this handbook.

### 14.4 Non-Compliance

Any extension that violates these integration rules is not permitted to operate in the Atlas pipeline. Non-compliant extensions must be removed or redesigned before they can interact with Atlas artifacts or state.

---

## 15. Engineering Checklist

### 15.1 Before Coding

- [ ] Read and understood this handbook
- [ ] Inspected the repository structure
- [ ] Read existing agents and utilities for patterns
- [ ] Reviewed existing tests for coverage expectations
- [ ] Understood the state machine and current pipeline state
- [ ] Identified all invariants that must be preserved
- [ ] Identified safety boundaries and forbidden zones
- [ ] Filed an issue or task describing the planned work
- [ ] Discussed approach with the team (if non-trivial)
- [ ] Exported the branch name per the naming convention

### 15.2 During Coding

- [ ] Following PEP 8 and project naming conventions
- [ ] Adding type hints to every function signature
- [ ] Writing unit tests alongside implementation
- [ ] Using stdlib-first approach — no unnecessary dependencies
- [ ] Handling errors explicitly — no bare excepts
- [ ] Adding structured logging with correlation IDs
- [ ] Externalizing configuration — no hardcoded values
- [ ] Creating provenance records for every artifact
- [ ] Generating SHA-256 checksums for every output
- [ ] Implementing rollback support for every agent

### 15.3 Before Commit

- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] All safety tests pass
- [ ] Test coverage is ≥ 90% for new code
- [ ] No existing tests were weakened or removed
- [ ] Linter passes (ruff or flake8)
- [ ] Type checker passes (mypy --strict)
- [ ] Commit message follows the style guide
- [ ] Commit is atomic — one logical change
- [ ] No temporary files, secrets, or binaries in the commit

### 15.4 Before Merge

- [ ] Pull request is open with descriptive title and body
- [ ] Motivation, approach, and risks are documented
- [ ] At least one reviewer has approved the change
- [ ] CI passes on the target branch
- [ ] Ad-hoc verification was performed (Section 9.3)
- [ ] Safety confirmation was provided (Section 3.3)
- [ ] No forbidden actions were performed (Section 4)
- [ ] Release checklist items are satisfied (if this is a release)

### 15.5 Before Release

- [ ] All pre-release checklist items are complete (Section 12.1)
- [ ] Release manifest is generated and verified
- [ ] Human approval is recorded in the governance log
- [ ] Release branch is created from `develop`
- [ ] Git tag is applied: `v<version>`
- [ ] Release branch is merged into `main` and `develop`
- [ ] Post-release verification is complete (Section 12.4)
- [ ] Release artifacts are archived with provenance records

---

## Appendices

### A. Reference Documents

| Document | Location |
|---|---|
| Project README | `IDEA.md` |
| Dataset Engineering Skill | `docs/skills/llm-dataset-engineering.md` |
| State Machine Reference | `docs/reference/pipeline-states.md` |

### B. Glossary

| Term | Definition |
|---|---|
| **Artifact** | Any file produced or consumed by the pipeline (dataset, manifest, provenance record) |
| **Checksum** | SHA-256 hash used to verify artifact integrity |
| **Provenance** | The complete history of an artifact's origin, transformations, and ownership |
| **Governance** | The policies and approvals governing dataset licensing and distribution |
| **Invariant** | A condition that must always hold true during pipeline operation |
| **Fail closed** | A safety principle: when uncertain, stop rather than proceed with guesses |
| **AUDIT_LOCK** | A terminal state that freezes all pipeline activity during incident investigation |

### C. Document Maintenance

This handbook is a living document. Changes must be proposed via pull request to `docs/project/` and approved by the Atlas engineering lead. Major version changes require team-wide review.

**Version History:**

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-07-29 | Atlas Engineering | Initial handbook |

---

*End of Atlas Engineering Handbook*
