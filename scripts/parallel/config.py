#!/usr/bin/env python3
"""Universal scheduler — configuration loading.

Single YAML loader for config/parallelism.yaml with:
- environment variable overrides (ATLAS_WORKERS_*, ATLAS_PROFILE)
- hardware profile support (static profiles + runtime detection)
- CLI override support (explicit parameter)

Worker Resolution Precedence:
  1. CLI/Code: explicit= parameter to resolve_worker_count()
  2. Environment: ATLAS_WORKERS_<STAGE_UPPER> = N
  3. Hardware profile: ATLAS_PROFILE or hostname match
  4. YAML config: config/parallelism.yaml
  5. Safe default: resource detection (cpu_cores, ram)

This is the ONLY allowed config loader. All pipelines must use
load_parallelism_config() and resolve_worker_count() from this module.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "parallelism.yaml"

# Env override pattern: ATLAS_WORKERS_<STAGE_UPPER> = N
ENV_PREFIX = "ATLAS_WORKERS_"
ENV_PROFILE = "ATLAS_PROFILE"

DEFAULTS: dict[str, Any] = {
    "parallelism": {
        "global": {
            "safety_margin_ram": 0.8,
            "cpu_saturation_threshold": 0.95,
            "disk_headroom_gb": 10,
            "default_per_task_ram_mb": 512,
            "io_worker_cap": 8,
        },
        "validation": {"file_workers": "auto", "chunk_size": 1000},
        "classification": {"stage1_shard_workers": 8, "stage2_shard_workers": 10},
        "acquisition": {"file_workers": 4, "chunk_size": 500},
        "extraction": {"shard_workers": "auto", "shards_per_source": 41},
        "training_views": {"workers": "auto"},
        "release": {"compress_workers": "auto", "upload_workers": 4},
    }
}

# Static hardware profiles (can be overridden by ATLAS_PROFILE).
HARDWARE_PROFILES: dict[str, dict[str, Any]] = {
    "dev-pc": {
        "cpu_cores": 16,
        "ram_mb": 30720,
        "gpu": "RTX 5070 (no driver, unusable)",
        "disk_gb": 420,
        "per_task_ram_mb": 512,
        "profile": "worker",
    },
    "mac-controller": {
        "cpu_cores": 8,
        "ram_mb": 16384,
        "gpu": None,
        "disk_gb": 512,
        "per_task_ram_mb": 512,
        "profile": "controller",
    },
}


def load_parallelism_config(path: str | Path | None = None) -> dict:
    """Load config/parallelism.yaml. Never raises — falls back to defaults.

    Returns the full dict: {"parallelism": {...}, "hardware_profiles": {...}}
    """
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    data: dict[str, Any] = {}
    try:
        import yaml

        with open(cfg_path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        if isinstance(loaded, dict):
            data = loaded
    except Exception:
        pass  # missing yaml / unreadable file -> defaults

    # Merge defaults so every stage key exists.
    merged: dict[str, Any] = {"parallelism": {}, "hardware_profiles": {}}
    default_p = DEFAULTS["parallelism"]
    for stage, stage_cfg in default_p.items():
        merged["parallelism"][stage] = dict(stage_cfg)
    loaded_p = data.get("parallelism") if isinstance(data, dict) else None
    if isinstance(loaded_p, dict):
        for stage, stage_cfg in loaded_p.items():
            if isinstance(stage_cfg, dict):
                merged["parallelism"][stage] = {**merged["parallelism"].get(stage, {}), **stage_cfg}
            else:
                merged["parallelism"][stage] = stage_cfg
    loaded_hw = data.get("hardware_profiles") if isinstance(data, dict) and isinstance(data.get("hardware_profiles"), dict) else {}
    merged["hardware_profiles"] = {**HARDWARE_PROFILES, **loaded_hw}
    return merged


def get_stage_config(stage: str, cfg: dict | None = None) -> dict:
    """Return resolved config for one stage (with defaults)."""
    cfg = cfg or load_parallelism_config()
    return dict(cfg.get("parallelism", {}).get(stage, {}))


def get_global_config(cfg: dict | None = None) -> dict:
    cfg = cfg or load_parallelism_config()
    return dict(cfg.get("parallelism", {}).get("global", {}))


def env_override(stage: str, current: int | None = None) -> int | None:
    """Apply ATLAS_WORKERS_<STAGE_UPPER> env override if present.

    Returns the overridden value, or ``current`` (None if no override).
    """
    key = ENV_PREFIX + stage.upper().replace("-", "_")
    raw = os.environ.get(key)
    if raw is None or raw.strip() == "":
        return current
    try:
        return int(raw.strip())
    except ValueError:
        return current


def resolve_worker_count(stage: str, cfg: dict | None = None, explicit: int | None = None) -> str | int:
    """Resolve a stage's worker count.

    Precedence: explicit (CLI) > env > config ('auto' or int) > 'auto'.
    Returns int when a concrete number is known, else 'auto' (scheduler decides).
    """
    if explicit is not None:
        return explicit
    env_val = env_override(stage)
    if env_val is not None:
        return env_val
    stage_cfg = get_stage_config(stage, cfg)
    key_candidates = ("workers", "file_workers", "shard_workers", "compress_workers")
    for key in key_candidates:
        if key in stage_cfg:
            val = stage_cfg[key]
            if isinstance(val, int) and val > 0:
                return val
            if isinstance(val, str) and val.strip().isdigit():
                return int(val.strip())
    return "auto"


def get_hardware_profile(cfg: dict | None = None, name: str | None = None) -> dict | None:
    """Resolve a hardware profile by ATLAS_PROFILE env, explicit name, or hostname."""
    cfg = cfg or load_parallelism_config()
    profiles = cfg.get("hardware_profiles", {})
    if name:
        return profiles.get(name)
    env_name = os.environ.get(ENV_PROFILE)
    if env_name and env_name in profiles:
        return profiles[env_name]
    import socket

    host = socket.gethostname().split(".")[0]
    if host in profiles:
        return profiles[host]
    return None
