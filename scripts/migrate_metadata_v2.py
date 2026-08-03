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
"""Back up, migrate, measure and restore Cortex metadata schema v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sqlite3
import sys
import tempfile
import time
from collections.abc import Sequence
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chroma_client import iter_collection_pages
from config import CHROMA_PATH, CORTEX_DATA_HOME
from cortex_logging import configure_logging
from indexer import _sync_locked, get_collection
from lexical_index import DEFAULT_LEXICAL_PATH, LexicalIndex
from write_lock import chroma_write_lock

_LOG = logging.getLogger("cortex.migration.metadata_v2")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _directory_manifest(path: Path) -> dict[str, str]:
    return {
        item.relative_to(path).as_posix(): _sha256(item)
        for item in sorted(path.rglob("*"))
        if item.is_file()
    }


def _sqlite_backup(source: Path, target: Path) -> None:
    with closing(sqlite3.connect(source)) as source_connection, closing(
        sqlite3.connect(target)
    ) as target_connection:
        source_connection.backup(target_connection)


def backup_indexes(
    chroma_path: Path,
    lexical_path: Path,
    backup_root: Path,
) -> Path:
    """Create one immutable backup directory before any migration write."""
    if not chroma_path.is_dir():
        raise FileNotFoundError(f"Chroma index not found: {chroma_path}")
    backup_path = backup_root / f"metadata-v2-{_timestamp()}"
    backup_path.mkdir(parents=True, exist_ok=False)
    shutil.copytree(chroma_path, backup_path / "chroma")
    if lexical_path.is_file():
        _sqlite_backup(lexical_path, backup_path / "lexical.db")
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "chroma_files": _directory_manifest(backup_path / "chroma"),
        "lexical_sha256": (
            _sha256(backup_path / "lexical.db")
            if (backup_path / "lexical.db").is_file()
            else None
        ),
    }
    (backup_path / "backup-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return backup_path


def restore_indexes(backup_path: Path, chroma_path: Path, lexical_path: Path) -> None:
    """Restore into absent targets; callers own replacement of live targets."""
    source_chroma = backup_path / "chroma"
    if not source_chroma.is_dir():
        raise FileNotFoundError(f"Backup Chroma index not found: {source_chroma}")
    if chroma_path.exists() or lexical_path.exists():
        raise FileExistsError("restore targets must be absent")
    chroma_path.parent.mkdir(parents=True, exist_ok=True)
    lexical_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_chroma, chroma_path)
    source_lexical = backup_path / "lexical.db"
    if source_lexical.is_file():
        shutil.copy2(source_lexical, lexical_path)


def verify_restore_sample(backup_path: Path) -> dict[str, Any]:
    """Restore the backup to disposable paths and compare exact saved bytes."""
    with tempfile.TemporaryDirectory(prefix="cortex-metadata-v2-restore-") as raw_temp:
        temp_root = Path(raw_temp)
        restored_chroma = temp_root / "chroma"
        restored_lexical = temp_root / "lexical.db"
        restore_indexes(backup_path, restored_chroma, restored_lexical)
        chroma_matches = _directory_manifest(restored_chroma) == _directory_manifest(
            backup_path / "chroma"
        )
        source_lexical = backup_path / "lexical.db"
        lexical_matches = (
            not source_lexical.exists()
            or (
                restored_lexical.is_file()
                and _sha256(restored_lexical) == _sha256(source_lexical)
            )
        )
        if not chroma_matches or not lexical_matches:
            raise RuntimeError("backup restore verification failed")
        return {
            "chroma_files": len(_directory_manifest(restored_chroma)),
            "chroma_bytes_match": chroma_matches,
            "lexical_bytes_match": lexical_matches,
        }


def _collection_snapshot(collection: Any) -> dict[str, int]:
    paths: set[str] = set()
    metadata_v2_chunks = 0
    for page in iter_collection_pages(collection, include=["metadatas"]):
        for metadata in page.get("metadatas") or []:
            if isinstance(metadata, dict) and isinstance(metadata.get("path"), str):
                paths.add(metadata["path"])
            if isinstance(metadata, dict) and metadata.get("schema_version") == 2:
                metadata_v2_chunks += 1
    chunks = int(collection.count())
    return {
        "chunks": chunks,
        "files": len(paths),
        "metadata_v2_chunks": metadata_v2_chunks,
        "non_v2_chunks": chunks - metadata_v2_chunks,
    }


def _query_samples(collection: Any, queries: Sequence[str]) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for query in queries:
        result = collection.query(
            query_texts=[query],
            n_results=3,
            include=["documents", "metadatas", "distances"],
        )
        samples.append(
            {
                "query": query,
                "hits": [
                    {
                        "id": chunk_id,
                        "path": metadata.get("path") if isinstance(metadata, dict) else None,
                        "title": (
                            metadata.get("title") if isinstance(metadata, dict) else None
                        ),
                        "distance": distance,
                    }
                    for chunk_id, metadata, distance in zip(
                        (result.get("ids") or [[]])[0],
                        (result.get("metadatas") or [[]])[0],
                        (result.get("distances") or [[]])[0],
                        strict=True,
                    )
                ],
            }
        )
    return samples


def migrate(queries: Sequence[str], backup_root: Path) -> dict[str, Any]:
    """Execute one measured migration pass while holding the Cortex write lock."""
    chroma_path = Path(CHROMA_PATH)
    lexical_path = Path(DEFAULT_LEXICAL_PATH)
    started = time.perf_counter()
    with chroma_write_lock():
        backup_path = backup_indexes(chroma_path, lexical_path, backup_root)
        restore_sample = verify_restore_sample(backup_path)
        collection = get_collection()
        before = _collection_snapshot(collection)
        queries_before = _query_samples(collection, queries)
        stats = _sync_locked(verbose=False)
        after = _collection_snapshot(collection)
        queries_after = _query_samples(collection, queries)
        lexical = LexicalIndex(lexical_path)
        lexical_count = lexical.count() if lexical.path.is_file() else 0
    report = {
        "schema_version": 1,
        "metadata_schema_version": 2,
        "backup_path": str(backup_path),
        "duration_seconds": round(time.perf_counter() - started, 3),
        "before": before,
        "after": after,
        "delta": {
            "chunks": after["chunks"] - before["chunks"],
            "files": after["files"] - before["files"],
        },
        "lexical_chunks_after": lexical_count,
        "sync": stats,
        "queries_before": queries_before,
        "queries_after": queries_after,
        "restore_sample": restore_sample,
        "success": after["non_v2_chunks"] == 0 and lexical_count == after["chunks"],
    }
    report_path = backup_path / "migration-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not report["success"]:
        raise RuntimeError(
            "migration did not reach complete v2 and lexical count parity; restore is available"
        )
    return report


def _restore_live(backup_path: Path) -> dict[str, str]:
    chroma_path = Path(CHROMA_PATH)
    lexical_path = Path(DEFAULT_LEXICAL_PATH)
    recovery_suffix = f".pre-restore-{_timestamp()}"
    recovery_chroma = chroma_path.with_name(chroma_path.name + recovery_suffix)
    recovery_lexical = lexical_path.with_name(lexical_path.name + recovery_suffix)
    lexical_sidecars = [
        lexical_path.with_name(lexical_path.name + suffix) for suffix in ("-wal", "-shm")
    ]
    recovery_sidecars = [
        sidecar.with_name(sidecar.name + recovery_suffix) for sidecar in lexical_sidecars
    ]
    with chroma_write_lock():
        if (
            recovery_chroma.exists()
            or recovery_lexical.exists()
            or any(path.exists() for path in recovery_sidecars)
        ):
            raise FileExistsError("recovery target already exists")
        if chroma_path.exists():
            chroma_path.replace(recovery_chroma)
        if lexical_path.exists():
            lexical_path.replace(recovery_lexical)
        for sidecar, recovery_sidecar in zip(
            lexical_sidecars, recovery_sidecars, strict=True
        ):
            if sidecar.exists():
                sidecar.replace(recovery_sidecar)
        try:
            restore_indexes(backup_path, chroma_path, lexical_path)
        except Exception:
            if chroma_path.exists():
                shutil.rmtree(chroma_path)
            if lexical_path.exists():
                lexical_path.unlink()
            if recovery_chroma.exists():
                recovery_chroma.replace(chroma_path)
            if recovery_lexical.exists():
                recovery_lexical.replace(lexical_path)
            for sidecar, recovery_sidecar in zip(
                lexical_sidecars, recovery_sidecars, strict=True
            ):
                if recovery_sidecar.exists():
                    recovery_sidecar.replace(sidecar)
            raise
    return {
        "restored_backup": str(backup_path),
        "recovery_chroma": str(recovery_chroma),
        "recovery_lexical": str(recovery_lexical),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run migration, disposable restore verification, or explicit live restore."""
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply one real migration pass")
    parser.add_argument("--query", action="append", default=[], help="Before/after query sample")
    parser.add_argument(
        "--backup-root",
        type=Path,
        default=Path(CORTEX_DATA_HOME) / "migration-backups",
    )
    parser.add_argument("--verify-restore", type=Path, metavar="BACKUP")
    parser.add_argument("--restore", type=Path, metavar="BACKUP")
    parser.add_argument("--yes", action="store_true", help="Confirm live restore replacement")
    args = parser.parse_args(argv)
    selected = sum(bool(value) for value in (args.apply, args.verify_restore, args.restore))
    if selected != 1:
        parser.error("choose exactly one of --apply, --verify-restore, or --restore")
    if args.apply:
        if not args.query:
            parser.error("--apply requires at least one --query sample")
        report = migrate(args.query, args.backup_root)
    elif args.verify_restore:
        report = verify_restore_sample(args.verify_restore)
    else:
        if not args.yes:
            parser.error("--restore requires --yes")
        report = _restore_live(args.restore)
    _LOG.info("metadata_v2_operation_complete")
    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
