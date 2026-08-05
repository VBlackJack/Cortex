# User guide

[Francais](../fr/user-guide.md) | **English**

[Back to table of contents](index.md)

## Indexing (sync)

### Full sync (all sections)

```bat
:: From the install folder
sync.bat
```

The sync is incremental: only new or modified files (detected via SHA-256 and
the chunking contract version) are reprocessed. Deleted, emptied or newly
excluded files are removed from the index.

A full sync also reconciles Markdown from the current published ingestion
generation. Pending or incomplete generations are never indexed, and an
unavailable generation preserves the already indexed `doc` rows.

On a new Windows installation, this sync covers the entire knowledge-base
folder recursively. The section filtering below only applies to advanced mode.

### Sync a single section

```powershell
python indexer.py operations
```

### From an MCP client

```
cortex_sync                       # all sections
cortex_sync section="operations"  # a single section
```

### Start from scratch (model changed, index corrupted)

1. Quit all MCP clients connected to Cortex.
2. Delete the `%LOCALAPPDATA%\Cortex\chroma_db\` folder (or the configured
   `chroma_path`).
3. Restart the MCP clients.
4. Run `sync.bat`.

## Search

### From an MCP client

The client may call `cortex_search` automatically when a question relates to
internal documentation. You can also request it explicitly, for example:
"Search Cortex for how to configure Zabbix alerts".

### On the command line (debug)

```powershell
# Global search
python indexer.py --search "zabbix alerts"

# Search within a section (the section is positional)
python indexer.py knowledge --search "deployment procedure"

# Number of results
python indexer.py --search "OSCARE" --top-k 10
```

Search responses use metadata schema v2. In addition to `section`, searches can
filter on `source_kinds`, `authors`, `occurred_at_from`, `occurred_at_to`,
`updated_at_from`, and `updated_at_to`. Date bounds are RFC 3339 timestamps.
Every result contains reconstructed metadata, a citation, relevance, and a
freshness verdict resolved in its own vault or ingestion domain.

## The four MCP tools

| Tool | Description |
|---|---|
| `cortex_search` | Hybrid search. Parameters: `query`, `section`, `top_k` (1-10), source/author filters, and occurred/updated date ranges. |
| `cortex_sync` | Triggers an incremental sync and includes the current document generation on a full sync. Parameter: `section` (optional). |
| `cortex_list_sections` | Lists included sections and "out of policy" folders. |
| `cortex_freshness` | Read-only vault and two-stage ingestion freshness. Parameters: `section` (optional), `include_entries` (`false` by default). |

When ingestion exists, `cortex_freshness` reports remote-to-disk source health,
the current generation ID, and disk-to-index status. The dedicated
`ingestion_index` summary is omitted when no document generation is available.

## Ingestion operations

The generic ingestion CLI reports the latest atomic source health and whether a
missed-window catch-up is due. The Confluence adapter stores its PAT
interactively and runs through the same locking, retry, expiry, and generation
engine:

```powershell
cortex ingestion status doc
cortex ingestion due doc
cortex confluence store-credential
cortex confluence sync
cortex confluence sync --force
```

See [Ingestion scheduling](ingestion-scheduling.md) for exit codes and settings,
and [Confluence writer](confluence-writer.md) for the allowlist and converter
contract.

## Cortex Doctor

The first tool to run for a support diagnostic is strictly read-only: it does
not repair, create or write anything, not even an application log. The index is
inspected via SQLite `mode=ro&immutable=1` rather than through
`PersistentClient`.

```powershell
# Human-readable report to copy and paste
python setup_config.py --doctor
cortex doctor

# Stable JSON schema (schema_version = 1)
python setup_config.py --doctor --json
```

The report covers Python and dependencies, the configuration and `kb_path`, the
migration state, the chunk count, the fingerprint, freshness in summary mode,
the write lock, the last sync errors, then each client in layers: binary,
optional VS Code extension, MCP entry, paths and authentication. `UNKNOWN`
always means "not automatically probeable" and provides the manual action to
take; it is never presented as OK.

A single global handshake actually launches `server.py`, sends MCP `initialize`,
checks the response, then terminates the process with a 20-second timeout. For
this probe the server uses a diagnostic lifespan that does not open Chroma
(`PersistentClient` would modify SQLite on open alone), since the index was
already checked separately in read-only mode.

The exit code is `0` when there is no `[FAIL]`. The `[WARN]`, `[UNKNOWN]`,
`[INFO]` and `[SKIP]` statuses remain informational.

The installed subcommands are thin dispatchers to the same entry points as the
historical scripts:

```powershell
cortex setup [--clients all] [--no-index] [--reset] [--yes]
cortex sync [section]
cortex ingestion [--config FILE] {status,due} SOURCE_KIND
cortex confluence [--config FILE] [--ingestion-config FILE] {store-credential,sync}
cortex doctor [--json]
cortex init
cortex register [--clients all]
cortex check [--clients all]
```

`cortex setup` chains init, index and client registration in a single call (see
[Setup](setup.md#one-command-setup)).

## Bounded local logs

Each Cortex process keeps the stderr output expected by MCP clients and also
writes to `%LOCALAPPDATA%\Cortex\logs\cortex.log`. Rotation is bounded to 5 MB
per file and 5 backups. The logs never contain document or chunk text: only
paths, statuses, errors and operational counters.

## Tests

```powershell
python -m pytest tests/ -v
```

The unit tests (`tests/test_chunker.py`) always run. The integration tests
(`tests/test_search.py`) are automatically skipped if the resolved
`chroma_path` does not exist yet.

### Local quality gate

```powershell
python -m pip install -e ".[dev]"
python -m pre_commit run --all-files
```

Every commit runs Ruff, mypy in strict mode and the full pytest suite. CI
replays these same hooks, with no parallel quality configuration.
