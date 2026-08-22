#!/usr/bin/env python3
"""
Tests for agent_trajectory_builder.py — Agent trajectory dataset builder.
"""
from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

import scripts.agent_trajectory_builder as atb


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_trajectory():
    """Return a minimal valid SWE-agent trajectory."""
    return {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "<pr_description>Bug in auth module</pr_description>"},
            {"role": "assistant", "content": "THOUGHT: Let me inspect the code.\n\n```bash\nfind . -name '*.py' | head\n```"},
            {"role": "user", "content": "<returncode>0</returncode>\n<output>auth.py\nutils.py\n```"},
            {"role": "assistant", "content": "THOUGHT: Found auth.py. Reading it now.\n\n```bash\ncat auth.py\n```"},
            {"role": "user", "content": "<returncode>0</returncode>\n<output>def authenticate(...)\n```"},
            {"role": "assistant", "content": "THOUGHT: I see the bug. Fixing it now.\n\n```bash\nsed -i 's/old/new/' auth.py\n```"},
            {"role": "user", "content": "<returncode>0</returncode>\n<output>```"},
            {"role": "assistant", "content": "THOUGHT: All tests passing. Fixed successfully."},
        ],
    }


@pytest.fixture
def short_trajectory():
    """Return a trajectory below the min message threshold."""
    return {
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "done"},
        ],
    }


@pytest.fixture
def failed_trajectory():
    """Return a trajectory with a traceback and no success."""
    return {
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "<pr_description>Bug report</pr_description>"},
            {"role": "assistant", "content": "THOUGHT: Looking at the code...\n\n```bash\ncat main.py\n```"},
            {"role": "user", "content": "<returncode>0</returncode>\n<output>def main(): pass\n```"},
            {"role": "assistant", "content": "THOUGHT: Applying fix...\n\n```bash\npatch main.py\n```"},
            {"role": "user", "content": "<returncode>1</returncode>\n<output>Traceback (most recent call last):\n  File ..."},
            {"role": "assistant", "content": "THOUGHT: The patch failed. I cannot fix this."},
        ],
    }


# ---------------------------------------------------------------------------
# analyze_trajectory
# ---------------------------------------------------------------------------

class TestAnalyzeTrajectory:
    def test_basic_stats(self, sample_trajectory):
        stats = atb.analyze_trajectory(sample_trajectory["messages"])
        assert stats.message_count == 9
        assert stats.observation_count == 3
        assert stats.thought_count == 4
        assert stats.bash_command_count == 3

    def test_short_trajectory(self, short_trajectory):
        stats = atb.analyze_trajectory(short_trajectory["messages"])
        assert stats.message_count == 3
        assert stats.observation_count == 0
        assert stats.estimated_difficulty == 1

    def test_failed_trajectory_detects_traceback_in_user_msg(self, failed_trajectory):
        """Traceback can appear in user (observation) messages too."""
        stats = atb.analyze_trajectory(failed_trajectory["messages"])
        # The traceback is in a user observation message
        assert stats.observation_count == 2
        # Traceback in user msg should still be detected
        assert stats.final_verdict == "failed"

    def test_completed_trajectory(self, sample_trajectory):
        stats = atb.analyze_trajectory(sample_trajectory["messages"])
        assert stats.has_success_indicator is True
        assert stats.final_verdict == "completed"

    def test_difficulty_scaling(self):
        """Higher observation count → higher difficulty."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "task"},
        ]
        for i in range(25):
            messages.append({"role": "assistant", "content": f"THOUGHT: step {i}"})
            messages.append({"role": "user", "content": f"<returncode>0</returncode>\n<output>obs {i}"})

        stats = atb.analyze_trajectory(messages)
        assert stats.estimated_difficulty == 4
        assert stats.observation_count == 25


# ---------------------------------------------------------------------------
# is_quality_trajectory
# ---------------------------------------------------------------------------

class TestIsQualityTrajectory:
    def test_passes_normal(self, sample_trajectory):
        with patch.object(atb, "MIN_MESSAGES", 5):
            stats = atb.analyze_trajectory(sample_trajectory["messages"])
            assert atb.is_quality_trajectory(stats) is True

    def test_rejects_too_short(self, short_trajectory):
        stats = atb.analyze_trajectory(short_trajectory["messages"])
        assert atb.is_quality_trajectory(stats) is False

    def test_rejects_catastrophic_failure(self, failed_trajectory):
        stats = atb.analyze_trajectory(failed_trajectory["messages"])
        assert atb.is_quality_trajectory(stats) is False

    def test_rejects_no_observations(self):
        """Trajectory with no tool observations is filtered out."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        stats = atb.analyze_trajectory(messages)
        assert stats.observation_count == 0
        assert atb.is_quality_trajectory(stats) is False


# ---------------------------------------------------------------------------
# extract_pr_description
# ---------------------------------------------------------------------------

class TestExtractPRDescription:
    def test_strips_wrappers(self, sample_trajectory):
        pr = atb.extract_pr_description(sample_trajectory["messages"])
        assert "<pr_description>" not in pr
        assert "Bug in auth module" in pr

    def test_strips_uploaded_files(self):
        messages = [
            {"role": "user", "content": "<uploaded_files>/testbed</uploaded_files>\nSome task"},
        ]
        pr = atb.extract_pr_description(messages)
        assert "<uploaded_files>" not in pr
        assert "Some task" in pr


# ---------------------------------------------------------------------------
# classify_domain
# ---------------------------------------------------------------------------

class TestClassifyDomain:
    def test_software_engineering(self):
        messages = [
            {"role": "user", "content": "Fix the database model"},
            {"role": "assistant", "content": "Looking at the model..."},
        ]
        assert atb.classify_domain(messages) == "software_engineering"

    def test_security_domain(self):
        messages = [
            {"role": "user", "content": "OAuth token validation broken"},
            {"role": "assistant", "content": "Checking auth module..."},
        ]
        assert atb.classify_domain(messages) == "security"

    def test_devops_domain(self):
        messages = [
            {"role": "user", "content": "Docker container failing on deploy"},
            {"role": "assistant", "content": "Checking k8s config..."},
        ]
        assert atb.classify_domain(messages) == "devops"

    def test_default_to_software(self):
        messages = [{"role": "user", "content": "random text"}]
        assert atb.classify_domain(messages) == "software_engineering"


# ---------------------------------------------------------------------------
# convert_trajectory
# ---------------------------------------------------------------------------

class TestConvertTrajectory:
    def test_preserves_structure(self, sample_trajectory):
        stats = atb.analyze_trajectory(sample_trajectory["messages"])
        converted = atb.convert_trajectory(
            messages=sample_trajectory["messages"],
            system_prompt=atb.ATAN_V1_SYSTEM_PROMPT,
            source_name="test-source",
            license_="MIT",
            stats=stats,
        )
        msgs = converted["messages"]
        assert msgs[0]["role"] == "system"
        assert "Anda adalah Atan" in msgs[0]["content"]
        assert len(msgs) == 9  # system + 8 original turns

    def test_injects_malaysian_prompt(self, sample_trajectory):
        stats = atb.analyze_trajectory(sample_trajectory["messages"])
        converted = atb.convert_trajectory(
            messages=sample_trajectory["messages"],
            system_prompt=atb.ATAN_V1_SYSTEM_PROMPT,
            source_name="test",
            license_="MIT",
            stats=stats,
        )
        assert "Anda adalah Atan" in converted["messages"][0]["content"]
        assert "Agentic workflow" in converted["messages"][0]["content"]

    def test_metadata_included(self, sample_trajectory):
        stats = atb.analyze_trajectory(sample_trajectory["messages"])
        converted = atb.convert_trajectory(
            messages=sample_trajectory["messages"],
            system_prompt=atb.ATAN_V1_SYSTEM_PROMPT,
            source_name="test-src",
            license_="Apache-2.0",
            stats=stats,
        )
        meta = converted["metadata"]
        assert meta["source"] == "test-src"
        assert meta["license"] == "Apache-2.0"
        assert meta["difficulty"] == 1  # 3 observations → difficulty 1
        assert meta["verdict"] == "completed"
        assert "trajectory_hash" in meta
        assert "generated_at" in meta

    def test_tool_observations_preserved(self, sample_trajectory):
        stats = atb.analyze_trajectory(sample_trajectory["messages"])
        converted = atb.convert_trajectory(
            messages=sample_trajectory["messages"],
            system_prompt=atb.ATAN_V1_SYSTEM_PROMPT,
            source_name="test",
            license_="MIT",
            stats=stats,
        )
        roles = [m["role"] for m in converted["messages"]]
        # Observations stay as user role
        obs_msgs = [m for m in converted["messages"] if "<returncode>" in m.get("content", "")]
        assert len(obs_msgs) == 3


# ---------------------------------------------------------------------------
# build_trajectories (integration)
# ---------------------------------------------------------------------------

class TestBuildTrajectories:
    def test_dry_run(self, capsys):
        """Dry run should list sources without writing."""
        with patch.object(sys, "argv", ["agent_trajectory_builder", "--dry-run"]):
            ret = atb.main()
        assert ret == 0
        captured = capsys.readouterr()
        assert "p0-swe-smith-trajectories" in captured.err
        assert "p1-swe-smith-mini" in captured.err

    def test_build_minimal(self, tmp_path, sample_trajectory, failed_trajectory):
        """Build with a tiny custom source."""
        src_path = tmp_path / "test_traj.jsonl"
        with src_path.open("w") as f:
            f.write(json.dumps(sample_trajectory) + "\n")
            f.write(json.dumps(failed_trajectory) + "\n")

        with patch.object(atb, "TRAJECTORY_SOURCES", [
            {"path": src_path, "name": "test-source", "license": "MIT", "source_type": "swe_agent"},
        ]):
            with patch.object(atb, "MIN_MESSAGES", 3):
                report = atb.build_trajectories(
                    output_dir=tmp_path / "out",
                    min_messages=3,
                    max_trajectories=10,
                    val_ratio=0.2,
                    seed=42,
                    include_failed=False,
                )

        # Failed trajectory should be excluded (include_failed=False)
        # With 1 record and val_ratio=0.2, max(1, int(1*0.2))=1 goes to val
        assert report["total_records"] == 1
        assert report["train_records"] == 0
        assert report["val_records"] == 1
        assert (tmp_path / "out" / "agent_trajectories_train.jsonl").exists()
        assert (tmp_path / "out" / "agent_trajectories_metadata.json").exists()

    def test_output_format_valid(self, tmp_path, sample_trajectory):
        """Output JSONL should be parseable and well-formed."""
        src_path = tmp_path / "src.jsonl"
        with src_path.open("w") as f:
            for _ in range(5):
                f.write(json.dumps(sample_trajectory) + "\n")

        with patch.object(atb, "TRAJECTORY_SOURCES", [
            {"path": src_path, "name": "test", "license": "MIT", "source_type": "swe_agent"},
        ]):
            with patch.object(atb, "MIN_MESSAGES", 3):
                atb.build_trajectories(
                    output_dir=tmp_path / "out",
                    min_messages=3,
                    max_trajectories=5,
                    seed=42,
                )

        with open(tmp_path / "out" / "agent_trajectories_train.jsonl") as f:
            for line in f:
                rec = json.loads(line)
                assert "messages" in rec
                assert "metadata" in rec
                assert rec["messages"][0]["role"] == "system"
                assert "Anda adalah" in rec["messages"][0]["content"]
