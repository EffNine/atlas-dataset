"""
acquisition_engine — Atlas Acquisition Engine.

Transforms the acquisition manifest into a deterministic, resumable ingestion
workflow with integrity verification, dataset versioning, Knowledge Pack
generation, Knowledge Collections, lifecycle management, Dataset Diff, AQL,
and Release Engineering.

Usage:
    from acquisition_engine import AcquisitionEngine
    engine = AcquisitionEngine("/path/to/atlas-dataset")
    plan = engine.dry_run()
    result = engine.execute()
    engine.resume()
"""

from .engine import AcquisitionEngine, is_denied_license, install_network_block
from .checkpoint import CheckpointManager, EngineCheckpoint, SourceCheckpoint
from .integrity import (
    VerificationLog,
    ChecksumRegistry,
    file_sha256,
    compute_file_checksums,
    verify_stage_integrity,
)
from .lifecycle import LifecycleTracker, LIFECYCLE_STATES, VALID_TRANSITIONS
from .versioning import VersionManager
from .knowledge_pack import generate_knowledge_pack, verify_knowledge_pack
from .knowledge_collection import KnowledgeCollectionManager
from .dataset_diff import compute_diff, render_diff_markdown, load_records_index
from .release import ReleaseManager, ReleaseGates, ReleaseGateResult, SemanticDiff
from .aql import execute_query, preview_query, validate_query, describe_query, AQLQuery

__all__ = [
    "AcquisitionEngine",
    "CheckpointManager",
    "ChecksumRegistry",
    "EngineCheckpoint",
    "KnowledgeCollectionManager",
    "LifecycleTracker",
    "ReleaseGateResult",
    "ReleaseGates",
    "ReleaseManager",
    "SemanticDiff",
    "SourceCheckpoint",
    "VerificationLog",
    "VersionManager",
    "AQLQuery",
    "compute_diff",
    "compute_file_checksums",
    "describe_query",
    "execute_query",
    "file_sha256",
    "generate_knowledge_pack",
    "install_network_block",
    "is_denied_license",
    "LIFECYCLE_STATES",
    "load_records_index",
    "preview_query",
    "render_diff_markdown",
    "validate_query",
    "VALID_TRANSITIONS",
    "verify_knowledge_pack",
    "verify_stage_integrity",
]
