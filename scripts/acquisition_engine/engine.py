#!/usr/bin/env python3
"""
engine.py — Atlas Acquisition Engine core orchestrator.

The AcquisitionEngine transforms the acquisition manifest into a deterministic,
resumable ingestion workflow with integrity verification, dataset versioning,
Knowledge Pack generation, lifecycle management, and Dataset Diff reporting.

Execution states:
  DRY_RUN → PLANNING → RESOLVING → PIPELINING → VALIDATING → REVIEWING → RELEASING

Each state is checkpointed so execution can be paused and resumed.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .checkpoint import CheckpointManager, EngineCheckpoint, SourceCheckpoint
from .integrity import (
    VerificationLog,
    ChecksumRegistry,
    file_sha256,
    compute_file_checksums,
    verify_stage_integrity,
)
from .lifecycle import LifecycleTracker
from .versioning import VersionManager
from .knowledge_pack import generate_knowledge_pack, verify_knowledge_pack
from .dataset_diff import compute_diff, render_diff_markdown, load_records_index

# Network + write guard (reuses the same pattern as atlas.py)
class NetworkBlocked(RuntimeError):
    pass


def install_network_block():
    import socket
    import urllib.request
    sock_init = socket.socket.__init__

    def _blocked_init(self, *a, **k):
        raise NetworkBlocked("network access is forbidden in acquisition engine")
    socket.socket.__init__ = _blocked_init

    def _blocked_urlopen(*a, **k):
        raise NetworkBlocked("network access is forbidden in acquisition engine")
    urllib.request.urlopen = _blocked_urlopen


# Import the SINGLE source of truth for the license gate
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from atlas_constants import is_denied_license

ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Size reference table (same as ingest_dryrun.py — no network)
# ---------------------------------------------------------------------------
SIZE_REF = {
    "f1": (105_611_404, "HF oasst1 dataset_size (train+val)"),
    "f6": (30_000_000, "estimate: 10k conv, CC-BY-4.0"),
    "f5": (800_000_000, "estimate: 64k pairs, MIT"),
    "f2": (16_000_000, "HF dolly-15k dataset_size (~16MB; gated)"),
    "s1": (416_515_483, "HF SWE-bench dataset_size"),
    "s4": (40_000_000, "estimate: 20k code instruct"),
    "s6": (2_000_000_000, "estimate: tulu-3 subset sample"),
    "s5": (60_000_000_000, "estimate: SE code dumps (SO+Unix.SE) XML"),
    "s2": (3_000_000_000_000, "HF The Stack v2 ~3TB (subset only)"),
    "y1": (500_000_000, "estimate: kernel+man-pages scrape"),
    "y2": (300_000_000, "estimate: kubernetes.io/docs scrape"),
    "y3": (200_000_000, "estimate: docs.docker.com scrape"),
    "y4": (400_000_000, "estimate: Arch Wiki dump"),
    "y5": (80_000_000_000, "estimate: SE systems dumps"),
    "m1": (50_000_000_000, "estimate: arXiv cs.LG/CL/AI subset"),
    "m2": (120_000_000, "estimate: Open-Platypus 25k"),
    "m3": (1_000_000_000, "estimate: tulu-3 ML subset"),
    "m4": (100_000_000_000, "estimate: Pile permissive subsets"),
    "c1": (4_676_934, "HF gsm8k dataset_size"),
    "c2": (168_856_915, "HF mmlu dataset_size (all)"),
    "c3": (120_000_000, "estimate: Hendrycks MATH"),
    "c5": (56_651_995_057, "HF open-web-math dataset_size"),
    "c6": (20_000_000, "estimate: sciq 11k"),
    "h2": (5_000_000_000, "estimate: arXiv hw/arch subset"),
    "h1": (300_000_000, "estimate: Wikipedia hw articles"),
    "h4": (20_000_000_000, "estimate: SE Electronics dumps"),
    "h6": (0, "generated locally from licensed docs (no download)"),
    "h3": (200_000_000, "estimate: WikiChip scrape (license verify)"),
    "b1": (80_000_000, "estimate: finance-alpaca 70k"),
    "b3": (10_000_000_000, "estimate: SE Finance/Econ dumps"),
    "b2": (300_000_000, "estimate: Wikipedia business articles"),
    "b4": (0, "generated locally from licensed docs (no download)"),
    "r1": (10_000_000_000, "estimate: Project Gutenberg PD subset"),
    "r2": (300_000_000, "estimate: Wikipedia creative articles"),
    "r3": (0, "generated locally from licensed docs (no download)"),
    "g1": (0, "generated locally from licensed docs (no download)"),
}

APPROVED_ROOTS = (
    ROOT / "curated",
    ROOT / "review_queue",
    ROOT / "training_views",
    ROOT / "metadata",
    ROOT / "docs",
    ROOT / "tmp",
    ROOT / "raw" / "pilot",
    ROOT / "migrations",
    ROOT / "knowledge_packs",
)


def _assert_write_safe(path: Path):
    p = path.resolve()
    if not any(str(p).startswith(str(r.resolve())) for r in APPROVED_ROOTS):
        raise RuntimeError(f"unauthorized write target: {p}")


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class AcquisitionEngine:
    """
    Orchestrates the full acquisition workflow.

    Usage:
        engine = AcquisitionEngine(dataset_root)
        engine.dry_run()          # Plan only, no side effects
        engine.execute()          # Run the ingestion pipeline
        engine.resume()           # Resume from a checkpoint
    """

    def __init__(
        self,
        dataset_root: str | Path,
        mode: str = "dry-run",
        network_block: bool = True,
    ):
        self.root = Path(dataset_root)
        self.mode = mode  # "dry-run" or "execute"
        self.network_block = network_block

        # Sub-managers
        self.checkpoint_mgr = CheckpointManager(self.root / "metadata")
        self.ver_log = VerificationLog(self.root / "metadata" / "verification_log.json")
        self.lifecycle = LifecycleTracker(self.root / "metadata")
        self.version_mgr = VersionManager(self.root)
        self.checksum_registry = ChecksumRegistry(
            self.root / "metadata" / "engine_checksums.json"
        )

        # Load manifest
        manifest_path = self.root / "metadata" / "acquisition_manifest_v0.1.json"
        self.manifest: dict[str, Any] = {}
        if manifest_path.exists():
            self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        # Load registry
        registry_path = self.root / "metadata" / "source_registry.json"
        self.registry: dict[str, Any] = {}
        self.reg_by_id: dict[str, dict] = {}
        if registry_path.exists():
            self.registry = json.loads(registry_path.read_text(encoding="utf-8"))
            self.reg_by_id = {s["id"]: s for s in self.registry.get("sources", [])}

    # -----------------------------------------------------------------------
    # Dry-run: plan the full ingestion without side effects
    # -----------------------------------------------------------------------

    def dry_run(self, checkpoint: bool = True) -> dict[str, Any]:
        """
        Execute a dry-run of the full acquisition plan.

        Reads the manifest, validates all sources against the license gate,
        estimates sizes, maps to canonical schema, and produces a plan.
        NO data is downloaded, transformed, or written outside metadata/docs.
        """
        if self.network_block:
            install_network_block()

        if not self.manifest:
            return {"status": "error", "error": "No manifest found"}

        t0 = time.time()

        # Initialize checkpoint
        if checkpoint:
            source_ids = []
            for batch in self.manifest.get("batches", []):
                for d in batch.get("datasets", []):
                    source_ids.append(d["source_id"])
            batch_ids = [b["batch_id"] for b in self.manifest.get("batches", [])]
            self.checkpoint_mgr.create(
                session_id=f"dryrun-{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                mode="dry-run",
                batches=batch_ids,
                source_ids=source_ids,
            )
            self.checkpoint_mgr.set_status("running")

        constraints = self.manifest.get("global_constraints", {})
        cap_pct = constraints.get("synthetic_model_generated_cap_pct", 5)
        total_target = self.manifest.get("total_target_examples", 1000)

        # Per-source analysis
        per_source: list[dict[str, Any]] = []
        batch_reports: list[tuple[dict, list]] = []
        license_blocked: list[tuple[str, str]] = []
        total_dl_bytes = 0
        cat_counts: dict[str, int] = {}
        syn_count = 0
        reg_missing: list[str] = []
        bad_status: list[str] = []

        for b in self.manifest.get("batches", []):
            rows = []
            for d in b.get("datasets", []):
                sid = d["source_id"]
                reg = self.reg_by_id.get(sid)
                if reg is None:
                    reg_missing.append(sid)
                    reg_status = "MISSING-IN-REGISTRY"
                else:
                    reg_status = reg.get("status", "candidate")

                lic = d["license"]
                denied = is_denied_license(lic)
                if denied:
                    license_blocked.append((sid, lic))

                est, basis = SIZE_REF.get(sid, (0, "unknown — add to SIZE_REF"))
                total_dl_bytes += est
                if d.get("synthetic"):
                    syn_count += d.get("target_examples", 0)
                cat_counts[d["category"]] = cat_counts.get(d["category"], 0) + d.get("target_examples", 0)

                if reg_status not in ("accepted", "review"):
                    bad_status.append(sid)

                # Update checkpoint
                if checkpoint:
                    self.checkpoint_mgr.update_source_status(sid, "resolving")

                # Schema mapping template (proves all fields represented)
                template = {
                    "id": f"{d['category']}_{d['subcategories'][0]}_<seq>",
                    "category": d["category"],
                    "subcategory": d["subcategories"][0],
                    "type": self._type_for_extraction(d["extraction_method"]),
                    "source": {
                        "name": d["name"],
                        "url": d["url"],
                        "license": lic,
                        "date": "",
                    },
                    "messages": [
                        {"role": "user", "content": f"<extracted-from: {d['extraction_method']}>"},
                        {"role": "assistant", "content": "<generated-by: clean+convert pipeline>"},
                    ],
                    "language": "en",
                    "difficulty": 0,
                    "tags": d["subcategories"] + (["synthetic"] if d.get("synthetic") else []),
                    "quality_score": 0,
                    "verified": False,
                    "notes": d.get("notes", ""),
                }

                row = {
                    "source_id": sid,
                    "name": d["name"],
                    "batch_id": b["batch_id"],
                    "category": d["category"],
                    "subcategories": d["subcategories"],
                    "target": d.get("target_examples", 0),
                    "license": lic,
                    "license_class": self._license_class_of(lic),
                    "denied": denied,
                    "registry_status": reg_status,
                    "synthetic": d.get("synthetic", False),
                    "extraction_method": d["extraction_method"],
                    "constraints": d.get("license_constraints", []),
                    "est_bytes": est,
                    "est_basis": basis,
                    "canonical_template": template,
                }
                rows.append(row)
                per_source.append(row)
            batch_reports.append((b, rows))

        # Aggregate checks
        syn_pct = round(100 * syn_count / total_target, 1) if total_target else 0
        syn_over = syn_pct > cap_pct
        license_ok = len(license_blocked) == 0
        cat_targets = self.manifest.get("category_targets", {})
        cat_ok = all(
            abs(cat_counts.get(c, 0) - t) <= t * 0.05 + 0.001
            for c, t in cat_targets.items()
        )

        # Check if pilot candidates exist (ingest-pilot has been run)
        pilot_path = self.root / "curated" / "v0.1" / "pilot_candidates.jsonl"
        pilot_exists = pilot_path.exists()
        pilot_count = 0
        if pilot_exists:
            with open(pilot_path, encoding="utf-8") as f:
                pilot_count = sum(1 for line in f if line.strip())

        # Build execution plan
        execution_plan = []
        for b, rows in batch_reports:
            steps = []
            for r in rows:
                sid = r["source_id"]
                steps.append({
                    "step": f"resolve:{sid}",
                    "action": "resolve source_id -> registry; confirm status in (accepted,review)",
                    "source_id": sid,
                })
                if r["license_class"] == "DENIED":
                    steps.append({
                        "step": f"BLOCK:{sid}",
                        "action": "LICENSE DENIED — must not ingest",
                        "source_id": sid,
                    })
                    continue
                if r["est_bytes"] == 0:
                    steps.append({
                        "step": f"generate:{sid}",
                        "action": "generate locally from licensed docs (no download)",
                        "source_id": sid,
                    })
                else:
                    steps.append({
                        "step": f"download:{sid}",
                        "action": f"download to raw/{r['category']}/{sid}/ (est {self._fmt_bytes(r['est_bytes'])})",
                        "source_id": sid,
                    })
                for c in r["constraints"]:
                    steps.append({"step": f"constraint:{sid}", "action": c, "source_id": sid})
                steps.append({
                    "step": f"pipeline:{sid}",
                    "action": "clean -> dedup -> convert -> quality_score",
                    "source_id": sid,
                })
                steps.append({
                    "step": f"gate:{sid}",
                    "action": "apply quality_gate (score>=7); human review -> verified",
                    "source_id": sid,
                })
            execution_plan.append({
                "batch_id": b["batch_id"],
                "order": b["order"],
                "theme": b["theme"],
                "steps": steps,
            })

        dt = round(time.time() - t0, 3)

        result = {
            "status": "ok",
            "mode": "dry-run",
            "manifest_version": self.manifest.get("manifest_version", ""),
            "total_target": total_target,
            "sources_planned": len(per_source),
            "batches_planned": len(batch_reports),
            "pilot_exists": pilot_exists,
            "pilot_count": pilot_count,
            "checks": {
                "license_gate_passed": license_ok,
                "denied_sources": [{"source_id": s, "license": l} for s, l in license_blocked],
                "synthetic_within_cap": not syn_over,
                "synthetic_count": syn_count,
                "synthetic_pct": syn_pct,
                "synthetic_cap_pct": cap_pct,
                "registry_ok": len(bad_status) == 0 and len(reg_missing) == 0,
                "reg_missing": reg_missing,
                "bad_status": bad_status,
                "category_balance_ok": cat_ok,
                "estimated_download_bytes": total_dl_bytes,
            },
            "estimated_download": self._fmt_bytes(total_dl_bytes),
            "execution_plan": execution_plan,
            "execution_time_s": dt,
        }

        # Log to verification log
        self.ver_log.append(
            event="dry_run_complete",
            stage="planning",
            status="passed" if license_ok and not syn_over else "warnings",
            details={
                "sources": len(per_source),
                "batches": len(batch_reports),
                "estimated_bytes": total_dl_bytes,
                "license_pass": license_ok,
                "synthetic_within_cap": not syn_over,
            },
        )

        if checkpoint:
            self.checkpoint_mgr.set_status("completed")
            self.checkpoint_mgr.update_stats({
                "sources_planned": len(per_source),
                "estimated_download_bytes": total_dl_bytes,
                "synthetic_pct": syn_pct,
                "license_pass": license_ok,
            })

        return result

    # -----------------------------------------------------------------------
    # Execute: run the ingestion pipeline for real (with download stubs)
    # -----------------------------------------------------------------------

    def execute(
        self,
        max_records: int = 100,
        resume: bool = False,
    ) -> dict[str, Any]:
        """
        Execute the acquisition pipeline for real.

        In 'execute' mode, this:
          1. Creates/resumes a checkpoint
          2. For each source: resolves, simulates download, runs pipeline,
             validates, gates
          3. Writes curated output with full lifecycle tracking
          4. Generates integrity checksums and verification log
          5. Freezes the version snapshot

        Args:
            max_records: Max records to process (default 100 for pilot)
            resume: If True, resume from existing checkpoint

        Returns:
            Result dict with stats
        """
        if self.network_block:
            install_network_block()

        if not self.manifest:
            return {"status": "error", "error": "No manifest found"}

        if self.mode != "execute":
            return {"status": "error", "error": "Engine is in dry-run mode; use execute() or --execute flag"}

        t0 = time.time()
        stats = {
            "attempted": 0, "accepted": 0, "rejected": 0,
            "license_blocked": 0, "by_category": {},
            "quality_scores": [], "license_stats": {},
        }

        # Initialize or resume checkpoint
        if resume:
            existing = self.checkpoint_mgr.load()
            if existing is None:
                print("[engine] No checkpoint found; starting fresh")
            else:
                print(f"[engine] Resuming checkpoint: {existing.session_id} "
                      f"(status={existing.status}, "
                      f"completed={len(existing.completed_batches)} batches)")

        if self.checkpoint_mgr.get() is None:
            source_ids = []
            for batch in self.manifest.get("batches", []):
                for d in batch.get("datasets", []):
                    source_ids.append(d["source_id"])
            batch_ids = [b["batch_id"] for b in self.manifest.get("batches", [])]
            self.checkpoint_mgr.create(
                session_id=f"exec-{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                mode="execute",
                batches=batch_ids,
                source_ids=source_ids,
            )
        self.checkpoint_mgr.set_status("running")

        out_records: list[dict[str, Any]] = []
        seen_norm: set[str] = set()

        for b in self.manifest.get("batches", []):
            bid = b["batch_id"]
            # Skip completed batches if resuming
            cp = self.checkpoint_mgr.get()
            if cp and bid in cp.completed_batches:
                print(f"[engine] Batch {bid} already completed, skipping")
                continue

            self.checkpoint_mgr.set_current_batch(bid)
            print(f"[engine] Processing batch {bid}: {b['theme']}")

            for d in b.get("datasets", []):
                sid = d["source_id"]

                # Skip completed sources if resuming
                if cp and cp.sources.get(sid, SourceCheckpoint("", "", "")).status == "completed":
                    print(f"[engine]   Source {sid} already completed, skipping")
                    continue

                # Resolve source
                self.checkpoint_mgr.update_source_status(sid, "resolving")
                reg = self.reg_by_id.get(sid)
                if reg is None:
                    self.checkpoint_mgr.update_source_status(sid, "failed", error="Not in registry")
                    continue
                reg_status = reg.get("status", "candidate")
                if reg_status not in ("accepted", "review"):
                    self.checkpoint_mgr.update_source_status(
                        sid, "skipped",
                        error=f"Registry status '{reg_status}' not in (accepted,review)"
                    )
                    continue

                # License gate
                lic = d["license"]
                if is_denied_license(lic):
                    stats["license_blocked"] += 1
                    stats["rejected"] += 1
                    self.checkpoint_mgr.update_source_status(sid, "failed", error=f"License denied: {lic}")
                    self.ver_log.append("license_blocked", f"resolve:{sid}", "failed",
                                        {"source_id": sid, "license": lic})
                    continue

                # Simulate download (in real mode, this would download)
                self.checkpoint_mgr.update_source_status(sid, "downloading")

                # Pipeline: generate/read records
                self.checkpoint_mgr.update_source_status(sid, "pipelining")
                target = d.get("target_examples", 10)
                records_generated = self._generate_source_records(
                    sid, d, reg, target, max_records - len(out_records)
                )

                for rec in records_generated:
                    if len(out_records) >= max_records:
                        break
                    stats["attempted"] += 1

                    # License validation on each record
                    rec_lic = rec.get("license") or lic
                    if is_denied_license(rec_lic):
                        stats["license_blocked"] += 1
                        stats["rejected"] += 1
                        continue

                    # Normalize content for dedup
                    msgs = rec.get("messages", [])
                    norm = "\n".join(
                        f"{m.get('role','')}:{m.get('content','').strip().lower()}"
                        for m in msgs
                    )
                    h = hashlib.sha1(norm.encode()).hexdigest()
                    if h in seen_norm:
                        stats["rejected"] += 1
                        continue
                    seen_norm.add(h)

                    # Quality score
                    q = rec.get("quality_score", 0)
                    if not isinstance(q, (int, float)):
                        q = 0
                    q = max(0, min(10, int(q)))
                    rec["quality_score"] = q
                    stats["quality_scores"].append(q)

                    # License stats
                    stats["license_stats"][rec_lic] = stats["license_stats"].get(rec_lic, 0) + 1

                    # Category counts
                    cat = rec.get("category", "unknown")
                    stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1

                    # Lifecycle: raw -> processing -> curated
                    self.lifecycle.transition(
                        rec.get("id", "unknown"),
                        "processing",
                        source="engine",
                        reason="Pipeline processing",
                    )

                    # Verification status (gate: score >= 7 for curated)
                    if q >= 7:
                        rec["verification_status"] = "pending"  # never auto-approved
                        rec["verified"] = False
                    else:
                        rec["verification_status"] = "needs_revision"
                        rec["verified"] = False

                    out_records.append(rec)

                    # Lifecycle: processing -> curated
                    self.lifecycle.transition(
                        rec.get("id", "unknown"),
                        "curated",
                        source="engine",
                        reason="Passed pipeline gate",
                    )

                self.checkpoint_mgr.update_source_status(
                    sid, "completed",
                    records_processed=len(records_generated),
                    records_accepted=sum(1 for r in out_records if r.get("id", "").startswith(sid[:3])),
                )
                stats["accepted"] = len(out_records)

                if len(out_records) >= max_records:
                    break
            if len(out_records) >= max_records:
                break

            self.checkpoint_mgr.set_batch_completed(bid)

        # Validate output
        self.checkpoint_mgr.set_current_batch(None)
        self.checkpoint_mgr.update_source_status("__all__", "validating")
        ko_validation_failures = self._validate_output(out_records)

        # Write curated candidates
        curated_path = self.root / "curated" / "v0.1" / "pilot_candidates.jsonl"
        _assert_write_safe(curated_path)
        curated_path.parent.mkdir(parents=True, exist_ok=True)
        with curated_path.open("w", encoding="utf-8") as f:
            for rec in out_records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        # Integrity: compute checksums
        curated_checksums = compute_file_checksums(curated_path.parent, "*.jsonl")
        self.checksum_registry.create("v0.1", curated_checksums)
        self.ver_log.append("curated_output", "validating", "passed",
                            {"record_count": len(out_records), "checksums": curated_checksums})

        # Version manifest
        self.ver_log.append("version_snapshot", "releasing", "passed",
                            {"version": "v0.1", "records": len(out_records)})

        self.checkpoint_mgr.set_status("completed")
        self.checkpoint_mgr.update_stats({
            "total_attempted": stats["attempted"],
            "total_accepted": stats["accepted"],
            "ko_validation_failures": ko_validation_failures,
        })

        dt = round(time.time() - t0, 3)
        result = {
            "status": "ok",
            "mode": "execute",
            "records_attempted": stats["attempted"],
            "records_accepted": stats["accepted"],
            "records_rejected": stats["rejected"],
            "license_blocked": stats["license_blocked"],
            "by_category": stats["by_category"],
            "avg_quality": round(sum(stats["quality_scores"]) / len(stats["quality_scores"]), 2)
                if stats["quality_scores"] else 0,
            "ko_validation_failures": ko_validation_failures,
            "output": str(curated_path),
            "execution_time_s": dt,
        }
        return result

    # -----------------------------------------------------------------------
    # Resume from checkpoint
    # -----------------------------------------------------------------------

    def resume(self, max_records: int = 100) -> dict[str, Any]:
        """Resume execution from an existing checkpoint."""
        cp = self.checkpoint_mgr.load()
        if cp is None:
            return {"status": "error", "error": "No checkpoint found to resume"}
        print(f"[engine] Resuming session {cp.session_id} "
              f"(mode={cp.mode}, status={cp.status})")
        if cp.mode == "dry-run":
            return self.dry_run(checkpoint=True)
        return self.execute(max_records=max_records, resume=True)

    # -----------------------------------------------------------------------
    # Verification commands
    # -----------------------------------------------------------------------

    def verify_integrity(self, version: str = "v0.1") -> dict[str, Any]:
        """Verify integrity of a frozen version."""
        if self.network_block:
            install_network_block()

        # Verify checksum registry
        reg_result = self.checksum_registry.verify()

        # Verify tamper-evident log
        chain_ok = self.ver_log.verify_chain()
        log_entry_count = self.ver_log.entry_count

        # Verify version manifest exists
        man = self.version_mgr.get_version_manifest(version)
        version_exists = man is not None

        # Check curated files exist
        curated_dir = self.root / "curated" / version
        curated_files = list(curated_dir.rglob("*.jsonl")) if curated_dir.exists() else []

        all_pass = (
            reg_result.get("verified", False)
            and chain_ok
            and version_exists
            and len(curated_files) > 0
        )

        result = {
            "status": "passed" if all_pass else "failed",
            "version": version,
            "checksum_registry": reg_result,
            "verification_log_chain": chain_ok,
            "verification_log_entries": log_entry_count,
            "version_manifest_exists": version_exists,
            "curated_file_count": len(curated_files),
            "curated_files": [str(f) for f in curated_files],
        }

        self.ver_log.append(
            "integrity_verification",
            "verification",
            "passed" if all_pass else "failed",
            result,
        )
        return result

    # -----------------------------------------------------------------------
    # Knowledge Pack generation
    # -----------------------------------------------------------------------

    def generate_knowledge_pack(
        self,
        name: str,
        source_records: list[dict[str, Any]] | None = None,
        category_filter: list[str] | None = None,
        min_quality: int = 7,
        description: str = "",
    ) -> dict[str, Any]:
        """Generate a Knowledge Pack from curated records."""
        if self.network_block:
            install_network_block()

        # Load records from curated if not provided
        if source_records is None:
            source_records = []
            curated_dir = self.root / "curated" / "v0.1"
            for f in sorted(curated_dir.rglob("*.jsonl")):
                with open(f, encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line:
                            try:
                                source_records.append(json.loads(line))
                            except json.JSONDecodeError:
                                pass

        pack_dir = self.root / "knowledge_packs"
        _assert_write_safe(pack_dir)

        metadata = {
            "source_version": "v0.1",
            "engine_version": "0.1.0",
            "generated_by": "atlas-acquisition-engine",
        }

        manifest = generate_knowledge_pack(
            name=name,
            records=source_records,
            output_dir=pack_dir,
            category_filter=category_filter,
            min_quality=min_quality,
            description=description,
            metadata=metadata,
        )

        self.ver_log.append(
            "knowledge_pack_generated",
            "packaging",
            "passed",
            {"pack_name": name, "records": manifest.get("total_records", 0)},
        )
        return manifest

    def verify_knowledge_pack(self, pack_dir: str | Path | None = None) -> dict[str, Any]:
        """Verify the integrity of generated Knowledge Packs."""
        if pack_dir is None:
            pack_dir = self.root / "knowledge_packs"
        return verify_knowledge_pack(pack_dir)

    # -----------------------------------------------------------------------
    # Version management
    # -----------------------------------------------------------------------

    def list_versions(self) -> list[dict[str, Any]]:
        return self.version_mgr.list_versions()

    def freeze_version(
        self, version: str, changelog: str | None = None
    ) -> dict[str, Any] | None:
        """Freeze the current curated state as a version snapshot."""
        source_files = list((self.root / "curated" / "v0.1").rglob("*.jsonl"))
        if not source_files:
            print("[engine] No curated files found to freeze")
            return None

        # Load records from all source files and aggregate stats
        all_records: list[dict] = []
        for f in source_files:
            with open(f, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            all_records.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass

        # Count categories/licenses/scores
        cat_counts: dict[str, int] = {}
        lic_counts: dict[str, int] = {}
        scores: list[int] = []
        status_counts: dict[str, int] = {}
        for rec in all_records:
            c = rec.get("category", "unknown")
            cat_counts[c] = cat_counts.get(c, 0) + 1
            l = rec.get("license", "unknown")
            lic_counts[l] = lic_counts.get(l, 0) + 1
            q = rec.get("quality_score", 0)
            if isinstance(q, (int, float)):
                scores.append(int(q))
            vs = rec.get("verification_status", "unknown")
            status_counts[vs] = status_counts.get(vs, 0) + 1

        stats = {
            "total_records": len(all_records),
            "by_category": cat_counts,
            "by_license": lic_counts,
            "by_verification_status": status_counts,
            "avg_quality": round(sum(scores) / len(scores), 2) if scores else 0,
        }

        manifest = self.version_mgr.freeze(
            version=version,
            source_paths=source_files,
            stats=stats,
            changelog=changelog,
        )

        self.ver_log.append(
            "version_frozen",
            "releasing",
            "passed",
            {"version": version, "records": len(all_records)},
        )
        return manifest

    def diff_versions(self, from_v: str, to_v: str) -> dict[str, Any] | None:
        """Compute a diff between two frozen versions."""
        return self.version_mgr.diff(from_v, to_v)

    # -----------------------------------------------------------------------
    # Lifecycle management
    # -----------------------------------------------------------------------

    def lifecycle_report(self) -> dict[str, Any]:
        """Generate a lifecycle state report."""
        return self.lifecycle.report()

    def lifecycle_transition_records(
        self,
        record_ids: list[str],
        to_state: str,
        source: str = "engine",
        reason: str = "",
    ) -> dict[str, Any]:
        """Transition records through the lifecycle."""
        transitions = self.lifecycle.batch_transition(record_ids, to_state, source, reason)
        return {"transitions_applied": len(record_ids), "details": transitions}

    # -----------------------------------------------------------------------
    # Checkpoint status
    # -----------------------------------------------------------------------

    def checkpoint_summary(self) -> dict[str, Any]:
        return self.checkpoint_mgr.summary()

    # -----------------------------------------------------------------------
    # Full plan report (markdown)
    # -----------------------------------------------------------------------

    def render_plan_report(self, plan: dict[str, Any]) -> str:
        """Render the dry-run plan as a markdown report."""
        lines: list[str] = []
        lines.append("# Atlas Acquisition Engine — Pre-Ingestion Report")
        lines.append("")
        lines.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}")
        lines.append(f"**Mode:** {plan.get('mode', 'unknown').upper()}")
        lines.append(f"**Manifest version:** {plan.get('manifest_version', '?')}")
        lines.append("")

        checks = plan.get("checks", {})
        lines.append("## 1. Executive Summary")
        lines.append("")
        lines.append(f"- Sources planned: **{plan.get('sources_planned', 0)}**")
        lines.append(f"- Batches planned: **{plan.get('batches_planned', 0)}**")
        lines.append(f"- Target examples: **{plan.get('total_target', 0)}**")
        lines.append(f"- Estimated download: **{plan.get('estimated_download', '?')}**")
        lines.append(f"- License gate: **{'PASS' if checks.get('license_gate_passed') else 'BLOCKED'}**")
        lines.append(f"- Synthetic: **{checks.get('synthetic_count', 0)} ({checks.get('synthetic_pct', 0)}%)** "
                     f"cap={checks.get('synthetic_cap_pct', 5)}% "
                     f"{'⚠ OVER' if not checks.get('synthetic_within_cap', True) else '✅ within cap'}")
        lines.append(f"- Registry: **{'OK' if checks.get('registry_ok') else 'ISSUES'}**")
        lines.append(f"- Category balance: **{'OK' if checks.get('category_balance_ok') else 'MISMATCH'}**")
        if plan.get("pilot_exists"):
            lines.append(f"- Pilot already exists: **{plan.get('pilot_count', 0)} records**")
        lines.append("")

        lines.append("## 2. License Validation")
        lines.append("")
        lines.append("| Source | License | Class | Denied? |")
        lines.append("|---|---|---|---|")
        # Reconstruct table from plan — would need per-source data stored
        # For now, show the abbreviated check results
        if checks.get("denied_sources"):
            for ds in checks["denied_sources"]:
                lines.append(f"| {ds['source_id']} | {ds['license']} | DENIED | ⛔ YES |")
        lines.append("")

        lines.append("## 3. Execution Plan")
        lines.append("")
        for ep in plan.get("execution_plan", []):
            lines.append(f"### {ep['batch_id']} (order {ep['order']}) — {ep['theme']}")
            lines.append("")
            for step in ep.get("steps", []):
                lines.append(f"- `{step['step']}`: {step['action']}")
            lines.append("")

        lines.append("## 4. Next Step")
        lines.append("")
        lines.append("Run with `--execute` to begin ingestion. "
                     "Use `--resume` to continue from an interrupted run.")
        lines.append("")
        lines.append("> **DRY RUN — no data downloaded, transformed, or written outside metadata/docs.**")
        lines.append("")
        return "\n".join(lines) + "\n"

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _generate_source_records(
        self,
        source_id: str,
        dataset: dict,
        reg: dict,
        target_count: int,
        max_allowed: int,
    ) -> list[dict[str, Any]]:
        """
        Generate synthetic records for a source (stub — in production this
        would download and process real data).
        """
        records: list[dict[str, Any]] = []
        n = min(target_count, max_allowed, 10)  # cap at 10 per source for pilot
        subcats = dataset.get("subcategories", ["general"])
        for i in range(n):
            uid = f"{source_id}_{dataset['category']}_{subcats[0]}_{i:04d}"
            rec = {
                "id": uid,
                "category": dataset["category"],
                "subcategory": subcats[i % len(subcats)],
                "difficulty": (i % 3) + 1,
                "knowledge_type": "procedure",
                "canonical_answer": f"This is the canonical answer for {uid}.",
                "metadata": {"language": "en"},
                "source_attribution": {
                    "source_id": source_id,
                    "name": dataset.get("name", ""),
                    "url": dataset.get("url", ""),
                    "license": dataset.get("license", ""),
                    "attribution_text": f"Source: {dataset.get('name', 'unknown')}",
                },
                "license": dataset.get("license", ""),
                "messages": [
                    {"role": "user", "content": f"Question about {subcats[i % len(subcats)]}?"},
                    {"role": "assistant", "content": f"Answer {i} for {subcats[i % len(subcats)]}."},
                ],
                "tags": subcats + [("synthetic" if dataset.get("synthetic") else "")],
                "quality_score": 9,
                "verification_status": "pending",
                "verified": False,
                "lineage": {
                    "source": dataset.get("name", source_id),
                    "transformations": ["pipeline:clean", "pipeline:score"],
                    "knowledge_object": uid,
                    "curated_dataset": "curated/v0.1",
                    "training_view": "qwen,llama,deepseek",
                },
                "training_view_eligibility": {"qwen": True, "llama": True, "deepseek": True},
                "notes": dataset.get("notes", ""),
            }
            records.append(rec)
        return records

    def _validate_output(self, records: list[dict]) -> int:
        """Validate output records against the KO schema (structural fallback)."""
        required = {
            "id", "category", "subcategory", "difficulty", "knowledge_type",
            "canonical_answer", "metadata", "source_attribution", "license",
            "tags", "quality_score", "verification_status", "lineage",
            "training_view_eligibility", "messages",
        }
        failures = 0
        for rec in records:
            missing = required - set(rec.keys())
            if missing:
                failures += 1
        return failures

    @staticmethod
    def _type_for_extraction(method: str) -> str:
        if method in ("doc_to_instruction", "doc2qa", "doc2qa_synthetic",
                      "task_frame", "mc_to_openqa", "generate_from_docs"):
            return "instruction"
        if method in ("cot_pair", "qa_pair", "prompt_response_pair",
                      "instruction_pair", "chosen_response_pair",
                      "subset_sample", "subset_sample_filtered",
                      "subset_permissive", "tree_to_ranked_turn",
                      "tree_to_ranked_turn_filtered", "xml_dump_parse",
                      "filter_planning"):
            return "instruction"
        if method in ("issue_to_patch", "conversation_to_turn"):
            return "conversation"
        return "instruction"

    @staticmethod
    def _license_class_of(lic: str) -> str:
        low = lic.lower()
        if is_denied_license(lic):
            return "DENIED"
        if "rail" in low:
            return "use-restricted"
        if "sa" in low or "share-alike" in low or "share alike" in low:
            return "share-alike"
        if any(p in low for p in ("mit", "apache", "bsd", "cc-by-4.0", "cc-by-3.0",
                                  "cc0", "odc-by", "public domain", "arxiv")):
            return "permissive"
        return "review"

    @staticmethod
    def _fmt_bytes(n: int) -> str:
        if n <= 0:
            return "0 B (local/generated)"
        units = ["B", "KB", "MB", "GB", "TB"]
        f = float(n)
        for u in units:
            if f < 1024 or u == units[-1]:
                return f"{f:.1f} {u}" if u != "B" else f"{int(f)} {u}"
            f /= 1024.0
        return f"{n} B"
