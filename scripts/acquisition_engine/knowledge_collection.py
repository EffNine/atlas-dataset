#!/usr/bin/env python3
"""
knowledge_collection.py — Atlas Knowledge Collections.

Knowledge Collections are named groupings of Knowledge Packs that form a
higher-level organizational layer. A Collection aggregates multiple Packs
under a thematic or functional umbrella (e.g. "v0.1-foundation" groups all
foundation-domain packs for the v0.1 release).

Each Collection has:
  - A unique name and descriptor
  - Ordered list of member Knowledge Packs (by name or explicit)
  - Aggregated statistics across all member packs
  - Integrity checksums for the collection manifest itself
  - Deterministic, reproducible composition

Hierarchy:
  Dataset > Releases > Knowledge Collections > Knowledge Packs > Records
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .integrity import file_sha256


class KnowledgeCollectionManager:
    """
    Manages Knowledge Collections — named groups of Knowledge Packs.

    Collections live under knowledge_packs/collections/<name>/ and each
    has a collection manifest that defines membership and aggregated stats.
    """

    def __init__(self, dataset_root: str | Path):
        self.root = Path(dataset_root)
        self.collections_dir = self.root / "knowledge_packs" / "collections"
        self.collections_dir.mkdir(parents=True, exist_ok=True)
        self.collection_index_path = self.root / "metadata" / "collection_index.json"

    # -----------------------------------------------------------------------
    # Index management
    # -----------------------------------------------------------------------

    def _load_index(self) -> dict[str, Any]:
        if not self.collection_index_path.exists():
            return {"collections": [], "generated": ""}
        try:
            return json.loads(self.collection_index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError):
            return {"collections": [], "generated": ""}

    def _save_index(self, index: dict[str, Any]) -> None:
        self.collection_index_path.write_text(
            json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def list_collections(self) -> list[dict[str, Any]]:
        """List all registered collections."""
        index = self._load_index()
        return index.get("collections", [])

    def get_collection(self, name: str) -> dict[str, Any] | None:
        """Get a collection by name."""
        for c in self.list_collections():
            if c.get("name") == name:
                return c
        return None

    def collection_exists(self, name: str) -> bool:
        return self.get_collection(name) is not None

    # -----------------------------------------------------------------------
    # Collection creation
    # -----------------------------------------------------------------------

    def create_collection(
        self,
        name: str,
        pack_names: list[str],
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Create a new Knowledge Collection from existing Knowledge Packs.

        Args:
            name: Collection name (e.g. "v0.1-foundation", "v0.1-all")
            pack_names: List of Knowledge Pack names to include
            description: Human-readable description
            metadata: Optional additional metadata (tags, version, etc.)

        Returns:
            Collection manifest dict
        """
        name = name.strip().lower().replace(" ", "-")
        if not name:
            return {"status": "error", "error": "Collection name cannot be empty"}

        # Verify referenced packs exist
        packs_dir = self.root / "knowledge_packs"
        resolved_packs: list[dict[str, Any]] = []
        missing_packs: list[str] = []
        total_records = 0
        all_categories: dict[str, int] = {}
        all_licenses: dict[str, int] = {}
        quality_scores: list[int] = []
        all_pack_checksums: dict[str, str] = {}

        for pn in pack_names:
            # Look for pack manifest
            man_path = packs_dir / f"{pn}_manifest.json"
            if not man_path.exists():
                # Try under collections subdir
                man_path = self.collections_dir / f"{pn}_manifest.json"
            if not man_path.exists():
                missing_packs.append(pn)
                continue

            try:
                pack_manifest = json.loads(man_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, FileNotFoundError):
                missing_packs.append(pn)
                continue

            pack_records = pack_manifest.get("total_records", 0)
            total_records += pack_records
            pack_cats = pack_manifest.get("statistics", {}).get("by_category", {})
            for cat, count in pack_cats.items():
                all_categories[cat] = all_categories.get(cat, 0) + count
            pack_lics = pack_manifest.get("statistics", {}).get("by_license", {})
            for lic, count in pack_lics.items():
                all_licenses[lic] = all_licenses.get(lic, 0) + count
            avg_q = pack_manifest.get("statistics", {}).get("avg_quality", 0)
            if avg_q:
                quality_scores.append(int(avg_q))

            # Track pack checksum
            checksums_file = packs_dir / f"{pn}_checksums.json"
            if checksums_file.exists():
                try:
                    csums = json.loads(checksums_file.read_text(encoding="utf-8"))
                    all_pack_checksums[pn] = csums.get("checksums", {}).get(pn, "")
                except (json.JSONDecodeError, KeyError):
                    pass

            resolved_packs.append({
                "pack_name": pn,
                "manifest": str(man_path),
                "total_records": pack_records,
            })

        if missing_packs:
            return {
                "status": "error",
                "error": f"Packs not found: {missing_packs}",
                "missing_packs": missing_packs,
            }

        if not resolved_packs:
            return {"status": "error", "error": "No valid packs to include"}

        now = datetime.now(timezone.utc).isoformat()

        # Compute collection checksum
        collection_signature = {
            "name": name,
            "packs": pack_names,
            "total_records": total_records,
            "generated": now,
        }
        csum_input = json.dumps(collection_signature, sort_keys=True, ensure_ascii=False).encode()
        from hashlib import sha256
        collection_checksum = sha256(csum_input).hexdigest()

        manifest: dict[str, Any] = {
            "collection_name": name,
            "collection_version": "1.0",
            "generated": now,
            "description": description,
            "total_packs": len(resolved_packs),
            "total_records": total_records,
            "pack_names": pack_names,
            "packs": resolved_packs,
            "statistics": {
                "by_category": dict(sorted(all_categories.items())),
                "by_license": dict(sorted(all_licenses.items())),
                "avg_quality": round(sum(quality_scores) / len(quality_scores), 2) if quality_scores else 0,
            },
            "collection_checksum": collection_checksum,
        }
        if metadata:
            manifest["metadata"] = metadata

        # Write collection manifest
        col_dir = self.collections_dir / name
        col_dir.mkdir(parents=True, exist_ok=True)
        man_path = col_dir / f"{name}_collection.json"
        man_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Update collection index
        index = self._load_index()
        index["collections"] = [
            c for c in index.get("collections", [])
            if c.get("name") != name
        ]
        index["collections"].append({
            "name": name,
            "description": description,
            "total_packs": len(resolved_packs),
            "total_records": total_records,
            "generated": now,
            "collection_checksum": collection_checksum,
        })
        index["generated"] = now
        self._save_index(index)

        print(f"[collection] Created Knowledge Collection '{name}' — "
              f"{len(resolved_packs)} packs, {total_records} records")
        manifest["status"] = "created"
        return manifest

    # -----------------------------------------------------------------------
    # Collection verification
    # -----------------------------------------------------------------------

    def verify_collection(self, name: str) -> dict[str, Any]:
        """Verify a Knowledge Collection's integrity."""
        col_dir = self.collections_dir / name
        if not col_dir.exists():
            return {"verified": False, "error": f"Collection '{name}' not found"}

        man_path = col_dir / f"{name}_collection.json"
        if not man_path.exists():
            return {"verified": False, "error": "Collection manifest not found"}

        try:
            manifest = json.loads(man_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError) as e:
            return {"verified": False, "error": f"Corrupt manifest: {e}"}

        # Recompute collection checksum
        collection_signature = {
            "name": manifest.get("collection_name", name),
            "packs": manifest.get("pack_names", []),
            "total_records": manifest.get("total_records", 0),
            "generated": manifest.get("generated", ""),
        }
        from hashlib import sha256
        expected_csum = sha256(
            json.dumps(collection_signature, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        stored_csum = manifest.get("collection_checksum", "")
        if expected_csum != stored_csum:
            return {
                "verified": False,
                "error": "Collection checksum mismatch — data may have been modified",
                "expected": expected_csum,
                "stored": stored_csum,
            }

        # Verify all member packs still exist
        packs_dir = self.root / "knowledge_packs"
        errors: list[str] = []
        for pn in manifest.get("pack_names", []):
            man = packs_dir / f"{pn}_manifest.json"
            if not man.exists():
                errors.append(f"Pack '{pn}' manifest not found")
                continue
            csums = packs_dir / f"{pn}_checksums.json"
            if not csums.exists():
                errors.append(f"Pack '{pn}' checksums not found")

        verified = len(errors) == 0
        return {
            "verified": verified,
            "collection_name": name,
            "total_packs": manifest.get("total_packs", 0),
            "total_records": manifest.get("total_records", 0),
            "checksum_match": expected_csum == stored_csum,
            "errors": errors if errors else None,
        }

    # -----------------------------------------------------------------------
    # Utility: list packs in a collection
    # -----------------------------------------------------------------------

    def get_collection_packs(self, name: str) -> list[dict[str, Any]]:
        """Get detailed info about all packs in a collection."""
        col_dir = self.collections_dir / name
        man_path = col_dir / f"{name}_collection.json"
        if not man_path.exists():
            return []
        try:
            manifest = json.loads(man_path.read_text(encoding="utf-8"))
            return manifest.get("packs", [])
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def render_collection_markdown(self, manifest: dict[str, Any]) -> str:
        """Render a collection manifest as markdown."""
        lines: list[str] = []
        lines.append(f"# Knowledge Collection: {manifest.get('collection_name', '?')}")
        lines.append("")
        if manifest.get("description"):
            lines.append(f"{manifest['description']}")
            lines.append("")
        lines.append(f"**Total packs:** {manifest.get('total_packs', 0)}")
        lines.append(f"**Total records:** {manifest.get('total_records', 0)}")
        lines.append(f"**Generated:** {manifest.get('generated', '?')[:19]}")
        lines.append(f"**Collection checksum:** `{manifest.get('collection_checksum', '?')[:16]}...`")
        lines.append("")

        stats = manifest.get("statistics", {})
        cats = stats.get("by_category", {})
        if cats:
            lines.append("## Category Distribution")
            lines.append("")
            lines.append("| Category | Count |")
            lines.append("|---|---|")
            for cat, count in sorted(cats.items()):
                lines.append(f"| {cat} | {count} |")
            lines.append("")

        lics = stats.get("by_license", {})
        if lics:
            lines.append("## License Distribution")
            lines.append("")
            lines.append("| License | Count |")
            lines.append("|---|---|")
            for lic, count in sorted(lics.items()):
                lines.append(f"| {lic} | {count} |")
            lines.append("")

        packs = manifest.get("packs", [])
        if packs:
            lines.append("## Member Packs")
            lines.append("")
            for p in packs:
                lines.append(f"- **{p.get('pack_name', '?')}** — {p.get('total_records', 0)} records")
            lines.append("")

        return "\n".join(lines)
