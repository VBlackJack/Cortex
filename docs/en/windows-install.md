# Windows installation

[Francais](../fr/installation-windows.md) | **English**

[Back to table of contents](index.md)

The Windows installer is the recommended way to use Cortex without Python or a
terminal. The same file installs the Cortex CLI, offline models, and Cortex
Companion, the graphical interface. It adds Cortex to PATH and configures the
supported MCP clients.

## Guided installation

1. Download `Cortex-Setup.exe` and `SHA256SUMS` from the matching
   [GitHub Release](https://github.com/VBlackJack/Cortex/releases).
2. In PowerShell, run `Get-FileHash .\Cortex-Setup.exe -Algorithm SHA256`, then
   verify that the digest exactly matches the `Cortex-Setup.exe` line in
   `SHA256SUMS`.
3. Double-click only after that check. Until the binary is signed, SmartScreen
   may still show an unknown-publisher warning; then select `More info` and
   `Run anyway`.
4. Choose the knowledge-base folder. The default is
   `%USERPROFILE%\Documents\Cortex-KB`; it may start empty.
5. Keep `Index everything in this folder` so documents at the root or in any
   subfolder become searchable. The advanced `Organize into sections` mode
   limits indexing to named folders; its defaults are `knowledge` (reference),
   `projects` (work), and `notes` (free-form notes).
6. Keep `Index this folder now` selected for an initial index, or clear it to
   finish faster and synchronize later.
7. Keep `Launch Cortex Companion` selected at the end. Then restart the
   registered AI applications.

Installation does not require administrator privileges. Cortex is installed
under `%LOCALAPPDATA%\Programs\Cortex`. New terminals opened after installation
can resolve the `cortex` command through PATH.

The installer bundles Cortex Companion and FastEmbed/ONNX models verified
against its manifest. The first synchronization therefore works offline and
downloads no model. The corpus and generated index remain local.

### First Confluence configuration

After Companion connects to Cortex:

1. Save the masked Confluence PAT under `Settings`.
2. Open `Pages Confluence` and paste a full page URL.
3. Choose the PAT expiry and classification, then verify the inferred space key.
4. Optionally select the external converter when this computer must run
   collection.
5. Select `Initialiser et ajouter la page` (Initialize and add the page), then
   confirm the page.

Companion creates and validates `%APPDATA%\Cortex\confluence.toml`; manual
editing is not required. The PAT stays in the DPAPI-protected Windows
Credential Manager and is never copied into TOML.

## Terminal-free use

Cortex Companion is added to the Start menu and opens after a guided install.
For first use:

1. Open `Réglages` (Settings). Companion normally detects the `cortex.exe`
   installed in the parent folder of the same Cortex installation. If the path
   needs correction, select
   `%LOCALAPPDATA%\Programs\Cortex\cortex.exe`, then
   `Enregistrer et connecter` (Save and connect).
   On a slow computer, also select a 15, 30, 60, or 120 second startup timeout;
   the default is 30 seconds. This timeout applies only to the startup
   compatibility check. If it expires, Companion remains read-only rather than
   running actions against an unconfirmed Cortex process.
2. Verify the `Dossier de la base de connaissances` (Knowledge-base folder).
   To change it, choose an existing folder, then select `Enregistrer le dossier`
   (Save folder).
3. Add documents to that folder.
4. Open `Base locale` (Local knowledge base), then select
   `Synchroniser les documents locaux` (Synchronize local documents). The
   screen remains
   available to follow the result and inspect details if the operation fails.

Two technical shortcuts remain available in the Start menu:

- `Cortex Sync` indexes new documents and keeps the console open to show the
  result.
- `Cortex Doctor` validates the installation and also keeps its result visible.

## Silent installation

For automated per-user deployment:

```powershell
Cortex-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /KBPATH="C:\Docs\Cortex-KB"
```

Silent mode creates the folder when needed, installs Cortex and Companion, and
registers the clients, but does not launch Companion or index immediately. Add
`/INDEX` to force the first index during deployment:

```powershell
Cortex-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /KBPATH="C:\Docs\Cortex-KB" /INDEX
```

Silent mode defaults to `/INDEXMODE=whole`. For advanced sections:

```powershell
Cortex-Setup.exe /VERYSILENT /KBPATH="C:\Docs\Cortex-KB" /INDEXMODE=sections /SECTIONS="knowledge,projects,notes"
```

The process returns a non-zero exit code if automatic setup fails.

## Reinstall and reset

When `%APPDATA%\Cortex\config.toml` already exists, the wizard offers two
choices:

- `Keep my current configuration` is the conservative default. The existing
  folder, mode, and index stay intact; Cortex reindexes and registers clients.
- `Reset configuration` removes only Cortex's configuration and generated data
  under `%LOCALAPPDATA%\Cortex`, then applies the folder and mode selected in
  the wizard. The document folder is never deleted.

Close AI applications before a reset: an active server may hold the index open
and make the operation fail safely. Silent installs still default to Keep;
`/RESETCONFIG` explicitly requests a reset:

```powershell
Cortex-Setup.exe /VERYSILENT /RESETCONFIG /KBPATH="C:\Docs\Cortex-KB" /INDEXMODE=whole /INDEX
```

## Uninstallation

Uninstall Cortex from `Settings > Apps`. The uninstaller runs
`cortex unregister --yes --clients all` before deleting the binary, then removes
only its entry from the user PATH. Companion also removes its scheduled task
only when the ownership token matches; an absent or foreign task is never
deleted.

The Cortex configuration, local Companion settings, index, and document folder
are preserved so that an uninstall never destroys user data.
