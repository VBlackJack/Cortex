# Frequently asked questions

[Francais](../fr/faq.md) | **English**

[Back to table of contents](index.md)

These answers describe the current Cortex behavior. For detailed procedures,
see [Windows installation](windows-install.md), [installation from source](setup.md),
[configuration](configuration.md), the [user guide](user-guide.md), and
[security](security.md).

<!-- faq:install-or-source -->
## Should I use the Windows installer or install Cortex from source?

Use `Cortex-Setup.exe` for a standard Windows installation. It does not require
Python, installs the application under `%LOCALAPPDATA%\Programs\Cortex`, adds the
shortcuts and user `PATH`, and provides the verified model payload. This is the
recommended path for a user workstation.

Installing from source requires Python 3.10 or newer. Choose it to develop
Cortex, modify the code, or test a revision that has not been released yet.
`install.bat` installs dependencies, initializes configuration, and offers client
registration. The standalone macOS and Linux binaries do not require Python
either.

<!-- faq:data-locations -->
## Where do configuration, the index, models, and logs live, and how much space is needed?

Lightweight configuration lives in `%APPDATA%\Cortex\config.toml`. By default,
generated local data lives under `%LOCALAPPDATA%\Cortex`:

- `chroma_db\` contains the vector index;
- `models\` contains the ONNX models;
- `logs\cortex.log` and its rotations contain logs;
- `chroma_db.write.lock` coordinates writes.

The attested model payload contains 12 files totaling 386,522,634 bytes
(368.62 MiB). Index size depends on the corpus. Each log file is capped at
5,000,000 bytes, with at most five backups. Source documents remain in the
selected knowledge-base folder.

<!-- faq:change-kb -->
## How do I change the knowledge-base path after installation?

Edit `kb_path` in `%APPDATA%\Cortex\config.toml`, close clients that use Cortex,
then restart them and run `cortex sync`. The new process reloads configuration;
incremental sync adds files from the new folder and removes paths that are no
longer present from the index.

To start with fresh configuration and a fresh index instead, use:

```powershell
$env:CORTEX_KB_PATH = "D:\NewKnowledgeBase"
cortex setup --reset --yes
```

Reset removes Cortex configuration and generated data, never documents from the
old or new knowledge base. `CORTEX_KB_PATH` overrides the configuration file for
the current process.

<!-- faq:sync-after-edits -->
## Must I reindex after adding, changing, or deleting documents?

Yes. Cortex does not install a file watcher. Run one of these paths:

```powershell
cortex sync
```

You can also run `sync.bat` or request the `cortex_sync` MCP tool from a client.
Sync is incremental: it reprocesses new or changed files and removes files that
were deleted, emptied, or newly excluded. To rebuild from scratch after a model
change or corruption, close clients, delete
`%LOCALAPPDATA%\Cortex\chroma_db`, then run a sync.

<!-- faq:client-not-seeing-cortex -->
## My client cannot see Cortex. What should I check?

First fully restart the client: MCP configurations are generally loaded at
startup. Then run:

```powershell
cortex check --clients all
cortex doctor
```

`cortex check` validates registered entries and paths. `cortex doctor` performs
strictly read-only layered diagnostics and distinguishes `FAIL`, `WARN`,
`UNKNOWN`, and `SKIP`. If the entry is missing, run
`cortex register --clients all`, then restart the client again. Registration is
user-scoped and preserves other MCP servers in shared files.

<!-- faq:uninstall -->
## What does Windows uninstall remove, and how do I clean everything?

The uninstaller first attempts `cortex unregister --yes --clients all`, then
removes the application, its shortcuts, its user `PATH` entry, and the installed
model files. Other MCP servers are preserved.

The knowledge base is never deleted. `%APPDATA%\Cortex\config.toml`, the index,
and logs under `%LOCALAPPDATA%\Cortex` are not explicit uninstaller cleanup
targets and may remain. For a complete cleanup, close every client, uninstall
Cortex, then manually delete `%APPDATA%\Cortex` and `%LOCALAPPDATA%\Cortex`.
Delete the documents folder only if you also intend to erase your own source
files.

<!-- faq:logs -->
## Where are the logs, and how do I read them?

The main log is `%LOCALAPPDATA%\Cortex\logs\cortex.log`. Cortex also writes
operational messages to stderr. Logs rotate at 5,000,000 bytes per file with
five backups, and never contain document or chunk text: only paths, statuses,
errors, and counters.

In PowerShell, show the latest lines with:

```powershell
Get-Content "$env:LOCALAPPDATA\Cortex\logs\cortex.log" -Tail 100
```

For a shareable diagnostic, start with `cortex doctor` and include only relevant
log lines.

<!-- faq:offline-models -->
## Does Cortex work offline, and how are models managed?

The Windows installer provides the embedding and reranker payload under
`%LOCALAPPDATA%\Cortex\models`. At startup, Cortex verifies every file against
the embedded SHA-256 manifest, then forces `HF_HUB_OFFLINE=1`. An installation
made with this installer can therefore index and search without Hugging Face
access.

An installation from source or a raw standalone binary must download models on
first use if its cache is empty. Revisions and required files are pinned in
`models.lock`. Dependency installation and that first download use the network,
but knowledge-base content is not sent.

<!-- faq:pip-audit -->
## Why does pip-audit ignore PYSEC-2026-311 for ChromaDB?

`PYSEC-2026-311` (`CVE-2026-45829`) is a pre-authentication remote code
execution issue in the ChromaDB HTTP server through the REST API with
`trust_remote_code=true`. Cortex does not use that path: it only uses embedded
`chromadb.PersistentClient`, with no REST server or `HttpClient`, and fixed local
ONNX models through FastEmbed.

The CI workflow therefore ignores this single vulnerability while no compatible
fixed ChromaDB release exists. The audit still covers the entire locked
transitive dependency tree, and any other vulnerability fails the job. The
ignore must be removed as soon as a fix can be pinned.

<!-- faq:parallel-clients -->
## Can I use multiple Cortex clients in parallel?

Yes for searches. Reads through `cortex_search` and `cortex_freshness` do not
take the write lock. However, only one sync operation can write to ChromaDB at a
time. Every write entry point takes an OS-level file lock; a second writer waits
for at most 30 seconds, then fails cleanly without writing and asks you to retry
later.

Do not run `sync.bat`, `cortex sync`, and `cortex_sync` simultaneously. Let the
first sync finish, then retry the second. The operating system automatically
releases the lock if its process exits or crashes, so stale-lock cleanup is not
normally required.
