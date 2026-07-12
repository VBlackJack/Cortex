# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Persistent SQLite FTS5 index derived exclusively from Chroma."""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from chroma_client import iter_collection_pages
from config import (
    CHROMA_PATH,
    COLLECTION_NAME,
    LEXICAL_INDEX_CONTRACT_VERSION,
)

LEXICAL_SCHEMA_VERSION = "1"
DEFAULT_LEXICAL_PATH = Path(CHROMA_PATH).parent / "lexical.db"
_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)


def sanitize_fts5_query(query: str) -> str | None:
    """Neutralize FTS5 syntax by retaining word tokens and quoting each one."""
    tokens = _TOKEN_PATTERN.findall(query)
    if not tokens:
        return None
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


def _read_only_connection(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


class LexicalIndex:
    """Transactional FTS5 storage keyed by complete Chroma chunk IDs."""

    def __init__(self, path: str | Path = DEFAULT_LEXICAL_PATH) -> None:
        self.path = Path(path)

    def _connect_write(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE VIRTUAL TABLE chunks USING fts5("
            "id UNINDEXED, path UNINDEXED, section UNINDEXED, text, "
            "tokenize='unicode61 remove_diacritics 2')"
        )
        connection.execute(
            "CREATE TABLE meta (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL)"
        )

    @staticmethod
    def _write_meta(connection: sqlite3.Connection) -> None:
        values = {
            "schema_version": LEXICAL_SCHEMA_VERSION,
            "contract_version": LEXICAL_INDEX_CONTRACT_VERSION,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "source_collection": COLLECTION_NAME,
        }
        connection.executemany(
            "INSERT INTO meta(key, value) VALUES (?, ?)",
            values.items(),
        )

    def metadata(self) -> dict[str, str] | None:
        if not self.path.is_file():
            return None
        try:
            with closing(_read_only_connection(self.path)) as connection:
                return dict(connection.execute("SELECT key, value FROM meta"))
        except sqlite3.Error:
            return None

    def is_compatible(self) -> bool:
        metadata = self.metadata()
        return bool(
            metadata
            and metadata.get("schema_version") == LEXICAL_SCHEMA_VERSION
            and metadata.get("contract_version") == LEXICAL_INDEX_CONTRACT_VERSION
            and metadata.get("source_collection") == COLLECTION_NAME
        )

    def count(self) -> int:
        with closing(_read_only_connection(self.path)) as connection:
            return int(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])

    def ids(self) -> set[str]:
        with closing(_read_only_connection(self.path)) as connection:
            return {str(row[0]) for row in connection.execute("SELECT id FROM chunks")}

    def replace_file(self, chunks: list[dict[str, Any]]) -> None:
        if not chunks:
            raise ValueError("cannot replace a lexical file with no chunks")
        paths = {chunk["metadata"].get("path") for chunk in chunks}
        if len(paths) != 1 or not isinstance(next(iter(paths)), str):
            raise ValueError("lexical chunks must describe exactly one path")
        path = next(iter(paths))
        rows = [
            (
                chunk["id"],
                path,
                chunk["metadata"].get("section", ""),
                chunk["text"],
            )
            for chunk in chunks
        ]
        with closing(self._connect_write()) as connection, connection:
            connection.execute("DELETE FROM chunks WHERE path = ?", (path,))
            connection.executemany(
                "INSERT INTO chunks(id, path, section, text) VALUES (?, ?, ?, ?)",
                rows,
            )

    def delete_path(self, path: str) -> None:
        with closing(self._connect_write()) as connection, connection:
            connection.execute("DELETE FROM chunks WHERE path = ?", (path,))

    def search(
        self, query: str, *, section: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        sanitized = sanitize_fts5_query(query)
        if sanitized is None or limit <= 0:
            return []
        sql = (
            "SELECT id, path, section, text, bm25(chunks) FROM chunks "
            "WHERE chunks MATCH ?"
        )
        params: list[Any] = [sanitized]
        if section is not None:
            sql += " AND section = ?"
            params.append(section)
        sql += " ORDER BY bm25(chunks), id LIMIT ?"
        params.append(limit)
        with closing(_read_only_connection(self.path)) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [
            {
                "id": str(chunk_id),
                "path": str(path),
                "section": str(row_section),
                "text": str(text),
                "bm25": float(score),
            }
            for chunk_id, path, row_section, text, score in rows
        ]

    def rebuild(self, collection: Any) -> None:
        with closing(self._connect_write()) as connection, connection:
            connection.execute("DROP TABLE IF EXISTS chunks")
            connection.execute("DROP TABLE IF EXISTS meta")
            self._create_schema(connection)
            self._write_meta(connection)
            for page in iter_collection_pages(
                collection,
                include=["documents", "metadatas"],
            ):
                ids = page.get("ids") or []
                documents = page.get("documents") or []
                metadatas = page.get("metadatas") or []
                rows = []
                for chunk_id, document, metadata in zip(
                    ids, documents, metadatas, strict=True
                ):
                    if not isinstance(document, str) or not isinstance(metadata, dict):
                        raise ValueError("Chroma returned an invalid lexical source row")
                    rows.append(
                        (
                            chunk_id,
                            metadata.get("path", ""),
                            metadata.get("section", ""),
                            document,
                        )
                    )
                connection.executemany(
                    "INSERT INTO chunks(id, path, section, text) VALUES (?, ?, ?, ?)",
                    rows,
                )


def chroma_ids(collection: Any) -> set[str]:
    ids: set[str] = set()
    for page in iter_collection_pages(collection, include=["metadatas"]):
        ids.update(str(chunk_id) for chunk_id in page.get("ids") or [])
    return ids


def prepare_lexical_index(
    collection: Any,
    path: str | Path = DEFAULT_LEXICAL_PATH,
) -> LexicalIndex:
    """Return a synchronized index, rebuilding from Chroma when necessary."""
    index = LexicalIndex(path)
    source_ids = chroma_ids(collection)
    ready = index.is_compatible()
    if ready:
        try:
            ready = bool(index.count()) and index.ids() == source_ids
        except (OSError, sqlite3.Error):
            ready = False
    if not ready:
        index.rebuild(collection)
    return index
