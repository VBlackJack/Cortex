# Cortex - RAG MCP for a knowledge base

[Francais](README.md) | **English**

Cortex is an MCP (Model Context Protocol) server that exposes semantic search
over a local knowledge base. It lets Claude, Codex and Gemini query internal
documentation without wasting their context window. Search is semantic (by
meaning, not keyword), in French and in English, and everything stays local: no
content from the knowledge base ever leaves the machine.

## How it works

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

The embedding model is the multilingual ONNX
`paraphrase-multilingual-MiniLM-L12-v2`.

## Quick start

```bat
:: From the folder where you cloned Cortex
install.bat
```

`install.bat` initializes the configuration, installs the dependencies, offers
to register Cortex in the detected MCP clients, and validates the installation.
After installation, restart the registered clients. Details:
[Setup](docs/en/setup.md).

## Exposed MCP tools

| Tool | Description |
|---|---|
| `cortex_search` | Semantic search. Parameters: `query`, `section` (optional), `top_k` (1-10). |
| `cortex_sync` | Triggers an incremental sync. Parameter: `section` (optional). |
| `cortex_list_sections` | Lists included sections and "out of policy" folders. |
| `cortex_freshness` | Freshness summary. Parameters: `section` (optional), `include_entries` (`false` by default). |

## Documentation

- [Table of contents](docs/en/index.md)
- [Setup](docs/en/setup.md): prerequisites, MCP clients.
- [User guide](docs/en/user-guide.md): sync, search, tools, doctor, logs.
- [Configuration](docs/en/configuration.md): `config.toml`, sections, data home,
  migration.
- [Reproducible install](docs/en/reproducible-install.md): `requirements.lock`,
  `--require-hashes`, regenerating the lock.
- [Architecture](docs/en/architecture.md): end-to-end and technical choices.
- [Security](docs/en/security.md): no outbound traffic, telemetry off,
  single-writer.

## Prerequisites

| Tool | Minimum version |
|---|---|
| Python | 3.10+ |
| Client | Claude Desktop/Code, Codex or Gemini with MCP support |
| Disk space | ~500 MB (model + index) |

## License

Apache 2.0. See [LICENSE](LICENSE).
