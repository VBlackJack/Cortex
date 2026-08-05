# Cortex - Public MCP Server and Index Contract

[Francais](../fr/spec.md) | **English**

> **Status**: Spec v2.1 - normative, synchronized with `main`
> **Author**: Julien Bombled
> **Date**: 2026-08-05
> **License**: [Apache 2.0](../../LICENSE)
> **Scope**: This document defines the observable surfaces, formats, and
> invariants of Cortex. Detailed design choices remain in
> [architecture.md](architecture.md).

The words "must", "must not", and "never" express contracts of the current
implementation. This document does not describe future or aspirational
behavior.

---

<!-- spec:identity -->
## 1. Product identity and read boundary

Cortex is a local, multi-client RAG server exposed through MCP. It indexes
user-selected Markdown and PDF files plus Markdown from the current published
ingestion generation, then returns the passages considered relevant to
clients. Files under `kb_path` remain authoritative for the `note` domain;
the current immutable generation is authoritative for the `doc` domain.
ChromaDB and the lexical index are reconstructible derived data.

| Surface | Observable contract |
|---|---|
| User documents | Read-only: no MCP tool creates, modifies, renames, or deletes a Markdown or PDF file under `kb_path` |
| Generated documents | Source writers publish immutable generations outside `kb_path`; only `current.json` selects the served generation |
| Derived index | `cortex_sync` can create and modify the local vector and lexical indexes from both domains |
| Search | Reads the index and returns chunks, source labels, and a freshness verdict |
| Runtime | Local CPU processing; Cortex forces `CUDA_VISIBLE_DEVICES` to an empty value |

The MCP client surface is therefore read-only with respect to the corpus, but
not with respect to derived data: `cortex_sync` is an index write operation.
Cortex provides no content editing tool, document mutation journal, or write
mechanism for `kb_path`. The separate operator CLI may publish generated source
content through an explicitly configured writer.

<!-- spec:mcp-tools -->
## 2. Transport and four-tool MCP surface

The `cortex serve` entry point starts FastMCP through `mcp.run()` over stdio.
The Cortex CLI exposes no HTTP or WebSocket transport and opens no network
listener. The server code registers exactly four tools and no Cortex-specific
MCP resource or prompt.

| Tool | Parameters | Behavior | Response format |
|---|---|---|---|
| `cortex_search` | `query: str`, optional `section`, `top_k`, `source_kinds`, `authors`, and occurred/updated RFC 3339 bounds | Local hybrid search, metadata filters, vector fallback, and domain-aware freshness | Structured schema v2 object with effective filters, results, citations, relevance, freshness, metadata, and compatibility Markdown |
| `cortex_sync` | `section: Optional[str] = None` | Incremental reconciliation of one section or the full configured scope | Markdown: `published_files`, `added_chunks`, `deleted_chunks`, `removed_files`, `skipped_files`, `errors` |
| `cortex_list_sections` | none | Lists included sections and top-level folders outside policy | Markdown: indexable sections followed by `out of policy` folders |
| `cortex_freshness` | `section: Optional[str] = None`, `include_entries: bool = False` | Compares live sources with index metadata without modifying them | Structured object: contract, scope, summary, duration, and optional per-file entries |

Section names are resolved case-insensitively. An unknown section returns an
error with the available sections. Configuration, migration, fingerprint, and
lock errors are converted into explicit responses; they do not become raw
traces on the client side.

<!-- spec:search -->
## 3. Hybrid search contract

`cortex_search` always clamps `top_k` between 1 and 10. In hybrid mode, each
branch retrieves at most 40 candidates. ChromaDB vector results and SQLite FTS5
lexical results are merged with Reciprocal Rank Fusion using `k = 60`, then the
first 20 candidates are offered to the
`jinaai/jina-reranker-v1-tiny-en` ONNX reranker.

| Returned mode | Condition | Final order |
|---|---|---|
| `hybrid+rerank` | Compatible lexical index and available reranker | Cross-encoder score, with stable order for ties |
| `hybrid` | Fusion is available but the reranker is not loaded or fails | RRF order, with degradation reason |
| `vector-only` | Lexical index is absent, incompatible, or unreadable | ChromaDB cosine distance, with fallback reason |

The lexical index neutralizes FTS5 query syntax by retaining only word tokens,
each placed in quotes. It is derived exclusively from ChromaDB chunks. ChromaDB
remains authoritative: a lexical failure degrades search but does not invalidate
the vector index.

Each Markdown hit contains its title or path, section and heading, vector
relevance when available, freshness verdict, and chunk text. A lexical-only hit
has the relevance `lexical-only`. A search with no results still reports the
mode and any fallback reason.

<!-- spec:indexing -->
## 4. Indexing and synchronization pipeline

| Stage | Observable contract |
|---|---|
| Vault selection | Only `.md` and `.pdf` files inside the configured `kb_path` scope are candidates; dot directories and denylisted paths are excluded |
| Ingestion selection | Only manifest-listed `.md` files under `documents/` in the generation selected by `current.json` are candidates |
| Snapshot | Markdown is decoded as strict UTF-8; a PDF is read and extracted from the same immutable binary snapshot |
| Chunking | H1-H3 for Markdown, pages for PDF, 512-character window, overlap of 64, and merging of small tails below 300 characters |
| Identity | `{path}::{content_hash}::{chunking_contract_version}::{ordinal}` with relative POSIX path, SHA-256 of exact bytes, and version `v3` |
| Vector publication | ChromaDB upsert in batches of 100, followed by read-back and verification of all expected IDs and metadata |
| Deletion | Old IDs are deleted only after verified publication of the new version |
| Lexical index | SQLite FTS5 is updated after ChromaDB and rebuilt from ChromaDB if absent, incompatible, or out of sync |

A Markdown chunk keeps the simple frontmatter title when present, otherwise the
file stem. A PDF chunk uses a title derived from the filename and a `Page N`
heading. Every chunk carries metadata schema v2, including `source_kind`,
`source_system`, stable source/container IDs, title, author, source dates,
canonical URI, relative path, section, capture date, logical `content_hash`,
and `chunk_index`. Internal index metadata additionally carries the exact-file
hash, expected chunk count, freshness contract, and chunking contract version.

Sync is hash-aware. An already complete and coherent version is skipped. A file
that becomes missing, excluded, empty, or too large is removed from both
indexes. A read, decode, extraction, or publication error increments `errors`
and preserves the old vector version. Reconciliation remains bounded to the
current section; in whole-folder mode, the reserved internal section `.`
represents all of `kb_path`. A full sync also reconciles `source_kind=doc` in
section `sources`. It reads only the current complete generation and preserves
existing document rows when the source, pointer, manifest, or documents
directory is unavailable or incomplete.

<!-- spec:freshness -->
## 5. Freshness contract v1

The observable contract has identifier `freshness-contract-v1` and hash version
`v1`. Internal `file_content_hash` is the lowercase SHA-256 of the exact bytes
read: no line ending, BOM, or Unicode normalization is applied. For a generated
Markdown document, public `content_hash` may instead carry the producer's valid
frontmatter hash of the normalized Markdown body; file identity and freshness
still use `file_content_hash`. PDF bytes are hashed as-is; Markdown must
additionally be valid UTF-8.

| Status | Meaning |
|---|---|
| `fresh` | All indexed chunks use the current contract and their hash equals the live snapshot |
| `stale` | The contract is coherent but the live hash differs |
| `unknown` | Legacy, incomplete, inconsistent, or out-of-contract metadata |
| `unindexed` | Eligible source that produces chunks, but has no indexed chunk |
| `no_chunks` | Present source that is empty or above the size limit |
| `missing` | Indexed path absent from the live corpus |
| `excluded` | Live source or indexed path now excluded by policy |
| `error` | Untrusted indexed path, unreadable source, invalid UTF-8, or extraction error |

The report always contains `contract_id`, `read_only: true`,
`freshness_is_not_completeness: true`, the scope, a per-status summary, and
`duration_ms`. Detailed entries are absent by default from the MCP tool and are
added only with `include_entries=true`. Out-of-policy folders are listed in the
scope without being presented as indexable sources.

Freshness is diagnosed and never repaired automatically. Cortex installs no
watcher and performs no implicit sweep before a read. Run `cortex sync`,
`sync.bat`, or `cortex_sync` after changing the corpus. `cortex_search` rehashes
each unique returned path against its own domain: `kb_path` for vault hits and
the current generation's `documents/` root for `doc` hits. An unavailable root
preserves the hit and marks freshness as `unavailable`.

When ingestion state exists, `cortex_freshness` also returns two-stage
freshness. The source stage reports remote-to-disk health; the index stage folds
in a dedicated `ingestion_index` comparison between the current generation and
indexed `doc` rows. The ingestion report is omitted when that domain is absent.

<!-- spec:integrity-concurrency -->
## 6. Index integrity and concurrency

The `cortex` ChromaDB collection uses cosine distance and a fingerprint made of
the embedding model, FastEmbed version, and `mean` pooling. A mismatch rejects
search and writes because the vector spaces are incompatible. An unstamped
legacy index is stamped only when its attested contract exactly matches the
current runtime.

| Operation | Lock and behavior |
|---|---|
| Search and freshness report | No sync lock on steady-state reads |
| Collection creation or stamping | Exclusive lock before any ChromaDB mutation |
| Vector and lexical sync | One exclusive lock covers the complete call and is reentrant within the process |
| Contention | Wait bounded to 30 seconds by default, then `CortexWriteLockedError` with no write |
| Abnormal writer termination | The OS-level file lock is released automatically |

Multiple clients can search concurrently. Only one sync operation can write at
a time; other writers must wait or retry after the timeout. The lock path and
timeout are configurable. If the lexical update fails after a valid vector
publication, ChromaDB remains authoritative and the next lexical preparation
detects the ID mismatch and rebuilds FTS5.

<!-- spec:clients -->
## 7. Nine user-scope MCP clients

The setup registry contains exactly nine IDs. Cortex defines no project-scope
configuration target.

| CLI ID | Client | User target | Format |
|---|---|---|---|
| `claude-desktop` | Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` | JSON `mcpServers.cortex` |
| `claude-code` | Claude Code | `claude mcp add --scope user` | Claude CLI, `user` scope |
| `codex` | Codex CLI and IDE extension | `~/.codex/config.toml` | TOML `[mcp_servers.cortex]` |
| `gemini` | Gemini CLI and Gemini Code Assist | `~/.gemini/settings.json` | JSON `mcpServers.cortex` |
| `antigravity` | Antigravity | `~/.gemini/config/mcp_config.json` | JSON `mcpServers.cortex` |
| `lmstudio` | LM Studio | `~/.lmstudio/mcp.json` | JSON `mcpServers.cortex` |
| `cursor` | Cursor | `~/.cursor/mcp.json` | JSON `mcpServers.cortex` |
| `windsurf` | Windsurf | `~/.codeium/windsurf/mcp_config.json` | JSON `mcpServers.cortex` |
| `vscode` | VS Code | `%APPDATA%\Code\User\mcp.json` | JSON `servers.cortex`, `type: stdio` |

A Python installation registers the absolute interpreter with `server.py`. A
standalone binary registers its own path with the `serve` argument.
Registration and uninstallation change only the `cortex` entry, preserve other
servers, and create a backup before modifying an existing file. Detection is
best-effort; Antigravity requires its live `~/.gemini/antigravity` profile to
avoid a Gemini false positive.

<!-- spec:data-locations -->
## 8. Configuration and data locations

| Data | Default location | Contract |
|---|---|---|
| Knowledge base | Path selected as `kb_path` | User source, never deleted by setup or reset |
| Configuration | Windows: `%APPDATA%\Cortex\config.toml`; others: `~/.config/Cortex/config.toml` | Strict TOML, `schema_version = 1`, unknown keys rejected |
| Data home | Windows: `%LOCALAPPDATA%\Cortex`; others: `$XDG_DATA_HOME/Cortex` or `~/.local/share/Cortex` | Root for generated machine-local data |
| Vector index | `<data_home>/chroma_db` | Overridable with `chroma_path` |
| Lexical index | `<parent of chroma_path>/lexical.db` | SQLite FTS5 derived from ChromaDB |
| Lock | `<data_home>/chroma_db.write.lock` | Overridable through configuration or environment |
| Models | `<data_home>/models` | FastEmbed cache shared by embedding and reranker |
| Logs | `<data_home>/logs/cortex.log` | 5,000,000 bytes per file, five backups |

Configuration precedence is environment, then TOML, then product default.
`CORTEX_KB_PATH` can override the corpus. Default limits are 1,000,000 bytes for
Markdown and 50,000,000 for PDF. Indexed paths are stored relative to `kb_path`
with POSIX separators.

If a legacy index exists next to the code, Cortex refuses to create a second
active index. Migration uses an atomic rename with no copy fallback; if both the
legacy source and target exist, Cortex refuses to choose or merge them.

<!-- spec:distribution -->
## 9. Distribution, models, and release

| Channel | Content and contract |
|---|---|
| Python source | Python 3.10 or newer, direct pins in `requirements.txt`, universal transitively resolved and hashed tree in `requirements.lock` |
| Standalone binaries | Windows x64, macOS arm64, and Linux x64; CLI and stdio server without Python, models not embedded |
| Windows installer | `Cortex-Setup.exe`, x64 compatible, no elevation, binary plus model payload in `%LOCALAPPDATA%\Cortex\models` |
| Release metadata | `SHA256SUMS` for artifacts and GitHub build provenance attestation |

The package version follows UTC CalVer `YYYY.MMDD.XX`; the two-digit counter
distinguishes multiple releases on the same day. A `v*` tag triggers builds for
all three platforms. Only a tagged run reaches the publication job;
`workflow_dispatch` builds without publishing.

The Windows chain fails closed. The model payload is acquired from the
revisions in `models.lock`, compared with the committed SHA-256 manifest,
materialized with only the declared files, then verified again. The build
wrapper rejects a missing executable, a mismatched binary version, a missing or
empty model payload, and direct compilation without valid defines. At runtime,
the presence of `manifest.json` requires verification of every file before ML
imports, then enables `HF_HUB_OFFLINE=1`.

Bare standalone binaries and source installations do not embed the models. If
their cache is empty, first use may download them. The release workflow
separately smoke-tests the Windows installer with Hugging Face networking
forced offline.

<!-- spec:limits-security -->
## 10. Security and accepted limits

| Limit | Current contract |
|---|---|
| MCP transport | stdio only; no Cortex HTTP or WebSocket endpoint |
| Document writing | No MCP tool writes source content; `cortex_sync` writes derived indexes, while explicit source CLIs may publish immutable generated generations outside `kb_path` |
| Client scope | User registration only; no project scope |
| Source formats | UTF-8 Markdown and native PDF only, with configured size limits |
| Change detection | No watcher; explicit sync required |
| Encryption and authentication | No Cortex encryption at rest and no MCP client authentication |
| Network | The verified installer operates offline; source and bare binary may download missing models; the optional Confluence writer reads its configured HTTPS origin |
| Secrets | Confluence PATs are accepted only through an interactive prompt and stored in Windows Credential Manager, never TOML, environment, arguments, or logs |

ChromaDB is always opened through `chromadb.PersistentClient` with
`anonymized_telemetry=False`. Cortex never starts the ChromaDB HTTP server, does
not use `HttpClient`, and does not pass `trust_remote_code=true`. For this
reason, CI temporarily ignores `PYSEC-2026-311` (`CVE-2026-45829`), which targets
that HTTP server path. This single ignore must be removed when a compatible
fixed ChromaDB release can be pinned.

Cortex does not send corpus content to a remote service. An MCP client is a
separate product, however: it may send requested chunks to its model according
to its own policy. Machine confidentiality, disk encryption, and client
authorization remain outside the Cortex boundary. See
[security.md](security.md) and [faq.md](faq.md).

<!-- spec:version-license -->
## 11. Spec version, documentation boundary, and license

| Spec version | Date | Change |
|---|---|---|
| 2.1 | 2026-08-05 | Metadata v2 filters, ingestion generations, Confluence writer, and two-stage freshness |
| 2.0 | 2026-07-21 | First public specification aligned with the implementation on `main` |

This spec is the reference for observable contracts of the MCP server, indexes,
setup, and distribution. Internal topology and design rationale remain in
[architecture.md](architecture.md); operational settings remain in
[configuration.md](configuration.md), and the user journey remains in the
[guide](user-guide.md).

This spec and the [Cortex](../../README.en.md) reference implementation are
released under the [Apache License, Version 2.0](../../LICENSE).
