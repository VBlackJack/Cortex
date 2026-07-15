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
"""MCP response-shaping and error-boundary tests."""

from __future__ import annotations

from typing import Any

import pytest

import freshness
import server
from config import ROOT_SECTION, CortexConfigError
from indexer import CortexSearchError, SearchResults


def test_cortex_freshness_defaults_to_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def report(_collection: object, **kwargs: object) -> dict[str, object]:
        calls.append(dict(kwargs))
        response: dict[str, object] = {"summary": {"fresh": 2}}
        if kwargs["include_entries"]:
            response["entries"] = [{"path": "knowledge/note.md"}]
        return response

    monkeypatch.setattr(server, "get_collection", object)
    monkeypatch.setattr(server, "cortex_freshness_report", report)

    response = server.cortex_freshness()

    assert response == {"summary": {"fresh": 2}}
    assert calls == [{"section": None, "include_entries": False}]


def test_cortex_freshness_details_are_explicit_and_section_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def report(_collection: object, **kwargs: object) -> dict[str, object]:
        return {
            "summary": {"fresh": 1},
            "entries": [{"path": f"{kwargs['section']}/note.md"}],
        }

    monkeypatch.setattr(server, "_resolve_section", lambda section: (section, None))
    monkeypatch.setattr(server, "get_collection", object)
    monkeypatch.setattr(server, "cortex_freshness_report", report)

    response = server.cortex_freshness(
        section="knowledge",
        include_entries=True,
    )

    assert response["entries"] == [{"path": "knowledge/note.md"}]


def test_cortex_search_formats_typed_query_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_search(**_kwargs: object) -> list[dict[str, object]]:
        raise CortexSearchError("Cortex search failed: database unavailable")

    monkeypatch.setattr(server, "search", fail_search)

    response = server.cortex_search("query")

    assert response == (
        "## Cortex search error\n\n"
        "Cortex search failed: database unavailable"
    )


def test_sync_and_freshness_format_missing_kb_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = CortexConfigError(
        "Missing required 'kb_path'. Run `python setup_config.py --init`."
    )

    def fail_sync(**_kwargs: object) -> dict[str, int]:
        raise error

    def fail_report(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise error

    monkeypatch.setattr(server, "sync", fail_sync)
    sync_response = server.cortex_sync()
    monkeypatch.setattr(server, "get_collection", object)
    monkeypatch.setattr(server, "cortex_freshness_report", fail_report)
    freshness_response = server.cortex_freshness()

    assert sync_response.startswith("## Cortex sync configuration error")
    assert "setup_config.py --init" in sync_response
    assert freshness_response == {"error": str(error)}


@pytest.mark.asyncio
async def test_server_lifespan_does_not_require_kb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Collection:
        def query(self, **_kwargs: object) -> dict[str, object]:
            return {}

    collection = Collection()
    monkeypatch.setattr(server, "get_collection", lambda: collection)
    warmups = {"reranker": 0}

    def warmup() -> None:
        warmups["reranker"] += 1
        return None

    monkeypatch.setattr(server, "warmup_reranker", warmup)

    async with server.app_lifespan(None) as state:
        assert state == {"collection": collection}
    assert warmups == {"reranker": 1}


def test_cortex_search_uses_existing_index_without_kb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(freshness, "KB_PATH", None)
    monkeypatch.setattr(
        server,
        "search",
        lambda **_kwargs: [
            {
                "text": "indexed content",
                "metadata": {"path": "knowledge/note.md", "title": "Note"},
                "distance": 0.1,
            }
        ],
    )

    response = server.cortex_search("query")

    assert "indexed content" in response
    assert "**Freshness:** unavailable" in response


def test_cortex_search_reports_hybrid_mode_and_lexical_only_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(freshness, "KB_PATH", None)
    monkeypatch.setattr(
        server,
        "search",
        lambda **_kwargs: SearchResults(
            [
                {
                    "id": "lexical",
                    "text": "exact lexical content",
                    "metadata": {"path": "knowledge/exact.md", "section": "knowledge"},
                    "lexical_only": True,
                }
            ],
            mode="hybrid",
        ),
    )

    response = server.cortex_search("exact")

    assert "**Mode:** hybrid" in response
    assert "**Relevance:** lexical-only" in response


def test_cortex_search_reports_vector_fallback_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(freshness, "KB_PATH", None)
    monkeypatch.setattr(
        server,
        "search",
        lambda **_kwargs: SearchResults(
            [
                {
                    "id": "vector",
                    "text": "vector content",
                    "metadata": {"path": "knowledge/vector.md"},
                    "distance": 0.2,
                }
            ],
            mode="vector-only",
            fallback_reason="lexical index absent; run cortex sync",
        ),
    )

    response = server.cortex_search("query")

    assert "**Mode:** vector-only" in response
    assert "**Fallback reason:** lexical index absent; run cortex sync" in response


def test_whole_folder_section_is_presented_without_internal_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "discover_sections", lambda: [ROOT_SECTION])
    monkeypatch.setattr(server, "discover_out_of_policy_sections", lambda: [])

    response = server.cortex_list_sections()

    assert "All documents (the whole knowledge base folder)" in response
    assert "`.`" not in response


def test_run_stdio_configures_logging_and_runs_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.delenv("CORTEX_DOCTOR_READ_ONLY", raising=False)
    monkeypatch.setattr("cortex_logging.configure_logging", lambda: calls.append("logging"))
    monkeypatch.setattr(server.mcp, "run", lambda: calls.append("server"))

    server.run_stdio()

    assert calls == ["logging", "server"]


def test_run_stdio_skips_logging_in_doctor_read_only_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setenv("CORTEX_DOCTOR_READ_ONLY", "1")
    monkeypatch.setattr("cortex_logging.configure_logging", lambda: calls.append("logging"))
    monkeypatch.setattr(server.mcp, "run", lambda: calls.append("server"))

    server.run_stdio()

    assert calls == ["server"]
