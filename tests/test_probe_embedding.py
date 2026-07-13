# Copyright 2026 Julien Bombled
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
"""Unit guards for the isolated lot 6d embedding probe."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from eval import probe_embedding


class FakeEmbedding:
    def embed(self, texts: Iterable[str]) -> Iterable[list[float]]:
        for text in texts:
            if text.startswith("query: "):
                yield [1.0, 0.0]
            elif text.startswith("passage: "):
                yield [0.0, 1.0]
            else:
                yield [1.0, 1.0]

    def query_embed(self, text: str) -> Iterable[list[float]]:
        return self.embed([text])

    def passage_embed(self, texts: Iterable[str]) -> Iterable[list[float]]:
        return self.embed(texts)


class RoleAwareEmbedding(FakeEmbedding):
    def query_embed(self, text: str) -> Iterable[list[float]]:
        return self.embed([f"query: {text}"])

    def passage_embed(self, texts: Iterable[str]) -> Iterable[list[float]]:
        return self.embed(f"passage: {text}" for text in texts)


def test_prefix_attestation_selects_explicit_policy_for_fastembed_080() -> None:
    result = probe_embedding.inspect_fastembed_prefixes(FakeEmbedding())  # type: ignore[arg-type]

    assert result["fastembed_distinguishes_roles"] is False
    assert result["selected_policy"] == "explicit-query-passage-v1"
    assert result["query_api_vs_passage_api_cosine"] == pytest.approx(1.0)
    assert result["explicit_query_vs_passage_cosine"] == pytest.approx(0.0)


def test_prefix_attestation_refuses_changed_fastembed_semantics() -> None:
    with pytest.raises(RuntimeError, match="now distinguishes E5"):
        probe_embedding.inspect_fastembed_prefixes(RoleAwareEmbedding())  # type: ignore[arg-type]


def test_fingerprint_attests_prefixes_dimensions_and_runtime() -> None:
    fingerprint = probe_embedding.embedding_fingerprint()

    assert fingerprint["embedding_model"] == "intfloat/multilingual-e5-large"
    assert fingerprint["dimensions"] == 1024
    assert fingerprint["normalization"] == "l2"
    assert fingerprint["prefix_policy"] == "explicit-query-passage-v1"
    assert fingerprint["fastembed_version"] == "0.8.0"
    assert fingerprint["onnxruntime_version"]


def test_granite_fingerprint_uses_card_attested_cls_without_prefixes() -> None:
    granite = probe_embedding.GraniteEmbedding.__new__(probe_embedding.GraniteEmbedding)

    fingerprint = granite.fingerprint()

    assert fingerprint["embedding_model"] == (
        "ibm-granite/granite-embedding-97m-multilingual-r2"
    )
    assert fingerprint["artifact_revision"] == (
        "c61e626a6255c490879d0af885078b61929d51f6"
    )
    assert fingerprint["dimensions"] == 384
    assert fingerprint["pooling"] == "cls"
    assert fingerprint["normalization"] == "l2"
    assert fingerprint["prefix_policy"] == "none-model-card-r2"


def test_rank_metrics_use_expected_path_and_frozen_cutoff() -> None:
    hits = [
        {"metadata": {"path": "wrong.md"}},
        {"metadata": {"path": "expected.md"}},
    ]

    assert probe_embedding._rank(hits, {"expected.md"}) == 2
    assert probe_embedding._summarize({"Q1": 2, "Q2": None}) == {
        "mrr_at_5": 0.25,
        "hit_at_1": 0.0,
        "hits_at_5": 1,
        "query_count": 2,
        "ranks": {"Q1": 2, "Q2": None},
    }
