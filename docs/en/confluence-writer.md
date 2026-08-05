<!--
Copyright 2026 Julien Bombled

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
-->

# Confluence writer

[Francais](../fr/writer-confluence.md) | **English**

[Back to table of contents](index.md)

The Confluence writer enumerates an explicit space allowlist through REST v1,
downloads only new or updated pages, and runs one or more sequential
ConfluenceRAGBuilder console jobs per generation. Each job stays within the
page-count and serialized-byte limits read from the frozen schema. The common
ingestion engine owns locking, retry, atomic generations, carry-forward,
tombstones, retention, and health state.

## Configuration

The optional writer file is `%APPDATA%\Cortex\confluence.toml`. Environment
variables prefixed with `CORTEX_CONFLUENCE_` override TOML, and TOML overrides
safe defaults. No space is enabled by default.

```toml
schema_version = 2
base_url = "https://confluence.example.test"
credential_target = "cortex-spike"
auth_expires_at = "2026-11-01T00:00:00+01:00"
console_path = "C:/Tools/ConfluenceRAGBuilder.Console.exe"
max_attachment_size_mb = 50
failure_threshold = 0.10

[[spaces]]
space_key = "DOC"
target = "knowledge/confluence"
classification = "perso-non-sensible"
selection = "whole_space"

[[spaces]]
space_key = "RUN"
target = "knowledge/runbooks"
classification = "pro-confidentiel"
selection = "pages"

[[spaces.pages]]
page_id = "379465380"

[[spaces.pages]]
page_id = "379465381"
```

`classification` accepts `perso-non-sensible` or `pro-confidentiel`. A
`pro-confidentiel` target remains strictly local and must never be committed or
shared.

Schema v2 requires `selection` on every space. `whole_space` keeps the existing
enumeration path and rejects any present `pages` key or table, including an
empty one. `pages` fetches only the listed numeric page IDs. IDs must be unique
within their space, and every fetched page is checked against `space_key`
before content or attachments are staged.

An empty page selection is legal and must be explicit:

```toml
[[spaces]]
space_key = "EMPTY"
target = "knowledge/empty"
classification = "perso-non-sensible"
selection = "pages"
pages = []
```

This mode enumerates no space and collects zero Confluence pages. Removing a
page ID from a complete successful selection removes that page from the next
generation and records its existing document tombstone. A failed selected page
is counted against `failure_threshold`; it is never staged under another
space, and the common generation engine applies its existing carry-forward and
publication rules.

Schema v1 remains supported without migration. A v1 space entry has no
`selection` or `pages` field, continues to mean `whole_space`, and the file is
not rewritten while loading.

The console path, base URL, credential target, declared expiry, attachment
limit, and failure threshold also have matching uppercase
`CORTEX_CONFLUENCE_...` environment overrides. Space allowlisting stays in
TOML so an inherited environment cannot silently broaden the source scope.

## Store the PAT

Run the interactive command in a human-controlled terminal:

```powershell
cortex confluence store-credential
```

The prompt uses `getpass`; the PAT is written as a generic Windows Credential
Manager entry. It is never accepted as an argument, environment variable, or
file value, and it is never printed. `auth_expires_at` is configuration, not a
secret.

## Sync and scheduling

Metadata schema v2 is required before a real publication. The current build
declares `METADATA_SCHEMA_VERSION = 2`; the CLI still verifies that gate before
reading credentials or contacting Confluence and fails closed if a future or
older deployment does not satisfy it.

After that prerequisite is deployed, Task Scheduler may run:

```powershell
cortex confluence sync
```

Use `--force` only for an operator-requested run. Normal invocations use the
common missed-window catch-up decision. The task account needs access to its
Credential Manager entry and to the configured ingestion data root.

Declared credential expiry is checked before the writer runs. An expired or
unavailable credential records an error and leaves the previous generation
served. Remote PAT revocation is enforced by the Confluence server: Cortex
observes it on the next authenticated request, so the synchronization cadence,
not local token caching, bounds how long already indexed content can remain.

Published zone `README.md` files declare the generated content read-only for
humans. Manual edits are replaced by the next successful generation.

## Converter contract

The package vendors `job.schema.json` and `result.schema.json` byte-for-byte
from ConfluenceRAGBuilder commit
`fceda69da9246e9cf927ca7b8ad68a330f5a7b9b`. Both payloads are validated with
JSON Schema draft 2020-12. A provenance hash mismatch or payload divergence
fails closed.

The writer splits work into stable `batch-0001`, `batch-0002`, and subsequent
directories, invokes the console sequentially, and applies the failure
threshold across the whole generation. A single page whose serialized record
cannot fit the schema byte limit fails with `job_payload_too_large`; other pages
continue.

An explicitly present empty `body.storage.value` is a valid page body. A
missing, null, or non-string field still fails closed. Attachment bytes are
staged under an ID-prefixed Windows-safe name while `file_name` keeps the
original Confluence title for macro resolution. Invalid Windows characters,
reserved device names, trailing dots/spaces, and the 255-character component
limit are handled before the console starts.

Only `markdown_paths` belonging to `converted` pages are consumed. Attachments
left in the console work directory for a `failed` page never enter a published
generation.
