# Configuration

[Francais](../fr/configuration.md) | **English**

[Back to table of contents](index.md)

## Environment variables

| Variable | Role | Default |
|---|---|---|
| `CORTEX_KB_PATH` | Optional override of `kb_path` | none |
| `CORTEX_WRITE_LOCK_PATH` | Override the lock path | `<data_home>/chroma_db.write.lock` |
| `CORTEX_WRITE_LOCK_TIMEOUT_SECONDS` | Override the lock timeout | `30` |
| `CORTEX_MAX_MARKDOWN_FILE_SIZE_BYTES` | Override the Markdown size limit | `1000000` |

The user configuration lives in `%APPDATA%\Cortex\config.toml` with
`schema_version = 1`. It never contains a secret. Precedence is environment
variable > TOML file > product default. Historical environment variables remain
compatible, but `install.bat` no longer creates them on a fresh install.

Schema v1 accepts the optional `chroma_path` and `index_whole_folder` keys, so
any existing v1 file stays valid. By default the lightweight configuration
stays roaming in `%APPDATA%\Cortex`, while
the index, the lock and the bulky logs live locally in `%LOCALAPPDATA%\Cortex`.

## Separate source configuration

Cortex keeps three strict TOML surfaces separate. Unknown keys fail closed, and
none of these files accepts a secret:

| File | Scope | Details |
|---|---|---|
| `%APPDATA%\Cortex\config.toml` | User-selected Markdown/PDF folder and derived indexes | This page |
| `%APPDATA%\Cortex\ingestion.toml` | Shared generations, retention, retry, lock, credential lifetime, and cadence | [Ingestion scheduling](ingestion-scheduling.md) |
| `%APPDATA%\Cortex\confluence.toml` | Confluence URL, console, declared expiry, limits, and whole-space or page selection | [Confluence writer](confluence-writer.md) |

Environment variables override the matching TOML values. The PAT is stored
interactively in Windows Credential Manager, never in a TOML file or an
environment variable.

`confluence.toml` accepts schema v1 and v2. Existing schema v1 files remain
whole-space allowlists and are never rewritten while loading. Schema v2
requires each space to declare `selection = "whole_space"` or
`selection = "pages"`; page mode may deliberately contain an empty list.

## Example config.toml

```toml
schema_version = 1
kb_path = "D:\\Knowledge"
chroma_path = "C:\\Users\\me\\AppData\\Local\\Cortex\\chroma_db"
index_whole_folder = true
included_sections = ["knowledge", "projects", "notes"]
excluded_dirs = [".datacron", "_archive", "_trash", "_attachments", "zzz_Corbeille", "_inbox", "_journal"]
exclude_files = ["00_INDEX.md"]
max_markdown_file_size_bytes = 1000000
max_pdf_size_bytes = 50000000
write_lock_path = "C:\\Users\\me\\AppData\\Local\\Cortex\\chroma_db.write.lock"
write_lock_timeout_seconds = 30
```

Create the file manually or run:

```powershell
python setup_config.py --init
```

`kb_path` is required for `cortex_sync` and `cortex_freshness`, with no default.
Search keeps working on the existing index when it is absent.

`chroma_path` and `write_lock_path` can be omitted to use the local data home,
or set explicitly for a specific operational need.

## Whole folder or sections

With `index_whole_folder = true`, Cortex recursively indexes all of `kb_path`
while still honoring `excluded_dirs` and `exclude_files`. This is the Windows
installer default for a new machine. `included_sections` remains in the file
but is not used in this mode.

An existing configuration without `index_whole_folder` keeps its historical
behavior: the absent value means `false` and enables sections.

To change modes safely on an existing installation, select `Reset` in the
installer or run:

```powershell
$env:CORTEX_KB_PATH = "D:\Knowledge"
$env:CORTEX_INDEX_MODE = "whole"
cortex setup --reset --yes
```

Reset removes `config.toml` and generated data from the data home before
rebuilding the index. It never deletes `kb_path`. Without `--reset`, an
existing configuration remains untouched.

Indexable sections are defined by `included_sections` in `config.toml`. A
top-level folder absent from both the allowlist and the denylist is never
indexed automatically: `cortex_list_sections` reports it as "out of policy"
until an explicit decision. MCP validation is case-insensitive (`KNOWLEDGE`
becomes `knowledge`).

From Claude, the `cortex_list_sections` MCP tool lists all available sections.

### Add a new section

1. Export the section under the configured `kb_path` folder.
2. Add its name to `included_sections` in `config.toml`.
3. Run `sync.bat` (or `cortex_sync` from Claude).

Without this opt-in, the folder stays visible as "out of policy" but is never
sent to the embedding model.

## Index contracts (not user-editable)

Index contracts stay centralized in `config.py` and are not user-editable:

```python
COLLECTION_NAME = "cortex"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_POOLING = "mean"
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
CHUNKING_CONTRACT_VERSION = "v3"
METADATA_SCHEMA_VERSION = 2
LEXICAL_INDEX_CONTRACT_VERSION = "v2"
SEARCH_TOP_K_MIN = 1
SEARCH_TOP_K_MAX = 10
SEARCH_HYBRID_CANDIDATES = 40
SEARCH_RERANK_CANDIDATES = 20
INGESTION_DOCUMENT_SOURCE_KIND = "doc"
INGESTION_DOCUMENT_SECTION = "sources"
```

`CHUNK_SIZE` is sized to stay under the MiniLM model's 128-token limit with a
safety margin. See "Why 512 characters per chunk?" in the
[architecture](architecture.md).

## Migrating the old index

If `chroma_db` still exists next to the code and the data home target does not,
`setup_config.py` offers to move it:

```powershell
python setup_config.py --migrate-data
```

The move uses an atomic rename and never creates a silent copy. If source and
target are on different volumes, Cortex refuses the copy fallback: close all
clients, move the folder manually, or temporarily set `chroma_path` to the
source volume. If the old and new index exist simultaneously, Cortex refuses to
choose or merge them. The fingerprint is contained in the moved folder; the
write lock uses the data home by default, while an existing explicit override is
strictly respected. To roll back, close the clients and move the folder back the
other way.
