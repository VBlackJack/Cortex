# Standalone distribution

[Francais](../fr/distribution.md) | **English**

[Back to table of contents](index.md)

Cortex can be delivered as one standalone executable containing both the CLI
and the MCP stdio server. The executable does not require Python on the target
machine.

## Command model

The same binary exposes the complete command surface:

```text
cortex setup
cortex unregister
cortex sync
cortex doctor
cortex serve
```

`cortex serve` is the MCP server entry point. Users normally do not launch it
directly: when `cortex setup` runs from the standalone executable, it registers
the current executable with `serve` as its argument in every selected client.

The Python installation remains supported. In that mode, setup continues to
register the current Python interpreter with `server.py`; existing development
and pip workflows are unchanged.

## Install on Windows

For non-technical users, download `Cortex-Setup.exe` from the release. The
wizard installs Cortex without administrator privileges, collects the document
folder, adds the binary to PATH, and registers the MCP clients. See the
[Windows installation guide](windows-install.md).

The raw Windows binary remains available for portable or advanced use.

## Install a released raw binary

1. Download the binary for your operating system from the matching GitHub
   Release.
2. Put it in a stable location that will not be renamed or deleted.
3. On Linux or macOS, make it executable with `chmod +x cortex-*`.
4. Run `cortex setup` from that binary, then restart the registered MCP clients.

The setup is user-scoped. Project-scoped MCP registration is intentionally not
part of Cortex.

The first index or server startup may download the configured embedding and
reranker models into the FastEmbed cache. Network access is therefore required
once for an empty model cache. Knowledge-base content and the resulting index
remain local.

## Build locally

Install Cortex with the optional build dependency:

```powershell
python -m pip install -e ".[build]"
```

On Windows:

```powershell
./scripts/build_installer.ps1 -Clean
```

On Linux or macOS:

```bash
./scripts/build_installer.sh --clean
```

Both scripts create a PyInstaller one-file executable under `dist/`. The binary
bundles ChromaDB, FastEmbed, ONNX Runtime, Tokenizers and the Cortex modules, so
it is substantially larger than a simple Python CLI. The model files themselves
are not bundled.

## Release workflow

Pushing a `v*` tag starts `.github/workflows/release.yml`. It builds on Windows,
macOS arm64 and Linux x64, smoke-tests the CLI and server imports, and attaches
the three binaries to the GitHub Release. `workflow_dispatch` can build the same
artifacts without publishing a release.
The Windows leg also compiles `Cortex-Setup.exe` with Inno Setup and attaches it
to the release. When the Windows signing secrets are configured, the workflow
signs the Windows binary before packaging and then signs the resulting installer.
The publish job generates `SHA256SUMS` for every artifact and creates a GitHub
build provenance attestation before publishing the release once.

The release job must never publish a binary from a failed platform build or a
failed smoke-test.
