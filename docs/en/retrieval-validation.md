# Retrieval and paired-version validation

[Français](../fr/validation-recherche.md) | **English**

[Back to the table of contents](index.md)

These additions are available in unreleased source builds. An older installed
version may not provide the desktop JSON contract.

The desktop search contract is available through:

```text
cortex search "certificate renewal" --json --section operations --source-kind note --top-k 5
```

Successful responses contain `contract_version: 1`, `operation: search`, `status:
succeeded`, the actual retrieval `mode`, a `degraded` flag and bounded `results`.
Each result contains its ID, title, excerpt, source kind, section, path, update
timestamp and optional `open_target`. A failed command returns a nonzero exit code;
it must not be interpreted as an empty successful result set. Queries are limited
to 2,000 characters, excerpts to 1,200 characters and results to ten.

Opening targets are restricted to HTTPS URLs without embedded credentials or
existing Markdown, text and PDF files contained in the configured knowledge base.
Canonical source URLs take precedence. Companion additionally rejects network-share
file targets and executable file types. Indexed document content remains untrusted.

## Relevance and performance

Run from the source checkout with the locked dependencies installed and an existing
verified Cortex model cache. The evaluation refuses missing model payloads instead
of silently comparing a degraded strategy.

```powershell
python eval/retrieval_benchmark.py --model-cache "$env:LOCALAPPDATA/Cortex/models" --output local/retrieval/baseline.json
python eval/retrieval_benchmark.py --model-cache "$env:LOCALAPPDATA/Cortex/models" --output local/retrieval/current.json --baseline local/retrieval/baseline.json
```

The runner uses a child interpreter, a temporary knowledge base and isolated
configuration/data roots. Model files are reused with network access disabled.
Native database handles close before temporary files are removed. No production
index or Confluence endpoint is used.

The supplied corpus contains 15 synthetic operational documents and 30 FR/EN
questions. It is a reproducible starting point, not a user-validated relevance
dataset. Supply `--corpus` to use a reviewed dataset with the same JSON structure.
The report records the corpus SHA-256, model/package identities, platform, recall,
MRR, nDCG and p95 latency for vector, hybrid and reranked retrieval. Duplicate
chunks cannot inflate document-level recall. The production default remains
unchanged; explicit strategy selection is used by the evaluator only.

Performance fields distinguish runtime imports, initial indexing, reranker loading,
first query after indexing, first JSON search in a fresh interpreter, incremental
indexing, index size and process memory. Windows memory is the resident working
set at measurement time; Unix uses peak RSS. The fresh interpreter test retains
filesystem caches and is not a cold-disk measurement or an installer benchmark.

`--baseline` rejects a recall drop by default. `--max-recall-drop` allows an explicit
absolute tolerance; `--max-latency-ratio` optionally gates p95 latency. Corpus and
cutoff must match. Use comparable machines for latency judgments. The output may
not overwrite its own baseline. Regression findings are recorded in the report
and return a nonzero exit status.

Measure a specific packaged executable independently:

```powershell
python eval/startup_benchmark.py --executable "$env:LOCALAPPDATA/Programs/Cortex/cortex.exe" --output local/retrieval/startup.json
```

This runs only `--version`, recording the binary SHA-256, version and five process
launch times. It neither launches the GUI nor flushes operating-system caches.

## Recovery and paired delivery

The ingestion tests exercise process termination before pointer publication,
restart recovery, injected disk-full failure and interrupted enumeration followed
by retry. They verify that the previous generation stays served and that partial
enumeration does not delete unobserved sources. These are isolated fault tests,
not a claim that every storage or remote-service failure has been reproduced.

Both repositories expose a manual `release-pair` workflow. Supply full lowercase
`cortex_sha` and `companion_sha` values. It verifies both checked-out identities,
then runs the shared byte-lock, TOML v1/v2/v3 and desktop JSON contract proofs,
and parses every command line the desktop builds with the Cortex parser that runs
it. The job summary identifies the exact tested pair. Ordinary `interoperability`
continues testing the peer's `main` by default.

This gate certifies source interoperability, not the bytes of an installer or a
signed release. Run it on committed revisions before preparing paired delivery.
