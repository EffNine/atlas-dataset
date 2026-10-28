"""Atlas Source Discovery v1.0 — automation-first translation data acquisition.

Isolation contract (hard):
  - Writes ONLY under metadata/source_discovery/ and tmp/source_discovery/.
  - NEVER writes to curated/, raw/ (except approved raw/pilot which we do not
    use), review_queue/, training_views/, releases/, translation-ai-v0.1/, or
    any existing Atlas dataset path.
  - No model training. No full-corpus JEV run (smoke-only boundary).
  - Research-grade human calibration is parked, not implemented here.

Pipeline:
  DISCOVER -> VERIFY METADATA -> DOWNLOAD -> HASH -> PARSE -> NORMALIZE
    -> LANGUAGE CHECK -> ALIGNMENT CHECK -> DEDUP -> QUALITY FILTER -> CORPUS
"""

from __future__ import annotations

REGISTRY_VERSION = "1.0"
SCHEMA_ID = "atlas-source-discovery-registry-v1"
