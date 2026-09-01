---
verified: 2026-09-01
tested_on: "CortexCompanion 2026.0901.02 / Windows / .NET 10"
---

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

### Guided initialization with Companion

When the file does not exist, open `Pages Confluence` in Companion:

1. Paste the full URL of the first Confluence page.
2. Verify the inferred space key. `viewpage.action` URLs and short links do not
   contain it, so enter it manually for those forms.
3. Choose the PAT's declared expiry date and the classification. The secure
   default is `pro-confidentiel`.
4. Optionally select `ConfluenceRAGBuilder.Console.exe`. This external converter
   is required for collection but not for managing the page list.
5. Select `Initialiser et ajouter la page` (Initialize and add the page), then
   confirm the resolved page.

Companion preserves an instance context such as `/wiki`, creates an empty
`pages` selection under `confluence/<SPACE_KEY>`, and then adds the ID confirmed
through the Cortex contract. Creation takes the mutation lock, verifies that the
file is still absent, validates the rendered result, and replaces it atomically.
The PAT never enters this file; it remains in Windows Credential Manager for the
current account.

The manual TOML below remains available for advanced configurations and
non-Windows environments.

On a slow computer, the value selected under `Réglages > Délai maximal des
commandes Cortex` (Settings > Maximum Cortex command timeout) also applies to
reading this page list and resolving a page. Select 60 or 120 seconds, then
`Enregistrer et connecter` (Save and connect), when Cortex needs several
seconds to start. Companion now reports an expired timeout explicitly instead
of describing it as a CLI read refusal.

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

Schema v3 adds `selection = "subtree"`. The `pages` table then lists subtree
roots instead of the complete page set: each root is collected together with
every current descendant page, resolved at collection time. A root with no
descendants collects exactly itself. Roots whose subtrees overlap collect each
page once. The `pages` table must be present and may be empty, exactly like the
`pages` selection, and `subtree` is refused under schema v1 and v2.

```toml
[[spaces]]
space_key = "DOC"
target = "knowledge/doc"
classification = "perso-non-sensible"
selection = "subtree"

[[spaces.pages]]
page_id = "1001"
```

Descendants are read through the CQL `ancestor` search rather than the
`content/{id}/descendant/page` endpoint, which answers HTTP 500 on measured
Kazan deployments.

Schema v1 remains supported without migration. A v1 space entry has no
`selection` or `pages` field, continues to mean `whole_space`, and the file is
not rewritten while loading.

### Atomic programmatic updates

The shared mutation API reads one byte snapshot, validates the model from those
same bytes, and uses the lowercase SHA-256 of the exact content as its CAS
token. It then acquires `<confluence.toml>.mutation.lock`, rechecks the current
bytes, writes and `fsync`s a same-directory temporary file, validates that
temporary without environment overrides, and atomically replaces the target.

An update writes the exact previous bytes to `confluence.toml.bak` before the
target replace. Initial creation writes no backup. Canonical rewriting uses
UTF-8 and LF endings; comments are not retained in the new target, but remain
available byte-for-byte in the backup. The serializer round-trips Windows
backslashes, apostrophes, and URLs with explicit ports. CAS conflict and lock
contention never fall back to last-write-wins.

This mutation lock is only for TOML writers. It is distinct from the ingestion
sync lock and the Chroma write lock. No CLI mutation command is exposed yet.

The console path, base URL, credential target, declared expiry, attachment
limit, and failure threshold also have matching uppercase
`CORTEX_CONFLUENCE_...` environment overrides. Space allowlisting stays in
TOML so an inherited environment cannot silently broaden the source scope.

## Store the PAT

Store the PAT before the first Confluence sync and repeat the operation whenever
the token is rotated. When `CONFLUENCE.toml` does not exist yet, Cortex and
Companion use the same default Windows target, `cortex-spike`. The file is still
required before adding pages or starting a collection because it supplies
`base_url`, `auth_expires_at`, and the space allowlist.

With Cortex Companion, open `Settings > Confluence authentication`, enter the
PAT in the masked field, then select `Save PAT`. Companion reads the validated
target from the Confluence configuration, or uses the default while the file is
absent, and writes the generic credential for the current Windows account
directly to Windows Credential Manager. The value is protected by DPAPI and is
never copied to Companion settings, TOML, or logs. If a later configuration
selects another target, save the PAT again for the target Companion displays.

For command-line administration, run the interactive command in a
human-controlled terminal:

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

## Machine-readable CLI

Resolve a numeric page ID, a `viewpage` URL, a `/spaces/SPACE/pages/ID/Title`
URL, a `/display/SPACE/Title` URL, or a Kazan `/x/KEY` tiny link:

```powershell
cortex confluence resolve "https://kazan.example.test/display/DOC/Run+Book" --json
```

On success, stdout contains exactly one JSON document. Errors and logs never
share stdout with this contract:

```json
{
  "contract_version": 1,
  "page_id": "379465380",
  "title": "Run Book",
  "space_key": "DOC",
  "configured": true
}
```

`configured` is true for a page in an allowlisted `whole_space` mapping. For a
`pages` mapping, it is true only when that page ID is already listed. A page
resolved in a non-allowlisted space is refused.

List the configured spaces, explicitly selected pages, locally known titles,
and global sync state without network or credential access:

```powershell
cortex confluence pages --json
```

```json
{
  "contract_version": 1,
  "spaces": [
    {
      "space_key": "RUN",
      "selection": "pages",
      "target": "knowledge/runbooks",
      "classification": "pro-confidentiel",
      "pages": [
        {"page_id": "379465380", "title": "Run Book"},
        {"page_id": "379465381", "title": null}
      ]
    }
  ],
  "last_sync": {
    "last_success_at": "2026-08-05T10:00:00Z",
    "status": "ok",
    "error_code": null
  }
}
```

For `whole_space`, `pages` is `null`. Without a current generation, configured
page titles are `null`; without source health, all three `last_sync` fields are
`null`.

The process exit contract is stable and does not require parsing human text:

| Code | Meaning |
|---:|---|
| `0` | Success, including a published sync or valid JSON result |
| `1` | General or configuration error |
| `2` | Ingestion sync lock already held |
| `3` | Sync not due |
| `4` | Credential unavailable/expired or remote authentication rejected |
| `5` | Network or Confluence REST failure |
| `6` | Invalid `resolve` input |
| `7` | Page not found |
| `8` | Resolved page outside the space allowlist |

Codes `0`, `1`, and `3` retain their existing meanings. All failures remain
non-zero for Task Scheduler, while dedicated codes expose actionable causes.

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
