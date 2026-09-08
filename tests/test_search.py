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
"""
Integration tests for semantic search against the developer's real index.

Opening that index is not free of side effects: the vector store writes to its
SQLite file on open, so the suite must not touch it unless the developer asks.
Run with the opt-in variable set; the tests also skip when no index exists.
"""
import os

import pytest

from config import CHROMA_PATH

REAL_INDEX_OPT_IN = "CORTEX_TEST_REAL_INDEX"


def _chroma_db_exists() -> bool:
    return os.path.isdir(CHROMA_PATH) and any(os.scandir(CHROMA_PATH))


pytestmark = pytest.mark.skipif(
    os.environ.get(REAL_INDEX_OPT_IN) != "1" or not _chroma_db_exists(),
    reason=f"runs against the real index only with {REAL_INDEX_OPT_IN}=1 and a built index",
)


def test_search_returns_expected_shape():
    from indexer import search

    results = search("zabbix", top_k=2)
    assert isinstance(results, list)
    if not results:
        pytest.skip("Empty index - nothing to assert against")
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
