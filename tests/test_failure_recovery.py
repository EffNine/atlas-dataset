#!/usr/bin/env python3
"""Tests for Atlas Automation Layer Failure Recovery v1.

Covers:
  - RetryManager: history persistence, retry counts
  - retry: failed quality → retry → success
  - retry: failed quality → retry → fail again
  - retry: failed validation → retry → success
  - retry: failed validation → retry → fail again
  - retry: pipeline not in FAILED state
  - retry: no failure_info
  - resume: failed pipeline → resume → success
  - resume: failed pipeline → resume → fail again
  - resume: pipeline not failed (no-op)
  - retry history persistence across loads
  - Immutable directory protection
"""

from __future__ import annotations

import json
import sys
import tempfile
import shutil
from pathlib import Path
from typing import Any

# Ensure the scripts directory is importable
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

from automation.state_machine import PipelineState, StateMachine
from automation.pipeline_orchestrator import PipelineStatus
from automation.failure_recovery import (
    RetryManager,
    retry_failed_agent,
    resume_pipeline,
)
from automation.base_agent import AgentResult, AgentStatus


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_failure_env() -> Path:
    """Create a temp atlas root with scripts copied."""
    tmp = Path(tempfile.mkdtemp())
    for d in ("metadata", "curated/v0.1", "tmp", "scripts"):
        (tmp / d).mkdir(parents=True, exist_ok=True)
    src = Path(__file__).resolve().parent.parent / "scripts"
    for item in src.iterdir():
        if item.is_file() and item.suffix == ".py" and not item.name.startswith("_"):
            (tmp / "scripts" / item.name).write_text(
                item.read_text(encoding="utf-8"), encoding="utf-8"
            )
    auto_dst = tmp / "scripts" / "automation"
    auto_dst.mkdir(exist_ok=True)
    for item in (src / "automation").iterdir():
        if item.is_file() and item.suffix == ".py":
            (auto_dst / item.name).write_text(
                item.read_text(encoding="utf-8"), encoding="utf-8"
            )
    return tmp


def _write_jsonl(path: Path, records: list[dict]) -> None:
    """Write records as JSONL to path."""
    path.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )


_HIGH_QUALITY_RECORD = {
    "id": "01_foundation_reasoning_0001",
    "category": "01_foundation",
    "subcategory": "reasoning",
    "type": "instruction",
    "source": {"name": "test", "license": "MIT"},
    "messages": [
        {
            "role": "user",
            "content": "Explain the concept of encapsulation in object-oriented programming.",
        },
        {
            "role": "assistant",
            "content": (
                "Encapsulation is a fundamental principle of object-oriented programming "
                "that bundles data (attributes) and methods (functions) that operate on "
                "that data into a single unit called a class. It restricts direct access "
                "to an object's internal state, exposing only what is necessary through "
                "controlled public interfaces.\n\n"
                "For example, a BankAccount class might have a private _balance field that "
                "can only be modified through deposit() and withdraw() methods, which "
                "enforce validation rules like preventing negative balances.\n\n"
                "```python\n"
                "class BankAccount:\n"
                "    def __init__(self):\n"
                "        self._balance = 0\n"
                "    def deposit(self, amount):\n"
                "        if amount > 0:\n"
                "            self._balance += amount\n"
                "    def get_balance(self):\n"
                "        return self._balance\n"
                "```\n\n"
                "The key benefits of encapsulation include: reduced complexity through "
                "information hiding, increased maintainability by decoupling interface "
                "from implementation, and improved security by preventing unauthorized "
                "access to internal state."
            ),
        },
    ],
    "language": "en",
    "difficulty": 2,
    "tags": ["oop", "encapsulation", "python"],
    "quality_score": 9,
    "verified": True,
    "notes": "Quality test record — high quality.",
}

_LOW_QUALITY_RECORD = {
    "id": "99_generic_trash_9999",
    "category": "01_foundation",
    "subcategory": "instruction-following",
    "type": "instruction",
    "source": {"name": "test", "license": "MIT"},
    "messages": [
        {"role": "user", "content": "What is AI?"},
        {"role": "assistant", "content": "Sure, here is a definition of AI."},
    ],
    "language": "en",
    "difficulty": 0,
    "tags": [],
    "quality_score": 3,
    "verified": False,
    "notes": "Quality test record — low quality.",
}


def _simulate_quality_failure(tmp: Path, pipeline_id: str = "test-fail-quality") -> StateMachine:
    """Create a pipeline in FAILED state due to quality failure.

    Sets up a low-quality record so QualityAgent fails, then runs
    the pipeline to produce a FAILED state.

    Returns the loaded StateMachine.
    """
    dspath = tmp / "curated" / "v0.1" / "pilot_candidates.jsonl"
    _write_jsonl(dspath, [_LOW_QUALITY_RECORD])

    from automation.pipeline_orchestrator import PipelineOrchestrator
    orch = PipelineOrchestrator(pipeline_id, tmp)
    result = orch.run_to_approval()
    # Quality should fail — pipeline should be FAILED
    sm = StateMachine(pipeline_id, tmp)
    sm.load()
    return sm


def _simulate_validation_failure(tmp: Path, pipeline_id: str = "test-fail-val") -> StateMachine:
    """Create a pipeline in FAILED state due to validation failure.

    Sets up a record with bad data so ValidationAgent fails.
    Quality is set high so it passes, then validation fails.

    Returns the loaded StateMachine.
    """
    dspath = tmp / "curated" / "v0.1" / "pilot_candidates.jsonl"
    # A record that quality will pass but validation will reject
    rec = dict(_HIGH_QUALITY_RECORD, id="bad_val_001", category="invalid_category!!!")
    _write_jsonl(dspath, [rec])

    from automation.pipeline_orchestrator import PipelineOrchestrator
    orch = PipelineOrchestrator(pipeline_id, tmp)
    result = orch.run_to_approval()
    sm = StateMachine(pipeline_id, tmp)
    sm.load()
    return sm


# ===================================================================
# RetryManager: History Persistence
# ===================================================================


def test_retry_manager_empty_history():
    """RetryManager starts with empty history for new pipelines."""
    tmp = _make_failure_env()
    try:
        mgr = RetryManager("test-pipeline", tmp)
        history = mgr.load_history()
        assert history == [], f"Expected empty history, got {history}"
        assert mgr.get_retry_count("quality") == 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_retry_manager_record_and_load():
    """Records are persisted and survive reload."""
    tmp = _make_failure_env()
    try:
        mgr = RetryManager("test-record", tmp)
        record = {
            "failed_agent": "quality",
            "previous_reason": "Low quality score",
            "retry_count": 1,
            "timestamp": "2026-07-29T12:00:00+00:00",
            "result": "success",
        }
        mgr.record_retry(record)

        # Load new instance
        mgr2 = RetryManager("test-record", tmp)
        history = mgr2.load_history()
        assert len(history) == 1
        assert history[0]["failed_agent"] == "quality"
        assert history[0]["result"] == "success"
        assert mgr2.get_retry_count("quality") == 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_retry_manager_multiple_records():
    """Multiple retry records accumulate correctly."""
    tmp = _make_failure_env()
    try:
        mgr = RetryManager("test-multi", tmp)
        for i in range(3):
            mgr.record_retry({
                "failed_agent": "validation",
                "previous_reason": f"Attempt {i+1}",
                "retry_count": i + 1,
                "timestamp": "2026-07-29T12:00:00+00:00",
                "result": "failed" if i < 2 else "success",
            })
        assert mgr.get_retry_count("validation") == 3
        assert mgr.get_retry_count("quality") == 0
        last = mgr.get_last_retry("validation")
        assert last is not None
        assert last["retry_count"] == 3
        assert last["result"] == "success"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_retry_manager_history_path():
    """Retry history is written to metadata/pipeline_retries/."""
    tmp = _make_failure_env()
    try:
        mgr = RetryManager("test-path", tmp)
        mgr.record_retry({
            "failed_agent": "quality",
            "previous_reason": "Test",
            "retry_count": 1,
            "timestamp": "2026-07-29T12:00:00+00:00",
            "result": "success",
        })
        expected_path = tmp / "metadata" / "pipeline_retries" / "test-path.json"
        assert expected_path.exists(), f"File not found: {expected_path}"
        tmp_resolved = tmp.resolve()
        rel = str(expected_path.resolve().relative_to(tmp_resolved))
        assert rel.startswith("metadata/"), (
            f"Retry history outside metadata/: {rel}"
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ===================================================================
# Qualtiy Failure → Retry → Success
# ===================================================================


def test_retry_quality_failure_to_success():
    """Failed quality agent can be retried after fixing data.

    Pipeline FAILED → retry quality only → quality passes → pipeline continues.
    """
    tmp = _make_failure_env()
    try:
        pipeline_id = "test-retry-qual-success"
        dspath = tmp / "curated" / "v0.1" / "pilot_candidates.jsonl"

        # Phase 1: Fail quality with low-quality data
        _write_jsonl(dspath, [_LOW_QUALITY_RECORD])
        from automation.pipeline_orchestrator import PipelineOrchestrator
        orch = PipelineOrchestrator(pipeline_id, tmp)
        r1 = orch.run_to_approval()
        assert r1.status == PipelineStatus.FAILED, f"Expected FAILED, got {r1.status}"
        assert "quality" in r1.agent_results
        assert not r1.agent_results["quality"].passed

        # Phase 2: Fix data — replace with high-quality records
        _write_jsonl(dspath, [_HIGH_QUALITY_RECORD])

        # Phase 3: Retry quality agent
        result = retry_failed_agent(pipeline_id, tmp)
        assert result["retry_result"] == "success", (
            f"Expected retry success, got {result['retry_result']}: "
            f"{result.get('message', '')}"
        )
        assert result["agent_name"] == "quality"
        assert result["agent_result"]["status"] == "passed"

        # Pipeline should have continued and reached at least WAITING_HUMAN_APPROVAL
        pipeline_result = result["pipeline_result"]
        assert pipeline_result["status"] != "failed", (
            f"Pipeline should not be failed after successful retry: "
            f"{pipeline_result.get('summary', '')}"
        )

        # Retry record should exist
        mgr = RetryManager(pipeline_id, tmp)
        assert mgr.get_retry_count("quality") == 1
        last = mgr.get_last_retry("quality")
        assert last is not None
        assert last["result"] == "success"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ===================================================================
# Quality Failure → Retry → Fail Again
# ===================================================================


def test_retry_quality_failure_to_fail_again():
    """Retrying a failed quality agent that fails again stays FAILED."""
    tmp = _make_failure_env()
    try:
        pipeline_id = "test-retry-qual-fail"
        dspath = tmp / "curated" / "v0.1" / "pilot_candidates.jsonl"

        # Phase 1: Fail quality with low-quality data
        _write_jsonl(dspath, [_LOW_QUALITY_RECORD])
        from automation.pipeline_orchestrator import PipelineOrchestrator
        orch = PipelineOrchestrator(pipeline_id, tmp)
        r1 = orch.run_to_approval()
        assert r1.status == PipelineStatus.FAILED

        # Phase 2: Retry WITHOUT fixing data — should fail again
        result = retry_failed_agent(pipeline_id, tmp)
        assert result["retry_result"] == "failed", (
            f"Expected retry to fail again, got {result['retry_result']}"
        )
        assert result["agent_name"] == "quality"
        assert result["agent_result"]["status"] == "failed"

        # Pipeline should still be FAILED
        sm = StateMachine(pipeline_id, tmp)
        sm.load()
        assert sm.current_state == PipelineState.FAILED, (
            f"Pipeline should remain FAILED after failed retry, "
            f"got {sm.current_state}"
        )

        # Retry record should show failure
        mgr = RetryManager(pipeline_id, tmp)
        assert mgr.get_retry_count("quality") == 1
        last = mgr.get_last_retry("quality")
        assert last is not None
        assert last["result"] == "failed"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ===================================================================
# Validation Failure → Retry → Success
# ===================================================================


def test_retry_validation_failure_to_success():
    """Failed validation agent can be retried after fixing data."""
    tmp = _make_failure_env()
    try:
        pipeline_id = "test-retry-val-success"
        dspath = tmp / "curated" / "v0.1" / "pilot_candidates.jsonl"

        # Phase 1: Fail validation with bad data
        rec = dict(_HIGH_QUALITY_RECORD, id="bad_val_001",
                   category="invalid_category!!!")
        _write_jsonl(dspath, [rec])

        from automation.pipeline_orchestrator import PipelineOrchestrator
        orch = PipelineOrchestrator(pipeline_id, tmp)
        r1 = orch.run_to_approval()
        assert r1.status == PipelineStatus.FAILED, f"Expected FAILED, got {r1.status}"
        # Verify it failed on validation
        if "validation" in r1.agent_results:
            assert not r1.agent_results["validation"].passed

        # Phase 2: Fix data
        _write_jsonl(dspath, [_HIGH_QUALITY_RECORD])

        # Phase 3: Retry validation
        result = retry_failed_agent(pipeline_id, tmp)
        assert result["retry_result"] == "success", (
            f"Expected retry success, got {result['retry_result']}: "
            f"{result.get('message', '')}"
        )
        assert result["agent_name"] == "validation"

        # Pipeline should have continued
        pipeline_result = result["pipeline_result"]
        assert pipeline_result["status"] != "failed"

        # Retry record
        mgr = RetryManager(pipeline_id, tmp)
        assert mgr.get_retry_count("validation") == 1
        last = mgr.get_last_retry("validation")
        assert last is not None
        assert last["result"] == "success"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ===================================================================
# Validation Failure → Retry → Fail Again
# ===================================================================


def test_retry_validation_failure_to_fail_again():
    """Retrying a failed validation agent that fails again stays FAILED."""
    tmp = _make_failure_env()
    try:
        pipeline_id = "test-retry-val-fail"
        dspath = tmp / "curated" / "v0.1" / "pilot_candidates.jsonl"

        # Phase 1: Fail validation
        rec = dict(_HIGH_QUALITY_RECORD, id="bad_val_001",
                   category="invalid_category!!!")
        _write_jsonl(dspath, [rec])

        from automation.pipeline_orchestrator import PipelineOrchestrator
        orch = PipelineOrchestrator(pipeline_id, tmp)
        r1 = orch.run_to_approval()
        assert r1.status == PipelineStatus.FAILED

        # Phase 2: Retry WITHOUT fixing data
        result = retry_failed_agent(pipeline_id, tmp)
        assert result["retry_result"] == "failed", (
            f"Expected retry to fail again, got {result['retry_result']}"
        )
        assert result["agent_name"] == "validation"

        # Pipeline stays FAILED
        sm = StateMachine(pipeline_id, tmp)
        sm.load()
        assert sm.current_state == PipelineState.FAILED
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ===================================================================
# Retry: Pipeline Not in FAILED State
# ===================================================================


def test_retry_not_failed():
    """Retry on a pipeline that is not FAILED returns skipped."""
    tmp = _make_failure_env()
    try:
        pipeline_id = "test-retry-not-failed"
        result = retry_failed_agent(pipeline_id, tmp)
        assert result["retry_result"] == "skipped", (
            f"Expected skipped, got {result['retry_result']}"
        )
        assert "error" in result, "Expected error message"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_retry_no_failure_info():
    """Retry on a pipeline that is FAILED but has no failure_info returns skipped."""
    tmp = _make_failure_env()
    try:
        pipeline_id = "test-retry-no-fi"
        # Manually set to FAILED without failure_info
        sm = StateMachine(pipeline_id, tmp)
        sm.transition_to(PipelineState.FAILED, triggered_by="test")

        result = retry_failed_agent(pipeline_id, tmp)
        assert result["retry_result"] == "skipped", (
            f"Expected skipped, got {result['retry_result']}"
        )
        assert "has no failure_info" in result.get("error", ""), (
            f"Expected 'no failure_info' error, got: {result.get('error', '')}"
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ===================================================================
# Resume: Failed Pipeline → Success
# ===================================================================


def test_resume_quality_failure_to_success():
    """Resume clears failure and continues the full pipeline after fixing data."""
    tmp = _make_failure_env()
    try:
        pipeline_id = "test-resume-qual-success"
        dspath = tmp / "curated" / "v0.1" / "pilot_candidates.jsonl"

        # Phase 1: Fail quality
        _write_jsonl(dspath, [_LOW_QUALITY_RECORD])
        from automation.pipeline_orchestrator import PipelineOrchestrator
        orch = PipelineOrchestrator(pipeline_id, tmp)
        r1 = orch.run_to_approval()
        assert r1.status == PipelineStatus.FAILED

        # Phase 2: Fix data
        _write_jsonl(dspath, [_HIGH_QUALITY_RECORD])

        # Phase 3: Resume (clear failure, run full pipeline)
        result = resume_pipeline(pipeline_id, tmp)
        assert result["resume_result"] == "success", (
            f"Expected resume success, got {result['resume_result']}: "
            f"{result.get('message', '')}"
        )

        pipeline_result = result["pipeline_result"]
        assert pipeline_result["status"] != "failed", (
            f"Pipeline should not be failed after resume: "
            f"{pipeline_result.get('summary', '')}"
        )

        # Pipeline should have advanced past INGESTED
        assert pipeline_result["current_state"] != "INGESTED"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ===================================================================
# Resume: Failed Pipeline → Fail Again
# ===================================================================


def test_resume_quality_failure_to_fail_again():
    """Resume with still-broken data results in pipeline failing again."""
    tmp = _make_failure_env()
    try:
        pipeline_id = "test-resume-qual-fail"
        dspath = tmp / "curated" / "v0.1" / "pilot_candidates.jsonl"

        # Phase 1: Fail quality
        _write_jsonl(dspath, [_LOW_QUALITY_RECORD])
        from automation.pipeline_orchestrator import PipelineOrchestrator
        orch = PipelineOrchestrator(pipeline_id, tmp)
        r1 = orch.run_to_approval()
        assert r1.status == PipelineStatus.FAILED

        # Phase 2: Resume WITHOUT fixing data
        result = resume_pipeline(pipeline_id, tmp)
        assert result["resume_result"] == "failed", (
            f"Expected resume to fail again, got {result['resume_result']}"
        )

        # Pipeline should be back in FAILED state
        sm = StateMachine(pipeline_id, tmp)
        sm.load()
        assert sm.current_state == PipelineState.FAILED
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ===================================================================
# Resume: Pipeline Not Failed
# ===================================================================


def test_resume_not_failed():
    """Resume on a non-failed pipeline returns skipped (acts as no-op)."""
    tmp = _make_failure_env()
    try:
        pipeline_id = "test-resume-not-failed"
        result = resume_pipeline(pipeline_id, tmp)
        assert result["resume_result"] == "skipped", (
            f"Expected skipped, got {result['resume_result']}"
        )
        assert result["pipeline_result"] is None, (
            f"Expected no pipeline_result, got {result['pipeline_result']}"
        )
        assert result["current_state"] == "INGESTED", (
            f"Expected INGESTED, got {result['current_state']}"
        )
        # Message should indicate pipeline is not FAILED
        assert "not in FAILED state" in result.get("message", "").lower() or \
               "no resume needed" in result.get("message", "").lower(), (
            f"Expected 'not in FAILED' message, got: {result.get('message', '')}"
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ===================================================================
# Retry History Persistence Across Loads
# ===================================================================


def test_retry_history_survives_reload():
    """Retry history persists across RetryManager reloads."""
    tmp = _make_failure_env()
    try:
        pipeline_id = "test-history-survive"
        dspath = tmp / "curated" / "v0.1" / "pilot_candidates.jsonl"

        # Cause a quality failure, fix, retry
        _write_jsonl(dspath, [_LOW_QUALITY_RECORD])
        from automation.pipeline_orchestrator import PipelineOrchestrator
        orch = PipelineOrchestrator(pipeline_id, tmp)
        orch.run_to_approval()

        _write_jsonl(dspath, [_HIGH_QUALITY_RECORD])
        r1 = retry_failed_agent(pipeline_id, tmp)
        assert r1["retry_result"] == "success"

        # Reload RetryManager — history should still be there
        mgr = RetryManager(pipeline_id, tmp)
        assert mgr.get_retry_count("quality") == 1

        # Verify the history file content
        history_path = tmp / "metadata" / "pipeline_retries" / f"{pipeline_id}.json"
        assert history_path.exists()
        data = json.loads(history_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["failed_agent"] == "quality"
        assert data[0]["result"] == "success"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ===================================================================
# Immutable Directory Protection
# ===================================================================


def test_retry_history_immutable_dirs_protected():
    """Retry history writes to metadata/pipeline_retries/, never curated/."""
    tmp = _make_failure_env()
    try:
        mgr = RetryManager("test-immutable", tmp)
        mgr.record_retry({
            "failed_agent": "quality",
            "previous_reason": "Test",
            "retry_count": 1,
            "timestamp": "2026-07-29T12:00:00+00:00",
            "result": "success",
        })
        history_path = tmp / "metadata" / "pipeline_retries" / "test-immutable.json"
        tmp_resolved = tmp.resolve()
        rel = str(history_path.resolve().relative_to(tmp_resolved))
        assert rel.startswith("metadata/"), (
            f"Retry history outside metadata/: {rel}"
        )

        # Verify curated/ and other immutable dirs are untouched
        for immutable_dir in ("curated", "review_queue", "training_views", "raw"):
            dir_path = tmp / immutable_dir
            if dir_path.exists():
                # Should be empty or not have our file
                assert not any(dir_path.rglob("*.json")), (
                    f"Found files in immutable dir: {immutable_dir}"
                )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
