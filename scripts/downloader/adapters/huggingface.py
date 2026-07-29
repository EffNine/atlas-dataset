#!/usr/bin/env python3
"""HuggingFace Hub source adapter (stdlib HTTP — no ``datasets`` dependency)."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from .base import DownloadResult, DownloadStatus, SourceAdapter
from ..http_util import fetch_bytes

_HF_DATASET_RE = re.compile(
    r"https?://huggingface\.co/(?:datasets/)?(?P<repo>[\w.-]+/[\w.-]+)",
    re.IGNORECASE,
)


class HuggingFaceAdapter(SourceAdapter):
    name = "huggingface"
    description = "Download HuggingFace dataset files via Hub HTTP API"

    def supports(self, source: dict[str, Any]) -> bool:
        url = (source.get("url") or "").strip()
        name = (source.get("name") or "").strip()
        if _HF_DATASET_RE.search(url):
            return True
        if "huggingface" in url.lower():
            return True
        # Bare org/name with HF-looking path and no other scheme
        if "/" in name and not name.startswith("http") and "github.com" not in name:
            # Prefer HF when URL already points there; otherwise let URL decide
            return "huggingface.co" in url.lower() or source.get("source_type") == "huggingface"
        return source.get("source_type") == "huggingface"

    def download(self, source: dict[str, Any], *, dry_run: bool = False) -> DownloadResult:
        repo = self._repo_id(source)
        source_ref = self.source_ref(source)
        api_url = f"https://huggingface.co/api/datasets/{quote(repo, safe='/')}"
        result = DownloadResult(
            source_ref=source_ref,
            adapter=self.name,
            status=DownloadStatus.PLANNED,
            url=api_url,
            metadata={"repo": repo},
        )

        try:
            body, _, _ = fetch_bytes(
                api_url,
                timeout=self.cache.timeout,
                max_retries=self.cache.max_retries,
                backoff_base=self.cache.backoff_base,
            )
            info = json.loads(body.decode("utf-8"))
        except Exception as exc:
            result.status = DownloadStatus.FAILED
            result.errors.append(f"Hub API lookup failed for {repo}: {exc}")
            return result

        siblings = info.get("siblings") or []
        file_names = [s.get("rfilename") for s in siblings if s.get("rfilename")]
        selected = self._select_files(file_names)
        result.files = [{"filename": f, "url": self._resolve_url(repo, f)} for f in selected]
        result.metadata["available_files"] = len(file_names)
        result.metadata["selected_files"] = len(selected)

        if dry_run:
            result.status = DownloadStatus.PLANNED
            result.summary = (
                f"Would download {len(selected)}/{len(file_names)} file(s) from {repo}"
            )
            return result

        if not selected:
            result.status = DownloadStatus.FAILED
            result.errors.append(f"no downloadable files selected for {repo}")
            return result

        entries = []
        downloaded_files: list[dict[str, Any]] = []
        for filename in selected:
            file_ref = f"{source_ref}:{filename}"
            url = self._resolve_url(repo, filename)
            try:
                entry = self.cache.download_url(
                    url,
                    file_ref,
                    adapter=self.name,
                    metadata={"repo": repo, "filename": filename},
                )
                entries.append(entry)
                downloaded_files.append(
                    {
                        "filename": filename,
                        "url": url,
                        "checksum": entry.checksum,
                        "size_bytes": entry.size_bytes,
                        "source_ref": file_ref,
                    }
                )
            except Exception as exc:
                result.errors.append(f"{filename}: {exc}")

        result.files = downloaded_files or result.files
        result.entries = entries

        if entries and not result.errors:
            result.status = DownloadStatus.DOWNLOADED
            result.summary = f"Downloaded {len(entries)} file(s) from {repo}"
        elif entries:
            result.status = DownloadStatus.DOWNLOADED
            result.summary = (
                f"Downloaded {len(entries)} file(s) from {repo} "
                f"with {len(result.errors)} error(s)"
            )
            result.warnings.extend(list(result.errors))
        else:
            result.status = DownloadStatus.FAILED
            result.summary = f"Failed to download any files from {repo}"

        self.cache.write_manifest(
            source_ref,
            [
                {
                    "filename": (e.metadata or {}).get("filename"),
                    "checksum": e.checksum,
                    "size_bytes": e.size_bytes,
                    "source_ref": e.source_ref,
                }
                for e in entries
            ],
        )
        return result

    def _repo_id(self, source: dict[str, Any]) -> str:
        url = (source.get("url") or "").strip()
        match = _HF_DATASET_RE.search(url)
        if match:
            return match.group("repo")
        name = (source.get("name") or "").strip()
        if "/" in name:
            return name.split()[0]
        raise ValueError(f"cannot determine HuggingFace repo id from source {source.get('id')}")

    def _select_files(self, file_names: list[str]) -> list[str]:
        """Prefer small metadata / sample files; avoid multi-GB shards by default."""
        explicit = self.config.get("files")
        if explicit:
            wanted = set(explicit)
            return [f for f in file_names if f in wanted]

        max_files = int(self.config.get("max_files", 3))
        prefer_ext = {".json", ".jsonl", ".parquet", ".csv", ".txt", ".md"}
        # Prefer README / dataset card / small config files first, then data files
        priority = []
        data = []
        for name in file_names:
            lower = name.lower()
            if lower in {"readme.md", "dataset_infos.json", ".gitattributes"}:
                priority.append(name)
            elif any(lower.endswith(ext) for ext in prefer_ext):
                # skip obvious huge shards unless explicitly requested
                if re.search(r"-of-\d+", lower) or "train-" in lower:
                    data.append(name)
                else:
                    priority.append(name)
            else:
                data.append(name)

        selected = priority[:max_files]
        if len(selected) < max_files:
            selected.extend(data[: max_files - len(selected)])
        return selected

    @staticmethod
    def _resolve_url(repo: str, filename: str) -> str:
        return (
            f"https://huggingface.co/datasets/{quote(repo, safe='/')}"
            f"/resolve/main/{quote(filename, safe='/')}"
        )
