#!/usr/bin/env python3
"""Tests for the Atlas Engineering Dashboard (ADR-016).

Covers:
- safety primitives (ids, paths, traversal, confirmations, tokens)
- action registry validation and argv construction against real CLI contracts
- JobManager execution, cancellation, persistence and crash recovery
- HTTP API surface: state aggregation, catalog safety, action submission,
  destructive confirmation, auth middleware, preview whitelist
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from dashboard import actions as dash_actions  # noqa: E402
from dashboard import safety as dash_safety  # noqa: E402
from dashboard.app import create_app  # noqa: E402
from dashboard.jobs import JobManager  # noqa: E402
from atlas_paths import get_root  # noqa: E402

ROOT = get_root()
PY = sys.executable


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def run(coro):
    return asyncio.run(coro)


def make_client(tmp_path, token: str | None = None) -> TestClient:
    app = create_app(data_dir=tmp_path / "dashdata", worker_count=2)

    async def _start() -> TestClient:
        client = TestClient(TestServer(app))
        await client.start_server()
        return client

    return run(_start())


def close_client(client: TestClient) -> None:
    async def _close() -> None:
        await client.close()

    run(_close())


async def await_job(client: TestClient, job_id: str,
                    timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = await client.get(f"/api/jobs/{job_id}")
        assert resp.status == 200
        job = await resp.json()
        if job["status"] not in ("queued", "running"):
            return job
        await asyncio.sleep(0.1)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


def submit(client: TestClient, action_id: str, payload: dict):
    async def _submit():
        resp = await client.post(f"/api/actions/{action_id}/run", json=payload)
        body = None
        if resp.status == 202:
            body = await resp.json()
        return resp.status, body

    status, body = run(_submit())

    class _RespProxy(int):
        pass

    # Return an object mimicking the previous (status, json) interface.
    class R:
        def __init__(self, s):
            self.status = s

    return R(status), body


# ---------------------------------------------------------------------------
# safety module
# ---------------------------------------------------------------------------


class TestSafety:
    def test_safe_id_accepts_valid(self):
        assert dash_safety.safe_id("release-v0.3_1.2") == "release-v0.3_1.2"

    @pytest.mark.parametrize("bad", ["../evil", "", "/abs", "a b", "x" * 200, None])
    def test_safe_id_rejects_invalid(self, bad):
        with pytest.raises(dash_safety.SafetyError):
            dash_safety.safe_id(bad)

    def test_resolve_readable_path_rejects_traversal(self):
        with pytest.raises(dash_safety.SafetyError):
            dash_safety.resolve_readable_path("../../etc/passwd")

    def test_resolve_readable_path_rejects_outside_whitelist(self):
        with pytest.raises(dash_safety.SafetyError):
            dash_safety.resolve_readable_path("scripts/atlas.py")

    def test_resolve_readable_path_accepts_whitelisted_file(self):
        path = dash_safety.resolve_readable_path("review_queue/rejected.jsonl")
        assert path.is_file()

    def test_require_confirmation_exact_match(self):
        with pytest.raises(dash_safety.SafetyError):
            dash_safety.require_confirmation("cancel pipeline", "CANCEL PIPELINE")
        dash_safety.require_confirmation("CANCEL PIPELINE", "CANCEL PIPELINE")

    def test_tokens_equal_constant_time_paths(self):
        assert dash_safety.tokens_equal("abc", "abc")
        assert not dash_safety.tokens_equal("abc", "abd")
        assert not dash_safety.tokens_equal(None, "abc")
        assert dash_safety.tokens_equal(None, None)


# ---------------------------------------------------------------------------
# actions registry
# ---------------------------------------------------------------------------


class TestActions:
    def test_unknown_action_raises(self):
        with pytest.raises(KeyError):
            dash_actions.build_argv("no.such.action", {})

    def test_destructive_blocked_without_confirm(self):
        with pytest.raises(dash_actions.SafetyError):
            dash_actions.build_argv("pipeline.cancel", {"pipeline_id": "p1"})

    def test_destructive_allowed_with_confirm(self):
        argv = dash_actions.build_argv(
            "pipeline.cancel", {"pipeline_id": "p1", "confirm": "CANCEL PIPELINE",
                                "reason": "done"})
        assert "cancel" in argv and "--pipeline-id" in argv

    def test_unknown_params_rejected(self):
        with pytest.raises(dash_actions.SafetyError, match="unknown parameter"):
            dash_actions.build_argv("pipeline.run",
                                    {"pipeline_id": "p1", "rm_rf": True})

    def test_missing_required_param_rejected(self):
        with pytest.raises(dash_actions.SafetyError, match="pipeline_id"):
            dash_actions.build_argv("pipeline.run", {})

    def test_underscores_become_dashes_in_flags(self):
        argv = dash_actions.build_argv("pipeline.run",
                                       {"pipeline_id": "p1", "dry_run": True})
        assert "--dry-run" in argv
        assert "--dry_run" not in argv

    def test_automation_runner_argv_shape(self):
        argv = dash_actions.build_argv("pipeline.run",
                                       {"pipeline_id": "p1", "dry_run": True})
        assert argv[1:] == ["-m", "scripts.automation_runner", "--json", "run",
                            "--pipeline-id", "p1", "--dry-run"]

    def test_atlas_argv_shape(self):
        argv = dash_actions.build_argv("aql.validate",
                                       {"query": "quality_score >= 8"})
        assert argv[1] == "scripts/atlas.py"
        assert "query" in argv and "--validate" in argv

    def test_output_path_outside_approved_roots_rejected(self):
        with pytest.raises(dash_actions.SafetyError):
            dash_actions.build_argv(
                "review.sample",
                {"records": ["pilot/v0.2/math/train.jsonl"],
                 "output": "curated/../../etc/evil.jsonl", "rate_pct": 5})

    def test_input_path_must_exist_within_whitelist(self):
        with pytest.raises(dash_actions.SafetyError):
            dash_actions.build_argv(
                "dataset.validate", {"input_path": "scripts/atlas.py",
                                     "strict": False})

    def test_catalog_reports_disabled_reasons_without_leaking_values(self):
        items = dash_actions.catalog()
        by_id = {a["id"]: a for a in items}
        assert len(items) >= 40
        cred = by_id["release.upload_hf"]["credentials_present"]
        assert all(isinstance(v, bool) for v in cred.values())
        gated = by_id["release.upload_hf"]
        if not gated["enabled"]:
            assert "HF_TOKEN" in gated["disabled_reason"]


# ---------------------------------------------------------------------------
# JobManager
# ---------------------------------------------------------------------------


class TestJobManager:
    def _mgr(self, tmp_path):
        return JobManager(data_dir=tmp_path / "d", root=ROOT, max_workers=2)

    def _wait_terminal(self, mgr, job_id, timeout=25.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rec = mgr.get(job_id)
            if rec["status"] not in ("queued", "running"):
                return rec
            time.sleep(0.05)
        raise AssertionError(f"job {job_id} did not finish in {timeout}s")

    def test_submit_and_succeed(self, tmp_path):
        mgr = self._mgr(tmp_path)
        try:
            job = mgr.submit(action_id="test.echo", title="echo", danger="read",
                             argv=[PY, "-c", "print('hello-dashboard')"],
                             timeout_s=30)
            # worker may pick the job up before we observe it
            assert job["status"] in ("queued", "running")
            rec = self._wait_terminal(mgr, job["id"])
            assert rec["status"] == "succeeded", rec
            assert rec["exit_code"] == 0
            assert "hello-dashboard" in mgr.log_tail(job["id"])
        finally:
            mgr.shutdown()

    def test_failure_captures_exit_code(self, tmp_path):
        mgr = self._mgr(tmp_path)
        try:
            job = mgr.submit(action_id="test.fail", title="fail", danger="read",
                             argv=[PY, "-c", "import sys; sys.exit(7)"],
                             timeout_s=30)
            rec = self._wait_terminal(mgr, job["id"])
            assert rec["status"] == "failed"
            assert rec["exit_code"] == 7
        finally:
            mgr.shutdown()

    def test_attention_exit_code(self, tmp_path):
        mgr = self._mgr(tmp_path)
        try:
            job = mgr.submit(action_id="review.ai_run", title="ai",
                             danger="network",
                             argv=[PY, "-c", "import sys; sys.exit(3)"],
                             timeout_s=30)
            rec = self._wait_terminal(mgr, job["id"])
            assert rec["status"] == "needs_attention"
            assert rec["needs_attention"] is True
            assert "NOT an acceptance" in rec["error"]
        finally:
            mgr.shutdown()

    def test_cancel_running_job(self, tmp_path):
        mgr = self._mgr(tmp_path)
        job = mgr.submit(action_id="test.sleep", title="sleep", danger="read",
                         argv=[PY, "-c", "import time; time.sleep(60)"],
                         timeout_s=60)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if mgr.get(job["id"])["status"] == "running":
                break
            time.sleep(0.05)
        try:
            ok, _msg = mgr.cancel(job["id"])
            assert ok
            rec = self._wait_terminal(mgr, job["id"], timeout=20)
            assert rec["status"] == "cancelled"
        finally:
            mgr.shutdown()

    def test_persistence_and_interrupted_recovery(self, tmp_path):
        mgr1 = self._mgr(tmp_path)
        job = mgr1.submit(action_id="test.sleep", title="sleep", danger="read",
                          argv=[PY, "-c", "import time; time.sleep(60)"],
                          timeout_s=60)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if mgr1.get(job["id"])["status"] == "running":
                break
            time.sleep(0.05)
        # simulate crash: new manager over the same data dir, old one gone
        mgr2 = JobManager(data_dir=tmp_path / "d", root=ROOT, max_workers=1)
        try:
            rec = mgr2.get(job["id"])
            assert rec is not None, "jobs.json was not persisted"
            assert rec["status"] == "interrupted"
        finally:
            mgr1.shutdown()
            mgr2.shutdown()


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------


@pytest.fixture()
def no_creds(monkeypatch):
    monkeypatch.delenv("ATLAS_DASHBOARD_TOKEN", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("ATLAS_REVIEW_BASE_URL", raising=False)


async def _with_client(tmp_path, body):
    app = create_app(data_dir=tmp_path / "dashdata", worker_count=2)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        return await body(client)
    finally:
        await client.close()


class TestReadEndpoints:
    def test_all_get_endpoints_200(self, tmp_path, no_creds):
        async def body(client):
            paths = [
                "/api/health", "/api/overview", "/api/catalog", "/api/releases",
                "/api/pipelines", "/api/approvals", "/api/review/progress",
                "/api/review/queue", "/api/review/artifacts", "/api/review/sft",
                "/api/sources", "/api/sources/etl", "/api/sources/downloads",
                "/api/sources/cache", "/api/views",
                "/api/evaluation/benchmarks", "/api/evaluation/reports",
                "/api/intelligence", "/api/calibration", "/api/readiness",
                "/api/jobs",
            ]
            for path in paths:
                resp = await client.get(path)
                assert resp.status == 200, path

        run(_with_client(tmp_path, body))

    def test_overview_reflects_real_release(self, tmp_path, no_creds):
        async def body(client):
            resp = await client.get("/api/overview")
            data = await resp.json()
            assert data["release"]["version"] == "v1.0"
            assert data["release"]["total_records"] == 9_515_938
            assert data["training_readiness"]["verdict"] in (
                "BLOCKED", "READY", "CONDITIONAL")

        run(_with_client(tmp_path, body))

    def test_release_detail_404_for_unknown(self, tmp_path, no_creds):
        async def body(client):
            resp = await client.get("/api/releases/v99.99")
            assert resp.status == 404

        run(_with_client(tmp_path, body))

    def test_pipeline_detail_contains_state_and_approval(self, tmp_path, no_creds):
        async def body(client):
            resp = await client.get("/api/pipelines/default")
            data = await resp.json()
            assert data["pipeline"]["current_state"] == "CANCELLED"
            assert "approval_request" in data

        run(_with_client(tmp_path, body))

    def test_static_spa_served(self, tmp_path, no_creds):
        async def body(client):
            resp = await client.get("/")
            assert resp.status == 200
            text = await resp.text()
            assert "Atlas Engineering Dashboard" in text
            # The modal Run button MUST be wired to the form — a regression
            # here leaves every action button dead in real browsers while all
            # API tests still pass.
            assert 'id="modal-submit"' in text
            assert 'form="modal-form"' in text
            resp = await client.get("/static/app.js")
            assert resp.status == 200
            js = await resp.text()
            assert 'data-action' in js          # click delegation source
            assert '#modal-form' in js          # submit handler target
            assert 'requestSubmit' in js        # explicit footer path

        run(_with_client(tmp_path, body))

    def test_security_headers_present(self, tmp_path, no_creds):
        async def body(client):
            resp = await client.get("/api/health")
            assert resp.headers["X-Content-Type-Options"] == "nosniff"
            assert "default-src 'self'" in resp.headers["Content-Security-Policy"]
            assert resp.headers["Cache-Control"] == "no-store"

        run(_with_client(tmp_path, body))


class TestActionSubmission:
    def test_read_action_runs_real_cli(self, tmp_path, no_creds):
        async def body(client):
            resp = await client.post("/api/actions/aql.validate/run", json={
                "query": "quality_score >= 8", "source": "v0.1"})
            assert resp.status == 202
            job_id = (await resp.json())["job"]["id"]
            job = await await_job(client, job_id)
            assert job["status"] == "succeeded"
            assert job["exit_code"] == 0
            assert job["triggered_by"] == "dashboard"
            log_resp = await client.get(f"/api/jobs/{job['id']}/log")
            assert "Valid query" in await log_resp.text()

        run(_with_client(tmp_path, body))

    def test_destructive_without_confirm_rejected(self, tmp_path, no_creds):
        async def body(client):
            resp = await client.post("/api/actions/pipeline.cancel/run", json={
                "pipeline_id": "default"})
            assert resp.status == 400
            detail = (await resp.json())["detail"]
            assert "confirm" in detail

        run(_with_client(tmp_path, body))

    def test_destructive_with_confirm_executes_real_cli(self, tmp_path, no_creds):
        async def body(client):
            resp = await client.post("/api/actions/pipeline.cancel/run", json={
                "pipeline_id": "default", "confirm": "CANCEL PIPELINE",
                "reason": "dashboard test of governed path"})
            assert resp.status == 202
            job = await await_job(client, (await resp.json())["job"]["id"])
            # 'default' is already CANCELLED (terminal): cmd_cancel is an
            # idempotent no-op that exits 0 with an explicit message — proving
            # the request reached the real FSM CLI.
            assert job["status"] == "succeeded"
            assert job["exit_code"] == 0
            log_resp = await client.get(f"/api/jobs/{job['id']}/log")
            text = await log_resp.text()
            assert "already CANCELLED" in text

        run(_with_client(tmp_path, body))

    def test_cancel_unknown_pipeline_is_idempotent_noop(self, tmp_path, no_creds):
        async def body(client):
            resp = await client.post("/api/actions/pipeline.cancel/run", json={
                "pipeline_id": "no-such-pipeline-xyz",
                "confirm": "CANCEL PIPELINE"})
            assert resp.status == 202
            job_id = (await resp.json())["job"]["id"]
            job = await await_job(client, job_id)
            # Real automation_runner semantics: cancel of an unknown/terminal
            # pipeline is an idempotent no-op that exits 0 with a message.
            assert job["status"] == "succeeded"
            detail = await (await client.get(f"/api/jobs/{job_id}")).json()
            assert detail["cli_result"]["message"] == (
                "Pipeline 'no-such-pipeline-xyz' is already CANCELLED.")

        run(_with_client(tmp_path, body))

    def test_release_rejection_surfaced_via_cli_result(self, tmp_path, no_creds):
        async def body(client):
            resp = await client.post("/api/actions/pipeline.release/run", json={
                "pipeline_id": "default", "confirm": "EXECUTE RELEASE"})
            assert resp.status == 202
            job_id = (await resp.json())["job"]["id"]
            job = await await_job(client, job_id)
            # Governance gate: releasing without approval is refused by the
            # real CLI (exit 0 + refusal message per its contract). The
            # refusal must be recoverable from both log and cli_result.
            log_resp = await client.get(f"/api/jobs/{job_id}/log")
            text = await log_resp.text()
            assert "human approval not granted" in text
            detail = await (await client.get(f"/api/jobs/{job_id}")).json()
            msg = detail.get("cli_result", {}).get("message") or ""
            assert "human approval not granted" in msg

        run(_with_client(tmp_path, body))

    def test_disabled_action_returns_409(self, tmp_path, no_creds):
        async def body(client):
            resp = await client.post("/api/actions/release.upload_hf/run", json={
                "repo_id": "x/y", "release": "v1.0"})
            assert resp.status == 409
            data = await resp.json()
            assert data["error"] == "action_disabled"
            assert "HF_TOKEN" in data["detail"]

        run(_with_client(tmp_path, body))

    def test_unknown_action_404(self, tmp_path, no_creds):
        async def body(client):
            resp = await client.post("/api/actions/not.an.action/run", json={})
            assert resp.status == 404

        run(_with_client(tmp_path, body))

    def test_validation_error_400(self, tmp_path, no_creds):
        async def body(client):
            resp = await client.post("/api/actions/pipeline.run/run", json={
                "pipeline_id": "../x"})
            assert resp.status == 400
            assert (await resp.json())["error"] == "validation_failed"

        run(_with_client(tmp_path, body))


class TestPreviewAndAuth:
    def test_preview_whitelisted_jsonl(self, tmp_path, no_creds):
        async def body(client):
            resp = await client.get(
                "/api/preview?path=review_queue/rejected.jsonl&limit=2")
            assert resp.status == 200
            data = await resp.json()
            assert data["is_jsonl"] is True
            assert data["returned"] <= 2

        run(_with_client(tmp_path, body))

    def test_preview_rejects_traversal_and_secrets(self, tmp_path, no_creds):
        async def body(client):
            for bad in ("../../../.env", "../.git/config",
                        "scripts/credential_helper.py"):
                quoted = bad.replace("/", "%2F")
                resp = await client.get(f"/api/preview?path={quoted}")
                assert resp.status == 400, bad

        run(_with_client(tmp_path, body))

    def test_preview_bad_limit_400(self, tmp_path, no_creds):
        async def body(client):
            resp = await client.get(
                "/api/preview?path=review_queue/rejected.jsonl&limit=abc")
            assert resp.status == 400

        run(_with_client(tmp_path, body))

    def test_auth_middleware(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ATLAS_DASHBOARD_TOKEN", "tok-123")

        async def body(client):
            resp = await client.get("/api/overview")
            assert resp.status == 401
            resp = await client.get(
                "/api/overview", headers={"Authorization": "Bearer tok-123"})
            assert resp.status == 200
            resp = await client.get("/api/health")
            assert resp.status == 200  # healthz exempt

        run(_with_client(tmp_path, body))
