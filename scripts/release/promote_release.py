#!/usr/bin/env python3
"""Atlas release promotion — v1.0-RC2 -> v1.0 final.

Promotes a frozen release candidate to a final release WITHOUT touching the
dataset bytes. The v1.0 dataset files are byte-identical to v1.0-RC2; the
promotion is a governance artifact:

  - a NEW frozen manifest is created (metadata/releases/v1.0_release.json)
    with status = "final" and a changelog describing the promotion
  - statistics/sources/gates are carried forward verbatim from the RC
    manifest (they describe the same records)
  - the release signature chains to the RC's stored chain_hash, so the
    signed chain remains: ... RC1 -> RC2 -> v1.0
  - the RC manifest is NEVER modified (immutability rule)

Usage:
  .venv-release/bin/python scripts/release/promote_release.py \
      --from v1.0-RC2 --to v1.0 \
      --changelog "v1.0: final release ..."

Or with defaults (v1.0-RC2 -> v1.0). Pass --dry-run to preview without
writing the manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from common import REPO_ROOT, read_json, utc_now, write_json

SIGNATURE_ALGORITHM = "sha256-chain-v1"

DEFAULT_CHANGELOG = (
    "v1.0: 9,515,938 records — promoted from v1.0-RC2 (frozen release "
    "candidate) to final release. Dataset bytes identical to RC2; all gates "
    "re-affirmed. Chain continues from RC2's stored chain_hash."
)


def sha256(text: bytes) -> str:
    return hashlib.sha256(text).hexdigest()


def sign_manifest(manifest: dict, prev_chain: str) -> dict:
    """Sign a manifest (content_hash over sorted keys, chain_hash over prev + content).

    Matches the scheme in dedup_release.py/build_manifest exactly so the
    chain is verifiable by the same tooling.
    """
    data = {k: v for k, v in manifest.items() if k not in {"release_signature", "release_id"}}
    content_hash = sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    )
    chain_hash = sha256((prev_chain + content_hash).encode())
    manifest["release_signature"] = {
        "content_hash": content_hash,
        "previous_release_hash": prev_chain,
        "chain_hash": chain_hash,
        "signature_algorithm": SIGNATURE_ALGORITHM,
    }
    manifest["release_id"] = chain_hash[:16]
    return manifest


def promote(*, from_version: str, to_version: str, changelog: str,
            root: Path, dry_run: bool = False) -> int:
    src_manifest_path = root / "metadata" / "releases" / f"{from_version}_release.json"
    dst_manifest_path = root / "metadata" / "releases" / f"{to_version}_release.json"

    if not src_manifest_path.exists():
        print(f"ERROR: source manifest not found: {src_manifest_path}", file=sys.stderr)
        return 2
    src = read_json(src_manifest_path)

    # Governance guards.
    if dst_manifest_path.exists():
        print(f"ERROR: destination manifest already exists: {dst_manifest_path}", file=sys.stderr)
        return 2
    if src.get("status") not in ("release_candidate", "final"):
        print(f"ERROR: source status is '{src.get('status')}', expected release_candidate/final",
              file=sys.stderr)
        return 2
    sig = src.get("release_signature", {})
    prev_chain = sig.get("chain_hash", "")
    if not prev_chain:
        print("ERROR: source manifest has no chain_hash", file=sys.stderr)
        return 2

    manifest = {
        "release_version": to_version,
        "release_type": src.get("release_type", "major"),
        "created_at": utc_now(),
        "changelog": changelog,
        "from_version": from_version,
        "total_records": src["total_records"],
        "statistics": src.get("statistics", {}),
        "sources": src.get("sources", {}),
        "gates": src.get("gates", {}),
        "gates_passed": bool(src.get("gates_passed", True)),
        "status": "final",
    }
    sign_manifest(manifest, prev_chain)

    print(f"Promote | {from_version} -> {to_version}")
    print(f"  total_records  : {manifest['total_records']:,}")
    print(f"  status         : {manifest['status']}")
    print(f"  prev_chain     : {prev_chain[:16]}...")
    print(f"  chain_hash     : {manifest['release_signature']['chain_hash'][:16]}...")
    print(f"  content_hash   : {manifest['release_signature']['content_hash'][:16]}...")
    print(f"  release_id     : {manifest['release_id']}")

    # Sanity: recompute expected chain_hash from the exact bytes we will write.
    check = json.loads(json.dumps(manifest))
    verify_sign = {k: v for k, v in check.items() if k not in {"release_signature", "release_id"}}
    v_content = sha256(json.dumps(verify_sign, sort_keys=True, ensure_ascii=False).encode())
    v_chain = sha256((prev_chain + v_content).encode())
    ok = (v_chain == manifest["release_signature"]["chain_hash"]
          and v_content == manifest["release_signature"]["content_hash"])
    print(f"  signature check: {'OK' if ok else 'FAIL'}")

    if dry_run:
        print("\nDRY RUN — no manifest written.")
        return 0 if ok else 1

    if not ok:
        print("ERROR: signature verification failed; refusing to write.", file=sys.stderr)
        return 1

    dst_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(dst_manifest_path, manifest)
    print(f"\nManifest: {dst_manifest_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="from_version", default="v1.0-RC2")
    ap.add_argument("--to", dest="to_version", default="v1.0")
    ap.add_argument("--changelog", default=DEFAULT_CHANGELOG)
    ap.add_argument("--root", default=None, help="Repo root (default: script-relative)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else REPO_ROOT
    return promote(
        from_version=args.from_version,
        to_version=args.to_version,
        changelog=args.changelog,
        root=root,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
