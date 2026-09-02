# Security

[Francais](../fr/security.md) | **English**

[Back to table of contents](index.md)

## Local runtime and bounded network access

All Chroma clients are built with `Settings(anonymized_telemetry=False)`: no
Chroma/PostHog telemetry is emitted. Cortex does not upload knowledge-base
content during indexing or search. The optional Confluence writer performs
authenticated HTTPS reads only against the configured origin and explicit
space allowlist. The verified Windows installer bundles the models and operates
offline; a source installation or standalone binary may contact Hugging Face
when a model is absent from the local cache. MCP clients remain distinct
products: depending on their policy, they may pass requested tool results to
the model.

## Confluence credential boundary

The Confluence PAT is entered through `getpass` and stored as a generic Windows
Credential Manager entry for the current task account. It is never accepted as
a CLI argument, environment variable, or TOML value. Secret wrappers redact
both string representations, and logs contain only target names and error
types.

Cortex checks the declared `auth_expires_at` before a scheduled attempt. An
expired or unreadable credential prevents publication and preserves the
previous generation. Remote revocation remains a Confluence-server contract:
Cortex observes rejection on the next authenticated request and does not keep a
second token cache.

## Confluence PAT transport

The PAT travels as an `Authorization: Bearer` header on every request, so two
rules bound its transport.

`base_url` must use `https`. A remote `http` origin is refused at configuration
validation, in Cortex and in Companion alike, because it would publish the token
in clear text on the network. Loopback hosts (`localhost`, `127.0.0.1`, `::1`)
stay allowed over `http`: no packet leaves the machine.

No HTTP redirect leaves the chosen origin. The default urllib opener replays
every request header, `Authorization` included, to whatever host a redirect
names. The Cortex transport therefore resolves redirects itself: it compares the
origin of each hop with the origin of the initial request, refuses the hop when
they differ, and bounds the hop count. A compromised Confluence instance or an
intermediary cannot forward the token to a third-party origin.

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
operational counters. The user, ingestion, and Confluence TOML files never
contain a secret.

## Scope and limits

Cortex protects the availability and integrity of its local index. It does not
encrypt the store at rest: on a machine where confidentiality requires it, the
local copy must be protected by disk encryption (BitLocker or equivalent).
Cortex also does not handle MCP client authentication: that is each client's
responsibility.
