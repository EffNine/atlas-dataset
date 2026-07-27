#!/usr/bin/env python3
"""
dataset_diff.py — Atlas Dataset Diff reporting between versions.

Generates structured diff reports between two dataset versions, showing:
  * Records added, removed, and changed between versions
  * Category distribution changes
  * Quality score distribution changes
  * License composition changes
  * Summary statistics
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_records_index(
    file_paths: list[Path],
) -> dict[str, dict[str, Any]]:
    """
    Load records from multiple JSONL files into an index by record ID.
    Returns {record_id: record_dict}.
    """
    index: dict[str, dict[str, Any]] = {}
    for fp in file_paths:
        if not fp.exists():
            continue
        with open(fp, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    rid = rec.get("id", "")
                    if rid:
                        index[rid] = rec
                except json.JSONDecodeError:
                    pass
    return index


def compute_diff(
    from_records: dict[str, dict[str, Any]],
    to_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """
    Compute a detailed diff between two sets of records.

    Args:
        from_records: {id: record} for the baseline version
        to_records: {id: record} for the new version

    Returns:
        Dict with added/removed/changed/unchanged analysis.
    """
    from_ids = set(from_records.keys())
    to_ids = set(to_records.keys())

    added_ids = to_ids - from_ids
    removed_ids = from_ids - to_ids
    common_ids = from_ids & to_ids

    # Find changed records among common IDs
    changed_records: list[dict[str, Any]] = []
    field_changes: dict[str, int] = {}
    unchanged_count = 0

    for rid in sorted(common_ids):
        from_rec = from_records[rid]
        to_rec = to_records[rid]

        # Compare key tracking fields (not full object to avoid content-noise)
        tracking_fields = [
            "quality_score", "verification_status", "verified",
            "difficulty", "license", "category", "subcategory",
        ]
        rec_changes: dict[str, tuple[Any, Any]] = {}
        for field in tracking_fields:
            fv = from_rec.get(field)
            tv = to_rec.get(field)
            if fv != tv:
                rec_changes[field] = (fv, tv)
                field_changes[field] = field_changes.get(field, 0) + 1

        if rec_changes:
            changed_records.append({
                "id": rid,
                "category": from_rec.get("category", ""),
                "changes": {
                    field: {"from": fv, "to": tv}
                    for field, (fv, tv) in rec_changes.items()
                },
            })
        else:
            unchanged_count += 1

    # Category distribution changes
    def _category_dist(records: dict[str, dict[str, Any]]) -> dict[str, int]:
        dist: dict[str, int] = {}
        for rec in records.values():
            cat = rec.get("category", "unknown")
            dist[cat] = dist.get(cat, 0) + 1
        return dist

    from_cat_dist = _category_dist(from_records)
    to_cat_dist = _category_dist(to_records)

    all_cats = sorted(set(from_cat_dist.keys()) | set(to_cat_dist.keys()))
    category_delta: dict[str, dict[str, int]] = {}
    for cat in all_cats:
        f = from_cat_dist.get(cat, 0)
        t = to_cat_dist.get(cat, 0)
        if f != t:
            category_delta[cat] = {"from": f, "to": t, "delta": t - f}

    # Quality distribution changes
    def _quality_dist(records: dict[str, dict[str, Any]]) -> dict[str, int]:
        dist: dict[str, int] = {}
        for rec in records.values():
            q = rec.get("quality_score", 0)
            if isinstance(q, (int, float)):
                bucket = str(int(q))
                dist[bucket] = dist.get(bucket, 0) + 1
        return dist

    from_q_dist = _quality_dist(from_records)
    to_q_dist = _quality_dist(to_records)

    # License composition changes
    def _license_dist(records: dict[str, dict[str, Any]]) -> dict[str, int]:
        dist: dict[str, int] = {}
        for rec in records.values():
            lic = rec.get("license", "unknown")
            dist[lic] = dist.get(lic, 0) + 1
        return dist

    from_lic_dist = _license_dist(from_records)
    to_lic_dist = _license_dist(to_records)

    # Added record details (first 10)
    added_details: list[dict[str, Any]] = []
    for rid in sorted(added_ids)[:10]:
        rec = to_records[rid]
        added_details.append({
            "id": rid,
            "category": rec.get("category", ""),
            "quality_score": rec.get("quality_score", 0),
            "license": rec.get("license", ""),
        })

    # Removed record details (first 10)
    removed_details: list[dict[str, Any]] = []
    for rid in sorted(removed_ids)[:10]:
        rec = from_records[rid]
        removed_details.append({
            "id": rid,
            "category": rec.get("category", ""),
            "quality_score": rec.get("quality_score", 0),
        })

    return {
        "summary": {
            "from_total": len(from_ids),
            "to_total": len(to_ids),
            "added": len(added_ids),
            "removed": len(removed_ids),
            "changed": len(changed_records),
            "unchanged": unchanged_count,
            "net_change": len(to_ids) - len(from_ids),
        },
        "category_delta": category_delta,
        "quality_distribution": {
            "from": dict(sorted(from_q_dist.items(), key=lambda x: int(x[0]))),
            "to": dict(sorted(to_q_dist.items(), key=lambda x: int(x[0]))),
        },
        "license_composition": {
            "from": dict(sorted(from_lic_dist.items())),
            "to": dict(sorted(to_lic_dist.items())),
        },
        "field_changes": dict(sorted(field_changes.items(), key=lambda x: -x[1])),
        "added_records": added_details,
        "removed_records": removed_details,
        "changed_records": changed_records[:20],
        "note": "Added/removed/changed details truncated at 10/10/20 items respectively. "
                "Full lists available via the record IDs.",
        "generated": datetime.now(timezone.utc).isoformat(),
    }


def render_diff_markdown(diff: dict[str, Any]) -> str:
    """Render a diff dict as a readable markdown report."""
    lines: list[str] = []
    summary = diff.get("summary", {})

    lines.append("# Atlas Dataset Diff Report")
    lines.append("")
    lines.append(f"**Generated:** {diff.get('generated', 'unknown')}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|---|---|")
    lines.append(f"| From version total | {summary.get('from_total', '?')} |")
    lines.append(f"| To version total | {summary.get('to_total', '?')} |")
    lines.append(f"| Added | {summary.get('added', 0)} |")
    lines.append(f"| Removed | {summary.get('removed', 0)} |")
    lines.append(f"| Changed | {summary.get('changed', 0)} |")
    lines.append(f"| Unchanged | {summary.get('unchanged', 0)} |")
    lines.append(f"| Net change | {summary.get('net_change', 0):+d} |")
    lines.append("")

    cat_delta = diff.get("category_delta", {})
    if cat_delta:
        lines.append("## Category Distribution Changes")
        lines.append("")
        lines.append("| Category | From | To | Delta |")
        lines.append("|---|---|---|---|")
        for cat, delta in cat_delta.items():
            d = delta.get("delta", 0)
            sign = f"+{d}" if d > 0 else str(d)
            lines.append(f"| {cat} | {delta.get('from', 0)} | {delta.get('to', 0)} | {sign} |")
        lines.append("")

    q_dist = diff.get("quality_distribution", {})
    if q_dist.get("from") or q_dist.get("to"):
        lines.append("## Quality Score Distribution")
        lines.append("")
        lines.append("| Score | From | To |")
        lines.append("|---|---|---|")
        all_scores = sorted(
            set(q_dist.get("from", {}).keys()) | set(q_dist.get("to", {}).keys()),
            key=int,
        )
        for s in all_scores:
            f = q_dist.get("from", {}).get(s, 0)
            t = q_dist.get("to", {}).get(s, 0)
            lines.append(f"| {s} | {f} | {t} |")
        lines.append("")

    lic_comp = diff.get("license_composition", {})
    if lic_comp.get("from") or lic_comp.get("to"):
        lines.append("## License Composition Changes")
        lines.append("")
        lines.append("| License | From | To |")
        lines.append("|---|---|---|")
        all_lics = sorted(set(lic_comp.get("from", {}).keys()) | set(lic_comp.get("to", {}).keys()))
        for lic in all_lics:
            f = lic_comp.get("from", {}).get(lic, 0)
            t = lic_comp.get("to", {}).get(lic, 0)
            lines.append(f"| {lic} | {f} | {t} |")
        lines.append("")

    changed = diff.get("changed_records", [])
    if changed:
        lines.append("## Changed Records (first 20)")
        lines.append("")
        for cr in changed:
            lines.append(f"- **{cr['id']}** ({cr.get('category', '')}):")
            for field, change in cr.get("changes", {}).items():
                lines.append(f"  - {field}: `{change.get('from')}` → `{change.get('to')}`")
        lines.append("")

    field_ch = diff.get("field_changes", {})
    if field_ch:
        lines.append("## Most-Changed Fields")
        lines.append("")
        lines.append("| Field | Change Count |")
        lines.append("|---|---|")
        for field, count in field_ch.items():
            lines.append(f"| {field} | {count} |")
        lines.append("")

    added = diff.get("added_records", [])
    if added:
        lines.append("## Added Records (first 10)")
        lines.append("")
        for ar in added:
            lines.append(f"- {ar['id']}  (cat={ar.get('category', '')}, "
                         f"score={ar.get('quality_score', 0)}, lic={ar.get('license', '')})")
        lines.append("")

    removed = diff.get("removed_records", [])
    if removed:
        lines.append("## Removed Records (first 10)")
        lines.append("")
        for rr in removed:
            lines.append(f"- {rr['id']}  (cat={rr.get('category', '')}, "
                         f"score={rr.get('quality_score', 0)})")
        lines.append("")

    lines.append("---")
    lines.append(f"*{diff.get('note', '')}*")
    lines.append("")

    return "\n".join(lines) + "\n"
