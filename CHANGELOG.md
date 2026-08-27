# Changelog

This file records technical changes to Cortex. User-facing summaries are
available in [French](docs/fr/notes-de-version.md) and
[English](docs/en/release-notes.md). Cortex versions follow CalVer in the
`YYYY.MMDD.PATCH` form.

## [Unreleased]

## [2026.0827.00] - 2026-08-27

### Added

- Added the `/spaces/SPACE/pages/ID/Title` page URL to the references accepted
  by `cortex confluence resolve`. The optional `/wiki` path prefix and a missing
  title slug are both accepted. Numeric page IDs, `viewpage` URLs, `/display/`
  URLs, and tiny links keep resolving unchanged. The space key carried by the
  URL is ignored on purpose: the REST answer stays the only authority on which
  space owns the page.

### Changed

- Changed the rejection message for a `/spaces/` URL that addresses no page,
  such as a space overview. It now names the expected `/pages/<numeric id>`
  shape instead of reporting a generic unsupported URL.
- Changed the Companion refusal shown when a resolved page belongs to a space
  absent from the configuration. It now states that Companion never creates a
  space and that the space must first be declared in the TOML file.

### Fixed

- Fixed six user-facing Companion messages that were written directly in the
  service code instead of the localization resources.

## [2026.0808.00] - 2026-08-08

### Added

- Added one Windows installer containing the Cortex CLI, verified offline
  models, and the self-contained Cortex Companion application.
- Added the versioned encrypted `.cortexbundle` format with `describe` and
  `verify` inspection commands.
- Added atomic `cortex config get` and `cortex config set` JSON operations for
  graphical clients.
- Added locked PyPI package publication for `cortex-local-rag` and MCP Registry
  publication to the release chain.
- Added a canonical PyInstaller builder and distribution tests that build,
  install, and import the real wheel outside the source tree.
- Added separate hash-locked runtime, development/build, and model dependency
  contracts with reproducible installation documentation.
- Added this technical changelog and bilingual user-facing release notes, linked
  from both documentation indexes and README files.
- Deferred database export, import, and rollback. The local index remains
  reconstructible from the Vault and configured sources through synchronization.

### Changed

- Made Cortex Companion the primary terminal-free Windows experience for
  configuration, synchronization, scheduling, and diagnostics.
- Made release publication build and smoke-test the unified Windows installer
  before publishing packages, registry metadata, or GitHub assets.
- Updated package metadata and the public package name to
  `cortex-local-rag`.
- Bumped the Cortex and Companion version to `2026.0808.00`.

### Security

- Made Windows credential access fail closed when native credential APIs are
  unavailable.

## Notice - 2026-08-06 - published history rewritten

The published Cortex history was rewritten on 2026-08-06 because seven April
commits exposed a personal email address in their author and committer fields,
and six trailers exposed a second address. The addresses are intentionally not
reproduced here.

All commit identifiers changed. A clone created before 2026-08-06 now diverges
from `origin/main`. Either create a fresh clone, or run:

```console
git fetch origin
git reset --hard origin/main
```

Warning: `git reset --hard` destroys local modifications. Save any work that
must be retained before running it.

The rewrite changed no content bytes and introduced no functional or behavioral
change. The 121 trees remain byte-identical and in the same order, author and
committer dates are unchanged, and `git fsck` completed with exit code 0. All
five tags were repointed. The five GitHub Releases and their 30 downloadable
assets remain available.

## [2026.0805.00] - 2026-08-05

44 commits.

### Added

- Registered Antigravity and LM Studio as user-scoped MCP clients.
- Added explanatory setup prompts and a bilingual FAQ for common installation,
  data, synchronization, and diagnostic questions.
- Added a bilingual public specification derived from the implemented MCP,
  indexing, data, and distribution contracts.
- Added fail-closed ingestion generations with locking, scheduling, credential
  handling, atomic publication, and preserved source artifacts.
- Exposed two-stage ingestion freshness through the MCP server.
- Added an incremental, allowlisted Confluence writer with credential storage,
  Markdown conversion, attachments, and atomic generation publication.
- Added structured metadata v2 for search filters and a reversible one-pass
  migration with backup and restore support.
- Added indexing of documents from the current published ingestion generation.
- Added Confluence page selection, atomic configuration mutation, and a
  machine-readable CLI surface for external consumers.
- Added release checksums and provenance attestations with pinned publication
  actions.

### Changed

- Made installer compilation fail closed and forced the running application to
  close before replacement.
- Made setup prompts more explicit for non-technical users.
- Preserved ingestion document artifacts across generation publication.
- Updated the bilingual guides to match the implemented ingestion, Confluence,
  metadata, setup, and search behavior.
- Included the setup wizard in packaged distributions.
- Aligned search candidate-budget assertions with the restored configured
  limits.
- Isolated Confluence metadata and ingestion freshness test state so technical
  gates do not depend on execution order.
- Bumped the package version to `2026.0805.00`.

### Fixed

- Restored configured search candidate-pool budgets after the metadata v2 work.
- Batched Confluence console conversion jobs instead of starting one process per
  item.
- Accepted empty Confluence storage bodies.
- Sanitized staged Confluence attachment names.
- Resolved freshness for document hits against the current published generation.

### Security

- Updated the MCP dependency line to `1.28.x` to address CVE-2026-52869,
  CVE-2026-52870, and CVE-2026-59950.

## [2026.0716.01] - 2026-07-16

5 commits.

### Added

- Added a manifest-gated offline model runtime.
- Embedded a pinned model payload in the Windows distribution and recorded its
  inventory and third-party notices.
- Added a manual model-attestation workflow and payload verification tooling.

### Changed

- Bumped the package version to `2026.0716.01`.

## [2026.0716.00] - 2026-07-16

5 commits.

### Changed

- Updated the bilingual README files to lead with the Windows installer and
  standalone binary installation paths.
- Registered MCP clients before initial indexing and made an initial indexing
  failure non-fatal to client registration.
- Bumped the package version to `2026.0716.00`.

### Fixed

- Used the operating system certificate store in packaged runtimes through
  `truststore`, including enterprise certificate authorities.

## [2026.0715.01] - 2026-07-15

5 commits.

### Added

- Added `cortex unregister` to remove Cortex MCP client entries.
- Added the Windows Inno Setup installer and its release artifact.

### Changed

- Made whole-folder indexing the default onboarding mode.
- Let reinstallations keep or reset existing Cortex state.
- Bumped the package version to `2026.0715.01`.

## [2026.0715.00] - 2026-07-15

Initial release, 62 commits. It established the local multilingual RAG MCP
server, portable configuration, incremental and freshness-aware indexing,
hybrid vector and lexical search, ONNX reranking, single-writer safety, setup
and diagnostic commands, bilingual documentation, standalone distribution,
and the CalVer release workflow.
