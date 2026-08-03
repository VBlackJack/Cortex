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

The Confluence writer enumerates an explicit space allowlist through REST v1,
downloads only new or updated pages, and runs one ConfluenceRAGBuilder console
process per generation. The common ingestion engine owns locking, retry,
atomic generations, carry-forward, tombstones, retention, and health state.

## Configuration

The optional writer file is `%APPDATA%\Cortex\confluence.toml`. Environment
variables prefixed with `CORTEX_CONFLUENCE_` override TOML, and TOML overrides
safe defaults. No space is enabled by default.

```toml
schema_version = 1
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
```

`classification` accepts `perso-non-sensible` or `pro-confidentiel`. A
`pro-confidentiel` target remains strictly local and must never be committed or
shared.

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

The metadata v2 rechunk must be deployed before the first real publication.
Until Cortex exposes that deployed contract, `cortex confluence sync` stops
before reading credentials or contacting Confluence.

After that prerequisite is deployed, Task Scheduler may run:

```powershell
cortex confluence sync
```

Use `--force` only for an operator-requested run. Normal invocations use the
common missed-window catch-up decision. The task account needs access to its
Credential Manager entry and to the configured ingestion data root.

Published zone `README.md` files declare the generated content read-only for
humans. Manual edits are replaced by the next successful generation.

## Converter contract

The package vendors `job.schema.json` and `result.schema.json` byte-for-byte
from ConfluenceRAGBuilder commit
`fceda69da9246e9cf927ca7b8ad68a330f5a7b9b`. Both payloads are validated with
JSON Schema draft 2020-12. A provenance hash mismatch or payload divergence
fails closed.

Only `markdown_paths` belonging to `converted` pages are consumed. Attachments
left in the console work directory for a `failed` page never enter a published
generation.
