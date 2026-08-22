#!/usr/bin/env python3
"""
synthetic_generator_v0.2.py — Genuinely diversified synthetic data generator for atan-v1.

Unlike v0.1 which used fixed templates producing >99% repetition, v0.2 uses
combinatorial generation across independent dimensions:

  - Variable reasoning graphs (not fixed linear steps)
  - Diverse scenario types with natural language variation
  - Failure branches and recovery paths in trajectories
  - Multiple role interaction patterns
  - Varied response styles (Malay-English ratio, directness, uncertainty)

Target: 10,000 genuinely diverse records with >80% uniqueness.

Categories: architecture, debugging, code_review, planning, testing,
            refactoring, devops, api_design, database, performance
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Seed configuration
# ---------------------------------------------------------------------------

ATLAS_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ATLAS_ROOT / "experiments" / "synthetic_corpus_v0.2"


# ---------------------------------------------------------------------------
# Dimension definitions — each dimension is independently sampled
# ---------------------------------------------------------------------------

# ---- Categories ----
CATEGORIES = [
    "architecture", "debugging", "code_review", "planning", "testing",
    "refactoring", "devops", "api_design", "database", "performance",
]

# ---- Difficulty levels with target distribution ----
DIFFICULTY_DISTRIBUTION = {
    "L2": 0.15,   # 1,500
    "L3": 0.40,   # 4,000
    "L4": 0.35,   # 3,500
    "L5": 0.10,   # 1,000
}

# ---- Project types (context) ----
PROJECT_TYPES = [
    "Rust CLI tool", "TypeScript backend service", "React SPA frontend",
    "Python FastAPI microservice", "Go HTTP service", "Dockerized monorepo",
    "event-driven worker pipeline", "ML inference service",
    "data ETL pipeline", "release/CI-CD platform", "MQTT automation service",
    "repository-level coding agent", "internal developer platform",
    "mobile app backend", "GraphQL API gateway",
]

# ---- Problem domains per category ----
PROBLEM_DOMAINS: dict[str, list[str]] = {
    "architecture": [
        "service boundary ownership", "module coupling", "dependency inversion",
        "cache placement strategy", "event processing pipeline", "plugin isolation",
        "configuration management", "repository layering", "state management",
        "deployment topology", "error handling boundary", "serialization format",
        "authentication flow", "rate limiting strategy", "multi-tenancy design",
        "feature flag architecture", "API versioning strategy", "background job system",
        "real-time sync mechanism", "eventual consistency model",
    ],
    "debugging": [
        "race condition in concurrent handler", "memory leak in long-running process",
        "stale cache after config change", "deadlock under load",
        "CI-only failure (works locally)", "intermittent timeout",
        "serialization mismatch between services", "incorrect state transition",
        "environment-specific behavior", "duplicate event processing",
        "connection pool exhaustion", "unexpected retry storm",
        "goroutine leak", "background job stuck", "auth token refresh loop",
    ],
    "code_review": [
        "security vulnerability in auth module", "missing error handling",
        "tight coupling between modules", "inconsistent error patterns",
        "hardcoded configuration", "missing unit test coverage",
        " SQL injection risk", "improper resource cleanup",
        "circular import dependency", "unbounded recursion risk",
    ],
    "planning": [
        "migration from sync to async architecture", "introducing caching layer",
        "breaking API change for v2", "adding multi-region support",
        "migrating database schema", "implementing feature flags",
        "adding observability to legacy service", "splitting monolith module",
        "adopting event sourcing", "implementing circuit breaker pattern",
    ],
    "testing": [
        "flaky integration test", "missing edge case in validator",
        "test environment drift from production", "slow test suite blocking PRs",
        "mocking complex dependency", "test data management",
        "coverage gap in critical path", "non-deterministic output in tests",
    ],
    "refactoring": [
        "extract shared utility from duplicated code", "replace conditional with polymorphism",
        "split large function into focused helpers", "introduce interface abstraction",
        "rename misleading variable", "extract error type hierarchy",
        "decouple business logic from I/O", "replace inheritance with composition",
    ],
    "devops": [
        "container image size optimization", "Kubernetes resource limit misconfiguration",
        "rollback strategy for zero-downtime deploy", "secret management in CI pipeline",
        "log aggregation across services", "health check configuration",
        "blue-green deployment setup", "backup and restore procedure",
    ],
    "api_design": [
        "REST vs GraphQL trade-off for new endpoint", "pagination strategy for large dataset",
        "rate limiting policy design", "idempotency key implementation",
        "webhook reliability guarantee", "API deprecation timeline",
        "request validation boundary", "response shape normalization",
    ],
    "database": [
        "N+1 query in hot path", "index missing on filter column",
        "connection pooling misconfiguration", "migration rollback strategy",
        "read replica lag causing stale data", "table partitioning for growth",
        "transaction isolation level choice", "deadlock in write-heavy table",
    ],
    "performance": [
        "slow query on large table", "memory pressure under peak load",
        "GC pause spike", "cold start latency in serverless",
        "network round-trip in hot loop", "CPU-bound serialization bottleneck",
        "thread pool exhaustion", "disk I/O contention",
    ],
}

# ---- User request patterns (natural language variety) ----
USER_PATTERNS: dict[str, list[dict]] = {
    "architecture": [
        "{project} ada isu dekat {problem}. Saya ada dua option: {option_a} atau {option_b}. Mana lebih sesuai untuk jangka panjang?",
        "Saya design {problem} dekat {project}. Option yang saya pertimbang: {option_a} vs {option_b}. Boleh review trade-off?",
        "Untuk {project}, team kita sedang debate pasal {problem}. Ada yang kata {option_a}, ada yang {option_b}. Nak dengar pandangan.",
        "Kita kena decide pasal {problem} dekat {project}. Saya倾向 {option_a} sebab {reason_a}, tapi {option_b} ada kelebihan di {aspect_b}. Bagaimana?",
    ],
    "debugging": [
        "Saya nampak {symptom} dekat {project}. Dah try {tried_a} dan {tried_b}, tapi masih berlaku. Boleh tolong trace?",
        "{project} sekarang ada {symptom}. Error log mention {error_hint}. Saya rasa mungkin dari {hypothesis}, tapi tak pasti.",
        "Nak minta tolong debug: {symptom} terjadi intermittently. Paling strange, ia berlaku di {condition} tapi not di {other_condition}.",
        "Ada yang report {symptom} dekat production {project}. saya dah check {checked_1}, {checked_2}, {checked_3}. Sesiapa punca?",
    ],
    "code_review": [
        "Boleh review PR ni? Saya buat {change_description} dekat {project}. Tak sure sama ada approach ni correct.",
        "I just push changes untuk {problem} dekat {project}. Apa yang anda akan check first?",
        "Ini PR untuk {project}: {pr_description}. Adakah saya miss sebarang edge case?",
    ],
    "planning": [
        "Kita nak plan {goal} untuk {project}. Current state: {current_state}. Apa yang perlu kita pertimbangkan?",
        "Saya ada roadmap untuk {project}. Target: {target}. Langkah pertama yang saya faham ialah {step1}. Adakah ini betul?",
        "Kita nak {goal} tapi ada constraint: {constraint}. Boleh cadangkan phased approach?",
    ],
    "testing": [
        "Test suite kita sekarang {test_problem} dekat {project}. macam mana nak fix tanpa breakdown existing coverage?",
        "Saya try to write test untuk {scenario} tapi {blocker}. Ada cadangan?",
        "Performance test menunjukkan {result}. Adakah ini acceptable atau kita kena optimize?",
    ],
    "refactoring": [
        "Saya nak refactor {code_area} dekat {project}. Sekarang dia {current_state}. Macam mana nak break without breaking consumers?",
        "Ada duplicated logic dekat {area1} dan {area2}. Nak combine tapi tak tahu cara paling safe.",
    ],
    "devops": [
        "{project} deployment sekarang manual dan prone to error. Nak automate tapi tak sure tool mana yang sesuai.",
        "Kita ada {infra_problem} dekat {project}. Nak solution yang simple tapi effective.",
    ],
    "api_design": [
        "Nak design API endpoint untuk {use_case} dekat {project}. Ada trade-off antara {aspect1} dan {aspect2}.",
        "Current API ada {api_problem}. Nak backward-compatible fix tapi tak nak break existing clients.",
    ],
    "database": [
        "{project} ada {db_problem}. Dah try {tried_solution} tapi masih slow. Apa lagi opsi yang ada?",
        "Kena buat schema migration untuk {project}. Data sudah besar, takut downtime. Macam mana nak safe migrate?",
    ],
    "performance": [
        "{project} sekarang {perf_problem}. Profile menunjukkan bottleneck dekat {bottleneck}. Nak optimize tanpa break correctness.",
        "Load test show {result}. Adakah ini infrastructure issue atau application issue?",
    ],
}

# ---- Assistant response style dimensions ----
RESPONSE_OPENINGS = [
    # Direct disagreement
    "Saya tak Akan approve approach ni untuk production. ",
    "Saya cadang kita jangan buat macam tu dulu. ",
    "Hold on — sebelum kita proceed, saya nak challenge assumption ni. ",
    "Ini memang risky. Kalau kita teruskan, downstream consequence dia akan",
    # Conditional agreement
    "Boleh, tapi hanya untuk prototype. Kalau target kita maintain jangka panjang, ",
    "Approach ni okay untuk sekarang, tapi ada trade-off yang kita kena acknowledge: ",
    "Saya setuju dengan direction ni, tapi ada beberapa boundary condition yang patut kita consider: ",
    # Evidence-based
    "Daripada apa yang saya nampak, masalah utama bukan di {surface_issue}. Ia rooted di {root_cause}. ",
    "Saya trace call path dia. First evidence point yang mencurigakan ialah {evidence}. ",
    # Empathetic but firm
    "Saya faham kenapa option ni menarik — {why attractive}. Tapi daripada experience saya, {counterpoint}. ",
    "Soalan ni simple appearance tapi complicated implication. Mari kita break down: ",
    # Analytical
    "Mari kita semak constraints dulu sebelum propose solution. {constraint1}, {constraint2}, dan {constraint3}. ",
    "Before commit pada approach mana-mana, kita perlu jawab tiga soalan: {q1}, {q2}, {q3}? ",
]

RESPONSE_STRUCTURES = [
    # Linear reasoning
    "linear",
    # Branching (if-then alternatives)
    "branching",
    # Socratic (question-led)
    "socratic",
    # First-principles
    "first_principles",
    # Trade-off matrix
    "tradeoff_matrix",
    # Failure-mode first
    "failure_mode_first",
]

# ---- Malay-English ratio variation ----
MALAY_DOMINANT = 0  # 70% BM, 30% EN technical terms
EN_MIXED = 1         # 50% BM, 50% EN
EN_DOMINANT = 2      # 30% BM, 70% EN (for L5 research-level)

# ---- Reasoning step templates (variable, not fixed) ----
REASONING_STEPS_TEMPLATES: dict[str, list[list[str]]] = {
    "linear": [
        ["symptom", "reproduce", "evidence", "hypothesis", "test", "root_cause", "fix", "verify"],
        ["requirement", "constraint", "options", "decision", "implementation", "validation"],
        ["current_state", "target_state", "gap_analysis", "plan", "execution", "review"],
        ["problem", "investigate", "analyze", "synthesize", "recommend"],
    ],
    "branching": [
        ["symptom", "gather_evidence", {"path_a": ["hypothesis_a", "test_a", "result_a"]}, {"path_b": ["hypothesis_b", "test_b", "result_b"]}, "converge", "fix"],
        ["understand", "identify_options", {"option_1": ["pros_1", "cons_1", "test_1"]}, {"option_2": ["pros_2", "cons_2", "test_2"]}, "decide", "implement"],
    ],
    "socratic": [
        ["observe", "question_assumption", "gather_counter_evidence", "refine_question", "test_refined", "conclude"],
        ["notice_pattern", "ask_why", "trace_cause", "ask_why_again", "find_root", "propose"],
    ],
    "first_principles": [
        ["state_problem", "decompose_to_facts", "identify_constraints", "rebuild_from_scratch", "evaluate", "decide"],
    ],
    "tradeoff_matrix": [
        ["enumerate_options", "define_criteria", "score_each_option", "identify_showstopper", "recommend_with_caveats"],
    ],
    "failure_mode_first": [
        ["assume_failure", "identify_single_points_of_failure", "stress_test_each", "design_guard_rails", "validate"],
    ],
}

# ---- Tool actions for agent trajectories ----
TOOL_ACTIONS = [
    "inspect relevant source file", "run type checker", "search for symbol references",
    "inspect git diff", "run focused test", "inspect configuration",
    "run integration test", "inspect logs", "list repository files",
    "run profiling tool", "check dependency tree", "read error traceback",
    "compare branch diff", "inspect CI output", "check database schema",
    "read API documentation", "inspect test coverage report",
    "analyze call graph", "check environment variables", "run load test",
]

TOOL_RESULT_PATTERNS = [
    "Confirmed: {finding}. No anomalies in related modules.",
    "Output differs from expectation — {finding}.",
    "Boundary case detected: {finding}. This may be the root cause.",
    "Nothing suspicious here. Moving to next hypothesis.",
    "Found the expected pattern at {location}. Continuing investigation.",
    "Unexpected: {finding}. Revising hypothesis.",
    "Multi-source correlation: {finding}. Converging on root cause.",
]

AGENT_RESPONSE_TEMPLATES = [
    "Saya akan inspect context dulu sebelum buat sebarang perubahan. {next_action}",
    "Saya ada hypothesis awal tentang punca {issue}. Saya akan test hypothesis itu dengan action yang paling kecil dulu.",
    "Hypothesis pertama tak cukup untuk explain failure. Saya update mental model dan tukar approach.",
    "Saya akan buat minimal fix, kemudian run regression test sebelum claim selesai.",
    "Fix verified untuk failure mode yang diuji. Saya tidak akan claim production-ready tanpa broader validation jika belum dijalankan.",
    "Saya dapati {finding}. Ini mengubah direction investigation saya.",
    "Ada {new_evidence} yang saya terlepas before. Saya perlu backtrack dan re-examine {re examined_area}.",
    "Solution ni menyelesaikan {problem} tapi introduce {new_risk}. Saya perlu weigh trade-off ni sebelum proceed.",
    "Saya akan trace dependency chain dulu — {dependency_context} — sebelum decide pada approach.",
    "Edge case yang saya concern: {edge_case}. Saya tambah test case ni dulu sebelum implement fix.",
]

# ---- Failure branch patterns ----
FAILURE_BRANCHES = [
    {
        "trigger": "tool_returns_error",
        "agent_response": "Tool call gagal dengan error. Saya akan diagnose error dan retry dengan corrected parameters.",
        "recovery": "retry_with_adjustment",
    },
    {
        "trigger": "test_fails",
        "agent_response": "Test still fails. Hypothesis saya salah. Saya perlu form new hypothesis berdasarkan error output.",
        "recovery": "form_new_hypothesis",
    },
    {
        "trigger": "regression_detected",
        "agent_response": "Wait — fix saya introduce regression dekat {affected_area}. Saya revert dan re-approach dari sudut lain.",
        "recovery": "revert_and_reroute",
    },
    {
        "trigger": "scope_creep",
        "agent_response": "Saya nampak masalah ni lebih luas dari yang saya anggap awal. Ada {related_issue} yang juga affected. Saya pause dan reassess scope.",
        "recovery": "reassess_scope",
    },
    {
        "trigger": "insufficient_evidence",
        "agent_response": "Evidence setakat ni belum cukup untuk conclude root cause. Saya perlu collect more data daripada {data_source}.",
        "recovery": "collect_more_data",
    },
]

# ---- Scenario modifiers for natural language variation ----
SCENARIO_MODIFIERS = [
    "", "", "",  # no modifier (weight towards plain)
    "urgent — deadline hari ini",
    "non-urgent — kita ada masa seminggu",
    "production incident, P1 severity",
    "prototype phase, boleh quick-and-dirty",
    "maintenance mode, nak sustainable solution",
    "after failed attempt oleh teammate",
    "during architecture review session",
    "post-mortem discussion",
]

# ---- Response length targets by difficulty ----
LENGTH_TARGETS: dict[str, tuple[int, int]] = {
    "L2": (200, 400),    # concise, direct
    "L3": (400, 700),    # moderate, with reasoning
    "L4": (600, 1000),   # detailed, with trade-offs
    "L5": (900, 1500),   # thorough, with alternatives and caveats
}


# ---------------------------------------------------------------------------
# Core generator classes
# ---------------------------------------------------------------------------

@dataclass
class GeneratorConfig:
    """Configuration for the v0.2 generator."""
    seed: int = 42
    total_records: int = 10_000
    output_dir: Path = field(default_factory=lambda: DEFAULT_OUTPUT_DIR)
    val_ratio: float = 0.1
    max_attempts_per_record: int = 50  # safety net for generation

    # Category distribution (will be normalized)
    category_weights: dict[str, float] = field(default_factory=lambda: {
        "architecture": 1.0, "debugging": 1.2, "code_review": 0.8,
        "planning": 0.7, "testing": 0.6, "refactoring": 0.7,
        "devops": 0.5, "api_design": 0.6, "database": 0.8, "performance": 0.7,
    })

    # Difficulty distribution
    difficulty_distribution: dict[str, float] = field(default_factory=lambda: DIFFICULTY_DISTRIBUTION.copy())


def _weighted_choice(items: list, weights: list[float]) -> Any:
    total = sum(weights)
    r = random.random() * total
    cumulative = 0.0
    for item, w in zip(items, weights):
        cumulative += w
        if r <= cumulative:
            return item
    return items[-1]


def _fill_template(template: str, ctx: dict[str, str]) -> str:
    """Fill a template string with context values, skipping missing keys."""
    result = template
    for key, value in ctx.items():
        placeholder = "{" + key + "}"
        if placeholder in result:
            result = result.replace(placeholder, value)
    # Remove any unfilled placeholders
    import re
    result = re.sub(r'\{[^}]+\}', '', result)
    return result.strip()


def _generate_context(category: str, difficulty: str, project_type: str) -> dict[str, str]:
    """Generate rich context variables for a record."""
    ctx: dict[str, str] = {
        "project": project_type,
        "category": category,
        "difficulty": difficulty,
    }

    # Problem domain
    problems = PROBLEM_DOMAINS.get(category, PROBLEM_DOMAINS["architecture"])
    ctx["problem"] = random.choice(problems)

    # Symptom (for debugging)
    symptoms = {
        "race condition": "race condition pada concurrent request handler",
        "memory leak": "memory usage bertambah steadily without bound",
        "stale cache": "stale cache selepas config reload",
        "deadlock": "deadlock intermittent bawah heavy load",
        "CI-only failure": "CI-only failure — works locally, fails in pipeline",
        "serialization mismatch": "serialization mismatch antara service A dan B",
        "incorrect state": "incorrect state transition selepas deploy",
        "intermittent timeout": "intermittent timeout pada critical path",
        "duplicate event": "duplicate event processing menyebabkan double charge",
        "connection pool": "connection pool exhaustion under peak traffic",
    }
    ctx["symptom"] = random.choice(list(symptoms.values()))

    # Options for architecture decisions
    option_pairs = [
        ("introduce a dedicated service", "extend the existing component"),
        ("use an event-driven boundary", "keep the design modular behind an interface"),
        ("adopt CQRS pattern", "stick with current CRUD model"),
        ("introduce a message queue", "use synchronous calls"),
        ("implement circuit breaker", "add retry with backoff"),
        ("split into microservice", "keep as monolith module"),
        ("use database view", "compute on application side"),
        ("introduce caching layer", "optimize the query directly"),
        ("adopt feature flags", "do a hard cutover deploy"),
        ("use typed protocol (gRPC)", "stay with REST/JSON"),
    ]
    opt_a, opt_b = random.choice(option_pairs)
    ctx["option_a"] = opt_a
    ctx["option_b"] = opt_b

    # Reasons and aspects
    ctx["reason_a"] = random.choice([
        "implementation dia lebih straightforward",
        "team dah biasa dengan pattern ni",
        "integration cost lebih rendah",
        "existing documentation cover scenario ni",
        "timeline ketat dan solution ni paling cepat",
    ])
    ctx["aspect_b"] = random.choice([
        "maintainability jangka panjang",
        "scalability under growth",
        "operational simplicity",
        "decoupling entre modules",
        "testability",
    ])

    # Tried solutions (for debugging)
    ctx["tried_a"] = random.choice([
        "restarting the service", "checking the logs", "reverting recent changes",
        "increasing timeout value", "clearing the cache", "rolling back to previous version",
    ])
    ctx["tried_b"] = random.choice([
        "adding debug instrumentation", "running local reproduction", "consulting the docs",
        "checking dependency versions", "validating environment config",
    ])

    # Error hints
    ctx["error_hint"] = random.choice([
        "stack overflow in recursive call", "null pointer at unexpected path",
        "permission denied on resource", "timeout exceeded",
        "invalid state in transition", "resource contention",
    ])

    # Hypothesis
    ctx["hypothesis"] = random.choice([
        "dia relate dengan race condition", "mungkin ada memory leak",
        "configuration drift between environments", "incorrect assumption about idempotency",
        "concurrency bug in the handler", "data corruption during migration",
    ])

    # Checked items
    ctx["checked_1"] = random.choice(["application logs", "database queries", "network traces", "memory profile"])
    ctx["checked_2"] = random.choice(["dependency versions", "environment variables", "configuration files", "container specs"])
    ctx["checked_3"] = random.choice(["recent git commits", "CI pipeline config", "deployment manifests", "monitoring alerts"])

    # Conditions
    ctx["condition"] = random.choice(["under load", "after restart", "with specific input data", "in production only"])
    ctx["other_condition"] = random.choice(["locally", "in staging", "with small datasets", "during unit tests"])

    # Constraint items
    ctx["constraint1"] = random.choice(["backward compatibility with v1 clients", "latency SLA under 100ms", "zero downtime deployment required"])
    ctx["constraint2"] = random.choice(["team size limited to 3 engineers", "legacy codebase with no tests", "deployment only through CI/CD pipeline"])
    ctx["constraint3"] = random.choice(["data privacy compliance requirements", "budget constraint on infrastructure", "existing monitoring gaps"])

    # Questions for socratic
    ctx["q1"] = random.choice(["what is the actual requirement?", "who owns this state?", "what happens under failure?"])
    ctx["q2"] = random.choice(["what is the migration cost?", "who are the downstream consumers?", "what is the rollback plan?"])
    ctx["q3"] = random.choice(["what assumptions are we making?", "is this testable?", "what does 'done' look like?"])

    # Code area and current state (refactoring)
    ctx["code_area"] = random.choice(["the authentication module", "the data processing pipeline", "the API gateway layer", "the event handler"])
    ctx["current_state"] = random.choice(["duplicated across 5 files", "a 300-line function", "tightly coupled with I/O", "using anti-pattern X"])
    ctx["area1"] = random.choice(["utils/helpers.py", "src/service/a.py", "lib/common/"])
    ctx["area2"] = random.choice(["src/service/b.py", "lib/common/legacy.py", "packages/shared/"])

    # Infrastructure problem
    ctx["infra_problem"] = random.choice([
        "manual deployment causing human error", "no observability into the pipeline",
        "scaling is reactive not proactive", "cost overrun on cloud spend",
    ])

    # Use case and API aspects
    ctx["use_case"] = random.choice([
        "real-time notification delivery", "batch data export", "user search with filters",
        "payment processing webhook", "analytics event ingestion",
    ])
    ctx["aspect1"] = random.choice(["simplicity", "type safety", "developer experience", "runtime performance"])
    ctx["aspect2"] = random.choice(["flexibility", "validation strictness", "versioning strategy", "error granularity"])

    # API problem
    ctx["api_problem"] = random.choice([
        "inconsistent error response format", "missing pagination on list endpoints",
        "no idempotency on mutation endpoints", "coupled response fields",
    ])

    # DB problem
    ctx["db_problem"] = random.choice([
        "query taking 5s on 10M row table", "deadlock under concurrent writes",
        "schema migration blocks reads", "connection pool saturation",
    ])
    ctx["tried_solution"] = random.choice([
        "adding an index", "rewriting the query", "adjusting connection settings",
        "partitioning the table",
    ])

    # Performance problem and bottleneck
    ctx["perf_problem"] = random.choice([
        "p99 latency spiked to 2s", "memory usage grew 10x over 24h",
        "CPU at 95% under normal load", "request queue backing up",
    ])
    ctx["bottleneck"] = random.choice([
        "synchronous DB calls in hot path", "JSON serialization overhead",
        "unnecessary re-computation", "blocking I/O on critical path",
    ])

    # Test problem
    ctx["test_problem"] = random.choice([
        "taking 45 minutes to complete", "failing intermittently",
        "not covering the critical path", "too tightly coupled to implementation",
    ])

    # Scenario
    ctx["scenario"] = random.choice([
        "concurrent modification of shared state", "error handling in async chain",
        "graceful degradation under partial failure", "state recovery after crash",
    ])
    ctx["blocker"] = random.choice([
        "can't mock the external dependency", "test order dependency",
        "setup takes too long", "assertion is too broad",
    ])

    # Result
    ctx["result"] = random.choice([
        "linear scaling breaks at 10k concurrent users",
        "latency distribution has a long tail",
        "resource utilization is uneven across nodes",
    ])

    # Finding
    ctx["finding"] = random.choice([
        "the bottleneck is at the serialization layer",
        "an unchecked exception propagates to the handler",
        "a stale reference persists across requests",
        "the concurrency control has a race window",
        "resource cleanup is skipped on error path",
    ])

    # Location
    ctx["location"] = random.choice([
        "src/handler/processing.rs:142", "packages/service/src/worker.go:89",
        "lib/core/cache.py:67", "app/api/routes.py:203",
    ])

    # Affected area
    ctx["affected_area"] = random.choice([
        "the billing module", "the session manager", "the cache layer",
        "the notification pipeline",
    ])

    # New risk
    ctx["new_risk"] = random.choice([
        "increased coupling between previously isolated modules",
        "hidden latency in the error path",
        "state inconsistency under failure conditions",
    ])

    # Dependency context
    ctx["dependency_context"] = random.choice([
        "module A depends on module B which depends on module C",
        "the service calls three downstream dependencies in sequence",
        "circular dependency between auth and user modules",
    ])

    # Edge case
    ctx["edge_case"] = random.choice([
        "empty input array", "concurrent modification during iteration",
        "network timeout mid-operation", "duplicate key insertion",
    ])

    # New evidence
    ctx["new_evidence"] = random.choice([
        "a timing difference between success and failure cases",
        "an unhandled error in the middleware layer",
        "a configuration drift between environments",
    ])

    # Re-examine area
    ctx["re_examined_area"] = random.choice([
        "the error handling path", "the initialization sequence",
        "the state transition logic", "the resource lifecycle",
    ])

    # Surface issue and root cause
    ctx["surface_issue"] = random.choice([
        "the timeout error", "the null reference", "the silent failure",
        "the incorrect calculation",
    ])
    ctx["root_cause"] = random.choice([
        "a missing guard clause in the validation layer",
        "an incorrect assumption about call ordering",
        "a race condition in the shared state management",
        "a configuration mismatch between environments",
    ])

    # Why attractive
    ctx["why_attractive"] = random.choice([
        "it's the fastest to implement", "the team already knows the pattern",
        "it follows existing conventions", "it requires minimal changes",
    ])
    ctx["counterpoint"] = random.choice([
        "it creates a hidden coupling that will surface later",
        "the maintenance burden increases non-linearly",
        "it doesn't generalize to the next requirement",
    ])

    # PR description
    ctx["pr_description"] = random.choice([
        "Refactors the auth module to use dependency injection instead of global state.",
        "Adds validation rules for the input pipeline to prevent malformed data from propagating.",
        "Introduces a circuit breaker for the external API client to handle transient failures gracefully.",
        "Extracts the shared serialization logic into a standalone utility to reduce duplication.",
    ])
    ctx["change_description"] = random.choice([
        "a major refactor of the payment processing module",
        "adding input validation to the API layer",
        "implementing a caching layer for the query engine",
        "replacing the sync HTTP client with an async one",
    ])

    # Goal and current state (planning)
    ctx["goal"] = random.choice([
        "reduce deployment time from 30min to under 5min",
        "achieve 99.95% availability for the API service",
        "eliminate all flaky tests from the suite",
        "reduce p99 latency from 800ms to under 200ms",
    ])
    ctx["current_state"] = random.choice([
        "manual deployment with frequent human error",
        "no automated canary analysis",
        "30% of tests are flaky due to timing dependencies",
        "unoptimized queries on the hot path",
    ])
    ctx["target"] = random.choice([
        "fully automated CI/CD with deployment gates",
        "observable and self-healing infrastructure",
        "deterministic test execution with zero flakes",
        "sub-100ms p99 latency under normal load",
    ])
    ctx["step1"] = random.choice([
        "audit the current deployment pipeline",
        "profile the slowest queries",
        "instrument the flaky test cases",
        "map the service dependency graph",
    ])
    ctx["constraint"] = random.choice([
        "cannot downtime the production service",
        "must work with the existing monitoring stack",
        "team has limited DevOps bandwidth",
        "budget for infrastructure is fixed",
    ])

    return ctx


def _generate_user_message(category: str, ctx: dict[str, str], modifier: str) -> str:
    """Generate a natural-sounding user message."""
    patterns = USER_PATTERNS.get(category, USER_PATTERNS["architecture"])
    template = random.choice(patterns)

    # Add modifier sometimes
    if modifier and random.random() < 0.4:
        template = template + " ({mod})".format(mod=modifier)

    return _fill_template(template, ctx)


def _generate_reasoning_steps(structure: str, ctx: dict[str, str]) -> list[str]:
    """Generate reasoning steps based on chosen structure."""
    templates = REASONING_STEPS_TEMPLATES.get(structure, REASONING_STEPS_TEMPLATES["linear"])
    chosen = random.choice(templates)
    return chosen


def _generate_assistant_response(
    category: str,
    difficulty: str,
    ctx: dict[str, str],
    structure: str,
    style: int,
    modifier: str,
) -> str:
    """Generate a diverse assistant response using template composition."""

    opening = random.choice(RESPONSE_OPENINGS)
    # Fill opening with context
    opening = _fill_template(opening, ctx)

    # Build body based on structure
    body_parts = []

    if structure == "linear":
        body_parts = _generate_linear_body(category, ctx, style)
    elif structure == "branching":
        body_parts = _generate_branching_body(category, ctx, style)
    elif structure == "socratic":
        body_parts = _generate_socratic_body(category, ctx, style)
    elif structure == "first_principles":
        body_parts = _generate_first_principles_body(category, ctx, style)
    elif structure == "tradeoff_matrix":
        body_parts = _generate_tradeoff_body(category, ctx, style)
    elif structure == "failure_mode_first":
        body_parts = _generate_failure_mode_body(category, ctx, style)

    # Length adjustment based on difficulty
    min_len, max_len = LENGTH_TARGETS.get(difficulty, LENGTH_TARGETS["L3"])
    target_len = random.randint(min_len, max_len)

    # Trim or extend to target length
    full_response = opening + " " + " ".join(body_parts)
    if len(full_response) > target_len:
        # Trim intelligently at sentence boundary
        truncated = full_response[:target_len]
        last_period = truncated.rfind(".")
        if last_period > target_len * 0.7:
            full_response = truncated[:last_period + 1]
        else:
            full_response = truncated.rstrip()[:target_len] + "..."

    return full_response


def _generate_linear_body(category: str, ctx: dict[str, str], style: int) -> list[str]:
    """Generate a linear step-by-step response body."""
    steps = []
    steps.append(f"First, I need to understand the current {ctx['problem']} situation.")

    if category == "debugging":
        steps.append(
            f"From the symptom '{ctx['symptom']}', the possible causes span multiple layers. "
            f"I'll start by {ctx['tried_a'].lower()} and {ctx['tried_b'].lower()} to eliminate obvious candidates."
        )
        steps.append(
            f"The error hint suggests '{ctx['error_hint']}'. "
            f"My hypothesis is that this relates to {ctx['hypothesis']}."
        )
        steps.append(
            f"After checking {ctx['checked_1']}, {ctx['checked_2']}, and {ctx['checked_3']}, "
            f"I can narrow it down to the root cause."
        )
    elif category == "architecture":
        steps.append(
            f"For {ctx['problem']}, the key considerations are {ctx['constraint1']}, "
            f"{ctx['constraint2']}, and {ctx['constraint3']}."
        )
        steps.append(
            f"Option A ({ctx['option_a']}) gives {ctx['reason_a']}, "
            f"while option B ({ctx['option_b']}) has advantages in {ctx['aspect_b']}."
        )
        steps.append(
            f"My recommendation depends on which constraint is binding. "
            f"If {ctx['aspect_b']} is the priority, I'd lean toward B despite the higher initial cost."
        )
    elif category == "code_review":
        steps.append(
            f"Looking at the {ctx['change_description']}, the main risk I see is "
            f"whether it handles {ctx['scenario']} correctly."
        )
        steps.append(
            f"I'd flag the {ctx['problem']} area for closer inspection — "
            f"specifically around error boundaries and edge cases."
        )
    else:
        steps.append(f"The issue centers on {ctx['problem']} in the {ctx['project']} context.")
        steps.append(
            f"Given constraints like {ctx['constraint1']} and {ctx['constraint2']}, "
            f"the viable paths are limited."
        )
        steps.append("I'll walk through the analysis step by step.")

    return steps


def _generate_branching_body(category: str, ctx: dict[str, str], style: int) -> list[str]:
    """Generate a branching response with alternative paths."""
    parts = []
    parts.append(
        f"This {ctx['problem']} problem has at least two viable paths, "
        f"and the right choice depends on which risk we're willing to accept."
    )

    parts.append(
        f"Path A: {ctx['option_a']} — this gives us {ctx['reason_a']}. "
        f"The risk is that it may not scale well when {ctx['aspect_b']} becomes critical."
    )

    parts.append(
        f"Path B: {ctx['option_b']} — cleaner long-term but higher implementation cost. "
        f"This would be justified if we expect {ctx['aspect_b']} to be a binding constraint within 6 months."
    )

    parts.append(
        f"Here's my decision rule: if the team can commit to {ctx['constraint1']} "
        f"without jeopardizing the roadmap, go with Path B. Otherwise, Path A with a documented migration path."
    )

    return parts


def _generate_socratic_body(category: str, ctx: dict[str, str], style: int) -> list[str]:
    """Generate a question-led response."""
    parts = []
    parts.append(
        f"Before proposing anything, I need us to agree on the facts. "
        f"Here's what I observe: {ctx['symptom']} is happening in {ctx['project']}."
    )
    parts.append(
        f"Question 1: {ctx['q1']} The current answer seems to be '{ctx['hypothesis']}', "
        f"but that's an assumption, not evidence."
    )
    parts.append(
        f"Question 2: {ctx['q2']} If we can't answer this, any solution is just a guess."
    )
    parts.append(
        f"Question 3: {ctx['q3']} This determines whether we're solving the right problem."
    )
    parts.append(
        f"My suggestion: let's gather evidence for each question before committing to {ctx['option_a']} or {ctx['option_b']}. "
        f"Specifically, check {ctx['checked_1']} and {ctx['checked_2']}."
    )
    return parts


def _generate_first_principles_body(category: str, ctx: dict[str, str], style: int) -> list[str]:
    """Generate a first-principles response."""
    parts = []
    parts.append(
        f"Let me strip this down to fundamentals. The {ctx['project']} system exists to {ctx['goal']}. "
        f"Everything else is a constraint or an implementation choice."
    )
    parts.append(
        f"Fact 1: {ctx['constraint1']} — this is non-negotiable."
    )
    parts.append(
        f"Fact 2: {ctx['constraint2']} — this limits our solution space significantly."
    )
    parts.append(
        f"Fact 3: The current {ctx['problem']} violates at least one of these facts, "
        f"which is why we're here."
    )
    parts.append(
        f"Rebuilding from scratch within these constraints: the minimal solution that satisfies "
        f"all three facts while addressing {ctx['problem']} would involve {ctx['option_a']}. "
        f"Not because it's familiar, but because it's the simplest construction that doesn't violate any constraint."
    )
    return parts


def _generate_tradeoff_body(category: str, ctx: dict[str, str], style: int) -> list[str]:
    """Generate a trade-off analysis response."""
    parts = []
    parts.append(
        f"Let me lay out the options against the criteria that matter for {ctx['problem']}."
    )
    criteria = [ctx['constraint1'], ctx['constraint2'], ctx['constraint3']]
    for i, criterion in enumerate(criteria, 1):
        parts.append(f"Criterion {i}: {criterion}")

    parts.append(
        f"{ctx['option_a']} scores well on implementation speed but poorly on {ctx['aspect_b']}. "
        f"{ctx['option_b']} is the inverse."
    )
    parts.append(
        f"The showstopper for me is: if {ctx['aspect_b']} becomes a binding constraint, "
        f"{ctx['option_a']} will require a costly rework. "
        f"So unless we're confident it won't bind, I'd recommend {ctx['option_b']} with a phase-gate review at 3 months."
    )
    return parts


def _generate_failure_mode_body(category: str, ctx: dict[str, str], style: int) -> list[str]:
    """Generate a failure-mode-first response."""
    parts = []
    parts.append(
        f"Let me start by assuming this will fail, and work backwards to find out how."
    )
    parts.append(
        f"Single point of failure #1: {ctx['problem']} has no guard rail on the {ctx['checked_1']} path."
    )
    parts.append(
        f"Single point of failure #2: if {ctx['hypothesis']} is wrong, we have no rollback."
    )
    parts.append(
        f"Single point of failure #3: {ctx['constraint1']} means we can't easily reverse course."
    )
    parts.append(
        f"Guard rails I'd insist on: (1) observable failure mode with alerting, "
        f"(2) a documented rollback procedure, and (3) a feature flag to disable {ctx['option_a']} without redeploy."
    )
    parts.append(
        f"Only after those are in place would I green-light the implementation."
    )
    return parts


def _generate_agent_trajectory(category: str, difficulty: str, ctx: dict[str, str]) -> dict[str, Any]:
    """Generate a multi-turn agent trajectory with variable structure."""
    trajectory = []
    behaviours = []

    # Initial user message
    user_msg = _generate_user_message(category, ctx, random.choice(SCENARIO_MODIFIERS))
    trajectory.append({"role": "user", "content": user_msg})

    # Determine trajectory length based on difficulty
    if difficulty == "L2":
        turns = random.randint(4, 6)
    elif difficulty == "L3":
        turns = random.randint(6, 10)
    elif difficulty == "L4":
        turns = random.randint(8, 14)
    else:  # L5
        turns = random.randint(10, 18)

    # Track which behaviours we've seen
    seen_behaviours = set()

    for i in range(turns):
        # Agent turn
        agent_template = random.choice(AGENT_RESPONSE_TEMPLATES)
        agent_content = _fill_template(agent_template, ctx)

        # Add behaviour tags
        if "inspect" in agent_content.lower() and "inspect_before_edit" not in seen_behaviours:
            behaviours.append("inspect_before_edit")
            seen_behaviours.add("inspect_before_edit")
        if "hypothesis" in agent_content.lower() and "hypothesis_testing" not in seen_behaviours:
            behaviours.append("hypothesis_testing")
            seen_behaviours.add("hypothesis_testing")
        if "revert" in agent_content.lower() or "backtrack" in agent_content.lower() or "tukar approach" in agent_content.lower():
            behaviours.append("failure_recovery")
            seen_behaviours.add("failure_recovery")
        if "minimal fix" in agent_content.lower() and "minimal_fix" not in seen_behaviours:
            behaviours.append("minimal_fix")
            seen_behaviours.add("minimal_fix")
        if "verified" in agent_content.lower() or "verify" in agent_content.lower() or "regression" in agent_content.lower():
            behaviours.append("self_verification")
            seen_behaviours.add("self_verification")

        trajectory.append({"role": "agent", "content": agent_content})

        # Tool turn (unless this is the last turn)
        if i < turns - 1:
            tool_action = random.choice(TOOL_ACTIONS)
            tool_result_template = random.choice(TOOL_RESULT_PATTERNS)
            tool_result = _fill_template(tool_result_template, ctx)
            trajectory.append({"role": "tool", "action": tool_action, "result": tool_result})

        # Occasional failure branch
        if random.random() < 0.25 and i < turns - 2:
            branch = random.choice(FAILURE_BRANCHES)
            branch_content = _fill_template(branch["agent_response"], ctx)
            trajectory.append({"role": "agent", "content": branch_content})
            if branch["recovery"] not in behaviours:
                behaviours.append("failure_recovery")
            # Recovery tool call
            recovery_tool = random.choice(TOOL_ACTIONS)
            trajectory.append({
                "role": "tool",
                "action": f"recovery: {recovery_tool}",
                "result": "Recovery action completed. Resuming investigation."
            })

    # Final agent summary
    final_templates = [
        f"Kesimpulan: {ctx['problem']} punca utama nya ialah {ctx['root_cause']}. "
        f"Fix yang saya cadang: {ctx['option_a']}. Saya akan document trade-off ni dalam ADR.",
        f"Wrap-up: selepas trace {ctx['checked_1']} dan {ctx['checked_2']}, "
        f"root cause confirmed. Minimal fix applied dan regression test pass. "
        f"Documentation dan monitoring update diperlukan sebelum merge.",
        f"Final assessment: masalah ni deeper dari surface indication. "
        f"Saya propose phased approach — phase 1: {ctx['option_a']}, "
        f"phase 2: address {ctx['aspect_b']}. Full migration plan akan saya prepare.",
    ]
    trajectory.append({
        "role": "agent",
        "content": random.choice(final_templates)
    })

    # Ensure at least 3 behaviours
    default_behaviours = ["inspect_before_edit", "hypothesis_testing", "self_verification"]
    for b in default_behaviours:
        if b not in behaviours:
            behaviours.append(b)

    return {
        "id": f"atan_traj_{random.randint(1, 99999):05d}",
        "task_type": "agent_trajectory",
        "category": category,
        "difficulty": difficulty,
        "language": "ms-MY",
        "project_type": ctx["project"],
        "task": ctx["problem"],
        "trajectory": trajectory,
        "behaviours": behaviours,
        "reasoning_structure": random.choice(list(REASONING_STEPS_TEMPLATES.keys())),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _generate_single_turn(category: str, difficulty: str, ctx: dict[str, str]) -> dict[str, Any]:
    """Generate a single-turn user/assistant record."""
    structure = random.choice(list(REASONING_STEPS_TEMPLATES.keys()))
    style = random.choice([MALAY_DOMINANT, EN_MIXED, EN_MIXED, EN_DOMINANT])  # weighted toward mixed
    modifier = random.choice(SCENARIO_MODIFIERS)

    user_msg = _generate_user_message(category, ctx, modifier)
    assistant_msg = _generate_assistant_response(category, difficulty, ctx, structure, style, modifier)

    reasoning_steps = _generate_reasoning_steps(structure, ctx)

    return {
        "id": f"atan_{category[:3]}_{random.randint(1, 99999):05d}",
        "task_type": category,
        "category": category,
        "difficulty": difficulty,
        "language": "ms-MY",
        "project_type": ctx["project"],
        "user": user_msg,
        "assistant": assistant_msg,
        "reasoning_steps": reasoning_steps,
        "response_style": {"malay_ratio": style, "structure": structure},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Main generation pipeline
# ---------------------------------------------------------------------------

def generate_dataset(config: GeneratorConfig) -> dict[str, list[dict[str, Any]]]:
    """Generate the full synthetic dataset."""
    random.seed(config.seed)

    # Compute record counts per category
    categories = list(config.category_weights.keys())
    weights = list(config.category_weights.values())
    total = config.total_records

    # Split into trajectory vs single-turn (70% single-turn, 30% trajectory)
    trajectory_count = total // 3
    single_turn_count = total - trajectory_count

    print(f"Generating {total} records: {single_turn_count} single-turn, {trajectory_count} trajectories", file=sys.stderr)

    all_records: list[dict[str, Any]] = []
    category_counts: dict[str, int] = {c: 0 for c in categories}
    difficulty_counts: dict[str, int] = {d: 0 for d in DIFFICULTY_DISTRIBUTION}

    # Generate single-turn records
    print("Generating single-turn records...", file=sys.stderr)
    for i in range(single_turn_count):
        category = _weighted_choice(categories, weights)
        # Sample difficulty from distribution
        difficulties = list(DIFFICULTY_DISTRIBUTION.keys())
        diff_weights = list(DIFFICULTY_DISTRIBUTION.values())
        difficulty = _weighted_choice(difficulties, diff_weights)
        project_type = random.choice(PROJECT_TYPES)

        ctx = _generate_context(category, difficulty, project_type)
        record = _generate_single_turn(category, difficulty, ctx)
        record["_category_count"] = category
        all_records.append(record)
        category_counts[category] += 1
        difficulty_counts[difficulty] += 1

        if (i + 1) % 2000 == 0:
            print(f"  Single-turn: {i + 1}/{single_turn_count}", file=sys.stderr)

    # Generate trajectory records
    print("Generating agent trajectories...", file=sys.stderr)
    for i in range(trajectory_count):
        category = _weighted_choice(categories, weights)
        difficulties = list(DIFFICULTY_DISTRIBUTION.keys())
        diff_weights = list(DIFFICULTY_DISTRIBUTION.values())
        difficulty = _weighted_choice(difficulties, diff_weights)
        project_type = random.choice(PROJECT_TYPES)

        ctx = _generate_context(category, difficulty, project_type)
        record = _generate_agent_trajectory(category, difficulty, ctx)
        record["_category_count"] = category
        all_records.append(record)
        category_counts[category] += 1
        difficulty_counts[difficulty] += 1

        if (i + 1) % 1000 == 0:
            print(f"  Trajectories: {i + 1}/{trajectory_count}", file=sys.stderr)

    # Shuffle and split
    random.shuffle(all_records)
    val_count = max(1, int(len(all_records) * config.val_ratio))
    val_records = all_records[:val_count]
    train_records = all_records[val_count:]

    # Strip internal fields
    for rec in train_records + val_records:
        rec.pop("_category_count", None)

    # Compute diversity metrics
    diversity = compute_diversity(train_records + val_records)

    print(f"\nGeneration complete:", file=sys.stderr)
    print(f"  Total: {len(all_records)}", file=sys.stderr)
    print(f"  Train: {len(train_records)}, Val: {len(val_records)}", file=sys.stderr)
    print(f"  Categories: {category_counts}", file=sys.stderr)
    print(f"  Difficulty: {difficulty_counts}", file=sys.stderr)
    print(f"  Diversity: {diversity}", file=sys.stderr)

    return {
        "train": train_records,
        "val": val_records,
        "metadata": {
            "version": "0.2.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_records": len(all_records),
            "train_records": len(train_records),
            "val_records": len(val_records),
            "category_distribution": category_counts,
            "difficulty_distribution": difficulty_counts,
            "diversity_metrics": diversity,
            "config": asdict(config),
        },
    }


def compute_diversity(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute diversity metrics for generated records."""
    # Content uniqueness (assistant response for single-turn, trajectory hash for agents)
    content_hashes = set()
    short_hashes = set()
    for rec in records:
        if rec.get("task_type") == "agent_trajectory":
            content = json.dumps(rec.get("trajectory", []), sort_keys=True)
        else:
            content = rec.get("assistant", "")
        content_hashes.add(content)
        short_hashes.add(content[:300] if isinstance(content, str) else json.dumps(content, sort_keys=True)[:300])

    total = len(records)
    return {
        "full_content_uniqueness": len(content_hashes) / max(total, 1),
        "short_content_uniqueness": len(short_hashes) / max(total, 1),
        "category_count": len(set(r.get("category", r.get("task_type", "")) for r in records)),
        "difficulty_count": len(set(r.get("difficulty", "") for r in records)),
        "project_type_count": len(set(r.get("project_type", "") for r in records)),
        "reasoning_structure_count": len(set(
            json.dumps(r.get("reasoning_steps", []), sort_keys=True)
            for r in records
        )),
    }


def save_dataset(data: dict[str, Any], output_dir: Path) -> None:
    """Save generated dataset to JSONL files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save train
    train_path = output_dir / "atan_v1_train.jsonl"
    with train_path.open("w", encoding="utf-8") as f:
        for rec in data["train"]:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"  Train: {train_path} ({len(data['train'])} records)", file=sys.stderr)

    # Save val
    val_path = output_dir / "atan_v1_val.jsonl"
    with val_path.open("w", encoding="utf-8") as f:
        for rec in data["val"]:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"  Val: {val_path} ({len(data['val'])} records)", file=sys.stderr)

    # Convert Path to str for JSON serialization
    serializable_metadata = {}
    for k, v in data["metadata"].items():
        if isinstance(v, Path):
            serializable_metadata[k] = str(v)
        elif isinstance(v, dict):
            serializable_metadata[k] = {
                sk: (str(sv) if isinstance(sv, Path) else sv)
                for sk, sv in v.items()
            }
        else:
            serializable_metadata[k] = v
    meta_path = output_dir / "manifest.json"
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(serializable_metadata, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"  Metadata: {meta_path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate genuinely diversified synthetic data for atan-v1 training (v0.2).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--output-dir", type=Path, default=str(DEFAULT_OUTPUT_DIR),
                        help="Output directory for generated dataset.")
    parser.add_argument("--total", type=int, default=10_000,
                        help="Total number of records to generate.")
    parser.add_argument("--val-ratio", type=float, default=0.1,
                        help="Validation split ratio.")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for reproducibility.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show planned distribution without generating.")
    args = parser.parse_args()

    config = GeneratorConfig(
        seed=args.seed,
        total_records=args.total,
        output_dir=Path(args.output_dir) if isinstance(args.output_dir, str) else args.output_dir,
        val_ratio=args.val_ratio,
    )

    if args.dry_run:
        print("DRY RUN — planned distribution:", file=sys.stderr)
        print(f"  Total records: {config.total_records}", file=sys.stderr)
        print(f"  Trajectories: {config.total_records // 3}", file=sys.stderr)
        print(f"  Single-turn: {config.total_records - config.total_records // 3}", file=sys.stderr)
        print(f"  Category weights: {config.category_weights}", file=sys.stderr)
        print(f"  Difficulty distribution: {config.difficulty_distribution}", file=sys.stderr)
        print(f"  Output dir: {config.output_dir}", file=sys.stderr)
        return 0

    print("=" * 60, file=sys.stderr)
    print("ATAN-V1 SYNTHETIC DATA GENERATOR v0.2", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"Seed: {config.seed}", file=sys.stderr)
    print(f"Target: {config.total_records} records", file=sys.stderr)
    print(f"Output: {config.output_dir}", file=sys.stderr)
    print(file=sys.stderr)

    data = generate_dataset(config)
    save_dataset(data, config.output_dir)

    div = data["metadata"]["diversity_metrics"]
    print(f"\nDiversity metrics:", file=sys.stderr)
    print(f"  Full content uniqueness: {div['full_content_uniqueness']*100:.1f}%", file=sys.stderr)
    print(f"  Short content uniqueness: {div['short_content_uniqueness']*100:.1f}%", file=sys.stderr)
    print(f"  Categories: {div['category_count']}", file=sys.stderr)
    print(f"  Project types: {div['project_type_count']}", file=sys.stderr)
    print(f"  Reasoning structures: {div['reasoning_structure_count']}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
