# Cortex - RAG MCP for a knowledge base

<!-- mcp-name: io.github.VBlackJack/cortex -->

[Francais](README.md) | **English**

Cortex is an MCP (Model Context Protocol) server that exposes semantic search
over a local knowledge base. It lets Claude, Codex and Gemini find the right
passage in your documents without wasting their context window. Search is
semantic (by meaning, not keyword), in French and in English. Cortex processes
and indexes the knowledge base locally without sending its content; the MCP
client may still pass requested chunks to its model under its own policy.
The optional Confluence writer only downloads explicitly allowlisted spaces;
the generated Markdown, vector index, and lexical index remain local.

## Installation

### Windows, no Python (recommended)

The simplest path: one installer for Cortex, Cortex Companion, the windowless
Confluence converter, and the offline models. No separate Python or .NET
runtime is required.

1. Download `Cortex-Setup.exe` and `SHA256SUMS` from the
   [latest release](https://github.com/VBlackJack/Cortex/releases/latest).
2. Before running the unsigned installer, calculate its digest with
   `Get-FileHash .\Cortex-Setup.exe -Algorithm SHA256` in PowerShell and verify
   that it exactly matches the `Cortex-Setup.exe` line in `SHA256SUMS`.
3. Double-click only after that check. If SmartScreen still warns, select
   `More info`, then `Run anyway`.
4. Choose the folder that holds your documents, keep `Index everything in this
   folder`, and finish. Cortex Companion opens when installation completes.
5. In Companion, open `Réglages` (Settings) and verify the knowledge-base
   folder. The Cortex executable installed with Companion is detected
   automatically.
6. Drop your documents in that folder, open `Base locale` (Local knowledge
   base), then select `Synchroniser les documents locaux` (Synchronize local
   documents).
7. Restart your AI application: Cortex shows up there as an MCP server.

Companion then lets you synchronize, schedule, diagnose, and configure Cortex
without a terminal. Details, silent mode and reinstall:
[Windows install](docs/en/windows-install.md).

### Standalone archives (Windows x64, macOS Apple Silicon, Linux x64)

Every release also ships one ZIP archive per platform. It contains the single
`cortex` or `cortex.exe` binary (MCP server + CLI, no Python) and the licenses
for every embedded dependency. See
[Standalone distribution](docs/en/distribution.md).

### From PyPI (Python, advanced)

```powershell
py -m pip install --upgrade cortex-local-rag
cortex setup
```

This path installs the CLI and MCP server, but not Cortex Companion. The model
is downloaded on first use if its cache is empty.

### From source (Python, advanced)

```bat
:: From the folder where you cloned Cortex
install.bat
```

`install.bat` initializes the configuration, installs the dependencies, offers
to register Cortex in the detected MCP clients, and validates the installation.
Details: [Setup](docs/en/setup.md).

## How it works

```
Documents folder (.md, .pdf)       Optional Confluence writer (REST)
      |                                      |
      |                              current Markdown generation
      +------------------+-------------------+
                         |
                         v
  cortex sync           <- Split, hash, vectorize, update FTS5
                         |
                         v
  %LOCALAPPDATA%\Cortex\  <- ChromaDB + lexical.db
      |
      v
  cortex serve          <- MCP server (FastMCP)
      |
      v
  MCP clients           <- Claude / Codex / Gemini / Antigravity / LM Studio / Cursor / Windsurf / VS Code
```

The embedding model is the multilingual ONNX
`paraphrase-multilingual-MiniLM-L12-v2`. The Windows installer bundles it; a
source installation or standalone binary downloads it when the local cache is
empty.

## Two indexing modes

- **Whole folder** (default): anything you place in the chosen folder, at the
  root or in any subfolder, becomes searchable. Nothing to configure.
- **Sections** (advanced): limits indexing to named subfolders you can search
  separately (defaults `knowledge`, `projects`, `notes`).

These modes govern the user-selected document folder. Generated ingestion
documents are indexed separately from the current published generation with
`source_kind=doc` and section `sources`.

Details: [Configuration](docs/en/configuration.md).

## The `cortex` command

The installed package exposes a single command:

| Subcommand | Purpose |
|---|---|
| `cortex setup` | Config + index + client registration in one go (`--kb-path`, `--yes`, `--no-index`, `--reset`). |
| `cortex serve` | Runs the MCP server (used by clients). |
| `cortex sync` | Incremental index synchronization. |
| `cortex ingestion` | Shows source health and whether catch-up is due. |
| `cortex confluence` | Stores the PAT interactively or runs the allowlisted writer. |
| `cortex config` | Reads or changes configuration through an atomic JSON contract, notably for Companion. |
| `cortex bundle` | Describes or verifies an encrypted portable archive. |
| `cortex doctor` | Installation diagnostics (read-only). |
| `cortex register` / `cortex unregister` | Adds or removes Cortex from MCP clients. |
| `cortex init` | Creates the single per-user configuration. |
| `cortex check` | Verifies the installation. |

`cortex --help` describes every subcommand and `cortex <command> --help` describes
its options. A prompt-free installation scripts as:

```powershell
cortex setup --yes --kb-path "D:\Documents\Knowledge"
```

## Exposed MCP tools

| Tool | Description |
|---|---|
| `cortex_search` | Hybrid search. Parameters: `query`, `section`, `top_k` (1-10), source/author filters, and occurred/updated date ranges. |
| `cortex_sync` | Triggers an incremental sync of the selected folder and, on a full sync, the current published document generation. |
| `cortex_list_sections` | Lists included sections and "out of policy" folders. |
| `cortex_freshness` | Read-only vault and ingestion freshness summary. Parameters: `section` (optional), `include_entries` (`false` by default). |

## Documentation

- [Table of contents](docs/en/index.md)
- [Windows install](docs/en/windows-install.md): unified Cortex + Companion +
  Confluence converter + models installer, corpus choice, silent mode,
  reinstall.
- [Standalone distribution](docs/en/distribution.md): per-platform archives and reproducible builds.
- [Install from source](docs/en/setup.md): prerequisites, MCP clients.
- [User guide](docs/en/user-guide.md): sync, search, tools, doctor, logs.
- [FAQ](docs/en/faq.md): installation, local data, sync, and diagnostics.
- [Release notes](docs/en/release-notes.md): user-visible changes by version and
  the published-history notice.
- [Technical changelog](CHANGELOG.md): complete changes by version.
- [Configuration](docs/en/configuration.md): `config.toml`, indexing modes,
  sections, data home, migration.
- [Ingestion scheduling](docs/en/ingestion-scheduling.md): source health,
  catch-up, retries, and Task Scheduler.
- [Metadata v2 migration](docs/en/metadata-v2-migration.md): structured search
  metadata, backup, migration, and restore.
- [Confluence writer](docs/en/confluence-writer.md): allowlisted REST ingestion,
  Windows Credential Manager, conversion, and atomic generations.
- [Reproducible install](docs/en/reproducible-install.md): `requirements.lock`,
  `--require-hashes`, regenerating the lock.
- [Public specification](docs/en/spec.md): MCP surface, index contracts, data,
  distribution, and limits.
- [Architecture](docs/en/architecture.md): end-to-end and technical choices.
- [Security](docs/en/security.md): local runtime, telemetry off,
  single-writer.

## Prerequisites

| Path | Requirements |
|---|---|
| Windows installer | No separate Python or .NET runtime. At least ~500 MB of space (applications, model + index). |
| Standalone archive | No Python. ~500 MB of space (model + index). |
| From source | Python 3.10+. ~500 MB of space. |
| Client | Claude Desktop/Code, Codex, Gemini, Antigravity, LM Studio, Cursor, Windsurf or VS Code (MCP support). |

## License

Apache 2.0. See [LICENSE](LICENSE).
