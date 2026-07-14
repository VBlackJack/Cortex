# Architecture

[Francais](../fr/architecture.md) | **English**

[Back to table of contents](index.md)

## End-to-end behavior

```
kb_path (TOML/env)      <- Confluence export (.md files)
      |
      v
  indexer.py            <- Split, hash, vectorize
      |
      v
  %LOCALAPPDATA%\Cortex\chroma_db\  <- Local vector store (ChromaDB)
      |
      v
  server.py             <- MCP server (FastMCP)
      |
      v
  MCP clients           <- Claude / Codex / Gemini
```

The knowledge base is a set of Markdown (and PDF) files under `kb_path`.
`indexer.py` splits them into chunks, computes a SHA-256 hash per file,
vectorizes each chunk with the embedding model, and writes everything to
ChromaDB. `server.py` then exposes search to the MCP clients.

## Project structure

```
<install_dir>\          <- Wherever you clone Cortex
|-- config.py           <- Product contracts and resolved configuration
|-- user_config.py      <- Strict TOML loading and atomic initialization
|-- chunker.py          <- Splits .md into chunks (headers + fixed size)
|-- chunker_pdf.py      <- Splits .pdf into chunks (pdfplumber + fixed size)
|-- chunker_utils.py    <- Shared helpers (hash, split, paths)
|-- indexer.py          <- Incremental sync to ChromaDB
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

### Why 512 characters per chunk?

The `paraphrase-multilingual-MiniLM-L12-v2` model truncates any input to 128
tokens maximum. Anything beyond that is never seen by the embedding. In French,
1 token is about 3.5 characters, so 512 characters equal about 145 tokens,
slightly above the theoretical ceiling, but the chunker cuts on natural
boundaries (line break, sentence end) which in practice produces shorter chunks.
Longer chunks (~2000 chars used early in the project) lost 70 to 80 % of the
indexed content to the embedding.

### Why are metadata paths relative?

The `path` stored in each chunk is relative to `CORTEX_KB_PATH` (for example
`operations/architecture.md`). This makes the index portable across machines as
long as the tree under the KB is identical, and it also serves the incremental
reconciliation.

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
