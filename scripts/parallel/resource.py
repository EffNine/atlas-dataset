#!/usr/bin/env python3
"""Universal scheduler — hardware resource detection.

Detects CPU cores, available RAM, and free disk; computes safe worker limits
that never exceed the configured safety margin.

Pure stdlib (psutil optional enhancement). Never raises for detection —
each detector degrades to a conservative default on failure.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from .config import get_global_config, load_parallelism_config


def detect_cpu() -> int:
    """Return number of usable logical CPUs (respects affinity)."""
    try:
        affinity = len(os.sched_getaffinity(0))
        if affinity > 0:
            return affinity
    except (AttributeError, OSError):
        pass
    try:
        return os.cpu_count() or 1
    except Exception:
        return 1


def detect_ram() -> dict:
    """Return {'total_mb': int, 'available_mb': int, 'used_mb': int}.

    Uses sysconf (Linux/macOS) or psutil when available. Conservative
    fallback: total = 4096 MB, available = 2048 MB.
    """
    total_mb: int | None = None
    avail_mb: int | None = None

    try:
        import psutil  # optional

        vm = psutil.virtual_memory()
        total_mb = vm.total // (1024 * 1024)
        avail_mb = vm.available // (1024 * 1024)
    except Exception:
        pass

    if total_mb is None:
        try:
            page_size = os.sysconf("SC_PAGE_SIZE")
            phys_pages = os.sysconf("SC_PHYS_PAGES")
            total_mb = (page_size * phys_pages) // (1024 * 1024)
        except (AttributeError, ValueError, OSError):
            total_mb = 4096

    if avail_mb is None:
        try:
            page_size = os.sysconf("SC_PAGE_SIZE")
            avail_pages = os.sysconf("SC_AVPHYS_PAGES")
            avail_mb = (page_size * avail_pages) // (1024 * 1024)
        except (AttributeError, ValueError, OSError):
            avail_mb = max(1024, total_mb // 2)

    return {"total_mb": int(total_mb), "available_mb": int(avail_mb), "used_mb": int(total_mb - avail_mb)}


def disk_free(path: str | Path = ".") -> int:
    """Return free disk bytes at path (conservative: 10 GB fallback)."""
    try:
        usage = shutil.disk_usage(str(path))
        return int(usage.free)
    except Exception:
        return 10 * 1024 * 1024 * 1024  # 10 GB fallback


def safe_worker_limit(
    per_task_ram_mb: int | None = None,
    safety_margin: float | None = None,
    max_workers: int | None = None,
    cpu_cap: int | None = None,
    cfg: dict | None = None,
) -> int:
    """Compute the maximum safe number of concurrent workers.

    Rules:
      workers <= cpu cores (respecting optional cap)
      workers <= available_ram_mb * safety_margin / per_task_ram_mb

    Returns at least 1. Never exceeds the configured safety margin.
    """
    cfg = cfg or load_parallelism_config()
    global_cfg = get_global_config(cfg)

    if per_task_ram_mb is None:
        per_task_ram_mb = int(global_cfg.get("default_per_task_ram_mb", 512))
    if safety_margin is None:
        safety_margin = float(global_cfg.get("safety_margin_ram", 0.8))

    cores = detect_cpu()
    if cpu_cap is not None:
        cores = min(cores, max(1, int(cpu_cap)))

    ram = detect_ram()
    ram_workers = max(1, int((ram["available_mb"] * safety_margin) // max(1, per_task_ram_mb)))

    limit = min(cores, ram_workers)
    if max_workers is not None:
        limit = min(limit, max(1, int(max_workers)))
    return max(1, limit)


def safe_io_worker_limit(
    max_workers: int | None = None,
    cfg: dict | None = None,
) -> int:
    """Compute a safe worker count for I/O-bound stages (downloads).

    I/O-bound work does not scale on CPU cores the way CPU-bound work does;
    the limiting factors are bandwidth, disk pressure, and memory. We use:

      workers = min(
          io_worker_cap (config, default 8),
          available_ram_mb * safety_margin / per_task_ram_mb,
          explicit max_workers if given,
      )

    The cap keeps concurrent transfers bounded so aggregate bandwidth and
    disk write pressure stay predictable, instead of blindly spawning one
    worker per core.
    """
    cfg = cfg or load_parallelism_config()
    global_cfg = get_global_config(cfg)
    per_task = int(global_cfg.get("default_per_task_ram_mb", 512))
    margin = float(global_cfg.get("safety_margin_ram", 0.8))

    io_cap = int(global_cfg.get("io_worker_cap", 8))

    ram = detect_ram()
    ram_workers = max(1, int((ram["available_mb"] * margin) // max(1, per_task)))

    limit = min(io_cap, ram_workers)
    if max_workers is not None:
        limit = min(limit, max(1, int(max_workers)))
    return max(1, limit)


def has_ram_headroom(min_available_mb: int | None = None, cfg: dict | None = None) -> bool:
    """Backpressure check: True if available RAM is above the margin."""
    cfg = cfg or load_parallelism_config()
    global_cfg = get_global_config(cfg)
    if min_available_mb is None:
        per_task = int(global_cfg.get("default_per_task_ram_mb", 512))
        min_available_mb = per_task * 2
    ram = detect_ram()
    return ram["available_mb"] >= min_available_mb


def detect_gpu() -> dict:
    """GPU awareness placeholder — never crashes, never assumes GPU exists.

    Returns {'present': bool, 'count': int, 'name': str | None}.
    """
    try:
        import subprocess

        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            names = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
            return {"present": True, "count": len(names), "name": names[0] if names else "unknown"}
    except Exception:
        pass
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            return {"present": True, "count": torch.cuda.device_count(), "name": torch.cuda.get_device_name(0)}
    except Exception:
        pass
    return {"present": False, "count": 0, "name": None}
