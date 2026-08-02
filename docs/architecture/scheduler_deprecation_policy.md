# Deprecation Policy — Legacy Parallel Modules

**Effective:** Atlas v1.9  
**Removal target:** Atlas v2.0

---

## 1. Overview

The Universal Scheduler (`scripts/parallel/`) is now the single execution layer for all Atlas dataset pipelines. Legacy parallel implementations are deprecated but preserved as backward-compatibility shims to ensure zero-breakage migration.

---

## 2. Deprecated Modules

### 2.1 `scripts/intelligence/adaptive_scheduler.py`

**Status:** Deprecated (v1.9)  
**Removal target:** Atlas v2.0  
**Replaced by:** `scripts/parallel/`

| Old Import | New Import |
|-----------|------------|
| `from adaptive_scheduler import TaskRegistry` | `from parallel.registry import TaskRegistry` |
| `from adaptive_scheduler import plan_tasks` | `from parallel.planner import plan_workload` |
| `from adaptive_scheduler import load_scheduler_config` | `from parallel.config import load_parallelism_config` |
| `from adaptive_scheduler import count_lines` | `from parallel.planner import task_line_range_reader` |
| `from adaptive_scheduler import Task` | `from parallel.models import Task` |

**Behavior:** This module is now a wrapper that:
1. Emits a `DeprecationWarning` on first use
2. Forwards all calls to the corresponding `parallel.*` implementation
3. Maintains the same return types and signatures

### 2.2 `scripts/intelligence/batch_classify.py`

**Status:** Deprecated (v1.9)  
**Removal target:** Atlas v2.0  
**Replaced by:** `scripts/intelligence/batch_classify_v2.py` + `scripts/parallel/`

| Old Import | New Import |
|-----------|------------|
| `from batch_classify import SourceConfig` | `from batch_classify_v2 import SourceConfig` |
| `from batch_classify import classify_source_shards` | Use `batch_classify_v2._classify_one()` + scheduler |
| `from batch_classify import merge_and_report` | `from batch_classify_v2 import merge_and_report` |
| `from batch_classify import split_single_shard` | `from parallel.planner import byte_range_tasks` |

**Behavior:** This module is now a wrapper that:
1. Emits a `DeprecationWarning` on first use
2. Forwards all function calls to `batch_classify_v2` implementations
3. Maintains the same return types and signatures

---

## 3. Migration Guide

### 3.1 For Pipeline Authors

Replace any imports from deprecated modules:

```python
# OLD (deprecated)
from adaptive_scheduler import TaskRegistry, plan_tasks, load_scheduler_config
from batch_classify import SourceConfig, classify_source_shards

# NEW (current)
from parallel.registry import TaskRegistry
from parallel.planner import plan_workload
from parallel.config import load_parallelism_config
from batch_classify_v2 import SourceConfig
```

### 3.2 For End Users

No changes required. Deprecation warnings appear in stderr but execution continues.

---

## 4. Deprecation Warning Behavior

All deprecated modules use Python's standard `warnings.warn()` with `DeprecationWarning`:

```python
import warnings
warnings.warn(
    "adaptive_scheduler is deprecated and will be removed in Atlas v2.0. "
    "Use scripts/parallel/ instead.",
    DeprecationWarning,
    stacklevel=2,
)
```

Warnings are emitted once per import/module, not per-call (using Python's default deprecation filter).

---

## 5. Removal Timeline

| Phase | Date | Action |
|-------|------|--------|
| v1.9 (current) | 2026-08-02 | Modules deprecated, wrappers in place |
| v2.0 (target) | TBD | Modules removed, warnings become errors |

Before v2.0 release:
- All deprecated imports must be replaced in codebase
- Tests must pass without deprecation warnings
- Documentation must reference new paths only

---

## 6. Acceptance Criteria for Removal

To remove a deprecated module in v2.0:

1. [ ] No remaining imports of the deprecated module (grep check)
2. [ ] All tests pass without deprecation warnings
3. [ ] Documentation updated to reference new paths
4. [ ] Changelog entry documenting the removal
5. [ ] Migration guide in `docs/migration/` for external users