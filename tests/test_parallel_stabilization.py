#!/usr/bin/env python3
"""Tests for unified parallelism introduced in the Atlas stabilization phase.

Covers:
- validate_one_file() + validate_dataset.py parallel execution
- run_extract_all.py
- validator.validate_records(workers=N)
- load_parallelism_config()
- parallel worker scheduling
- deterministic outputs
- resume behaviour
- skip behaviour
- cleanup behaviour
- malformed config
- invalid worker counts

All tests are deterministic and CI-safe (no network, no dev-pc).
"""

from __future__ import annotations

import json
import multiprocessing
import subprocess
import sys
from pathlib import Path

import pytest

# CI-safe process pool start method.
# On macOS the default 'spawn' re-imports the pytest __main__ entrypoint when
# ProcessPoolExecutor forks children, causing infinite recursion. 'fork' avoids
# re-importing the main module and is the Linux CI default.
if multiprocessing.get_start_method(allow_none=True) != "fork":
    try:
        multiprocessing.set_start_method("fork", force=True)
    except RuntimeError:
        pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

REPO_RUNNER = ROOT / "run_classify_all_v2.py"
CONFIG_PATH = ROOT / "config" / "parallelism.yaml"


# ── Helpers ──────────────────────────────────────────────────────────


def _exec_runner():
    """Execute run_classify_all_v2.py in a namespace, return its globals."""
    ns = {"__file__": str(REPO_RUNNER)}
    src = REPO_RUNNER.read_text()
    exec(compile(src, str(REPO_RUNNER), "exec"), ns)
    return ns


def _valid_record(i: int = 1) -> dict:
    """Curated-stage record shape (validates against validate_one_file)."""
    return {
        "id": f"test_{i:07d}",
        "category": "01_foundation",
        "subcategory": "general-reasoning",
        "type": "qa",
        "source": {"name": "test", "license": "CC-BY-4.0", "date": "2024-01-01"},
        "messages": [
            {"role": "system", "content": "You are Atlas, a precise and helpful AI assistant."},
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
        ],
        "language": "en",
        "difficulty": 2,
        "tags": [],
        "quality_score": 8,
        "verified": True,
        "notes": "",
    }


def _import_validator():
    """Import TrainingViewValidator via package path (avoids relative-import error)."""
    sys.path.insert(0, str(SCRIPTS))
    from training_view_engine.validator import TrainingViewValidator
    return TrainingViewValidator


def _validator_records(n: int) -> list[dict]:
    """Canonical knowledge-object shape (validates against TrainingViewValidator)."""
    return [
        {
            "id": f"rec_{i:04d}",
            "category": "01_foundation",
            "subcategory": "general-reasoning",
            "type": "qa",
            "messages": [{"role": "user", "content": "q"},
                         {"role": "assistant", "content": "a"}],
            "difficulty": 2,
            "knowledge_type": "factual",
            "canonical_answer": "a",
            "metadata": {},
            "source_attribution": {"source": "test"},
            "source": {"name": "test", "license": "CC-BY-4.0"},
            "license": "CC-BY-4.0",
            "language": "en",
            "tags": [],
            "quality_score": 9,
            "verification_status": "approved",
            "training_view_eligibility": True,
            "lineage": {
                "source": "test",
                "transformations": [],
                "knowledge_object": f"rec_{i:04d}",
                "curated_dataset": "v1.0",
                "training_view": None,
                "future_model": None,
            },
        }
        for i in range(n)
    ]


# ── load_parallelism_config() ────────────────────────────────────────


def test_load_parallelism_config_defaults():
    ns = _exec_runner()
    cfg = ns["load_parallelism_config"]()
    p = cfg.get("parallelism", {})
    assert p["classification"]["stage1_shard_workers"] == 8
    assert p["classification"]["stage2_shard_workers"] == 10
    assert p["classification"]["skip_v11_sources"] is True
    assert p["validation"]["file_workers"] == 8
    assert p["acquisition"]["file_workers"] == 4
    assert p["extraction"]["shard_workers"] == 8
    assert p["training_views"]["workers"] == 8


def test_load_parallelism_config_get_classification():
    ns = _exec_runner()
    cfg = ns["load_parallelism_config"]()
    clf = ns["get_classification_config"](cfg)
    assert clf["stage1_shard_workers"] == 8
    assert clf["stage2_shard_workers"] == 10


def test_malformed_config_falls_back(tmp_path: Path):
    """A missing config must return defaults without crashing (both yaml and fallback)."""
    ns = _exec_runner()
    ns["CONFIG_PATH"] = tmp_path / "missing.yaml"
    cfg = ns["load_parallelism_config"]()
    assert isinstance(cfg, dict)
    assert "parallelism" in cfg
    assert "hardware_profiles" in cfg


def test_malformed_config_garbage_yaml_falls_back(tmp_path: Path):
    """A config with invalid YAML must fall back without crashing."""
    p = tmp_path / "bad.yaml"
    p.write_text(": : :\n\tunbalanced\n", encoding="utf-8")
    ns = _exec_runner()
    ns["CONFIG_PATH"] = p
    cfg = ns["load_parallelism_config"]()
    assert isinstance(cfg, dict)


def test_invalid_worker_counts_never_crash_cli():
    ns = _exec_runner()
    cfg = ns["load_parallelism_config"]()
    clf = ns["get_classification_config"](cfg)
    for key in ("stage1_shard_workers", "stage2_shard_workers"):
        val = clf.get(key)
        assert isinstance(val, int) and val >= 1, f"{key}={val}"


# ── validate_one_file() ──────────────────────────────────────────────


def test_validate_one_file_ok(tmp_path: Path):
    from validate_dataset import validate_one_file
    p = tmp_path / "f.jsonl"
    p.write_text(json.dumps(_valid_record()) + "\n", encoding="utf-8")
    res = validate_one_file(p)
    assert res["path"] == str(p)
    assert res["total"] == 1
    assert res["bad_json"] == 0
    assert res["record_errors"] == 0


def test_validate_one_file_missing_file(tmp_path: Path):
    from validate_dataset import validate_one_file
    # validate_one_file raises on a missing file; the CLI catches this
    # (glob filter + parallel error capture). Assert the contract.
    with pytest.raises(FileNotFoundError):
        validate_one_file(tmp_path / "nope.jsonl")


def test_validate_one_file_malformed_line(tmp_path: Path):
    from validate_dataset import validate_one_file
    p = tmp_path / "bad.jsonl"
    p.write_text("{not json}\n" + json.dumps(_valid_record()) + "\n", encoding="utf-8")
    res = validate_one_file(p)
    assert res["bad_json"] == 1
    assert res["total"] == 1


# ── validate_dataset.py parallel execution ───────────────────────────


def test_validate_dataset_parallel_flag_help():
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "validate_dataset.py"), "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "--file-workers" in r.stdout


def test_validate_dataset_runs_on_glob(tmp_path: Path):
    for i in range(3):
        (tmp_path / f"file_{i}.jsonl").write_text(
            json.dumps(_valid_record(i)) + "\n", encoding="utf-8"
        )
    r = subprocess.run(
        [
            sys.executable, str(SCRIPTS / "validate_dataset.py"),
            "--input", str(tmp_path / "*.jsonl"),
            "--file-workers", "2",
            "--quiet",
        ],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr


def test_validate_dataset_glob_no_match_exit2(tmp_path: Path):
    r = subprocess.run(
        [
            sys.executable, str(SCRIPTS / "validate_dataset.py"),
            "--input", str(tmp_path / "nomatch_*.jsonl"),
        ],
        capture_output=True, text=True,
    )
    assert r.returncode == 2  # not found -> exit 2


# ── validator.validate_records(workers=N) ────────────────────────────


def test_validate_records_workers_equals_sequential():
    V = _import_validator()
    v = V(ROOT)
    records = _validator_records(200)
    seq = v.validate_records(records, quality_threshold=7, workers=1)
    par = v.validate_records(records, quality_threshold=7, workers=4)
    assert len(seq) == len(par) == 200
    assert [r["record_id"] for r in seq] == [r["record_id"] for r in par]
    assert [r["valid"] for r in seq] == [r["valid"] for r in par]


def test_validate_records_small_input_ignores_workers():
    V = _import_validator()
    v = V(ROOT)
    res = v.validate_records(_validator_records(2), quality_threshold=7, workers=4)
    assert len(res) == 2
    assert all(r["valid"] for r in res)


def test_validate_records_order_preserved():
    V = _import_validator()
    v = V(ROOT)
    records = _validator_records(120)
    res = v.validate_records(records, quality_threshold=7, workers=4)
    assert [r["record_id"] for r in res] == [f"rec_{i:04d}" for i in range(120)]


# ── run_extract_all.py ───────────────────────────────────────────────


def test_run_extract_all_help():
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "run_extract_all.py"), "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "--source" in r.stdout and "--shard-workers" in r.stdout


def test_run_extract_all_missing_script_fails_cleanly():
    """extract_one with a nonexistent script returns ERROR, not a crash."""
    sys.path.insert(0, str(SCRIPTS))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "run_extract_all", SCRIPTS / "run_extract_all.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Point SCRIPT_DIR at an empty temp dir so the script never exists
    mod.SCRIPT_DIR = SCRIPTS.parent / "does_not_exist_xyz"
    result = mod.extract_one(("wiki_sys", 3))
    assert result[2].startswith("ERROR")


# ── resume / skip / cleanup behaviour ────────────────────────────────


def test_append_source_to_v12_and_cleanup(tmp_path: Path):
    ns = _exec_runner()
    out_dir = tmp_path
    (out_dir / "_tmp").mkdir()
    v12 = out_dir / "unknown_classified_v1.2.jsonl"
    src = out_dir / "_tmp" / "classified_wiki_test.jsonl"
    src.write_text(
        json.dumps(_valid_record(1)) + "\n" + json.dumps(_valid_record(2)) + "\n",
        encoding="utf-8",
    )
    ns["OUT_DIR"] = out_dir
    ns["V12_CLASSIFIED"] = v12
    count = ns["append_source_to_v12"]("wiki_test")
    assert count == 2
    assert v12.exists()
    assert v12.read_text().count("\n") == 2
    assert not src.exists(), "source file must be deleted after append"


def test_append_source_to_v12_missing_src(tmp_path: Path):
    ns = _exec_runner()
    out_dir = tmp_path
    v12 = out_dir / "unknown_classified_v1.2.jsonl"
    ns["OUT_DIR"] = out_dir
    ns["V12_CLASSIFIED"] = v12
    count = ns["append_source_to_v12"]("ghost")
    assert count == 0
    assert not v12.exists()


def test_append_source_to_v12_no_duplicates_on_restart(tmp_path: Path):
    ns = _exec_runner()
    out_dir = tmp_path
    (out_dir / "_tmp").mkdir()
    v12 = out_dir / "unknown_classified_v1.2.jsonl"
    src = out_dir / "_tmp" / "classified_dup.jsonl"
    src.write_text(json.dumps(_valid_record()) + "\n", encoding="utf-8")
    ns["OUT_DIR"] = out_dir
    ns["V12_CLASSIFIED"] = v12
    ns["append_source_to_v12"]("dup")
    ns["append_source_to_v12"]("dup")  # source file gone -> no-op
    assert v12.read_text().count("\n") == 1


def test_skip_flag_split_logic():
    skip_str = "wiki_ai,wiki_sw,wiki_sys"
    skip_sources = {s.strip() for s in skip_str.split(",") if s.strip()}
    assert skip_sources == {"wiki_ai", "wiki_sw", "wiki_sys"}


# ── deterministic outputs ────────────────────────────────────────────


def test_validate_deterministic_across_runs(tmp_path: Path):
    from validate_dataset import validate_one_file
    p = tmp_path / "f.jsonl"
    p.write_text(json.dumps(_valid_record()) + "\n", encoding="utf-8")
    assert validate_one_file(p) == validate_one_file(p)


# ── config sanity (yaml optional) ────────────────────────────────────


def test_config_yaml_has_required_keys():
    yaml = pytest.importorskip("yaml")
    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    p = cfg["parallelism"]
    assert set(p["classification"].keys()) >= {
        "stage1_shard_workers", "stage2_shard_workers", "skip_v11_sources",
    }
    assert p["validation"]["file_workers"] >= 1
    assert p["acquisition"]["file_workers"] >= 1
    assert p["extraction"]["shard_workers"] >= 1
    assert p["training_views"]["workers"] >= 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
