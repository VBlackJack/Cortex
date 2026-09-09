# Copyright 2026 Julien Bombled
# Licensed under the Apache License, Version 2.0.
"""Run the real retrieval stack in a disposable index, with explicit model-cache reuse."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from contextlib import redirect_stdout
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.retrieval_metrics import (  # noqa: E402
    acceptance_failures,
    metrics,
    percentile,
    regressions,
)

DEFAULT_CORPUS = Path(__file__).with_name("retrieval_corpus.json")
MODES: tuple[Literal["default", "vector", "hybrid", "rerank"], ...] = (
    "default", "vector", "hybrid", "rerank",
)
TOP_K = 5


def configure_environment(root: Path) -> None:
    """Override every Cortex writable root before importing runtime modules."""
    for name in list(os.environ):
        if name.startswith("CORTEX_"):
            del os.environ[name]
    os.environ.update(
        APPDATA=str(root / "roaming"),
        LOCALAPPDATA=str(root / "local"),
        CORTEX_KB_PATH=str(root / "kb"),
        CORTEX_INDEX_MODE="whole",
    )


def configure_isolation(root: Path, corpus: dict[str, Any]) -> None:
    """Create only disposable documents before importing runtime modules."""
    configure_environment(root)
    (root / "kb").mkdir()
    for document in corpus["documents"]:
        path = root / "kb" / document["path"]
        if not path.resolve().is_relative_to((root / "kb").resolve()):
            raise ValueError("Corpus document escaped the disposable root")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(document["text"], encoding="utf-8")


def cold_search(root: Path, model_cache: Path, query: str) -> dict[str, Any]:
    """Measure the desktop JSON search in a fresh interpreter over the disposable index."""
    started = time.perf_counter()
    configure_environment(root)
    import indexer
    import reranker
    from offline_models import verify_manifest
    from search_command import emit_search

    verify_manifest(model_cache)
    indexer._MODEL_RUNTIME = replace(indexer._MODEL_RUNTIME, cache_dir=model_cache, embedded=True)
    reranker._MODEL_RUNTIME = replace(
        reranker._MODEL_RUNTIME, cache_dir=model_cache, embedded=True
    )
    output = io.StringIO()
    with redirect_stdout(output):
        exit_code = emit_search(query, None, TOP_K, None)
    if exit_code != 0:
        raise RuntimeError("Fresh-process desktop search failed")
    elapsed = time.perf_counter() - started
    payload = json.loads(output.getvalue())
    return {
        "first_search_fresh_process_seconds": elapsed,
        "first_search_result_count": len(payload["results"]),
        "first_search_mode": payload["mode"],
        "scope": "fresh interpreter and models; existing index and OS filesystem caches",
    }


def run(root: Path, corpus: dict[str, Any], model_cache: Path) -> dict[str, Any]:
    """Measure actual indexing and all retrieval strategies without accessing the user's index."""
    configure_isolation(root, corpus)
    started = time.perf_counter()
    import indexer
    import reranker
    from config import EMBEDDING_MODEL, RERANKER_MODEL
    from eval.probe_reranker import rss_mb
    from offline_models import verify_manifest

    verify_manifest(model_cache)

    indexer._MODEL_RUNTIME = replace(indexer._MODEL_RUNTIME, cache_dir=model_cache, embedded=True)
    reranker._MODEL_RUNTIME = replace(
        reranker._MODEL_RUNTIME, cache_dir=model_cache, embedded=True
    )
    import_seconds = time.perf_counter() - started
    started = time.perf_counter()
    initial = indexer.sync_report(verbose=False)
    build_seconds = time.perf_counter() - started
    if initial.status != "succeeded":
        raise RuntimeError(f"Isolated indexing failed: {initial.status}")
    started = time.perf_counter()
    failure = reranker.warmup_reranker()
    reranker_load_seconds = time.perf_counter() - started
    if failure:
        raise RuntimeError(f"Cannot compare reranking: {failure}")
    trials: list[dict[str, Any]] = []
    for mode in MODES:
        for question in corpus["questions"]:
            started = time.perf_counter()
            hits = (
                indexer.search(question["query"], top_k=TOP_K)
                if mode == "default"
                else indexer.search(question["query"], top_k=TOP_K, retrieval_mode=mode)
            )
            elapsed = time.perf_counter() - started
            paths = [str(hit["metadata"]["path"]) for hit in hits]
            trials.append(
                {
                    "id": question["id"],
                    "language": question["language"],
                    "requested_mode": mode,
                    "actual_mode": hits.mode,
                    "degraded": hits.fallback_reason is not None,
                    "seconds": elapsed,
                    "paths": paths,
                    **metrics(paths, question["expected"], TOP_K),
                }
            )
    started = time.perf_counter()
    incremental = indexer.sync_report(verbose=False)
    incremental_seconds = time.perf_counter() - started
    if incremental.status != "succeeded":
        raise RuntimeError("Incremental verification failed")
    summaries = {}
    for mode in MODES:
        rows = [row for row in trials if row["requested_mode"] == mode]
        summaries[mode] = {
            name: sum(row[name] for row in rows) / len(rows) for name in ("recall", "mrr", "ndcg")
        }
        summaries[mode]["p95_seconds"] = percentile([row["seconds"] for row in rows], 0.95)
    return {
        "schema_version": 1,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "embedding_model": EMBEDDING_MODEL,
        "reranker_model": RERANKER_MODEL,
        "packages": {name: version(name) for name in ("chromadb", "fastembed", "onnxruntime")},
        "top_k": TOP_K,
        "import_seconds": import_seconds,
        "initial_sync_seconds": build_seconds,
        "reranker_load_seconds": reranker_load_seconds,
        "resident_memory_mb": rss_mb(),
        "memory_measurement": "resident working set on Windows; peak RSS on Unix",
        "first_query_seconds": trials[0]["seconds"],
        "incremental_sync_seconds": incremental_seconds,
        "incremental_added_chunks": incremental.counters.added_chunks,
        "index_bytes": sum(p.stat().st_size for p in (root / "local").rglob("*") if p.is_file()),
        "summaries": summaries,
        "trials": trials,
    }


def main() -> int:
    """Run in a child so native index handles close before disposable files are cleaned up."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--model-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--acceptance", type=Path,
                        help="Require default retrieval to meet a corpus-bound bilingual policy")
    parser.add_argument("--max-recall-drop", type=float, default=0.0)
    parser.add_argument("--max-latency-ratio", type=float)
    parser.add_argument("--worker-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--probe-search", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.baseline and args.baseline.resolve() == args.output.resolve():
        parser.error("The output must not overwrite the comparison baseline")
    if args.worker_root is None:
        started = time.perf_counter()
        subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parents[1] / "cli.py"), "--version"],
            check=True,
            capture_output=True,
            timeout=30,
        )
        bootstrap_seconds = time.perf_counter() - started
        with tempfile.TemporaryDirectory(prefix="cortex-retrieval-") as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--corpus",
                    str(args.corpus.resolve()),
                    "--model-cache",
                    str(args.model_cache.resolve()),
                    "--output",
                    str(args.output.resolve()),
                    "--worker-root",
                    directory,
                ],
                check=False,
            )
            if result.returncode == 0:
                report = json.loads(args.output.read_text(encoding="utf-8"))
                report["source_cli_version_process_seconds"] = bootstrap_seconds
                cold_output = Path(directory) / "cold-search.json"
                subprocess.run(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--corpus",
                        str(args.corpus.resolve()),
                        "--model-cache",
                        str(args.model_cache.resolve()),
                        "--output",
                        str(cold_output),
                        "--worker-root",
                        directory,
                        "--probe-search",
                    ],
                    check=True,
                    timeout=120,
                )
                report.update(json.loads(cold_output.read_text(encoding="utf-8")))
                if args.baseline:
                    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
                    report["regressions"] = regressions(
                        report, baseline, args.max_recall_drop, args.max_latency_ratio
                    )
                if args.acceptance:
                    policy = json.loads(args.acceptance.read_text(encoding="utf-8"))
                    report["acceptance_failures"] = acceptance_failures(report, policy)
                args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
                if report.get("regressions") or report.get("acceptance_failures"):
                    return 1
            return result.returncode
    corpus_bytes = args.corpus.read_bytes()
    corpus = json.loads(corpus_bytes)
    report = (
        cold_search(args.worker_root, args.model_cache, corpus["questions"][0]["query"])
        if args.probe_search
        else run(args.worker_root, corpus, args.model_cache)
    )
    report["corpus_sha256"] = hashlib.sha256(corpus_bytes).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
