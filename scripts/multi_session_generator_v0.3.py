#!/usr/bin/env python3
"""
multi_session_generator_v0.3.py — Multi-session + dialogue trajectory generator for atan-v1.

Architects two trajectory types on a shared state framework:

  Type A — Multi-session project continuation:
    Session 1: Plan → Inspect → Implement Feature X → Save state → Handoff
    Session 2: Resume from handoff → Continue Feature X → Hit blocker → Fix → Handoff
    Session 3: Resume → Complete Feature X → Integration test → Verify → Done

  Type B — Multi-turn debate/negotiation dialogue (Priority 2 plug-in):
    User proposes approach → Model pushes back → User argues → Model adapts
    → Alternative proposed → Model evaluates → Mutual agreement → Plan

Both types share:
  - ProjectContext: repo state, architecture, ongoing work
  - SessionState: what was done, what's pending, open questions
  - Turn structure: user ↔ agent ↔ (optional user pushback) ↔ agent

Usage:
  python scripts/multi_session_generator_v0.3.py \\
      --output-dir model-eval-finetune/datasets/sft/multi_session_v0.3/ \\
      --total 5000 --seed 42
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ATLAS_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ATLAS_ROOT / "experiments" / "multi_session_v0.3"

# Language mixing configuration — controls BM vs EN ratio in generated text
# Target: >= 0.35 Malay ratio (v0.2 reference is ~0.46)
MALAY_MIX_LEVEL = 0.45  # 45% Malay markers in generated content


ATAN_V1_SYSTEM_PROMPT = (
    "Anda adalah Atan, seorang senior software engineer dan architecture consultant "
    "dari Malaysia. Anda mempunyai pengalaman luas dalam software engineering, "
    "system design, debugging, code review, dan agentic workflows.\n\n"
    "Gaya komunikasi:\n"
    "- Boleh bercakap dalam Bahasa Melayu atau English, atau mix mengikut konteks\n"
    "- Technical terms kekal dalam English (code, API, architecture, etc.)\n"
    "- Natural, professional, like talking to a senior colleague\n"
    "- Jangan terlalu formal atau sound like AI chatbot\n\n"
    "Prinsip kerja:\n"
    "- Fahami full context sebelum buat sebarang perubahan\n"
    "- Consider trade-offs dan impact pada architecture\n"
    "- Challenge bad ideas secara profesional — jangan just agree\n"
    "- Explain reasoning dengan jelas, bukan just give answer\n"
    "- Jika approach user ada masalah, tunjukkan alternatives + pros/cons\n\n"
    "Agentic workflow: understand → inspect → plan → execute → test → review → verify\n"
    "Jangan skip step. Verify setiap perubahan sebelum conclude."
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ProjectContext:
    """The project being worked on — shared state across sessions."""
    name: str
    language: str
    architecture: str  # e.g. "monolith", "microservices", "serverless"
    size: str  # e.g. "small (5k LOC)", "medium (50k LOC)", "large (200k LOC)"
    domain: str  # e.g. "e-commerce", "fintech", "healthcare", "social"
    existing_modules: list[str]
    known_issues: list[str]
    ongoing_features: list[str]
    tech_stack: list[str]
    constraints: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ProjectContext":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class SessionState:
    """What happened in a session and what carries forward."""
    session_id: int
    objective: str
    plan: list[str]
    actions_taken: list[str]
    code_changes: list[str]  # summary of what was changed
    tests_added: list[str]
    blockers_encountered: list[str]
    blockers_resolved: list[str]
    open_questions: list[str]
    remaining_work: list[str]
    state_at_end: str  # human-readable summary
    confidence: str  # "high", "medium", "low" — how confident we are about next step

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SessionState":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class DialogueTurn:
    """A single turn in a multi-turn debate/negotiation."""
    role: str  # "user" or "agent"
    content: str
    intent: str  # e.g. "propose", "challenge", "justify", " concede", "revise", "confirm"
    evidence: list[str] | None = None  # specific evidence cited

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DialogueTurn":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class MultiSessionTrajectory:
    """A complete multi-session project trajectory."""
    id: str
    task_type: str  # "multi_session_project"
    category: str
    difficulty: str
    language: str
    project: ProjectContext
    sessions: list[SessionState]
    total_sessions: int
    final_outcome: str
    behaviours: list[str]
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["project"] = self.project.to_dict()
        d["sessions"] = [s.to_dict() for s in self.sessions]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MultiSessionTrajectory":
        d = d.copy()
        d["project"] = ProjectContext.from_dict(d["project"])
        d["sessions"] = [SessionState.from_dict(s) for s in d["sessions"]]
        return cls(**d)


@dataclass
class MultiTurnDialogue:
    """A complete multi-turn debate/negotiation dialogue."""
    id: str
    task_type: str  # "multi_turn_dialogue"
    category: str
    difficulty: str
    language: str
    project_context: str  # brief project description
    turns: list[DialogueTurn]
    resolution: str  # how the discussion ended
    resolution_type: str  # "agreed", "compromise", "deferred", "user_convinced", "agent_convinced"
    behaviours: list[str]
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["turns"] = [t.to_dict() for t in self.turns]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MultiTurnDialogue":
        d = d.copy()
        d["turns"] = [DialogueTurn.from_dict(t) for t in d["turns"]]
        return cls(**d)


# ---------------------------------------------------------------------------
# Project context generation
# ---------------------------------------------------------------------------

PROJECT_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "ecommerce-platform",
        "language": "TypeScript",
        "architecture": "modular monolith with service boundaries",
        "size": "medium (80k LOC)",
        "domain": "e-commerce",
        "existing_modules": ["catalog", "cart", "checkout", "payment", "inventory", "user-auth", "notification"],
        "known_issues": ["cart session lost on page refresh", "payment webhook retry logic race condition", "inventory check has N+1 query"],
        "ongoing_features": ["adding real-time stock updates via WebSocket", "migrating payment from sync to async processing"],
        "tech_stack": ["Node.js", "PostgreSQL", "Redis", "GraphQL", "Docker", "Kubernetes"],
        "constraints": ["must maintain 99.9% uptime during migration", "PCI-DSS compliance required for payment changes", "zero-downtime deploy mandatory"],
    },
    {
        "name": "fintech-core-banking",
        "language": "Java",
        "architecture": "event-driven microservices",
        "size": "large (250k LOC)",
        "domain": "fintech",
        "existing_modules": ["account-service", "transaction-service", "ledger-service", "kyc-service", "fraud-detection", "notification-service", "reporting-service"],
        "known_issues": ["transactionId not deterministic across services", "ledger double-entry validation skipped in 30% of paths", "fraud detection model retraining causes 2s latency spike"],
        "ongoing_features": ["implementing real-time fraud scoring", "adding multi-currency support to ledger"],
        "tech_stack": ["Java 21", "Kafka", "PostgreSQL", "Quarkus", "Kubernetes", "Prometheus"],
        "constraints": ["financial data audit trail required for 7 years", "regulatory compliance review before any schema change", "transaction ordering must be preserved"],
    },
    {
        "name": "healthcare-patient-portal",
        "language": "Python",
        "architecture": "frontend SPA + backend API",
        "size": "medium (60k LOC)",
        "domain": "healthcare",
        "existing_modules": ["patient-dashboard", "appointment-scheduler", "prescription-manager", "lab-results", "billing", "auth"],
        "known_issues": ["appointment conflicts not detected for overlapping time slots", "PDF generation fails for patients with special characters in names", "session timeout too aggressive for elderly users"],
        "ongoing_features": ["adding telemedicine video consultation", "implementing patient-reported outcome surveys"],
        "tech_stack": ["Python/FastAPI", "React", "PostgreSQL", "FHIR API", "AWS", "Redis"],
        "constraints": ["HIPAA compliance required", "audit logging for all patient data access", "system must handle 10x traffic during flu season"],
    },
    {
        "name": "logistics-warehouse-management",
        "language": "Go",
        "architecture": "monolith with plugin architecture",
        "size": "large (180k LOC)",
        "domain": "logistics",
        "existing_modules": ["warehouse-inventory", "shipment-tracking", "picker-routing", "carrier-integration", "label-generation", "returns-processing"],
        "known_issues": ["picker route optimization recalculates every 5 min causing CPU spike", "carrier API rate limits not respected during peak", "returns status stuck in 'processing' for 12% of items"],
        "ongoing_features": ["adding AI-powered demand forecasting", "integrating drone delivery tracking"],
        "tech_stack": ["Go", "ClickHouse", "RabbitMQ", "gRPC", "Docker", "Terraform"],
        "constraints": ["must process 10k shipments/hour during peak", "99.99% availability for shipment tracking API", "carrier integration must be hot-swappable"],
    },
    {
        "name": "social-media-analytics",
        "language": "Rust",
        "architecture": "data pipeline + serving layer",
        "size": "medium (45k LOC)",
        "domain": "media/tech",
        "existing_modules": ["ingestion-pipeline", "stream-processor", "aggregation-engine", "query-service", "dashboard-api", "alert-engine"],
        "known_issues": ["stream processor drops events during backpressure", "aggregation cache invalidation inconsistent across regions", "query latency p99 degrades linearly with dataset size"],
        "ongoing_features": ["adding real-time anomaly detection", "implementing custom metric expressions"],
        "tech_stack": ["Rust", "Apache Flink", "ClickHouse", "Redis", "Kubernetes", "gRPC"],
        "constraints": ["must handle 1M events/sec ingestion", "query results must be consistent within 500ms SLA", "zero data loss guarantee on ingestion"],
    },
    {
        "name": "saas-subscription-platform",
        "language": "Python",
        "architecture": "multi-tenant microservices",
        "size": "large (120k LOC)",
        "domain": "SaaS",
        "existing_modules": ["billing", "subscription-manager", "usage-metering", "tenant-isolation", "webhook-dispatcher", "rate-limiter", "audit-log"],
        "known_issues": ["tenant data leakage between adjacent tenants", "subscription proration incorrect for mid-cycle changes", "webhook retry storm under load"],
        "ongoing_features": ["adding usage-based pricing tier", "implementing self-service portal"],
        "tech_stack": ["Python/FastAPI", "PostgreSQL", "Celery", "Redis", "Docker", "AWS"],
        "constraints": ["strict tenant isolation required", "billing accuracy auditable to the cent", "99.95% uptime SLA with financial penalties"],
    },
    {
        "name": "real-time-collaboration-editor",
        "language": "TypeScript",
        "architecture": "WebSocket-based real-time sync",
        "size": "medium (55k LOC)",
        "domain": "collaboration/tooling",
        "existing_modules": ["document-store", "presence-engine", "conflict-resolver", "operation-queue", "snapshot-service", "undo-redo"],
        "known_issues": ["conflict resolution breaks on simultaneous edits from 3+ users", "document snapshot takes 2s under heavy write load", "presence cursor jumps between users in large docs"],
        "ongoing_features": ["adding rich text formatting", "implementing comment/thread system"],
        "tech_stack": ["TypeScript", "WebSocket", "CRDT", "PostgreSQL", "Redis", "Docker"],
        "constraints": ["conflict-free sync guaranteed under all conditions", "max 100ms latency for presence updates", "offline-first with auto-sync on reconnect"],
    },
    {
        "name": "iot-device-management",
        "language": "Go",
        "architecture": "MQTT-based device telemetry",
        "size": "medium (70k LOC)",
        "domain": "IoT",
        "existing_modules": ["device-registry", "telemetry-ingest", "rule-engine", "alert-manager", "firmware-updater", "geofence-service"],
        "known_issues": ["device firmware update fails silently for 5% of devices", "telemetry ingested out-of-order causing incorrect alerts", "rule engine state corruption on restart"],
        "ongoing_features": ["adding edge computing support", "implementing predictive maintenance"],
        "tech_stack": ["Go", "MQTT", "InfluxDB", "Kafka", "Docker", "Kubernetes"],
        "constraints": ["must handle 100k concurrent device connections", "firmware updates must be rollback-safe", "data retention 1 year for compliance"],
    },
    {
        "name": "marketplace-auction-platform",
        "language": "Java",
        "architecture": "event-sourced microservices",
        "size": "large (200k LOC)",
        "domain": "marketplace",
        "existing_modules": ["auction-engine", "bid-validator", "settlement-service", "escrow-manager", "seller-dashboard", "buyer-app"],
        "known_issues": ["concurrent bids cause duplicate settlement entries", "auction close timing off by 200ms under load", "escrow release triggered before delivery confirmation"],
        "ongoing_features": ["adding live video auction support", "implementing anti-sniping mechanism"],
        "tech_stack": ["Java", "Event Sourcing", "CQRS", "PostgreSQL", "Kafka", "Elasticsearch"],
        "constraints": ["bid integrity must be cryptographically verifiable", "zero double-spend possible", "settlement must complete within 5s of auction close"],
    },
    {
        "name": "developer-ides-backend",
        "language": "Rust",
        "architecture": "language server protocol + LSP",
        "size": "medium (90k LOC)",
        "domain": "developer tools",
        "existing_modules": ["code-completion", "diagnostics-engine", "refactoring-tool", "indexer", "workspace-manager", "lsp-bridge"],
        "known_issues": ["completion suggestions stale after 30s of inactivity", "diagnostics fail on files with non-ASCII characters", "workspace index rebuild takes 45s for large projects"],
        "ongoing_features": ["adding semantic highlighting", "implementing inline error explanations"],
        "tech_stack": ["Rust", "LSP", "Tree-sitter", "SQLite", " wasm"],
        "constraints": ["completion must respond within 50ms", "zero false-positive diagnostics", "memory usage bounded at 500MB for 100k file projects"],
    },
    {
        "name": "video-streaming-cdn",
        "language": "Go",
        "architecture": "edge computing + origin shield",
        "size": "large (300k LOC)",
        "domain": "media streaming",
        "existing_modules": ["ingest-service", "transcoder", "cdn-edge", "origin-shield", "analytics-collector", "drm-manager", "live-stream-processor"],
        "known_issues": ["transcoding queue backlog during peak hours", "DRM license server timeout causes playback failure", "edge cache invalidation delayed by 30s"],
        "ongoing_features": ["adding AV1 codec support", "implementing adaptive bitrate switching"],
        "tech_stack": ["Go", "FFmpeg", "Redis", "Kafka", "Cloudflare", "AWS S3"],
        "constraints": ["99.99% playback success rate", "sub-2s startup latency globally", "support 4K HDR at scale"],
    },
]

CATEGORY_TASKS: dict[str, list[dict[str, str]]] = {
    "multi_session_project": [
        {
            "category": "feature_development",
            "description": "implement a new feature across multiple sessions with evolving requirements",
            "objectives": [
                "Add real-time notification system using WebSocket",
                "Implement user preference management with A/B testing hooks",
                "Build audit logging for all sensitive data access",
                "Add multi-tenant support to existing single-tenant service",
                "Implement dark mode with persistent user preference",
                "Add in-app messaging with read receipts",
                "Build real-time collaborative editing feature",
                "Implement push notification service with FCM/APNs",
                "Add social sharing with deep linking support",
                "Build offline-first sync for mobile clients",
                "Implement role-based access control (RBAC) system",
                "Add real-time presence indicator for online users",
                "Build automated report generation and export",
                "Implement two-factor authentication flow",
                "Add content recommendation engine",
            ],
        },
        {
            "category": "refactor_large_module",
            "description": "refactor a tightly coupled module while maintaining backward compatibility",
            "objectives": [
                "Extract payment processing from monolithic checkout service",
                "Split large authentication module into focused sub-modules",
                "Decouple notification service from user service dependencies",
                "Replace monolithic config loader with hierarchical config system",
                "Migrate legacy ORM queries to repository pattern",
                "Extract shared middleware into independent package",
                "Split large API gateway into focused route handlers",
                "Decouple event bus from concrete message types",
                "Extract template rendering engine into standalone module",
                "Refactor monolithic validation layer into composable validators",
                "Split database connection pool management into separate module",
                "Extract business logic from controller into service layer",
            ],
        },
        {
            "category": "bug_fix_complex",
            "description": "diagnose and fix a complex multi-session bug with intermittent failure",
            "objectives": [
                "Fix intermittent race condition in concurrent order processing",
                "Resolve memory leak in long-running background worker",
                "Fix data corruption during partial failure in batch job",
                "Debug CI-only failure that doesn't reproduce locally",
                "Fix incorrect calculation in pricing engine under edge case",
                "Fix race condition in concurrent WebSocket handler",
                "Resolve intermittent deadlock in database transaction",
                "Debug memory leak in image processing pipeline",
                "Fix incorrect timezone handling across services",
                "Resolve data inconsistency after partial deployment",
                "Fix flaky integration test caused by timing dependency",
                "Debug silent data loss in message queue consumer",
            ],
        },
        {
            "category": "migration",
            "description": "plan and execute a data or architecture migration with rollback strategy",
            "objectives": [
                "Migrate PostgreSQL schema with zero downtime",
                "Migrate from REST to GraphQL for client-facing API",
                "Migrate monolith module to独立 service with feature flags",
                "Migrate auth from session-based to JWT with dual-write period",
                "Migrate data from SQL to document store for flexible schema",
                "Migrate from monolith to event-sourced architecture",
                "Migrate database from PostgreSQL to CockroachDB",
                "Migrate deployment from VM to Kubernetes",
                "Migrate from synchronous to asynchronous processing",
                "Migrate authentication from OAuth1 to OAuth2",
                "Migrate data pipeline from batch to streaming",
                "Migrate from self-hosted to managed service",
            ],
        },
        {
            "category": "performance_optimization",
            "description": "profile, identify bottlenecks, and optimize across multiple iterations",
            "objectives": [
                "Reduce API p99 latency from 800ms to under 200ms",
                "Fix memory growth in long-running worker process",
                "Optimize N+1 query in high-traffic reporting endpoint",
                "Reduce Docker image size by 60% without losing functionality",
                "Improve batch processing throughput by 5x",
                "Reduce database connection pool saturation under load",
                "Optimize Redis cache hit ratio from 60% to 95%",
                "Reduce cold start latency for serverless function from 3s to 500ms",
                "Optimize GraphQL resolver for nested query paths",
                "Reduce WebSocket message processing latency by 50%",
                "Optimize search query performance on large index",
                "Reduce CPU usage during peak traffic by 40%",
            ],
        },
    ],
    "multi_turn_dialogue": [
        {
            "category": "architecture_tradeoff",
            "description": "debate between two valid architecture approaches with genuine trade-offs",
            "patterns": [
                "Event-driven vs synchronous processing for order handling",
                "Monolith vs microservice for new feature module",
                "SQL vs NoSQL for user preference storage",
                "GraphQL vs REST for internal service communication",
                "Custom auth implementation vs third-party identity provider",
                "CQRS vs traditional CRUD for order management",
                "Cache-aside vs write-through for session data",
                "Kubernetes vs serverless for deployment target",
            ],
        },
        {
            "category": "security_review",
            "description": "security review where user proposes solution and model identifies risks",
            "patterns": [
                "Storing JWT in localStorage vs httpOnly cookie",
                "Implementing rate limiting at app layer vs CDN layer",
                "Using regex for input validation vs parameterized queries",
                "Storing secrets in environment variables vs secrets manager",
                "Implementing CORS with wildcard vs specific origins",
                "Using client-side encryption vs server-side encryption",
                "Direct DB connection from worker vs connection pooling",
            ],
        },
        {
            "category": "technical_debt",
            "description": "negotiate technical debt investment vs feature delivery timeline",
            "patterns": [
                "Refactor auth module vs ship new feature by deadline",
                "Add test coverage for legacy module vs fix critical bug",
                "Redesign API versioning strategy vs ship breaking change",
                "Invest in observability infrastructure vs ship user-facing feature",
                "Rewrite integration tests vs manual QA for release",
                "Address dependency vulnerability vs ship time-sensitive feature",
            ],
        },
        {
            "category": "implementation_approach",
            "description": "disagree on implementation approach with evidence-based negotiation",
            "patterns": [
                "Build vs buy decision for authentication system",
                "Build custom search vs integrate Algolia/Elasticsearch",
                "Implement WebSocket for real-time vs polling",
                "Use ORM vs raw SQL for data access layer",
                "Implement feature flags vs environment-specific deployment",
                "Single repository vs monorepo vs polyrepo for new service",
            ],
        },
    ],
}


# ---------------------------------------------------------------------------
# Session generation — builds coherent multi-session narratives
# ---------------------------------------------------------------------------

SESSION_PLAN_TEMPLATES: dict[str, list[list[str]]] = {
    "feature_development": [
        ["inspect existing codebase", "identify integration points", "design data model",
         "implement core logic", "add validation", "write unit tests",
         "implement integration", "run regression tests", "document changes"],
        ["analyze requirements", "identify affected modules", "create migration plan",
         "implement phase 1 (core)", "verify phase 1", "implement phase 2 (integration)",
         "handle edge cases", "add monitoring", "run full test suite"],
        ["review existing patterns", "design extension point", "implement plugin interface",
         "add configuration", "write tests", "integrate with main flow",
         "handle error cases", "performance check", "update documentation"],
    ],
    "refactor_large_module": [
        ["analyze module boundaries", "identify coupling points", "design extraction plan",
         "create new module skeleton", "migrate first subsystem", "verify no regression",
         "migrate second subsystem", "update callers", "remove legacy code", "run full suite"],
        ["profile current performance", "identify hot paths", "design optimization strategy",
         "implement caching layer", "measure improvement", "implement query optimization",
         "add connection pooling", "benchmark results", "document changes"],
        ["map dependency graph", "identify circular dependencies", "design decoupling strategy",
         "extract interface", "implement provider", "update consumers", "remove direct dependencies",
         "add integration tests", "verify behavior unchanged"],
    ],
    "bug_fix_complex": [
        ["reproduce the failure", "collect logs and traces", "identify failure pattern",
         "form hypothesis", "write failing test", "implement fix", "verify test passes",
         "check for related issues", "run regression suite", "document root cause"],
        ["analyze stack traces", "identify resource leak pattern", "add profiling instrumentation",
         "confirm leak source", "implement fix", "verify memory stable",
         "add monitoring alert", "write regression test", "check similar patterns"],
        ["reproduce intermittently", "add detailed logging", "identify race window",
         "analyze lock ordering", "implement fix", "run stress test",
         "verify no regression", "add test coverage for edge case"],
    ],
    "migration": [
        ["analyze current state", "design migration strategy", "create dual-write layer",
         "migrate batch data", "verify data consistency", "switch reads",
         "switch writes", "remove legacy code", "run validation suite"],
        ["document current API surface", "design v2 API", "implement v2 alongside v1",
         "add version negotiation", "migrate clients gradually", "deprecate v1",
         "remove v1 code", "update documentation"],
        ["profile current deployment", "design blue-green strategy", "prepare new environment",
         "deploy blue (new) alongside green (old)", "switch traffic gradually",
         "monitor metrics", "switch fully to blue", "teardown green"],
    ],
    "performance_optimization": [
        ["establish baseline metrics", "profile hot paths", "identify top bottleneck",
         "implement optimization", "measure improvement", "optimize next bottleneck",
         "repeat until target met", "run full regression", "document optimization"],
        ["collect memory profile", "identify leak source", "implement fix",
         "verify leak resolved", "check for similar patterns", "add memory tests",
         "benchmark under load", "set up monitoring alerts"],
        ["analyze query execution plans", "identify N+1 pattern", "implement batching",
         "add query optimization", "measure improvement", "optimize secondary queries",
         "add connection pool tuning", "document findings"],
    ],
}

SESSION_OUTCOME_PATTERNS: dict[str, list[str]] = {
    "feature_development": [
        "Feature implemented dan integrated. User验收 passed dengan edge cases covered.",
        "Core logic done tapi integration testing reveal bug di boundary condition. Need follow-up session.",
        "Implementation complete tetapi performance benchmark show 2x slower than expected. Optimization needed.",
        "Feature works locally tapi CI pipeline fails due to environment difference. Debugging needed.",
        "Code reviewed dan approved. Documentation updated. Ready for deployment after QA sign-off.",
    ],
    "refactor_large_module": [
        "Refactor complete with 100% test coverage. No behavioral regression detected.",
        "First phase done successfully. Second phase hit unexpected coupling — need to revisit design.",
        "Extraction worked but some edge cases in legacy code not covered by tests. Risk of regression.",
        "Refactor complete but CI build time increased by 40%. Need to investigate parallelization.",
        "Partial refactor — core coupling removed but documentation and migration guide still pending.",
    ],
    "bug_fix_complex": [
        "Root cause identified dan fixed. Stress test passes 10x normal load. Regression suite green.",
        "Fix applied tapi intermittent nature means cannot fully verify. Added monitoring alert untuk catch recurrence.",
        "Fixed the primary issue but discovered related bug in adjacent module. Created ticket for follow-up.",
        "Patch works for reproduction case but production trace shows different failure path. Need deeper investigation.",
        "Root cause was configuration drift between environments, not code bug. Applied config fix dan added drift detection.",
    ],
    "migration": [
        "Migration complete dengan zero downtime. Data consistency verified. Rollback plan documented.",
        "Batch migration successful tapi delta between batch and real-time shows 0.01% divergence. Investigation needed.",
        "Blue-green switch done but canary metrics show 5% increase in latency on new environment. Monitoring closely.",
        "API v2 deployed alongside v1. Gradual client migration started. V1 deprecation timeline set at 90 days.",
        "Schema migration applied successfully. Backup restored dari pre-migration snapshot sebagai safety net.",
    ],
    "performance_optimization": [
        "Target reached. P99 latency reduced from 800ms to 150ms. Memory stable under sustained load.",
        "First optimization round gave 40% improvement. Remaining 20% target needs deeper architectural change.",
        "Memory leak fixed. Long-running worker now stable at 24h. Added monitoring untuk early detection.",
        "Query optimization complete. Database CPU dropped from 85% to 45%. Connection pool tuning pending.",
        "Partial optimization achieved. Some queries still slow due to missing index on rarely-used column. Low priority.",
    ],
}


def generate_project_context(template_idx: int, seed: int) -> ProjectContext:
    """Generate a project context from a template with randomized details."""
    random.seed(seed)
    tpl = PROJECT_TEMPLATES[template_idx % len(PROJECT_TEMPLATES)]

    # Randomize some fields for variety
    modules = tpl["existing_modules"].copy()
    random.shuffle(modules)
    issues = tpl["known_issues"].copy()
    random.shuffle(issues)
    ongoing = tpl["ongoing_features"].copy()
    random.shuffle(ongoing)
    constraints = tpl["constraints"].copy()
    random.shuffle(constraints)

    return ProjectContext(
        name=tpl["name"],
        language=tpl["language"],
        architecture=tpl["architecture"],
        size=tpl["size"],
        domain=tpl["domain"],
        existing_modules=modules[:random.randint(4, 6)],
        known_issues=issues[:random.randint(2, 4)],
        ongoing_features=ongoing[:random.randint(1, 2)],
        tech_stack=tpl["tech_stack"],
        constraints=constraints[:random.randint(2, 3)],
    )


def generate_session(
    session_num: int,
    total_sessions: int,
    objective: str,
    plan_template: list[str],
    project: ProjectContext,
    previous_state: SessionState | None,
    seed: int,
) -> SessionState:
    """Generate a single session with coherent state."""
    random.seed(seed)

    # Adjust plan based on whether this is continuing from previous session
    plan = plan_template.copy()
    if previous_state and session_num > 1:
        # Resume from where we left off
        if previous_state.remaining_work:
            plan = [f"resume from: {previous_state.remaining_work[0]}"] + plan[:3]
        if previous_state.open_questions:
            plan.append(f"resolve: {previous_state.open_questions[0]}")
        plan.append("verify previous work still correct")

    # Select actions taken (subset of plan, with variation)
    n_actions = random.randint(max(3, len(plan) // 2), len(plan))
    actions = random.sample(plan, n_actions)

    # Generate code change summaries
    change_templates = [
        f"Modified {random.choice(project.existing_modules)}.py to {actions[0] if actions else 'update logic'}",
        f"Added new module for {objective.split()[:3]}...",
        f"Updated configuration in {random.choice(project.tech_stack[:2])} settings",
        f"Refactored {random.choice(project.existing_modules)} to use new pattern",
        f"Added validation layer for {random.choice(project.known_issues)[:30]}...",
    ]
    code_changes = random.sample(change_templates, min(random.randint(1, 3), len(change_templates)))

    # Tests
    test_templates = [
        f"Added unit test untuk {actions[0] if actions else 'new behavior'}",
        f"Added integration test untuk edge case di {random.choice(project.existing_modules)}",
        f"Added regression test untuk known issue: {project.known_issues[0][:40]}",
    ]
    tests_added = random.sample(test_templates, min(random.randint(1, 2), len(test_templates)))

    # Blockers
    blockers_enc = []
    blockers_res = []
    if random.random() < 0.6:  # 60% chance of encountering blocker
        blocker_templates = [
            f"Unexpected coupling between {random.choice(project.existing_modules)} and legacy code",
            f"Test environment configuration differs from production",
            f"Dependency version conflict dengan {random.choice(project.tech_stack)}",
            f"Rate limit hit when testing against external API",
            f"Existing test suite has flaky test yang block validation",
        ]
        blockers_enc = [random.choice(blocker_templates)]
        if random.random() < 0.7:  # 70% chance of resolving
            blockers_res = [f"Resolved by {'refactoring coupling' if 'coupling' in blockers_enc[0] else 'updating config' if 'configuration' in blockers_enc[0] else 'pinning dependency version'}"]

    # Open questions
    open_qs = []
    if random.random() < 0.4:
        open_qs = [f"Whether {random.choice(project.constraints)[:40]}... affects the implementation"]

    # Remaining work
    remaining = []
    unfinished = [p for p in plan if p not in actions]
    if unfinished and random.random() < 0.5:
        remaining = unfinished[:random.randint(1, min(2, len(unfinished)))]

    # State at end
    if previous_state and session_num > 1:
        state_summary = f"Resume dari Session {session_num - 1}. Lanjutkan {objective}. Previous state: {previous_state.state_at_end[:80]}..."
    else:
        state_summary = f"Session {session_num} selesai. {objective}. Actions: {len(actions)} steps completed."

    confidence = "high"
    if blockers_enc and not blockers_res:
        confidence = "low"
    elif open_qs:
        confidence = "medium"
    elif remaining:
        confidence = "medium"

    return SessionState(
        session_id=session_num,
        objective=objective,
        plan=plan,
        actions_taken=actions,
        code_changes=code_changes,
        tests_added=tests_added,
        blockers_encountered=blockers_enc,
        blockers_resolved=blockers_res,
        open_questions=open_qs,
        remaining_work=remaining,
        state_at_end=state_summary,
        confidence=confidence,
    )


def build_multi_session_trajectory(
    task_def: dict[str, str],
    project: ProjectContext,
    n_sessions: int,
    seed: int,
) -> MultiSessionTrajectory:
    """Build a coherent multi-session trajectory."""
    random.seed(seed)

    category = task_def["category"]
    # Pick a specific objective from the category's objective list
    objectives = task_def.get("objectives", [task_def["description"]])
    objective = random.choice(objectives)

    # Select plan template based on category
    plan_key = category if category in SESSION_PLAN_TEMPLATES else "feature_development"
    plan_templates = SESSION_PLAN_TEMPLATES[plan_key]
    plan_template = random.choice(plan_templates)

    # Select outcome pattern
    outcome_key = category if category in SESSION_OUTCOME_PATTERNS else "feature_development"
    outcome_patterns = SESSION_OUTCOME_PATTERNS[outcome_key]

    sessions = []
    previous_state = None
    for i in range(1, n_sessions + 1):
        s = generate_session(i, n_sessions, objective, plan_template, project, previous_state, seed + i)
        sessions.append(s)
        previous_state = s

    # Final outcome
    if sessions[-1].remaining_work and random.random() < 0.3:
        final_outcome = random.choice([
            f"Session terakhir belum complete. {sessions[-1].remaining_work[0]} masih pending. Need follow-up.",
            f"Feature partially delivered. Core works tapi {sessions[-1].open_questions[0] if sessions[-1].open_questions else 'edge cases'} belum address.",
        ])
    else:
        final_outcome = random.choice(outcome_patterns)

    # Behaviours
    behaviours = ["inspect_before_edit", "hypothesis_testing", "self_verification"]
    if any(s.blockers_encountered for s in sessions):
        behaviours.append("failure_recovery")
    if any(s.blockers_resolved for s in sessions):
        behaviours.append("problem_solving")
    if n_sessions > 2:
        behaviours.append("state_management")
        behaviours.append("incremental_progress")
    if sessions[-1].confidence == "low":
        behaviours.append("cautious_claims")

    return MultiSessionTrajectory(
        id=f"atan_ms_{random.randint(1, 99999):05d}",
        task_type="multi_session_project",
        category=category,
        difficulty=_difficulty_for_task(category, n_sessions),
        language="ms-MY",
        project=project,
        sessions=sessions,
        total_sessions=n_sessions,
        final_outcome=final_outcome,
        behaviours=list(set(behaviours)),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Multi-turn dialogue generation (Priority 2 — plugs into same framework)
# ---------------------------------------------------------------------------

DIALOGUE_PATTERNS: dict[str, list[dict[str, Any]]] = {
    "architecture_tradeoff": [
        {
            "turn_sequence": [
                {"role": "user", "intent": "propose", "template": "Saya nak guna {approach_a} untuk {problem}. Nak tahu opinion anda?"},
                {"role": "agent", "intent": "evaluate", "template": "Saya faham kenapa {approach_a} menarik — {reason_a}. Tapi saya ada beberapa concern tentang {concern_a}. Mari kita compare dengan {approach_b}."},
                {"role": "user", "intent": "challenge", "template": "Tapi {approach_b} lebih complicated. Timeline kita ketat. Kenapa tak boleh just go with {approach_a} je?"},
                {"role": "agent", "intent": "justify", "template": "Faham pasal timeline. Tapi {concern_a} bukan theoretical — ia akan surface bila {trigger_condition}. Kalau kita take shortcut sekarang, migration cost nanti lebih tinggi."},
                {"role": "user", "intent": "negotiate", "template": "Okay tapi macam mana kalau kita buat {hybrid_approach}? Quick win dulu, refactor later."},
                {"role": "agent", "intent": "revise", "template": "Hybrid approach ni actually quite reasonable. We can do {hybrid_approach} as Phase 1, dengan documented migration path ke {full_approach} di Phase 2. Ini bagi quick win tanpa technical debt yang silent."},
                {"role": "user", "intent": "confirm", "template": "Okay sounds good. Let's go with hybrid. What's the first step?"},
                {"role": "agent", "intent": "confirm", "template": "Step 1: Saya akan document the trade-off dalam ADR. Step 2: Implement Phase 1 with clear exit criteria. Step 3: Schedule Phase 2 review setelah 2 sprints."},
            ],
        },
        {
            "turn_sequence": [
                {"role": "user", "intent": "propose", "template": "Kita kena decide pasal {problem} dekat {project}. Saya倾向 {approach_a} sebab {reason_a}, tapi {approach_b} ada kelebihan di {aspect_b}. Mana lebih sesuai?"},
                {"role": "agent", "intent": "evaluate", "template": "Untuk {problem}, dua option ni ada trade-off yang genuine. {approach_a} gives {reason_a} tetapi {concern_a}. {approach_b} pulak {aspect_b} better tapiimplementation cost lebih tinggi."},
                {"role": "user", "intent": "challenge", "template": "Kalau ikut logic anda, kenapa tak terus pilih {approach_b}? {reason_a} pun cukup penting kan?"},
                {"role": "agent", "intent": "justify", "template": "Valid question. Tapi {concern_a} jadi binding constraint bila {trigger_condition}. Kalau kita ignore ni, nanti {consequence}. Oleh itu {approach_a} lebih safe walaupun {aspect_b} kurang optimum."},
                {"role": "user", "intent": "negotiate", "template": "Hmm okay. So basically saya kena accept {concern_a} risk untuk dapat {aspect_b}? Ada middle ground?"},
                {"role": "agent", "intent": "revise", "template": "Ada — {hybrid_approach}. Kita boleh start dengan {approach_a} untuk address {concern_a}, kemudian migrate ke {approach_b} bila {trigger_condition} resolved. Phased approach ni reduce risk sambil tetap capai {aspect_b} long term."},
                {"role": "user", "intent": "confirm", "template": "Phased approach okay. Bila kita boleh start Phase 2?"},
                {"role": "agent", "intent": "confirm", "template": "Phase 2 trigger: bila {trigger_condition} dah address. I'll draft the migration plan dengan clear milestones."},
            ],
        },
        {
            "turn_sequence": [
                {"role": "user", "intent": "propose", "template": "Untuk {problem}, team kita ada dua faction: satu nak {approach_a}, satu nak {approach_b}. Saya tengah conflicted. Pandangan anda?"},
                {"role": "agent", "intent": "evaluate", "template": "This is a classic tradeoff. {approach_a} side is right about {reason_a}, but {approach_b} side is right about {aspect_b}. The question is: which constraint is binding?"},
                {"role": "user", "intent": "challenge", "template": "Tapi kita bukan ada masa untuk perfect solution. kena decide soon. Saya rasa {approach_a} je la, then fix {concern_a} nanti."},
                {"role": "agent", "intent": "justify", "template": "I understand the time pressure. Tapi {concern_a} bukan cosmetic issue — ia akan cause {consequence} dalam {timeframe}. Kalau kita defer, mitigation cost akan {cost_multiplier}x lebih tinggi."},
                {"role": "user", "intent": "negotiate", "template": "Okay kalau macam tu, apa minimum yang kita perlu buat untuk address {concern_a} tanpa sacrifice {reason_a} entirely?"},
                {"role": "agent", "intent": "revise", "template": "Minimum viable: implement {concern_a} guardrail di {approach_a} dengan {minimal_guard}. Ini address the critical risk tanpa full {approach_b} complexity. Then kita monitor dan iterate."},
                {"role": "user", "intent": "confirm", "template": "Got it. Guardrail first, full solution later. Let's document this."},
                {"role": "agent", "intent": "confirm", "template": "Agreed. I'll write the ADR with: context, the tradeoff analysis, our decision (guardrail first), and the review milestone for full solution."},
            ],
        },
    ],
    "security_review": [
        {
            "turn_sequence": [
                {"role": "user", "intent": "propose", "template": "Saya plan nak implement {security_approach} untuk handle {security_problem}. Quick and simple."},
                {"role": "agent", "intent": "challenge", "template": "Hold on — {security_approach} ada several security implications yang perlu kita consider. Specifically, {risk_1} and {risk_2}."},
                {"role": "user", "intent": "dismiss", "template": "Tapi {counter_argument}. Semua orang buat macam ni. Tak perlu over-engineer security."},
                {"role": "agent", "intent": "justify", "template": "Saya tak kata over-engineer. Tapi {specific_risk} is a real attack vector. Recent {related_incident} menunjukkan ini bukan theoretical — attackers memang exploit this pattern."},
                {"role": "user", "intent": "revise", "template": "Okay I see your point. What would you recommend instead?"},
                {"role": "agent", "intent": "propose_alternative", "template": "Instead of {security_approach}, I'd recommend {safer_alternative}. It gives better security posture dengan minimal complexity increase. The key difference is {key_difference}."},
                {"role": "user", "intent": "confirm", "template": "Makes sense. Let's go with {safer_alternative}. Can you outline the implementation steps?"},
                {"role": "agent", "intent": "confirm", "template": "Sure. Steps: 1) {step1} 2) {step2} 3) Add security test untuk {attack_vector}. 4) Code review dengan security focus."},
            ],
        },
        {
            "turn_sequence": [
                {"role": "user", "intent": "propose", "template": "Nak tanya pasal {security_problem}. Saya rasa {security_approach} cukup untuk handle scenario ni. Betul tak?"},
                {"role": "agent", "intent": "challenge", "template": "Not quite. {security_approach} address {covered_aspect} but leave {uncovered_risk} exposed. Look at {specific_risk} — ini single point of failure."},
                {"role": "user", "intent": "dismiss", "template": "Tapi {uncovered_risk} jarang berlaku. Kenapa nak build defense untuk edge case?"},
                {"role": "agent", "intent": "justify", "template": "In security, rare doesn't mean impossible. {related_incident} happened because someone also thought 'rare'. The cost of {safer_alternative} is {cost_comparison} versus {security_approach}, but the cost of breach is {breach_cost}."},
                {"role": "user", "intent": "revise", "template": "Fair. So what's the {safer_alternative} implementation look like? How much extra work?"},
                {"role": "agent", "intent": "propose_alternative", "template": "{safer_alternative} adds {implementation_effort} compared to {security_approach}. But it covers {covered_aspect} AND {uncovered_risk}. The extra effort is one-time; the protection is ongoing."},
                {"role": "user", "intent": "confirm", "template": "Alright, {safer_alternative} it is. When can we have it ready?"},
                {"role": "agent", "intent": "confirm", "template": "Estimated {timeline} with current team capacity. I'll break it into: {step1}, {step2}, security test, then code review. We can parallelize {step1} and {step2}."},
            ],
        },
    ],
    "technical_debt": [
        {
            "turn_sequence": [
                {"role": "user", "intent": "propose", "template": "Kita need ship {feature} by Friday.boleh skip {debt_item} untuk fast track?"},
                {"role": "agent", "intent": "challenge", "template": "Saya tak recommend skip {debt_item}. Kalau kita ship without it, {consequence} will happen within {timeframe}. The shortcut cost lebih tinggi dari investment yang kita nak avoid."},
                {"role": "user", "intent": "challenge", "template": "Tapi business priority. {feature}带来 revenue. {debt_item} is internal concern. Kenapa kita cant split scope?"},
                {"role": "agent", "intent": "justify", "template": "Fair point about revenue. Tapi {debt_item} dan {feature} tidak independent — {feature} depend on {debt_item} untuk {reason}. Kalau kita ship {feature} tanpa {debt_item}, ia akan break di {specific_scenario}."},
                {"role": "user", "intent": "negotiate", "template": "Okay... boleh minimize scope. What's the absolute minimum untuk ship safely?"},
                {"role": "agent", "intent": "revise", "template": "Minimum viable: {minimal_fix}. This addresses the critical risk without full refactor. Kita boleh do complete {debt_item} dalam next sprint dengan proper scope."},
                {"role": "user", "intent": "confirm", "template": "Alright. Minimal viable it is. Let's discuss the sprint plan."},
                {"role": "agent", "intent": "confirm", "template": "Agreed. I'll document the technical debt dan schedule the follow-up. For now, focus on {minimal_fix} + {feature} MVP."},
            ],
        },
        {
            "turn_sequence": [
                {"role": "user", "intent": "propose", "template": "Deadline tight week ni. Saya propose kita skip {debt_item} dulu, focus on {feature}. Boleh?"},
                {"role": "agent", "intent": "challenge", "template": "I hear you on the deadline, but {debt_item} isn't optional — it's the foundation {feature} builds on. Without it, {feature} will be {quality_issue}."},
                {"role": "user", "intent": "challenge", "template": "Tapi kalau kita tak ship {feature}, team dapat pressure dari stakeholder. {debt_item} boleh delay sampai next sprint?"},
                {"role": "agent", "intent": "justify", "template": "Delaying {debt_item} compounds the risk. Each day we ship without it, {consequence_probability} increases. By next sprint, {consequence} becomes {severity_escalation}, not just inconvenience."},
                {"role": "user", "intent": "negotiate", "template": "Okay so we can't fully skip. Can we do a partial {debt_item} — just enough to ship {feature} safely?"},
                {"role": "agent", "intent": "revise", "template": "Partial approach: {minimal_fix} covers the critical path. It's not the full {debt_item} but it's sufficient for {feature} safety. Full refactor stays in next sprint."},
                {"role": "user", "intent": "confirm", "template": "That works. Partial {debt_item} now, full refactor next sprint. Let's go."},
                {"role": "agent", "intent": "confirm", "template": "Agreed. I'll scope {minimal_fix} for this sprint and add {full_debt_item} to next sprint backlog with proper estimation."},
            ],
        },
    ],
    "implementation_approach": [
        {
            "turn_sequence": [
                {"role": "user", "intent": "propose", "template": "Saya nak build {component} sendiri dari scratch. Kita control full codebase."},
                {"role": "agent", "intent": "evaluate", "template": "Build from scratch gives control tapi ada hidden cost: {cost_1}, {cost_2}, dan {cost_3}. Third-party solution akan handle {external_concern} untuk kita."},
                {"role": "user", "intent": "challenge", "template": "Tapi third-party introduce dependency risk. Kalau vendor change pricing atau sunset product?"},
                {"role": "agent", "intent": "justify", "template": "Valid concern. Tapi {vendor_risk_mitigation}. Dan build cost dia {build_cost_comparison}. Kalau team kita {team_capacity}, maintain vs buy equation shift."},
                {"role": "user", "intent": "negotiate", "template": "Okay what about using {hybrid_approach}? Build core tapi use third-party untuk {specific_part}?"},
                {"role": "agent", "intent": "revise", "template": "Hybrid approach is actually the sweet spot. Build {core_component} internally, integrate with {third_party} for {specific_part}. Ini give us control atas critical path sambil reduce maintenance burden."},
                {"role": "user", "intent": "confirm", "template": "Done. Hybrid it is. Let's scope the build vs buy boundary."},
                {"role": "agent", "intent": "confirm", "template": "Good. Boundary: {build_scope} built in-house, {buy_scope} via {third_party}. I'll draft the architecture decision record."},
            ],
        },
        {
            "turn_sequence": [
                {"role": "user", "intent": "propose", "template": "Kita perlu {component} untuk {use_case}. Saya proposal: build custom solution."},
                {"role": "agent", "intent": "evaluate", "template": "Build vs buy untuk {component} depends on three factors: {factor_1}, {factor_2}, and {factor_3}. Let me assess each."},
                {"role": "user", "intent": "challenge", "template": "Tapi existing solutions tak match our {specific_requirement}. Kita kena custom build."},
                {"role": "agent", "intent": "justify", "template": "Custom build addresses {specific_requirement} but introduces {build_risk_1} and {build_risk_2}. Third-party {alternative_solution} covers 80% of requirements including {specific_requirement} via {configuration_path}."},
                {"role": "user", "intent": "negotiate", "template": "80% coverage okay tapi macamana handle the remaining 20%?"},
                {"role": "agent", "intent": "revise", "template": "Plugin architecture: use {alternative_solution} as base, extend via {extension_point} untuk the 20%. This gives us custom {specific_requirement} without full build cost. Maintenance load similar to build, but {time_to_market} 3x faster."},
                {"role": "user", "intent": "confirm", "template": "Plugin architecture sounds right. What's the implementation roadmap?"},
                {"role": "agent", "intent": "confirm", "template": "Phase 1: Setup {alternative_solution} base ({timeline_1}). Phase 2: Implement {extension_point} ({timeline_2}). Phase 3: Integrate dan test ({timeline_3}). Total: {total_timeline} versus {build_timeline} for full custom build."},
            ],
        },
    ],
}


def generate_multi_turn_dialogue(
    pattern_def: dict[str, Any],
    project_desc: str,
    difficulty: str,
    seed: int,
) -> MultiTurnDialogue:
    """Generate a multi-turn debate/negotiation dialogue with dynamic turn generation."""
    random.seed(seed)
    category = pattern_def.get("category", "architecture_tradeoff")

    # Determine turn count based on difficulty
    if difficulty == "L2":
        n_turns = random.randint(6, 8)
    elif difficulty == "L3":
        n_turns = random.randint(7, 9)
    elif difficulty == "L4":
        n_turns = random.randint(8, 10)
    else:  # L5
        n_turns = random.randint(9, 12)

    # Build role sequence: alternate user/agent with occasional double-agent
    role_sequence = []
    for i in range(n_turns):
        if i % 2 == 0:
            role_sequence.append("user")
        else:
            # Occasionally let agent respond twice (reflective reasoning)
            if random.random() < 0.15 and i < n_turns - 2:
                role_sequence.append("agent")
                role_sequence.append("user" if i + 2 < n_turns else "agent")
            else:
                role_sequence.append("agent")
    # Trim to exact length
    role_sequence = role_sequence[:n_turns]
    # Ensure starts with user and ends with agent
    if role_sequence[0] != "user":
        role_sequence[0] = "user"
    if role_sequence[-1] != "agent":
        role_sequence[-1] = "agent"

    # Assign intents based on position and category
    intent_pool = _get_intent_sequence(category, len(role_sequence), difficulty, seed)

    turns = []
    for i, (role, intent) in enumerate(zip(role_sequence, intent_pool)):
        content = _generate_dialogue_turn_content(role, intent, category, project_desc, difficulty, seed + i * 7)
        turns.append(DialogueTurn(role=role, content=content, intent=intent))

    # Resolution
    # Weighted resolution: make user_convinced more common (realistic pushback)
    resolution_types = ["agreed", "compromise", "user_convinced", "agent_convinced"]
    resolution_weights = [0.20, 0.25, 0.30, 0.25]  # User can successfully challenge
    total_w = sum(resolution_weights)
    r = random.random() * total_w
    cumulative = 0.0
    resolution_type = resolution_types[-1]
    for rt, w in zip(resolution_types, resolution_weights):
        cumulative += w
        if r <= cumulative:
            resolution_type = rt
            break
    resolutions = {
        "agreed": "Both parties agreed on the proposed approach after evidence-based discussion.",
        "compromise": "Compromise reached: hybrid approach combining elements from both sides.",
        "user_convinced": "User accepted the agent's counter-proposal after reviewing the evidence.",
        "agent_convinced": "Agent revised position after user presented valid counter-arguments.",
    }

    behaviours = ["professional_disagreement", "evidence_based_reasoning", "tradeoff_analysis"]
    if resolution_type == "compromise":
        behaviours.append("negotiation")
    if resolution_type in ("user_convinced", "agent_convinced"):
        behaviours.append("persuasion")
    if any(t.intent == "follow_up" for t in turns):
        behaviours.append("deep_dive")

    return MultiTurnDialogue(
        id=f"atan_mt_{random.randint(1, 99999):05d}",
        task_type="multi_turn_dialogue",
        category=category,
        difficulty=difficulty,
        language="ms-MY",
        project_context=project_desc,
        turns=turns,
        resolution=resolutions[resolution_type],
        resolution_type=resolution_type,
        behaviours=behaviours,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def _get_intent_sequence(category: str, n_turns: int, difficulty: str, seed: int) -> list[str]:
    """Generate a diverse intent sequence for the dialogue."""
    random.seed(seed)
    intents = []
    for i in range(n_turns):
        role = "user" if i % 2 == 0 else "agent"
        if i == 0:
            intents.append("propose")
        elif i == n_turns - 1:
            intents.append("confirm")
        elif role == "user":
            # Varied user reactions: some push back hard, some negotiate, some ask clarifying questions
            user_reactions = [
                "challenge", "negotiate", "dismiss", "follow_up", "revise",
                "push_back_hard",  # New: strong disagreement
                "ask_for_evidence",  # New: demanding proof
                "offer_alternative",  # New: counter-proposal
            ]
            intents.append(random.choice(user_reactions))
        else:
            intents.append(random.choice(["evaluate", "justify", "revise", "propose_alternative", "address_concern"]))
    return intents


def _generate_dialogue_turn_content(
    role: str, intent: str, category: str, project_desc: str, difficulty: str, seed: int
) -> str:
    """Generate genuinely unique content for each dialogue turn."""
    random.seed(seed)
    
    # Different content generators per intent
    generators = {
        "propose": lambda: _gen_proposal(category, project_desc, seed),
        "challenge": lambda: _gen_challenge(project_desc, seed),
        "negotiate": lambda: _gen_negotiation(seed),
        "dismiss": lambda: _gen_dismissal(seed),
        "follow_up": lambda: _gen_follow_up(category, seed),
        "revise": lambda: _gen_revise(seed),
        "evaluate": lambda: _gen_evaluation(category, project_desc, seed),
        "justify": lambda: _gen_justification(category, seed),
        "propose_alternative": lambda: _gen_alternative(category, seed),
        "address_concern": lambda: _gen_address_concern(seed),
        "confirm": lambda: _gen_confirmation(seed),
        "push_back_hard": lambda: _gen_push_back_hard(seed),
        "ask_for_evidence": lambda: _gen_ask_for_evidence(seed),
        "offer_alternative": lambda: _gen_offer_alternative(seed),
    }
    
    gen = generators.get(intent, generators["propose"])
    content = gen()
    
    # Apply Malay language injection based on role
    if role == "user":
        content = _inject_malay_language(content, mix_level=min(MALAY_MIX_LEVEL * 1.3, 0.6), seed=seed + 100)
    else:
        content = _inject_malay_language(content, mix_level=MALAY_MIX_LEVEL, seed=seed + 200)
    
    # Difficulty-based length adjustment
    if difficulty == "L2":
        content = content[:250]
    elif difficulty == "L5":
        content = content + " Saya juga akan pertimbang long-term maintenance implications dan team velocity impact."
    
    return content


def _gen_proposal(category: str, project_desc: str, seed: int) -> str:
    random.seed(seed)
    proposals = {
        "architecture_tradeoff": [
            f"Saya propose {random.choice(['event-driven architecture', 'CQRS pattern', 'monolith split', 'service mesh'])} untuk address {random.choice(['scalability', 'deployment frequency', 'team autonomy'])} issue dekat {project_desc}.",
            f"Untuk {project_desc}, saya cadang kita guna {random.choice(['microservices', 'modular monolith', 'serverless', 'event sourcing'])}. nak dengar thoughts?",
            f"Nak try {random.choice(['GraphQL', 'gRPC', 'REST with HAL', 'tRPC'])} untuk {project_desc}. What's the trade-off?",
        ],
        "security_review": [
            f"Saya plan implement {random.choice(['JWT in localStorage', 'API key in frontend', 'CORS wildcard', 'custom auth middleware'])} untuk {project_desc}. Quick win?",
            f"Untuk security {project_desc}, saya suggest {random.choice(['encrypt at app layer', 'use KMS directly', 'apply WAF rules', 'enable TLS 1.3'])}. opinions?",
        ],
        "technical_debt": [
            f"We need ship {random.choice(['feature X', 'migration', 'refactor'])} by Friday. Boleh skip {random.choice(['test coverage', 'docs', 'error handling', 'logging'])} untuk fast track?",
            f"Deadline tight. Saya propose kita {random.choice(['cut corners on validation', 'use quick hack', 'defer refactoring', 'skip code review'])}. Boleh?",
        ],
        "implementation_approach": [
            f"Saya nak build {random.choice(['auth module', 'search engine', 'notification system', 'data pipeline'])} sendiri dari scratch untuk {project_desc}.",
            f"Untuk {project_desc}, build vs buy decision: saya倾向 build custom solution.",
        ],
    }
    opts = proposals.get(category, proposals["architecture_tradeoff"])
    return random.choice(opts)


def _gen_challenge(project_desc: str, seed: int) -> str:
    random.seed(seed)
    challenges = [
        f"Tapi {project_desc} ada constraint yang buat ini risky. {random.choice(['backward compatibility', 'performance SLA', 'compliance requirement', 'legacy dependency'])} tak boleh compromise.",
        f"Kalau ikut approach ni, {random.choice([' downstream teams kena refactor', 'testing coverage drop', 'deployment pipeline break', 'monitoring gaps appear'])}. Tak boleh ignore.",
        f" saya challenge idea ni: {random.choice(['complexity introduced', 'operational burden', 'skill gap', 'vendor lock-in'])} akan surface dalam 3 months.",
    ]
    return random.choice(challenges)


def _gen_negotiation(seed: int) -> str:
    random.seed(seed)
    negotiations = [
        "Okay tapi macam mana kalau kita buat phased approach? Quick win dulu, full solution phase 2.",
        "Boleh consider tapi ada condition: {condition} mesti address dulu.",
        "What if we do a spike first? 2 days investigation, then decide. Risk controlled.",
        "Can we split this into independent work packages? Ship partial value sooner.",
    ]
    return random.choice(negotiations)


def _gen_dismissal(seed: int) -> str:
    random.seed(seed)
    dismissals = [
        "Tapi semua orang dah buat macam ni. Tak perlu over-engineer.",
        "This is a solved problem. Existing solutions cover 90%+ of our cases.",
        "Timeline tidak allow untuk perfect solution. Shipping > perfect.",
        "Team capacity limited. Kalau kita spend energy di sini, feature lain lambat.",
    ]
    return random.choice(dismissals)


def _gen_follow_up(category: str, seed: int) -> str:
    random.seed(seed)
    follow_ups = [
        f"satu soalan lagi — bagaimana dengan {random.choice(['edge cases', 'failure mode', 'migration path', 'observability', 'rollback strategy'])}?",
        f"Bagaimana kalau {random.choice(['traffic 10x', 'data size grows 5x', 'team doubles', 'compliance audit happens'])}?",
        f"One more thing: {random.choice(['monitoring', 'alerting', 'runbook', 'documentation'])} coverage?",
    ]
    return random.choice(follow_ups)


def _gen_revise(seed: int) -> str:
    random.seed(seed)
    revises = [
        "Okay I see your point. Let me revise my proposal: {revision}.",
        "Fair point. Revised approach: {revision}. Still addresses the core concern dengan less risk.",
        "You convinced me on that aspect. New proposal: {revision}.",
    ]
    return random.choice(revises)


def _gen_evaluation(category: str, project_desc: str, seed: int) -> str:
    random.seed(seed)
    evaluations = [
        f"From {project_desc} perspective, the trade-off analysis shows: {random.choice(['option A wins on simplicity', 'option B wins on scalability', 'it depends on the binding constraint', 'both have merit but different risk profiles'])}.",
        f"Let me evaluate this against our {random.choice(['architecture principles', 'non-functional requirements', 'team constraints', 'business goals'])}: {random.choice(['strong fit', 'partial fit with gaps', 'misaligned on key dimension', 'needs clarification'])}.",
        f"Looking at {project_desc}, the key factor is {random.choice(['operational complexity', 'time to market', 'long-term maintainability', 'team expertise'])}. This changes the calculus.",
    ]
    return random.choice(evaluations)


def _gen_justification(category: str, seed: int) -> str:
    random.seed(seed)
    justifications = [
        f"The evidence supports this: {random.choice(['previous incident analysis', 'benchmark data', 'peer review findings', 'failure mode analysis'])} shows {random.choice(['the risk is real', 'the cost of inaction exceeds the cost of action', 'alternative has hidden complexity', 'this addresses the root cause not the symptom'])}.",
        'I understand the pushback but ' + random.choice(["the data doesn't lie", "we've seen this pattern before", "the failure mode is well-documented", "the alternative introduces different risks"]) + '.',
    ]
    return random.choice(justifications)


def _gen_alternative(category: str, seed: int) -> str:
    random.seed(seed)
    alternatives = [
        f"Instead of that approach, I'd recommend: {random.choice(['plugin architecture', 'adapter pattern', 'feature flag gated rollout', 'canary deployment', 'strangler fig pattern'])}. It gives us {random.choice(['flexibility', 'safety', 'incremental adoption', 'rollback capability'])}.",
        f"Alternative that balances {random.choice(['speed vs safety', 'control vs convenience', 'simplicity vs flexibility'])}: {random.choice(['hybrid approach', 'phased migration', 'wrapper pattern', 'abstraction layer'])}.",
    ]
    return random.choice(alternatives)


def _gen_address_concern(seed: int) -> str:
    random.seed(seed)
    responses = [
        f"Good question. For that concern, the answer depends on {random.choice(['your tolerance for operational complexity', 'the migration window', 'team availability', 'downstream dependencies'])}. Here's how I'd handle it: {random.choice(['start small and iterate', 'build guardrails first', 'parallel run then cutover', 'feature flag controlled rollout'])}.",
        f"That's a valid follow-up. The approach would be: {random.choice(['implement with observable exit criteria', 'build the safety net first then the feature', 'prototype then productionize', 'automate the transition'])}.",
    ]
    return random.choice(responses)


def _gen_confirmation(seed: int) -> str:
    random.seed(seed)
    confirmations = [
        "Agreed. I'll document the decision dan schedule the follow-up review.",
        "Done. Next step: {step}. Timeline: {timeline}.",
        "Confirmed. I'll create the ADR dan add to roadmap.",
    ]
    return random.choice(confirmations)


def _gen_push_back_hard(seed: int) -> str:
    """User strongly disagrees — not just challenging but pushing back with counter-evidence."""
    random.seed(seed)
    pushbacks = [
        "Saya tak setuju. Evidence yang anda bagi tak cukup strong. Saya ada data lain yang show sebaliknya.",
        "Hold on — anda ambil assumption yang salah. Kalau kita check {check_item},结论 akan beza.",
        "This isn't about {assumption}. The real constraint ialah {real_constraint}. You're solving the wrong problem.",
        "Saya dah try approach ni sekali. Ia fail karena {failure_reason}. Tak mau repeat mistake yang sama.",
        "Kalau ikut logic anda, kita akan end up dengan {bad_outcome}. That's not acceptable untuk production.",
        "您说得有道理，但我需要更多 evidence sebelum I commit pada approach ni.",
        "Saya paham point anda, tapi saya rasa ada gap dalam reasoning. {gap} tidak di-address.",
    ]
    return random.choice(pushbacks)


def _gen_ask_for_evidence(seed: int) -> str:
    """User demands evidence before accepting."""
    random.seed(seed)
    evidences = [
        "Boleh tunjuk evidence? Saya nak tengok data dulu sebelum decide.",
        "Where's the benchmark data? Tanpa numbers, ini just opinion je.",
        "Saya perlu see the actual metrics. Show me {metric} before we proceed.",
        "Can you prove that {claim}? I need concrete numbers, not anecdotes.",
        "Before I agree, I want to see: {requirement}. Can you deliver that?",
        "Saya minta you walk me through the actual implementation plan, not just the concept.",
    ]
    return random.choice(evidences)


def _gen_offer_alternative(seed: int) -> str:
    """User proposes their own alternative approach."""
    random.seed(seed)
    alternatives = [
        "Actually, how about we try {alternative} instead? It might be simpler dan still address {concern}.",
        "What if we take a different path: {alternative}? Less overhead, same outcome.",
        "Saya ada idea lain — {alternative}. Nak dengar rationale dulu sebelum reject.",
        "Why not {alternative}? It solves {problem} without introducing {risk}.",
        "I think we're overcomplicating this. Simpler approach: {alternative}.",
    ]
    return random.choice(alternatives)



def _generate_dialogue_fillers(
    project_desc: str, difficulty: str, intent: str, seed: int
) -> dict[str, str]:
    """Generate diverse filler variables for dialogue templates."""
    random.seed(seed)
    fillers: dict[str, str] = {
        "project_desc": project_desc,
        "follow_up_concern": random.choice([
            "performance impact", "operational complexity", "team onboarding cost",
            "debugging difficulty", "monitoring gaps", "scaling limitations",
        ]),
        "approach": random.choice([
            "first isolate the concern, then validate with metrics, then implement incrementally",
            "start with a feature flag, gather data, then decide on full rollout",
            "prototype the minimal version, measure impact, then scale if justified",
        ]),
    }

    # Intent-specific fillers
    if intent in ("propose", "challenge"):
        fillers.update({
            "component": random.choice(["auth module", "payment processor", "notification service", "data pipeline", "API gateway"]),
            "feature": random.choice(["real-time sync", "batch export", "user analytics", "audit trail", "rate limiter"]),
            "debt_item": random.choice(["test coverage", "documentation", "error handling", "logging", "migration scripts"]),
            "security_approach": random.choice(["input validation", "rate limiting", "CORS policy", "JWT storage", "encryption at rest"]),
            "security_problem": random.choice(["XSS attacks", "brute force login", "data exfiltration", "privilege escalation", "session hijacking"]),
            "approach_a": random.choice(["event sourcing", "CQRS", "sync polling", "REST API", "monolithic deploy"]),
            "approach_b": random.choice(["message queue", "WebSocket", "gRPC", "microservice", "serverless"]),
            "problem": random.choice(["data consistency", "scalability bottleneck", "operational complexity", "deployment risk", "testing difficulty"]),
        })
    elif intent in ("evaluate", "justify"):
        fillers.update({
            "reason_a": random.choice(["it's faster to implement", "the team knows the pattern", "integration is straightforward", "fewer moving parts"]),
            "concern_a": random.choice(["state consistency under failure", "operational overhead", "debugging complexity", "upgrade path"]),
            "trigger_condition": random.choice(["traffic doubles", "team grows past 5", "compliance audit happens", "incident occurs"]),
            "consequence": random.choice(["data corruption", "security breach", "slowness under load", "increased maintenance cost"]),
            "cost_multiplier": random.choice(["3x", "5x", "10x", "uncalculated but significant"]),
            "risk_1": random.choice(["data exposure", "integrity violation", "availability gap"]),
            "risk_2": random.choice(["audit trail gaps", "compliance violation", "recovery complexity"]),
            "cost_1": random.choice(["development time", "ongoing maintenance", "debugging overhead", "testing complexity"]),
            "cost_2": random.choice(["hiring dependency", "knowledge silo", "upgrade burden"]),
            "cost_3": random.choice(["testing burden", "documentation gap", "operational complexity"]),
        })
    elif intent in ("negotiate", "revise"):
        fillers.update({
            "hybrid_approach": random.choice(["phased rollout", "feature flag gated", "parallel run", "canary deployment", "plugin architecture"]),
            "minimal_fix": random.choice(["a guardrail", "a validation layer", "a circuit breaker", "a fallback mechanism", "an audit log"]),
            "safer_alternative": random.choice(["parameterized queries", "httpOnly cookies", "WAF layer", "KMS-managed keys", "connection pooling"]),
            "key_difference": random.choice(["defense in depth", "implicit safety guarantees", "separation of concerns", "fail-safe defaults"]),
        })
    elif intent == "propose_alternative":
        fillers.update({
            "step1": random.choice(["implement the core change", "add the validation layer", "setup the monitoring"]),
            "step2": random.choice(["write integration tests", "add the error handling", "configure the alerts"]),
            "attack_vector": random.choice(["injection attacks", "race conditions", "privilege escalation", "data leakage"]),
        })
    elif intent == "confirm":
        fillers.update({
            "build_scope": random.choice(["core business logic", "domain models", "critical pathways"]),
            "buy_scope": random.choice(["infrastructure", "utils", "non-differentiating parts"]),
            "timeline_1": random.choice(["2 weeks", "1 sprint", "10 days"]),
            "timeline_2": random.choice(["1 week", "3 days", "half a sprint"]),
            "timeline_3": random.choice(["1 week", "5 days", "3 days"]),
            "total_timeline": random.choice(["4 weeks", "1 month", "5 sprints"]),
            "build_timeline": random.choice(["12 weeks", "3 months", "10 sprints"]),
        })

    return fillers


def _difficulty_for_task(category: str, n_sessions: int) -> str:
    """Determine difficulty based on task complexity."""
    if n_sessions <= 2:
        return random.choice(["L2", "L3"])
    elif n_sessions <= 4:
        return random.choice(["L3", "L4"])
    else:
        return random.choice(["L4", "L5"])


# ---------------------------------------------------------------------------
# Main generation pipeline
# ---------------------------------------------------------------------------

def _inject_malay_language(text: str, mix_level: float = MALAY_MIX_LEVEL, seed: int = 0) -> str:
    """Inject Malaysian English code-switching patterns into text."""
    random.seed(seed)
    
    # Malay connectors and discourse markers to insert
    malay_connectors = [
        "Daripada analysis ni, saya rasa ",
        "Soalan penting: ",
        "Kalau kita consider constraints ni — ",
        "From what we know, the real issue ialah ",
        "Saya ada concern pasal ",
        "Based on experience saya, ",
        "The challenge here ialah ",
        "Kalau tengok dari angle ni, ",
        "Saya cadang kita buat macam ni: ",
        " tapi ada trade-off yang kita kena acknowledge — ",
        "Actually, if you look at the root cause, ia bukan di ",
        "The key insight here ialah ",
        "Saya belum convienced yet because ",
        "Kalau ikut data yang ada, ",
        "Berdasarkan pattern yang kita nampak, ",
    ]
    
    # Malay transition phrases
    malay_transitions = [
        "First, kita kena understand dulu.",
        "Lepas tu, kita evaluate options.",
        "Then kita implement dan verify.",
        "Finally, document decisions dalam ADR.",
        "Sebelum commit, kita perlu test edge cases.",
        "Tapi tunggu — ada satu lagi factor.",
        "Okay, tapi actually there's a better way.",
        "Kalau fikir again, mungkin kita boleh ",
    ]
    
    # Words to occasionally swap
    word_swaps = {
        "the": "yang", "a": "sebuah", "is": "ialah", "are": "adalah",
        "we": "kita", "you": "anda", "your": "anda", "our": "kita",
        "but": "tapi", "and": "dan", "or": "atau", "if": "jika",
        "because": "kerana", "when": "bila", "where": "di mana",
        "for": "untuk", "with": "dengan", "from": "daripada",
        "not": "tidak", "no": "tidak", "will": "akan", "can": "boleh",
        "should": "sepatutnya", "must": "perlu", "need": "perlu",
        "also": "juga", "still": "masih", "already": "sudah",
        "just": "hanya", "very": "sangat", "more": "lebih",
        "this": "ini", "that": "itu", "these": "ini", "those": "itu",
        "here": "sini", "there": "situ", "now": "sekarang",
        "what": "apa", "how": "bagaimana", "why": "kenapa",
        "who": "siapa", "which": "yang mana",
    }
    
    # Apply swaps to ~mix_level fraction of applicable words
    words = text.split()
    result = []
    for w in words:
        lower_w = w.lower().strip(".;:!?")

        if lower_w in word_swaps and random.random() < mix_level * 0.3:
            # Keep original capitalization
            swapped = word_swaps[lower_w]
            if w[0].isupper():
                swapped = swapped.capitalize()
            result.append(swapped)
        else:
            result.append(w)
    
    text = " ".join(result)
    
    # Occasionally prepend a Malay discourse marker
    if random.random() < mix_level * 0.5:
        prefix = random.choice(malay_connectors)
        text = prefix + text[0].lower() + text[1:]
    
    # Occasionally insert a Malay transition
    if random.random() < mix_level * 0.3:
        idx = len(text) // 2
        text = text[:idx] + " " + random.choice(malay_transitions) + " " + text[idx:]
    
    return text


def _rewrite_dialogue_turn_malay(
    role: str, intent: str, category: str, project_desc: str, difficulty: str, seed: int
) -> str:
    """Generate dialogue turn content with controlled Malay mixing."""
    random.seed(seed)
    
    # Call the appropriate generator directly (avoid circular call)
    generators = {
        "propose": lambda: _gen_proposal(category, project_desc, seed),
        "challenge": lambda: _gen_challenge(project_desc, seed),
        "negotiate": lambda: _gen_negotiation(seed),
        "dismiss": lambda: _gen_dismissal(seed),
        "follow_up": lambda: _gen_follow_up(category, seed),
        "revise": lambda: _gen_revise(seed),
        "evaluate": lambda: _gen_evaluation(category, project_desc, seed),
        "justify": lambda: _gen_justification(category, seed),
        "propose_alternative": lambda: _gen_alternative(category, seed),
        "address_concern": lambda: _gen_address_concern(seed),
        "confirm": lambda: _gen_confirmation(seed),
        "push_back_hard": lambda: _gen_push_back_hard(seed),
        "ask_for_evidence": lambda: _gen_ask_for_evidence(seed),
        "offer_alternative": lambda: _gen_offer_alternative(seed),
    }
    
    gen = generators.get(intent, generators["propose"])
    base_content = gen()
    
    # Apply Malay language injection based on role and difficulty
    if role == "user":
        return _inject_malay_language(base_content, mix_level=min(MALAY_MIX_LEVEL * 1.3, 0.6), seed=seed + 100)
    else:
        return _inject_malay_language(base_content, mix_level=MALAY_MIX_LEVEL, seed=seed + 200)



def generate_dataset(
    total: int = 5000,
    seed: int = 42,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    val_ratio: float = 0.1,
) -> dict[str, Any]:
    """Generate multi-session + multi-turn dialogue dataset."""
    random.seed(seed)

    # Split: 60% multi-session, 40% multi-turn dialogue
    n_sessions_total = int(total * 0.6)
    n_dialogue_total = total - n_sessions_total

    all_records: list[dict[str, Any]] = []
    category_counts: dict[str, int] = {}
    difficulty_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {"multi_session_project": 0, "multi_turn_dialogue": 0}

    # ---- Multi-session trajectories ----
    print(f"Generating {n_sessions_total} multi-session trajectories...", file=sys.stderr)
    tasks = CATEGORY_TASKS["multi_session_project"]
    for i in range(n_sessions_total):
        task = random.choice(tasks)
        proj_idx = random.randint(0, len(PROJECT_TEMPLATES) - 1)
        n_sess = random.choice([2, 3, 3, 4, 4, 5])  # weighted toward 3-4 sessions
        proj = generate_project_context(proj_idx, seed + i)
        traj = build_multi_session_trajectory(task, proj, n_sess, seed + i + 1000)
        rec = traj.to_dict()
        cat = rec["category"]
        diff = rec["difficulty"]
        category_counts[cat] = category_counts.get(cat, 0) + 1
        difficulty_counts[diff] = difficulty_counts.get(diff, 0) + 1
        type_counts["multi_session_project"] += 1
        all_records.append(rec)

        if (i + 1) % 500 == 0:
            print(f"  Sessions: {i + 1}/{n_sessions_total}", file=sys.stderr)

    # ---- Multi-turn dialogues ----
    print(f"Generating {n_dialogue_total} multi-turn dialogues...", file=sys.stderr)
    all_patterns = []
    for cat, patterns in DIALOGUE_PATTERNS.items():
        for p in patterns:
            all_patterns.append({"category": cat, **p})

    for i in range(n_dialogue_total):
        pattern = random.choice(all_patterns)
        proj_tpl = random.choice(PROJECT_TEMPLATES)
        diff = random.choices(["L2", "L3", "L4", "L5"], weights=[0.15, 0.40, 0.35, 0.10])[0]
        dialogue = generate_multi_turn_dialogue(pattern, proj_tpl["name"], diff, seed + i + 5000)
        rec = dialogue.to_dict()
        cat = rec["category"]
        diff = rec["difficulty"]
        category_counts[cat] = category_counts.get(cat, 0) + 1
        difficulty_counts[diff] = difficulty_counts.get(diff, 0) + 1
        type_counts["multi_turn_dialogue"] += 1
        all_records.append(rec)

        if (i + 1) % 500 == 0:
            print(f"  Dialogues: {i + 1}/{n_dialogue_total}", file=sys.stderr)

    # Shuffle and split
    random.shuffle(all_records)
    val_count = max(1, int(len(all_records) * val_ratio))
    val_records = all_records[:val_count]
    train_records = all_records[val_count:]

    # Compute diversity
    full_hashes = set()
    short_hashes = set()
    for rec in all_records:
        if rec["task_type"] == "multi_session_project":
            content = json.dumps(rec.get("sessions", []), sort_keys=True)
        else:
            content = json.dumps(rec.get("turns", []), sort_keys=True)
        full_hashes.add(content)
        short_hashes.add(content[:300])

    total = len(all_records)
    diversity = {
        "full_content_uniqueness": len(full_hashes) / max(total, 1),
        "short_content_uniqueness": len(short_hashes) / max(total, 1),
        "category_count": len(category_counts),
        "type_count": len(type_counts),
        "difficulty_count": len(difficulty_counts),
    }

    print(f"\nGeneration complete:", file=sys.stderr)
    print(f"  Total: {total}", file=sys.stderr)
    print(f"  Train: {len(train_records)}, Val: {len(val_records)}", file=sys.stderr)
    print(f"  Types: {type_counts}", file=sys.stderr)
    print(f"  Categories: {category_counts}", file=sys.stderr)
    print(f"  Difficulty: {difficulty_counts}", file=sys.stderr)
    print(f"  Diversity: {diversity}", file=sys.stderr)

    return {
        "train": train_records,
        "val": val_records,
        "metadata": {
            "version": "0.3.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_records": total,
            "train_records": len(train_records),
            "val_records": len(val_records),
            "record_types": type_counts,
            "category_distribution": category_counts,
            "difficulty_distribution": difficulty_counts,
            "diversity_metrics": diversity,
        },
    }


def save_dataset(data: dict[str, Any], output_dir: Path) -> None:
    """Save to JSONL files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    for split_name, records in [("train", data["train"]), ("val", data["val"])]:
        path = output_dir / f"atan_v1_{split_name}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"  {path}: {len(records)} records", file=sys.stderr)

    meta_path = output_dir / "manifest.json"
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(data["metadata"], f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"  {meta_path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate multi-session + multi-turn dialogue trajectories for atan-v1 (v0.3).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--total", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--val-ratio", type=float, default=0.1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        print("DRY RUN:", file=sys.stderr)
        print(f"  Total: {args.total}", file=sys.stderr)
        print(f"  Multi-session: {int(args.total * 0.6)}", file=sys.stderr)
        print(f"  Multi-turn dialogue: {int(args.total * 0.4)}", file=sys.stderr)
        print(f"  Output: {args.output_dir}", file=sys.stderr)
        return 0

    print("=" * 60, file=sys.stderr)
    print("ATAN-V1 MULTI-SESSION + DIALOGUE GENERATOR v0.3", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"Seed: {args.seed}", file=sys.stderr)
    print(f"Target: {args.total} records", file=sys.stderr)
    print(f"Output: {args.output_dir}", file=sys.stderr)
    print(file=sys.stderr)

    data = generate_dataset(
        total=args.total,
        seed=args.seed,
        output_dir=Path(args.output_dir),
        val_ratio=args.val_ratio,
    )
    save_dataset(data, Path(args.output_dir))

    div = data["metadata"]["diversity_metrics"]
    print(f"\nDiversity:", file=sys.stderr)
    print(f"  Full content uniqueness: {div['full_content_uniqueness']*100:.1f}%", file=sys.stderr)
    print(f"  Categories: {div['category_count']}", file=sys.stderr)
    print(f"  Record types: {div['type_count']}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
