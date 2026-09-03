# Release notes

[Francais](../fr/notes-de-version.md) | **English**

[Back to the table of contents](index.md)

This page summarizes user-visible changes. See the
[technical changelog](../../CHANGELOG.md) for complete details.

<!-- release:2026-0903-02 -->
## 2026.0903.02 - 2026-09-03

- Cortex Companion can authorize a new Confluence space from the `Pages`
  screen. Paste the URL of any page of the space, pick its classification, and
  confirm; editing `confluence.toml` by hand is no longer the only way. Only
  the first-run screen could do this before, and it disappears once the file
  exists.
- Adding a page from a space that is not authorized yet no longer stops at an
  error. The card is filled in with the URL you just pasted, names the space it
  would authorize, and confirming adds your page in the same gesture.
- Error messages no longer end with the log lines Cortex wrote while it worked.
  Only the sentence meant for you is shown.

<!-- release:2026-0903-01 -->
## 2026.0903.01 - 2026-09-03

- The synchronization report now counts documents with no indexable body. A
  page that holds only a Confluence children macro, or no text at all, used to
  be reported as skipped alongside unchanged files and logged nowhere. It now
  has its own counter and its own log line, so you can find it.
- Cortex Companion stops watching a synchronization run when the screen that
  watches it is replaced. The abandoned screen used to keep reading local state
  in the background.
- Cortex Companion renames three theme colors so each one matches the brush
  that reads it. No visible change.

<!-- release:2026-0903-00 -->
## 2026.0903.00 - 2026-09-03

- A command-line usage error, such as a mistyped flag, now exits with the
  invalid-input code (6). It used to exit with 2, which Cortex Companion reads
  as "another operation holds the index".
- `cortex sync --search` no longer stops on a Windows console that cannot
  display a character from your notes, such as an emoji. The character is
  written as an escape sequence and the rest of the listing follows.
- Cortex Companion drops nine interface strings that no screen displayed. No
  visible change.

<!-- release:2026-0902-01 -->
## 2026.0902.01 - 2026-09-02

- Cortex Companion opens normally again. Version `2026.0902.00` could stop
  before displaying its window because of an invalid progress-bar binding.
- If an unexpected startup failure happens, the dialog now includes the
  exception type and message as well as the local log directory.
- The release gate now opens the complete Companion window so this class of WPF
  runtime failure is caught before publication.

<!-- release:2026-0902-00 -->
## 2026.0902.00 - 2026-09-02

- The Confluence token can no longer leave the instance you chose. An HTTP
  redirect to another host is now refused instead of being followed with the
  authentication header attached.
- The Confluence address must now use `https`, except for a local test instance.
  A cleartext address exposed the token on the network. Companion says so as
  soon as you paste the first page URL.
- Companion can finally stop a running collection. The `Interrompre` button asks
  for confirmation, states what will happen, then stops the operation. The
  already published generation stays intact.
- Closing Companion during a run now asks for confirmation and reminds you that
  the operation keeps running in the background.
- `Collecter Confluence` moved up onto the main card of `Base locale`, next to
  local synchronization, instead of hiding under the advanced options.
- `F5` reloads the current screen and `Ctrl+S` saves from Settings. The shortcut
  appears in the button tooltip.
- Companion borders are easier to see: their contrast fell below the
  accessibility floor on highlighted rows.
- `cortex --help` now describes every subcommand, and `cortex sync --help` prints
  a usage line you can copy as it stands.
- `cortex setup --kb-path` makes a prompt-free installation possible without
  setting an environment variable first.

<!-- release:2026-0901-05 -->
## 2026.0901.05 - 2026-09-01

- When a page URL is pasted, Companion now counts the page-only, subtree, and
  whole-space scopes before saving the choice. When descendants exist, subtree
  collection is selected and recommended by default.
- Every choice shows its page count, estimated storage, physical location, and
  configured retention. The `target` field is identified as a logical prefix,
  with an action to open the current generation directory.
- A manual collection always starts immediately. Changing the effective scope
  also invalidates cadence for automated invocations.
- During long collections, Companion displays the current phase and numeric
  progress. After collection, an overly narrow scope reports excluded
  descendants and offers a one-click subtree correction.
- A `failure_threshold` rejection now explains the failed count and rate, the
  configured threshold, and recovery choices. Old orphaned Confluence temporary
  directories are swept conservatively at startup.

<!-- release:2026-0901-04 -->
## 2026.0901.04 - 2026-09-01

- This replacement build publishes the Confluence fixes from `2026.0901.03`,
  whose build was blocked before publication.
- The installer supplies the console converter automatically, and Companion
  repairs existing configurations without asking users for a path.
- The release now verifies the converter source, tests, and `--probe`
  capability locally before adding it to the installer.

<!-- release:2026-0901-03 -->
## 2026.0901.03 - 2026-09-01

- The installer now provides the actual windowless Confluence console
  converter. A standard installation no longer asks for a converter path.
- Companion verifies the converter in under five seconds before saving it. The
  windowed `ConfluenceRAGBuilder.exe` is rejected immediately instead of
  opening a window and waiting without a result.
- Existing schema-v2 `confluence.toml` files that omit `console_path` are
  repaired automatically and atomically on first load.
- Failures record the effective converter path in diagnostics, and every
  `cortex-confluence-*` temporary workspace is removed on exit.

<!-- release:2026-0901-02 -->
## 2026.0901.02 - 2026-09-01

- The timeout selected in `Réglages` (Settings) now applies to every short CLI
  command launched by Companion: connection, Cortex configuration reads, and
  Confluence page management.
- On a slow computer, selecting 60 or 120 seconds and then `Enregistrer et
  connecter` (Save and connect) prevents Companion from terminating
  `cortex.exe` while it is still starting.
- A real timeout now provides a clear explanation and recovery action instead
  of the misleading `CLI refused the read` message.
- Existing settings are reused automatically; the update does not require the
  user to re-enter TOML configuration or the PAT.

<!-- release:2026-0901-01 -->
## 2026.0901.01 - 2026-09-01

- Initial Confluence setup now happens directly in `Pages Confluence`. Paste a
  page URL, choose the PAT expiry date and classification, then select
  `Initialiser et ajouter la page` (Initialize and add the page).
- Companion detects the instance address and space key from URLs that expose
  them. Legacy `viewpage.action` URLs and short links remain accepted; enter the
  Confluence space key when those links do not contain it.
- `confluence.toml` is created through the locked, validated, atomic writer. The
  PAT remains only in the DPAPI-protected Windows Credential Manager and is
  never written to that file.
- The external converter can be selected on the same screen. It is optional for
  managing pages but still required to collect them.

<!-- release:2026-0901-00 -->
## 2026.0901.00 - 2026-09-01

- The Confluence PAT can now be saved on first use, before `confluence.toml` is
  created. Companion then uses Cortex's matching default Windows target,
  `cortex-spike`.
- Until `confluence.toml` exists, page additions stay disabled and the screen
  explains the prerequisite instead of launching a command that cannot
  resolve a page. Refreshing the screen enables the action once the file is
  created.
- Incomplete configuration is now reported as invalid with useful detail such
  as a missing `base_url` or `auth_expires_at`, instead of the generic "CLI
  refused the read" message.

<!-- release:2026-0831-01 -->
## 2026.0831.01 - 2026-08-31

- `Settings > Confluence authentication` now provides a masked field for the
  Personal Access Token (PAT). Configure Confluence first, then save the PAT
  before the first collection or whenever the token is rotated.
- Companion reads the configured `credential_target` and stores the PAT for
  the current Windows account in Windows Credential Manager, protected by
  DPAPI. The secret is never written to Companion settings, the Confluence
  TOML file, or logs.
- The terminal command `cortex confluence store-credential` remains available
  for command-line administration and uses the same credential entry.

<!-- release:2026-0831-00 -->
## 2026.0831.00 - 2026-08-31

- On a slow computer, `Réglages` (Settings) now lets you choose how long
  Companion waits for Cortex to start: 15, 30, 60, or 120 seconds. The default
  is 30 seconds.
- Cortex version verification no longer loads the offline models. Initial
  connection is therefore faster, while a longer timeout remains available for
  computers where Cortex needs more time to start.
- If Cortex still does not answer before the selected limit, Companion stays
  read-only and the Pages screen does not launch Cortex a second time.

<!-- release:2026-0827-03 -->
## 2026.0827.03 - 2026-08-27

- Fix: the Pages screen reported an invalid response as soon as a space used
  the subtree mode, because its roots never reached the interface. Update
  before using the subtree mode introduced in 2026.0827.02.

<!-- release:2026-0827-02 -->
## 2026.0827.02 - 2026-08-27

- A third collection mode arrives: the subtree. Each listed page becomes a
  root, and Cortex also collects every page below it. Useful when you want a
  whole branch of a space without taking the complete space.
- The tree is resolved at every collection rather than frozen in the file, so
  pages added later under a root are picked up on their own.
- In Companion, the mode button now cycles through all three modes: whole
  space, then explicit pages, then subtree. Moving from pages to subtree turns
  the pages you already listed into the roots.
- A subtree root is removed the same way any explicit page already was.

<!-- release:2026-0827-01 -->
## 2026.0827.01 - 2026-08-27

- A "Forcer la collecte" (Force collection) checkbox now starts a Confluence
  collection without waiting for the schedule Cortex applies. A collection that
  had already succeeded inside the interval used to block the button until the
  schedule elapsed, with no way out from the interface.
- The message shown in that case now explains what is happening and points at
  the checkbox, instead of presenting a bare exit code next to genuine
  failures.

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
