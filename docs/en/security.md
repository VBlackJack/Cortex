# Security

[Francais](../fr/security.md) | **English**

[Back to table of contents](index.md)

## No outbound data flow

All Chroma clients are built with `Settings(anonymized_telemetry=False)`: no
Chroma/PostHog telemetry is emitted. Indexing and search do not initiate any
outbound network flow from Cortex. The MCP clients remain distinct products:
depending on their policy, they may pass the tool results they requested to the
model. Installing the dependencies and the first model download are naturally
network operations, without transmitting the content of the knowledge base.

## Ignored ChromaDB vulnerability (PYSEC-2026-311)

The CI audit explicitly ignores one vulnerability: `PYSEC-2026-311`
(CVE-2026-45829), a pre-authentication RCE in the ChromaDB HTTP server through
its REST API with `trust_remote_code=true`. It is not exploitable in Cortex:
Cortex uses an embedded `PersistentClient`, never the ChromaDB HTTP server, and
the ONNX model is pinned locally via fastembed, so the `trust_remote_code` path
is never taken. A scan confirms the absence of any `HttpClient` in the sources.
The ignore is documented in the CI workflow and must be removed as soon as a
fixed ChromaDB version is published (bump the pin).

## Single-writer writes (write lock)

ChromaDB (SQLite backend) accepts only one writer at a time. Two index
corruption incidents (a segfault, then an HNSW/metadata desync) had the same
root cause: two concurrent writes on the same DB (typically `server.py`
respawned by Claude Desktop while a sync was already running).

Each Chroma write point now acquires an exclusive inter-process lock
(`filelock`, OS level, auto-released if the holding process dies, whether crash,
kill or respawn) before touching the DB. If a second writer tries to write while
a first holds the lock, it fails cleanly (`CortexWriteLockedError`, bounded
timeout, never an infinite wait). `cortex_sync` then returns a "locked, retry
later" message rather than a raw error. Reads (`cortex_search`,
`cortex_freshness`) are never blocked: Chroma allows concurrent reads, only
writing is single-writer.

Proof (see `tests/test_write_lock.py`, 4 tests, real processes and an isolated
DB): two concurrent writers produce exactly one success and one clean failure,
DB integrity preserved; the respawn-during-sync scenario is reproduced and
blocked; reads are not blocked while a writer holds the lock; a writer killed
abruptly (simulated crash) yields an automatically released lock, with no
permanent deadlock. Configurable via `CORTEX_WRITE_LOCK_PATH` and
`CORTEX_WRITE_LOCK_TIMEOUT_SECONDS` (`config.toml`, 30 s by default).

## Logs without sensitive content

The local logs (`%LOCALAPPDATA%\Cortex\logs\cortex.log`, rotation 5 MB x 5)
never contain document or chunk text: only paths, statuses, errors and
operational counters. The user configuration (`config.toml`) never contains a
secret.

## Scope and limits

Cortex protects the availability and integrity of its local index. It does not
encrypt the store at rest: on a machine where confidentiality requires it, the
local copy must be protected by disk encryption (BitLocker or equivalent).
Cortex also does not handle MCP client authentication: that is each client's
responsibility.
