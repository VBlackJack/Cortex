# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Read-only source freshness reporting for the Cortex index."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from chroma_client import iter_collection_pages
from chunker import chunk_markdown_file
from chunker_pdf import chunk_pdf_file
from chunker_utils import discover_out_of_policy_dirs, is_excluded_path, sha256_bytes
from config import (
    EXCLUDE_FILES,
    EXCLUDED_DIRS,
    FRESHNESS_CONTRACT_ID,
    FRESHNESS_CONTRACT_VERSION,
    INCLUDED_SECTIONS,
    INDEX_WHOLE_FOLDER,
    KB_PATH,
    ROOT_SECTION,
    CortexConfigError,
    require_kb_path,
)

_LOG = logging.getLogger("cortex.freshness")
_HASH_LENGTH = 64


@dataclass(frozen=True)
class FreshnessScope:
    """Explicit source-selection policy for one freshness report.

    Passing this instead of relying on module globals lets a caller (for
    example cortex doctor) run the report against a specific configuration
    without mutating this module's or chunker_utils' globals.
    """

    kb_path: str | None
    included_sections: frozenset[str]
    excluded_dirs: frozenset[str]
    exclude_files: frozenset[str]
    index_whole_folder: bool = False


def _default_scope() -> FreshnessScope:
    """Build the scope from this module's config-derived globals."""
    return FreshnessScope(
        kb_path=KB_PATH,
        included_sections=INCLUDED_SECTIONS,
        excluded_dirs=EXCLUDED_DIRS,
        exclude_files=EXCLUDE_FILES,
        index_whole_folder=INDEX_WHOLE_FOLDER,
    )


@dataclass(frozen=True)
class FileSnapshot:
    """One exact, strict binary read of an eligible Markdown source."""

    path: str
    content_hash: str


def read_source_snapshot(path: Path, kb_root: Path) -> FileSnapshot:
    """Read, contain and hash one source, strictly decoding Markdown."""
    root = kb_root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    try:
        rel_path = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("source path escapes KB_PATH") from exc
    raw = resolved.read_bytes()
    if resolved.suffix.lower() == ".md":
        raw.decode("utf-8", errors="strict")
    return FileSnapshot(path=rel_path.as_posix(), content_hash=sha256_bytes(raw))


def read_markdown_snapshot(path: Path, kb_root: Path) -> FileSnapshot:
    """Backward-compatible strict Markdown snapshot helper."""
    return read_source_snapshot(path, kb_root)


def cortex_freshness_report(
    collection: Any,
    section: str | None = None,
    include_entries: bool = True,
    emit_log: bool = True,
    *,
    scope: FreshnessScope | None = None,
) -> dict[str, Any]:
    """Compare live sources with index metadata without writing either system.

    The selection policy comes from ``scope`` when given, otherwise from this
    module's config-derived globals (see _default_scope). Callers that need a
    specific configuration pass ``scope`` rather than mutating globals."""
    active = scope if scope is not None else _default_scope()
    started = perf_counter()
    root = Path(require_kb_path(active.kb_path))
    indexed, invalid_paths = _indexed_metadata(collection, section)
    entries: list[dict[str, str]] = []
    seen_paths: set[str] = set()

    for path, reason in invalid_paths.items():
        entries.append({"path": path, "status": "error", "reason": reason})

    if not root.is_dir():
        return _report(
            entries,
            started,
            active,
            scope_error="KB_PATH is not a directory",
            include_entries=include_entries,
            emit_log=emit_log,
        )

    for excluded in _discover_excluded(root, section, active):
        rel_path = excluded.relative_to(root).as_posix()
        seen_paths.add(rel_path)
        entries.append({"path": rel_path, "status": "excluded"})

    for source in _discover_sources(root, section, active):
        rel_path = source.relative_to(root).as_posix()
        seen_paths.add(rel_path)
        try:
            snapshot = read_source_snapshot(source, root)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            entries.append({"path": rel_path, "status": "error", "reason": str(exc)})
            continue
        entries.append(_classify_present(snapshot, indexed.pop(rel_path, []), source))

    for rel_path, metadata in sorted(indexed.items()):
        if rel_path in seen_paths:
            continue
        status = "missing"
        if is_excluded_path(
            Path(rel_path),
            excluded_dirs=active.excluded_dirs,
            exclude_files=active.exclude_files,
        ):
            status = "excluded"
        entries.append(
            {"path": rel_path, "status": status, "chunks": str(len(metadata))}
        )

    out_of_policy = []
    if not active.index_whole_folder:
        out_of_policy = discover_out_of_policy_dirs(
            root,
            included_sections=active.included_sections,
            excluded_dirs=active.excluded_dirs,
            exclude_files=active.exclude_files,
        )
    return _report(
        entries,
        started,
        active,
        out_of_policy_dirs=out_of_policy,
        include_entries=include_entries,
        emit_log=emit_log,
    )


def _source_scan_bases(root: Path, section: str | None, scope: FreshnessScope) -> list[Path]:
    """Bases to scan for indexable sources. Explicit section: that one
    folder, whatever its policy status (a diagnostic look is fine -
    freshness never writes). Whole vault (no section): included_sections
    only - an out-of-policy dir must not be silently scanned as if it were
    a normal section (it would get real fresh/unindexed statuses instead
    of being surfaced distinctly via out_of_policy_dirs)."""
    if scope.index_whole_folder and section in {None, ROOT_SECTION}:
        return [root]
    if section:
        return [root / section]
    return [root / name for name in sorted(scope.included_sections)]


def _excluded_scan_bases(root: Path, section: str | None, scope: FreshnessScope) -> list[Path]:
    """Bases to scan for excluded content, to surface it rather than hide
    it. Explicit section: that one folder. Whole vault: included_sections
    (catches nested exclusions like _memory/_archive/) plus every
    top-level excluded_dirs entry (catches standalone excluded dirs like
    _archive/) - but never an out-of-policy dir, which is a distinct
    status, not folded into "excluded"."""
    if scope.index_whole_folder and section in {None, ROOT_SECTION}:
        return [root]
    if section:
        return [root / section]
    return [root / name for name in sorted(scope.included_sections | scope.excluded_dirs)]


def _discover_sources(root: Path, section: str | None, scope: FreshnessScope) -> list[Path]:
    paths: list[Path] = []
    for base in _source_scan_bases(root, section, scope):
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".md", ".pdf"}:
                continue
            rel = path.relative_to(root)
            if is_excluded_path(
                rel,
                excluded_dirs=scope.excluded_dirs,
                exclude_files=scope.exclude_files,
            ):
                continue
            paths.append(path)
    return sorted(paths)


def _discover_excluded(root: Path, section: str | None, scope: FreshnessScope) -> list[Path]:
    paths: list[Path] = []
    for base in _excluded_scan_bases(root, section, scope):
        if not base.is_dir():
            continue
        paths.extend(
            path
            for path in base.rglob("*")
            if path.is_file()
            and path.suffix.lower() in {".md", ".pdf"}
            and is_excluded_path(
                path.relative_to(root),
                excluded_dirs=scope.excluded_dirs,
                exclude_files=scope.exclude_files,
            )
        )
    return sorted(set(paths))


def _indexed_metadata(
    collection: Any, section: str | None
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    indexed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    invalid: dict[str, str] = {}
    for result in iter_collection_pages(
        collection,
        where={"section": section} if section else None,
        include=["metadatas"],
    ):
        metadatas = result.get("metadatas") or []
        for metadata in metadatas:
            if not metadata:
                continue
            raw_path = metadata.get("path")
            normalized = _normalize_index_path(raw_path)
            if normalized is None:
                invalid[str(raw_path)] = "untrusted indexed path"
                continue
            indexed[normalized].append(dict(metadata))
    return indexed, invalid


def _normalize_index_path(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = Path(value.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    return candidate.as_posix()


def classify_hash(live_content_hash: str, metadata: list[dict[str, Any]]) -> str:
    """Compare a freshly computed content hash against stored chunk metadata.

    Coherent means every metadata row agrees on one valid contract hash under
    the current contract id/version. Returns "fresh", "stale", or "unknown"
    (incoherent or legacy metadata - fail-safe, never silently "fresh").
    """
    hashes = {item.get("content_hash") for item in metadata}
    contracts = {item.get("contract_id") for item in metadata}
    versions = {item.get("content_hash_contract_version") for item in metadata}
    valid_hashes = {
        value
        for value in hashes
        if isinstance(value, str) and len(value) == _HASH_LENGTH
    }
    coherent = (
        len(hashes) == 1
        and len(valid_hashes) == 1
        and contracts == {FRESHNESS_CONTRACT_ID}
        and versions == {FRESHNESS_CONTRACT_VERSION}
    )
    if not coherent:
        return "unknown"
    stored_hash = next(iter(valid_hashes))
    return "fresh" if stored_hash == live_content_hash else "stale"


def _classify_present(
    snapshot: FileSnapshot, metadata: list[dict[str, Any]], source: Path
) -> dict[str, str]:
    if not metadata:
        result = (
            chunk_pdf_file(source)
            if source.suffix.lower() == ".pdf"
            else chunk_markdown_file(source)
        )
        if result.status == "ok":
            return {"path": snapshot.path, "status": "unindexed"}
        if result.status in {"empty", "too_large"}:
            return {"path": snapshot.path, "status": "no_chunks"}
        return {
            "path": snapshot.path,
            "status": "error",
            "reason": result.error or result.status,
        }
    status = classify_hash(snapshot.content_hash, metadata)
    return {"path": snapshot.path, "status": status, "chunks": str(len(metadata))}


def annotate_search_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach a per-hit freshness verdict to cortex_search results, in place.

    Bounded to the unique source paths present in "hits" (one rehash per
    distinct file, not per hit). Never raises - a per-source failure
    degrades that hit's verdict to "missing"/"error" and the rest continue.
    Order and every existing key are preserved; only "freshness" is added.
    """
    try:
        root = Path(require_kb_path(KB_PATH))
    except CortexConfigError:
        for hit in hits:
            hit["freshness"] = "unavailable"
        return hits
    verdict_cache: dict[str, str] = {}
    for hit in hits:
        metadata = hit.get("metadata") or {}
        normalized = _normalize_index_path(metadata.get("path"))
        if normalized is None:
            hit["freshness"] = "error"
            continue
        if normalized not in verdict_cache:
            verdict_cache[normalized] = _annotate_source(root, normalized, metadata)
        hit["freshness"] = verdict_cache[normalized]
    return hits


def _annotate_source(root: Path, rel_path: str, metadata: dict[str, Any]) -> str:
    try:
        snapshot = read_markdown_snapshot(root / rel_path, root)
    except FileNotFoundError:
        return "missing"
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        _LOG.warning("search_annotation_error path=%s reason=%s", rel_path, exc)
        return "error"
    return classify_hash(snapshot.content_hash, [metadata])


def _report(
    entries: list[dict[str, str]],
    started: float,
    scope: FreshnessScope,
    scope_error: str | None = None,
    out_of_policy_dirs: list[str] | None = None,
    include_entries: bool = True,
    emit_log: bool = True,
) -> dict[str, Any]:
    entries.sort(key=lambda item: item["path"])
    summary: dict[str, int] = defaultdict(int)
    for entry in entries:
        summary[entry["status"]] += 1
    report: dict[str, Any] = {
        "contract_id": FRESHNESS_CONTRACT_ID,
        "read_only": True,
        "freshness_is_not_completeness": True,
        "scope": {
            "index_whole_folder": scope.index_whole_folder,
            "included_sections": sorted(scope.included_sections),
            "excluded_dirs": sorted(scope.excluded_dirs),
            "out_of_policy_dirs": sorted(out_of_policy_dirs or []),
            "pdf": "supported_by_contract_v1",
        },
        "summary": dict(sorted(summary.items())),
        "duration_ms": round((perf_counter() - started) * 1000, 3),
    }
    if include_entries:
        report["entries"] = entries
    if scope_error:
        report["error"] = scope_error
    if emit_log:
        _LOG.info(
            "freshness_report section_entries=%d summary=%s",
            len(entries),
            report["summary"],
        )
    return report
