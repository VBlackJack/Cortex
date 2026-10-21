# Architecture

[Français](../fr/architecture.md) | **English**

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

## Per-client or shared server

By default (`[server] mode = "per-client"`), every MCP client session starts its
own `cortex serve`, which loads the embedding model, opens the index and serves
that one client. Thirty open sessions mean thirty complete processes.

With `mode = "shared"`, the command line written into the clients stays
`cortex serve`, but it becomes a light relay:

```
MCP client --stdio--> cortex serve (relay) --+
MCP client --stdio--> cortex serve (relay) --+--> local endpoint --> cortex daemon run
MCP client --stdio--> cortex serve (relay) --+                         (one per user)
```

**What is shared.** The daemon hosts the single FastMCP instance and its four
tools, the embedding model, the reranker, one Chroma client and one read-only
lexical connection, the write lock and the logs. Each connection keeps its own
MCP session: initialization, request ids and cancellation. Synchronous tools run
in worker threads, so a long `cortex_sync` never freezes the other sessions;
reads run one at a time, and a second sync started from another session gets the
same "locked" answer as a sync blocked by another process.

**Seeing other writers.** A long-lived Chroma client does not see vectors that
another process wrote: its vector segment stays as it was loaded. The daemon
therefore reopens its client before a read once the index files have changed and
the write lock is free again, so a `cortex sync` run from a console or a
scheduled task is visible to the next search.

**Endpoint security.** No TCP port is ever opened. On Windows the endpoint is
the named pipe `\\.\pipe\cortex-<user SID>-v1`, created with a DACL that grants
access to the current user only, `FILE_FLAG_FIRST_PIPE_INSTANCE` and
`PIPE_REJECT_REMOTE_CLIENTS`; the daemon checks that every client process belongs
to the same user, and the relay checks the same of the serving process. Elsewhere
it is a Unix socket in a 0700 directory owned by the user, the socket itself
0600, with the peer uid checked where the platform exposes it. Every connection
opens with a versioned frame, at most 4 KiB, carrying a random 32-byte token that
the daemon writes to `<data home>\daemon\token` at each start; JSON-RPC lines are
then limited to 8 MiB. The token is never logged.

**Lifecycle.**

- One daemon per user, held by `<data home>\daemon\daemon.lock`; the operating
  system releases it if the process dies.
- The first relay that finds no daemon starts one detached, then waits for it at
  most 10 seconds; failing that, it serves the session itself in per-client mode.
- The daemon drains and exits after `idle_timeout_seconds` without a session,
  when `config.toml` changes (it resolves the configuration once at start, like
  every Cortex process), on `cortex daemon stop`, or when a relay of a newer
  version asks for it. A drain lets in-flight requests finish, a sync always.
- When the connection closes, the relay answers a JSON-RPC error for a request
  in flight, never replays it, then reconnects and replays the session's
  `initialize` exchange. After three losses within five minutes it serves the
  rest of the session in its own process.
- A relay whose `CORTEX_*` environment differs from the daemon's, or that meets
  a newer daemon or an endpoint held by another process, serves its session in
  per-client mode. It never takes over an endpoint.

Known limit: a client that puts its servers in a kill-on-close Windows job
without allowing breakaway (the MCP Python SDK client does) also kills the
daemon its relay started when it closes; the other relays then start a new one.

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
|-- daemon_*.py         <- Shared mode: daemon, relay, endpoint, frames
|-- sync.bat            <- Development: sync section by section (%~dp0)
|-- install.bat         <- Development: install from the clone (%~dp0)
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
- The development scripts `install.bat` and `sync.bat` use `%~dp0`: they find
  their own run folder.
- `setup_config.py` detects its own location to register the server in each
  client.
- `%APPDATA%\Cortex\config.toml` separates roaming choices from the shipped
  code; `%LOCALAPPDATA%\Cortex` holds the machine-specific data.

Result: a developer can clone Cortex into any folder on any machine, run
`install.bat`, and work from that checkout. End users do not clone anything:
`Cortex-Setup.exe` or a standalone archive installs the same code as a
self-contained executable folder.
