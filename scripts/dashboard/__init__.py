#!/usr/bin/env python3
"""Atlas Engineering Dashboard — browser control plane over Atlas operations.

Layer 4 (CLI & Tooling). See docs/adr/ADR-016-engineering-dashboard.md.

Modules:
    app      aiohttp application assembly (API + static SPA)
    actions  whitelisted registry of real Atlas CLI operations
    jobs     persisted async job runner (subprocess executor)
    state    read-only aggregation of authoritative Atlas state
    safety   path/confirmation/token security primitives
"""

from __future__ import annotations

__version__ = "1.0.0"
