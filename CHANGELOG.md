# Changelog

This file records technical changes to Cortex. User-facing summaries are
available in [French](docs/fr/notes-de-version.md) and
[English](docs/en/release-notes.md). Cortex versions follow CalVer in the
`YYYY.MMDD.PATCH` form.

## [Unreleased]

## [2026.0902.00] - 2026-09-02

### Security

- Stopped the Confluence bearer credential from ever reaching an origin the
  operator did not choose. The default urllib opener follows a redirect to any
  host and replays every request header, `Authorization` included, so the
  transport now resolves redirects itself, compares each hop against the origin
  of the initial request, refuses a hop that changes origin, and bounds the hop
  count.
- Required `https` for `base_url` outside loopback, in the Cortex configuration
  model, in the Companion TOML parser, and at the moment a page URL is pasted
  into Companion. The PAT rides every request as a bearer header, so a cleartext
  remote origin published it on the network.
- Declared a read-only default `GITHUB_TOKEN` scope on the Cortex `ci` and
  `release` workflows, so a job that omits its own block cannot write.
- Added a `dotnet list package --vulnerable --include-transitive` gate to the
  Cortex Companion workflow, matching the pip-audit gate on the Cortex side.

### Added

- Added a Companion action that stops a running collection. It confirms first,
  states the exact consequence, then terminates the detached worker and the
  Cortex process it owns. Termination reaches only the worker whose recorded
  process identity still matches, so a reused process identifier is never
  killed, and the run is recorded as stopped rather than failed.
- Added a confirmation before the Companion window closes during a run, because
  the detached worker outlives the window and only the progress display is lost.
- Added `F5` on every Companion screen and `Ctrl+S` on Settings, with the
  shortcut shown in the button tooltip.
- Added a per-subcommand description to `cortex --help` and made every
  subcommand parser carry its own program name, so `cortex sync --help` prints
  `usage: cortex sync` instead of a usage line the user cannot type.
- Added `cortex setup --kb-path`, so a prompt-free installation no longer
  requires setting `CORTEX_KB_PATH` in the environment first.
- Added `README.fr.md` to Cortex Companion, mirroring the English README.
- Added guards for the invariants this release established: a dependency policy
  test binding the suppressed advisories to the audited chromadb pin, a function
  length ratchet, a design-token test refusing raw layout values in views, a
  localization test refusing a string that silently renders its own key, and a
  non-text contrast test for borders and focus rings.

### Changed

- Moved the Companion Confluence collection action onto the main card of the
  local knowledge base screen, next to local synchronization. It previously sat
  inside a collapsed advanced drawer while the documentation presented it as a
  main step.
- Rendered every Companion label and value as a single formatted string instead
  of separate text blocks glued with punctuation, so a narrow window can no
  longer separate a value from its label and screen readers stop announcing the
  separators.
- Moved the last raw layout values in the Companion views into named theme
  tokens, and made the card style use the border token rather than a spacing
  token, which had been giving every card a four-pixel frame.
- Moved the Confluence transport timeout and response size bound into
  `confluence_writer/constants.py`.
- Extracted the search hit renderer out of the `cortex_search` MCP tool.

### Fixed

- Fixed a Companion border that sat at 2.51:1 against highlighted rows, below
  the WCAG 1.4.11 non-text floor of 3:1. The border color now clears 3:1 against
  every surface a bordered container uses.
- Stated in the Companion diagnostics panel that the raw stream is the Cortex
  command line output and is in English, inside an otherwise French interface.
- Configured Cortex logging only once `cortex sync` arguments have parsed, so
  rendering help or reporting a usage error no longer installs a process-wide
  log handler on the way out.

## [2026.0901.05] - 2026-09-01

### Added

- Added `cortex confluence preview <reference> --json`, which resolves the root,
  counts the page-only, subtree, and whole-space choices, estimates their local
  storage, and reports the physical ingestion root and generation retention.
- Added versioned stderr progress records for enumeration, staging, conversion,
  and publication. Companion displays the phase and `current/total`, and shows a
  separate indeterminate indexing phase for local document synchronization.
- Added per-space scope summaries to `confluence pages --json` contract v2 so
  Companion can expose excluded descendants and offer a one-click subtree fix.
- Added a validated Companion action that opens the current immutable generation
  documents directory and explains that `target` is a logical index prefix.

### Changed

- Made subtree the default measured choice when a pasted root has descendants;
  page-only and whole-space collection remain explicit choices with page and
  storage estimates before the configuration write.
- Made every manual Companion collection force an immediate run. Scheduled runs
  still honor cadence, while a changed canonical selection fingerprint also
  makes Cortex due without waiting for the previous interval.
- Exposed the configured generation retention and physical storage root in
  Companion. The existing atomic publisher continues to prune older generations
  to the configured bound.
- Constrained ingestion source kinds to the `doc` enum and made unknown on-disk
  source directories produce an invalid freshness entry instead of a false empty
  report.

### Fixed

- Made a successful narrow `pages` collection report how many descendants were
  excluded instead of presenting the page count without its measured scope.
- Made failure-threshold rejection state the failed and requested counts, actual
  rate, configured threshold, preserved previous generation, and recovery choices.
- Added a conservative startup sweep for direct, non-link
  `%TEMP%\cortex-confluence-*` workspaces left orphaned for at least 24 hours.

## [2026.0901.04] - 2026-09-01

### Changed

- Made the Windows release independent of private cross-repository checkout
  permissions by pinning the minimal Confluence console 1.2.0 source archive
  in-tree with its SHA-256 and Apache-2.0 license.
- The release workflow now verifies that archive, rebuilds and tests its Core
  and Console projects, and probes the published executable before embedding
  it. This is the publishable replacement for the failed `2026.0901.03`
  pipeline and contains all of that version's user-facing fixes.

## [2026.0901.03] - 2026-09-01

### Added

- Embedded the self-contained `ConfluenceRAGBuilder.Console.exe` 1.2.0 payload
  and its license under the stable Windows installation path
  `Converters\ConfluenceRAGBuilder.Console.exe`.
- Added a five-second JSON capability probe used by Companion and Cortex before
  any converter path is accepted or any conversion job is launched.

### Changed

- Made `console_path` optional for installed Windows builds. Cortex resolves the
  embedded converter by default; the TOML and environment values remain
  developer overrides.
- Made Companion populate new configurations with the embedded path and
  atomically repair existing schema-v2 configurations that omitted it.
- Accepted `confluence` as a user-facing alias for the canonical `doc`
  ingestion health source while rejecting unknown source names.

### Fixed

- Rejected the windowed `ConfluenceRAGBuilder.exe` before it can open and block
  a collection without producing `result.json`.
- Added the effective converter path and stable refusal reason to diagnostics,
  and deterministically removes `cortex-confluence-*` workspaces on success or
  failure.

## [2026.0901.02] - 2026-09-01

### Changed

- Applied Companion's selected 15, 30, 60, or 120 second CLI timeout to the
  compatibility handshake, Cortex configuration operations, and Confluence
  page reads and resolutions. Existing settings remain compatible with the
  persisted property used by previous releases.
- Added configured and elapsed durations to timeout logs without recording CLI
  arguments, paths, or secrets.

### Fixed

- Removed the hidden five-second Confluence read limit and fifteen-second
  Cortex configuration limit that could terminate the bundled CLI on slower
  Windows computers even when the user had selected 120 seconds.
- Replaced the misleading `Le CLI a refusé la lecture` timeout path with an
  explicit message that directs the user to increase the shared limit in
  Settings.

## [2026.0901.01] - 2026-09-01

### Added

- Added a guided Confluence first-run card to Cortex Companion. A user can paste
  one supported page URL, declare the PAT expiry and classification, optionally
  select the external converter, and initialize the space allowlist without
  editing TOML.
- Added local inference for every page URL form already accepted by Cortex,
  including modern `/spaces/.../pages/...`, `/display/...`, legacy
  `viewpage.action`, and short `/x/...` links while preserving a `/wiki` context
  path.

### Security

- Kept the PAT exclusively in the DPAPI-protected Windows Credential Manager.
  The generated configuration contains only non-secret metadata and starts from
  the fail-closed `pro-confidentiel` classification.
- Reused the existing mutation lock, validation round-trip, exact absence check,
  and atomic replacement for first-file creation.

### Fixed

- Removed the first-run dead end where Companion told non-technical users to
  initialize `confluence.toml` manually before the Pages screen could work.

## [2026.0901.00] - 2026-09-01

### Changed

- Allowed Cortex Companion to save a Confluence PAT before `confluence.toml`
  exists by using Cortex's canonical `cortex-spike` Windows credential target.
- Kept page mutations disabled until `confluence.toml` exists, with an explicit
  prerequisite instead of launching a child CLI process that cannot resolve a
  page yet.

### Fixed

- Classified incomplete Confluence configuration as invalid input (exit code
  6), so Companion no longer reports the generic "CLI refused the read" error
  when `base_url` or `auth_expires_at` is missing.
- Isolated section-policy tests from the operator's `index_whole_folder`
  setting so the release suite is deterministic on configured workstations.

## [2026.0831.01] - 2026-08-31

### Added

- Added a masked Confluence PAT field to Companion Settings. Once a valid
  Confluence configuration exists, users can store or rotate the credential
  without opening a terminal.

### Security

- Stored the PAT directly in the DPAPI-protected Windows Credential Manager
  entry named by the validated `credential_target`. The current Windows
  account owns the generic credential; Companion never writes the secret to
  its settings, the Confluence TOML file, or application logs.

### Fixed

- Made the Confluence force-collection test await the complete asynchronous
  command before deleting its temporary configuration, removing an
  intermittent locked-file failure from the Windows release gate.

## [2026.0831.00] - 2026-08-31

### Added

- Added a bounded Cortex startup timeout setting to Companion. Users can choose
  15, 30, 60, or 120 seconds; 30 seconds is the default for both new and legacy
  settings, and unsupported stored values fall back to that default.

### Changed

- Changed the packaged `cortex --version` path so it returns the public version
  before truststore setup or offline-model verification. Companion no longer
  pays the model bootstrap cost merely to verify that Cortex is compatible.
- Separated the configurable startup handshake timeout from the five-second
  timeout used by Companion's Confluence read operations.

### Fixed

- Prevented the Pages screen from launching Cortex a second time after a failed
  startup handshake has already placed Companion in read-only mode.

## [2026.0827.03] - 2026-08-27

### Fixed

- Fixed `confluence pages --json` reporting a null page table for a subtree
  space. The contract now lists the configured roots, as it already did for the
  explicit page selection. Graphical clients validate a non-null table for both
  modes, so the Pages screen rejected the whole document as invalid JSON as
  soon as one space used the subtree mode shipped in 2026.0827.02.

## [2026.0827.02] - 2026-08-27

### Added

- Added Confluence schema v3 and its `selection = "subtree"` collection mode.
  The `pages` table then lists subtree roots: each root is collected together
  with every current descendant page, resolved at collection time rather than
  frozen in the file. Roots whose subtrees overlap collect each page once, and
  the table may be empty exactly like the `pages` selection.
- Added `ConfluenceRestClient.enumerate_subtree`, which reads descendants
  through the CQL `ancestor` search. The documented
  `content/{id}/descendant/page` endpoint answers HTTP 500 on measured Kazan
  deployments and is deliberately not used.
- Added ancestry-aware `configured` reporting to `confluence resolve`. In a
  subtree space a page counts as configured when it is a root or descends from
  one; a root still answers without any extra request.

### Changed

- Changed the Companion mode switch from a two-state toggle to a three-state
  cycle: whole space, then explicit pages, then subtree. Explicit identifiers
  survive the pages-to-subtree step and become the roots whose descendants the
  next collection adds. Every other step clears the list, and the typed
  space-key confirmation names the target mode.
- Changed Companion page removal so a subtree root can be removed the same way
  an explicit page identifier already could.

## [2026.0827.01] - 2026-08-27

### Added

- Added a Companion toggle that forces one Confluence collection past the
  Cortex due interval. A collection that had already succeeded inside the
  interval previously left the screen with no way to collect again until the
  schedule elapsed, because the worker never passed `--force`.

### Changed

- Changed the Companion message for exit code 3 on a Confluence collection. It
  now states that nothing is due, names the schedule as the reason, and points
  at the force toggle. The exit code is kept at the end of the sentence for
  support, instead of leading the message like a failure.

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

### Security

- Accepted three further chromadb advisories in the dependency audit gate:
  CVE-2026-45830, CVE-2026-45831, and CVE-2026-45833. They join the already
  accepted PYSEC-2026-311. Every one of them requires the chromadb HTTP server,
  its tenants, or its authorization provider, and Cortex embeds
  `PersistentClient` only. Chromadb 1.5.9 carries the same advisories, so no
  upgrade closes them. The ignores are removed once a fixed release ships.

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
