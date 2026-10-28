# ADR-016: Atlas Engineering Dashboard

**Status:** Accepted
**Date:** 2026-08-23
**Deciders:** Principal Engineer / Product Architect / QA Lead / Security Engineer / Release Engineer
**Related:** ADR-010 (architecture governance), ADR-011 (release immutability),
ADR-013 (parallel processing), ADR-014 (release pipeline), AGENTS.md §5, §11, §21

---

## Context

Atlas operations (pipeline FSM transitions, human approvals, downloads, ETL,
view builds, release verification/promotion/publishing, AI-assisted review,
evaluation) are only reachable through CLI entry points
(`scripts/automation_runner.py`, `scripts/atlas.py`, `scripts/release/*`) and a
terminal TUI. Operators lack a browser-based control plane to observe real
state and trigger governed operations without shell access.

The repository already has:

- Authoritative JSON state under `metadata/` (release index + manifests,
  pipeline state per `StateMachine._persist()`, approvals via `ApprovalGate`,
  readiness report, benchmark registry, view manifests).
- Governed CLIs that enforce every gate (e.g. `VALIDATION → RELEASED`
  forbidden; approval required before release; never-overwrite writers).
- A pinned dependency set (`requirements-lock.txt`) that includes **aiohttp
  3.14.3**. No other web framework is installed.

## Problem

Browser dashboards built as "frontend over business logic" would either
duplicate Atlas logic (violating the single-source-of-truth principle) or open
unsafe capabilities (arbitrary commands, path traversal, silent data edits).
Both are forbidden by AGENTS.md §21.

## Decision

Introduce a new **Layer 4 tooling subsystem**: `scripts/dashboard/`.

1. **Orchestration-only backend.** The dashboard is an application/API layer
   over existing subsystems. Zero business logic is duplicated:
   - All **reads** are aggregations of authoritative state files and manifests.
   - All **writes/actions** execute the *existing* CLIs as subprocesses with
     argv built from a strict server-side allowlist. The browser can never
     express an arbitrary command, path, or flag combination.

2. **Async job model.** Every mutating or long-running operation becomes a
   persisted job (`queued → running → succeeded | failed | timeout | cancelled |
   interrupted`) with captured exit codes and logs under
   `metadata/dashboard/`. Request handlers never block on job execution.

3. **Stack.** `aiohttp.web` (already a locked dependency) serves both the JSON
   API and a build-free vanilla-JS single-page frontend from
   `scripts/dashboard/static/`. No npm/node toolchain, no new dependencies.

4. **Safety envelope.**
   - Binds to `127.0.0.1` by default; optional bearer token via
     `ATLAS_DASHBOARD_TOKEN` (constant-time compare).
   - Strict security headers (CSP `default-src 'self'`, nosniff, no-store).
   - Path-typed inputs validated against repo-root-relative whitelists;
     preview endpoints restricted to explicit read-safe subtrees.
   - Destructive actions (`deny`, `cancel`, `rescind`, `promote`,
     `publish`, cache purge, e2e non-dry-run) require an exact typed
     confirmation phrase returned by the action catalog.
   - Credential-gated actions (HF upload/download, AI reviewer) are disabled —
     with the reason shown — when their env credentials are absent; env values
     are never exposed.
   - Job logs never include environment contents; argv is stored because it
     contains no secrets by construction (credentials flow via env only).

5. **Governance preservation.**
   - Human approval remains the FSM gate: the dashboard surfaces
     `request-approval / approve / deny / rescind / release` exactly as the
     automation layer defines them; the browser user IS the human approver and
     must supply identity + role; agents cannot self-approve.
   - Release immutability respected: promotion runs `promote_release.py`
     (new manifest, same bytes); no endpoint writes into frozen bundles.
   - AI review failure semantics preserved: reviewer batch exit code 3 is
     surfaced as `needs_attention`, never acceptance.
   - Worker counts for the internal executor come from
     `parallel.config.resolve_worker_count()` (ADR-013).

6. **Layer registration.** `dashboard*` modules registered in
   `validate_architecture.LAYER_MAP` as Layer 4 so import direction stays
   governed.

## Consequences

**Positive**

- One-command local ops UI: `python -m scripts.dashboard.server`.
- Full audit trail of operator-triggered work (jobs.json + logs) without a
  second state source: jobs are *evidence*, not authoritative Atlas state.
- Existing CLI behaviour untouched; the TUI/CLI remain first-class.

**Negative / limitations**

- The interactive human record-review TUI cannot run inside a browser tab; the
  dashboard exposes sample generation, AI review, calibration, and decision
  file inspection, while keystroke-level review stays terminal-based (button
  explains this instead of faking it).
- aiohttp.web is used in server role although it entered the lockfile as an
  HTTP client dependency; acceptable because it is version-locked and
  battle-tested, and avoids adding a new dependency.

## UI v2 — "Mission Control" (2026-08-24)

The SPA was redesigned around a dark ops-console aesthetic while keeping the
original constraints: vanilla JS/CSS/SVG, no build step, no new dependencies,
API layer untouched.

- **Design tokens**: layered near-black surfaces with hairline borders,
  electric-blue accent, Inter/system + JetBrains Mono (tabular numerals),
  8px spacing grid. All colors/sizes flow through CSS custom properties.
- **Layout**: collapsible sidebar navigation with inline-SVG icon set;
  sticky topbar with per-tab context crumbs; off-canvas sidebar on mobile.
- **Visualization (`viz.js`)**: dependency-free SVG primitives — sparklines
  (job durations), donut gate-mix, horizontal bar charts (records by category
  from the real v1.0 manifest statistics), an interactive 11-state FSM node
  graph with visited/current highlighting and a transition timeline, and a
  hash-linked release chain strip.
- **UX**: ⌘K command palette over tabs/actions/pipelines; skeleton loaders;
  pulsing running states; log viewer with filter-highlight + download;
  explained empty states; focus-visible rings; reduced-motion support.
- Strict CSP preserved: zero inline styles/scripts; all dynamic chart
  geometry uses SVG attributes or CSSOM (permitted), never `style=""`.

## Remote Access (Tailscale)

The server always binds to `127.0.0.1`; it is never exposed to the LAN
directly. Remote access is published through Tailscale instead:

```bash
# persistent service (systemd user unit)
~/.config/systemd/user/atlas-dashboard.service   # binds 127.0.0.1:8765,
                                                 # carries ATLAS_DASHBOARD_TOKEN
systemctl --user enable --now atlas-dashboard

# tailnet-only HTTPS reverse proxy (WireGuard + Let's Encrypt cert)
tailscale serve --bg 8765
# -> https://<host>.<tailnet>.ts.net/
```

Properties:
- Reachable **only** by devices authenticated to the operator's tailnet; no
  funnel/internet exposure.
- The bearer token (`ATLAS_DASHBOARD_TOKEN`) is still required on every `/api`
  call; the SPA collects it once via an in-page bar and stores it in browser
  `localStorage`, attaching it as an `Authorization` header thereafter.
- Static SPA assets are readable within the tailnet without the token (no
  secrets in code); every data/action endpoint remains token-gated.
- To revoke: `tailscale serve --https=443 off` and/or rotate the token by
  editing the unit's Environment line + `systemctl --user daemon-reload &&
  systemctl --user restart atlas-dashboard`.

## Verification

- `tests/test_dashboard_server.py` covers catalog safety, param validation,
  destructive confirmation, path traversal rejection, auth middleware, state
  aggregation against real files, and end-to-end job execution/cancellation.
- `python scripts/validate_architecture.py` passes with the new Layer 4 entries.
- Live smoke test: server boots, overview returns v1.0 release state, a dry-run
  pipeline job and an AQL validation job execute successfully with exit code 0.
