# Release notes

[Francais](../fr/notes-de-version.md) | **English**

[Back to the table of contents](index.md)

This page summarizes user-visible changes. See the
[technical changelog](../../CHANGELOG.md) for complete details.

<!-- release:2026-0827-00 -->
## 2026.0827.00 - 2026-08-27

- Adding a Confluence page now accepts the address recent Confluence versions
  show in the browser, of the `/spaces/SPACE/pages/ID/Title` form. Looking up
  the numeric page ID by hand is no longer necessary. Every previously accepted
  form keeps working.
- Pasting the address of a space home, rather than a page, now states what is
  expected instead of reporting a plain refusal.
- When the page belongs to a space missing from the configuration file,
  Companion explains that the space must be declared there first, and that
  Companion does not create it.

<!-- release:2026-0808-00 -->
## 2026.0808.00 - 2026-08-08

- One Windows installer now provides Cortex, the offline models, and Cortex
  Companion. No separate Python or .NET runtime is required.
- Companion becomes the recommended terminal-free path: `Réglages` (Settings)
  detects Cortex and selects the document folder. In `Base locale` (Local
  knowledge base), `Synchroniser les documents locaux` (Synchronize local
  documents) starts and follows a synchronization.
- Database export, import, and rollback are deferred from this release. The
  local index is reconstructible from the Vault and configured sources by
  running a synchronization.
- Advanced Python users can install the public `cortex-local-rag` package from
  PyPI. Releases also publish the server declaration to the MCP Registry.
- The release chain builds and smoke-tests the unified installer before
  publishing packages and artifacts.

<!-- release:notice-2026-08-06 -->
## Notice - 2026-08-06 - published history rewritten

The published Cortex history was rewritten on 2026-08-06. Seven April commits
exposed a personal email address in their author and committer fields, and six
trailers exposed a second address. The addresses are intentionally not
reproduced here.

All commit identifiers changed. A clone created before 2026-08-06 now diverges
from `origin/main`. The simplest remedy is a fresh clone. Alternatively, run:

```console
git fetch origin
git reset --hard origin/main
```

Warning: `git reset --hard` destroys local modifications. Save any work that
must be retained before running it.

The rewrite changed no content bytes and introduced no behavioral change. The
121 trees remain byte-identical and in the same order, author and committer
dates are unchanged, and `git fsck` completed with exit code 0. All five tags
were repointed. The five GitHub Releases and their downloadable artifacts remain
available.

<!-- release:2026-0805-00 -->
## 2026.0805.00 - 2026-08-05

- Cortex can now produce atomic document generations, report their freshness,
  and index documents from the current published generation.
- The optional Confluence writer collects only allowlisted spaces or pages,
  preserves source artifacts, and publishes Markdown by generation.
- The writer handles empty pages, sanitizes attachment names, and batches
  conversions.
- Page selection, atomic configuration mutations, and a machine-readable CLI
  surface for external interfaces are available.
- Search metadata v2 adds structured filters and a reversible migration with
  backup and restore support.
- Antigravity and LM Studio join the MCP clients detected by setup.
- The installer closes the application before replacement and refuses to
  continue if compilation fails. Setup prompts explain their effects more
  clearly.
- MCP dependencies address CVE-2026-52869, CVE-2026-52870, and CVE-2026-59950.
  Releases provide checksums and a provenance attestation.
- A FAQ, public specification, and the FR/EN guides cover these new workflows.

<!-- release:2026-0716-01 -->
## 2026.0716.01 - 2026-07-16

- The Windows installer includes a pinned offline model payload.
- The runtime verifies the model manifest before loading it.

<!-- release:2026-0716-00 -->
## 2026.0716.00 - 2026-07-16

- Documentation now leads with the Windows installer and standalone binaries.
- Setup registers MCP clients before initial indexing. An indexing failure no
  longer cancels client registration.
- The packaged runtime uses the operating system certificate store, including
  enterprise certificate authorities.

<!-- release:2026-0715-01 -->
## 2026.0715.01 - 2026-07-15

- A Windows Inno Setup installer is available.
- Whole-folder indexing becomes the default choice.
- Reinstallation can preserve or reset existing Cortex state.
- `cortex unregister` removes Cortex entries from MCP clients.

<!-- release:2026-0715-00 -->
## 2026.0715.00 - 2026-07-15

Initial public release: local multilingual search, hybrid vector and lexical
indexing, incremental synchronization, MCP tools, setup and diagnostics, FR/EN
documentation, and standalone binaries.
