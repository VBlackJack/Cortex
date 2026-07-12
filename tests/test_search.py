# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""
Integration tests for semantic search.
Skipped automatically if the local ChromaDB has not been built yet.
"""
import os

import pytest

from config import CHROMA_PATH


def _chroma_db_exists() -> bool:
    return os.path.isdir(CHROMA_PATH) and any(os.scandir(CHROMA_PATH))


pytestmark = pytest.mark.skipif(
    not _chroma_db_exists(),
    reason="ChromaDB not built — run `python indexer.py` first",
)


def test_search_returns_expected_shape():
    from indexer import search

    results = search("zabbix", top_k=2)
    assert isinstance(results, list)
    if not results:
        pytest.skip("Empty index — nothing to assert against")
    hit = results[0]
    assert "text" in hit
    assert "metadata" in hit
    assert "distance" in hit
    assert isinstance(hit["distance"], float)


def test_search_section_filter():
    from indexer import search

    results = search("alert", section="Zabbix", top_k=3)
    assert isinstance(results, list)
    for hit in results:
        # Either no results, or every hit must come from the requested section.
        meta = hit.get("metadata") or {}
        if "section" in meta:
            assert meta["section"] == "Zabbix"
