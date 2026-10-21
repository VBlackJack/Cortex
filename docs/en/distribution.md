# Standalone distribution

[Français](../fr/distribution.md) | **English**

[Back to table of contents](index.md)

Cortex can be delivered as a standalone ZIP archive. It unpacks to a `cortex/`
folder holding one executable that provides both the CLI and the MCP stdio
server, its `_internal` runtime folder, and the exact licenses for its embedded
dependencies. The executable embeds CPython 3.13 and does not require Python on
the target machine.

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
   or deleted. Keep the `cortex/` folder whole: the executable needs the
   `_internal` folder beside it, and the `licenses` folder ships with it.
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

Both scripts create a PyInstaller directory build, `dist/cortex/` with the
executable beside `_internal/`, and a verified license inventory under
`dist/licenses/`. The directory bundles ChromaDB, FastEmbed, ONNX Runtime,
Tokenizers and the Cortex modules, so it is substantially larger than a simple
Python CLI. The model files themselves are not bundled. Because nothing is
unpacked at start-up, the executable starts in one to three seconds.

## Release workflow

Pushing a `v*` tag starts `.github/workflows/release.yml`. `workflow_dispatch`
builds the same artifacts for a candidate, against a chosen Companion ref,
without publishing anything. The jobs run in this order, and each one needs the
previous one to succeed:

1. **Retrieval gate.** The bilingual retrieval benchmark from
   `.github/workflows/retrieval.yml` must pass first.
2. **Verify.** On CPython 3.13: the tag must equal `_version.py` and the version
   in `server.json`; then `ruff`, `mypy`, the full `pytest` suite and
   `pip-audit` on the three hash-locked trees (`requirements.lock`,
   `requirements-dev.lock`, `requirements-model.lock`) with the same assessed
   ignore list as CI.
3. **Build.** Three portable builds, Windows x64, macOS arm64 and Linux x64,
   each with the frozen CPython 3.13 interpreter. PyInstaller produces a
   directory (`cortex` or `cortex.exe` beside `_internal`); the build checks the
   runner architecture, generates and verifies the license inventory, smoke-tests
   the CLI and the server imports, and archives the directory inside a single
   `cortex/` folder with its licenses.
4. **Windows installer.** The Windows leg verifies and publishes the paired
   Cortex Companion (the Companion tag of the same name) and the pinned
   Confluence console converter, prepares the embedded model payload and
   verifies it against `models/manifest.json`, then compiles the combined
   `Cortex-Setup.exe` with Inno Setup. An offline smoke test installs it with
   Hugging Face offline, then runs a synchronization, a search and a JSON search
   on the installed models.
5. **Signing.** When the `WINDOWS_CERT_PFX_BASE64` and `WINDOWS_CERT_PASSWORD`
   secrets exist, `cortex.exe`, the converter, `CortexCompanion.exe`, the
   embedded uninstaller and `Cortex-Setup.exe` are signed with Authenticode, and
   the certificate is deleted at the end of the job whatever the outcome.
   Without the secrets the build continues unsigned; users must then compare the
   installer digest with `SHA256SUMS` before running it.
6. **Python distribution.** The wheel is built with reproducible metadata,
   checked with `twine`, installed over `requirements.lock` in a clean virtual
   environment and smoke-tested.
7. **PyPI and MCP Registry.** The wheel is published to PyPI through trusted
   publishing (skipped when that exact version is already there), then the
   committed `server.json` is published to the MCP Registry.
8. **GitHub Release.** The job refuses anything but the exact five-asset set:
   `Cortex-Setup.exe`, `cortex-windows-x64.zip`, `cortex-macos-arm64.zip`,
   `cortex-linux-x64.zip` and the `cortex_local_rag` wheel. It then writes
   `SHA256SUMS`, creates a build provenance attestation for every asset and
   publishes the release once, without GitHub-generated notes.

The release job must never publish an archive from a failed platform build,
license inventory, or smoke-test.

CI tests every push on Python 3.11, 3.12 and 3.13. Its dependency scan also runs
every Monday, so a new advisory against a locked dependency surfaces between
releases instead of at the next tag.

The build chain itself also runs on every push, on Windows: the `build-chain`
job of `.github/workflows/ci.yml` freezes the executable, generates and checks
the license inventory, stages the portable archive, then builds, checks and
smoke-tests the wheel, with the same commands as the release (a test keeps them
identical). A drift in those steps therefore fails on the commit that causes it,
not after a tag. The release only adds the payload assembly (Companion,
converter, embedded models) and the installer, signing, the installed and
offline smoke tests, and publication.
