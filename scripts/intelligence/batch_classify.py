#!/usr/bin/env python3
"""
batch_classify.py — DEPRECATED (v1.9)

This module is a backward-compatibility shim. It has been superseded by
the Universal Scheduler in ``scripts/parallel/`` and the canonical
implementation in ``batch_classify_v2.py``.

**Migration path:**

  Old:  python scripts/intelligence/batch_classify.py --root . --release v1.2
  New:  python scripts/intelligence/batch_classify_v2.py --root . --release v1.2

  Old:  from batch_classify import SourceConfig, classify_source_shards, merge_and_report
  New:  from batch_classify_v2 import SourceConfig, classify_source_shards, merge_and_report
        Use parallel.scheduler.Scheduler for per-source parallelism

**Shim policy (Phase 5D):** this module contains NO business logic. All
implementations live in ``batch_classify_v2.py``; this file re-exports them
so existing import paths continue to work. It emits a ``DeprecationWarning``
on import and will be removed in Atlas v2.0.

**Removal target:** Atlas v2.0
"""

from __future__ import annotations

import warnings

_DEPRECATION_MSG = (
    "batch_classify.py is deprecated and will be removed in Atlas v2.0. "
    "Use scripts/intelligence/batch_classify_v2.py instead.\n"
    "All functionality is available via:\n"
    "  - batch_classify_v2.py (full-source parallel classification)\n"
    "  - scripts/parallel/ (universal scheduler)"
)

warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)

# ---------------------------------------------------------------------------
# Re-export canonical implementations from batch_classify_v2 (identity —
# the SAME class/function objects, so `shim.X is v2.X` holds).
# ---------------------------------------------------------------------------

from batch_classify_v2 import (  # noqa: E402,F401
    ALL_SOURCES,
    DEFAULT_CLASSIFIER_VERSION,
    DEFAULT_DATA_SNAPSHOT,
    SourceConfig,
    SummaryAccumulator,
    _classify_one,
    _print_final_report,
    _process_shard_worker,
    _process_task_worker,
    classify_source_shards,
    classify_source_shards_adaptive,
    generate_distribution_report,
    generate_summary_report,
    main,
    merge_and_report,
    merge_classified_files,
    split_single_shard,
)

__all__ = [
    "ALL_SOURCES",
    "DEFAULT_CLASSIFIER_VERSION",
    "DEFAULT_DATA_SNAPSHOT",
    "SourceConfig",
    "SummaryAccumulator",
    "_classify_one",
    "_print_final_report",
    "_process_shard_worker",
    "_process_task_worker",
    "classify_source_shards",
    "classify_source_shards_adaptive",
    "generate_distribution_report",
    "generate_summary_report",
    "main",
    "merge_and_report",
    "merge_classified_files",
    "split_single_shard",
]
