# Architecture

[Francais](../fr/architecture.md) | **English**

[Back to table of contents](index.md)

## End-to-end behavior

```
kb_path (.md, .pdf)                  allowlisted Confluence REST
      |                                        |
      |                              confluence_writer/
      |                                        |
      |                           ingestion/doc/current.json
      |                                        |
      +------------------+---------------------+
                         |
                         v
  indexer.py             <- Split, hash, vectorize, reconcile
      |
      +--> chroma_db/    <- Vector index
      +--> lexical.db    <- SQLite FTS5 index
      |
      v
  server.py              <- MCP server (FastMCP)
      |
      v
  MCP clients            <- Claude / Codex / Gemini
```

Cortex indexes two isolated source domains. User-selected Markdown and PDF
files live under `kb_path` with `source_kind=note`. Optional source writers
publish immutable Markdown generations under the ingestion data root with
`source_kind=doc`; only the generation selected by `current.json` is eligible.
`indexer.py` writes both ChromaDB and SQLite FTS5, then `server.py` exposes
structured hybrid search and read-only freshness to MCP clients.

## Project structure

```
<install_dir>\          <- Wherever you clone Cortex
|-- config.py           <- Product contracts and resolved configuration
|-- user_config.py      <- Strict TOML loading and atomic initialization
|-- chunker.py          <- Splits .md into chunks (headers + fixed size)
|-- chunker_pdf.py      <- Splits .pdf into chunks (pdfplumber + fixed size)
|-- chunker_utils.py    <- Shared helpers (hash, split, paths)
|-- indexer.py          <- Incremental sync to ChromaDB
|-- lexical_index.py    <- Derived SQLite FTS5 index
|-- freshness.py        <- Vault and current-generation freshness
|-- ingestion\          <- Atomic generations, scheduling, health, credentials
|-- confluence_writer\  <- Allowlisted REST source and console bridge
|-- server.py           <- FastMCP MCP server (4 Cortex tools)
|-- sync.bat            <- Runs the sync section by section (portable, %~dp0)
|-- install.bat         <- One-click install / reinstall (portable)
|-- setup_config.py     <- Safe multi-client registration + validation
|-- cli.py              <- Dispatcher for the cortex subcommands
|-- pyproject.toml      <- Packaging and quality tool configuration
|-- requirements.txt    <- Single source of pinned runtime dependencies
|-- requirements.lock   <- Hash-locked transitive tree (see reproducible install)
|-- conftest.py         <- pytest bootstrap (sys.path)
|-- tests\              <- Unit tests (chunker) + integration (search)
\-- chroma_db\          <- Old location, migrated to the user data home
```

## Technical choices

### Why ONNX / fastembed?

PyTorch and sentence-transformers detected the GPU during initialization and
caused a BSOD (dxgkrnl.sys). The ONNX model via `fastembed` runs entirely on
CPU, uses ~150 MB of RAM, and does not touch the GPU.

### Why an embedding fingerprint?

The index and the queries must use exactly the same vector space. Cortex
therefore stores in the Chroma metadata the model, the `fastembed` version and
the pooling (`mean`, an explicit contract since the qdrant/fastembed#436 fix
active in v0.6.0 for this model). At startup, before a search and before any
write, Cortex refuses access if a value differs and states the rebuild
procedure. The historical index attested on 2026-07-12 is migrated once to the
`fastembed=0.8.0 / pooling=mean` fingerprint.

### Why sync section by section?

Each section is an independent Python process in `sync.bat`. This caps RAM at
~300 MB per process (instead of a single peak if everything were in memory) and
makes it easy to resume after an error.

### Why is the incremental index scoped by section?

Without scoping, a sync of the `operations` section could see the `knowledge`
files as "deleted" and erase them. Comparison and deletions are now limited to
the current section.

The ingestion document domain is reconciled independently from vault rows.
Only the current `doc` generation is considered; a missing, pending, or
incomplete generation preserves already indexed document rows instead of
purging them.

### Why 512 characters per chunk?

The `paraphrase-multilingual-MiniLM-L12-v2` model truncates any input to 128
tokens maximum. Anything beyond that is never seen by the embedding. In French,
1 token is about 3.5 characters, so 512 characters equal about 145 tokens,
slightly above the theoretical ceiling, but the chunker cuts on natural
boundaries (line break, sentence end) which in practice produces shorter chunks.
Longer chunks (~2000 chars used early in the project) lost 70 to 80 % of the
indexed content to the embedding.

### Why are metadata paths relative?

The `path` stored in a vault chunk is relative to `CORTEX_KB_PATH` (for example
`operations/architecture.md`). The path of an ingestion chunk is relative to
the `documents` directory of the current generation. This makes each domain
portable and gives reconciliation a stable identity without mixing vault and
generated documents.

### Why is everything portable?

Installation paths are portable. `kb_path` comes from the user configuration or
`CORTEX_KB_PATH`; no machine-specific value is hardcoded in the sources:

- `config.py` resolves `CHROMA_PATH` to `%LOCALAPPDATA%\Cortex\chroma_db` or the
  user override.
- `install.bat` and `sync.bat` use `%~dp0`: they find their own run folder.
- `setup_config.py` detects its own location to register the server in each
  client.
- `%APPDATA%\Cortex\config.toml` separates roaming choices from the shipped
  code; `%LOCALAPPDATA%\Cortex` holds the machine-specific data.

Result: you can clone Cortex into any folder on any machine, run `install.bat`,
and it is operational.
