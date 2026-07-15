# Windows installation

[Francais](../fr/installation-windows.md) | **English**

[Back to table of contents](index.md)

The Windows installer is the recommended way to use Cortex without Python or a
terminal. It installs the binary at user scope, adds Cortex to PATH, and
configures the supported MCP clients.

## Guided installation

1. Download `Cortex-Setup.exe` from the matching
   [GitHub Release](https://github.com/VBlackJack/Cortex/releases).
2. Double-click the installer. Until the binary is signed, SmartScreen may show
   an unknown-publisher warning. Verify that the file came from the official
   release before selecting `More info`, then `Run anyway`.
3. Choose the knowledge-base folder. The default is
   `%USERPROFILE%\Documents\Cortex-KB`; it may start empty.
4. Keep `Index everything in this folder` so documents at the root or in any
   subfolder become searchable. The advanced `Organize into sections` mode
   limits indexing to named folders; its defaults are `knowledge` (reference),
   `projects` (work), and `notes` (free-form notes).
5. Keep `Index this folder now` selected for an initial index, or clear it to
   finish faster and synchronize later.
6. Restart the registered AI applications when installation completes.

Installation does not require administrator privileges. Cortex is installed
under `%LOCALAPPDATA%\Programs\Cortex`. New terminals opened after installation
can resolve the `cortex` command through PATH.

The first synchronization containing documents may download the FastEmbed/ONNX
models. Network access is required once when their cache is empty. The corpus
and generated index remain local.

## Terminal-free use

Two shortcuts are added to the Start menu:

- `Cortex Sync` indexes new documents and keeps the console open to show the
  result.
- `Cortex Doctor` validates the installation and also keeps its result visible.

## Silent installation

For automated per-user deployment:

```powershell
Cortex-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /KBPATH="C:\Docs\Cortex-KB"
```

Silent mode creates the folder when needed, installs Cortex, and registers the
clients, but does not index immediately. Add `/INDEX` to force the first index
during deployment:

```powershell
Cortex-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /KBPATH="C:\Docs\Cortex-KB" /INDEX
```

Silent mode defaults to `/INDEXMODE=whole`. For advanced sections:

```powershell
Cortex-Setup.exe /VERYSILENT /KBPATH="C:\Docs\Cortex-KB" /INDEXMODE=sections /SECTIONS="knowledge,projects,notes"
```

The process returns a non-zero exit code if automatic setup fails.

## Uninstallation

Uninstall Cortex from `Settings > Apps`. The uninstaller runs
`cortex unregister --yes --clients all` before deleting the binary, then removes
only its entry from the user PATH.

The Cortex configuration, index, and document folder are preserved so that an
uninstall never destroys user data.
