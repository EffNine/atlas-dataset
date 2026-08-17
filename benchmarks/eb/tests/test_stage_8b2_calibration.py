#!/usr/bin/env python3
"""
Stage 8B.2 — Scoring Calibration with Outcome Semantics
Runs scenarios A-T through the revised LongHorizonEvaluator.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from eb.core.schema import StageData, StageResult, Task, TaskResult
from eb.core.types import ExecutionMode, Difficulty, Capability, BenchmarkPartition, EvaluatorStatus
from eb.evaluators.long_horizon import LongHorizonEvaluator


def make_task(stages_defs: list[dict], **overrides) -> Task:
    defaults = {
        "id": "EB-CAL-001",
        "category": "engineering",
        "mode": ExecutionMode.LONG,
        "difficulty": Difficulty.L3,
        "capabilities": [Capability.ADVISORY],
        "prompt": "Calibration task",
        "partition": BenchmarkPartition.DEVELOPMENT,
        "context": {"stages": stages_defs},
    }
    defaults.update(overrides)
    return Task.model_validate(defaults)


def calibrate(name: str, task: Task, result: TaskResult) -> dict:
    evaluator = LongHorizonEvaluator()
    ev = evaluator.evaluate(task, result)
    return {
        "name": name,
        "score": ev.score,
        "outcome": ev.status.value,
        "evidence": ev.evidence,
        "flags": ev.flags,
        "details": ev.details,
    }


def run_calibration():
    print("=" * 70)
    print("Stage 8B.2 — Scoring Calibration (A–T)")
    print("=" * 70)

    results = []

    # A. All stages succeed
    task = make_task([
        {"id": "s1", "name": "S1", "prompt": "P1"},
        {"id": "s2", "name": "S2", "prompt": "P2"},
        {"id": "s3", "name": "S3", "prompt": "P3", "terminal": True},
    ])
    result = TaskResult(
        task_id="EB-CAL-001", run_id="r1",
        stage_results=[
            StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
            StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=1.0),
            StageResult(stage_id="s3", stage_name="S3", status="SUCCESS", score=1.0),
        ],
        raw_response="All tests passed successfully",
    )
    results.append(calibrate("A. all_stages_succeed", task, result))

    # B. Early stage fails
    task = make_task([
        {"id": "s1", "name": "S1", "prompt": "P1"},
        {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
    ])
    result = TaskResult(
        task_id="EB-CAL-001", run_id="r1",
        stage_results=[
            StageResult(stage_id="s1", stage_name="S1", status="FAILED", score=0.0),
            StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=1.0),
        ],
    )
    results.append(calibrate("B. early_stage_fails", task, result))

    # C. Middle stage fails
    task = make_task([
        {"id": "s1", "name": "S1", "prompt": "P1"},
        {"id": "s2", "name": "S2", "prompt": "P2"},
        {"id": "s3", "name": "S3", "prompt": "P3", "terminal": True},
    ])
    result = TaskResult(
        task_id="EB-CAL-001", run_id="r1",
        stage_results=[
            StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
            StageResult(stage_id="s2", stage_name="S2", status="FAILED", score=0.0),
            StageResult(stage_id="s3", stage_name="S3", status="SUCCESS", score=1.0),
        ],
    )
    results.append(calibrate("C. middle_stage_fails", task, result))

    # D. Terminal stage fails
    task = make_task([
        {"id": "s1", "name": "S1", "prompt": "P1"},
        {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
    ])
    result = TaskResult(
        task_id="EB-CAL-001", run_id="r1",
        stage_results=[
            StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
            StageResult(stage_id="s2", stage_name="S2", status="FAILED", score=0.0),
        ],
    )
    results.append(calibrate("D. terminal_stage_fails", task, result))

    # E. Strong implementation / weak delivery
    task = make_task([
        {"id": "s1", "name": "S1", "prompt": "P1"},
        {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
    ], context={"delivery_criteria": {"checks": [{"type": "contains", "value": "delivered"}]}})
    result = TaskResult(
        task_id="EB-CAL-001", run_id="r1",
        stage_results=[
            StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
            StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=0.2),
        ],
        raw_response="Implementation complete but no delivery confirmation",
    )
    results.append(calibrate("E. strong_impl_weak_delivery", task, result))

    # F. Weak early progress / strong final delivery
    task = make_task([
        {"id": "s1", "name": "S1", "prompt": "P1"},
        {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
    ], context={"delivery_criteria": {"checks": [{"type": "contains", "value": "delivered"}]}})
    result = TaskResult(
        task_id="EB-CAL-001", run_id="r1",
        stage_results=[
            StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=0.2),
            StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=1.0),
        ],
        raw_response="Task delivered successfully",
    )
    results.append(calibrate("F. weak_early_strong_final", task, result))

    # G. Requirement change succeeds
    task = make_task([
        {"id": "s1", "name": "S1", "prompt": "P1"},
        {"id": "s2", "name": "S2", "prompt": "P2", "requirement_change": {"from": "a", "to": "b"}},
        {"id": "s3", "name": "S3", "prompt": "P3", "terminal": True},
    ])
    result = TaskResult(
        task_id="EB-CAL-001", run_id="r1",
        stage_results=[
            StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
            StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=1.0),
            StageResult(stage_id="s3", stage_name="S3", status="SUCCESS", score=1.0),
        ],
        raw_response="All stages including requirement change completed",
    )
    results.append(calibrate("G. requirement_change_succeeds", task, result))

    # H. Requirement change fails
    task = make_task([
        {"id": "s1", "name": "S1", "prompt": "P1"},
        {"id": "s2", "name": "S2", "prompt": "P2", "requirement_change": {"from": "a", "to": "b"}},
        {"id": "s3", "name": "S3", "prompt": "P3", "terminal": True},
    ])
    result = TaskResult(
        task_id="EB-CAL-001", run_id="r1",
        stage_results=[
            StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
            StageResult(stage_id="s2", stage_name="S2", status="FAILED", score=0.0),
            StageResult(stage_id="s3", stage_name="S3", status="SUCCESS", score=1.0),
        ],
    )
    results.append(calibrate("H. requirement_change_fails", task, result))

    # I. Adapter error
    task = make_task([
        {"id": "s1", "name": "S1", "prompt": "P1"},
        {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
    ])
    result = TaskResult(
        task_id="EB-CAL-001", run_id="r1",
        stage_results=[
            StageResult(stage_id="s1", stage_name="S1", status="ERROR", score=None, error="boom"),
            StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=1.0),
        ],
    )
    results.append(calibrate("I. adapter_error", task, result))

    # J. Empty / no-op case
    task = make_task([])
    result = TaskResult(task_id="EB-CAL-001", run_id="r1", stage_results=[])
    results.append(calibrate("J. empty_no_op", task, result))

    # K. All stages pass but final delivery fails
    task = make_task([
        {"id": "s1", "name": "S1", "prompt": "P1"},
        {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
    ], context={"delivery_criteria": {"checks": [{"type": "contains", "value": "delivered"}]}})
    result = TaskResult(
        task_id="EB-CAL-001", run_id="r1",
        stage_results=[
            StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
            StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=1.0),
        ],
        raw_response="No delivery confirmation here",
    )
    results.append(calibrate("K. all_pass_delivery_fails", task, result))

    # L. First stage passes, all later stages fail
    task = make_task([
        {"id": "s1", "name": "S1", "prompt": "P1"},
        {"id": "s2", "name": "S2", "prompt": "P2"},
        {"id": "s3", "name": "S3", "prompt": "P3", "terminal": True},
    ])
    result = TaskResult(
        task_id="EB-CAL-001", run_id="r1",
        stage_results=[
            StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
            StageResult(stage_id="s2", stage_name="S2", status="FAILED", score=0.0),
            StageResult(stage_id="s3", stage_name="S3", status="FAILED", score=0.0),
        ],
    )
    results.append(calibrate("L. first_pass_later_fail", task, result))

    # M. Only optional stage fails
    task = make_task([
        {"id": "s1", "name": "S1", "prompt": "P1"},
        {"id": "s2", "name": "S2", "prompt": "P2"},
        {"id": "s3", "name": "S3", "prompt": "P3"},
    ])
    result = TaskResult(
        task_id="EB-CAL-001", run_id="r1",
        stage_results=[
            StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
            StageResult(stage_id="s2", stage_name="S2", status="FAILED", score=0.0),
            StageResult(stage_id="s3", stage_name="S3", status="SUCCESS", score=1.0),
        ],
    )
    results.append(calibrate("M. optional_stage_fails", task, result))

    # N. Required stage fails but later stages produce useful artifacts
    task = make_task([
        {"id": "s1", "name": "S1", "prompt": "P1"},
        {"id": "s2", "name": "S2", "prompt": "P2"},
        {"id": "s3", "name": "S3", "prompt": "P3", "terminal": True},
    ])
    result = TaskResult(
        task_id="EB-CAL-001", run_id="r1",
        stage_results=[
            StageResult(stage_id="s1", stage_name="S1", status="FAILED", score=0.0),
            StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=0.8),
            StageResult(stage_id="s3", stage_name="S3", status="SUCCESS", score=0.9),
        ],
    )
    results.append(calibrate("N. required_fails_useful_later", task, result))

    # O. Requirement changes twice and both adaptations succeed
    task = make_task([
        {"id": "s1", "name": "S1", "prompt": "P1"},
        {"id": "s2", "name": "S2", "prompt": "P2", "requirement_change": {"from": "a", "to": "b"}},
        {"id": "s3", "name": "S3", "prompt": "P3", "requirement_change": {"from": "b", "to": "c"}},
        {"id": "s4", "name": "S4", "prompt": "P4", "terminal": True},
    ])
    result = TaskResult(
        task_id="EB-CAL-001", run_id="r1",
        stage_results=[
            StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
            StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=1.0),
            StageResult(stage_id="s3", stage_name="S3", status="SUCCESS", score=1.0),
            StageResult(stage_id="s4", stage_name="S4", status="SUCCESS", score=1.0),
        ],
        raw_response="All changes adapted and delivered",
    )
    results.append(calibrate("O. req_change_twice_both_succeed", task, result))

    # P. Requirement changes then adaptation fails
    task = make_task([
        {"id": "s1", "name": "S1", "prompt": "P1"},
        {"id": "s2", "name": "S2", "prompt": "P2", "requirement_change": {"from": "a", "to": "b"}},
        {"id": "s3", "name": "S3", "prompt": "P3", "terminal": True},
    ])
    result = TaskResult(
        task_id="EB-CAL-001", run_id="r1",
        stage_results=[
            StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
            StageResult(stage_id="s2", stage_name="S2", status="FAILED", score=0.0),
            StageResult(stage_id="s3", stage_name="S3", status="SUCCESS", score=1.0),
        ],
    )
    results.append(calibrate("P. req_change_then_adapt_fails", task, result))

    # Q. Terminal stage passes but critical test suite fails
    task = make_task([
        {"id": "s1", "name": "S1", "prompt": "P1"},
        {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
    ], context={"delivery_criteria": {"checks": [
        {"type": "contains", "value": "passed"},
        {"type": "contains", "value": "tests"},
    ]}})
    result = TaskResult(
        task_id="EB-CAL-001", run_id="r1",
        stage_results=[
            StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=1.0),
            StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=0.5),
        ],
        raw_response="Some output but tests failed",
    )
    results.append(calibrate("Q. terminal_passes_tests_fail", task, result))

    # R. All stages succeed with low-quality scores
    task = make_task([
        {"id": "s1", "name": "S1", "prompt": "P1"},
        {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
    ])
    result = TaskResult(
        task_id="EB-CAL-001", run_id="r1",
        stage_results=[
            StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=0.3),
            StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=0.2),
        ],
    )
    results.append(calibrate("R. all_low_quality", task, result))

    # S. All stages succeed with high-quality scores
    task = make_task([
        {"id": "s1", "name": "S1", "prompt": "P1"},
        {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
    ])
    result = TaskResult(
        task_id="EB-CAL-001", run_id="r1",
        stage_results=[
            StageResult(stage_id="s1", stage_name="S1", status="SUCCESS", score=0.9),
            StageResult(stage_id="s2", stage_name="S2", status="SUCCESS", score=0.95),
        ],
    )
    results.append(calibrate("S. all_high_quality", task, result))

    # T. Sandbox failure before Stage 1 (no stages executed)
    task = make_task([
        {"id": "s1", "name": "S1", "prompt": "P1"},
        {"id": "s2", "name": "S2", "prompt": "P2", "terminal": True},
    ])
    result = TaskResult(task_id="EB-CAL-001", run_id="r1", stage_results=[])
    results.append(calibrate("T. sandbox_failure_no_stages", task, result))

    # Print results
    print(f"\n{'#':>2}  {'Scenario':<38} {'Score':>8} {'Outcome':<12} {'Gates'}")
    print("-" * 100)
    for r in results:
        gates = ", ".join(r["flags"]) if r["flags"] else "-"
        score_str = f"{r['score']:.4f}" if r["score"] is not None else "N/A"
        print(f"  {results.index(r)+1:2d}  {r['name']:<38} {score_str:>8} {r['outcome']:<12} {gates}")

    # Required expectations check
    print("\n" + "=" * 70)
    print("REQUIRED EXPECTATIONS CHECK")
    print("=" * 70)

    checks = {
        "A. all_stages_succeed": {"outcome": "PASS", "score_min": 0.9},
        "B. early_stage_fails": {"outcome_not": "PASS"},
        "C. middle_stage_fails": {"outcome_not": "PASS"},
        "D. terminal_stage_fails": {"outcome": "FAIL", "score": 0.0},
        "E. strong_impl_weak_delivery": {"outcome_not": "PASS"},
        "F. weak_early_strong_final": {"outcome": "PASS"},
        "G. requirement_change_succeeds": {"outcome": "PASS", "score_min": 0.9},
        "H. requirement_change_fails": {"outcome_not": "PASS"},
        "I. adapter_error": {"outcome": "FAIL"},
        "J. empty_no_op": {"outcome": "NOT_APPLICABLE"},
        "K. all_pass_delivery_fails": {"outcome_not": "PASS"},
        "L. first_pass_later_fail": {"outcome_not": "PASS"},
        "M. optional_stage_fails": {"outcome_not": "PASS"},
        "N. required_fails_useful_later": {"outcome_not": "PASS"},
        "O. req_change_twice_both_succeed": {"outcome": "PASS"},
        "P. req_change_then_adapt_fails": {"outcome_not": "PASS"},
        "Q. terminal_passes_tests_fail": {"outcome_not": "PASS"},
        "R. all_low_quality": {"outcome": "PASS"},  # All stages SUCCESS → PASS even if low quality
        "S. all_high_quality": {"outcome": "PASS", "score_min": 0.9},
        "T. sandbox_failure_no_stages": {"outcome": "NOT_APPLICABLE"},
    }

    all_pass = True
    for r in results:
        name = r["name"]
        if name not in checks:
            continue
        expected = checks[name]
        ok = True
        reasons = []
        if "outcome" in expected and r["outcome"] != expected["outcome"]:
            ok = False
            reasons.append(f"expected={expected['outcome']} got={r['outcome']}")
        if "outcome_not" in expected and r["outcome"] == expected["outcome_not"]:
            ok = False
            reasons.append(f"must not be {expected['outcome_not']}")
        if "score" in expected and r["score"] != expected["score"]:
            ok = False
            reasons.append(f"expected_score={expected['score']} got={r['score']}")
        if "score_min" in expected and (r["score"] or 0) < expected["score_min"]:
            ok = False
            reasons.append(f"score {r['score']} < min {expected['score_min']}")
        status = "OK" if ok else f"FAIL ({', '.join(reasons)})"
        if not ok:
            all_pass = False
        print(f"  [{status:>30s}] {name}")

    print()
    if all_pass:
        print("ALL CHECKS PASSED")
    else:
        print("SOME CHECKS FAILED")

    return all_pass


if __name__ == "__main__":
    sys.exit(0 if run_calibration() else 1)
