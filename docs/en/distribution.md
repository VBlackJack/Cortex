# Standalone distribution

[Francais](../fr/distribution.md) | **English**

[Back to table of contents](index.md)

Cortex can be delivered as a standalone ZIP archive. It contains one executable
providing both the CLI and the MCP stdio server, plus the exact licenses for its
embedded dependencies. The executable does not require Python on the target
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

The `cortex-windows-x64.zip` archive remains available for portable or advanced
use.

## Install a released standalone archive

1. Download the archive for your operating system and `SHA256SUMS` from the
   matching GitHub Release, then verify its SHA-256 digest.
2. Extract the complete archive into a stable location that will not be renamed
   or deleted. Keep the `licenses` folder beside the binary.
3. On Linux or macOS, make the binary executable with `chmod +x cortex`.
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

Both scripts create a PyInstaller one-file executable and a verified license
inventory under `dist/`. The binary bundles ChromaDB, FastEmbed, ONNX Runtime,
Tokenizers and the Cortex modules, so it is substantially larger than a simple
Python CLI. The model files themselves are not bundled.

## Release workflow

Pushing a `v*` tag starts `.github/workflows/release.yml`. It builds on Windows
x64, macOS arm64 and Linux x64, smoke-tests the CLI and server imports, and
attaches three ZIP archives with their licenses to the GitHub Release.
`workflow_dispatch` can build the same artifacts without publishing a release.
The Windows leg also compiles `Cortex-Setup.exe` with Inno Setup and attaches it
to the release. This Windows version is unsigned; users must compare its digest
with `SHA256SUMS` before running it. The publish job generates checksums for every
artifact and creates a GitHub build provenance attestation before publishing the
release once.

The release job must never publish an archive from a failed platform build,
license inventory, or smoke-test.
