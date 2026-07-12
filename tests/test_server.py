# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""MCP response-shaping and error-boundary tests."""

from __future__ import annotations

from typing import Any

import pytest

import server
from indexer import CortexSearchError


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
