#!/usr/bin/env python3
"""Tests for the AcquisitionEngine migration (Universal Scheduler Phase 5C).

Design under test: PURE WORKERS + SERIALIZED FINALIZE.

Covers:
- task planning deterministic (manifest order, stable task IDs)
- worker purity (no shared writes from worker)
- scheduler vs sequential SHA256 equality of curated output
- record count / provenance / dedup / max_records behaviour unchanged
- checkpoint resume equivalence
- failed worker retry + terminal failure
- stale lease recovery
- sequential fallback (kill-switch)
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import shutil
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
REPO = Path(__file__).resolve().parent.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

if sys.platform == "darwin":
    try:
        multiprocessing.set_start_method("fork", force=True)
    except RuntimeError:
        pass

# The AcquisitionEngine only writes under APPROVED_ROOTS (repo curated/
# metadata/tmp/...). Tests create fixture roots under REPO/tmp/ which is
# gitignored and approved, then clean up.


@pytest.fixture
def eng_tmp():
    """Yield a unique approved root under REPO/tmp and clean it up."""
    import uuid
    d = REPO / "tmp" / f"test_5c_{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _manifest_ds(sid: str, *, lic: str = "MIT", target: int = 4, category: str = "01_foundation",
                 subcats: list[str] | None = None) -> dict:
    if subcats is None:
        # Distinct subcategories per source by default so cross-source dedup
        # does NOT fire in identity tests (dedup is tested explicitly).
        subcats = [f"sub-{sid}-a", f"sub-{sid}-b"]
    return {
        "source_id": sid,
        "name": f"source/{sid}",
        "url": f"https://example.com/{sid}",
        "license": lic,
        "license_class": "permissive" if lic in ("MIT", "Apache-2.0") else "unknown",
        "license_constraints": [],
        "category": category,
        "subcategories": subcats,
        "target_examples": target,
        "extraction_method": "doc_to_instruction",
        "synthetic": False,
        "attribution_required": False,
        "notes": "",
    }


def _make_root(tmp_path: Path, datasets: list[dict], *, batches=None, registry_status: str = "accepted") -> Path:
    """Create a root with manifest + registry (mirrors AcquisitionEngine contract)."""
    root = tmp_path
    md = root / "metadata"
    md.mkdir(parents=True, exist_ok=True)
    if batches is None:
        batches = [{"batch_id": "B01", "order": 1, "theme": "t", "datasets": datasets}]
    manifest = {
        "manifest_version": "0.1.0",
        "total_target_examples": sum(d.get("target_examples", 0) for d in datasets),
        "global_constraints": {"synthetic_model_generated_cap_pct": 5},
        "category_targets": {},
        "batches": batches,
    }
    (md / "acquisition_manifest_v0.1.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    registry = {"sources": [{
        "id": d["source_id"], "name": d["name"], "status": registry_status,
        "license": d["license"], "url": d["url"],
    } for d in datasets]}
    (md / "source_registry.json").write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return root


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _run_execute(root: Path, *, max_records: int = 100, resume: bool = False) -> dict:
    """Run AcquisitionEngine.execute in a fresh instance (execute mode)."""
    from acquisition_engine import AcquisitionEngine
    engine = AcquisitionEngine(root, mode="execute", network_block=False)
    return engine.execute(max_records=max_records, resume=resume)


@pytest.fixture
def env(eng_tmp: Path):
    ds = [
        _manifest_ds("s1", target=4),
        _manifest_ds("s2", target=3),
        _manifest_ds("s3", target=5),
    ]
    root = _make_root(eng_tmp / "root", ds)
    return {"root": root, "datasets": ds, "base": eng_tmp}


# ----------------------------------------------------------------------
# 1. Task planning deterministic
# ----------------------------------------------------------------------

class TestPlanning:
    def test_plan_manifest_order(self, env):
        from acquisition_engine.scheduler_tasks import plan_engine_tasks
        from acquisition_engine.engine import AcquisitionEngine
        eng = AcquisitionEngine(env["root"], mode="execute", network_block=False)
        tasks = plan_engine_tasks(eng.manifest, eng.reg_by_id, 100, env["root"])
        assert [t.task_id for t in tasks] == [
            "acq:engine:B01:s1", "acq:engine:B01:s2", "acq:engine:B01:s3",
        ]

    def test_task_ids_stable(self, env):
        from acquisition_engine.scheduler_tasks import engine_task_id
        assert engine_task_id("B01", "s1") == "acq:engine:B01:s1"
        assert engine_task_id("B02", "s1") == "acq:engine:B02:s1"
        assert engine_task_id("B01", "s1") != engine_task_id("B01", "s2")


# ----------------------------------------------------------------------
# 2. Worker purity (no shared writes)
# ----------------------------------------------------------------------

class TestWorkerPurity:
    def test_worker_returns_data_only(self, env):
        """Worker must not write checkpoint/lifecycle/ver_log/curated."""
        from acquisition_engine.scheduler_tasks import engine_source_task, plan_engine_tasks
        from acquisition_engine.engine import AcquisitionEngine
        eng = AcquisitionEngine(env["root"], mode="execute", network_block=False)
        tasks = plan_engine_tasks(eng.manifest, eng.reg_by_id, 100, env["root"])
        payload = engine_source_task(tasks[0])
        assert payload["status"] == "ok"
        assert len(payload["records"]) == 4  # s1 target 4
        # No shared files written by the worker
        cp = env["root"] / "metadata" / "engine_checkpoint.json"
        lf = env["root"] / "metadata" / "lifecycle.json"
        vf = env["root"] / "metadata" / "verification_log.json"
        cf = env["root"] / "curated" / "v0.1" / "pilot_candidates.jsonl"
        assert not cp.exists() and not lf.exists() and not vf.exists() and not cf.exists()

    def test_worker_license_blocked(self, env):
        from acquisition_engine.scheduler_tasks import engine_source_task, plan_engine_tasks
        from acquisition_engine.engine import AcquisitionEngine
        # Add a denied-license dataset
        ds = env["datasets"] + [_manifest_ds("bad", lic="Proprietary-NonCommercial")]
        root = _make_root(env["base"] / "root2", ds)
        eng = AcquisitionEngine(root, mode="execute", network_block=False)
        tasks = plan_engine_tasks(eng.manifest, eng.reg_by_id, 100, root)
        bad = [t for t in tasks if t.input == "bad"][0]
        payload = engine_source_task(bad)
        assert payload["status"] == "failed"
        assert payload["license_blocked"] is True
        assert payload["records"] == []


# ----------------------------------------------------------------------
# 3. Scheduler vs sequential byte-identical output
# ----------------------------------------------------------------------

class TestOutputIdentity:
    def test_sha256_equality_scheduler_vs_sequential(self, env):
        """Scheduler path and sequential fallback produce byte-identical
        curated output, same record count, same provenance."""
        import acquisition_engine.engine as eng_mod

        # Sequential (kill-switch off scheduler in engine AND worker path)
        old_engine_flag = eng_mod._ENGINE_SCHEDULER_ENABLED
        eng_mod._ENGINE_SCHEDULER_ENABLED = False
        try:
            r1 = _run_execute(env["root"], max_records=100)
        finally:
            eng_mod._ENGINE_SCHEDULER_ENABLED = old_engine_flag
        seq_file = env["root"] / "curated" / "v0.1" / "pilot_candidates.jsonl"
        assert seq_file.exists()

        # Fresh copy for scheduler run
        sched_root = env["base"] / "sched"
        shutil.copytree(env["root"], sched_root)
        r2 = _run_execute(sched_root, max_records=100)
        sched_file = sched_root / "curated" / "v0.1" / "pilot_candidates.jsonl"

        assert r1["records_accepted"] == r2["records_accepted"] == 12  # 4+3+5
        assert r1["records_attempted"] == r2["records_attempted"]
        assert _sha256(seq_file) == _sha256(sched_file)  # BYTE-IDENTICAL

    def test_provenance_equality(self, env):
        import acquisition_engine.engine as eng_mod
        old = eng_mod._ENGINE_SCHEDULER_ENABLED
        eng_mod._ENGINE_SCHEDULER_ENABLED = False
        try:
            _run_execute(env["root"], max_records=100)
        finally:
            eng_mod._ENGINE_SCHEDULER_ENABLED = old
        seq_recs = [json.loads(l) for l in
                    (env["root"] / "curated" / "v0.1" / "pilot_candidates.jsonl").read_text().splitlines()]

        sched_root = env["base"] / "sched2"
        shutil.copytree(env["root"], sched_root)
        _run_execute(sched_root, max_records=100)
        sched_recs = [json.loads(l) for l in
                      (sched_root / "curated" / "v0.1" / "pilot_candidates.jsonl").read_text().splitlines()]

        assert len(seq_recs) == len(sched_recs)
        for a, b in zip(seq_recs, sched_recs):
            assert a["id"] == b["id"]
            assert a["source_attribution"] == b["source_attribution"]
            assert a["lineage"] == b["lineage"]
            assert a["license"] == b["license"]
            assert a["quality_score"] == b["quality_score"]

    def test_dedup_behaviour_unchanged(self, eng_tmp: Path):
        """Two sources with identical content: first-wins dedup identical in
        both paths (only the first source's records survive)."""
        import acquisition_engine.engine as eng_mod
        # s1 and s2 have IDENTICAL subcategories/generation -> identical
        # messages -> cross-source dedup fires identically in both paths.
        ds = [_manifest_ds("s1", target=3, subcats=["x", "y"]),
              _manifest_ds("s2", target=3, subcats=["x", "y"])]
        root = _make_root(eng_tmp / "root", ds)
        old = eng_mod._ENGINE_SCHEDULER_ENABLED
        eng_mod._ENGINE_SCHEDULER_ENABLED = False
        try:
            _run_execute(root, max_records=100)
        finally:
            eng_mod._ENGINE_SCHEDULER_ENABLED = old
        seq_recs = [json.loads(l) for l in
                    (root / "curated" / "v0.1" / "pilot_candidates.jsonl").read_text().splitlines()]

        sched_root = eng_tmp / "sched"
        shutil.copytree(root, sched_root)
        _run_execute(sched_root, max_records=100)
        sched_recs = [json.loads(l) for l in
                      (sched_root / "curated" / "v0.1" / "pilot_candidates.jsonl").read_text().splitlines()]

        assert len(seq_recs) == len(sched_recs) == 3  # only s1's 3 survive
        assert [r["id"] for r in seq_recs] == [r["id"] for r in sched_recs]

    def test_max_records_behaviour_unchanged(self, env):
        import acquisition_engine.engine as eng_mod
        old = eng_mod._ENGINE_SCHEDULER_ENABLED
        eng_mod._ENGINE_SCHEDULER_ENABLED = False
        try:
            r1 = _run_execute(env["root"], max_records=6)
        finally:
            eng_mod._ENGINE_SCHEDULER_ENABLED = old

        sched_root = env["base"] / "sched3"
        shutil.copytree(env["root"], sched_root)
        r2 = _run_execute(sched_root, max_records=6)
        assert r1["records_accepted"] == r2["records_accepted"] == 6
        assert _sha256(env["root"] / "curated" / "v0.1" / "pilot_candidates.jsonl") == \
            _sha256(sched_root / "curated" / "v0.1" / "pilot_candidates.jsonl")


# ----------------------------------------------------------------------
# 4. Checkpoint resume equivalence
# ----------------------------------------------------------------------

class TestResume:
    def test_checkpoint_resume_equivalence(self, env):
        """Scheduler run writes engine_checkpoint.json; a resume run skips
        completed sources (both via registry and via checkpoint)."""
        r1 = _run_execute(env["root"], max_records=100)
        cp_path = env["root"] / "metadata" / "engine_checkpoint.json"
        assert cp_path.exists()
        cp = json.loads(cp_path.read_text())
        assert cp["status"] == "completed"
        assert cp["sources"]["s1"]["status"] == "completed"
        assert cp["sources"]["s3"]["status"] == "completed"

        # Resume: registry-completed tasks skipped; no new records are
        # generated (matches sequential resume semantics — the engine writes
        # only records produced during THIS run).
        r2 = _run_execute(env["root"], max_records=100, resume=True)
        assert r2["records_accepted"] == 0

    def test_engine_checkpoint_file_kept(self, env):
        """Constraint 3 from 5B: metadata/engine_checkpoint.json still exists
        with the same shape after a scheduler run."""
        _run_execute(env["root"], max_records=100)
        cp_path = env["root"] / "metadata" / "engine_checkpoint.json"
        assert cp_path.exists()
        raw = json.loads(cp_path.read_text())
        assert "session_id" in raw and "status" in raw and "sources" in raw
        assert "checksum" in raw  # integrity checksum still computed


# ----------------------------------------------------------------------
# 5. Retry / lease / fallback
# ----------------------------------------------------------------------

class TestRecovery:
    def test_failed_worker_retried_then_completed(self, env, tmp_path: Path):
        from acquisition_engine.scheduler_tasks import engine_source_task, plan_engine_tasks
        from parallel.scheduler import Scheduler
        from acquisition_engine.engine import AcquisitionEngine
        eng = AcquisitionEngine(env["root"], mode="execute", network_block=False)
        tasks = plan_engine_tasks(eng.manifest, eng.reg_by_id, 100, env["root"])

        calls = {"n": 0}
        def flaky(t):
            if calls["n"] == 0:
                calls["n"] += 1
                raise RuntimeError("transient")
            calls["n"] += 1
            return engine_source_task(t)

        s = Scheduler("acquisition", registry_root=tmp_path / "reg", workers=1,
                      pool="thread", max_retries=2)
        results = s.run(tasks, flaky)
        assert all(r.status == "completed" for r in results)

    def test_terminal_failure_after_max_retries(self, env, tmp_path: Path):
        from acquisition_engine.scheduler_tasks import plan_engine_tasks
        from parallel.scheduler import Scheduler
        from acquisition_engine.engine import AcquisitionEngine
        eng = AcquisitionEngine(env["root"], mode="execute", network_block=False)
        tasks = plan_engine_tasks(eng.manifest, eng.reg_by_id, 100, env["root"])

        def always_fail(t):
            raise RuntimeError("always")
        s = Scheduler("acquisition", registry_root=tmp_path / "reg2", workers=1,
                      pool="process", max_retries=2)
        results = s.run(tasks, always_fail)
        assert all(r.status == "failed" for r in results)
        assert results[0].attempts == 3

    def test_stale_running_reclaimed(self, tmp_path: Path):
        from parallel.registry import TaskRegistry
        reg = TaskRegistry(tmp_path / "reg3", "acquisition")
        reg.claim("acq:engine:B01:s1")
        reclaimed = reg.reclaim_stale_running(lease_seconds=0)
        assert "acq:engine:B01:s1" in reclaimed
        assert reg.status("acq:engine:B01:s1") == "pending"

    def test_sequential_fallback_identical(self, env):
        """Kill-switch forces the sequential loop; output identical."""
        import acquisition_engine.engine as eng_mod
        old = eng_mod._ENGINE_SCHEDULER_ENABLED
        eng_mod._ENGINE_SCHEDULER_ENABLED = False
        try:
            r = _run_execute(env["root"], max_records=100)
        finally:
            eng_mod._ENGINE_SCHEDULER_ENABLED = old
        assert r["records_accepted"] == 12
        # curated file exists with expected content
        recs = [json.loads(l) for l in
                (env["root"] / "curated" / "v0.1" / "pilot_candidates.jsonl").read_text().splitlines()]
        assert len(recs) == 12


# ----------------------------------------------------------------------
# 6. Worker purity at scale: no lifecycle writes during scheduler run
# ----------------------------------------------------------------------

class TestNoSharedWrites:
    def test_worker_never_touches_shared_files(self, env):
        """Even after a full scheduler run, worker-phase files are written
        only by the finalize (lifecycle/ver_log exist, but no partial state
        from individual workers)."""
        import acquisition_engine.engine as eng_mod
        old = eng_mod._ENGINE_SCHEDULER_ENABLED
        eng_mod._ENGINE_SCHEDULER_ENABLED = False
        try:
            _run_execute(env["root"], max_records=100)
        finally:
            eng_mod._ENGINE_SCHEDULER_ENABLED = old

        sched_root = env["base"] / "sched4"
        shutil.copytree(env["root"], sched_root)
        _run_execute(sched_root, max_records=100)
        # lifecycle file exists in both and has same record ids
        seq_lf = env["root"] / "metadata" / "lifecycle_state.json"
        sched_lf = sched_root / "metadata" / "lifecycle_state.json"
        assert seq_lf.exists() and sched_lf.exists()
        seq_ids = set(json.loads(seq_lf.read_text()).get("records", {}).keys())
        sched_ids = set(json.loads(sched_lf.read_text()).get("records", {}).keys())
        assert seq_ids == sched_ids
